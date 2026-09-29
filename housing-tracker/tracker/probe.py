"""Import the earlier bounded probe, always as partial/unverified geography."""
import csv
import gzip
import hashlib
import json
import re
from pathlib import Path

from tracker.storage import import_snapshot


def next_data(html):
    match = re.search(r'<script\b[^>]*\bid=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.S)
    if not match:
        raise ValueError("Missing __NEXT_DATA__; source may have changed")
    return json.loads(match.group(1))


def detail_year(html, property_id):
    payload = next_data(html)["props"]["pageProps"]["componentProps"]["gdpClientCache"]
    cache = json.loads(payload) if isinstance(payload, str) else payload
    for entry in cache.values():
        prop = entry.get("property") or {}
        if str(prop.get("zpid")) != str(property_id):
            continue
        if prop.get("yearBuilt") is not None:
            return prop["yearBuilt"], "property.yearBuilt"
        if (prop.get("resoFacts") or {}).get("yearBuilt") is not None:
            return prop["resoFacts"]["yearBuilt"], "property.resoFacts.yearBuilt"
    return None, ""


def import_probe(db_path, directory):
    folder = Path(directory)
    summary = json.loads((folder / "houses-summary.json").read_text(encoding="utf-8-sig"))
    if summary.get("school", {}).get("id") != 102507:
        raise ValueError("This importer supports the verified North Gwinnett probe only")
    if summary.get("http_status") != 200 or summary.get("filter_mismatches") or summary.get("row_violations"):
        raise ValueError("Probe validation failed; no observations imported")
    with (folder / "houses-first-page.csv").open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    if len(rows) != summary["extracted_first_page"]:
        raise ValueError("CSV row count does not match the saved probe summary")
    search_path = folder / "houses-first-page.html"
    by_id = {}
    if search_path.exists():
        state = next_data(search_path.read_text(encoding="utf-8-sig"))["props"]["pageProps"]["searchPageState"]
        by_id = {str(x.get("zpid")): x for x in state["cat1"]["searchResults"]["listResults"]}
    details = {}
    paths = list(folder.glob("detail-*.html"))
    if (folder / "sample-detail.html").exists():
        paths.append(folder / "sample-detail.html")
    for path in paths:
        html = path.read_text(encoding="utf-8-sig")
        for row in rows:
            year, source = detail_year(html, row["zpid"])
            if year is not None:
                details[row["zpid"]] = (year, source)
    listings = []
    for row in rows:
        record = dict(row)
        pid = row["zpid"]
        if row["observed_at_utc"] != summary["observed_at_utc"]:
            raise ValueError("CSV and summary observation times differ")
        record.update(property_id=f"zillow:{pid}", episode_id=f"zillow:{pid}:unknown")
        record["raw_status"] = record["status"]
        if row["status"] == "New construction":
            record["status"] = by_id.get(pid, {}).get("hdpData", {}).get("homeInfo", {}).get("homeStatus", "")
        if pid in details:
            record["year_built"], record["year_source"] = details[pid]
        record["evidence"] = "Saved local first-page probe; school assignment unverified; detail years enriched offline"
        listings.append(record)
    # Content-addressed originals allow offline parsing fixes. No bulk data enters Git.
    originals = [folder / "houses-summary.json", folder / "houses-first-page.csv", *paths]
    if search_path.exists():
        originals.append(search_path)
    archive = Path(db_path).parent / "raw"
    archive.mkdir(parents=True, exist_ok=True)
    manifest = []
    for path in originals:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        target = archive / f"{digest}.gz"
        if not target.exists():
            target.write_bytes(gzip.compress(raw, mtime=0))
        manifest.append({"name": path.name, "sha256": digest, "bytes": len(raw)})
    snapshot = {
        "schema_version": 1, "dataset": "observed", "school": "north_gwinnett",
        "scope": "probe_houses_3bed_2bath_400k_700k_first_page_v1",
        "observed_at": summary["observed_at_utc"], "quality": "partial",
        "reported_count": summary["total_results_reported"], "source": "Zillow saved local HTTP probe",
        "boundary_version": "unverified-school-proximity", "coverage": {
            "all_pages": False, "all_prices": False, "official_zone_verified": False, "query_validated": True},
        "note": "Only first page, USD 400k-700k; official school assignment unverified. Not market inventory.",
        "evidence_files": manifest, "listings": listings,
    }
    return import_snapshot(db_path, snapshot)
