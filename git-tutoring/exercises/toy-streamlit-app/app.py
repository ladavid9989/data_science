import pandas as pd
import streamlit as st

st.set_page_config(page_title="Git Tutorial Toy Dashboard", layout="wide")

st.title("Git Tutorial Toy Dashboard")
st.caption("A tiny Streamlit app for practicing Git commits, branches, and hosting.")

data = pd.read_csv("data/jobs.csv")

min_score = st.slider("Minimum score", min_value=0, max_value=100, value=70)
filtered = data[data["score"] >= min_score]

st.dataframe(filtered, use_container_width=True, hide_index=True)

st.write(f"Showing {len(filtered)} of {len(data)} rows.")
