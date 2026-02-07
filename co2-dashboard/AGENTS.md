# AGENTS.md - Project Status & Roadmap

## Project: CO2 Emission Dashboard
Visualize global CO2 emissions trends (1970-2023) using World Bank data.

### Current Status (Feb 06, 2026)
- **Dashboard Implementation**: Completed initial version of Streamlit app (`app.py`).
  - Features: Global Map visualization, Line Charts for trends, Top 10 Rankings.
- **Data Pipeline**: Implemented robust fetcher (`data_fetcher.py`).
  - Source: Switched to World Bank GHG data (`EN.GHG.CO2.MT.CE.AR5`) after original CO2 series errors.
  - Optimization: Added caching to reduce API calls.
- **Dependencies**: Created `requirements.txt` with necessary libraries.

### Accomplished Today
- Built `data_fetcher.py` to handle API interactions and data cleaning.
- Developed `app.py` for interactive visualization.
- Debugged API "JSON decoding error" by migrating to available GHG indicators.
- Verified dashboard functionality locally.

### Next Steps
1. **Enhance UI/UX**: Add more interactive filters (e.g., by region, income group).
2. **Performance Optimization**: Implement more aggressive caching or database storage for large datasets.
3. **Additional Metrics**: Include other greenhouse gases (Methane, Nitrous Oxide) if relevant.
4. **Deployment**: Prepare for deployment to Streamlit Cloud or similar platform.
