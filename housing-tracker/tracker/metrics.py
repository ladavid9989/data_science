"""Historical filters use the facts on each observation date."""
from __future__ import annotations

import pandas as pd

from tracker.storage import SCOPE, SOURCE_SCOPE

INVENTORY = ["active", "under_contract", "pending"]


def canonical_runs(runs, complete_only=True):
    data = runs.copy()
    if complete_only:
        data = data[((data.quality == "complete") & (data.scope == SCOPE)) |
                    (data.quality.eq("source_complete") & data.scope.str.startswith(SOURCE_SCOPE + ":"))]
        # Never compare different geographic/query versions in one historical series.
        latest = data.sort_values("observed_at").drop_duplicates("school", keep="last")
        data = data.merge(latest[["school", "scope", "boundary_version"]],
                          on=["school", "scope", "boundary_version"])
    data = data.assign(_priority=data.quality.map({"failed": 0, "partial": 1, "source_complete": 2, "complete": 3}))
    return data.sort_values(["_priority", "observed_at", "run_id"]).drop_duplicates(
        ["school", "market_date"], keep="last").drop(columns="_priority")


def joined(runs, observations, complete_only=True):
    selected = canonical_runs(runs, complete_only)
    return observations.merge(selected, on="run_id", how="inner")


def filter_rows(data, price=(400000, 700000), years=(1600, 2100), include_unknown=True,
                beds=3, baths=2, statuses=None):
    data = data.copy()
    mask = (data.property_type == "SINGLE_FAMILY") & (data.bedrooms >= beds) & (data.bathrooms >= baths)
    if price is not None:
        mask &= data.price.between(*price, inclusive="both")
    mask &= data.year_built.between(*years, inclusive="both") | (include_unknown & data.year_built.isna())
    if statuses is not None:
        mask &= data.status.isin(statuses)
    return data.loc[mask].copy()


def daily_metrics(runs, observations, schools, start, end, **filters):
    valid = canonical_runs(runs)
    all_rows = joined(runs, observations)
    selected = filter_rows(all_rows, **filters)
    records = []
    for school in schools:
        for stamp in pd.date_range(start, end):
            day = stamp.date().isoformat()
            run = valid[(valid.school == school) & (valid.market_date == day)]
            record = {"date": day, "school": school, "active": None, "contract": None,
                      "median_price": None, "year_coverage": None, "matched": None,
                      "complete": not run.empty}
            if not run.empty:
                rows = selected[(selected.school == school) & (selected.market_date == day)]
                rows = rows[rows.in_inventory.eq(1)]
                active = rows[rows.status == "active"]
                inventory = rows[rows.status.isin(INVENTORY)]
                positive = active.loc[active.price > 0, "price"]
                record.update(active=len(active), contract=int(rows.status.isin(["under_contract", "pending"]).sum()),
                              matched=len(inventory), median_price=positive.median() if len(positive) else None,
                              year_coverage=inventory.year_built.notna().mean() * 100 if len(inventory) else None)
            records.append(record)
    return pd.DataFrame(records)


def property_history(runs, observations, property_id, school):
    valid = canonical_runs(runs[runs.school == school], complete_only=False)
    selected = observations[observations.property_id == property_id]
    actual = selected.merge(valid, on="run_id")
    if actual.empty:
        return actual
    first = actual.market_date.min()
    dates = pd.DataFrame({"market_date": pd.date_range(first, valid.market_date.max()).strftime("%Y-%m-%d")})
    frame = dates.merge(valid, on="market_date", how="left").merge(selected, on="run_id", how="left")
    frame["availability"] = "관측됨"
    successful = frame.quality.isin(["complete", "source_complete"])
    frame.loc[frame.property_id.isna() & successful, "availability"] = "검색에서 미관측 · 판매 여부 미확인"
    frame.loc[frame.property_id.isna() & ~successful, "availability"] = "수집 누락 / 불완전"
    frame.loc[frame.property_id.notna() & ~successful, "availability"] = "부분 수집에서 관측"
    return frame


def changes_between(previous, current):
    """Only comparable identified episodes; unknown episode IDs cannot prove a price change."""
    both = previous.merge(current, on=["property_id", "episode_id"], suffixes=("_before", "_after"))
    both = both[~both.episode_id.str.endswith(":unknown")].copy()
    both["price_change"] = both.price_after - both.price_before
    return both[both.price_change.ne(0) & both.price_change.notna()]
