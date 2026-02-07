# AGENTS.md - Project Status & Roadmap

## Project: CO2 Emission Dashboard
Visualize global CO2 emissions trends (1970-2023) using World Bank data.

### Current Status (Feb 07, 2026)
- **Dashboard Implementation**: Enhanced UI/UX with interactive filters (`app.py`).
  - Features: Global Map, Line Charts, Rankings, **Region & Income Filters**.
  - Logic: Data now filtered by Region/Income -> Country -> Year.
- **Data Pipeline**: `data_fetcher.py` enhanced to fetch `Region` and `IncomeGroup` metadata.
- **Dependencies**: `requirements.txt` remains unchanged.

### Accomplished Today
- Added interactive **Region** and **Income Group** filters to the sidebar.
- Updated `data_fetcher.py` to retrieve and map country metadata (Region, Income).
- Updated visualizations to reflect the filtered dataset scope (e.g., "Filtered Stats").
- Verified data fetching logic.

### Next Steps
1. **Performance Optimization**: Implement more aggressive caching or database storage for large datasets.
2. **Additional Metrics**: Include other greenhouse gases (Methane, Nitrous Oxide) if relevant.
3. **Deployment**: Prepare for deployment to Streamlit Cloud or similar platform.
4. **Further UI**: Add a "Download Data" button for the filtered dataset.
