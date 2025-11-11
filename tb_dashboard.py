import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="WHO Tuberculosis Dashboard", layout="wide")

# --- 1. Load and Wrangle WHO Data ---
@st.cache_data
def load_data():
    url = "https://raw.githubusercontent.com/ladavid9989/data_science/main/who.csv"
    who = pd.read_csv(url)

    # --- 당신의 wrangling 절차 반영 ---
    who_m = who.melt(
        id_vars=who.iloc[:, [0, 3]], 
        value_vars=who.iloc[:, 4:], 
        var_name="key", 
        value_name="cases"
    )

    who_m.dropna(inplace=True)
    who_m.reset_index(drop=True, inplace=True)

    # 표준화 및 분리
    who_m.key = who_m.key.str.replace("newrel", "new_rel").str.strip()
    who_m["new"] = who_m.key.str.split(pat="_", n=3, expand=True)[0]
    who_m["type"] = who_m.key.str.split(pat="_", n=3, expand=True)[1]
    who_m["sexage"] = who_m.key.str.split(pat="_", n=3, expand=True)[2]
    who_m.drop(columns=["new", "key"], inplace=True)

    # 성별, 연령대 분리
    who_m["sex"] = who_m.sexage.str.split(pat="", n=2, expand=True)[1]
    who_m["age"] = who_m.sexage.str.split(pat="", n=2, expand=True)[2]
    who_m.drop(columns=["sexage"], inplace=True)

    # 상위 4개국 추출
    big4 = who_m.groupby("country").cases.sum().sort_values(ascending=False).nlargest(n=4)
    who_sc = who_m.groupby(["country", "year", "sex"]).agg(agg_sum=("cases", "sum")).reset_index()
    big4_df = pd.merge(who_sc, big4, how="inner", on="country")

    return big4_df

# --- 2. Load data ---
big4_df = load_data()

# --- 3. Sidebar filters ---
st.sidebar.header("Filters")
countries = st.sidebar.multiselect(
    "Select Country", 
    sorted(big4_df["country"].unique()), 
    sorted(big4_df["country"].unique())
)
sexes = st.sidebar.multiselect(
    "Select Gender", 
    sorted(big4_df["sex"].unique()), 
    sorted(big4_df["sex"].unique())
)
year_range = st.sidebar.slider(
    "Select Year Range", 
    int(big4_df["year"].min()), 
    int(big4_df["year"].max()), 
    (1995, 2015)
)

# --- 4. Filtered Data ---
filtered = big4_df[
    (big4_df["country"].isin(countries)) &
    (big4_df["sex"].isin(sexes)) &
    (big4_df["year"].between(year_range[0], year_range[1]))
]

# --- 5. Layout ---
st.title("🌍 WHO Tuberculosis Dashboard")
st.markdown("""
Interactive exploration of tuberculosis cases across top 4 countries.  
Data source: WHO (via GitHub Repository)
""")

# --- 6. Visualization ---
fig = px.area(
    filtered,
    x="year",
    y="agg_sum",
    color="sex",
    facet_col="country",
    facet_col_wrap=2,
    title="Tuberculosis Cases (1995–2015) - World Health Organization",
    labels={"agg_sum": "Number of TB cases", "sex": "Gender"}
)
st.plotly_chart(fig, use_container_width=True)

# --- 7. Data Preview ---
st.subheader("📋 Data Preview")
st.dataframe(filtered.head(20))