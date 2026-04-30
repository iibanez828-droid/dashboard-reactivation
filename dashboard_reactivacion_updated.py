# Updated dashboard_reactivacion.py

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

st.markdown("""
<style>
header {visibility: hidden;}
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
.block-container {padding-top: 1rem;}
</style>
""", unsafe_allow_html=True)

# LOAD EXCEL DIRECTLY
excel_path = "Data base Reactivation.xlsx"
xls = pd.ExcelFile(excel_path)

df_structural = pd.read_excel(xls, sheet_name="Structural")
df_rules = pd.read_excel(xls, sheet_name="Rules & Rate")

st.title("Reactivation Dashboard")

# MAP RULES
rules_map = dict(zip(df_rules.iloc[:,0], df_rules.iloc[:,1]))

# COMPONENT LOGIC (BB to BU approx)
component_cols = df_structural.columns[53:73]

for comp in component_cols:
    if comp in rules_map:
        df_structural[comp] = (df_structural[comp] >= rules_map[comp]).astype(int)

# GANTT
if "Labour_Hours" in df_structural.columns:
    df_gantt = df_structural.copy()
    df_gantt["Start"] = pd.to_datetime("2026-01-01")
    df_gantt["Duration_Days"] = df_gantt["Labour_Hours"] / 24
    df_gantt["Finish"] = df_gantt["Start"] + pd.to_timedelta(df_gantt["Duration_Days"], unit="D")

    fig = px.timeline(
        df_gantt,
        x_start="Start",
        x_end="Finish",
        y="Truck"
    )

    fig.update_traces(
        customdata=list(zip(
            df_gantt["Finish"].astype(str),
            df_gantt["Labour_Hours"],
            df_gantt["Duration_Days"]
        )),
        hovertemplate="Truck: %{y}<br>Finish: %{customdata[0]}<br>Hours: %{customdata[1]}<br>Days: %{customdata[2]:.1f}"
    )

    st.plotly_chart(fig, use_container_width=True)

st.dataframe(df_structural)
