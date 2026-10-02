"""Run with: streamlit run streamlit_app.py. Reads saved observations only."""
from datetime import date
from html import escape
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from tracker.archive import sync
from tracker.metrics import INVENTORY, canonical_runs, changes_between, daily_metrics, filter_rows, joined, property_history, rank_price_cuts
from tracker.storage import SCHOOLS, default_db, read_frames

st.set_page_config(page_title="Schoolside · 주택 시장 트래커", page_icon="🏡", layout="wide")
COLORS = {"North Gwinnett": "#177568", "Johns Creek": "#6577C8"}
SHORT = {"north_gwinnett": "North Gwinnett", "johns_creek": "Johns Creek"}
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


def chart_style(fig, height=300):
    fig.update_layout(height=height, margin=dict(l=8, r=12, t=20, b=10), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#3D5361"),
                      legend=dict(orientation="h", y=1.16, x=0), hovermode="x unified")
    fig.update_xaxes(showgrid=False, title=None)
    fig.update_yaxes(gridcolor="#E7EDF0", zeroline=False, title=None)
    return fig


def line_chart(frame, column, currency=False):
    fig = go.Figure()
    for school, values in frame.groupby("school", sort=False):
        label = SHORT[school]
        fig.add_trace(go.Scatter(x=values.date, y=values[column], mode="lines+markers",
                                name=label, connectgaps=False, line=dict(color=COLORS[label], width=2.5),
                                marker=dict(size=4), hovertemplate="%{x}<br>%{y:,.0f}<extra>%{fullData.name}</extra>"))
    if currency:
        fig.update_yaxes(tickprefix="$", tickformat=",.0f")
    return chart_style(fig)


db = default_db()
dataset = "observed"


@st.cache_data(ttl=300, show_spinner=False)
def refresh_cloud(path):
    try:
        sync(path)
        return ""
    except Exception as exc:
        return str(exc)


sync_error = refresh_cloud(str(db)) if os.environ.get("HOUSING_OFFLINE") != "1" else ""

with st.sidebar:
    st.markdown("### 🏡 Schoolside")
    st.caption("GEORGIA · HOUSING OBSERVATORY")
    st.caption("실제 관측 · GitHub 일일 수집")
    st.divider()
    school_choice = st.selectbox("고등학교 통학구역", ["두 학군 비교", *SCHOOLS.values()], key="school")
    schools = list(SCHOOLS) if school_choice == "두 학군 비교" else [k for k, v in SCHOOLS.items() if v == school_choice]
    st.caption("현재 수집: Houses · 침실 3+ · 욕실 2+ · $400k–$700k")
    st.caption("가격 범위를 벗어난 매물은 새로 수집하지 않습니다. 과거 전체 가격대 기록은 보존됩니다.")
    all_prices = st.toggle("저장된 범위 전체 보기", value=False, key="all_prices")
    price = None
    if not all_prices:
        low = st.number_input("최저 가격 ($)", min_value=0, max_value=20000000, value=400000, step=25000, key="price_min")
        high = st.number_input("최고 가격 ($)", min_value=0, max_value=20000000, value=700000, step=25000, key="price_max")
        if low > high:
            st.error("최저 가격은 최고 가격 이하여야 합니다.")
            st.stop()
        price = (low, high)
    years = st.slider("건축연도", 1600, 2031, (1600, 2031), key="years")
    include_unknown = st.checkbox("건축연도 미확인 포함", value=True, key="unknown")
    beds = st.selectbox("최소 침실", [3, 4, 5, 6], key="beds")
    baths = st.selectbox("최소 욕실", [2.0, 2.5, 3.0, 4.0], key="baths")

runs, observations = read_frames(db, dataset)
runs = runs[runs.school.isin(schools)]
observations = observations[observations.run_id.isin(runs.run_id)]
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
common = canonical.groupby("market_date").school.nunique()
common_dates = common[common == len(schools)].index.tolist()
asof = max(common_dates) if common_dates else None
full = joined(range_runs, observations)
if asof:
    latest_rows = full[full.market_date == asof]
    scope_label = f"두 학군의 공통 수집일 {asof} · 검증된 검색 범위 기준"
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
cards[0].metric("판매 중 매물" if asof else "필터에 맞는 관측 매물", f"{len(active) if asof else len(current):,}")
cards[1].metric("호가 중앙값" if asof else "시장 중앙값", money(active.loc[active.price > 0, "price"].median()) if asof else "미산출")
cards[2].metric("계약 진행 / Pending", f"{int(current.status.isin(['under_contract', 'pending']).sum()):,}")
cards[3].metric("건축연도 확인", f"{inventory.year_built.notna().sum()} / {len(inventory)}", f"{coverage:.0f}% 확인", delta_color="off")

overview, listings_tab, history_tab, health_tab = st.tabs(["시장 흐름", "매물 탐색", "집별 타임라인", "수집 상태"])
with overview:
    if not asof:
        st.warning("비교 가능한 완전 수집 기록이 없습니다. 일부 매물로 전체 매물 수나 가격 추이를 계산하지 않습니다.")
        st.markdown("**지금 볼 수 있는 것:** 매물 탐색, 확인된 건축연도, 실제 관측 시점과 수집 범위.")
        st.markdown("날짜별 수집이 누적되면 비교 가능한 검색 범위의 추이가 표시됩니다.")
    else:
        metrics = daily_metrics(range_runs, observations, schools, start, end, **filters)
        left, right = st.columns(2)
        with left:
            st.subheader("매일의 판매 중 매물")
            st.caption("그날의 가격·건축연도 조건에 맞는 매물 수")
            st.plotly_chart(line_chart(metrics, "active"), width="stretch", key="inventory_chart")
        with right:
            st.subheader("호가 중앙값")
            st.caption("매물 구성에 따라 변합니다. 개별 집의 가치 상승률이 아닙니다.")
            st.plotly_chart(line_chart(metrics, "median_price", True), width="stretch", key="price_chart")
        st.caption("그래프의 끊긴 구간은 수집 실패 또는 불완전한 기록입니다. 0건으로 대체하지 않습니다.")
        activity = filter_rows(full, **filters)
        sold_activity = activity[activity.status.eq("sold") & activity.sold_date.notna()].sort_values("observed_at").drop_duplicates(
            ["property_id", "episode_id", "sold_date"], keep="last")
        sold_activity = sold_activity[sold_activity.sold_date.between(start.isoformat(), end.isoformat())]
        activity_cards = st.columns(3)
        activity_cards[0].metric("기간 내 거래일이 확인된 판매", str(len(sold_activity)))
        activity_cards[1].metric("거래가격까지 확인", str(sold_activity.sold_price.notna().sum()))
        activity_cards[2].metric("확인된 거래가격 중앙값", money(sold_activity.sold_price.median()))
        st.caption("위 판매 지표는 확인된 거래일 기준이며, 가격 필터는 기록된 호가에 적용됩니다. 뒤늦게 공개된 거래가격은 이후 집계에서 추가될 수 있습니다.")
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
            st.subheader("같은 등록 건의 가격 변화")
            if len(common_dates) < 2:
                st.info("비교할 이전 완전 수집일이 없습니다.")
            else:
                prior = sorted(common_dates)[-2]
                changes = changes_between(full[full.market_date == prior], full[full.market_date == asof])
                changes = changes[changes.property_id.isin(current.property_id)]
                st.caption(f"{prior} → {asof} · 현재 필터에 해당하는 매물 · 등록 건이 확인된 경우만 비교")
                if changes.empty:
                    st.info("이 구간에서 확인된 동일 등록 건의 가격 변화가 없습니다.")
                else:
                    st.dataframe(changes[["address_after", "price_before", "price_after", "price_change"]].rename(columns={
                        "address_after": "매물", "price_before": "이전 호가", "price_after": "현재 호가", "price_change": "변화 ($)"}),
                        hide_index=True, width="stretch")
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
    display["school"] = display.school.map(SHORT)
    display["status"] = display.status.map(STATUS)
    display['year_status'] = display.year_status.fillna('not_requested').map({'verified': '확인', 'not_requested': '상세 조회 대기', 'not_in_response': '응답에 없음', 'parse_failed': '추출 실패', 'conflict': '값 충돌'})
    columns = {"address": "매물", "school": "학군", "price": "호가 ($)", 'cut_amount': '인하액 ($)', 'cut_percent': '인하율 (%)', 'cut_date': '인하일', 'cut_basis': '인하 근거', "year_built": "건축연도", 'year_status': '연도 확인 상태',
               "bedrooms": "침실", "bathrooms": "욕실", "square_feet": "면적 (sqft)", "status": "상태", 'price_observed_at': '호가 확인 시각 (UTC)', "url": "원문"}
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
    st.caption("개별 집의 전체 관측 이력입니다. 왼쪽 가격·건축연도·조회 기간 필터를 벗어난 기록도 유지합니다.")
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
        st.caption(f"마지막 실제 관측: {home.observed_at} · 등록 건 ID: {home.episode_id}")
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
    st.caption("GitHub Actions가 매시간 작은 배치를 실행합니다. 미완료 페이지와 건축연도를 이어서 확인하며, 접근 제한 중에는 대기합니다. PC가 꺼져 있어도 실행됩니다.")
    st.link_button("GitHub 수집 실행 기록", "https://github.com/ladavid9989/data_science/actions/workflows/housing-collect.yml")
    for school in schools:
        subset = runs[runs.school == school]
        if subset.empty:
            st.warning(f"{SHORT[school]}: 관측 없음")
        else:
            last = subset.sort_values("observed_at").iloc[-1]
            st.write(f"**{SHORT[school]}** · 마지막 관측 {last.observed_at} · {last.quality} · {last.row_count}건")
            st.caption(last.note)
    health = range_runs[["market_date", "school", "quality", "row_count", "reported_count", "boundary_version", "note"]].copy()
    health["school"] = health.school.map(SHORT)
    st.dataframe(health.sort_values(["market_date", "school"], ascending=[False, True]), hide_index=True, width="stretch")
    st.info("Source complete: 해당 수집 가격 범위의 검색 페이지와 매물 수를 대조한 기록입니다. 배치 사이 시점 차이가 있으며, 학군 전체 시장을 보장하지 않습니다. Partial/Failed는 추이 통계에서 제외됩니다. 가격 범위를 벗어나 검색에서 사라진 집을 판매 완료로 보지 않습니다.")
    with st.expander("로컬 저장소와 가져오기"):
        st.code(str(db), language=None)
        st.markdown("관측 JSON과 원본 체크섬을 SQLite에 보관합니다. 기존 probe 원본은 DB 옆 raw 폴더에 압축 저장합니다. "
                    "백업 시 DB와 raw 폴더를 함께 보관하세요. 자세한 명령은 프로젝트 README에 있습니다.")

st.divider()
st.caption("SCHOOLSIDE · LOCAL PROTOTYPE  /  화면 새로고침은 저장된 기록만 읽습니다. 실시간 시세가 아닙니다.")
