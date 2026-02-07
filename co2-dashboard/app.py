import streamlit as st
import plotly.express as px
import pandas as pd
from data_fetcher import get_co2_data

# Page Config
st.set_page_config(
    page_title="Global CO2 Emissions",
    page_icon="🌍",
    layout="wide"
)

# Title and Description
st.title("🌍 Global CO2 Emissions Dashboard")
st.markdown("""
This dashboard visualizes CO2 emissions data from the World Bank.
Use the sidebar to filter by year, country, and metric.
""")

# Load Data
with st.spinner("Fetching data from World Bank API..."):
    df = get_co2_data()

# Sidebar Controls
st.sidebar.header("Filter Settings")

# 1. Region Filter
all_regions = sorted([r for r in df['Region'].dropna().unique() if r != ''])
selected_regions = st.sidebar.multiselect(
    "Select Region (Optional)",
    options=all_regions,
    default=[]
)

# 2. Income Group Filter
all_income_groups = sorted([i for i in df['IncomeGroup'].dropna().unique() if i != ''])
selected_income_groups = st.sidebar.multiselect(
    "Select Income Group (Optional)",
    options=all_income_groups,
    default=[]
)

# Filter data based on Region and Income BEFORE Country selection
df_filtered = df.copy()
if selected_regions:
    df_filtered = df_filtered[df_filtered['Region'].isin(selected_regions)]
if selected_income_groups:
    df_filtered = df_filtered[df_filtered['IncomeGroup'].isin(selected_income_groups)]

# Metric Selection
metric_options = {
    "Total Emissions (Mt)": "CO2_Total",
    "Emissions Per Capita (metric tons)": "CO2_PerCapita"
}
selected_metric_label = st.sidebar.radio("Select Metric", list(metric_options.keys()))
selected_metric = metric_options[selected_metric_label]

# Year Selection
min_year = int(df['Year'].min())
max_year = int(df['Year'].max())

# Default to most recent year with significant data (often data lags 1-3 years)
# Let's check max year in data or default to max_year - 3
default_year = max_year - 3 if max_year > 2020 else max_year

selected_year = st.sidebar.slider(
    "Select Year",
    min_value=min_year,
    max_value=max_year,
    value=default_year
)

# Country Selection
# Get unique countries from the FILTERED dataset
all_countries = sorted(df_filtered['Country'].unique())

# Default to top 5 emitters in the selected year and metric (within filtered scope)
df_year_filtered = df_filtered[df_filtered['Year'] == selected_year]

if not df_year_filtered.empty:
    top_countries = df_year_filtered.sort_values(by=selected_metric, ascending=False).head(5)['Country'].tolist()
else:
    top_countries = []

# If the previously selected default countries aren't in the new filtered list, reset them
# (Streamlit handles this, but good to be explicit for the default)

selected_countries = st.sidebar.multiselect(
    "Select Countries for Comparison",
    options=all_countries,
    default=top_countries
)

# Main Dashboard Area

# Row 1: Key Metrics & Map
col1, col2 = st.columns([1, 3])

# Filter data for selected year (using the fully filtered dataset)
# If no countries selected, do we show all filtered? 
# Usually map shows global/filtered scope.
# Line chart shows specific countries.

df_current_year = df_filtered[df_filtered['Year'] == selected_year].copy()
df_current_year.dropna(subset=[selected_metric], inplace=True)

with col1:
    scope_text = "Global"
    if selected_regions or selected_income_groups:
        scope_text = "Filtered"
        
    st.subheader(f"{scope_text} Stats ({selected_year})")
    if not df_current_year.empty:
        total_emissions = df_current_year[selected_metric].sum()
        
        # Format based on metric
        if selected_metric == "CO2_Total":
            st.metric(label=f"Total Emissions (Mt)", value=f"{total_emissions:,.0f}")
        else:
            avg_per_capita = df_current_year[selected_metric].mean()
            st.metric(label=f"Avg Emissions (tons/capita)", value=f"{avg_per_capita:.2f}")
            
        st.markdown(f"**Countries Reporting:** {len(df_current_year)}")
    else:
        st.warning("No data available for this year.")

with col2:
    st.subheader(f"Map - {selected_metric_label}")
    if not df_current_year.empty:
        fig_map = px.choropleth(
            df_current_year,

            locations="ISO3",
            color=selected_metric,
            hover_name="Country",
            color_continuous_scale=px.colors.sequential.Plasma,
            projection="natural earth",
            title=f"Global {selected_metric_label} ({selected_year})"
        )
        fig_map.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
        st.plotly_chart(fig_map, use_container_width=True)
    else:
        st.info("No data to display on map for this year.")

# Row 2: Trends & Rankings
st.divider()
col3, col4 = st.columns(2)

with col3:
    st.subheader("Trends Over Time")
    if selected_countries:
        # Filter for selected countries
        df_trends = df[df['Country'].isin(selected_countries)].copy()
        
        if not df_trends.empty:
            fig_line = px.line(
                df_trends,
                x="Year",
                y=selected_metric,
                color="Country",
                title=f"{selected_metric_label} Trend ({min_year}-{max_year})",
                markers=True
            )
            st.plotly_chart(fig_line, use_container_width=True)
        else:
            st.info("No data for selected countries.")
    else:
        st.info("Select countries in the sidebar to view trends.")

with col4:
    st.subheader(f"Top 10 Countries ({selected_year})")
    if not df_current_year.empty:
        top_10 = df_current_year.sort_values(by=selected_metric, ascending=False).head(10)
        fig_bar = px.bar(
            top_10,
            x=selected_metric,
            y="Country",
            orientation='h',
            title=f"Top 10 by {selected_metric_label}",
            color=selected_metric,
            color_continuous_scale=px.colors.sequential.Plasma
        )
        fig_bar.update_layout(yaxis={'categoryorder':'total ascending'})
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("No data available for rankings.")

# Raw Data Expander
with st.expander("View Raw Data"):
    st.dataframe(df)
