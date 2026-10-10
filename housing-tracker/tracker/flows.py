"""Observed listing flows, distinct from unverified sales or original listing dates."""
from datetime import timedelta

import pandas as pd

from tracker.metrics import INVENTORY, canonical_runs, filter_rows

FLOW_REASONS = {
    'first_observed': '처음 관측 · 신규 등록 여부 미확인',
    'reappeared': '재관측', 'reactivated': '계약 진행 → 판매 중',
    'filter_entered': '필터·검색 범위 편입', 'to_contract': '계약 진행 / Pending 전환',
    'to_sold': '판매 완료 확인', 'withdrawn': '등록 철회 확인',
    'filter_left': '필터·검색 범위 이탈', 'unexplained_left': '검색에서 미관측 · 사유 미확인',
}


def listing_flows(runs, observations, schools, start, end, **filters):
    """Compare consecutive ET daily snapshots. First snapshots and gaps are not flows.

    In the all-school view compare the union of IDs, so moving between school
    search results is not counted as leaving and entering the combined market.
    """
    valid = canonical_runs(runs[runs.school.isin(schools) & runs.market_date.le(str(end))])
    rows = observations.merge(valid, on='run_id')
    rows['_stamp'] = pd.to_datetime(rows.price_observed_at, utc=True, errors='coerce', format='mixed')
    rows['_price_day'] = rows._stamp.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d')
    rows['_status_day'] = pd.to_datetime(rows.status_observed_at.fillna(rows.price_observed_at), utc=True,
        errors='coerce', format='mixed').dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d')
    stale = rows[rows.in_inventory.eq(1) & rows.status.isin(INVENTORY) & rows._price_day.ne(rows.market_date)]
    complete = set(map(tuple, valid[['school', 'market_date']].values)) - set(map(tuple, stale[['school', 'market_date']].values))
    eligible = filter_rows(rows, **filters)
    active = eligible[eligible.in_inventory.eq(1) & eligible.status.eq('active')]
    contracts = eligible[eligible.in_inventory.eq(1) & eligible.status.isin(['pending', 'under_contract'])]
    history = observations.merge(runs[runs.school.isin(schools) & runs.market_date.le(str(end)) & runs.quality.ne('failed')], on='run_id')
    groups = [(school, [school]) for school in schools]
    if len(schools) > 1:
        groups.append(('__all__', schools))
    records, events = [], []

    def by_id(frame):
        return frame.sort_values(['in_inventory', '_stamp', 'school']).drop_duplicates('property_id', keep='last').set_index('property_id')

    for stamp in pd.date_range(start, end):
        day, prior = stamp.date().isoformat(), (stamp.date() - timedelta(days=1)).isoformat()
        for name, members in groups:
            ready = all((school, date) in complete for school in members for date in (prior, day))
            current_ready = all((school, day) in complete for school in members)
            selected = rows[rows.school.isin(members)]
            before = by_id(active[active.school.isin(members) & active.market_date.eq(prior)])
            after = by_id(active[active.school.isin(members) & active.market_date.eq(day)])
            record = dict(date=day, school=name, flow_complete=ready,
                          active=len(after) if current_ready else None,
                          contract=contracts[contracts.school.isin(members) & contracts.market_date.eq(day)].property_id.nunique() if current_ready else None,
                          entered=None, left=None, net=None, **{key: None for key in FLOW_REASONS})
            if ready:
                before_raw = by_id(selected[selected.market_date.eq(prior)])
                after_raw = by_id(selected[selected.market_date.eq(day)])
                seen = set(history.loc[history.school.isin(members) & history.market_date.lt(day), 'property_id'])
                record.update(entered=0, left=0, net=len(after) - len(before), **{key: 0 for key in FLOW_REASONS})
                for direction, ids in [('entered', after.index.difference(before.index)), ('left', before.index.difference(after.index))]:
                    for pid in ids:
                        home = after.loc[pid] if direction == 'entered' else before.loc[pid]
                        other = before_raw.loc[pid] if direction == 'entered' and pid in before_raw.index else (
                            after_raw.loc[pid] if direction == 'left' and pid in after_raw.index else None)
                        if direction == 'entered':
                            reason = ('reactivated' if other is not None and other.status in ('pending', 'under_contract') else
                                      'filter_entered' if other is not None and other.status == 'active' else
                                      'reappeared' if pid in seen else 'first_observed')
                        else:
                            fresh = other is not None and other._status_day == day
                            reason = ('to_contract' if fresh and other.status in ('pending', 'under_contract') else
                                      'to_sold' if fresh and other.status == 'sold' else
                                      'withdrawn' if fresh and other.status == 'withdrawn' else
                                      'filter_left' if fresh and other.status == 'active' else 'unexplained_left')
                        record[direction] += 1
                        record[reason] += 1
                        events.append(dict(date=day, school=name, property_id=pid, address=home.address,
                                           direction=direction, reason=reason, previous_status=before_raw.loc[pid].status if pid in before_raw.index else None,
                                           current_status=after_raw.loc[pid].status if pid in after_raw.index else None,
                                           price=home.price, url=home.url))
            records.append(record)
    return pd.DataFrame(records), pd.DataFrame(events, columns=['date', 'school', 'property_id', 'address',
        'direction', 'reason', 'previous_status', 'current_status', 'price', 'url'])


def confirmed_sales(runs, observations, schools, end, **filters):
    """First observed Sold/Closed confirmation; retain dated and undated evidence.

    The original asking-price filters are applied to a prior tracked observation,
    never to the closing price. Source sale dates and confirmation dates differ.
    """
    valid = runs[runs.school.isin(schools) & runs.market_date.le(str(end)) & runs.quality.ne('failed')]
    rows = observations.merge(valid, on='run_id').sort_values(['observed_at', 'run_id'])
    eligible = filter_rows(rows, **filters)
    tracked = eligible[eligible.in_inventory.eq(1) & eligible.status.isin(INVENTORY)]
    tracked_first = tracked.groupby(['school', 'property_id']).observed_at.min().to_dict()
    sold = rows[rows.status.eq('sold')].copy()
    sold = sold[[tracked_first.get((row.school, row.property_id), '9999') <= row.observed_at for row in sold.itertuples()]] if len(sold) else sold
    sold['_sale_date'] = pd.to_datetime(sold.sold_date, errors='coerce').dt.strftime('%Y-%m-%d')
    sold['_confirmed_day'] = pd.to_datetime(sold.status_observed_at, utc=True, errors='coerce', format='mixed').dt.tz_convert(
        'America/New_York').dt.strftime('%Y-%m-%d').fillna(sold.market_date)
    sold = sold[sold._sale_date.isna() | sold._sale_date.le(str(end))]
    dates_by_episode = sold.groupby(['school', 'property_id', 'episode_id'])._sale_date.agg(lambda values: set(values.dropna())).to_dict()
    # Attach an earlier undated confirmation when its episode has one known sale.
    # Multiple dated transactions of the same property must remain separate.
    sold['_sale_key'] = [row._sale_date if pd.notna(row._sale_date) else
        (next(iter(dates_by_episode[(row.school, row.property_id, row.episode_id)]))
         if len(dates_by_episode[(row.school, row.property_id, row.episode_id)]) == 1 else 'undated:' + str(row.episode_id))
        for _, row in sold.iterrows()]
    keys = ['school', 'property_id', '_sale_key']
    sold['confirmed_date'] = sold.groupby(keys)._confirmed_day.transform('min')
    for field in ['sold_price', 'sold_date', '_sale_date']:
        sold[field] = sold.groupby(keys)[field].ffill()
    return sold.drop_duplicates(keys, keep='last')
