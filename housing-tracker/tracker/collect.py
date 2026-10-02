"""Bounded daily collection. Access challenges stop requests; saved facts are replayable."""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tracker.probe import next_data
from tracker.storage import SOURCE_SCOPE, import_snapshot, normalize_status, read_frames

SOURCES = {
    "north_gwinnett": (102507, "north-gwinnett-high-school",
        "https://gis3.gwinnettcounty.com/mapvis/rest/services/GISDataBrowser/GC_Main/MapServer/26",
        "HIGH='North Gwinnett HS'"),
    "johns_creek": (164559, "johns-creek-high-school",
        "https://www4.fultonschools.org/arcgisserver/rest/services/AttendanceZones/CombinedAttendanceZones/FeatureServer/22",
        "name_1633352979610 LIKE '%Johns Creek%' AND zonetype='High School Attendance Zone'"),
}


class AccessBlocked(RuntimeError):
    def __init__(self, message, wait_seconds=3600):
        super().__init__(message)
        self.wait_seconds = wait_seconds


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    encoded = gzip.compress(body, mtime=0)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open('wb') as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def read_json(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


class Client:
    def __init__(self, raw_dir, delay=5, budget=100):
        self.raw_dir = Path(raw_dir)
        self.delay, self.budget, self.count, self.last = delay, budget, 0, 0
        self.evidence = []

    def get(self, url):
        if self.count >= self.budget:
            raise RuntimeError("Daily request budget exhausted")
        time.sleep(max(0, self.delay - (time.monotonic() - self.last)))
        self.count += 1
        self.last = time.monotonic()
        request = urllib.request.Request(url, headers={"User-Agent": "Schoolside/0.2"})
        try:
            with urllib.request.urlopen(request, timeout=30) as reply:
                body = reply.read(12_000_001)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 429):
                wait = 3600 if exc.code == 429 else 86400
                retry = exc.headers.get("Retry-After", "")
                if retry:
                    try:
                        wait = max(wait, int(retry))
                    except ValueError:
                        try:
                            wait = max(wait, int((parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds()))
                        except (ValueError, TypeError):
                            pass
                raise AccessBlocked(f"HTTP {exc.code}: source access stopped", wait) from exc
            raise
        if len(body) > 12_000_000:
            raise RuntimeError("Unexpected response size")
        text = body.decode("utf-8-sig")
        if re.search(r"px-captcha|verify you are human|Access to this page has been denied", text, re.I):
            raise AccessBlocked("Source challenge: stopped without bypass")
        digest = hashlib.sha256(body).hexdigest()
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        path = self.raw_dir / (digest + ".gz")
        if not path.exists():
            temporary = path.with_suffix('.tmp')
            with temporary.open('wb') as handle:
                handle.write(gzip.compress(body, mtime=0))
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        self.evidence.append({"url": url, "sha256": digest, "observed_at": datetime.now(timezone.utc).isoformat()})
        return text


def in_ring(x, y, ring):
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            inside = not inside
    return inside


def contains(geojson, lon, lat):
    if lon is None or lat is None:
        return None
    for feature in geojson["features"]:
        geometry = feature["geometry"]
        if geometry["type"] not in ("Polygon", "MultiPolygon"):
            raise ValueError("Unsupported zone geometry")
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        for polygon in polygons:
            if in_ring(lon, lat, polygon[0]) and not any(in_ring(lon, lat, hole) for hole in polygon[1:]):
                return True
    return False


def zone_for(school, archive, client):
    cache = archive / "state" / (school + "-zone.json.gz")
    if cache.exists():
        value = read_json(cache)
        if datetime.now(timezone.utc) - datetime.fromisoformat(value["fetched_at"]) < timedelta(days=30):
            return value
    _, _, endpoint, clause = SOURCES[school]
    url = endpoint + "/query?" + urllib.parse.urlencode({"where": clause, "outFields": "*", "f": "geojson", "outSR": 4326})
    data = json.loads(client.get(url))
    if not data.get("features") or data.get("exceededTransferLimit"):
        raise ValueError("School boundary response incomplete")
    normalized = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": f["geometry"]} for f in data["features"]]}
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()[:16]
    value = {"fetched_at": datetime.now(timezone.utc).isoformat(), "source": url,
             "version": school + "-" + digest, "geometry": normalized}
    write_json(cache, value)
    return value


def filters(price_min=None, price_max=None):
    result = {"beds": {"min": 3}, "baths": {"min": 2}, "price": {"min": price_min, "max": price_max},
              "isSingleFamily": {"value": True}, "isForRent": {"value": False},
              "isRecentlySold": {"value": False}, "isPendingListingsSelected": {"value": True},
              "isAcceptingBackupOffersSelected": {"value": True},
              "isComingSoon": {"value": False}, "isComingSoonStatus": {"value": False}}
    for name in ("isTownhouse", "isCondo", "isApartmentOrCondo", "isMultiFamily", "isApartment", "isManufactured", "isLotLand"):
        result[name] = {"value": False}
    return result


def validate_page(state, school_id, requested, defaults, page):
    query = state["queryState"]
    if query.get("schoolId") != school_id:
        raise ValueError("Returned school does not match")
    if int(query.get("pagination", {}).get("currentPage", 1)) != page:
        raise ValueError("Pagination did not advance")
    effective = {**defaults, **state.get("defaultFilterState", {}), **query.get("filterState", {})}
    for key, parts in requested.items():
        for part, value in parts.items():
            if effective.get(key, {}).get(part) != value:
                raise ValueError(f"Returned filter mismatch: {key}.{part}")


def search_row(item):
    info = item.get("hdpData", {}).get("homeInfo", {})
    status = item.get("statusText", "")
    normalized = normalize_status(status)
    if normalized == "off_market_unknown":
        normalized = normalize_status(info.get("homeStatus"))
    pid = "zillow:" + str(item["zpid"])
    return dict(property_id=pid, episode_id=pid + ":unknown", address=item.get("address", pid),
                price=item.get("unformattedPrice"), bedrooms=item.get("beds"), bathrooms=item.get("baths"),
                square_feet=item.get("area"), year_built=info.get("yearBuilt"), property_type=info.get("homeType", "UNKNOWN"),
                status=normalized, raw_status=status, latitude=item.get("latLong", {}).get("latitude"),
                longitude=item.get("latLong", {}).get("longitude"),
                url=urllib.parse.urljoin("https://www.zillow.com", item.get("detailUrl", "")), in_inventory=True)


def detail_property(html, pid):
    payload = next_data(html)["props"]["pageProps"]["componentProps"]["gdpClientCache"]
    cache = json.loads(payload) if isinstance(payload, str) else payload
    for entry in cache.values():
        prop = entry.get("property") or {}
        if str(prop.get("zpid")) == pid.split(":", 1)[-1]:
            return prop
    raise ValueError("Detail property identity mismatch")


def enrich_school(db, school, client, snapshot, rows, zone, cache, detail_limit):
    stamp = snapshot["observed_at"]
    old_runs, old_rows = read_frames(db, "observed")
    old_rows = old_rows.merge(old_runs[["run_id", "school", "observed_at"]], on="run_id")
    prior = old_rows[old_rows.school.eq(school)].sort_values("observed_at").drop_duplicates("property_id", keep="last")
    prior_map = {r["property_id"]: r for r in prior.to_dict("records")}
    # Reuse earlier verified years without changing older snapshots.
    known_years = old_rows[old_rows.school.eq(school) & old_rows.year_built.notna()].sort_values("observed_at").drop_duplicates("property_id", keep="last")
    for record in known_years.to_dict("records"):
        if record["property_id"] in rows and rows[record["property_id"]].get("year_built") is None:
            rows[record["property_id"]].update(year_built=int(record["year_built"]), year_source=record["year_source"])
    for pid, row in rows.items():
        saved = cache.get(pid, {})
        if saved.get("year_built"):
            row.update(year_built=saved["year_built"], year_source=saved.get("year_source", "cached detail"))
        if saved.get("episode_id"):
            row["episode_id"] = saved["episode_id"]
    candidates = list(rows)
    missing = [pid for pid in prior_map if pid not in rows and prior_map[pid]["status"] != "sold"]
    candidates += missing
    def priority(pid):
        saved = cache.get(pid, {})
        row = rows.get(pid, {})
        # A missing/pending listing is checked first, then unseen years, then stale detail metadata.
        rank = 0 if pid in missing or row.get("status") in ("pending", "under_contract") else 1 if not row.get("year_built") else 2
        return rank, saved.get("checked_at", ""), pid
    candidates.sort(key=priority)
    attempted = 0
    for pid in candidates:
        saved = cache.get(pid, {})
        checked = datetime.fromisoformat(saved["checked_at"]) if saved.get("checked_at") else None
        wait_days = 1 if priority(pid)[0] <= 1 else 30
        if checked and datetime.now(timezone.utc) - checked < timedelta(days=wait_days):
            continue
        if attempted >= detail_limit:
            break
        attempted += 1
        row = rows.get(pid)
        url = (row or prior_map[pid]).get("url")
        if not url:
            continue
        cache.setdefault(pid, {})["checked_at"] = datetime.now(timezone.utc).isoformat()
        try:
            prop = detail_property(client.get(url), pid)
            year = prop.get("yearBuilt") or (prop.get("resoFacts") or {}).get("yearBuilt")
            if year:
                cache[pid].update(year_built=year, year_source="detail property / resoFacts.yearBuilt")
            if row is None:
                # Only explicit detail observations can follow a listing out of search.
                previous = prior_map[pid]
                row = {key: previous.get(key) for key in ("property_id", "episode_id", "address", "property_type", "url")}
                row.update(price=prop.get("price"), bedrooms=prop.get("bedrooms"), bathrooms=prop.get("bathrooms"),
                           square_feet=prop.get("livingArea"), status=prop.get("homeStatus"), raw_status=prop.get("homeStatus"),
                           latitude=prop.get("latitude"), longitude=prop.get("longitude"), in_inventory=False)
                rows[pid] = row
            if year:
                row.update(year_built=year, year_source=cache[pid]["year_source"])
            if not row.get("latitude") and pid not in missing:
                row.update(latitude=prop.get("latitude"), longitude=prop.get("longitude"))
                row["in_inventory"] = contains(zone["geometry"], row["longitude"], row["latitude"]) is True
            listing_id = (prop.get("attributionInfo") or {}).get("mlsId")
            listed = prop.get("datePostedString") or prop.get("datePosted")
            if listing_id and listed:
                row["episode_id"] = f"{pid}:mls:{listing_id}:{listed}"
                cache[pid]["episode_id"] = row["episode_id"]
            row["evidence"] = "Search and/or matching detail property observed at " + stamp
            # Do not attach an old lastSoldPrice to a current listing. Explicit dated sold events only.
            if normalize_status(prop.get("homeStatus")) == "sold":
                first_seen = old_rows.loc[old_rows.property_id.eq(pid), "observed_at"].min()
                for event in prop.get("priceHistory") or []:
                    if str(event.get("event", "")).lower() == "sold" and event.get("date") and isinstance(first_seen, str) and event["date"] >= first_seen[:10]:
                        row.update(status="sold", sold_price=event.get("price"), sold_date=event["date"],
                                   evidence="Explicit source sold event after tracker first observation")
                        break
        except AccessBlocked:
            raise
        except Exception as exc:
            cache[pid]["error"] = str(exc)[:200]
    snapshot["note"] += f" Detail checks: {attempted}; construction years are enriched incrementally."


def collect_school(db, archive, school, client, detail_limit=25):
    stamp = datetime.now(timezone.utc).isoformat()
    snapshot = dict(schema_version=1, dataset="observed", school=school, observed_at=stamp,
                    quality="failed", scope=SOURCE_SCOPE + ":unverified", source="Zillow public school search",
                    boundary_version="unverified", coverage={}, listings=[], note="")
    evidence_start = len(client.evidence)
    rows, errors, cache = {}, [], {}
    state_file = archive / "state" / (school + "-details.json.gz")
    if state_file.exists():
        cache = read_json(state_file)
    try:
        zone = zone_for(school, archive, client)
        snapshot["boundary_version"] = zone["version"]
        snapshot["scope"] = SOURCE_SCOPE + ":" + zone["version"]
        school_id, slug, _, _ = SOURCES[school]
        base = f"https://www.zillow.com/schools/{school_id}/{slug}/"
        seed = next_data(client.get(base))["props"]["pageProps"]["searchPageState"]
        query = copy.deepcopy(seed["queryState"])
        query.setdefault("filterState", {}).update(filters())
        total, pages, all_ids = None, 1, set()
        for page in range(1, 11):
            query["pagination"] = {"currentPage": page}
            url = base + (f"{page}_p/" if page > 1 else "") + "?searchQueryState=" + urllib.parse.quote(json.dumps(query, separators=(",", ":")))
            data = next_data(client.get(url))["props"]["pageProps"]["searchPageState"]
            validate_page(data, school_id, filters(), seed.get("defaultFilterState", {}), page)
            result = data["cat1"]
            count = int(result["searchList"]["totalResultCount"])
            if total is not None and count != total:
                raise ValueError("Inventory changed while paginating; partial snapshot retained")
            total, pages = count, max(1, int(result["searchList"]["totalPages"]))
            snapshot["reported_count"] = total
            if pages > 10:
                raise ValueError("Search exceeds the 10-page safety limit")
            for item in result["searchResults"]["listResults"]:
                if item.get("relaxed") or item.get("isHomeRec"):
                    continue
                row = search_row(item)
                if row["property_type"] != "SINGLE_FAMILY" or (row["bedrooms"] or 0) < 3 or (row["bathrooms"] or 0) < 2:
                    raise ValueError("Result violates requested house/bed/bath criteria")
                all_ids.add(row["property_id"])
                membership = contains(zone["geometry"], row["longitude"], row["latitude"])
                if membership is None:
                    errors.append("One or more properties have no mappable coordinates")
                    row.update(in_inventory=False, evidence="School search result with unresolved coordinates; excluded from mapped inventory")
                    rows[row["property_id"]] = row
                elif membership:
                    row["evidence"] = "Observed in school search; coordinate inside mapped attendance polygon"
                    rows[row["property_id"]] = row
            if page >= pages:
                break
        if len(all_ids) != total:
            raise ValueError(f"Pagination reconciliation: {len(all_ids)} unique / {total} reported")
        snapshot["coverage"] = dict(all_pages=True, all_prices=True, query_validated=True, official_zone_verified=False)
        snapshot["quality"] = "source_complete"
        mapped_count = sum(r["in_inventory"] for r in rows.values())
        snapshot["note"] = (f"All {pages} search pages; {total} source results, {mapped_count} with coordinates inside mapped polygon. "
                            "Zillow school search is not proven exhaustive for the attendance zone; boundary school year not independently verified.")

        enrich_school(db, school, client, snapshot, rows, zone, cache, detail_limit)
    except Exception as exc:
        errors.append(str(exc)[:250])
        if snapshot["quality"] != "source_complete":
            snapshot["quality"] = "partial" if rows else "failed"
        if isinstance(exc, AccessBlocked):
            snapshot["access_blocked"] = True
            pause_until = datetime.now(timezone.utc) + timedelta(seconds=exc.wait_seconds)
            write_json(archive / "state" / "access.json.gz", {"retry_after": pause_until.isoformat(), "reason": str(exc)})
    snapshot["listings"] = list(rows.values())
    snapshot["expected_unique_count"] = len(rows)
    snapshot["note"] += " " + "; ".join(dict.fromkeys(errors))
    snapshot["evidence_files"] = client.evidence[evidence_start:]
    write_json(state_file, cache)
    run_id, _ = import_snapshot(db, snapshot)
    destination = archive / "snapshots" / stamp[:10] / f"{school}-{run_id}.json.gz"
    write_json(destination, snapshot)
    return snapshot


def collect(db, archive, detail_limit=5):
    archive = Path(archive)
    policy = archive / "state" / "access.json.gz"
    if policy.exists():
        pause = read_json(policy)
        if datetime.now(timezone.utc) < datetime.fromisoformat(pause["retry_after"]):
            print("Source cooldown until " + pause["retry_after"], flush=True)
            return []
    client = Client(Path(db).parent / "raw", budget=2 * (detail_limit + 14))
    results = []
    # Publish both schools' inventory before spending any requests on enrichment.
    for school in SOURCES:
        snapshot = collect_school(db, archive, school, client, 0)
        results.append(snapshot)
        print(f"{school}: {snapshot['quality']}; {len(snapshot['listings'])} observations", flush=True)
        if snapshot.get("access_blocked"):
            return results
    for i, original in enumerate(results):
        if not detail_limit or original["quality"] != "source_complete":
            continue
        school = original["school"]
        snapshot = copy.deepcopy(original)
        snapshot["search_observed_at"] = original["observed_at"]
        snapshot["observed_at"] = datetime.now(timezone.utc).isoformat()
        rows = {r["property_id"]: r for r in snapshot["listings"]}
        state_file = archive / "state" / (school + "-details.json.gz")
        cache = read_json(state_file)
        zone = read_json(archive / "state" / (school + "-zone.json.gz"))
        start = len(client.evidence)
        try:
            enrich_school(db, school, client, snapshot, rows, zone, cache, detail_limit)
        except AccessBlocked as exc:
            snapshot["note"] += " " + str(exc)
            snapshot["access_blocked"] = True
            pause_until = datetime.now(timezone.utc) + timedelta(seconds=exc.wait_seconds)
            write_json(policy, {"retry_after": pause_until.isoformat(), "reason": str(exc)})
        except Exception as exc:
            snapshot["note"] += " Detail enrichment failed: " + str(exc)[:200]
        snapshot["evidence_files"] += client.evidence[start:]
        snapshot["listings"] = list(rows.values())
        snapshot["expected_unique_count"] = len(rows)
        write_json(state_file, cache)
        run_id, _ = import_snapshot(db, snapshot)
        write_json(archive / "snapshots" / snapshot["observed_at"][:10] / f"{school}-{run_id}.json.gz", snapshot)
        results[i] = snapshot
        if snapshot.get("access_blocked"):
            break
    return results
