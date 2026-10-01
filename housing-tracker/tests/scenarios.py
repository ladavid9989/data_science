"""Isolated test fixtures; never imported by the application or collector."""
from datetime import date, datetime, time, timedelta, timezone
from random import Random

from tracker.storage import SCHOOLS, SCOPE, import_snapshot

DEMO_VERSION = "synthetic-v1"


def snapshots():
    for school_index, school in enumerate(SCHOOLS):
        rng = Random(340 + school_index)
        houses = []
        for i in range(42):
            houses.append({
                "property_id": f"DEMO-{school}-{i:03}", "episode_id": f"DEMO-{school}-{i:03}:1",
                "address": f"DEMO · {'Cedar' if school_index == 0 else 'Willow'} House {i + 1:02}",
                "price": rng.randrange(36, 105) * 10000, "bedrooms": rng.choice([3, 4, 4, 5]),
                "bathrooms": rng.choice([2, 2.5, 3, 4]), "square_feet": rng.randrange(1800, 4300, 100),
                "year_built": None if i % 7 == 0 else rng.choice([1988, 1994, 1998, 2000, 2005, 2012, 2020, 2025]),
                "property_type": "SINGLE_FAMILY", "status": "active", "url": "",
                "latitude": (34.06 if school_index == 0 else 34.01) + rng.uniform(-0.018, 0.018),
                "longitude": (-84.065 if school_index == 0 else -84.19) + rng.uniform(-0.018, 0.018),
                "year_source": "Fictional scenario", "evidence": "Fictional scenario; not a real property",
            })
        for offset in range(30):
            day = date(2026, 8, 31) + timedelta(days=offset)
            quality = "failed" if (school_index == 0 and offset == 11) else "partial" if (school_index == 1 and offset == 17) else "complete"
            rows = []
            for i, base in enumerate(houses):
                if (i >= 33 and offset < (i - 32) * 3) or (i == 2 and offset >= 17):
                    continue
                row = dict(base)
                if i == 0:
                    row.update(price=710000 if offset < 8 else 690000, year_built=2000)
                elif i % 5 == 0 and offset >= 8 + i % 12:
                    row["price"] -= 15000
                if i in {1, 5, 9, 13} and offset >= 10 + i % 6:
                    row["status"] = "under_contract" if offset < 18 else "pending"
                if i == 1 and offset >= 22:
                    row.update(status="sold", sold_date="2026-09-22")
                    if offset >= 27:
                        row["sold_price"] = base["price"] - 10000
                if i == 4 and 15 <= offset < 24:
                    row["status"] = "withdrawn"
                if i == 4 and offset >= 24:
                    row.update(episode_id=f"{base['property_id']}:2", price=base["price"] - 25000)
                rows.append(row)
            expected = len(rows)
            if quality == "failed":
                rows = []
            elif quality == "partial":
                rows = rows[:9]
            yield {
                "schema_version": 1, "dataset": "observed", "school": school, "scope": SCOPE,
                "observed_at": datetime.combine(day, time(10, 17), tzinfo=timezone.utc).isoformat(),
                "quality": quality, "reported_count": expected, "expected_unique_count": expected,
                "boundary_version": "synthetic-boundary-not-an-assignment-map",
                "coverage": {"all_pages": quality == "complete", "all_prices": True,
                             "official_zone_verified": True, "query_validated": True},
                "source": DEMO_VERSION,
                "note": "FICTIONAL demonstration. Coordinates, counts, prices and assignments are synthetic. "
                        + ("Simulated collection failure." if quality == "failed" else
                           "Simulated incomplete pagination." if quality == "partial" else ""),
                "listings": rows,
            }


def seed(path):
    return sum(import_snapshot(path, snapshot)[1] for snapshot in snapshots())
