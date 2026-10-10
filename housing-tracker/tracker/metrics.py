"""Historical filters use the facts on each observation date."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from tracker.storage import SCOPE, SOURCE_SCOPE, BAND_SCOPE

INVENTORY = ["active", "under_contract", "pending"]


def canonical_runs(runs, complete_only=True, *, daily=True):
    data = runs.copy()
    if complete_only:
        recognized = data[data.scope.eq(SCOPE) | data.scope.str.startswith((SOURCE_SCOPE + ':', BAND_SCOPE + ':'))]
        # A newly restricted collection cannot inherit an older all-price market series.
        latest_scope = recognized.sort_values('observed_at').drop_duplicates('school', keep='last')
        data = data.merge(latest_scope[['school', 'scope', 'boundary_version']], on=['school', 'scope', 'boundary_version'])
        data = data[((data.quality == "complete") & (data.scope == SCOPE)) |
                    (data.quality.eq("source_complete") & data.scope.str.startswith((SOURCE_SCOPE + ":", BAND_SCOPE + ":")))]
        # Never compare different geographic/query versions in one historical series.
        latest = data.sort_values("observed_at").drop_duplicates("school", keep="last")
        data = data.merge(latest[["school", "scope", "boundary_version"]],
                          on=["school", "scope", "boundary_version"])
    data = data.assign(_priority=data.quality.map({"failed": 0, "partial": 1, "source_complete": 2, "complete": 3}))
    data = data.sort_values(["_priority", "observed_at", "run_id"])
    if daily:
        data = data.drop_duplicates(["school", "market_date"], keep="last")
    return data.drop(columns="_priority")


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
    runs = runs[runs.market_date.le(str(end))]
    valid = canonical_runs(runs)
    all_rows = joined(runs, observations)
    selected = filter_rows(all_rows, **filters)
    records = []
    for school in schools:
        for stamp in pd.date_range(start, end):
            day = stamp.date().isoformat()
            run = valid[(valid.school == school) & (valid.market_date == day)]
            record = {"date": day, "school": school, "active": None, "contract": None,
                      "median_price": None, "mean_price": None, "year_coverage": None, "matched": None,
                      "complete": not run.empty}
            if not run.empty:
                rows = selected[(selected.school == school) & (selected.market_date == day)]
                rows = rows[rows.in_inventory.eq(1)]
                active = rows[rows.status == "active"]
                inventory = rows[rows.status.isin(INVENTORY)]
                positive = active.loc[active.price > 0, "price"]
                record.update(active=len(active), contract=int(rows.status.isin(["under_contract", "pending"]).sum()),
                              matched=len(inventory), median_price=positive.median() if len(positive) else None,
                              mean_price=positive.mean() if len(positive) else None,
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
    """Observed property-price differences, with explicit relistings excluded."""
    keys = ['property_id'] + (['school'] if 'school' in previous and 'school' in current else [])
    both = previous.merge(current, on=keys, suffixes=("_before", "_after"))
    return _price_differences(both)


def _price_differences(both, *, include_unchanged=False):
    known = (both.episode_id_before.notna() & both.episode_id_after.notna() &
             ~both.episode_id_before.str.endswith(':unknown', na=True) &
             ~both.episode_id_after.str.endswith(':unknown', na=True))
    both = both[~known | both.episode_id_before.eq(both.episode_id_after)].copy()
    both['comparison_basis'] = '같은 매물 ID의 관측 호가 비교'
    both.loc[known.reindex(both.index), 'comparison_basis'] = '같은 등록 건의 관측 호가 비교'
    both["price_change"] = both.price_after - both.price_before
    both['price_change_percent'] = both.price_change / both.price_before * 100
    valid = both.price_before.gt(0) & both.price_after.gt(0) & both.price_change.notna()
    return both[valid & (include_unchanged | both.price_change.ne(0))]


def rolling_market_metrics(runs, observations, schools, start, end, **filters):
    """Seven-calendar-day matched active cohorts; no carried-forward price baselines.

    Each property has one weight, including unchanged prices. Cut incidence and
    cut size describe observed transitions of that same endpoint cohort, not
    historical source badges. An aggregate row deduplicates overlapping schools.
    """
    runs = runs[runs.market_date.le(str(end)) & runs.school.isin(schools)]
    daily = canonical_runs(runs)
    rows = observations.merge(daily, on='run_id')
    rows['_stamp'] = pd.to_datetime(rows.price_observed_at, utc=True, errors='coerce', format='mixed')
    rows['_price_day'] = rows['_stamp'].dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d')
    # A year-enrichment snapshot is not a new observation of price or inventory.
    stale = set(map(tuple, rows.loc[rows.in_inventory.eq(1) & rows.status.isin(INVENTORY) &
        rows._price_day.ne(rows.market_date), ['school', 'market_date']].values))
    complete = set(map(tuple, daily[['school', 'market_date']].values)) - stale
    eligible = filter_rows(rows, **filters)
    eligible = eligible[eligible.status.eq('active') & eligible.in_inventory.eq(1)]
    transitions = price_change_history(runs, observations, pd.Timestamp(start).date() - timedelta(days=6), end, **filters)
    all_rows = observations.merge(canonical_runs(runs, daily=False), on='run_id')
    all_rows['_stamp'] = pd.to_datetime(all_rows.price_observed_at, utc=True, errors='coerce', format='mixed')
    groups = [(school, [school]) for school in schools]
    if len(schools) > 1:
        groups.append(('__all__', schools))
    records = []
    for stamp in pd.date_range(start, end):
        day = stamp.date().isoformat()
        baseline = (stamp.date() - timedelta(days=7)).isoformat()
        days = pd.date_range(baseline, day).strftime('%Y-%m-%d')
        for name, members in groups:
            before = eligible[eligible.school.isin(members) & eligible.market_date.eq(baseline)]
            after = eligible[eligible.school.isin(members) & eligible.market_date.eq(day)]
            ready = all((school, date) in complete for school in members for date in (baseline, day))
            covered_days = sum(all((school, date) in complete for school in members) for date in days)
            record = dict(date=day, school=name, baseline_date=baseline, weekly_ready=ready,
                          observed_days=covered_days, active=after.property_id.nunique(), active_change_7d=None,
                          comparable_count=0, comparison_coverage=None, mean_change_7d=None,
                          cut_count=None, cut_share_7d=None, cut_event_count=None, median_cut_percent=None)
            if ready:
                record['active_change_7d'] = after.property_id.nunique() - before.property_id.nunique()
                pairs = _price_differences(before.merge(after, on=['school', 'property_id'],
                    suffixes=('_before', '_after')), include_unchanged=True)
                # Unknown endpoints must not conceal a known relisting inside the window.
                period = all_rows[all_rows.school.isin(members) & all_rows.market_date.between(baseline, day)]
                known = period[period.episode_id.notna() & ~period.episode_id.str.endswith(':unknown', na=True)]
                relisted = known.groupby(['school', 'property_id']).episode_id.nunique()
                blocked = set(relisted[relisted.gt(1)].index)
                pairs = pairs[[key not in blocked for key in zip(pairs.school, pairs.property_id)]] if len(pairs) else pairs
                pairs = pairs.sort_values(['_stamp_after', '_stamp_before', 'school']).drop_duplicates('property_id', keep='last')
                n = len(pairs)
                record.update(comparable_count=n,
                              comparison_coverage=n / record['active'] * 100 if record['active'] else None,
                              mean_change_7d=pairs.price_change_percent.mean() if n else None)
                if n:
                    cuts = transitions[transitions.school.isin(members) & transitions.price_change.lt(0)].merge(
                        pairs[['school', 'property_id', '_stamp_before', '_stamp_after']].rename(
                            columns={'_stamp_before': '_baseline', '_stamp_after': '_endpoint'}),
                        on=['school', 'property_id'])
                    cuts = cuts[cuts._stamp_before.ge(cuts._baseline) & cuts._stamp_after.le(cuts._endpoint)]
                    record.update(cut_count=cuts.property_id.nunique(), cut_share_7d=cuts.property_id.nunique() / n * 100,
                                  cut_event_count=len(cuts),
                                  median_cut_percent=-cuts.price_change_percent.median() if len(cuts) else None)
            records.append(record)
    return pd.DataFrame(records)


def price_change_history(runs, observations, start, end, **filters):
    """Each observed price transition, including intraday moves and a pre-window baseline."""
    start, end = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    valid = canonical_runs(runs[runs.market_date.le(end.isoformat())], daily=False)
    rows = observations.merge(valid, on='run_id', how='inner')
    # Enrichment snapshots may be new, but their price timestamp remains unchanged.
    rows['_stamp'] = pd.to_datetime(rows.price_observed_at, utc=True, errors='coerce', format='mixed')
    rows = rows[rows['_stamp'].notna() & rows.price.gt(0)].copy()
    rows = rows[rows['_stamp'].dt.tz_convert('America/New_York').dt.date.le(end)]
    keys = ['school', 'property_id']
    rows = rows.sort_values(keys + ['_stamp', 'observed_at', 'run_id']).drop_duplicates(
        keys + ['_stamp'], keep='last')
    before = rows.groupby(keys, sort=False).shift(1)
    columns = [column for column in rows.columns if column not in keys]
    paired = pd.concat([rows[keys], before[columns].add_suffix('_before'),
                        rows[columns].add_suffix('_after')], axis=1)
    changes = _price_differences(paired)
    changes['change_date'] = changes['_stamp_after'].dt.tz_convert('America/New_York').dt.date
    # Apply the viewer's filters to the facts at the time of the change, not today's inventory.
    eligible = filter_rows(rows, **filters).index
    return changes[changes.change_date.between(start, end) & changes.index.isin(eligible)].sort_values(
        ['_stamp_after', 'price_change', 'school', 'property_id'], ascending=[False, True, True, True])


def rank_price_cuts(current, history, order='percent'):
    """Use explicit source cuts or observed reductions in the same known listing episode."""
    result = current.copy()
    result['cut_amount'] = pd.to_numeric(result.get('price_cut'), errors='coerce')
    result['cut_basis'] = result.get('cut_source', pd.Series(index=result.index, dtype=str))
    result['cut_date'] = result.get('price_cut_date', pd.Series(index=result.index, dtype=str))
    for index, row in result.iterrows():
        if not pd.isna(row.cut_amount) and row.cut_amount > 0:
            continue
        if str(row.episode_id).endswith(':unknown') or history.empty:
            continue
        prior = history[(history.property_id == row.property_id) & (history.episode_id == row.episode_id) &
                        (history.school == row.school) & (history.observed_at < row.observed_at)]
        prior = prior.sort_values('observed_at')
        if not prior.empty and prior.iloc[-1].price > row.price:
            result.at[index, 'cut_amount'] = prior.iloc[-1].price - row.price
            result.at[index, 'cut_basis'] = '동일 등록 건 관측 비교'
            result.at[index, 'cut_date'] = row.market_date
    result['cut_percent'] = result.cut_amount / (result.price + result.cut_amount) * 100
    key = {'percent': 'cut_percent', 'amount': 'cut_amount', 'price': 'price'}[order]
    return result.sort_values([key, 'price', 'property_id'], ascending=[order == 'price', True, True], na_position='last')
