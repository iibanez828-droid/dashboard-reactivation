
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

# ---------- UI FIX ----------
st.markdown("""
<style>
header {visibility: hidden;}
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
.block-container {padding-top: 1rem;}
</style>
""", unsafe_allow_html=True)

# ---------- LOAD DATA ----------
excel_path = "Data base Reactivation.xlsx"
xls = pd.ExcelFile(excel_path)

df = pd.read_excel(xls, sheet_name="Structural")
rules = pd.read_excel(xls, sheet_name="Rules & Rate")

# ---------- RULES MAPPING ----------
rules_map = dict(zip(rules.iloc[:,0], rules.iloc[:,1]))

# ---------- COMPONENT LOGIC (BB–BU approx) ----------
component_cols = df.columns[53:73]

for comp in component_cols:
    if comp in rules_map:
        df[comp] = (df[comp] >= rules_map[comp]).astype(int)

# ---------- BASIC KPIs ----------
total_cost = df.get("Total Cost", pd.Series([0])).sum()
avg_cost = df.get("Total Cost", pd.Series([0])).mean()

# ---------- TABS ----------
tab1, tab2 = st.tabs(["Fleet Overview", "Reactivation Gantt"])

# ---------- TAB 1 ----------
with tab1:
    st.title("Fleet Overview")
    st.metric("Total Fleet Cost", f"${total_cost:,.0f}")
    st.metric("Avg Cost per Truck", f"${avg_cost:,.0f}")
    st.dataframe(df, use_container_width=True)

# ---------- TAB 2 (GANTT) ----------
with tab2:
    st.title("Reactivation Gantt")

    start_date = st.date_input("Project Start Date")

    if "Labour_Hours" in df.columns and "Truck" in df.columns:
        gantt_df = df.copy()

        gantt_df["Start"] = pd.to_datetime(start_date)

        gantt_df = gantt_df.sort_values("Labour_Hours")

        starts = []
        current_start = pd.to_datetime(start_date)

        for i, row in gantt_df.iterrows():
            starts.append(current_start)
            duration = row["Labour_Hours"] / 24
            current_start = current_start + pd.Timedelta(days=max(duration - 10, 0))

        gantt_df["Start"] = starts
        gantt_df["Duration_Days"] = gantt_df["Labour_Hours"] / 24
        gantt_df["Finish"] = gantt_df["Start"] + pd.to_timedelta(gantt_df["Duration_Days"], unit="D")

        fig = px.timeline(
            gantt_df,
            x_start="Start",
            x_end="Finish",
            y="Truck",
            color="Total Cost" if "Total Cost" in gantt_df.columns else None,
        )

        fig.update_traces(
            text=[f"{h/24:.1f}d" for h in gantt_df["Labour_Hours"]],
            textposition="inside",
            customdata=list(zip(
                gantt_df["Finish"].astype(str),
                gantt_df["Labour_Hours"],
                gantt_df["Duration_Days"],
                gantt_df.get("Total Cost", [0]*len(gantt_df))
            )),
            hovertemplate="Truck: %{y}<br>Finish: %{customdata[0]}<br>Hours: %{customdata[1]}<br>Days: %{customdata[2]:.1f}<br>Cost: %{customdata[3]}"
        )

        fig.update_layout(height=700)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("Columns 'Labour_Hours' and 'Truck' required for Gantt.")
