"""
Landcros — Fleet Reactivation Dashboard
Read the Excel file and logo from the same directory as this script.
Run with: streamlit run dashboard_reactivation_modified.py
"""

import streamlit as st

st.set_page_config(
    page_title="Landcros — Fleet Reactivation",
    layout="wide",
    initial_sidebar_state="expanded",
)

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import base64
import os
from datetime import date
from pathlib import Path

# ─────────────────────────────────────────────────────────────────
#  PATHS  (files sit next to this script)
# ─────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
EXCEL_PATH_CANDIDATES = [
    BASE_DIR / "Data base Reactivation.xlsx",
    BASE_DIR / "Data_base_Reactivation.xlsx",
]
EXCEL_PATH = next((p for p in EXCEL_PATH_CANDIDATES if p.exists()), EXCEL_PATH_CANDIDATES[0])
LOGO_PATH_CANDIDATES = [
    BASE_DIR / "LANDCROS logo_orange_RGB-1.webp",
    BASE_DIR / "LANDCROS_logo_orange_RGB-1.webp",
]
LOGO_PATH = next((p for p in LOGO_PATH_CANDIDATES if p.exists()), LOGO_PATH_CANDIDATES[0])

@st.cache_data
def load_logo_b64():
    if not LOGO_PATH.exists():
        return None
    with open(LOGO_PATH, "rb") as f:
        return base64.b64encode(f.read()).decode()

@st.cache_data
def load_data():
    if not EXCEL_PATH.exists():
        st.error(f"Excel file not found: {EXCEL_PATH}. Put the Excel file in the same folder as this .py file.")
        st.stop()
    structural  = pd.read_excel(EXCEL_PATH, sheet_name="Structural")
    rules       = pd.read_excel(EXCEL_PATH, sheet_name="Rules & Rate")
    labour_sht  = pd.read_excel(EXCEL_PATH, sheet_name="Labour")
    comp_costs  = pd.read_excel(EXCEL_PATH, sheet_name="Component $")
    return structural, rules, labour_sht, comp_costs

LOGO_B64 = load_logo_b64()
structural, rules, labour_sht, comp_costs = load_data()

# ─────────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────────
CHM_RATE = 40.86   # USD/hr — from Rules & Rate column D

# Rules & Rate category → default threshold (column B, rows 1–5)
# Row 0: Hydraulic 0.65 | Row 1: Electrical 0.50 | Row 2: Final Drives 0.70
# Row 3: Engine 0.70   | Row 4: Body 0.70
CATEGORY_DEFAULTS = {
    "Hydraulic":    float(rules.loc[0, "Percentages"]),  # 0.65
    "Electrical":   float(rules.loc[1, "Percentages"]),  # 0.50
    "Final Drives": float(rules.loc[2, "Percentages"]),  # 0.70
    "Engine":       float(rules.loc[3, "Percentages"]),  # 0.70
    "Body":         float(rules.loc[4, "Percentages"]),  # 0.70
}

# Component → category  (used to pick the right threshold per slider)
COMP_CATEGORY = {
    "Accum front brake":     "Hydraulic",
    "Accum rear brake":      "Hydraulic",
    "Accum steer right":     "Hydraulic",
    "Accum steer left":      "Hydraulic",
    "Hoist cylinder right":  "Hydraulic",
    "Hoist cylinder left":   "Hydraulic",
    "Steer cylinder right":  "Hydraulic",
    "Steer cylinder left":   "Hydraulic",
    "Front strut right":     "Hydraulic",
    "Rear strtus right":     "Hydraulic",
    "Front strut left":      "Hydraulic",
    "Rear strut right":      "Hydraulic",
    "Rear strut left":       "Hydraulic",
    "Alternator":            "Electrical",
    "Eletrical motor right": "Electrical",
    "Eletrical motor left":  "Electrical",
    "Final Drive right":     "Final Drives",
    "Final Drive left":      "Final Drives",
    "Engine":                "Engine",
    "Operator Cab":          "Electrical",
    "Frame":                 "Body",
    "Body":                  "Body",
    "Body reapirs":          "Body",
    "Spindle right":         "Hydraulic",
    "Spindle left":          "Hydraulic",
}

CATEGORY_COLORS = {
    "Hydraulic":    "#FF6B00",
    "Electrical":   "#1A1A1A",
    "Final Drives": "#FF9340",
    "Engine":       "#FF4500",
    "Body":         "#888888",
}

# Flag column in Structural (.1 suffix) → component name in Component $
# Formula in Excel: =IF(Rules!$B$N <= life_col, 1, 0)
# where N is the row for that component's category
# Meaning: if threshold <= life% → flag = 1 (component needs work)
# As threshold rises, fewer components are flagged.
FLAG_COL_TO_COMP = {
    "Accum front brake.1":     "Accum front brake",
    "Accum rear brake.1":      "Accum rear brake",
    "Accum steer right.1":     "Accum steer right",
    "Accum steer left.1":      "Accum steer left",
    "Alternator.1":            "Alternator",
    "Operator Cab.1":          "Operator Cab",
    "Hoist cylinder right.1":  "Hoist cylinder right",
    "Hoist cylinder left.1":   "Hoist cylinder left",
    "Steer cylinder right.1":  "Steer cylinder right",
    "Steer cylinder left.1":   "Steer cylinder left",
    "Final Drive right.1":     "Final Drive right",
    "Final Drive left.1":      "Final Drive left",
    "Engine.1":                "Engine",
    "Eletrical motor right.1": "Eletrical motor right",
    "Eletrical motor left.1":  "Eletrical motor left",
    "Front strut right.1":     "Front strut right",
    "Rear strtus right.1":     "Rear strtus right",
    "Front strut left.1":      "Front strut left",
    "Rear strut left":         "Rear strut left",
    "Body reapirs":            "Body reapirs",
}

# Life % column in Structural for each component in Component $
COMP_LIFE_COL = {
    "Accum front brake":     "Accum front brake",
    "Accum rear brake":      "Accum rear brake",
    "Accum steer right":     "Accum steer right",
    "Accum steer left":      "Accum steer left",
    "Alternator":            "Alternator",
    "Operator Cab":          "Operator Cab",
    "Hoist cylinder right":  "Hoist cylinder right",
    "Hoist cylinder left":   "Hoist cylinder left",
    "Steer cylinder right":  "Steer cylinder right",
    "Steer cylinder left":   "Steer cylinder left",
    "Final Drive right":     "Final Drive right",
    "Final Drive left":      "Final Drive left",
    "Engine":                "Engine",
    "Eletrical motor right": "Eletrical motor right",
    "Eletrical motor left":  "Eletrical motor left",
    "Front strut right":     "Front strut right",
    "Rear strtus right":     "Rear strtus right",
    "Front strut left":      "Front strut left",
    "Rear strut left":       "Rear strut right",   # closest available col
    "Body reapirs":          "Body",
}

# ALL life-% columns in Structural (used for the life chart)
ALL_LIFE_COLS = [
    "Accum front brake", "Accum rear brake", "Accum steer right", "Accum steer left",
    "Alternator", "Operator Cab", "Frame",
    "Hoist cylinder right", "Hoist cylinder left",
    "Steer cylinder right", "Steer cylinder left",
    "Final Drive right", "Final Drive left",
    "Engine", "Eletrical motor right", "Eletrical motor left",
    "Spindle right", "Spindle left",
    "Front strut right", "Rear strtus right", "Front strut left", "Rear strut right",
    "Body",
]

KIT_COLS = [
    "Kits 1 A/C System", "Kit 2 Lube system", "Kit 3 Hydraulic filters & seal kits",
    "Kit 4 Operator Cab Monuting", "Kit 5 Drive system ", "Kit 6 Drive system elfa fan blower",
    "Kit 7 Drive system braking resistor", "Kit 8 Body Mounting & Pads", "Kit 9 Accum steer & Brake",
    "Kit 10 Brake Valve & Cooler mounting", "Kit 11 Front axle & MTG",
    "Kit 12 Frame Bottom plate optimized", "Kit 13 Frame upper plate optimized",
    "Kit 14 Frame left side optimized", "Kit 15 Frame right  side optimized ",
    "Kit 16 Hoist plate reinforment optmized", "Kit 17 Filtration drive system optmized",
    "Kit 18 Engine & Hardware", "Kit 19 Mirror bracket support ", "Kit 20 Fuel tank Bracket support",
]
KIT_LABELS = [
    "Kit 1 — A/C System", "Kit 2 — Lube System", "Kit 3 — Hydraulic Filters",
    "Kit 4 — Operator Cab", "Kit 5 — Drive System", "Kit 6 — Drive Elfa Fan",
    "Kit 7 — Braking Resistor", "Kit 8 — Body Mounting", "Kit 9 — Accum Steer & Brake",
    "Kit 10 — Brake Valve & Cooler", "Kit 11 — Front Axle & MTG", "Kit 12 — Frame Bottom Plate",
    "Kit 13 — Frame Upper Plate", "Kit 14 — Frame Left Side", "Kit 15 — Frame Right Side",
    "Kit 16 — Hoist Plate Reinf.", "Kit 17 — Filtration Drive", "Kit 18 — Engine & Hardware",
    "Kit 19 — Mirror Bracket", "Kit 20 — Fuel Tank Bracket",
]

# Component $ lookup
comp_data   = comp_costs.set_index("Name ")
labour_hrs  = labour_sht.iloc[0]   # row 0 = labour hours per kit
labour_cost = labour_sht.iloc[1]   # row 1 = parts cost per kit

# ─────────────────────────────────────────────────────────────────
#  BASE DATASET  (total cost uses original Excel values — no slider)
# ─────────────────────────────────────────────────────────────────
df_base = structural.copy()
# Total cost = (Total Labour hours × CHM rate) + pre-calculated truck cost from Excel
df_base["Total_Cost"] = df_base["Total Labour"] * CHM_RATE + df_base["Total cost per truck"]

# Core-truck filter is selected from the sidebar later.
# Default is Weighted criteria, but it can also be Hours.
df_sorted_base = df_base.sort_values(["Weighted criteria", "Total_Cost"], ascending=[True, True])
TOP19_DTS  = df_sorted_base.head(19)["DT"].astype(int).tolist()
REST11_DTS = df_sorted_base.iloc[19:]["DT"].astype(int).tolist()

# ─────────────────────────────────────────────────────────────────
#  CSS
# ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@300;400;600;700;800&family=Barlow:wght@300;400;500;600&display=swap');
html,body,[class*="css"]{font-family:'Barlow',sans-serif;background-color:#FFFFFF!important;color:#1A1A1A;}
[data-testid="stSidebar"]{background:#1A1A1A!important;border-right:3px solid #FF6B00;}
[data-testid="stSidebar"] *{color:#FFFFFF!important;}
[data-testid="stSidebar"] label{font-family:'Barlow Condensed',sans-serif;font-weight:600;font-size:0.82rem;letter-spacing:0.09em;text-transform:uppercase;color:#AAAAAA!important;}
[data-testid="stSidebar"] .stSlider{padding:0.2rem 0 0.9rem 0;}
[data-testid="stSidebar"] .stSlider [data-baseweb="slider"] [role="slider"]{background-color:#FF6B00!important;border-color:#FF6B00!important;}
[data-testid="stSidebar"] [data-testid="stSlider"] [data-baseweb="slider"] div[class*="thumb"]{background-color:#FF6B00!important;}
section[data-testid="stSidebar"] > div > div > div > button {
    display: block !important;
    visibility: visible !important;
    color: #FF6B00 !important;
    background: transparent;
    border: 1px solid #444;
    border-radius: 3px;
    font-family: 'Barlow Condensed', sans-serif;
    font-weight: 600;
    letter-spacing: 0.08em;
}
[data-testid="stTabs"] [role="tablist"]{border-bottom:2px solid #FF6B00;gap:0;}
[data-testid="stTabs"] button[role="tab"]{font-family:'Barlow Condensed',sans-serif;font-weight:700;font-size:0.9rem;letter-spacing:0.1em;text-transform:uppercase;color:#888888;padding:10px 24px;border-radius:0;background:transparent;}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"]{color:#FF6B00!important;border-bottom:3px solid #FF6B00;background:transparent;}
.lc-header{display:flex;align-items:center;justify-content:space-between;background:#1A1A1A;padding:18px 32px;border-bottom:4px solid #FF6B00;margin-bottom:24px;border-radius:0 0 4px 4px;}
.lc-header-title{font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:1.85rem;letter-spacing:0.04em;color:#FFFFFF;line-height:1.1;}
.lc-header-subtitle{font-family:'Barlow',sans-serif;font-weight:300;font-size:0.82rem;color:#AAAAAA;margin-top:3px;letter-spacing:0.07em;text-transform:uppercase;}
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px;}
.kpi-card{background:#F7F7F7;border-left:4px solid #FF6B00;padding:16px 18px 12px 18px;border-radius:2px;}
.kpi-label{font-family:'Barlow Condensed',sans-serif;font-weight:600;font-size:0.7rem;letter-spacing:0.13em;text-transform:uppercase;color:#888888;margin-bottom:5px;}
.kpi-value{font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:2rem;color:#1A1A1A;line-height:1;}
.kpi-sub{font-size:0.73rem;color:#888888;margin-top:4px;}
.section-title{font-family:'Barlow Condensed',sans-serif;font-weight:700;font-size:1rem;letter-spacing:0.11em;text-transform:uppercase;color:#1A1A1A;border-bottom:2px solid #FF6B00;padding-bottom:5px;margin-bottom:14px;margin-top:6px;}
.threshold-note{font-size:0.78rem;color:#666;background:#FFF4EC;border-left:3px solid #FF6B00;padding:8px 12px;margin-bottom:16px;border-radius:0 2px 2px 0;}
.truck-badge{display:inline-flex;align-items:center;gap:20px;background:#1A1A1A;padding:12px 24px;border-radius:3px;margin-bottom:18px;}
.truck-badge-dt{font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:2.2rem;color:#FF6B00;letter-spacing:0.05em;}
.truck-badge-label{font-family:'Barlow Condensed',sans-serif;font-weight:600;font-size:0.7rem;letter-spacing:0.12em;text-transform:uppercase;color:#888888;}
.truck-badge-val{font-family:'Barlow Condensed',sans-serif;font-weight:700;font-size:1.15rem;color:#FFFFFF;}
.truck-badge-sep{width:1px;height:36px;background:#444444;}
.block-container{padding-top:1rem!important;padding-left:2rem!important;padding-right:2rem!important;}
.sidebar-logo{display:flex;justify-content:center;padding:18px 16px 10px 16px;margin-bottom:10px;border-bottom:1px solid #333;}
.sidebar-logo img{max-width:150px;}
hr{border:none;border-top:1px solid #EFEFEF;margin:18px 0;}
header{visibility:hidden;}
#MainMenu,footer{visibility:hidden;}
.lc-footer{margin-top:28px;padding:14px 0;border-top:1px solid #EFEFEF;display:flex;justify-content:space-between;align-items:center;}
.lc-footer span{font-family:'Barlow Condensed',sans-serif;font-size:0.78rem;color:#CCCCCC;letter-spacing:0.07em;text-transform:uppercase;}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────
#  SIDEBAR
# ─────────────────────────────────────────────────────────────────
with st.sidebar:
    if LOGO_B64:
        st.markdown(
            f'<div class="sidebar-logo"><img src="data:image/webp;base64,{LOGO_B64}" alt="Landcros"/></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<div class="sidebar-logo"><b>LANDCROS</b></div>', unsafe_allow_html=True)

    # Sliders initialised from Rules & Rate default values
    t_hyd = st.slider("Hydraulic",    0.0, 1.0, CATEGORY_DEFAULTS["Hydraulic"],    0.01, format="%.2f")
    t_ele = st.slider("Electrical",   0.0, 1.0, CATEGORY_DEFAULTS["Electrical"],   0.01, format="%.2f")
    t_fd  = st.slider("Final Drives", 0.0, 1.0, CATEGORY_DEFAULTS["Final Drives"], 0.01, format="%.2f")
    t_eng = st.slider("Engine",       0.0, 1.0, CATEGORY_DEFAULTS["Engine"],       0.01, format="%.2f")
    t_bod = st.slider("Body",         0.0, 1.0, CATEGORY_DEFAULTS["Body"],         0.01, format="%.2f")

    thresholds = {
        "Hydraulic":    t_hyd,
        "Electrical":   t_ele,
        "Final Drives": t_fd,
        "Engine":       t_eng,
        "Body":         t_bod,
    }

    st.markdown("---")
    st.markdown("### Core Truck Filter")
    st.markdown(
        '<p style="font-size:0.77rem;color:#888;margin-bottom:10px;">'
        "Select how the core group of 19 trucks is chosen from the Structural sheet.</p>",
        unsafe_allow_html=True,
    )
    core_filter_metric = st.radio(
        "Select first 19 trucks by",
        options=["Weighted criteria", "Hours"],
        index=0,
        help="Both options select the 19 lowest values. Additional trucks can still be added below.",
    )
    core_sort_col = "Weighted criteria" if core_filter_metric == "Weighted criteria" else "Hours"
    df_sorted_core = df_base.sort_values([core_sort_col, "Total_Cost"], ascending=[True, True])
    TOP19_DTS = df_sorted_core.head(19)["DT"].astype(int).tolist()
    REST11_DTS = df_sorted_core.iloc[19:]["DT"].astype(int).tolist()

    st.markdown("---")
    st.markdown("### Additional Trucks")
    st.markdown(
        f'<p style="font-size:0.77rem;color:#888;margin-bottom:10px;">'
        f"The core filter keeps the 19 trucks with the lowest <b>{core_filter_metric}</b>. "
        "Trucks below are excluded — add them here to expand the analysis.</p>",
        unsafe_allow_html=True,
    )
    extra_dts = st.multiselect(
        "Include additional DTs",
        options=[int(x) for x in REST11_DTS],
        default=[],
    )

# -----------------------------------------------------------------
#  DYNAMIC COMPONENT COSTS
# -----------------------------------------------------------------
def _safe_component_value(row_label, comp_name):
    """Return value from Component $ sheet using Name as row and component as column."""
    try:
        if comp_name in comp_data.columns and row_label in comp_data.index:
            val = comp_data.loc[row_label, comp_name]
            return 0.0 if pd.isna(val) else float(val)
    except Exception:
        pass
    return 0.0

def component_total_cost(comp_name):
    """Component cost from Component $ sheet."""
    lh   = _safe_component_value("Labour hours", comp_name)
    lc   = _safe_component_value("Labour cost", comp_name)
    mech = _safe_component_value("Mechanized & Rebuild", comp_name)
    pts  = _safe_component_value("parts", comp_name)
    chr_ = _safe_component_value("Chrome tube & rod", comp_name)
    return (lh * lc) + mech + pts + chr_

COMP_TOTAL_COST = {c: component_total_cost(c) for c in set(FLAG_COL_TO_COMP.values())}

def apply_dynamic_component_costs(dataframe):
    """Recalculate component-related costs after threshold sliders update flags."""
    dataframe = dataframe.copy()
    dynamic_component_costs = []
    for _, row in dataframe.iterrows():
        total = 0.0
        for comp_name, unit_cost in COMP_TOTAL_COST.items():
            flag_col = f"_flag_{comp_name}"
            if flag_col in dataframe.columns:
                try:
                    if int(row.get(flag_col, 0)) == 1:
                        total += unit_cost
                except Exception:
                    pass
        dynamic_component_costs.append(total)

    dataframe["Cost per Components"] = dynamic_component_costs
    if "Total cost per kit" in dataframe.columns:
        dataframe["Total cost per truck"] = dataframe["Total cost per kit"].fillna(0) + dataframe["Cost per Components"].fillna(0)
    else:
        dataframe["Total cost per truck"] = dataframe["Cost per Components"].fillna(0)
    dataframe["Total_Cost"] = dataframe["Total Labour"].fillna(0) * CHM_RATE + dataframe["Total cost per truck"].fillna(0)
    return dataframe

# ─────────────────────────────────────────────────────────────────
#  ACTIVE DATASET
# ─────────────────────────────────────────────────────────────────

active_dts = list(dict.fromkeys(TOP19_DTS + [int(x) for x in extra_dts]))
df = df_base[df_base["DT"].isin(active_dts)].copy()
df.columns = df.columns.str.strip()

# ─────────────────────────────────────────────────────────────────
#  EXACT EXCEL FORMULA LOGIC
#  Reads BB:BU formulas and uses the real referenced life column
# ─────────────────────────────────────────────────────────────────

for flag_col, comp_name in FLAG_COL_TO_COMP.items():
    life_col = COMP_LIFE_COL.get(comp_name)
    cat      = COMP_CATEGORY.get(comp_name)

    if life_col and life_col in df.columns and cat in thresholds:
        thr = thresholds[cat]
        df[f"_flag_{comp_name}"] = (df[life_col] >= thr).astype(int)
    else:
        # 🚨 IMPORTANTE: no usar el flag original
        df[f"_flag_{comp_name}"] = 0

# ─────────────────────────────────────────────────────────────────
#  COSTOS DINÁMICOS
# ─────────────────────────────────────────────────────────────────

df = apply_dynamic_component_costs(df)

# ─────────────────────────────────────────────────────────────────
#  SORTING
# ─────────────────────────────────────────────────────────────────

df_cost_sorted  = df.sort_values("Total_Cost", ascending=False).reset_index(drop=True)
df_crack_sorted = df.sort_values("Weighted criteria", ascending=False).reset_index(drop=True)

# ─────────────────────────────────────────────────────────────────
#  HEADER
# ─────────────────────────────────────────────────────────────────
header_logo_html = (
    f'<img src="data:image/webp;base64,{LOGO_B64}" style="height:50px;" alt="Landcros"/>'
    if LOGO_B64 else
    '<div style="font-family:Barlow Condensed,sans-serif;font-size:2rem;font-weight:800;color:#FF6B00;">LANDCROS</div>'
)
st.markdown(
    f"""
    <div class="lc-header">
      <div>
        <div class="lc-header-title">EH5000 Fleet Reactivation</div>
        <div class="lc-header-subtitle">
          Component &amp; Cost Analysis by Truck
        </div>
      </div>
      {header_logo_html}
    </div>
    """,
    unsafe_allow_html=True,
)

tab_fleet, tab_truck, tab_kits, tab_gantt = st.tabs([
    "Fleet Overview", "Cost Analysis per Truck", "Kit Analysis", "Reactivation Gantt",
])

# ═══════════════════════════════════════════════════════════════
#  TAB 1 — FLEET OVERVIEW
# ═══════════════════════════════════════════════════════════════
with tab_fleet:
    total_fleet_cost = df["Total_Cost"].sum()
    avg_cost         = df["Total_Cost"].mean()
    avg_hours        = df["Hours"].mean()
    # Component count is threshold-sensitive
    total_flags = sum(
        int(df[f"_flag_{c}"].sum())
        for c in FLAG_COL_TO_COMP.values()
        if f"_flag_{c}" in df.columns
    )

    st.markdown(
        f"""
        <div class="kpi-grid">
          <div class="kpi-card"><div class="kpi-label">Total Fleet Cost</div>
            <div class="kpi-value">${total_fleet_cost:,.0f}</div>
            <div class="kpi-sub">USD — all active trucks</div></div>
          <div class="kpi-card"><div class="kpi-label">Avg Cost per Truck</div>
            <div class="kpi-value">${avg_cost:,.0f}</div>
            <div class="kpi-sub">USD per unit</div></div>
          <div class="kpi-card"><div class="kpi-label">Avg Operating Hours</div>
            <div class="kpi-value">{avg_hours:,.0f}</div>
            <div class="kpi-sub">hours per truck</div></div>
          <div class="kpi-card"><div class="kpi-label">Components to Replace</div>
            <div class="kpi-value">{total_flags}</div>
            <div class="kpi-sub">fleet total — current threshold</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Row 1: Cost chart + Components required ──
    c1, c2 = st.columns([1.3, 1], gap="large")

    with c1:
        st.markdown('<div class="section-title">Total Cost per Truck (USD) — Descending</div>', unsafe_allow_html=True)
        bar_colors = ["#FF6B00" if v == df_cost_sorted["Total_Cost"].max() else "#1A1A1A"
                      for v in df_cost_sorted["Total_Cost"]]
        fig_cost = go.Figure(go.Bar(
            x=df_cost_sorted["DT"].astype(str),
            y=df_cost_sorted["Total_Cost"],
            marker_color=bar_colors,
            text=[f"${v:,.0f}" for v in df_cost_sorted["Total_Cost"]],
            textposition="outside", textangle=-45,
            textfont=dict(size=8, family="Barlow Condensed", color="#1A1A1A"),
            hovertemplate="DT %{x}<br>Cost: $%{y:,.0f}<extra></extra>",
        ))
        fig_cost.update_layout(
            margin=dict(l=10, r=10, t=10, b=70), height=400,
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            font=dict(family="Barlow", color="#1A1A1A"),
            xaxis=dict(
                title="DT", type="category",
                categoryorder="array",
                categoryarray=df_cost_sorted["DT"].astype(str).tolist(),
                showgrid=False, tickfont=dict(size=9, family="Barlow Condensed"),
            ),
            yaxis=dict(title="Cost (USD)", showgrid=True, gridcolor="#F0F0F0", tickformat="$,.0f"),
            bargap=0.28,
        )
        st.plotly_chart(fig_cost, use_container_width=True, config={"displayModeBar": False})

    with c2:
        comp_counts = {}
        for cn in FLAG_COL_TO_COMP.values():
            fk  = f"_flag_{cn}"
            if fk in df.columns:
                cnt = int(df[fk].sum())
                if cnt > 0:
                    comp_counts[cn] = cnt
        comp_df = pd.DataFrame(
            sorted(comp_counts.items(), key=lambda x: x[1]),
            columns=["Component", "Count"],
        )
        comp_df["Category"] = comp_df["Component"].map(lambda c: COMP_CATEGORY.get(c, "Body"))
        comp_df["Color"]    = comp_df["Category"].map(CATEGORY_COLORS)
        fig_comp = go.Figure(go.Bar(
            y=comp_df["Component"], x=comp_df["Count"], orientation="h",
            marker_color=comp_df["Color"].tolist(),
            text=comp_df["Count"], textposition="outside",
            textfont=dict(size=10, family="Barlow Condensed"),
            hovertemplate="%{y}<br>Count: %{x}<extra></extra>",
        ))
        fig_comp.update_layout(
            margin=dict(l=10, r=40, t=10, b=10), height=400,
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            font=dict(family="Barlow", color="#1A1A1A"),
            xaxis=dict(showgrid=True, gridcolor="#F0F0F0", showline=False),
            yaxis=dict(tickfont=dict(size=9, family="Barlow Condensed"), showline=False, autorange="reversed"),
            bargap=0.25,
        )
        st.plotly_chart(fig_comp, use_container_width=True, config={"displayModeBar": False})

    # ── Row 2: Kits + Structural severity heatmap ──
    c3, c4 = st.columns([1, 1], gap="large")

    with c3:
        st.markdown('<div class="section-title">Total Kits Required — Fleet</div>', unsafe_allow_html=True)
        kit_totals = [
            {"Kit": lbl, "Trucks": int((df[kc] >= 1).sum())}
            for kc, lbl in zip(KIT_COLS, KIT_LABELS)
            if kc in df.columns
        ]
        kit_df = pd.DataFrame(kit_totals).sort_values("Trucks", ascending=True)
        kit_colors = [
            "#FF6B00" if v == kit_df["Trucks"].max()
            else "#FF9340" if v >= kit_df["Trucks"].quantile(0.75)
            else "#1A1A1A"
            for v in kit_df["Trucks"]
        ]
        fig_kits = go.Figure(go.Bar(
            y=kit_df["Kit"], x=kit_df["Trucks"], orientation="h",
            marker_color=kit_colors, text=kit_df["Trucks"], textposition="outside",
            textfont=dict(size=10, family="Barlow Condensed"),
            hovertemplate="%{y}<br>Trucks: %{x}<extra></extra>",
        ))
        fig_kits.update_layout(
            margin=dict(l=10, r=40, t=10, b=10), height=420,
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            font=dict(family="Barlow", color="#1A1A1A"),
            xaxis=dict(range=[0, len(df) * 1.2], showgrid=True, gridcolor="#F0F0F0", showline=False),
            yaxis=dict(tickfont=dict(size=9, family="Barlow Condensed"), showline=False),
            bargap=0.25,
        )
        st.plotly_chart(fig_kits, use_container_width=True, config={"displayModeBar": False})

    with c4:
        st.markdown('<div class="section-title">Structural Severity by Truck</div>', unsafe_allow_html=True)
        sev_cols   = ["High Arch Severity", "Nose Cone Severity", "Inside Web Plates Severity",
                      "Hoist Plates Severity", "Top & Bottom flange Severity"]
        sev_labels = ["High Arch", "Nose Cone", "Web Plates", "Hoist Plates", "Top/Bot Flange"]
        sev_data = df[["DT"] + sev_cols].set_index("DT")
        sev_data.columns = sev_labels
        fig_heat = go.Figure(go.Heatmap(
            z=sev_data.values, x=sev_labels, y=sev_data.index.astype(str),
            colorscale=[[0.0, "#2ECC71"], [0.5, "#FF9340"], [1.0, "#E74C3C"]],
            zmin=0, zmax=2,
            text=sev_data.values, texttemplate="%{text}",
            textfont=dict(size=10, family="Barlow Condensed", color="#FFFFFF"),
            hovertemplate="DT %{y} — %{x}<br>Severity: %{z}<extra></extra>",
            showscale=True,
            colorbar=dict(
                title="Level", tickvals=[0, 1, 2],
                ticktext=["0 — None", "1 — Moderate", "2 — Severe"],
                tickfont=dict(size=9),
            ),
        ))
        fig_heat.update_layout(
            margin=dict(l=10, r=10, t=10, b=10), height=420,
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            font=dict(family="Barlow", color="#1A1A1A", size=10),
            xaxis=dict(tickfont=dict(size=10, family="Barlow Condensed")),
            yaxis=dict(tickfont=dict(size=9, family="Barlow Condensed"), autorange="reversed"),
        )
        st.plotly_chart(fig_heat, use_container_width=True, config={"displayModeBar": False})

    # ── Row 3: Hours vs Cost + Weighted criteria bar ──
    c5, c6 = st.columns([1, 1], gap="large")

    with c5:
        st.markdown('<div class="section-title">Operating Hours vs Total Cost</div>', unsafe_allow_html=True)
        fig_scatter = go.Figure(go.Scatter(
            x=df["Hours"], y=df["Total_Cost"],
            mode="markers+text",
            text=df["DT"].astype(str), textposition="top center",
            textfont=dict(size=9, family="Barlow Condensed"),
            marker=dict(
                size=12, color=df["Weighted criteria"],
                colorscale=[[0, "#2ECC71"], [0.4, "#FF9340"], [1, "#E74C3C"]],
                showscale=True,
                colorbar=dict(title="Weighted<br>Criteria", tickfont=dict(size=9)),
                line=dict(width=1, color="#1A1A1A"),
            ),
            hovertemplate="DT %{text}<br>Hours: %{x:,.0f}<br>Cost: $%{y:,.0f}<extra></extra>",
        ))
        fig_scatter.update_layout(
            margin=dict(l=10, r=10, t=10, b=10), height=360,
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            font=dict(family="Barlow", color="#1A1A1A"),
            xaxis=dict(title="Operating Hours", showgrid=True, gridcolor="#F0F0F0"),
            yaxis=dict(title="Total Cost (USD)", showgrid=True, gridcolor="#F0F0F0", tickformat="$,.0f"),
        )
        st.plotly_chart(fig_scatter, use_container_width=True, config={"displayModeBar": False})

    with c6:
        st.markdown('<div class="section-title">Weighted Crack Criteria by Truck</div>', unsafe_allow_html=True)
        fig_crack = go.Figure(go.Bar(
            x=df_crack_sorted["DT"].astype(str),
            y=df_crack_sorted["Weighted criteria"],
            marker_color=[
                "#E74C3C" if v >= 0.5 else "#FF9340" if v >= 0.25 else "#2ECC71"
                for v in df_crack_sorted["Weighted criteria"]
            ],
            text=[f"{v:.3f}" if v > 0 else "" for v in df_crack_sorted["Weighted criteria"]],
            textposition="outside",
            textfont=dict(size=9, family="Barlow Condensed"),
            hovertemplate="DT %{x}<br>Weighted Criteria: %{y:.3f}<extra></extra>",
        ))
        for level, label, color in [(0.25, "Moderate", "#FF9340"), (0.50, "Severe", "#E74C3C")]:
            fig_crack.add_hline(
                y=level, line_dash="dot", line_color=color, line_width=1.5,
                annotation_text=label, annotation_position="top right",
                annotation_font=dict(size=9, color=color),
            )
        fig_crack.update_layout(
            margin=dict(l=10, r=10, t=10, b=10), height=360,
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            font=dict(family="Barlow", color="#1A1A1A"),
            xaxis=dict(
                title="DT", type="category",
                categoryorder="array",
                categoryarray=df_crack_sorted["DT"].astype(str).tolist(),
                tickfont=dict(size=9, family="Barlow Condensed"), showgrid=False,
            ),
            yaxis=dict(
                title="Weighted Criteria", showgrid=True, gridcolor="#F0F0F0",
                range=[0, max(df["Weighted criteria"].max() * 1.3, 0.6)],
            ),
            bargap=0.3,
        )
        st.plotly_chart(fig_crack, use_container_width=True, config={"displayModeBar": False})

    # ── Fleet detail table ──
    st.markdown("---")
    st.markdown('<div class="section-title">Fleet Cost Detail</div>', unsafe_allow_html=True)
    tbl = df[["DT", "Hours", "Weighted criteria", "Total Labour",
              "Total cost per kit", "Cost per Components",
              "Total cost per truck", "Total_Cost"]].copy().sort_values("Total_Cost")
    tbl.columns = ["DT", "Hours", "Weighted Criteria", "Labour Hrs",
                   "Kit Cost (USD)", "Component Cost (USD)", "Base Cost (USD)", "Total Cost (USD)"]
    tbl["DT"]    = tbl["DT"].astype(int)
    tbl["Hours"] = tbl["Hours"].map("{:,.0f}".format)
    tbl["Weighted Criteria"] = tbl["Weighted Criteria"].map("{:.3f}".format)
    for c in ["Kit Cost (USD)", "Component Cost (USD)", "Base Cost (USD)", "Total Cost (USD)"]:
        tbl[c] = tbl[c].map("${:,.0f}".format)
    st.dataframe(tbl, use_container_width=True, hide_index=True)

# ═══════════════════════════════════════════════════════════════
#  TAB 2 — COST ANALYSIS PER TRUCK
# ═══════════════════════════════════════════════════════════════
with tab_truck:
    all_dts = sorted([int(x) for x in df["DT"].tolist()])
    sel_dt  = st.selectbox("Select Truck (DT)", options=all_dts, format_func=lambda x: f"DT {x}")

    truck_row   = df[df["DT"] == sel_dt].iloc[0]
    truck_total = float(truck_row["Total_Cost"])
    truck_hrs   = float(truck_row["Hours"])
    truck_wc    = float(truck_row["Weighted criteria"])

    st.markdown(
        f"""
        <div class="truck-badge">
          <div><div class="truck-badge-label">Truck</div>
               <div class="truck-badge-dt">DT {int(sel_dt)}</div></div>
          <div class="truck-badge-sep"></div>
          <div><div class="truck-badge-label">Total Cost</div>
               <div class="truck-badge-val">${truck_total:,.0f} USD</div></div>
          <div class="truck-badge-sep"></div>
          <div><div class="truck-badge-label">Operating Hours</div>
               <div class="truck-badge-val">{truck_hrs:,.0f} hrs</div></div>
          <div class="truck-badge-sep"></div>
          <div><div class="truck-badge-label">Weighted Criteria</div>
               <div class="truck-badge-val">{truck_wc:.3f}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Build component list — ALL components (with life %) and active ones (with costs)
    all_comp_rows = []
    for flag_col, comp_name in FLAG_COL_TO_COMP.items():
        fk        = f"_flag_{comp_name}"
        is_active = int(truck_row.get(fk, truck_row.get(flag_col, 0))) == 1
        life_col  = COMP_LIFE_COL.get(comp_name)
        life_pct  = (float(truck_row[life_col]) if life_col
                     and life_col in truck_row.index
                     and pd.notna(truck_row[life_col]) else None)

        if comp_name in comp_data.columns:
            lh   = float(comp_data.loc["Labour hours",         comp_name])
            lc   = float(comp_data.loc["Labour cost",          comp_name])
            mech = float(comp_data.loc["Mechanized & Rebuild",  comp_name])
            pts  = float(comp_data.loc["parts",                comp_name])
            chr_ = float(comp_data.loc["Chrome tube & rod",    comp_name])
            lab_val = lh * lc
            total_c = lab_val + mech + pts + chr_
        else:
            lab_val = mech = pts = chr_ = total_c = 0.0

        all_comp_rows.append({
            "Component":          comp_name,
            "Category":           COMP_CATEGORY.get(comp_name, "Body"),
            "Life %":             life_pct,
            "Required":           is_active,
            "Labour Cost":        lab_val if is_active else 0.0,
            "Mechanized & Rebuild": mech if is_active else 0.0,
            "Parts":              pts  if is_active else 0.0,
            "Chrome Tube & Rod":  chr_ if is_active else 0.0,
            "Total":              total_c if is_active else 0.0,
        })

    cdf = pd.DataFrame(all_comp_rows)
    cdf["Life_pct_display"] = cdf["Life %"].fillna(0) * 100

    # ── Chart 1: Life % for ALL components (green → red by life value, orange border = required) ──
    st.markdown('<div class="section-title">Component Life % — All Components</div>', unsafe_allow_html=True)

    cdf_life = cdf.sort_values("Life_pct_display", ascending=True).reset_index(drop=True)

    def life_bar_color(row):
        v = row["Life_pct_display"]
        if v <= 30:   return "#2ECC71"
        if v <= 60:   return "#FF9340"
        return "#E74C3C"

    bar_life_colors     = cdf_life.apply(life_bar_color, axis=1).tolist()
    bar_line_colors     = ["#FF6B00" if r else "rgba(0,0,0,0)" for r in cdf_life["Required"]]
    bar_line_widths     = [2.5        if r else 0               for r in cdf_life["Required"]]

    fig_life = go.Figure(go.Bar(
        y=cdf_life["Component"],
        x=cdf_life["Life_pct_display"],
        orientation="h",
        marker=dict(
            color=bar_life_colors,
            line=dict(color=bar_line_colors, width=bar_line_widths),
        ),
        text=[f"{v:.1f}%" for v in cdf_life["Life_pct_display"]],
        textposition="outside",
        textfont=dict(size=9, family="Barlow Condensed"),
        hovertemplate="%{y}<br>Life: %{x:.1f}%<br>Required: %{customdata}<extra></extra>",
        customdata=["Yes" if r else "No" for r in cdf_life["Required"]],
    ))
    # Threshold reference lines
    for cat, thr in thresholds.items():
        fig_life.add_vline(
            x=thr * 100, line_dash="dot",
            line_color=CATEGORY_COLORS.get(cat, "#888"),
            line_width=1,
            annotation_text=f"{cat} {thr*100:.0f}%",
            annotation_position="top",
            annotation_font=dict(size=8, color=CATEGORY_COLORS.get(cat, "#888")),
        )
    fig_life.update_layout(
        margin=dict(l=10, r=80, t=30, b=10), height=560,
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        font=dict(family="Barlow", color="#1A1A1A"),
        xaxis=dict(
            title="Life (%)", range=[0, 115],
            showgrid=True, gridcolor="#F0F0F0", ticksuffix="%",
        ),
        yaxis=dict(tickfont=dict(size=9, family="Barlow Condensed"), autorange="reversed"),
        bargap=0.2,
    )
    st.plotly_chart(fig_life, use_container_width=True, config={"displayModeBar": False})

    st.markdown(
        '<p style="font-size:0.78rem;color:#888;margin-bottom:18px;">'
        "Color: <span style='color:#2ECC71;font-weight:700;'>green</span> = low life (good), "
        "<span style='color:#FF9340;font-weight:700;'>orange</span> = mid, "
        "<span style='color:#E74C3C;font-weight:700;'>red</span> = high life (needs work). "
        "Orange border = flagged for replacement at current threshold.</p>",
        unsafe_allow_html=True,
    )

    # ── Chart 2: Stacked cost composition — ALL components (zero-cost if not required) ──
    st.markdown('<div class="section-title">Cost Composition per Component — All Components</div>', unsafe_allow_html=True)

    cost_cats  = ["Labour Cost", "Mechanized & Rebuild", "Parts", "Chrome Tube & Rod"]
    bar_colors = ["#1A1A1A", "#FF6B00", "#FF9340", "#888888"]
    fig_stack  = go.Figure()

    for cat, color in zip(cost_cats, bar_colors):
        vals = cdf[cat].tolist()
        fig_stack.add_trace(go.Bar(
            name=cat, x=cdf["Component"], y=vals, marker_color=color,
            text=[f"${v:,.0f}" if v > 0 else "" for v in vals],
            textposition="inside",
            textfont=dict(size=8, family="Barlow Condensed", color="#FFFFFF"),
            hovertemplate=f"{cat}<br>%{{x}}<br>${{y:,.0f}}<extra></extra>",
        ))

    fig_stack.add_trace(go.Scatter(
        x=cdf["Component"], y=cdf["Total"], mode="text",
        text=[f"<b>${v:,.0f}</b>" if v > 0 else "" for v in cdf["Total"]],
        textposition="top center",
        textfont=dict(size=9, family="Barlow Condensed", color="#FF6B00"),
        showlegend=False, hoverinfo="skip",
    ))
    fig_stack.update_layout(
        barmode="stack",
        margin=dict(l=10, r=10, t=40, b=120), height=500,
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        font=dict(family="Barlow", color="#1A1A1A"),
        legend=dict(orientation="h", y=1.08, x=0, font=dict(size=10, family="Barlow Condensed")),
        xaxis=dict(tickangle=-40, tickfont=dict(size=8, family="Barlow Condensed"), showgrid=False),
        yaxis=dict(title="Cost (USD)", showgrid=True, gridcolor="#F0F0F0", tickformat="$,.0f"),
        bargap=0.25,
    )
    st.plotly_chart(fig_stack, use_container_width=True, config={"displayModeBar": False})

    # ── Cost summary KPIs ──
    required_cdf = cdf[cdf["Required"]]
    ca, cb, cc, cd = st.columns(4)
    totals_map = {
        "Labour Cost":          required_cdf["Labour Cost"].sum(),
        "Mechanized & Rebuild": required_cdf["Mechanized & Rebuild"].sum(),
        "Parts":                required_cdf["Parts"].sum(),
        "Chrome Tube & Rod":    required_cdf["Chrome Tube & Rod"].sum(),
    }
    for col_obj, (lbl, val) in zip([ca, cb, cc, cd], totals_map.items()):
        with col_obj:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">{lbl}</div>'
                f'<div class="kpi-value" style="font-size:1.45rem;">${val:,.0f}</div></div>',
                unsafe_allow_html=True,
            )

# ═══════════════════════════════════════════════════════════════
#  TAB 3 — KIT ANALYSIS
# ═══════════════════════════════════════════════════════════════
with tab_kits:
    all_dts_kit = sorted([int(x) for x in df["DT"].tolist()])
    sel_dt_kit  = st.selectbox("Select Truck (DT)", options=all_dts_kit,
                               format_func=lambda x: f"DT {x}", key="kit_sel")
    trk = df[df["DT"] == sel_dt_kit].iloc[0]

    st.markdown(
        f"""
        <div class="truck-badge">
          <div><div class="truck-badge-label">Truck</div>
               <div class="truck-badge-dt">DT {int(sel_dt_kit)}</div></div>
          <div class="truck-badge-sep"></div>
          <div><div class="truck-badge-label">Total Cost</div>
               <div class="truck-badge-val">${float(trk["Total_Cost"]):,.0f} USD</div></div>
          <div class="truck-badge-sep"></div>
          <div><div class="truck-badge-label">Operating Hours</div>
               <div class="truck-badge-val">{float(trk["Hours"]):,.0f} hrs</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    kit_rows = []
    for kit_col, label in zip(KIT_COLS, KIT_LABELS):
        if kit_col not in trk.index:
            continue
        qty = int(trk[kit_col])
        if qty < 1:
            continue
        lh_kit      = float(labour_hrs.get(kit_col, 0))
        lc_kit      = float(labour_cost.get(kit_col, 0))
        lab_total   = lh_kit * CHM_RATE * qty
        parts_total = lc_kit * qty
        kit_rows.append({
            "Kit":               label,
            "Quantity":          qty,
            "Labour Hours":      lh_kit * qty,
            "Labour Cost (USD)": lab_total,
            "Parts Cost (USD)":  parts_total,
            "Total Cost (USD)":  lab_total + parts_total,
        })

    if not kit_rows:
        st.info("No kits required for this truck.")
    else:
        kdf = pd.DataFrame(kit_rows)

        k1, k2, k3, k4 = st.columns(4)
        with k1:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">Total Kit Types</div>'
                f'<div class="kpi-value" style="font-size:1.6rem;">{len(kdf)}</div>'
                f'<div class="kpi-sub">types applied</div></div>', unsafe_allow_html=True)
        with k2:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">Total Quantity</div>'
                f'<div class="kpi-value" style="font-size:1.6rem;">{kdf["Quantity"].sum()}</div>'
                f'<div class="kpi-sub">units all kits</div></div>', unsafe_allow_html=True)
        with k3:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">Total Labour Cost</div>'
                f'<div class="kpi-value" style="font-size:1.6rem;">${kdf["Labour Cost (USD)"].sum():,.0f}</div>'
                f'<div class="kpi-sub">USD</div></div>', unsafe_allow_html=True)
        with k4:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">Total Kit Cost</div>'
                f'<div class="kpi-value" style="font-size:1.6rem;">${kdf["Total Cost (USD)"].sum():,.0f}</div>'
                f'<div class="kpi-sub">USD (labour + parts)</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        ck1, ck2 = st.columns([1.3, 1], gap="large")

        with ck1:
            st.markdown('<div class="section-title">Kit Cost Composition</div>', unsafe_allow_html=True)
            fig_ks = go.Figure()
            fig_ks.add_trace(go.Bar(
                name="Labour Cost", y=kdf["Kit"], x=kdf["Labour Cost (USD)"], orientation="h",
                marker_color="#1A1A1A",
                text=[f"${v:,.0f}" if v > 0 else "" for v in kdf["Labour Cost (USD)"]],
                textposition="inside", textfont=dict(size=9, family="Barlow Condensed", color="#FFFFFF"),
                hovertemplate="Labour<br>%{y}<br>$%{x:,.0f}<extra></extra>",
            ))
            fig_ks.add_trace(go.Bar(
                name="Parts Cost", y=kdf["Kit"], x=kdf["Parts Cost (USD)"], orientation="h",
                marker_color="#FF6B00",
                text=[f"${v:,.0f}" if v > 0 else "" for v in kdf["Parts Cost (USD)"]],
                textposition="inside", textfont=dict(size=9, family="Barlow Condensed", color="#FFFFFF"),
                hovertemplate="Parts<br>%{y}<br>$%{x:,.0f}<extra></extra>",
            ))
            fig_ks.update_layout(
                barmode="stack", margin=dict(l=10, r=40, t=10, b=10), height=460,
                paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                font=dict(family="Barlow", color="#1A1A1A"),
                legend=dict(orientation="h", y=1.06, x=0, font=dict(size=10, family="Barlow Condensed")),
                xaxis=dict(showgrid=True, gridcolor="#F0F0F0", tickformat="$,.0f"),
                yaxis=dict(tickfont=dict(size=9, family="Barlow Condensed"), autorange="reversed"),
                bargap=0.25,
            )
            st.plotly_chart(fig_ks, use_container_width=True, config={"displayModeBar": False})

        with ck2:
            st.markdown('<div class="section-title">Labour Hours per Kit</div>', unsafe_allow_html=True)
            fig_kh = go.Figure(go.Bar(
                y=kdf["Kit"], x=kdf["Labour Hours"], orientation="h",
                marker_color=[
                    "#FF6B00" if v == kdf["Labour Hours"].max()
                    else "#FF9340" if v >= kdf["Labour Hours"].quantile(0.75)
                    else "#1A1A1A"
                    for v in kdf["Labour Hours"]
                ],
                text=[f"{v:.0f} hrs" for v in kdf["Labour Hours"]],
                textposition="outside", textfont=dict(size=9, family="Barlow Condensed"),
                hovertemplate="%{y}<br>Labour: %{x:.0f} hrs<extra></extra>",
            ))
            fig_kh.update_layout(
                margin=dict(l=10, r=60, t=10, b=10), height=460,
                paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                font=dict(family="Barlow", color="#1A1A1A"),
                xaxis=dict(title="Labour Hours", showgrid=True, gridcolor="#F0F0F0"),
                yaxis=dict(tickfont=dict(size=9, family="Barlow Condensed"), autorange="reversed"),
                bargap=0.25,
            )
            st.plotly_chart(fig_kh, use_container_width=True, config={"displayModeBar": False})

        st.markdown('<div class="section-title">Total Cost per Kit (Sorted)</div>', unsafe_allow_html=True)
        ks = kdf.sort_values("Total Cost (USD)", ascending=False)
        fig_kt = go.Figure(go.Bar(
            x=ks["Kit"], y=ks["Total Cost (USD)"],
            marker_color=["#FF6B00" if v == ks["Total Cost (USD)"].max() else "#1A1A1A"
                          for v in ks["Total Cost (USD)"]],
            text=[f"${v:,.0f}" for v in ks["Total Cost (USD)"]],
            textposition="outside", textfont=dict(size=9, family="Barlow Condensed"),
            hovertemplate="%{x}<br>Total: $%{y:,.0f}<extra></extra>",
        ))
        fig_kt.update_layout(
            margin=dict(l=10, r=10, t=10, b=120), height=380,
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            font=dict(family="Barlow", color="#1A1A1A"),
            xaxis=dict(tickangle=-35, tickfont=dict(size=9, family="Barlow Condensed"), showgrid=False),
            yaxis=dict(title="Total Cost (USD)", showgrid=True, gridcolor="#F0F0F0", tickformat="$,.0f"),
            bargap=0.3,
        )
        st.plotly_chart(fig_kt, use_container_width=True, config={"displayModeBar": False})

        st.markdown('<div class="section-title">Kit Detail Table</div>', unsafe_allow_html=True)
        tbl_k = kdf.copy()
        tbl_k["Labour Hours"]      = tbl_k["Labour Hours"].map("{:.1f}".format)
        tbl_k["Labour Cost (USD)"] = tbl_k["Labour Cost (USD)"].map("${:,.0f}".format)
        tbl_k["Parts Cost (USD)"]  = tbl_k["Parts Cost (USD)"].map("${:,.0f}".format)
        tbl_k["Total Cost (USD)"]  = tbl_k["Total Cost (USD)"].map("${:,.0f}".format)
        st.dataframe(tbl_k, use_container_width=True, hide_index=True)

# ═══════════════════════════════════════════════════════════════
#  TAB 4 — REACTIVATION GANTT
# ═══════════════════════════════════════════════════════════════
with tab_gantt:
    st.markdown('<div class="section-title">Reactivation Gantt — Labour Duration by Truck</div>', unsafe_allow_html=True)

    gcol1, gcol2 = st.columns([1, 2], gap="large")
    with gcol1:
        gantt_start_date = st.date_input(
            "Project start date",
            value=date.today(),
            help="The schedule is recalculated from this start date. Each next truck starts before the previous truck finishes.",
        )
        overlap_days = st.slider("Overlap between trucks (days)", 0, 20, 10, 1)

    gantt_df = df[["DT", "Total Labour", "Total_Cost"]].copy()
    gantt_df = gantt_df.sort_values(["Total Labour", "Total_Cost"], ascending=[True, True]).reset_index(drop=True)
    gantt_df["Duration_Days"] = gantt_df["Total Labour"] / 24.0

    starts, finishes = [], []
    current_start = pd.Timestamp(gantt_start_date)
    for _, row in gantt_df.iterrows():
        duration_days = max(float(row["Duration_Days"]), 0.1)
        finish = current_start + pd.to_timedelta(duration_days, unit="D")
        starts.append(current_start)
        finishes.append(finish)
        current_start = finish - pd.Timedelta(days=overlap_days)

    gantt_df["Start"] = starts
    gantt_df["Finish"] = finishes
    gantt_df["Duration_ms"] = (gantt_df["Finish"] - gantt_df["Start"]).dt.total_seconds() * 1000
    gantt_df["DT_Label"] = gantt_df["DT"].astype(int).astype(str)
    gantt_df["Bar_Label"] = gantt_df.apply(
        lambda r: f'DT {int(r["DT"])} | {r["Duration_Days"]:.1f} d | {int(r["Total Labour"]):,} hrs | ${r["Total_Cost"]:,.0f}',
        axis=1,
    )

    # Simple timeline style restored from the previous working version.
    # X length = calendar duration; color intensity = labour hours.
    labour_norm = gantt_df["Total Labour"] / gantt_df["Total Labour"].max() if gantt_df["Total Labour"].max() > 0 else gantt_df["Total Labour"]
    bar_colors = [
        "#FF6B00" if v >= 0.85 else "#FF9340" if v >= 0.65 else "#1A1A1A"
        for v in labour_norm
    ]

    fig_gantt = go.Figure(go.Bar(
        x=gantt_df["Duration_ms"],
        y=gantt_df["DT_Label"],
        base=gantt_df["Start"],
        orientation="h",
        marker_color=bar_colors,
        text=gantt_df["Bar_Label"],
        textposition="inside",
        insidetextanchor="middle",
        textfont=dict(size=10, family="Barlow Condensed", color="#FFFFFF"),
        hovertemplate=(
            "DT %{y}<br>"
            "Start: %{base|%b %d, %Y}<br>"
            "Finish: %{customdata[0]}<br>"
            "Labour: %{customdata[1]:,.0f} hrs<br>"
            "Duration: %{customdata[2]:.1f} days<br>"
            "Total cost: $%{customdata[3]:,.0f}<extra></extra>"
        ),
        customdata=list(zip(
            gantt_df["Finish"].dt.strftime("%b %d, %Y"),
            gantt_df["Total Labour"],
            gantt_df["Duration_Days"],
            gantt_df["Total_Cost"],
        )),
    ))

    fig_gantt.update_layout(
        margin=dict(l=10, r=30, t=20, b=45),
        height=max(560, 34 * len(gantt_df)),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family="Barlow", color="#1A1A1A"),
        xaxis=dict(
            title="Schedule date",
            type="date",
            tickformat="%b-%d",
            showgrid=True,
            gridcolor="#F0F0F0",
            range=[gantt_df["Start"].min() - pd.Timedelta(days=3), gantt_df["Finish"].max() + pd.Timedelta(days=3)],
        ),
        yaxis=dict(
            title="Truck DT",
            type="category",
            categoryorder="array",
            categoryarray=gantt_df["DT_Label"].tolist(),
            autorange="reversed",
            tickfont=dict(size=9, family="Barlow Condensed"),
        ),
        bargap=0.22,
        showlegend=False,
    )
    st.plotly_chart(fig_gantt, use_container_width=True, config={"displayModeBar": False})

    cga, cgb, cgc, cgd = st.columns(4)
    with cga:
        st.markdown(f'<div class="kpi-card"><div class="kpi-label">First Start</div><div class="kpi-value" style="font-size:1.45rem;">{gantt_df["Start"].min():%b %d}</div></div>', unsafe_allow_html=True)
    with cgb:
        st.markdown(f'<div class="kpi-card"><div class="kpi-label">Final Finish</div><div class="kpi-value" style="font-size:1.45rem;">{gantt_df["Finish"].max():%b %d}</div></div>', unsafe_allow_html=True)
    with cgc:
        total_calendar_days = (gantt_df["Finish"].max() - gantt_df["Start"].min()).total_seconds() / 86400
        st.markdown(f'<div class="kpi-card"><div class="kpi-label">Calendar Span</div><div class="kpi-value" style="font-size:1.45rem;">{total_calendar_days:.1f} d</div></div>', unsafe_allow_html=True)
    with cgd:
        st.markdown(f'<div class="kpi-card"><div class="kpi-label">Total Labour Hours</div><div class="kpi-value" style="font-size:1.45rem;">{gantt_df["Total Labour"].sum():,.0f}</div><div class="kpi-sub">across all trucks</div></div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────
#  FOOTER
# ─────────────────────────────────────────────────────────────────
st.markdown(
    '<div class="lc-footer">'
    '<span>Landcros &mdash; Fleet Reactivation Analysis</span>'
    '<span>Data: Data base Reactivation.xlsx</span>'
    '</div>',
    unsafe_allow_html=True,
)
