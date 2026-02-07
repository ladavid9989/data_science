
import wbgapi as wb
import pandas as pd
import streamlit as st

@st.cache_data
def get_co2_data():
    """
    Fetches CO2 emissions data (Total and Per Capita) from World Bank API.
    
    Returns:
        pd.DataFrame: A dataframe with columns ['ISO3', 'Country', 'Region', 'IncomeGroup', 'Year', 'CO2_Total', 'CO2_PerCapita']
    """
    # Indicators (Updated to GHG series as classic EN.ATM.CO2E.KT is missing/issues)
    # EN.GHG.CO2.MT.CE.AR5: Carbon dioxide (CO2) emissions (total) excluding LULUCF (Mt CO2e)
    # EN.GHG.CO2.PC.CE.AR5: Carbon dioxide (CO2) emissions excluding LULUCF per capita (t CO2e/capita)
    indicators = {
        'EN.GHG.CO2.MT.CE.AR5': 'CO2_Total',
        'EN.GHG.CO2.PC.CE.AR5': 'CO2_PerCapita'
    }
    
    try:
        # Fetch data
        # labels=True includes Country names (but usually in a way that requires handling)
        # We'll fetch without labels first to keep structure clean, then map countries later.
        df = wb.data.DataFrame(indicators.keys(), economy='all', time='all', labels=False)
        
        # Current index: (economy, series)
        # Columns: Years (integers)
        
        # Reset index to make economy and series accessible
        df = df.reset_index()
        # Columns now: ['economy', 'series', 1970, 1971, ...]
        
        # Melt year columns to long format
        # ID vars are 'economy' and 'series'
        # All other columns are years
        id_vars = ['economy', 'series']
        value_vars = [c for c in df.columns if c not in id_vars]
        
        df_melt = df.melt(id_vars=id_vars, value_vars=value_vars, var_name='Year', value_name='Value')
        
        # Pivot to put series as columns
        # Index: economy, Year
        # Columns: series (values from 'series' column)
        # Values: Value
        df_pivot = df_melt.pivot_table(index=['economy', 'Year'], columns='series', values='Value').reset_index()
        
        # Rename series columns using our mapping
        df_pivot.rename(columns=indicators, inplace=True)
        
        # Rename economy to ISO3
        df_pivot.rename(columns={'economy': 'ISO3'}, inplace=True)
        
        # Fetch Country Metadata to get names and filter aggregates
        countries = wb.economy.DataFrame()
        # countries index is ISO3 id
        
        # identify aggregates
        # 'aggregate' column is boolean
        aggregates = countries[countries['aggregate'] == True].index.tolist()
        
        # Filter out aggregates
        df_clean = df_pivot[~df_pivot['ISO3'].isin(aggregates)].copy()
        
        # Get metadata mappings
        try:
            region_map = wb.region.Series().to_dict()
            income_map = wb.income.Series().to_dict()
        except:
            region_map = {}
            income_map = {}

        # Map country names, regions, and income levels
        country_map = countries['name'].to_dict()
        df_clean['Country'] = df_clean['ISO3'].map(country_map)
        
        # Map Region and Income (using the 'region' and 'incomeLevel' columns from countries df)
        # We need to map the codes in countries df to names first
        
        # Create a dict for ISO3 -> Region Name
        iso3_to_region = {}
        iso3_to_income = {}
        
        for iso3, row in countries.iterrows():
            region_code = row.get('region', '')
            income_code = row.get('incomeLevel', '')
            
            iso3_to_region[iso3] = region_map.get(region_code, region_code)
            iso3_to_income[iso3] = income_map.get(income_code, income_code)
            
        df_clean['Region'] = df_clean['ISO3'].map(iso3_to_region)
        df_clean['IncomeGroup'] = df_clean['ISO3'].map(iso3_to_income)
        
        # Reorder and select columns
        cols = ['ISO3', 'Country', 'Region', 'IncomeGroup', 'Year', 'CO2_Total', 'CO2_PerCapita']
        
        # Ensure all columns exist (in case one indicator failed completely, though unlikely if fetch worked)
        for col in cols:
            if col not in df_clean.columns:
                df_clean[col] = pd.NA
        
        df_clean = df_clean[cols]
        
        # Clean Year column (remove 'YR' prefix and convert to int)
        # Check if Year is string before replacing, just in case
        if df_clean['Year'].astype(str).str.startswith('YR').any():
             df_clean['Year'] = df_clean['Year'].astype(str).str.replace('YR', '').astype(int)
        
        # Sort
        df_clean.sort_values(by=['Country', 'Year'], inplace=True)
        
        return df_clean

    except Exception as e:

        # If running in streamlit, show error
        try:
            st.error(f"Failed to fetch data: {e}")
        except:
            pass
        print(f"Error in data fetcher: {e}")
        return pd.DataFrame()

if __name__ == "__main__":
    try:
        # Manually call the function logic if decorator fails? 
        # No, just run it. Streamlit prints a warning but runs.
        df = get_co2_data()
        print("Data fetched successfully!")
        print(df.head())
        print(f"Shape: {df.shape}")
        
    except Exception as e:
        print(f"Error: {e}")
