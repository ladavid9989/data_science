"""Run with: streamlit run streamlit_app.py. Reads saved observations only."""
from datetime import date, timedelta
from html import escape
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from tracker.archive import sync
from tracker.band import PRICE_RANGE, prune_database
from tracker.flows import FLOW_REASONS, confirmed_sales, listing_flows
from tracker.metrics import INVENTORY, canonical_runs, daily_metrics, filter_rows, joined, price_change_history, property_history, rank_price_cuts, rolling_market_metrics
from tracker.storage import SCHOOLS, default_db, read_frames

st.set_page_config(page_title="Schoolside · 주택 시장 트래커", page_icon="🏡", layout="wide")
COLORS = {"North Gwinnett": "#177568", "Johns Creek": "#6577C8", "Chattahoochee": "#C17C23",
          "Northview": "#AD5276"}
SHORT = {school: name.removesuffix(' High School') for school, name in SCHOOLS.items()}
STATUS = {"active": "판매 중", "under_contract": "계약 진행", "pending": "Pending",
          "sold": "판매 완료", "withdrawn": "등록 철회", "off_market_unknown": "상태 미확인"}
st.markdown("""<style>
.block-container {padding-top: 2.3rem; max-width: 1440px;}
h1 {letter-spacing: -1.5px; font-weight: 750 !important;}
h2,h3 {letter-spacing: -.5px;}
[data-testid="stMetric"] {background: white; border: 1px solid #e3e9ec; border-radius: 14px; padding: 17px 20px;}
[data-testid="stMetricLabel"] {color: #697B86;}
[data-testid="stMetricValue"] {font-size: 1.9rem;}
[data-testid="stSidebar"] {border-right: 1px solid #e3e9ec;}
.eyebrow {font-size: .72rem; letter-spacing: 2px; color: #177568; font-weight: 750; margin-bottom: .4rem;}
.badge {display: inline-block; padding: 5px 12px; border-radius: 18px; background: #fff0ce; color: #725218; font-size: .78rem; font-weight: 650;}
</style>""", unsafe_allow_html=True)


def money(value):
    return "—" if pd.isna(value) else f"${value:,.0f}"


def eastern_time(value):
    stamp = pd.to_datetime(value, utc=True, errors="coerce")
    return "—" if pd.isna(stamp) else stamp.tz_convert("America/New_York").strftime("%Y-%m-%d %I:%M %p %Z")


def chart_style(fig, height=300):
    fig.update_layout(height=height, margin=dict(l=8, r=12, t=20, b=10), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#3D5361"),
                      legend=dict(orientation="h", y=1.16, x=0), hovermode="x unified")
    fig.update_xaxes(showgrid=False, title=None)
    fig.update_yaxes(gridcolor="#E7EDF0", zeroline=False, title=None)
    return fig


def line_chart(frame, column, currency=False, percent=False):
    fig = go.Figure()
    for school, values in frame.groupby("school", sort=False):
        label = SHORT[school]
        fig.add_trace(go.Scatter(x=values.date, y=values[column], mode="lines+markers",
                                name=label, connectgaps=False, line=dict(color=COLORS[label], width=2.5),
                                marker=dict(size=4), hovertemplate="%{x}<br>" +
                                ("%{y:.2f}%" if percent else "%{y:,.0f}") + "<extra>%{fullData.name}</extra>"))
    if currency:
        fig.update_yaxes(tickprefix="$", tickformat=",.0f")
    if percent:
        fig.update_yaxes(ticksuffix="%", tickformat=".2f", zeroline=True)
    return chart_style(fig)


db = default_db()
dataset = "observed"


@st.cache_data(ttl=300, show_spinner=False)
def refresh_cloud(path):
    try:
        prune_database(path)
        if os.environ.get('HOUSING_OFFLINE') != '1':
            sync(path)
        return ""
    except Exception as exc:
        return str(exc)


sync_error = refresh_cloud(str(db))

with st.sidebar:
    st.markdown("### 🏡 Schoolside")
    st.caption("GEORGIA · HOUSING OBSERVATORY")
    st.caption("실제 관측 · 미국 동부시간(ET)")
    st.divider()
    school_choice = st.selectbox("고등학교 통학구역", ["전체 학군 비교", *SCHOOLS.values()], key="school")
    schools = list(SCHOOLS) if school_choice == "전체 학군 비교" else [k for k, v in SCHOOLS.items() if v == school_choice]
    st.caption("현재 수집: Houses · 침실 3+ · 욕실 2+ · $400k–$700k")
    price = PRICE_RANGE
    years = st.slider("건축연도", 1600, 2031, (1600, 2031), key="years")
    include_unknown = st.checkbox("건축연도 미확인 포함", value=True, key="unknown")
    beds = st.selectbox("최소 침실", [3, 4, 5, 6], key="beds")
    baths = st.selectbox("최소 욕실", [2.0, 2.5, 3.0, 4.0], key="baths")

runs, observations = read_frames(db, dataset)
runs = runs[runs.school.isin(schools)]
observations = observations[observations.run_id.isin(runs.run_id) & observations.price.between(*PRICE_RANGE)]
st.markdown('<div class="eyebrow">SCHOOLSIDE / MARKET TRACKER</div>', unsafe_allow_html=True)
st.title("학군으로 보는 주택 시장")
st.markdown("가격이 어떻게 바뀌고, 어떤 집이 시장에 남아 있는지 살펴보세요.")
st.caption("Zillow 학교 검색에서 관측한 매물입니다. 지도 경계 안의 매물을 구분하지만, 실제 통학구역 전체를 빠짐없이 포함하는지는 아직 검증되지 않았습니다.")
if sync_error:
    st.warning("클라우드 기록 동기화에 실패해 기존 로컬 기록을 표시합니다. 수집 상태에서 마지막 관측일을 확인하세요.")

if runs.empty:
    st.info("이 학군에 아직 관측 기록이 없습니다. 첫 수집이 완료되면 표시됩니다.")
    st.stop()

with st.sidebar:
    earliest, latest = date.fromisoformat(runs.market_date.min()), date.fromisoformat(runs.market_date.max())
    dates = st.date_input("조회 기간", value=(earliest, latest), min_value=earliest, max_value=latest,
                          key=f"dates_{dataset}_{school_choice}")
    if len(dates) != 2:
        st.info("시작일과 종료일을 선택하세요.")
        st.stop()
    st.divider()
    st.caption("화면을 열어도 새 수집은 실행되지 않습니다.")
    if st.button("저장된 기록 새로고침", width="stretch"):
        refresh_cloud.clear()
        st.rerun()

start, end = dates
filters = dict(price=price, years=years, include_unknown=include_unknown, beds=beds, baths=baths)
range_runs = runs[runs.market_date.between(start.isoformat(), end.isoformat())]
canonical = canonical_runs(range_runs)
ready_schools = [school for school in schools if school in set(canonical.school)]
waiting_schools = [school for school in schools if school not in ready_schools]
if waiting_schools and ready_schools:
    st.info(f"{', '.join(SHORT[school] for school in waiting_schools)}: 선택 기간의 완전 수집을 기다리고 있습니다. "
            f"현재 합계는 {', '.join(SHORT[school] for school in ready_schools)} 기준이며, 기존 학군의 기록은 계속 표시합니다.")
common = canonical.groupby("market_date").school.nunique()
common_dates = common[common == len(ready_schools)].index.tolist() if ready_schools else []
asof = max(common_dates) if common_dates else None
full = joined(range_runs, observations)
if asof:
    latest_rows = full[full.market_date == asof]
    scope_label = f"{'수집 완료 학군의 공통 수집일' if len(schools) > 1 else '수집일'} {asof} · 검증된 검색 범위 기준"
else:
    candidates = canonical_runs(range_runs[range_runs.quality.ne("failed")], complete_only=False).sort_values("observed_at").drop_duplicates("school", keep="last")
    latest_rows = observations.merge(candidates, on="run_id")
    scope_label = "가장 최근 관측 샘플 · 시장 전체 통계 미제공"
current = filter_rows(latest_rows, **filters)
inventory = current[current.status.isin(INVENTORY) & current.in_inventory.eq(1)]
active = current[current.status.eq("active") & current.in_inventory.eq(1)]
coverage = inventory.year_built.notna().mean() * 100 if len(inventory) else 0
st.caption(f"{scope_label}  ·  {'추가 가격 필터 없음 (저장된 범위)' if price is None else f'${price[0]:,}–${price[1]:,}'}  ·  Houses / {beds}+ bd / {baths:g}+ ba")
cards = st.columns(4)
weekly = rolling_market_metrics(runs, observations, ready_schools, start, end, **filters) if asof else pd.DataFrame()
headline = weekly[(weekly.date == asof) & weekly.school.eq('__all__' if len(ready_schools) > 1 else ready_schools[0])].iloc[0] if asof else None
count_delta = f"{headline.active_change_7d:+.0f}개 · 7일 전 대비" if asof and pd.notna(headline.active_change_7d) else None
cards[0].metric("현재 판매 중 매물" if asof else "필터에 맞는 관측 매물",
                f"{active.property_id.nunique() if asof else current.property_id.nunique():,}", count_delta, delta_color="off")
for card, label, column in zip(cards[1:], ['7일간 관측된 가격 인하 비율', '동일 매물 7일 호가 변화율', '관측 인하폭 중앙값 · 1회당'],
                               ['cut_share_7d', 'mean_change_7d', 'median_cut_percent']):
    value = headline[column] if asof else None
    card.metric(label, f"{value:+.2f}%" if column == 'mean_change_7d' and pd.notna(value) else
                (f"{value:.2f}%" if pd.notna(value) else '미산출'))
if asof:
    comparison_label = f'동일 매물 {headline.comparable_count}개 / 현재 판매 중 {active.property_id.nunique()}개' if headline.weekly_ready else '비교 기록 부족'
    st.caption(f"7일 비교: {headline.baseline_date} → {asof} · {comparison_label}. "
               "전체 학군 합계에서는 중복 매물을 한 번만 셉니다.")
    st.caption('인하폭 중앙값은 비교 대상에서 관측된 인하 1회당 감소율의 중앙값입니다. 인하 관측이 없으면 미산출로 표시합니다.')
    if not headline.weekly_ready:
        st.info('7일 비교 기록 부족: 선택 학군 모두에 7일 전과 기준일의 완전한 새 가격 관측이 있어야 합계를 계산합니다. 계산 가능한 학군은 아래 표에서 확인할 수 있습니다.')
    elif headline.comparable_count == 0:
        st.info('양쪽 날짜의 조건을 모두 충족하는 동일 매물이 없어 7일 가격 지표를 계산하지 않습니다.')
    elif headline.observed_days < 8:
        st.info(f'비교 구간 8개 날짜 중 {headline.observed_days}일에 완전한 새 관측이 있습니다. 인하 비율은 저장된 관측에서 확인한 값이며, 수집 사이의 변동은 놓칠 수 있습니다.')

overview, listings_tab, history_tab, health_tab = st.tabs(["시장 흐름", "매물 탐색", "집별 타임라인", "수집 상태"])
with overview:
    if not asof:
        st.warning("비교 가능한 완전 수집 기록이 없습니다. 일부 매물로 전체 매물 수나 가격 추이를 계산하지 않습니다.")
        st.markdown("**지금 볼 수 있는 것:** 매물 탐색, 확인된 건축연도, 실제 관측 시점과 수집 범위.")
        st.markdown("날짜별 수집이 누적되면 비교 가능한 검색 범위의 추이가 표시됩니다.")
    else:
        metrics = daily_metrics(runs, observations, schools, start, end, **filters)
        metrics = metrics.merge(weekly.drop(columns='active'), on=['date', 'school'], how='left')
        left, right = st.columns(2)
        with left:
            st.subheader("일별 매물 수")
            st.caption("각 날짜의 마지막 완전 수집에서 확인한 판매 중 매물 수입니다. 계약 진행·Pending은 제외하며, 거래량을 뜻하지 않습니다.")
            st.plotly_chart(line_chart(metrics, "active"), width="stretch", key="inventory_chart")
        with right:
            st.subheader("동일 매물의 7일 호가 변화")
            st.caption("각 날짜와 7일 전 모두 판매 중이고 필터에 맞는 집을 비교합니다. 집마다 변화율을 계산한 뒤 동일 비중으로 평균하며, 가격이 그대로인 집도 포함합니다.")
            st.plotly_chart(line_chart(metrics, 'mean_change_7d', percent=True), width="stretch", key="price_chart")
        left, right = st.columns(2)
        with left:
            st.subheader('7일간 관측된 가격 인하 비율')
            st.caption('위와 같은 비교 대상 중 한 번 이상 인하가 관측된 매물의 비율입니다. 한 집이 여러 번 내려도 매물 수는 한 번만 셉니다.')
            st.plotly_chart(line_chart(metrics, 'cut_share_7d', percent=True), width='stretch', key='cut_share_chart')
        with right:
            st.subheader('비교 대상과 기록 범위')
            audit = weekly[weekly.date.eq(asof) & weekly.school.ne('__all__')].copy()
            audit['school'] = audit.school.map(SHORT)
            audit['비교 상태'] = audit.apply(lambda row: '7일 비교 기록 부족' if not row.weekly_ready else
                ('동일 매물 없음' if not row.comparable_count else '비교 가능'), axis=1)
            audit = audit[['school', 'active', 'comparable_count', 'comparison_coverage', 'cut_count', 'mean_change_7d',
                           'cut_share_7d', 'cut_event_count', 'observed_days', '비교 상태']].rename(columns={
                'school': '학군', 'active': '판매 중', 'comparable_count': '동일 매물', 'comparison_coverage': '비교 포함률 (%)',
                'cut_count': '인하 매물', 'mean_change_7d': '7일 변화율 (%)', 'cut_share_7d': '인하 비율 (%)',
                'cut_event_count': '관측 인하 횟수', 'observed_days': '관측 일수 / 8'})
            st.dataframe(audit, hide_index=True, width='stretch')
            st.caption('7일 전 기록이 없는 새 학군은 미산출입니다. 중간 관측이 빠진 날의 변동은 확인할 수 없습니다. 날짜는 미국 동부시간 기준입니다.')
        st.caption('신규 관측·검색 이탈·확인된 재등록은 동일 매물 비교에서 제외합니다. 이 지표는 $400k–$700k 관심 매물의 관측 호가 흐름이며, 전체 시장의 거래가격 지수가 아닙니다. 그래프의 빈 구간은 비교 기록 부족이며 0으로 채우지 않습니다.')
        with st.expander('보조 지표 · 현재 매물의 가격대와 구성'):
            secondary = st.columns(3)
            secondary[0].metric('현재 호가 중앙값', money(active.drop_duplicates('property_id').price.median()))
            secondary[1].metric('계약 진행 / Pending', str(inventory[inventory.status.ne('active')].property_id.nunique()))
            secondary[2].metric('건축연도 확인', f'{inventory.year_built.notna().sum()} / {len(inventory)}', f'{coverage:.0f}% 확인', delta_color='off')
            price_stat = st.selectbox('가격 통계', ['중앙값', '평균'], key='price_stat')
            st.caption('매물 구성과 가격대 진입·이탈에 영향을 받는 값입니다. 같은 집의 가격 변화는 위 7일 지표로 확인하세요.')
            st.plotly_chart(line_chart(metrics, 'median_price' if price_stat == '중앙값' else 'mean_price', True), width='stretch', key='composition_chart')
        st.subheader('매물 진입·이탈과 판매 완료')
        flow_window = st.selectbox('매물 흐름 조회 기간', ['최근 1일', '최근 7일', '최근 30일', '선택 기간 전체'], index=1, key='flow_window')
        flow_days = {'최근 1일': 1, '최근 7일': 7, '최근 30일': 30}.get(flow_window)
        flow_start = max(start, end - timedelta(days=flow_days - 1)) if flow_days else start
        flows, flow_events = listing_flows(runs, observations, schools, start, end, **filters)
        metrics = metrics.merge(flows.drop(columns=['active', 'contract']), on=['date', 'school'], how='left')
        flow_school = '__all__' if len(schools) > 1 else schools[0]
        flow_period = flows[flows.school.eq(flow_school) & flows.date.between(str(flow_start), str(end))]
        compared = flow_period[flow_period.flow_complete]
        period_events = flow_events[flow_events.school.eq(flow_school) & flow_events.date.between(str(flow_start), str(end))].copy()
        sales = confirmed_sales(runs, observations, schools, end, **filters)
        sales['confirmed_date'] = sales.groupby(['property_id', '_sale_key']).confirmed_date.transform('min')
        sales = sales.sort_values('observed_at').drop_duplicates(['property_id', '_sale_key'], keep='last')
        sales = sales[sales.confirmed_date.between(str(flow_start), str(end))]
        st.caption(f'{flow_start} ~ {end} · 미국 동부시간 · 전일과 비교 가능한 {len(compared)}/{len(flow_period)}일의 합계. 각 날짜의 마지막 완전 수집끼리 비교합니다.')
        if len(compared) != len(flow_period):
            st.info('첫 수집일·수집 누락·검색 범위 변경·오래된 관측은 진입·이탈 비교에서 제외합니다. 아래 수치는 비교 가능한 날짜의 부분 합계이며, 빠진 날을 0건으로 처리하지 않습니다.')
        flow_cards = st.columns(5)
        for card, label, key in zip(flow_cards[:3], ['판매 중 목록 진입', '판매 중 목록 이탈', '매물 순증감'], ['entered', 'left', 'net']):
            card.metric(label, f'{compared[key].sum():+.0f}' if key == 'net' and len(compared) else
                        (f'{compared[key].sum():.0f}' if len(compared) else '미산출'))
        flow_cards[3].metric('현재 계약 진행 / Pending', str(inventory[inventory.status.ne('active')].property_id.nunique()))
        flow_cards[4].metric('기간 내 판매 완료 확인', str(len(sales)))
        st.caption(f'현재 계약 진행은 {asof} 기준 보유 건수입니다. 진입·이탈은 날짜별 이동 횟수로, 같은 집의 재진입·재이탈은 각각 셉니다. 전체 학군 합계에서는 중복 매물을 한 번만 셉니다.')
        st.caption('판매 완료는 원문에서 확인한 건수이며 최초 확인일 기준입니다. 0건이어도 실제 거래가 없다는 뜻은 아닙니다. 실제 거래일과 근거는 아래 판매 완료 내역에서 확인할 수 있습니다.')
        if len(compared):
            st.caption(f"진입 중 처음 관측 {compared.first_observed.sum():.0f}건 · 재관측 {compared.reappeared.sum():.0f}건 · 계약 진행에서 판매 중으로 복귀 {compared.reactivated.sum():.0f}건 · 필터 편입 {compared.filter_entered.sum():.0f}건. "
                       f"이탈 중 계약 진행 전환 {compared.to_contract.sum():.0f}건 · 판매 완료 확인 {compared.to_sold.sum():.0f}건 · 등록 철회 {compared.withdrawn.sum():.0f}건 · 필터 이탈 {compared.filter_left.sum():.0f}건 · 사유 미확인 {compared.unexplained_left.sum():.0f}건.")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=flow_period.date, y=flow_period.entered, name='진입', marker_color='#177568'))
        fig.add_trace(go.Bar(x=flow_period.date, y=-pd.to_numeric(flow_period.left), name='이탈', marker_color='#AD5276'))
        fig.add_trace(go.Scatter(x=flow_period.date, y=flow_period.net, name='순증감', mode='lines+markers', connectgaps=False, line_color='#6577C8'))
        fig.update_layout(barmode='relative')
        st.plotly_chart(chart_style(fig, 260), width='stretch', key='flow_chart')
        st.caption('처음 관측된 집도 새로 등록된 집이라고 단정하지 않습니다. 가격대 진입이나 필터 정보 보완으로 포함될 수 있습니다. 검색 이탈도 판매 완료를 뜻하지 않습니다. 같은 날 들어왔다가 사라진 매물은 일별 마지막 목록 비교에 잡히지 않을 수 있습니다.')
        with st.expander('진입·이탈 내역과 CSV'):
            flow_display = period_events[['date', 'address', 'direction', 'reason', 'previous_status', 'current_status', 'price', 'url']].copy()
            flow_display['direction'] = flow_display.direction.map({'entered': '진입', 'left': '이탈'})
            flow_display['reason'] = flow_display.reason.map(FLOW_REASONS)
            for column in ['previous_status', 'current_status']:
                flow_display[column] = flow_display[column].map(STATUS).fillna('미관측')
            flow_display = flow_display.rename(columns={'date': '비교일 (ET)', 'address': '매물', 'direction': '이동', 'reason': '분류',
                'previous_status': '전일 관측 상태', 'current_status': '당일 관측 상태', 'price': '관측 호가 ($)', 'url': '원문'})
            st.dataframe(flow_display, hide_index=True, width='stretch', column_config={'원문': st.column_config.LinkColumn(display_text='Zillow ↗')})
            st.download_button('진입·이탈 이력 CSV', flow_display.to_csv(index=False).encode('utf-8-sig'), file_name=f'listing_flows_{flow_start}_{end}.csv', mime='text/csv')
            st.dataframe(flow_period[['date', 'flow_complete', 'entered', 'left', 'net']].rename(columns={
                'date': '날짜', 'flow_complete': '전일 비교 가능', 'entered': '진입', 'left': '이탈', 'net': '순증감'}), hide_index=True, width='stretch')
        with st.expander('판매 완료 확인 내역 · Closed / Sold'):
            st.caption('Closed와 Sold는 같은 판매 완료로 한 번만 셉니다. 위 건수는 최초 확인일 기준이고 실제 거래일은 아래에 별도로 표시합니다. 0건은 저장된 확인 기록이 없다는 뜻이며 실제 거래가 없다는 뜻은 아닙니다. 이탈 사유의 판매 완료와 중복될 수 있으므로 서로 더하지 않습니다.')
            st.caption('추적하던 관심 매물에서 원문이 판매 완료로 명시한 기록만 집계합니다. 검색에서 사라진 집의 상태 확인은 지연되거나 누락될 수 있으며, 날짜·가격 미확인 항목은 비워 둡니다.')
            sales_display = sales[['confirmed_date', 'sold_date', 'address', 'sold_price', 'evidence', 'url']].rename(columns={
                'confirmed_date': '최초 확인일 (ET)', 'sold_date': '거래일', 'address': '매물', 'sold_price': '확인된 거래가격 ($)', 'evidence': '확인 근거', 'url': '원문'})
            st.dataframe(sales_display, hide_index=True, width='stretch', column_config={'원문': st.column_config.LinkColumn(display_text='Zillow ↗')})
            st.download_button('판매 완료 확인 CSV', sales_display.to_csv(index=False).encode('utf-8-sig'), file_name=f'confirmed_sales_{flow_start}_{end}.csv', mime='text/csv')
        left, right = st.columns(2)
        with left:
            st.subheader("건축연도 분포")
            known = inventory.dropna(subset=["year_built"]).copy()
            if known.empty:
                st.info("현재 필터에서 확인된 건축연도가 없습니다.")
            else:
                known["학군"] = known.school.map(SHORT)
                fig = px.histogram(known, x="year_built", color="학군", nbins=12, color_discrete_map=COLORS, barmode="group")
                st.plotly_chart(chart_style(fig, 260), width="stretch", key="year_chart")
            st.caption(f"건축연도 미확인 {inventory.year_built.isna().sum()}건은 분포에서 제외했습니다.")
        with right:
            st.subheader("관측 호가 변화")
            change_window = st.selectbox("가격변화 조회 기간", ["최근 1일", "최근 7일", "최근 30일", "선택 기간 전체"],
                                         index=1, key="change_window")
            window_days = {"최근 1일": 1, "최근 7일": 7, "최근 30일": 30}.get(change_window)
            change_start = max(start, end - timedelta(days=window_days - 1)) if window_days else start
            changes = price_change_history(runs, observations, change_start, end, **filters)
            st.caption(f"{change_start} ~ {end} · 미국 동부시간 기준 확인일 · 왼쪽 조회 기간의 종료일 기준이며, 선택 기간 안으로 제한됩니다.")
            st.caption("수집할 때마다 직전 관측 호가와 비교합니다. 기간 시작 전 기록도 비교 기준으로 사용하며, 같은 날 여러 번 확인된 변동도 각각 남깁니다.")
            if changes.empty:
                st.info("이 기간의 저장된 관측에서 확인된 가격변화 이력이 없습니다. 비교할 이전 관측이 없거나 수집 사이에 발생한 변동은 확인할 수 없습니다.")
            else:
                st.caption(f"인하 {int(changes.price_change.lt(0).sum())}건 · 인상 {int(changes.price_change.gt(0).sum())}건 · {changes.property_id.nunique()}개 매물")
                change_table = changes.copy()
                change_table['school'] = change_table.school.map(SHORT)
                for column in ['price_observed_at_before', 'price_observed_at_after']:
                    change_table[column] = change_table[column].map(eastern_time)
                change_table = change_table[["price_observed_at_after", "address_after", "school", "price_before", "price_after",
                                             "price_change", "price_change_percent", "price_observed_at_before", "comparison_basis"]].rename(columns={
                    "price_observed_at_after": "변동 확인 시각 (ET)", "address_after": "매물", "school": "학군",
                    "price_before": "이전 호가", "price_after": "변동 후 호가", "price_change": "변화 ($)",
                    "price_change_percent": "변화 (%)", "price_observed_at_before": "이전 확인 시각 (ET)", "comparison_basis": "비교 근거"})
                st.dataframe(change_table, hide_index=True, width="stretch", key="price_changes", column_config={
                    "이전 호가": st.column_config.NumberColumn(format="$%d"),
                    "변동 후 호가": st.column_config.NumberColumn(format="$%d"),
                    "변화 ($)": st.column_config.NumberColumn(format="$%d"),
                    "변화 (%)": st.column_config.NumberColumn(format="%.2f%%"),
                })
                st.download_button("가격변화 이력 CSV", change_table.to_csv(index=False).encode("utf-8-sig"),
                                   file_name=f"price_changes_{change_start}_{end}.csv", mime="text/csv")
            st.caption("변동 확인 시각은 실제 가격 변경 시각과 다를 수 있습니다. 변동 당시 필터에 맞는 매물을 포함하며, 현재 목록에서 사라져도 이력은 유지합니다. 확인된 재등록은 제외합니다.")
        st.download_button("일별 통계 CSV", metrics.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"{dataset}_daily_metrics.csv", mime="text/csv")

with listings_tab:
    order = st.selectbox('매물 정렬', ['가격 인하율 큰 순', '가격 인하액 큰 순', '낮은 가격순'], key='listing_order')
    status_options = st.multiselect("목록에 표시할 상태", list(STATUS), default=INVENTORY,
                                   format_func=lambda x: STATUS[x], key="listing_status")
    search = st.text_input("주소 또는 매물 ID 검색", key="search", placeholder="예: Summit Gate")
    table = current[current.status.isin(status_options)].copy()
    table = rank_price_cuts(table, observations.merge(runs, on='run_id'),
                            {'가격 인하율 큰 순': 'percent', '가격 인하액 큰 순': 'amount', '낮은 가격순': 'price'}[order])
    if search:
        table = table[table.address.str.contains(search, case=False, regex=False) | table.property_id.str.contains(search, case=False, regex=False)]
    st.caption(f"{len(table)}개 매물 · {scope_label}")
    st.caption('인하는 Zillow가 표시한 최근 인하 또는 동일 등록 건의 관측 비교입니다. 오늘 발생한 인하라는 뜻은 아닙니다. 인하율 = 인하액 ÷ 인하 전 가격.')
    display = table.copy()
    display['price_observed_at'] = display.price_observed_at.map(eastern_time)
    display["school"] = display.school.map(SHORT)
    display["status"] = display.status.map(STATUS)
    display['year_status'] = display.year_status.fillna('not_requested').map({'verified': '확인', 'not_requested': '상세 조회 대기', 'not_in_response': '응답에 없음', 'parse_failed': '추출 실패', 'conflict': '값 충돌'})
    columns = {"address": "매물", "school": "학군", "price": "호가 ($)", 'cut_amount': '인하액 ($)', 'cut_percent': '인하율 (%)', 'cut_date': '인하일', 'cut_basis': '인하 근거', "year_built": "건축연도", 'year_status': '연도 확인 상태',
               "bedrooms": "침실", "bathrooms": "욕실", "square_feet": "면적 (sqft)", "status": "상태", 'price_observed_at': '호가 확인 시각 (미국 동부)', "url": "원문"}
    display = display[list(columns)].rename(columns=columns)
    st.dataframe(display, hide_index=True, width="stretch", height=390, column_config={
        "호가 ($)": st.column_config.NumberColumn(format="$%d"),
        "건축연도": st.column_config.NumberColumn(format="%d"),
        '인하액 ($)': st.column_config.NumberColumn(format='$%d'),
        '인하율 (%)': st.column_config.NumberColumn(format='%.2f%%'),
        "원문": st.column_config.LinkColumn(display_text="Zillow ↗"),
    })
    st.download_button("현재 목록 CSV", display.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"{dataset}_listings.csv", mime="text/csv")
    with st.expander("지도 보기"):
        st.caption("매물 좌표입니다. 실제 학교 배정은 교육청에서 최종 확인해야 합니다.")
        coordinates = table[["latitude", "longitude"]].dropna()
        if coordinates.empty:
            st.info("표시할 좌표가 없습니다.")
        else:
            st.map(coordinates, latitude="latitude", longitude="longitude", color="#177568", size=50)

with history_tab:
    st.caption("관심 가격대 $400k–$700k 안에서 기록된 집별 이력입니다. 건축연도·조회 기간 필터와 별도로 확인할 수 있습니다.")
    catalog = observations.merge(runs[["run_id", "school", "observed_at"]], on="run_id").sort_values("observed_at").drop_duplicates("property_id", keep="last")
    labels = {row.property_id: f"{row.address} · {SHORT[row.school]}" for row in catalog.itertuples()}
    if catalog.empty:
        st.info("아직 관측된 매물이 없습니다.")
    else:
        pid = st.selectbox("추적할 집", list(labels), format_func=lambda x: labels[x], key=f"property_{dataset}_{school_choice}")
        home = catalog[catalog.property_id == pid].iloc[0]
        history = property_history(runs, observations, pid, home.school)
        st.markdown(f"#### {escape(home.address)}")
        detail_cards = st.columns(4)
        detail_cards[0].metric("마지막 관측 호가", money(home.price))
        detail_cards[1].metric("건축연도", "미확인" if pd.isna(home.year_built) else str(int(home.year_built)))
        detail_cards[2].metric("마지막 확인 상태", STATUS[home.status])
        detail_cards[3].metric("확인된 거래가격", money(home.sold_price))
        st.caption(f"마지막 실제 관측: {eastern_time(home.observed_at)} · 등록 건 ID: {home.episode_id}")
        if history.iloc[-1].availability != "관측됨":
            st.warning(f"최근 수집일: {history.iloc[-1].availability}. 이전 상태를 현재 상태로 단정하지 않습니다.")
        if home.episode_id.endswith(":unknown"):
            st.caption("등록 건 ID가 확인되지 않은 샘플입니다. 재등록 여부나 정확한 가격 변경 이벤트를 단정하지 않습니다.")
        fig = go.Figure()
        for episode, _ in history.dropna(subset=["episode_id"]).groupby("episode_id", sort=False):
            series = history.copy()
            series.loc[series.episode_id.ne(episode) | series.status.eq("sold"), "price"] = None
            fig.add_trace(go.Scatter(x=series.market_date, y=series.price, name="관측 호가 · " + episode.rsplit(":", 1)[-1],
                                    mode="lines+markers", connectgaps=False))
        sold = history[history.sold_price.notna()].drop_duplicates(["episode_id", "sold_date", "sold_price"])
        if not sold.empty:
            fig.add_trace(go.Scatter(x=sold.market_date, y=sold.sold_price, mode="markers", name="거래가격 확인일",
                                    marker=dict(symbol="diamond", size=12, color="#D8A33B")))
        fig.update_yaxes(tickprefix="$", tickformat=",.0f")
        st.plotly_chart(chart_style(fig), width="stretch", key="history_chart")
        timeline = history[["market_date", "price", "status", "availability", "sold_date", "sold_price", "episode_id"]].copy()
        timeline["status"] = timeline.status.map(STATUS)
        timeline = timeline.rename(columns={"market_date": "관측일", "price": "호가 ($)", "status": "확인 상태",
            "availability": "관측 여부", "sold_date": "거래일", "sold_price": "거래가격 ($)", "episode_id": "등록 건"})
        st.dataframe(timeline.sort_values("관측일", ascending=False), hide_index=True, width="stretch")
        st.caption("검색에서 사라짐 ≠ 판매 완료. 거래일과 거래가격을 확인한 날짜는 다를 수 있습니다.")

with health_tab:
    st.subheader("기록의 범위와 신뢰도")
    st.caption(f"30분 간격으로 실행하고 {len(SCHOOLS)}개 학군을 순차 수집합니다. 정상 실행 시 학군별 전체 검색은 약 {30 * len(SCHOOLS)}분마다 갱신합니다. 건축연도가 모두 확인돼도 새 매물과 가격을 다시 조회합니다. 실행 지연·하루 요청 한도·접근 제한 중에는 더 늦어질 수 있습니다.")
    st.link_button("GitHub 수집 실행 기록", "https://github.com/ladavid9989/data_science/actions/workflows/housing-collect.yml")
    for school in schools:
        subset = runs[runs.school == school]
        if subset.empty:
            st.warning(f"{SHORT[school]}: 관측 없음")
        else:
            last = subset.sort_values("observed_at").iloc[-1]
            latest_rows = observations[observations.run_id.eq(last.run_id)]
            known = int(latest_rows.year_built.notna().sum())
            waiting = int(latest_rows.year_built.isna().sum())
            quality = "검색 목록 대조 완료" if last.quality == 'source_complete' else last.quality
            st.write(f"**{SHORT[school]}** · 마지막 기록 {eastern_time(last.observed_at)} · {quality} · {len(latest_rows)}건")
            st.caption(f"건축연도 확인 {known}/{len(latest_rows)} · 미확인 {waiting}건. 검색 목록 완료와 상세정보 보완 완료는 별개입니다.")
            stamps = pd.to_datetime(latest_rows.price_observed_at, utc=True, errors='coerce', format='mixed').dropna()
            if not stamps.empty:
                st.caption(f"호가 조회 시각: {eastern_time(stamps.min())} ~ {eastern_time(stamps.max())}")
    health = range_runs.sort_values('observed_at').drop_duplicates(['market_date', 'school'], keep='last')
    health = health[["market_date", "school", "quality", "row_count", "reported_count"]].copy()
    health["school"] = health.school.map(SHORT)
    st.dataframe(health.sort_values(["market_date", "school"], ascending=[False, True]), hide_index=True, width="stretch")
    st.caption("학군별 하루의 마지막 저장 기록입니다. 같은 검색 목록에 건축연도를 보완한 중간 기록은 합쳐 표시합니다.")
    st.info("Source complete: 해당 수집 가격 범위의 검색 페이지와 매물 수를 대조한 기록입니다. 배치 사이 시점 차이가 있으며, 학군 전체 시장을 보장하지 않습니다. Partial/Failed는 추이 통계에서 제외됩니다. 가격 범위를 벗어나 검색에서 사라진 집을 판매 완료로 보지 않습니다.")
    with st.expander("로컬 저장소와 가져오기"):
        st.code(str(db), language=None)
        st.markdown("관측 JSON과 원본 체크섬을 SQLite에 보관합니다. 기존 probe 원본은 DB 옆 raw 폴더에 압축 저장합니다. "
                    "백업 시 DB와 raw 폴더를 함께 보관하세요. 자세한 명령은 프로젝트 README에 있습니다.")

st.divider()
st.caption("SCHOOLSIDE · LOCAL PROTOTYPE  /  화면 새로고침은 저장된 기록만 읽습니다. 실시간 시세가 아닙니다.")
