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
from io import BytesIO
import plotly.express as px

# ─────────────────────────────────────────────────────────────────
#  PATHS  (files sit next to this script)
# ─────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
EXCEL_PATH_CANDIDATES = [
    BASE_DIR / "Data base Reactivation2.xlsx",
    BASE_DIR / "Data_base_Reactivation2.xlsx",
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

@st.cache_data(show_spinner="Loading Excel data...")
def load_data():
    if not EXCEL_PATH.exists():
        st.error(f"Excel file not found: {EXCEL_PATH}. Put the Excel file in the same folder as this .py file.")
        st.stop()

    # Performance improvement: open the workbook once and read all required sheets in a single call.
    # The previous version opened the same Excel file once per sheet on every cache miss.
    required_sheets = [
        "Structural",
        "Rules & Rate",
        "Labour",
        "Component $",
        "Summary Inventory",
        "Cerrejon inventory impact",
        "Component parts impact",
        "Inventory total",
    ]
    sheets = pd.read_excel(EXCEL_PATH, sheet_name=required_sheets, engine="openpyxl")

    structural = sheets["Structural"]
    rules = sheets["Rules & Rate"]
    labour_sht = sheets["Labour"]
    comp_costs = sheets["Component $"]
    kits_sht = sheets["Summary Inventory"]
    cerrejon_impact = sheets["Cerrejon inventory impact"]
    component_impact = sheets["Component parts impact"]
    inventory_total = sheets["Inventory total"]

    # Normalize string-based column names once. This fixes hidden mismatches such as
    # "Kit 5 Drive system " vs "Kit 5 Drive system" and makes every dashboard
    # section read the same Excel names. Numeric truck columns are preserved.
    for _df in sheets.values():
        _df.columns = [c.strip() if isinstance(c, str) else c for c in _df.columns]

    return structural, rules, labour_sht, comp_costs, kits_sht, cerrejon_impact, component_impact, inventory_total

LOGO_B64 = load_logo_b64()
structural, rules, labour_sht, comp_costs, kits_sht, cerrejon_impact, component_impact, inventory_total = load_data()

# ─────────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────────
CHM_RATE = 40.86   # USD/hr — from Rules & Rate column D

# Rules & Rate category → default threshold (column B, rows 1–5)
# Row 0: Hydraulic 0.65 | Row 1: Electrical 0.50 | Row 2: Final Drives 0.70
# Row 3: Engine 0.70   | Row 4: Strut 0.70   | Row 5: Body 0.70
CATEGORY_DEFAULTS = {
    "Hydraulic":    float(rules.loc[0, "Percentages"]),  # 0.65
    "Strut":        float(rules.loc[4, "Percentages"]),  # 0.70
    "Electrical":   float(rules.loc[1, "Percentages"]),  # 0.50
    "Final Drives": float(rules.loc[2, "Percentages"]),  # 0.70
    "Engine":       float(rules.loc[3, "Percentages"]),  # 0.70
    "Body":         float(rules.loc[4, "Percentages"]),  # 0.70 (using same as Strut per Excel structure)
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
    "Front strut right":     "Strut",
    "Rear strut right":      "Strut",
    "Front strut left":      "Strut",
    "Rear strut right":      "Strut",
    "Rear strut left":       "Strut",
    "Alternator":            "Electrical",
    "Electrical motor right": "Electrical",
    "Electrical motor left":  "Electrical",
    "Final Drive right":     "Final Drives",
    "Final Drive left":      "Final Drives",
    "Engine":                "Engine",
    "Operator Cab":          "Electrical",
    "Frame":                 "Body",
    "Body":                  "Body",
    "Body repairs":          "Body",
    "Spindle right":         "Hydraulic",
    "Spindle left":          "Hydraulic",
}



# ─────────────────────────────────────────────────────────────────
#  HELPER BAR CHART
# ─────────────────────────────────────────────────────────────────

def _category_summary(df, qty_col, value_col):
    tmp = df.copy()

    if "Category Item" not in tmp.columns:
        return pd.DataFrame(columns=["Category Item", qty_col, value_col])

    # If requested columns are missing, create zero-filled Series to avoid KeyError
    if qty_col not in tmp.columns:
        tmp[qty_col] = pd.Series(0, index=tmp.index)
    if value_col not in tmp.columns:
        tmp[value_col] = pd.Series(0, index=tmp.index)

    tmp[qty_col] = pd.to_numeric(tmp[qty_col], errors="coerce").fillna(0)
    tmp[value_col] = pd.to_numeric(tmp[value_col], errors="coerce").fillna(0)

    return (
        tmp.groupby("Category Item", as_index=False)
        .agg({
            qty_col: "sum",
            value_col: "sum"
        })
        .sort_values(value_col, ascending=False)
    )


def _render_category_cards(df, title):
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)

    if df.empty:
        st.info("No category data available")
        return

    cols = st.columns(min(len(df), 4))

    for idx, (_, row) in enumerate(df.head(4).iterrows()):
        with cols[idx]:
            qty_val = row.iloc[1]
            cost_val = row.iloc[2]

            st.markdown(
                f"""
                <div class="kpi-card">
                    <div class="kpi-label">{row["Category Item"]}</div>
                    <div class="kpi-value" style="font-size:1.2rem;">
                        {qty_val:,.0f}
                    </div>
                    <div class="kpi-sub">
                        ${cost_val:,.0f}
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )


def _bar_chart(
    df,
    x_col,
    y_col,
    title,
    y_title,
    prefix=""
):
    fig = px.bar(
        df,
        x=x_col,
        y=y_col,
        text=y_col,
    )

    fig.update_traces(
        texttemplate=prefix + "%{text:,.0f}",
        textposition="outside",
        marker_color="#FF6B00",
    )

    fig.update_layout(
        title=title,
        paper_bgcolor="white",
        plot_bgcolor="white",
        height=500,
        margin=dict(l=20, r=20, t=60, b=20),
        xaxis_title="",
        yaxis_title=y_title,
        showlegend=False,
        font=dict(
            family="Arial",
            size=14,
            color="black"
        )
    )

    return fig

CATEGORY_COLORS = {
    "Hydraulic":    "#FF6B00",
    "Electrical":   "#1A1A1A",
    "Final Drives": "#FF9340",
    "Engine":       "#FF4500",
    "Body":         "#888888",
    "Strut":        "#FFFF00",
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
    "Electrical motor right.1": "Electrical motor right",
    "Electrical motor left.1":  "Electrical motor left",
    "Front strut right.1":     "Front strut right",
    "Rear strut right.1":      "Rear strut right",
    "Front strut left.1":      "Front strut left",
    "Rear strut left.1":       "Rear strut left",
    "Body repairs.1":          "Body repairs",
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
    "Electrical motor right": "Electrical motor right",
    "Electrical motor left":  "Electrical motor left",
    "Front strut right":     "Front strut right",
    "Rear strut right":      "Rear strut right",
    "Front strut left":      "Front strut left",
    "Rear strut left":       "Rear strut left",
    "Body repairs":          "Body",
}

# ALL life-% columns in Structural (used for the life chart)
ALL_LIFE_COLS = [
    "Accum front brake", "Accum rear brake", "Accum steer right", "Accum steer left",
    "Alternator", "Operator Cab", "Frame",
    "Hoist cylinder right", "Hoist cylinder left",
    "Steer cylinder right", "Steer cylinder left",
    "Final Drive right", "Final Drive left",
    "Engine", "Electrical motor right", "Electrical motor left",
    "Spindle right", "Spindle left",
    "Front strut right", "Rear strut right", "Front strut left", "Rear strut left",
    "Body",
]

# Structural severity columns (for heatmaps and analysis)
SEVERITY_COLS = [
    "High Arch Severity",
    "Nose Cone Severity",
    "Inside Web Plates Severity",
    "Hoist Plates Severity",
    "Top & Bottom flange Severity",
]

SEVERITY_LABELS = [
    "High Arch",
    "Nose Cone",
    "Web Plates",
    "Hoist Plates",
    "Top/Bot Flange",
]

def _is_kit_col(col):
    return isinstance(col, str) and col.strip().lower().startswith(("kit ", "kits "))

def _kit_number(col):
    import re
    m = re.search(r"kit[s]?\s*(\d+)", str(col), flags=re.IGNORECASE)
    return int(m.group(1)) if m else 999

def _kit_label(col):
    text = str(col).strip()
    import re
    m = re.match(r"kit[s]?\s*(\d+)\s*(.*)", text, flags=re.IGNORECASE)
    if not m:
        return text
    num = int(m.group(1))
    desc = m.group(2).strip(" -–—")
    return f"Kit {num} — {desc}" if desc else f"Kit {num}"

# Kits are detected directly from Excel instead of a manual list.
# This guarantees that all 21 kits in Labour/Structural are available in the dashboard.
KIT_COLS = sorted(
    [c for c in labour_sht.columns if _is_kit_col(c) and c in structural.columns],
    key=_kit_number,
)
KIT_LABELS = [_kit_label(c) for c in KIT_COLS]

# Component $ lookup
comp_data   = comp_costs.set_index("Name")
# Safe guards: labour_sht may be empty or have fewer than two rows in some edge cases.
labour_hrs = labour_sht.iloc[0] if len(labour_sht) > 0 else pd.Series(dtype=float)
labour_cost = labour_sht.iloc[1] if len(labour_sht) > 1 else pd.Series(dtype=float)

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
[data-testid="stSidebar"] h3{color:#FF6B00!important;font-weight:700!important;text-transform:uppercase!important;letter-spacing:0.08em!important;}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{color:#FF6B00!important;font-weight:600!important;}
[data-testid="stSidebar"] [data-testid="stDownloadButton"] button{background-color:#CCCCCC!important;color:#FF6B00!important;border:2px solid #FF6B00!important;font-weight:700!important;padding:10px 16px!important;border-radius:4px!important;}
[data-testid="stSidebar"] [data-testid="stDownloadButton"] button:hover{background-color:#AAAAAA!important;}
/* ── PDF menu: selectbox selected value & input text ── */
[data-testid="stSidebar"] [data-baseweb="select"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-baseweb="select"] span,
[data-testid="stSidebar"] [data-baseweb="select"] div[class*="ValueContainer"] *,
[data-testid="stSidebar"] [data-baseweb="select"] input,
[data-testid="stSidebar"] [data-testid="stSelectbox"] span{color:#1A1A1A!important;}
/* ── PDF menu: selectbox control background so dark text is readable ── */
[data-testid="stSidebar"] [data-baseweb="select"] > div:first-child{background-color:#F7F7F7!important;border:1px solid #FF6B00!important;}
/* ── PDF menu: dropdown list portal (renders outside sidebar DOM) ── */
[data-baseweb="popover"] [role="listbox"],
[data-baseweb="popover"] [role="option"],
[data-baseweb="menu"] li,
[data-baseweb="menu"] [role="option"]{background-color:#FFFFFF!important;color:#1A1A1A!important;}
[data-baseweb="popover"] [role="option"]:hover,
[data-baseweb="menu"] [role="option"]:hover{background-color:#FFF4EC!important;color:#FF6B00!important;}
[data-baseweb="popover"] [aria-selected="true"],
[data-baseweb="menu"] [aria-selected="true"]{background-color:#FF6B00!important;color:#FFFFFF!important;}
/* ── PDF menu: chevron/arrow icon stays visible ── */
[data-testid="stSidebar"] [data-baseweb="select"] svg{fill:#FF6B00!important;}
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
#MainMenu,footer{visibility:hidden;}
.lc-footer{margin-top:28px;padding:14px 0;border-top:1px solid #EFEFEF;display:flex;justify-content:space-between;align-items:center;}
.lc-footer span{font-family:'Barlow Condensed',sans-serif;font-size:0.78rem;color:#CCCCCC;letter-spacing:0.07em;text-transform:uppercase;}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────
#  SIDEBAR (NATIVO STREAMLIT)
# ─────────────────────────────────────────────────────────────────

with st.sidebar:

    # ────────────────
    # LOGO
    # ────────────────
    if LOGO_B64:
        st.markdown(
            f'<div class="sidebar-logo"><img src="data:image/webp;base64,{LOGO_B64}" alt="Landcros"/></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="sidebar-logo"><b>LANDCROS</b></div>',
            unsafe_allow_html=True
        )

    st.markdown("---")

    # ────────────────
    # THRESHOLDS
    # ────────────────
    st.markdown("### Component Thresholds")

    t_hyd = st.slider("Hydraulic",    0.0, 1.0, CATEGORY_DEFAULTS["Hydraulic"],    0.01, format="%.2f")
    t_strut = st.slider("Strut",      0.0, 1.0, CATEGORY_DEFAULTS["Strut"],        0.01, format="%.2f")
    t_ele = st.slider("Electrical",   0.0, 1.0, CATEGORY_DEFAULTS["Electrical"],   0.01, format="%.2f")
    t_fd  = st.slider("Final Drives", 0.0, 1.0, CATEGORY_DEFAULTS["Final Drives"], 0.01, format="%.2f")
    t_eng = st.slider("Engine",       0.0, 1.0, CATEGORY_DEFAULTS["Engine"],       0.01, format="%.2f")
    t_bod = st.slider("Body",         0.0, 1.0, CATEGORY_DEFAULTS["Body"],         0.01, format="%.2f")

    thresholds = {
        "Hydraulic":    t_hyd,
        "Strut":        t_strut,
        "Electrical":   t_ele,
        "Final Drives": t_fd,
        "Engine":       t_eng,
        "Body":         t_bod,
    }

    st.markdown("---")

    # ────────────────
    # CORE FILTER
    # ────────────────
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
    )

    core_sort_col = "Weighted criteria" if core_filter_metric == "Weighted criteria" else "Hours"

    df_sorted_core = df_base.sort_values(
        [core_sort_col, "Total_Cost"],
        ascending=[True, True]
    )

    TOP19_DTS = df_sorted_core.head(19)["DT"].astype(int).tolist()
    REST11_DTS = df_sorted_core.iloc[19:]["DT"].astype(int).tolist()

    st.markdown("---")

    # ────────────────
    # ADDITIONAL TRUCKS
    # ────────────────
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
    """Recalculate component-related costs after threshold sliders update flags.

    Optimized version: use vectorized pandas dot product instead of iterating
    truck-by-truck and component-by-component on every Streamlit rerun.
    """
    dataframe = dataframe.copy()

    flag_cols = []
    unit_costs = []
    for comp_name, unit_cost in COMP_TOTAL_COST.items():
        flag_col = f"_flag_{comp_name}"
        if flag_col in dataframe.columns:
            flag_cols.append(flag_col)
            unit_costs.append(float(unit_cost))

    if flag_cols:
        flags = (
            dataframe[flag_cols]
            .apply(pd.to_numeric, errors="coerce")
            .fillna(0)
            .clip(lower=0, upper=1)
        )
        dataframe["Cost per Components"] = flags.dot(np.asarray(unit_costs, dtype=float))
    else:
        dataframe["Cost per Components"] = 0.0

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
#  SUSPENSION COST SUMMARY HELPERS
# ─────────────────────────────────────────────────────────────────
SUSPENSION_GROUPS = {
    "Front Suspensions": ["Front strut right", "Front strut left"],
    "Rear Suspensions": ["Rear strut right", "Rear strut left"],
}

SUSPENSION_COST_LABELS = {
    "Labour": "Labour Cost",
    "Parts": "Parts",
    "Chrome Tube and Rod": "Chrome Tube & Rod",
    "Mechanized and Rebuild": "Mechanized & Rebuild",
}

def _component_cost_breakdown(comp_name):
    labour_hours = _safe_component_value("Labour hours", comp_name)
    labour_rate = _safe_component_value("Labour cost", comp_name)
    return {
        "Labour Cost": labour_hours * labour_rate,
        "Parts": _safe_component_value("parts", comp_name),
        "Chrome Tube & Rod": _safe_component_value("Chrome tube & rod", comp_name),
        "Mechanized & Rebuild": _safe_component_value("Mechanized & Rebuild", comp_name),
    }

def build_suspension_cost_summary(dataframe):
    """Build suspension cost KPIs using vectorized flag counts."""
    summary = {
        cost_key: {
            "front_cost": 0.0,
            "rear_cost": 0.0,
            "total_cost": 0.0,
            "front_count": 0,
            "rear_count": 0,
            "total_count": 0,
        }
        for cost_key in SUSPENSION_COST_LABELS.values()
    }

    for group_name, components in SUSPENSION_GROUPS.items():
        group_key = "front" if group_name.startswith("Front") else "rear"
        for comp_name in components:
            flag_col = f"_flag_{comp_name}"
            if flag_col not in dataframe.columns:
                continue
            required_count = int(pd.to_numeric(dataframe[flag_col], errors="coerce").fillna(0).clip(0, 1).sum())
            if required_count == 0:
                continue

            cost_breakdown = _component_cost_breakdown(comp_name)
            for cost_key, cost_value in cost_breakdown.items():
                summary[cost_key][f"{group_key}_cost"] += required_count * float(cost_value)
                summary[cost_key]["total_cost"] += required_count * float(cost_value)
                summary[cost_key][f"{group_key}_count"] += required_count
                summary[cost_key]["total_count"] += required_count

    return summary

def render_suspension_kpi_card(title, values):
    return f"""
    <div class="kpi-card" style="height:100%;">
      <div class="kpi-label">{title}</div>
      <div style="display:grid;grid-template-columns:1fr;gap:8px;margin-top:10px;">
        <div style="border-bottom:1px solid #EFEFEF;padding-bottom:7px;">
          <div class="kpi-sub">Front suspensions</div>
          <div class="kpi-value" style="font-size:1.35rem;">${values["front_cost"]:,.0f}</div>
          <div class="kpi-sub">{values["front_count"]} components to repair</div>
        </div>
        <div style="border-bottom:1px solid #EFEFEF;padding-bottom:7px;">
          <div class="kpi-sub">Rear suspensions</div>
          <div class="kpi-value" style="font-size:1.35rem;">${values["rear_cost"]:,.0f}</div>
          <div class="kpi-sub">{values["rear_count"]} components to repair</div>
        </div>
        <div>
          <div class="kpi-sub">Total fleet suspensions</div>
          <div class="kpi-value" style="font-size:1.45rem;color:#FF6B00;">${values["total_cost"]:,.0f}</div>
          <div class="kpi-sub">{values["total_count"]} total components to repair</div>
        </div>
      </div>
    </div>
    """


# ─────────────────────────────────────────────────────────────────
#  PDF REPORT HELPERS
# ─────────────────────────────────────────────────────────────────
REPORT_TABS = [
    "Fleet Overview",
    "Cost Analysis per Truck",
    "Kit Analysis",
    "Reactivation Gantt",
    "Inventory Analysis",
    "Part List",
]


def _format_usd(value):
    try:
        return f"${float(value):,.0f}"
    except Exception:
        return "$0"


# ── Sidebar config snapshot ──────────────────────────────────────────
def _sidebar_config_text(thresholds, core_filter_metric, extra_dts):
    """Return a one-line summary of the current sidebar configuration."""
    thr_parts = ", ".join(f"{k}: {v*100:.0f}%" for k, v in thresholds.items())
    extra = ", ".join(str(d) for d in extra_dts) if extra_dts else "none"
    return (
        f"Filter: {core_filter_metric}  |  "
        f"Thresholds — {thr_parts}  |  "
        f"Extra DTs: {extra}"
    )


# ── Branded page template — based on HTM_letterhead_LANDCROS.docx ────
# Hitachi logo (header, right) — cropped from image2.wmf in the letterhead
_HITACHI_LOGO_B64 = "iVBORw0KGgoAAAANSUhEUgAAAncAAAEOCAYAAADrDzH2AAA6KUlEQVR4nO3deVxU5f4H8M+wCSgqiigooCYuaK5kmguaWu5maaaW5r5WdutXtmrL1XDXcqnbzS1bLE3LstzSbqm5lCuKKO4iqKCyCLLM74/nckWZc+bMnGcWDp/368XL4sw85wFmznzPs3y/JrPZbAYRERERGYKHqztARERERPIwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBeLm6A0RE5BiXL19Gamoq0tLS/vdvVlYWypQpg4oVK6JChQqoUKECAgMDUbVqVZQtW9bVXSYiCRjcERGVcCdPnsTevXtx9OhRJCQk4OTJk0hISEB6errmNjw8PFC3bl00a9YMTZs2RfPmzdGsWTNUrlzZgT0nIkcwsbZsyTBo0CCcPn1aVxurVq1C7dq1JfXIfomJiRg8eLCuNmrVqoUvvvjC5uc988wzOHnypK5zr169GmFhYcW+P3DgQJw5c0ZX20YzfPhwjBo1yq7nvvbaa9i8ebPU/nTu3BkffPCB1DadLS8vDzt37sTWrVuxd+9e7NmzB9euXXPIuUwmE6KiotChQwfExMSgffv2qFq1qkPOZUlCQgKGDBmiq406depg5cqVknqkjyOvP2pcec0l1+DIXQlx4MABHDt2TFcbWVlZknqjT1ZWFnbv3q2rjRs3btj1vIMHD+Lw4cO6zn3r1i2L3//7778RHx+vq22j6dy5s13Pu3jxIubMmYPbt29L7c+hQ4cwfvx4hIeHS23X0a5cuYKNGzfip59+wqZNm5CWluaU85rNZhw9ehRHjx7FwoULAQBRUVEYOHAghg8fjtDQUIeePzMzU/e1IjMzU1Jv9HPk9UeNK6+55BrcUEFEbmfu3LnSAzsAyM3Nxfz586W36yhnz57F+PHjERYWhqFDh+Lrr792WmCnJC4uDm+99RYiIiLQt29f/PzzzygoKHBpn4jobgzuiMit3LhxA59++qnD2v/4448dNo0pS3p6Ol5//XXUr18fixcvRk5Ojqu7VExeXh7WrVuHbt26oU6dOoiNjcXVq1dd3S0iAoM7InIzH330kUOngDIzM7F48WKHta/X+vXrUa9ePUyfPh3Z2dmu7o4mp0+fxuTJkxEWFobJkyeXmH4TGRWDOyJyG9nZ2fjoo48cfp558+a51VosALh+/TqeffZZPPbYY0hKSnJ1d+ySnZ2N2NhYREdH615bRkT2Y3BHRG7js88+w+XLlx1+nmvXrmHZsmUOP49WGzZsQMOGDbF8+XJXd0WKo0eP4qGHHsL69etd3RWiUonBHRG5hfz8fMydO9dp55s9ezby8vKcdj4lixYtQu/evXHp0iVXd0WqjIwMPP7441i0aJGru0JU6jAVChG5hdWrV+vOAWaL06dPY/Xq1Rg0aJDTznmvRYsWYeLEiXBUulGTyYTQ0FAEBQUhKCgIwcHBCAgIQGpqKi5fvoyUlBScO3fOYWvkCgoKMHHiRJhMJowbN84h5yCi4hjcEZFbmDVrltPPGRsbi4EDB8JkMjn93I4K7Jo0aYKYmBjExMSgXbt2qFKliurj8/PzcerUKRw6dAhHjhzB8uXLpSbjNpvNeO6559C0aVO0bt1aWrtEpIzTskTkcr/88gv++usvp5/30KFD+OWXX5x+3jVr1kgN7Ly8vDBmzBgcPXoUBw4cwPz58/H4449bDewAwNPTE3Xr1kW/fv0wdepUxMfHY8mSJTZXQVCTn5+P4cOHcxctkZNw5I5IkmXLljllB+bw4cNx7tw5XW0888wzGDp0qKQeKatVq5amx82YMcPuc3h7e6Nx48bYv3+/Xc+PjY1F165d7T6/rZKTkzFu3DhpgV2LFi2wdOlS3H///VLa8/HxwZgxYzBo0CA899xz0jZ5HD9+HDNmzMDbb78tpT0iUsbgjkiSVq1aOeU8/v7+utuoWbMmOnXqJKE3+u3duxfbtm2z+/mPP/44+vXrh/79+9v1/O3bt2PXrl1OmzIcN24crly5IqWtXr164csvv0TZsmWltFdUQEAAli1bhi5duuDZZ5+VsvkkNjYWQ4cORUREhIQeEpESTssSkUt98MEHup4/fvx4PPbYY7rqnM6cOVNXH7T6+uuv8d1330lpa9SoUfjuu+8cEtgVNXjwYMybN09KW1lZWZg6daqUtohIGYM7InKZ+Ph4rFu3zu7nR0VFoV27dvDy8tI1zbxu3TrExcXZ/Xwtrly5gueee05KW3369MHixYvh6ekppT1rJkyYgOHDh0tp66uvvmKZMiIHY3BHRC4zc+ZMXUXnJ0yY8L+drqNGjYKHh32XNLPZjNmzZ9vdDy0mTpwoZTq2ZcuW+OKLL5wW2BWaNm2alFHC7Oxst0ogTWREDO6IyCUuX76MVatW2f38cuXK4emnn/7f/9eqVQtdunSxu72VK1fq3qiiZNu2bVi9erXudry9vbF27Vop6y5tVbVqVUycOFFKW6xcQeRYDO6IyCXmzJmjKzXGkCFDUL58+bu+N3r0aLvby83NxYIFC+x+vhpZlTd69+6N6tWrS2nLHpMmTZKSE3DXrl1ITU2V0CMisoTBHRE53c2bN/HJJ5/oamPs2LHFvte7d29dGyuWLFmCa9eu6elWMYmJifjpp5+ktDVq1Cgp7dirWrVqaNq0qe528vPz7U5dQ0TWMbgjIqdbuHAhbty4Yffz27dvbzGvm5eXF4YNG2Z3u5mZmViyZIndz7fkhx9+0LWusFBERISuaWdZZKXQOXbsmJR2iKg4BndE5FQ5OTn48MMPdbUxfvx4xWOjR4/WtdlgwYIFuHXrlt3Pv9fGjRultDNw4EC7N4zIFBUVJaUdBndEjsMkxkTkVEuXLkVSUpLdz69WrRr69u2reDw8PByPPPKI3UFVSkoKli1bJqXQfVZWFnbs2KG7HQB48sknpbSjV/369REYGKi7nYsXL0roDRFZwuCOiJwmPz8fc+bM0dXGqFGj4OPjo/qY0aNH6xoxmzlzJkaNGgUvL32XyO3bt0upp3rfffehWbNmutuRoXXr1twMQeTmXD/GT0SlxrfffouEhAS7n+/p6YkRI0ZYfVzPnj117So9ffo0vv32W7ufX+i3337T3QYAp5VGIyJjYHBHRE6jt8xX7969NdUl9fLy0l1R4YMPPoDZbNbVRnx8vK7nF4qOjpbSDhGVDpyWLUVu3LghPc2Dvf2g0mfz5s2601/Ysg5u1KhRmDZtGvLz8+0618GDB7Fp0yY8+uijdj0fgK5RyqJatGghpZ3SKD8/3y2uewDsfi0S2YrBXSnStm1bV3eBSrHY2Fhdz69Tp45NaTjCwsLQtWtX/Pjjj3afMzY21u7grqCgAKdOnbL73IVMJhMaN26su53SKi4uDkFBQa7uBpFTcVqWiBxu37592Lp1q642JkyYYHMqED0VKwDg119/xa5du+x67vnz56VspoiIiChWiYOISA2DOyJyOL2jdn5+fhgyZIjNz+vRowfCw8N1nXvWrFl2PU9PupeiLCVrJiJSw+COiBzq1KlT+O6773S1MXjwYFSqVMnm53l6euqqWAEA69atsyvhrqy1pQ0aNJDSDhGVHgzuiMihYmNjdS8kt1RHVquRI0fqqlhRUFBgV26+69ev233Oonx9faW0Q0SlB4M7InKY5ORkrFy5UlcbrVq10rVbtEaNGujevbuuPqxcuRKXLl2y6TmygjsiIlsxuCMih5kzZ47uTQUyyoDp3ViRk5ODefPm2fScmzdv6jonEZG9GNwRkUPcvHkTn3zyia42goKCpNRU7d69u6bkx2qWLFli02ictRJpRESOwuCOiBxi0aJFuqcmR4wYIWXNmYeHh+6KFenp6Vi8eLHmx1epUkXX+YiI7MXgjoiky8nJwYIFC3S14eHhgTFjxkjqkahY4e3trauNefPm4datW5oeKyu401sCjYhKH1aoKEWWLVuGWrVqubobOH36NJ599llXd4McaPny5brzvHXr1k3q6zUkJATdu3fH+vXr7W4jJSUFy5cv17R7Nzg42O7zFJWWlialndKqdu3aWLp0qau7AQAYNmwYEhMTXd0NKgUY3JUiLVq0QKNGjVzdDbvylVHJkZ+fb3fi36JkbKS41+jRo3UFdwAwc+ZMjBw5El5e6pfPkJAQXecpdOHCBSntlFZly5ZF+/btXd0NAKIvRM7AaVkikmrt2rVISEjQ1UZERAS6du0qqUd3dO3aFTVr1tTVRmJiItasWWP1cUFBQVI2VZw/f153G0RUujC4IyKpZs+erbuNcePG6Uo8rMTDwwMjRozQ3c706dOtroXz8PBAtWrVdJ8rLi4OOTk5utshotKD07JEJM3WrVvx559/6m5n7dq12LJli4QeFScjufDBgwexZcsWdOnSRfVxUVFROHfunK5z3bp1C3v37kXbtm11tUNEpQeDOyKS5oMPPpDSzp49e6S040ixsbFWg7vo6Gj8/PPPus+1fft2twru+vTpg4sXL+pu54cffpC2NpGI7mBwR0RSHDx4EFu3bnV1N5xm69at2L17N1q1aqX4mOjoaCnn2rFjB958800pbcmwbds2ZGRk6GrDZDIhMDBQUo+IqCiuuSMiKaZNm1bqcrJZW1/YunVreHjov8zu3LkTt2/f1t2ODJmZmboDOwAIDAyUkqCaiIpjcEdEumndQWo0a9euxYkTJxSPBwcHSxm9y8rKwl9//aW7HRkuX74spZ3w8HAp7RBRcQzuiEi3GTNmID8/39XdcLqCggKrOf169Ogh5Vx79+6V0o5estZDPvjgg1LaIaLiGNwRkS7JyclYsWKFq7vhMitWrMClS5cUj/fp00fKeZYsWYLc3FwpbemxYcMGKe24S2JhIiNicEdEuthSb9WIrNXRbdKkiZRAJi4uDvPmzdPdjh75+flSdv+aTCZ06NBBf4eIyCIGd0Rkt/T0dCxZssTV3XC5xYsXq+bPe+mll6Sc580338SuXbuktGWPdevWITU1VXc7TZo0QWhoqIQeEZElDO6IyG7WgprS4ubNm6pBbs+ePdGwYUPd57l9+zaGDx/ukp2z2dnZeOWVV6S01atXLyntEJFlzHNHRHbJycnB/PnzpbT1wgsvuCwtRkZGBhYuXKi7nQULFmDSpEkWfw4PDw8sXLgQHTt21J0u5vjx43jnnXfwz3/+U1c7tnr//feRmJioux1PT0+MHDlSQo+ISAmDOyKyy8qVK1U3EmjVpk0bl68l2717N/bv36+rjaSkJKxYsQKjR4+2eDwmJgbDhg3DZ599pus8gMgpmJiYiGXLlqFMmTK627Nm9uzZ0oLJPn36MA0KkYNxWpaIbFZQUIA5c+ZIaWvMmDFS2tFDKSCzVWxsrGpKmJkzZ0oLbL766iv06dMHWVlZUtqzxGw2Y8qUKXj55ZeltGcymfDaa69JaYuIlDG4IyKbfffddzh27JjudipWrIgnnnhCQo/0GTRoEMqXL6+7ncTERKxdu1bxeKVKlfDll1/C29tb97kA4JdffkF4eDhefvllHD9+XEqbhTIzMzFgwAC8++670trs3bu3tJJsRKSMwR0R2cxa4l6thg0bBn9/fylt6VGuXDkMHjxYSlvWyrA99NBDUtfLXbt2DbNnz0aDBg3QoUMHbNu2TVd7Fy5cwBtvvIGIiAh88803knoJ1KhRA4sXL5bWHhEp45o7IrLJtm3bsHv3biltudPC+rFjx0oJPg4cOICtW7eic+fOio95+eWXcf78eXz44Ye6z1fUjh070KlTJ0RHR6Nx48aoVasW6tSpg8jISERGRhYbnbx9+zaSkpKwc+dO/Pbbb/jtt98QFxcntU8A4O/vj/Xr1yMkJER620RUHIM7IrJJbGyslHY6dOiAqKgoKW3J0LhxY7Rq1UpK4BobG6sa3JlMJsyfPx95eXkOGc3at28f9u3bV+z7wcHBCAsLQ0ZGBpKTk52Sxsbf3x/ff/89mjdv7vBzEZHAaVki0uzgwYPYvHmzlLbcYSPFvWT1acuWLVZ335pMJixcuFBagmMtUlJSsH//fsTHxzslsPPz88P333+PTp06OfxcRHQHgzsi0mz69Om687QBQFBQEPr27SuhR3INGDAAlSpVktLWjBkzrD7GZDJh1qxZ+Ne//iVtk4W78PHxwTfffMPAjsgFGNwRkSanT5/GmjVrpLQ1YsQIp+Rns5Wfnx+efvppKW2tWbMGCQkJmh47cuRIbNq0CZGRkVLO7Wo1a9bEpk2b0KNHD1d3hahUYnBHRJrMnDkTeXl5utsxmUwYMWKEhB45xtixY2EymXS3k5+fj9mzZ2t+fIcOHXDo0CFMmTLFZdU69PL19cWkSZNw+PBhxMTEuLo7RKUWgzsisiolJQXLli2T0laXLl3ceoSqQYMGaNu2rZS2li1bhqSkJM2P9/X1xdSpU3HmzBm8/fbbqFKlipR+OFqVKlXw0ksv4dSpU5g7dy7KlSvn6i4RlWoM7ojIqvnz5+PWrVtS2nLHjRT3ktXHnJwcLFiwwObnVa1aFe+88w7OnTuHVatWoW/fvvDz85PSJ1m8vb3Ru3dvrF27FhcuXMCsWbMQGhrq6m4RERjcEZEV6enp0tJ1VKtWDb169ZLSliP1799f2qjZokWL7N6Z6uvri0GDBmHt2rVISUnB6tWrMXDgQFSoUEFK32zl7++PTp06Yc6cObhw4QLWr1+Pvn37wsfHxyX9ISLLmOeuhHjqqadsmt6xpHLlypJ6o0/lypUxduxYXW3Ymwx1wIABaNOmja5zV6xYUdfz9Ro4cKDu10LLli01PzYuLg79+/fXdb5C7du3LxG7Qn18fDBjxgzs2rVLSnvHjx9Hq1atdLVRrlw59O/fH/3798ft27exfft2bNiwAYcPH0ZcXBxSUlKk9LWoSpUqITo6GjExMYiJicEDDzzg1EAuKChI97WiRo0aknqjn6uuP6685pJrmMwy8hoQEZFLpaam4vjx4zhx4gQSEhL+93Xu3Lm70tf4+PigQoUK//sKDAxEhQoVEBQUhPDwcISHh6NmzZoIDw9HQECAC38iIrIXgzsiIiIiA+GaOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgTC4IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgTC4IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgTC4IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgTC4IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgXhpfmTmNSA/z4FdISIiIiJFZcoBZcpafZjJbDabNTU4NQpIOqa3W0RERERkj55TgF5TrT6M07JEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiID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"

# Footer orange band (image4.png from the letterhead) — full-width branded strip
_HITACHI_LOGO_B64 = "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A2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgTC4IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgTC4IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgTC4IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgTC4IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgXhpfmTmNSA/z4FdISIiIiJFZcoBZcpafZjJbDabNTU4NQpIOqa3W0RERERkj55TgF5TrT6M07JEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6cw6uMq3vgWh5egIenq3sBeHq7Rz/IPbjL65KIpNJeW5bIGv9AoEptIKQhEBoFBNUWX1UjgS1zgR+murqHjuXhBVQKF7+DoNp3/g2qLX4f01oCl444vh9ePkDFGsX7EdoQqFoXmNoQSD7h+H64M5OH+FuZ/nt/m38byEoDcjJd2y9HsPq6fAC4dNTVvSQiiRjc2aJ5P6BsJXntFeQBp/cASUcBjSV+3UZkO6BFf6DKfeKrci0RVMhUryPQqBtQrYH44D35H2D3SiA3W+557FWnLRA9AAiuA1SpAwTVFB+kztZ+LFDzgTt/i4rVAZPJ+f1wd34VgJaDgKhHgMj2lt/LeTnitZaZKv69cuq/X4n//fckkH7F+X23RWQ7oMWTrn9dGkW9jkCTPuLGKCUBOLgeOL7N1b0iUsV3vC16TQFCG8lvNz0FOPk7kLgbOLNHBHy5t+SfR6aoR4COzzmu/UGLgJhxd3+v1TNAtzeAGQ8B1y857txaNegCdJzo6l6IPoQ2dHUv3FdIA+Dh54EHnwbKlFN/rFcZoHw18QUA97W5+/iFQ8B7TRzTT1nc5XVZ0plMwIgvgAeeKvLNbuK1tOcL4LOnS95NOZUaXHNni4uHgfxc+e0GBAPNHgeemAG8tB2YfhboNRUIqCL/XLKc2Qf8+Tlwdj+Qd1tu24FhQLtRlo9VjgCe+VTu+ex1br/jfge22P8NcGAdcDXRdX1wR8GRwPMbgSlHxeimtcDOKM7uE6+HlJOu7onrRA/Q30abEfcEdkW0HAS0G63/HEQOwpE7W3w6CDA9DVSoJtaw1O0A9Hwb8PaTe56AKkDPKcCjrwBb5wMb3nW/kbyD68UXAATWAAbMFwGqDJHt1KeRGnQGvH1dPz178HvxBYiAtM97QOuhzu/Hhnfu/HfdDsDQf4v1VKWZf0Vg4gYxlWaJ2Qwkx4s1kFdPA+YCsf6uRhMxWlemrFO7K1XR12W1+sBzPwFBtVzbJ2fx8AIGfiim3fd9ra+txj3VjzfsCvz2sb5zEDkIgztbmQvElOD1S2Ia9WYyMPQz9efE/wr8EgsU5N/5nocnEBIFNOktPpAt8fYDuk4GGnUHPn7Cfe/E0y4Aq8YCUY/K+VC0NmLp6S3WT7k6uCsq7Tzw+WixNse/ouv6cWK7uBl4dpnr+uBqJg9g5JfKgd2lo8DCXiKos8TTG6jZEqj/sPiq3brk7va+fFwE/6Xh9eAbAIz6WqzTTYrT3145K9ehspX1n4PIQRjc6bVnFdB/ttgpakluNvBhD8sjb0d/EbtIa7cC+rwP1O9kuY0ajYHhnwMftJLXb9nSrwDXTstZk3juL/Xj1y+KoNrd5N0GUs+5NrgDgPMHXHt+V+vznhhVsSQ5HpjzsFjnqiQ/Fzj1h/j68T3At7wYxWn+hBilLmkO/+jqHjheUC0xUhsSJa/Nc/uB+x5SPn7xsLxzEUnGNXd65d0GUs8rH08+YX1KNXE3MO8RIOE/yo+p9SDQ8FH7+ljSnPzvB6sludnAsmed2h0qQfwDgS4vKx//YoJ6YGdJ9k2xgH7JE8Dczvr65woZV8XuX6Oq9SDw6i65gR0gAnulFDGXjty9HILIzTC4czRzgfbHffuS+mN6TtXdnRLBXCBGO/d+efdUdtIxYEYb4NgW1/WN3FvTx9RT8lw5pa/97HR9z3eVG26wu9wRmj0O/GMbUL6q/LbTr4jrzZ4v7lyHzAXiuhTbxvabBCIn4rSsOzmzV0xJhje3fLx2K5HP7Mxe5/bLFW7dEBtYVo4Wux5Tzxp79IHkqPWg8rGMq8C1M07rilsxYsqOoFrAmG/uJKJ2hFs3gH8PBj4fI/IGXjlVcgN8KlU4cuduzuxRP96om3P64S5yMoDzfzOwI23UdoWWraS8NpZKHq8yjg3sisrJEGtZGdhRCcHgzt2c2ad+3FkXM6KSyLe88jGTB3B/D+f1hYjIRTgt626SHFzj0WQCKkUAlcJErj5Pb7HD8+oZsdvVXadvPLxETczQRiLdh96RvHJBQOWaYvdjQLBYP5N2QaTHyLwmo8fWefuKKefKNYEKIcCNJHH+lARRBsvdla0sRsoKf4eF/b9y0nVpalLPiuULSp6cC1w8JCpNuAOTh0jMHVhDvB+9fIH0ZCDtonhfOuu1qEdAMFC9kXhP6tmpXSFEVFrJuOq+O759/EXFkwohwKEN+tvz9hPvoUphQIVQsVM79azYpJd61nHX4/LVxO86M1XMjFhi8hDX3Or3i36e/xu4HK99HbkWPv4iZVFwpLgxS08BMq6I1//1C+77eVQCMLhzN8GR8tv0DRAZ26MeAerGiIuxJelXRE6+41tFEtSbl+X3xZrCIuehDcXut8J/QxqICwEAvHO/7cGdt68oy9TwUVErUmlnndksUiAc/kksnL58XN/PY0l4c6DzP0SOQ9+A4sdzMoH4bcC+1SLVjrtc4EwmoH5n0e96HZVLnuVmA6d3i9fSoQ3WU9vIlJKgfrxcEPDiVrHr9cJB5/TpXlXuE5UP7nsIqP2QeuqcpDhRx3T3SutLNhzNr4JYdxbSEAiNEv9GtBCBDgD8MFVbUOYfWPz9Xf3+O5sivn/bcjtDPxPJwgup5dSsFAFM2qx8PO0CsHyY8vGi16GIFnf6WrWeyFGaFGdfcGcyiZRX9/cQ+RPDm4sbbEvSU4D47cDhDXdv6rBFYRBX9Hcd2vBOXeUN7xQP7hp0ATq/CNRpU3wkPPumyGaweZZ99XW9fUVN8paDxI26Wmqh9BTgxA7xeXRgnXumv3JjDO7cTc2W6sdTz2lvK6AK0ONtoPUQ9emqoo+PflJ8DV4MHNkoLoCOLpTecaKoChDSQGTUl5kw1jcA6P0u0HaktvJTJhMQES2+er4NHP0ZWDpU3s649mOBAfPUf8YyZYHGvcTXQ8OAlSOVE+46g8lDlIPr/KL4cLPG21ck5q7bAej1juj7ihEi2HO0A+uB7m+qP6ZcEDB5t0gsvnG680ZJQxuJEoMNH9W+vCIkSnx1mADs+wpYO9m2a4AeAVWAR14RgVdo1N2BlS3uayPqQt8bWNiqdmtxfdCiTFlRyUZJcnzx73WcCNRp998grq5y0GWvh4YBXV/V9h4CxE144fX4kf8DvnkJOKYSsALihqHVEPt+196+wMCPRNk1Jb7lxbrvhl2Bb14UFZS0athVtF/lPm2PDwgWgWCL/uK/f3xP+7mIwZ1b8fBUTr4KiJ1bWkvqNOsLDF6iPEp3I0nceQVUsVxuqXB90hv7gdkd9aeQUNNhgvaLti0qVgcm71L+ULp+SdwRmkwikLJ0F9mwK/DGPmBWB/21Wx9+XgSZJpP259R/WNQbnhbt+CDbkuBI4Nml4jViSe4tkZ8x46oI5iqGFn9MUC1g0iZg5Shg5zJH9lbUVb1wUJQRU+PtK0r8RQ8AVr8ognhHqtFYjBiWC7J8PD1F5LvMuCo+mMOa3F3W0GQCHhgoXo+fDLD+IS9DhRDgEZWcgVo16AS0H6O/HUdz1HXI01sENWq1aC8dESPcvuXFsoLy1e4+Xv1+8R76+QNg3RvKU6P1Otr3u/b2AyZ8rx4QF2UyAf3nihu3wlJ3im37Ak/OKxmvAQNhcOdOHn1VTHso2b5QTNlZE9kOGPOt5dGBq4nAF+OBuM13LhCe3iI/2PCVxUeUAsOAgQuBBSpBp177VosPv9BG6j+/LUwmUYJKKbC7eFhUKsi4Kv7/y4kiZ9bor4v/3gLDgF5TgaVD9PWp3ai7///WjTt/gzLllEcKKoWLn2XeI3LXu1hTpizwws+W69Tm5Yjps3tfk9Xqi/QU91Yq8fACBiwAjvzs+On+T54EXtsjphGtqVYfeH6jCKw2TgMO/SC/P0G1gUlbLAd2BXnAV88Df/xbJEQvVCFEVL55YODdj/cPBJ7/CVgxEti1XH5fi8q4JvpVuRYQ1tT+Ebez+4E/P//vaFIj9TyEavatFnW9C/lVFKNalmSlAfu/UW7L0hTfX98CEQ+IUTuZtXhHrBKjT5YknxCzI6d23vmeh6cYHes3u3gJva6TxWv2kyfF+rx7nftb/BzBkUC1Btp+195+wIT12gO7QiYT8PQnYpAgJ0P5cQ+/YDmwy0wFti0ATv8pppwDa4ift1lf7aObpIjBnTswmcSbts/7yo9JOw9smmW9rTJlgaFLLQd2ySdEUs7CgKZQfq64EOZmi7u3ezV8VIziOaqM0Q9T7vx31Xriw1bvxfX+HiLIVbJ60t2/B3OBuCj+/qnlO+zoJ0UAmH1TX78A4HaW+HDe++Wd7/mWB/pOE6MHltTvBHSaBGyZo//8WvWdbjmwM5uBRX1E+bx7XT4OzOkkpj3v/Rv6BojSYCtHFX+eTIUfmGPWaB8lrd1KvPZP7AB+fNe+9USW+JYX7SrVS17/FrBjcfHv30gSlViq3Fd8qYaHl1g2cWqn9TWGely/KF6ngLjpazcaeGqB7e0c/vHOtSMwDHhyDtC8n+3tFL1OACLIUQrubiSJ3HS2WP/Wnf+u20Gs8dN7HYoeoBzY5d4CPu5XvIxZQb5Yz3f1DPD6nrtHcAFxI/7Uh6Ke972O/CS+ABEsDZgvblrVPPMvsc6ukLlAbDg6+bt4z7Z6RnkZQfmq4nWhdF3y9AY6vVD8+7ezgPeaiLWP91r3uljb2+NNILK9et9JEfNquJKPv7iIjFkDPDZN+YMoNxv410BxN2pN25HKaxp+mFo8sCvq0A/KCZJ7v2vbdKK9kuNFP/UwmdSreVy/pLz+q+gddFFeZeSk0SjIF2WsigZ2gAgav3pOfdr9sX9aDrYcoWKoWB9oyaHvLQd2hdJTgF8/snzsoWHOuSv/+zv7ykPVjRHTp6/8LqfcX7+ZyhtPkuOBTTOVn5t3W5RLs7ShxtsPGPKpc96TgBip/fVD/Td4aefFTdLtLDn9cpQT28Voox5eZcT6WiVfTFCvT3vpiPKatvZjxLVeTdoFYNU49dmeVs8ADw4W/12QJ0bjXwoG3m8mrkfLnrUcRBZVr6PysSa972y4uatv5y0HdoB4vR/bDMyKAWZ3kHejVcowuHO0qnWB1/cV/5p2BliQAbz0qxiGVpJ7S4ySKNVaLcpkAmLGWT527Qywf7X1NpQeE97ceXdRej9Aaj0odrgpuXVDeQeq2kiI2kVMq23zldd3mc3igq80xeHtC7RVWewsU/uxytPEv6gEJIWUpsQ8PIHOk+zulk02vCPW0xXk2f7c+9oAz/8M/N9/ik+NaeUfCDz4tPLxX2Za3wF5dh8Qt8nyscj2xadtHU1GdZybyc7bFKLHjSR9z285sPjauUKJu4GdS623sWXO3dP1RXV/U4ziqklPUa/KUnizaDYDix8XmxbuTb/z+6dit7aSsKbKx6rfb/n7Pio7nYs6sQOY2wnYMlfb4+l/GNw5mo+/CDTu/aocoX7Xff2ieGO/WUf54n6v2q2VR0US/qNtK73aneQDT2nrh16Z1/TlsYt4wP7n3rqhfCzMyiJ9a7LTgZ+mqT8m85r6Rf/Bp52TyLr1UMvfz70l1shYc/2CcpDa7AnrH0qybJ0HzGir/T10rzptgTf/BjqMt/25rYfcSd9zr5xMbTdbAPCfT5SPPR6rnhKE7Kd3yjtG5TWjNa1N+hWRCsWSyhFA0z6298uSrfOU15uazeo73StWt/01GFjD8nStErU1fWQR19y5k/QUYM+X4qKfuNv2xfP1HlY+1qCzGDG0xsdP+Vidtrb1R4/rF+1fwJ0cL9JcKLlpZ1qTe9e+2OrYFm1JaeO3Ax2fs3ysUri4G3ZkjrbgSHEeS0weYj2dFkojfwFVxHqpS0fs65+tTv8JzH9UrKvrOUV9R7olPv5iU1GtVmIdV+4tbc+r30n52Jk92ktZxatMSwXWEO97R2wEKe2uX7T/ub4B6rMHajfR90o6BjRTONakD/DXGpu6VsypncDaV9Ufk3Ze+ZjJJBIw2xoM958r1qRunG7f6DqpYnDnaHm3xSgGID7s1HJFZaWJN5m9ebfqqwR3FUIsr32whTNLn+lJ3Bu3yf6RGkfSmsz3kpUqJZXCHRvcqU0/e5VR/9DSysMFkwaJu4EF3USQ1+0NsYbSljVrrZ4R1UQ+7G59JMFkEsGgEmt/46KyroupzMIkv/eq9SCDO0fQcw2q2VL9emkpz549aj2o7/lms1gDaWnnbVFqa7UB5feR2vS7ySTWcjd/AvjmH1xbJxmnZR0tKQ544z7x9VpN8QGjpGo9oMtL9p/r3vQT5F5Sz2p7nLULaSU7k8lqVd3gr6PE3cDCXsDMtsobaJREthN5/6wJqq28QxawfdmB2nIBvR/wJF9EtPpxpc0ElqiN8AZH2j/DAYg1nUrlx4qyN9Dd97X6axcQOSlf3CrWtzpzdsjgOHLnTOYC4KuJwOQ/xcJyS3q8KXZS2lqRwNtXOUEqIN7AehdD611gXBL4VXRc21ov6FlpYn2k0mukokrJHhnU2s++Cez9Sv85MtygZuqpnSLAa95PpH3Rmjm/eT+R4kJtZ3PlmlK6qIlSonJyncoR6sdtKaWVoZK83GQSgwKJu7S3V5SjS9rlZIoduAM0VLKo0xZ4+TexgWPtq9qyQ5AiBnfOdna/WCCttKvV2w/oPwdYrLKD1pKK1dWnmM4ftD3vk1F5+4kdXhHRQM1oUSOzQjXxISm75FBR1kbkCpkLxNo8pQ9tS1UgZFKr9+jhJVIjuEu9W73MZrGz9+B6oMNEcXPlH2j9ef3niLyISpuUHP03IvdWsbrysZwM21LBWCt9WCnM/uBO6zVJj18/FCPZWjZQmEwi2XuTXsBnQ5xTicWgOC3rCuveUC8l1fQxoHFP29q0tvmiaqRt7RlNSJTIJfjK78C868CrO0VC1lZDxBqyitUdG9gBtgVEWdeVjzk6cFB7Lfn4O37k0BXybt/Znf7HZ9YfXzFUPTWQ3vWtVLKp/f1tDaisbQCzt+avs5jNImn80qHag9ry1YAXfhEjfo6+LhsUgztXyEoDvntN/TFPfaScRsGSG1ZKOoVEaW/LSCJaiIvElCNAt9dE/jJ7yx/pZcsmAv+KysfKqazlksFaebCQBo49vytlpgIrR1quGnEvtV231haok7HlK+SmA2xPA5SXbeVcJeS1tnsFMLMdkHJS2+NNJlGPe8IPYtkR2YTBnavs/Ex9KL1yBPDoK9rby72lXhrLP1B9qsCIHhoG/N/vQNQjylPW1y8Bf64SpY1WjAC+VCj/JYPW0RwPT6BsZeXjamtwZLC2HsjoG3fMZuDrF6zn81NLbnz9ktw+Ucmi9vcPCJZbWaQkvdbO/QW800jUN9eayLrho6LuubOqsRgEgztXMZvFGji1/D5dJ9uWHT/NSl4mtUoYRtOiPzDk38p3fAe/B96uD7xaHfjsaWDDu2I67sQOx/VJ6/RJ2crKmykAIFUl55QM1vJ7lYbXUX4usNFKwmm1RfM3StAHri3sTdNUlIen+08l6qUWcHn5iPxuspS011pejhgZfysSWPN/2vJGNu8HtHVwTWqDYXDnShcPAzuWKB/3KiMKRGt11spu2JjxpePuJ6i2KPqt9LP++iGw+DF5uaa0sraDrpBSPrNCtqRRsMcZK8mu67QV5eiMLv5X9fWHautmrU09yXwf3roury1r1EZ1fQO0tVH9fuNX1biaqH5c5g7nkjRyV1TebWDTLOC9puq1qgs17uXwLhkJgztXW/eGeoqRqEe0j5ScsrJjKqSB7dn5S6KOE4Ey5Swfy7oOfPuya3Z7Vm+s7XFhSuno/0utVqQMibus/35sKR1UUmWnqwfSaumKbiSp/51s3RSjFjjJqPeqldp6TK1rMdXq7RqFtRQjtqTK8augfMxcoK+ShjtIPgEs6CrKBCafUH5cabihlIjBnatl37S+uWLAfOVgpShrIw0A0Osd44/eteinfOz4FuVC3ID6Wje9wq0EbYVqWkmAamsORFtlpQEXDqg/puVg5TrGRuHtp75O0loJKbU1tSENtfejXJB6Pxydq6wotY1b4c2tX1vKlFOuWyyTs2oXKzl/QP06U82G9064SkWYG5dLzoYKa079ASx5QnmatmKoei5XuguDO3ewe4X6Wq/AMKD7G9bbSY4XmwPU1HxAbDQwqjLl1FN1XD2j/vx6HWT25m6BYepVCwqpXczzcmyrS2mvzbPVj3t4ipsOZ5ak00JtraKtIlqop2E4slH9+Ud+Vj5WM1qke9BCbcQiL0fUInYWtdHI8tWAalZG7x5+Xt4HtFKOQUDkfnPlazM3G0hQuabXaKK9raZ9lI8l/Ka9nZLg0hH1neqsQauZm12ZSykt9f06/0PbtMe6163nEhq4UAR5RuTjrz56oDZ65uEJRD8lv09FtX5W/XjVeqL2qZJ9X4sEx4629yv1KRJA7GLr857j+2KL0IYih2Gzvvo/3Bt1Vz52/m/r66r2r1bOaebhpX0ESy2f3r6vrSe5lSkrTf18alOuNR8QSaJlSTuvPFPh7aeejNsZtqmsl67TVtvrM7gOEBlj+VhejljW486q1rM9jcmBdZa/n56inv+T7sLgzl1cOgJsX6R83MsHGLzE+rRH2gVg+TD1NVPeviJFyNOfAEG1tPdR5qiIo6SnqH/o1o0RF0xLHvk/x+dw6zpZOZWIjz8waKHyRd9cAGxb4Li+FVWQLxKPqo2OAEC310ViaFvWcjr6dVS7NTB2LfDucbH+UusIWVGhDZXXFRbki1QO1uRmA79+pHy8/WjrH/CBYcr9yM8FNs+x3g/Zko4pH+s6Geg06e7vmTzEz/B//xFBl7lAVGnQKzdbPZ2GWq5IZzj8o/Ioe7X6QNsR1ttoN1r5mr9lrvUbDFdrORB4bY9teVaVHnvhoJw+lRIM7tzJ92+p73yKbC9qWlqzbzWw3sodspePKPPybrwI8iwFPCaT+HBpM1x8WD76qvVzuwO1aSoPL2DEqrt/Xm8/oN8sUcHC0cpWAl76FWj2+J0PdpMH0KCz+PCr30n5uZvniPJ1znJkI/DdZOuPu68N8PxGMWLWoIvlqUy/CkCjbsDAj4AXt8jvqyXBkWK3+YyLomZl5xfFTk21G6SAYODBwcA/tiknEf95OpC4W1sffnpfefo2qHbxQKgobz9g+Arl9barxrnmA+/SEeVjJhPw5Fzgzb/EtP1j/wTe2A88OU/s/gfEtJusHd+Xjiof03KtdCRzAbDoMeXR28dnADVUNllVv18Ed5ZcPi7SN5UE1e8H3jogPmesZQwIbQT0ed/ysfhfpXfNyFhb1p1kp4uCycNXKj/mybniw+LWDfW2Nk4THwrdrGzW8PQWQV67UWIh69XTwK2bYkqjfNW7P6hLyp3Tj++JEm5lK1k+XrMl8F4CkBQnFiTXjJabd+peZrNYXH/fQ+L/ywUBY9eIzTTJCaI0nLXzn91nPWB3hE2zAE8foNdU62WAarcGJm0SI1tpF8SO0bKB4gahaKCkNvLjCCYPILKd+ALE6O7Z/WJa7/pFEXQEhomckjUfUB9N2zpfFELXqiAf+NdTIqC1tBSi3yxx3i1z7p4GrxACjPwCqNvBcrsbpwN//Ft7P2TasVgEHWqvh7Bmlnd930gSr2O1mxhbnNoJ3N/D8rGur4lR2xPbxXUtPUXMVFRrAPz5uXPqql5NFAHepE3Fbxb8KwKTtgA/vgvsWi6u/4UadAFGfG55p2z2TWDpEG354dxF4edM2xHixujwBhGYp5wE/MqLTAJNeoulHpY2w5z6Q1yLSDMGd+7mz8/FSFm9jpaPl68G9JwCfPMP622tex1IOgo88y8xCmCNt58xypRdOwN80h+Y+KP6eo+QqOI/7+EflT8s7JGZCix7VlzMnvoQ6FCkAoZvebFo35oLh4D5XeUkkLXHxmnAsS3iwyZYQ41iD09xh641r5+zBQSLUURbZFwVVUx2LLY9jU72TWB2B2D458XTGplMQPsx4utm8p0RraBayjcn2xaI97arXDoK/DBVjMrZIuMq8HF/ueumfv0Q6DDecvUdk0lcS9sML37s2GbnBHeACEwWPQZM+L749SigirguDJgPpCQA2RmiTGGNJpZvMq6dBT7qqT566s5MHuImt/BGV4u9XwIrRxtnV7CTcFrWHVnbXPHwc9p3W/25CngzUqz9sTc4KMgXu7JO7bTv+a5wfBswp6P2ofys66Lk1FqJU8+n/wT+2Rw49MOdTTOLHtNeWzE3W3x4ze3knE0Uas7sEWWDVo3VXjbIkiunxCYAR8m6bn1U2xbpV4CfPxDZ9Lcvsj8/4u0s4ON+wIqRIk2GJeWrimA/okXxwM5cIF7TS4eItZCutnEa8NkzQE6mtsdfPAxMf1AEOjJlp4v31PGtctuV7dhmYFYM8Ncayzs+TR5i80FECzHieW9gl3EV+CUWmN6y5AZ2tko5CSzqA3w6SM4azVKGI3cy/L0GOK2wBseeUlFJcSIQUBvViYjWPk16/SLw1XPiQ6phV3HXVLs1UKX2nXUw97qZLKYzDv8kRrO0BBf7v1UOAG1dK6b2O81K1dZG4m5gzsNiZ1rXyWK0puhFMz9XfNDuXw3sWiGmbSqGAv/5xHJ7WpKFFvY79TywaUbxXFcH1wNHfgLajAC6v168DFNOJnDyd/E73/+NetJYJZnXlH8GwP7gJ+828NvHwM6lQMNud15HNRorJ1otyBe/j8M/ipJvamukZEg9B7xYSaypDGsmdkeHNRN9VNtYYTaLv//Ny3emlI9sFCOuavnKbGEuEFOpf/xbLA1o+KgYoa/5gOV1dWkXRDB0fJvoS5qOsnN/faucdy8rzb42//xc9KvdKDFNe+/mrJwMcf34499i5LfoztZ9q4EKCn+Pc3/Z1o+z+4C5ncW0e7sx4vdZOUL52padru09kHVd+X2klnheyZk9IsCvWF0kp6/TVrx/gusUn+LOuy1G8uK3ib//0Z/FzZ499n+jHFRrvS7be03ZtUKMNhb+rFXrqm+ounLqzrXv1E7reVtJkcls1ngrOjXK+WtlyPHKVhIjBgHBdy4w1y+JANNoKkeIacW82yIISLvg2rxJJpOYFq4QIvp0NdHxpcUcxdtPfFiXr3antJS5ADh/0PWjjoV8/EUAUjQhcMZVcSOTnmJ9Z7Aj+QeKD32/8uLGID1ZXlDpLIW/X5+yYmmEM1O0WFK2kng9BgQDnl4igL92Rqy/c6egweQh3juBYSKAu3lZvcxbSeblIzYSWUpTk3re+SUhS6KeU8QaaCsY3BERERGVBBqDO665IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAaivfzYub+A21kO7g4RERERWVQpXHxZoT24IyIiIiK3x2lZIiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgTC4IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGcj/A8Iw750LEK1pAAAAAElFTkSuQmCC"

_FOOTER_BAND_B64 = "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"


def _make_page_template(logo_bytes=None, eh5000_bytes=None):
    """
    Replica of HTM_letterhead_LANDCROS.docx:
      Header : Hitachi logo top-right  |  document title centred-left
      Footer : full-width orange band (LANDCROS / Japanese Excellence) + contact + page
    logo_bytes and eh5000_bytes are accepted for API compatibility but ignored.
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors as rl_colors
    from reportlab.platypus import Image as RLImage
    import base64, io as _io

    PAGE_W, PAGE_H = letter          # 612 x 792 pt
    _ORANGE = rl_colors.HexColor("#FF6600")
    _BLACK  = rl_colors.HexColor("#1A1A1A")
    _GREY   = rl_colors.HexColor("#555555")
    _LGREY  = rl_colors.HexColor("#CCCCCC")

    # Pre-decode images once
    try:
        _hitachi_bytes = base64.b64decode(_HITACHI_LOGO_B64)
    except Exception:
        _hitachi_bytes = None

    try:
        _footer_bytes = base64.b64decode(_FOOTER_BAND_B64)
    except Exception:
        _footer_bytes = None

    HDR_H  = 62    # header zone height (pt)
    FTR_H  = 52    # footer zone height (pt)
    MARGIN = 36    # left/right margin  (pt)

    # Hitachi logo size in header — proportional to cropped image (631x270 → ~2.34:1)
    LOGO_W = 72
    LOGO_H = int(LOGO_W / 2.34)   # ≈ 31 pt

    def _on_page(canvas, doc):
        canvas.saveState()

        # ── HEADER ───────────────────────────────────────────────────
        # Hitachi logo — top right
        if _hitachi_bytes:
            try:
                h_img = RLImage(_io.BytesIO(_hitachi_bytes), width=LOGO_W, height=LOGO_H)
                h_img.drawOn(canvas, PAGE_W - MARGIN - LOGO_W,
                             PAGE_H - HDR_H + (HDR_H - LOGO_H) // 2 + 2)
            except Exception:
                pass

        # Document title — left / centre area
        canvas.setFont("Helvetica-Bold", 10)
        canvas.setFillColor(_BLACK)
        canvas.drawString(MARGIN, PAGE_H - 24,
                          "Fleet Reactivation Analysis")
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(_ORANGE)
        canvas.drawString(MARGIN, PAGE_H - 36,
                          "LANDCROS")
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(_GREY)
        canvas.drawString(MARGIN + 56, PAGE_H - 36,
                          "Japanese Excellence  |  Reliable Solutions")

        # Orange rule under header
        canvas.setStrokeColor(_ORANGE)
        canvas.setLineWidth(1.2)
        canvas.line(MARGIN, PAGE_H - HDR_H, PAGE_W - MARGIN, PAGE_H - HDR_H)

        # ── FOOTER ───────────────────────────────────────────────────
        BAND_Y = 34
        BAND_H = 16
        BAND_W = PAGE_W - 2

        # Orange band image from letterhead
        if _footer_bytes:
            try:
                band_img = RLImage(_io.BytesIO(_footer_bytes),
                                   width=BAND_W, height=BAND_H)
                band_img.drawOn(canvas, 1, BAND_Y)
            except Exception:
                canvas.setFillColor(_ORANGE)
                canvas.rect(0, BAND_Y, PAGE_W, BAND_H, fill=1, stroke=0)
        else:
            canvas.setFillColor(_ORANGE)
            canvas.rect(0, BAND_Y, PAGE_W, BAND_H, fill=1, stroke=0)

        # Thin rule above contact line
        canvas.setStrokeColor(_LGREY)
        canvas.setLineWidth(0.3)
        canvas.line(MARGIN, 30, PAGE_W - MARGIN, 30)

        # Contact + page number
        canvas.setFont("Helvetica", 5.5)
        canvas.setFillColor(_GREY)
        canvas.drawString(MARGIN, 22,
            "200 Woodlawn Road West, Guelph, Ontario N1H 1B6, Canada  |  "
            "Tel: +1 (519) 823-2000  |  www.landcros.com")
        canvas.drawRightString(PAGE_W - MARGIN, 22, f"Page {doc.page}")

        canvas.restoreState()

    TOP_MARGIN    = HDR_H + 10
    BOTTOM_MARGIN = FTR_H
    return _on_page, TOP_MARGIN, BOTTOM_MARGIN


def _fig_to_pdf_element(fig, width=520, height=285):
    """Convert a Plotly figure into a ReportLab image element."""
    from reportlab.platypus import Image, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet
    styles = getSampleStyleSheet()
    try:
        img_bytes = fig.to_image(format="png", engine="kaleido", width=1100, height=620, scale=2)
        return Image(BytesIO(img_bytes), width=width, height=height)
    except Exception as exc:
        return Paragraph(
            "Chart image could not be exported. Asegúrate de que 'kaleido' esté instalado en el entorno que ejecuta Streamlit. "
            f"Detalle técnico: {exc}",
            styles["BodyText"],
        )


def _pdf_table(data, col_widths=None):
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle

    _ORANGE = colors.HexColor("#FF6B00")
    _DARK   = colors.HexColor("#1A1A1A")

    hdr_style = ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=7,
                                textColor=colors.white, leading=9, wordWrap="CJK")
    cell_style = ParagraphStyle("td", fontName="Helvetica", fontSize=7,
                                 textColor=_DARK, leading=9, wordWrap="CJK")

    wrapped = []
    for r_idx, row in enumerate(data):
        wrapped_row = []
        for cell in row:
            style = hdr_style if r_idx == 0 else cell_style
            wrapped_row.append(Paragraph(str(cell), style))
        wrapped.append(wrapped_row)

    tbl = Table(wrapped, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  _DARK),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7),
        ("GRID",          (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F7F7")]),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, _ORANGE),
    ]))
    return tbl



def _report_kpi_table(report_df):
    total_flags = sum(
        int(report_df[f"_flag_{c}"].sum())
        for c in FLAG_COL_TO_COMP.values()
        if f"_flag_{c}" in report_df.columns
    )
    _n = max(len(report_df), 1)
    _rpt_avg_kits   = report_df["Total cost per kit"].fillna(0).mean() if "Total cost per kit" in report_df.columns else 0.0
    _rpt_avg_labour = report_df["Total Labour"].fillna(0).mean() * CHM_RATE
    _rpt_avg_comp   = report_df["Cost per Components"].fillna(0).mean() if "Cost per Components" in report_df.columns else 0.0
    _cer_col  = "Impact Cerrejon Inventory"   # capital I — matches cerrejon_impact sheet (V10)
    _comp_col = "Impact Cerrejon inventory"   # lowercase i — matches component_impact sheet (V10)
    _rpt_cer_tot = pd.to_numeric(
        cerrejon_impact.get(_cer_col, 0),
        errors="coerce"
    ).fillna(0).sum()
    _rpt_comp_tot = pd.to_numeric(
        component_impact.get(_comp_col, 0),
        errors="coerce"
    ).fillna(0).sum()
    _rpt_avg_inventory = (_rpt_cer_tot + _rpt_comp_tot) / _n
    return [
        ["Metric", "Value"],
        ["Active Trucks", f"{len(report_df):,.0f}"],
        ["Total Fleet Cost", _format_usd(report_df["Total_Cost"].sum())],
        ["Average Cost per Truck", _format_usd(report_df["Total_Cost"].mean())],
        ["  ↳ Avg Cost — Kits", _format_usd(_rpt_avg_kits)],
        ["  ↳ Avg Cost — Labour (Kits + Components)", _format_usd(_rpt_avg_labour)],
        ["  ↳ Avg Cost — Component Parts", _format_usd(_rpt_avg_comp)],
        ["  ↳ Avg Cost — Inventory Impact", _format_usd(_rpt_avg_inventory)],
        ["Average Operating Hours", f"{report_df['Hours'].mean():,.0f}"],
        ["Components to Replace", f"{total_flags:,.0f}"],
    ]


def build_report_figures(report_df):
    """Create report-ready Plotly figures using the current filtered fleet."""
    figs = {}

    cost_sorted = report_df.sort_values("Total_Cost", ascending=False).reset_index(drop=True)
    figs["fleet_cost"] = go.Figure(go.Bar(
        x=cost_sorted["DT"].astype(str),
        y=cost_sorted["Total_Cost"],
        marker_color="#FF6B00",
        text=[f"${v:,.0f}" for v in cost_sorted["Total_Cost"]],
        textposition="outside",
        hovertemplate="DT %{x}<br>Cost: $%{y:,.0f}<extra></extra>",
    ))
    figs["fleet_cost"].update_layout(
        title="Total Cost per Truck",
        margin=dict(l=30, r=20, t=50, b=60),
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        xaxis=dict(title="DT", type="category"),
        yaxis=dict(title="Cost (USD)", tickformat="$,.0f", gridcolor="#F0F0F0"),
    )

    comp_counts = {}
    for comp_name in FLAG_COL_TO_COMP.values():
        flag_col = f"_flag_{comp_name}"
        if flag_col in report_df.columns:
            comp_counts[comp_name] = int(report_df[flag_col].sum())
    comp_series = pd.Series(comp_counts).sort_values(ascending=False).head(18)
    figs["components"] = go.Figure(go.Bar(
        y=comp_series.index,
        x=comp_series.values,
        orientation="h",
        marker_color="#1A1A1A",
        text=comp_series.values,
        textposition="outside",
    ))
    figs["components"].update_layout(
        title="Components Required by Type",
        margin=dict(l=150, r=30, t=50, b=40),
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        xaxis=dict(title="Required components", gridcolor="#F0F0F0"),
        yaxis=dict(autorange="reversed"),
    )

    kit_totals = {}
    for kit_col, kit_label in zip(KIT_COLS, KIT_LABELS):
        if kit_col in report_df.columns:
            kit_totals[kit_label] = float(pd.to_numeric(report_df[kit_col], errors="coerce").fillna(0).sum())
    kit_series = pd.Series(kit_totals).sort_values(ascending=False)
    figs["kits"] = go.Figure(go.Bar(
        x=kit_series.index,
        y=kit_series.values,
        marker_color="#FF6B00",
        text=[f"{v:.0f}" for v in kit_series.values],
        textposition="outside",
    ))
    figs["kits"].update_layout(
        title="Kits Required by Type",
        margin=dict(l=30, r=20, t=50, b=120),
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        xaxis=dict(tickangle=-35),
        yaxis=dict(title="Quantity", gridcolor="#F0F0F0"),
    )

    susp_summary = build_suspension_cost_summary(report_df)
    susp_rows = []
    for label, values in susp_summary.items():
        susp_rows.append({
            "Cost Category": label,
            "Front": values["front_cost"],
            "Rear": values["rear_cost"],
            "Total": values["total_cost"],
        })
    susp_df = pd.DataFrame(susp_rows)
    if not susp_df.empty:
        figs["suspension"] = go.Figure()
        figs["suspension"].add_trace(go.Bar(name="Front", x=susp_df["Cost Category"], y=susp_df["Front"], marker_color="#1A1A1A"))
        figs["suspension"].add_trace(go.Bar(name="Rear", x=susp_df["Cost Category"], y=susp_df["Rear"], marker_color="#FF6B00"))
        figs["suspension"].update_layout(
            title="Suspension Repair Cost KPIs — Fleet Scope",
            barmode="group",
            margin=dict(l=40, r=20, t=50, b=80),
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            yaxis=dict(title="Cost (USD)", tickformat="$,.0f", gridcolor="#F0F0F0"),
            xaxis=dict(tickangle=-20),
        )

    figs["severity"] = build_severity_heatmap(report_df)
    figs["hours_cost"] = build_hours_vs_cost_fig(report_df)
    figs["weighted"] = build_weighted_criteria_fig(report_df)

    return figs


def build_severity_heatmap(report_df):
    if not all(col in report_df.columns for col in SEVERITY_COLS):
        return None

    sev_data = report_df[["DT"] + SEVERITY_COLS].set_index("DT")
    sev_data.columns = SEVERITY_LABELS
    fig = go.Figure(go.Heatmap(
        z=sev_data.values,
        x=sev_data.columns,
        y=sev_data.index.astype(str),
        colorscale=[[0.0, "#2ECC71"], [0.5, "#FF9340"], [1.0, "#E74C3C"]],
        zmin=0,
        zmax=2,
        text=sev_data.values,
        texttemplate="%{text}",
        textfont=dict(size=10, family="Barlow Condensed", color="#FFFFFF"),
        hovertemplate="DT %{y} — %{x}<br>Severity: %{z}<extra></extra>",
        showscale=True,
        colorbar=dict(
            title="Level",
            tickvals=[0, 1, 2],
            ticktext=["0 — None", "1 — Moderate", "2 — Severe"],
            tickfont=dict(size=9),
        ),
    ))
    fig.update_layout(
        title="Structural Severity by Truck",
        margin=dict(l=10, r=10, t=30, b=40),
        height=420,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family="Barlow", color="#1A1A1A", size=10),
        xaxis=dict(tickfont=dict(size=10, family="Barlow Condensed")),
        yaxis=dict(tickfont=dict(size=9, family="Barlow Condensed"), autorange="reversed"),
    )
    return fig


def build_hours_vs_cost_fig(report_df):
    if "Hours" not in report_df.columns or "Total_Cost" not in report_df.columns:
        return None
    fig = go.Figure(go.Scatter(
        x=report_df["Hours"],
        y=report_df["Total_Cost"],
        mode="markers+text",
        text=report_df["DT"].astype(str),
        textposition="top center",
        textfont=dict(size=9, family="Barlow Condensed"),
        marker=dict(
            size=12,
            color=report_df["Weighted criteria"] if "Weighted criteria" in report_df.columns else 0,
            colorscale=[[0, "#2ECC71"], [0.4, "#FF9340"], [1, "#E74C3C"]],
            showscale=True,
            colorbar=dict(title="Weighted<br>Criteria", tickfont=dict(size=9)),
            line=dict(width=1, color="#1A1A1A"),
        ),
        hovertemplate="DT %{text}<br>Hours: %{x:,.0f}<br>Cost: $%{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        title="Operating Hours vs Total Cost",
        margin=dict(l=10, r=10, t=30, b=40),
        height=360,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family="Barlow", color="#1A1A1A"),
        xaxis=dict(title="Operating Hours", showgrid=True, gridcolor="#F0F0F0"),
        yaxis=dict(title="Total Cost (USD)", showgrid=True, gridcolor="#F0F0F0", tickformat="$,.0f"),
    )
    return fig


def build_weighted_criteria_fig(report_df):
    if "DT" not in report_df.columns or "Weighted criteria" not in report_df.columns:
        return None
    sorted_df = report_df.sort_values("Weighted criteria", ascending=False).reset_index(drop=True)
    fig = go.Figure(go.Bar(
        x=sorted_df["DT"].astype(str),
        y=sorted_df["Weighted criteria"],
        marker_color=[
            "#E74C3C" if v >= 0.5 else "#FF9340" if v >= 0.25 else "#2ECC71"
            for v in sorted_df["Weighted criteria"]
        ],
        text=[f"{v:.3f}" for v in sorted_df["Weighted criteria"]],
        textposition="outside",
        textfont=dict(size=9, family="Barlow Condensed"),
        hovertemplate="DT %{x}<br>Weighted Criteria: %{y:.3f}<extra></extra>",
    ))
    for level, label, color in [(0.25, "Moderate", "#FF9340"), (0.50, "Severe", "#E74C3C")]:
        fig.add_hline(
            y=level, line_dash="dot", line_color=color, line_width=1.5,
            annotation_text=label, annotation_position="top right",
            annotation_font=dict(size=9, color=color),
        )
    fig.update_layout(
        title="Weighted Crack Criteria by Truck",
        margin=dict(l=10, r=10, t=30, b=40),
        height=360,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family="Barlow", color="#1A1A1A"),
        xaxis=dict(
            title="DT",
            type="category",
            categoryorder="array",
            categoryarray=sorted_df["DT"].astype(str).tolist(),
            tickfont=dict(size=9, family="Barlow Condensed"),
            showgrid=False,
        ),
        yaxis=dict(
            title="Weighted Criteria",
            showgrid=True,
            gridcolor="#F0F0F0",
            range=[0, max(sorted_df["Weighted criteria"].max() * 1.3, 0.6)],
        ),
        bargap=0.3,
    )
    return fig


def build_gantt_fig(report_df, start_date=date.today(), overlap_days=10):
    gantt_df = report_df[["DT", "Total Labour", "Total_Cost"]].copy()
    gantt_df = gantt_df.sort_values(["Total Labour", "Total_Cost"], ascending=[True, True]).reset_index(drop=True)
    gantt_df["Duration_Days"] = gantt_df["Total Labour"] / 24.0

    starts, finishes = [], []
    current_start = pd.Timestamp(start_date)
    for _, row in gantt_df.iterrows():
        duration_days = max(float(row["Duration_Days"]), 0.1)
        finish = current_start + pd.to_timedelta(duration_days, unit="D")
        starts.append(current_start)
        finishes.append(finish)
        current_start = finish - pd.Timedelta(days=overlap_days)

    gantt_df["Start"] = starts
    gantt_df["Finish"] = finishes
    gantt_df["DT_Label"] = gantt_df["DT"].astype(int).astype(str)
    gantt_df["Bar_Label"] = gantt_df.apply(
        lambda r: f'DT {int(r["DT"])} | {r["Duration_Days"]:.1f} d | {int(r["Total Labour"]):,} hrs | ${r["Total_Cost"]:,.0f}',
        axis=1,
    )

    labour_norm = gantt_df["Total Labour"] / gantt_df["Total Labour"].max() if gantt_df["Total Labour"].max() > 0 else gantt_df["Total Labour"]
    bar_colors = [
        "#FF6B00" if v >= 0.85 else "#FF9340" if v >= 0.65 else "#1A1A1A"
        for v in labour_norm
    ]

    fig = px.timeline(
        gantt_df,
        x_start="Start",
        x_end="Finish",
        y="DT_Label",
        category_orders={"DT_Label": gantt_df["DT_Label"].tolist()},
    )
    fig.update_traces(
        marker_color=bar_colors,
        marker_line_color="white",
        marker_line_width=1,
        text=gantt_df["Bar_Label"],
        textposition="inside",
        insidetextanchor="middle",
        textfont=dict(size=10, family="Barlow Condensed", color="#FFFFFF"),
        customdata=list(zip(
            gantt_df["Duration_Days"],
            gantt_df["Total Labour"],
            gantt_df["Total_Cost"],
            gantt_df["Start"].dt.strftime("%b %d, %Y"),
            gantt_df["Finish"].dt.strftime("%b %d, %Y"),
        )),
        hovertemplate=(
            "DT %{y}<br>Start: %{customdata[3]}<br>Finish: %{customdata[4]}<br>"
            "Duration: %{customdata[0]:.1f} d<br>Labour: %{customdata[1]:,.0f} hrs<br>Total cost: $%{customdata[2]:,.0f}<extra></extra>"
        ),
    )
    fig.update_layout(
        title="Reactivation Gantt — Labour Duration by Truck",
        margin=dict(l=30, r=20, t=55, b=55),
        height=max(680, 42 * len(gantt_df)),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family="Barlow", color="#1A1A1A"),
        xaxis=dict(
            title="Timeline",
            showgrid=True,
            gridcolor="#F0F0F0",
            tickformat="%b %d",
            tickfont=dict(size=10, family="Barlow Condensed"),
        ),
        yaxis=dict(
            title="Truck DT",
            type="category",
            categoryorder="array",
            categoryarray=gantt_df["DT_Label"].tolist(),
            autorange="reversed",
            tickfont=dict(size=10, family="Barlow Condensed"),
        ),
        showlegend=False,
    )
    return fig


def build_truck_analysis_figures(report_df):
    # Guard: report_df may be empty during some flows (no data selected)
    if report_df is None or report_df.empty:
        return {
            "selected_dt": None,
            "truck_row": {"Hours": 0, "Weighted criteria": 0.0, "Total_Cost": 0},
            "life": go.Figure(),
            "cost_stack": go.Figure(),
            "suspension": None,
        }

    selected_dt = int(report_df["DT"].astype(int).iloc[0])
    filtered = report_df[report_df["DT"].astype(int) == selected_dt]
    if filtered.empty:
        return {
            "selected_dt": selected_dt,
            "truck_row": {"Hours": 0, "Weighted criteria": 0.0, "Total_Cost": 0},
            "life": go.Figure(),
            "cost_stack": go.Figure(),
            "suspension": None,
        }
    truck_row = filtered.iloc[0]

    all_comp_rows = []
    for flag_col, comp_name in FLAG_COL_TO_COMP.items():
        fk = f"_flag_{comp_name}"
        is_active = int(truck_row.get(fk, truck_row.get(flag_col, 0))) == 1
        life_col = COMP_LIFE_COL.get(comp_name)
        life_pct = (
            float(truck_row[life_col]) if life_col and life_col in truck_row.index and pd.notna(truck_row[life_col]) else None
        )

        if comp_name in comp_data.columns:
            lh = _safe_component_value("Labour hours", comp_name)
            lc = _safe_component_value("Labour cost", comp_name)
            mech = _safe_component_value("Mechanized & Rebuild", comp_name)
            pts = _safe_component_value("parts", comp_name)
            chr_ = _safe_component_value("Chrome tube & rod", comp_name)
            lab_val = lh * lc
            total_c = lab_val + mech + pts + chr_
        else:
            lab_val = mech = pts = chr_ = total_c = 0.0

        all_comp_rows.append({
            "Component": comp_name,
            "Category": COMP_CATEGORY.get(comp_name, "Body"),
            "Life %": life_pct,
            "Required": is_active,
            "Labour Cost": lab_val if is_active else 0.0,
            "Mechanized & Rebuild": mech if is_active else 0.0,
            "Parts": pts if is_active else 0.0,
            "Chrome Tube & Rod": chr_ if is_active else 0.0,
            "Total": total_c if is_active else 0.0,
        })

    cdf = pd.DataFrame(all_comp_rows)
    cdf["Life_pct_display"] = cdf["Life %"].fillna(0) * 100
    cdf_life = cdf.sort_values("Life_pct_display", ascending=True).reset_index(drop=True)

    def life_bar_color(row):
        v = row["Life_pct_display"]
        if v <= 30: return "#2ECC71"
        if v <= 60: return "#FF9340"
        return "#E74C3C"

    bar_life_colors = cdf_life.apply(life_bar_color, axis=1).tolist()
    bar_line_colors = ["#FF6B00" if r else "rgba(0,0,0,0)" for r in cdf_life["Required"]]
    bar_line_widths = [2.5 if r else 0 for r in cdf_life["Required"]]

    fig_life = go.Figure(go.Bar(
        y=cdf_life["Component"],
        x=cdf_life["Life_pct_display"],
        orientation="h",
        marker=dict(color=bar_life_colors, line=dict(color=bar_line_colors, width=bar_line_widths)),
        text=[f"{v:.1f}%" for v in cdf_life["Life_pct_display"]],
        textposition="outside",
        textfont=dict(size=9, family="Barlow Condensed"),
        hovertemplate="%{y}<br>Life: %{x:.1f}%<br>Required: %{customdata}<extra></extra>",
        customdata=["Yes" if r else "No" for r in cdf_life["Required"]],
    ))
    for cat, thr in thresholds.items():
        fig_life.add_vline(
            x=thr * 100,
            line_dash="dot",
            line_color=CATEGORY_COLORS.get(cat, "#888"),
            line_width=1,
            annotation_text=f"{cat} {thr*100:.0f}%",
            annotation_position="top",
            annotation_font=dict(size=8, color=CATEGORY_COLORS.get(cat, "#888")),
        )
    fig_life.update_layout(
        title="Component Life % — Selected Truck",
        margin=dict(l=10, r=80, t=30, b=30),
        height=560,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family="Barlow", color="#1A1A1A"),
        xaxis=dict(title="Life (%)", range=[0, 115], showgrid=True, gridcolor="#F0F0F0", ticksuffix="%"),
        yaxis=dict(tickfont=dict(size=9, family="Barlow Condensed"), autorange="reversed"),
        bargap=0.2,
    )

    cost_cats = ["Labour Cost", "Mechanized & Rebuild", "Parts", "Chrome Tube & Rod"]
    bar_colors = ["#1A1A1A", "#FF6B00", "#FF9340", "#888888"]
    fig_stack = go.Figure()
    for cat, color in zip(cost_cats, bar_colors):
        vals = cdf[cat].tolist()
        fig_stack.add_trace(go.Bar(
            name=cat,
            x=cdf["Component"],
            y=vals,
            marker_color=color,
            text=[f"${v:,.0f}" if v > 0 else "" for v in vals],
            textposition="inside",
            textfont=dict(size=8, family="Barlow Condensed", color="#FFFFFF"),
            hovertemplate=f"{cat}<br>%{{x}}<br>$%{{y:,.0f}}<extra></extra>",
        ))
    fig_stack.add_trace(go.Scatter(
        x=cdf["Component"],
        y=cdf["Total"],
        mode="text",
        text=[f"<b>${v:,.0f}</b>" if v > 0 else "" for v in cdf["Total"]],
        textposition="top center",
        textfont=dict(size=9, family="Barlow Condensed", color="#FF6B00"),
        showlegend=False,
        hoverinfo="skip",
    ))
    fig_stack.update_layout(
        title="Cost Composition per Component — Selected Truck",
        barmode="stack",
        margin=dict(l=10, r=10, t=30, b=120),
        height=500,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family="Barlow", color="#1A1A1A"),
        legend=dict(orientation="h", y=1.08, x=0, font=dict(size=10, family="Barlow Condensed")),
        xaxis=dict(tickangle=-40, tickfont=dict(size=8, family="Barlow Condensed"), showgrid=False),
        yaxis=dict(title="Cost (USD)", showgrid=True, gridcolor="#F0F0F0", tickformat="$,.0f"),
        bargap=0.25,
    )

    fig_susp = None
    susp_df = cdf[cdf["Component"].isin(["Front strut right", "Rear strut right", "Front strut left", "Rear strut left"])].copy()
    if not susp_df.empty:
        fig_susp = go.Figure()
        fig_susp.add_trace(go.Bar(name="Labour Cost", x=susp_df["Component"], y=susp_df["Labour Cost"], marker_color="#1A1A1A"))
        fig_susp.add_trace(go.Bar(name="Mechanized & Rebuild", x=susp_df["Component"], y=susp_df["Mechanized & Rebuild"], marker_color="#FF6B00"))
        fig_susp.add_trace(go.Bar(name="Parts", x=susp_df["Component"], y=susp_df["Parts"], marker_color="#FF9340"))
        fig_susp.add_trace(go.Bar(name="Chrome Tube & Rod", x=susp_df["Component"], y=susp_df["Chrome Tube & Rod"], marker_color="#888888"))
        fig_susp.update_layout(
            title="Suspension Cost Breakdown — Selected Truck",
            barmode="stack",
            margin=dict(l=10, r=10, t=30, b=80),
            height=390,
            paper_bgcolor="#FFFFFF",
            plot_bgcolor="#FFFFFF",
            font=dict(family="Barlow", color="#1A1A1A"),
            legend=dict(orientation="h", y=1.1, x=0, font=dict(size=10, family="Barlow Condensed")),
            xaxis=dict(tickangle=-20, showgrid=False),
            yaxis=dict(title="Cost (USD)", showgrid=True, gridcolor="#F0F0F0", tickformat="$,.0f"),
        )

    return {
        "selected_dt": selected_dt,
        "life": fig_life,
        "cost_stack": fig_stack,
        "suspension": fig_susp,
        "truck_row": truck_row,
        "truck_components": cdf,
    }


def _report_fleet_detail_table(report_df):
    header = [
        "DT", "Hours", "Weighted Criteria", "Labour Hrs",
        "Kit Cost (USD)", "Component Cost (USD)", "Base Cost (USD)", "Total Cost (USD)"
    ]
    rows = []
    table_df = report_df[["DT", "Hours", "Weighted criteria", "Total Labour", "Total cost per kit", "Cost per Components", "Total cost per truck", "Total_Cost"]].copy()
    for _, row in table_df.sort_values("Total_Cost").iterrows():
        rows.append([
            int(row["DT"]),
            f"{row['Hours']:,.0f}",
            f"{row['Weighted criteria']:.3f}",
            f"{row['Total Labour']:,.0f}",
            _format_usd(row["Total cost per kit"]),
            _format_usd(row["Cost per Components"]),
            _format_usd(row["Total cost per truck"]),
            _format_usd(row["Total_Cost"]),
        ])
    return [header] + rows


def _format_kits_table_data(dataframe, max_rows=30):
    df = dataframe.copy().fillna("")
    df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]

    col_map = {}
    for col in df.columns:
        if not isinstance(col, str):
            continue
        lower_col = col.strip().lower()
        if lower_col in {"category", "categoria", "category item"}:
            col_map[col] = "Category"
        elif lower_col in {"pn", "part number", "part no", "part num", "part#"}:
            col_map[col] = "PN"
        elif lower_col in {"description", "descripcion", "desc", "desc."}:
            col_map[col] = "Description"
        elif "qty per truck" in lower_col or lower_col in {"qty", "quantity", "quantity per truck", "qty/truck", "qty per unit"}:
            col_map[col] = "QTY x Truck"
        elif "total required project" in lower_col or lower_col in {"total required", "required project", "total required project", "total required project "}:
            col_map[col] = "Total required"

    df = df.rename(columns=col_map)
    desired_columns = ["Category", "PN", "Description", "QTY x Truck", "Total required"]
    selected_columns = [col for col in desired_columns if col in df.columns]
    df = df[selected_columns]

    rows = [selected_columns]
    for _, row in df.head(max_rows).iterrows():
        rendered = []
        for col in selected_columns:
            value = row[col]
            if col == "QTY x Truck" or col == "Total required":
                try:
                    rendered.append(f"{float(value):,.0f}")
                except Exception:
                    rendered.append(str(value))
            else:
                rendered.append(str(value))
        rows.append(rendered)
    return rows


def _report_selected_truck_kit_rows(report_df):
    if report_df is None or report_df.empty:
        return []

    selected_dt = int(report_df["DT"].astype(int).iloc[0])
    filtered = report_df[report_df["DT"].astype(int) == selected_dt]
    if filtered.empty:
        return []
    truck_row = filtered.iloc[0]
    kit_rows = []
    for kit_col, label in zip(KIT_COLS, KIT_LABELS):
        if kit_col not in truck_row.index:
            continue
        qty = int(truck_row[kit_col]) if pd.notna(truck_row[kit_col]) else 0
        if qty < 1:
            continue
        lh_kit = float(labour_hrs.get(kit_col, 0))
        lc_kit = float(labour_cost.get(kit_col, 0))
        lab_total = lh_kit * CHM_RATE * qty
        parts_total = lc_kit * qty
        kit_rows.append([
            label,
            qty,
            f"{lh_kit * qty:,.0f}",
            _format_usd(lab_total),
            _format_usd(parts_total),
            _format_usd(lab_total + parts_total),
        ])
    if not kit_rows:
        return []
    header = ["Kit", "QTY", "Labour Hours", "Labour Cost (USD)", "Parts Cost (USD)", "Total Cost (USD)"]
    return [header] + kit_rows


def _report_inventory_kpi_table(report_df):
    """Generate KPI table for selected truck from the dataframe."""
    if report_df.empty:
        return [["Metric", "Value"], ["Selected truck", "N/A"]]
    
    # Get the first truck in report_df
    selected_dt = int(report_df["DT"].iloc[0])
    selected_dt_str = str(selected_dt)
    
    # Use cerrejon_impact data
    if selected_dt_str not in cerrejon_impact.columns:
        return [["Metric", "Value"], ["Truck", str(selected_dt)], ["Data", "Not available"]]
    
    inv = cerrejon_impact.copy()
    inv["_truck_qty"] = pd.to_numeric(inv[selected_dt_str], errors="coerce").fillna(0)
    # Fix: Use .get() for column access (correct DataFrame method)
    price_col = inv["Price 2026"] if "Price 2026" in inv.columns else pd.Series([0] * len(inv))
    inv["_truck_cost"] = inv["_truck_qty"] * pd.to_numeric(price_col, errors="coerce").fillna(0)
    required = float(inv["_truck_qty"].sum())
    cost = float(inv["_truck_cost"].sum())
    zero = float(inv.loc[inv["Category Item"].astype(str).str.contains("Zero", case=False, na=False), "_truck_qty"].sum())
    not_cat = float(inv.loc[inv["Category Item"].astype(str).str.contains("Not Catalogued", case=False, na=False), "_truck_qty"].sum())

    return [
        ["Metric", "Value"],
        ["Truck", str(selected_dt)],
        ["Required Parts", f"{required:,.0f}"],
        ["Estimated Inventory Cost", _format_usd(cost)],
        ["Stock in Zero", f"{zero:,.0f}"],
        ["Not Catalogued", f"{not_cat:,.0f}"],
    ]


def _add_fleet_overview_section(story, styles, report_df, figs,
                                thresholds=None, core_filter_metric="", extra_dts=None):
    from reportlab.platypus import Paragraph, Spacer
    story.append(Paragraph("Fleet Overview", styles["Heading2"]))
    _config_model_block(story, styles,
                        thresholds or {}, core_filter_metric, extra_dts or [],
                        "Fleet Overview")
    story.append(_pdf_table(_report_kpi_table(report_df), col_widths=[220, 220]))
    story.append(Spacer(1, 10))
    story.append(_fig_to_pdf_element(figs["fleet_cost"]))
    story.append(Spacer(1, 10))
    story.append(_fig_to_pdf_element(figs["components"]))
    story.append(Spacer(1, 10))
    if figs.get("kits") is not None:
        story.append(_fig_to_pdf_element(figs["kits"]))
        story.append(Spacer(1, 10))
    if figs.get("severity") is not None:
        story.append(_fig_to_pdf_element(figs["severity"]))
        story.append(Spacer(1, 10))
    if figs.get("hours_cost") is not None:
        story.append(_fig_to_pdf_element(figs["hours_cost"]))
        story.append(Spacer(1, 10))
    if figs.get("weighted") is not None:
        story.append(_fig_to_pdf_element(figs["weighted"]))
        story.append(Spacer(1, 10))
    story.append(Paragraph("Fleet detail table", styles["Heading3"]))
    story.append(_pdf_table(_report_fleet_detail_table(report_df), col_widths=[60, 50, 60, 60, 60, 60, 60, 60]))


def _add_cost_analysis_section(story, styles, report_df, figs,
                               thresholds=None, core_filter_metric="", extra_dts=None):
    from reportlab.platypus import Paragraph, Spacer
    story.append(Paragraph("Cost Analysis per Truck", styles["Heading2"]))
    _config_model_block(story, styles,
                        thresholds or {}, core_filter_metric, extra_dts or [],
                        "Cost Analysis per Truck")
    story.append(_fig_to_pdf_element(figs["fleet_cost"]))
    story.append(Spacer(1, 10))
    if "suspension" in figs:
        story.append(_fig_to_pdf_element(figs["suspension"]))
        story.append(Spacer(1, 10))

    truck_figs = build_truck_analysis_figures(report_df)
    story.append(Paragraph(f"Selected Truck Detail — DT {truck_figs['selected_dt']}", styles["Heading3"]))
    story.append(Spacer(1, 6))
    truck_hours = truck_figs['truck_row']['Hours']
    truck_weighted = truck_figs['truck_row']['Weighted criteria']
    story.append(_pdf_table([
        ["Metric", "Value"],
        ["Selected Truck", str(truck_figs["selected_dt"])],
        ["Total Cost", _format_usd(truck_figs["truck_row"]["Total_Cost"])],
        ["Hours", f"{truck_hours:,.0f}"],
        ["Weighted Criteria", f"{truck_weighted:.3f}"],
    ], col_widths=[220, 220]))
    story.append(Spacer(1, 10))
    story.append(_fig_to_pdf_element(truck_figs["life"]))
    story.append(Spacer(1, 10))
    story.append(_fig_to_pdf_element(truck_figs["cost_stack"]))
    if truck_figs.get("suspension") is not None:
        story.append(Spacer(1, 10))
        story.append(_fig_to_pdf_element(truck_figs["suspension"]))


def _add_kit_analysis_section(story, styles, report_df, figs,
                              thresholds=None, core_filter_metric="", extra_dts=None):
    from reportlab.platypus import Paragraph, Spacer
    story.append(Paragraph("Kit Analysis", styles["Heading2"]))
    _config_model_block(story, styles,
                        thresholds or {}, core_filter_metric, extra_dts or [],
                        "Kit Analysis")
    story.append(_fig_to_pdf_element(figs["kits"]))
    story.append(Spacer(1, 10))

    kit_totals = []
    for kit_col, kit_label in zip(KIT_COLS, KIT_LABELS):
        if kit_col in report_df.columns:
            qty = float(pd.to_numeric(report_df[kit_col], errors="coerce").fillna(0).sum())
            if qty > 0:
                kit_totals.append([kit_label, _format_usd(qty)])
    story.append(_pdf_table([["Kit", "Fleet Quantity"]] + kit_totals[:25], col_widths=[330, 110]))
    story.append(Spacer(1, 10))

    if not (report_df is None or report_df.empty):
        selected_dt = int(report_df["DT"].astype(int).iloc[0])
        selected_rows = _report_selected_truck_kit_rows(report_df)
        if selected_rows:
            story.append(Paragraph(f"Selected Truck Kits — DT {selected_dt}", styles["Heading3"]))
            story.append(Spacer(1, 6))
            # Kit | QTY | Labour Hours | Labour Cost | Parts Cost | Total Cost
            # Total usable width ~540pt (letter - margins 72pt)
            story.append(_pdf_table(selected_rows, col_widths=[160, 36, 80, 88, 88, 88]))


def _config_model_block(story, styles, thresholds, core_filter_metric, extra_dts, tab_name):
    """Renders a 'Configuracion del Modelo' collapsible-style table at the top of each tab section."""
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors

    _ORANGE = colors.HexColor("#FF6600")
    _DARK   = colors.HexColor("#1A1A1A")
    _CREAM  = colors.HexColor("#FFF4EC")

    story.append(Spacer(1, 4))
    story.append(Paragraph("Configuracion del Modelo", styles["Heading3"]))

    rows = [["Parametro", "Valor"]]
    rows.append(["Seccion", tab_name])
    rows.append(["Filtro principal", core_filter_metric or "Weighted criteria"])
    rows.append(["DTs adicionales", ", ".join(str(d) for d in extra_dts) if extra_dts else "Ninguno"])
    if thresholds:
        for cat, val in thresholds.items():
            rows.append([f"Umbral — {cat}", f"{val*100:.0f}%"])

    tbl = Table(rows, colWidths=[200, 300], hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  _DARK),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, _CREAM]),
        ("GRID",          (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, _ORANGE),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 10))


def _add_gantt_section(story, styles, report_df,
                       thresholds=None, core_filter_metric="", extra_dts=None):
    from reportlab.platypus import Paragraph, Spacer
    story.append(Paragraph("Reactivation Gantt", styles["Heading2"]))
    _config_model_block(story, styles,
                        thresholds or {}, core_filter_metric, extra_dts or [],
                        "Reactivation Gantt")

    # Gantt figure — width capped at 500pt (letter 612pt - 72pt margins = 540pt usable)
    story.append(_fig_to_pdf_element(build_gantt_fig(report_df), width=500, height=300))
    story.append(Spacer(1, 10))

    gantt_df = report_df[["DT", "Total Labour", "Total_Cost"]].copy()
    gantt_df = gantt_df.sort_values(["Total Labour", "Total_Cost"], ascending=[True, True]).head(30)
    table_data = [["DT", "Labour Hours", "Labour Days", "Total Cost"]]
    for _, row in gantt_df.iterrows():
        labour_hours = float(row["Total Labour"])
        table_data.append([
            f"DT {int(row['DT'])}",
            f"{labour_hours:,.0f}",
            f"{labour_hours / 24:.1f}",
            _format_usd(row["Total_Cost"]),
        ])
    story.append(_pdf_table(table_data, col_widths=[100, 130, 130, 140]))


def _add_inventory_section(story, styles, report_df,
                           thresholds=None, core_filter_metric="", extra_dts=None):
    from reportlab.platypus import Paragraph, Spacer
    story.append(Paragraph("Inventory Analysis", styles["Heading2"]))
    _config_model_block(story, styles,
                        thresholds or {}, core_filter_metric, extra_dts or [],
                        "Inventory Analysis")
    required_col = "Required parts" if "Required parts" in cerrejon_impact.columns else None
    if required_col is None:
        numeric_cols = cerrejon_impact.select_dtypes(include=[np.number]).columns.tolist()
        required_col = numeric_cols[-1] if numeric_cols else None
    category_col = "Inventory category" if "Inventory category" in cerrejon_impact.columns else None
    dt_col = "DT" if "DT" in cerrejon_impact.columns else None

    if required_col and category_col and dt_col:
        inv = cerrejon_impact.copy()
        inv[required_col] = pd.to_numeric(inv[required_col], errors="coerce").fillna(0)
        inv_summary = inv.groupby(category_col, as_index=False)[required_col].sum().sort_values(required_col, ascending=False)
        fig_inv = px.bar(inv_summary, x=category_col, y=required_col, title="Required Parts by Inventory Category")
        fig_inv.update_layout(margin=dict(l=30, r=20, t=50, b=100), paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF")
        story.append(_fig_to_pdf_element(fig_inv))
        story.append(Spacer(1, 10))
        table_data = [["Inventory Category", "Required Parts"]] + [[r[category_col], f"{r[required_col]:,.0f}"] for _, r in inv_summary.iterrows()]
        story.append(_pdf_table(table_data[:25], col_widths=[300, 120]))

        selected_truck_cols = [c for c in cerrejon_impact.columns if str(c).isdigit()]
        if selected_truck_cols:
            selected_dt = selected_truck_cols[0]
            truck_tmp = cerrejon_impact.copy()
            truck_tmp["_truck_qty"] = pd.to_numeric(truck_tmp[selected_dt], errors="coerce").fillna(0)
            # Fix: Use proper column access for DataFrame
            price_col = truck_tmp["Price 2026"] if "Price 2026" in truck_tmp.columns else pd.Series([0] * len(truck_tmp))
            truck_tmp["_truck_cost"] = truck_tmp["_truck_qty"] * pd.to_numeric(price_col, errors="coerce").fillna(0)
            truck_cat = _category_summary(truck_tmp, qty_col="_truck_qty", value_col="_truck_cost")
            story.append(Spacer(1, 10))
            story.append(Paragraph(f"Category Item Mix — DT {selected_dt}", styles["Heading3"]))
            story.append(_pdf_table([["Category Item", "Quantity", "Cost"]] + [[r["Category Item"], f"{r['_truck_qty']:,.0f}", _format_usd(r["_truck_cost"])] for _, r in truck_cat.iterrows()][:25], col_widths=[220, 110, 110]))
            story.append(Spacer(1, 10))
            story.append(_pdf_table(_report_inventory_kpi_table(report_df), col_widths=[220, 220]))

    component_cost_col = "Impact Cerrejon inventory" if "Impact Cerrejon inventory" in component_impact.columns else component_impact.columns[-1]
    comp_cost_df = component_impact[["Component", component_cost_col]].copy()
    comp_cost_df[component_cost_col] = pd.to_numeric(comp_cost_df[component_cost_col], errors="coerce").fillna(0)
    comp_cost_df = comp_cost_df.groupby("Component", as_index=False)[component_cost_col].sum().sort_values(component_cost_col, ascending=False)
    story.append(Spacer(1, 10))
    story.append(Paragraph("Inventory impact cost by component", styles["Heading3"]))
    story.append(_fig_to_pdf_element(_bar_chart(comp_cost_df, "Component", component_cost_col, "Inventory impact cost by component", "Cost (USD)", "$")))


def _add_part_list_section(story, styles,
                           thresholds=None, core_filter_metric="", extra_dts=None):
    from reportlab.platypus import Paragraph, PageBreak, Spacer
    story.append(Paragraph("Part List", styles["Heading2"]))
    _config_model_block(story, styles,
                        thresholds or {}, core_filter_metric, extra_dts or [],
                        "Part List")
    story.append(Paragraph(
        "Kits inventory table is included below. The full part list is paginated to keep the PDF readable.",
        styles["BodyText"],
    ))
    kit_data = _format_kits_table_data(kits_sht, max_rows=len(kits_sht))
    if len(kit_data) > 1:
        header = kit_data[0]
        rows = kit_data[1:]
        page_size = 20
        total_rows = len(rows)
        page_count = (total_rows + page_size - 1) // page_size
        story.append(Paragraph(f"Total rows: {total_rows}. Showing {page_size} rows per page.", styles["BodyText"]))
        story.append(Spacer(1, 8))
        for page_index, start in enumerate(range(0, total_rows, page_size), start=1):
            chunk = rows[start:start + page_size]
            story.append(Paragraph(
                f"Kits Inventory Table — Page {page_index} of {page_count}",
                styles["Heading3"],
            ))
            story.append(Spacer(1, 4))
            # Column widths tuned to letter page (540pt usable).
            # Category and Description need the most space; PN, QTY, Total are narrow.
            width_map = {
                "Category":      120,
                "PN":             70,
                "Description":   200,
                "QTY x Truck":    60,
                "Total required": 70,
            }
            col_widths = [width_map.get(col, max(60, int(540 / max(len(header), 1)))) for col in header]
            story.append(_pdf_table([header] + chunk, col_widths=col_widths))
            if page_index < page_count:
                story.append(PageBreak())
    else:
        story.append(Paragraph("No kit inventory rows were available.", styles["BodyText"]))


def build_dashboard_pdf(report_tab, include_all_tabs=False,
                        thresholds=None, core_filter_metric="", extra_dts=None):
    """Build a PDF report for one tab or for the full project."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
    from reportlab.lib import colors

    thresholds   = thresholds   or {}
    extra_dts    = extra_dts    or []

    # Load logo bytes for page template
    logo_bytes   = None
    eh5000_bytes = None
    if LOGO_PATH.exists():
        try:
            with open(LOGO_PATH, "rb") as _f:
                logo_bytes = _f.read()
        except Exception:
            logo_bytes = None

    # EH5000 image (same directory as this script)
    eh5000_candidates = [
        BASE_DIR / "EH5000-2.webp",
        BASE_DIR / "EH5000-2.png",
        BASE_DIR / "EH5000-2.jpg",
    ]
    for _p in eh5000_candidates:
        if _p.exists():
            try:
                with open(_p, "rb") as _f:
                    eh5000_bytes = _f.read()
            except Exception:
                eh5000_bytes = None
            break

    on_page_cb, top_margin, bot_margin = _make_page_template(logo_bytes, eh5000_bytes)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=top_margin,
        bottomMargin=bot_margin,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        textColor=colors.HexColor("#1A1A1A"),
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=20,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="MetaLine",
        fontName="Helvetica",
        fontSize=7.5,
        textColor=colors.HexColor("#666666"),
        alignment=TA_CENTER,
        spaceAfter=3,
        leading=10,
    ))
    styles.add(ParagraphStyle(
        name="ConfigLine",
        fontName="Helvetica",
        fontSize=6.5,
        textColor=colors.HexColor("#888888"),
        alignment=TA_LEFT,
        spaceAfter=2,
        leading=9,
    ))

    story = []

    # ── Cover block ──────────────────────────────────────────────
    from datetime import datetime
    now_str  = datetime.now().strftime("%B %d, %Y  %H:%M")
    title_text = (
        "EH5000 Fleet Reactivation — Full Project Report"
        if include_all_tabs
        else f"EH5000 Fleet Reactivation — {report_tab} Report"
    )
    story.append(Paragraph(title_text, styles["ReportTitle"]))
    story.append(Spacer(1, 4))

    # Date / time line
    story.append(Paragraph(f"Generated: {now_str}", styles["MetaLine"]))
    story.append(Spacer(1, 3))

    # Sidebar config block (small table for readability)
    config_rows = [
        ["Core filter", core_filter_metric or "Weighted criteria"],
        ["Extra DTs included", ", ".join(str(d) for d in extra_dts) if extra_dts else "None"],
    ]
    if thresholds:
        for cat, val in thresholds.items():
            config_rows.append([f"Threshold — {cat}", f"{val*100:.0f}%"])

    config_table = Table(
        [["Configuration", "Value"]] + config_rows,
        colWidths=[200, 300],
        hAlign="CENTER",
    )
    config_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#1A1A1A")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#FFF4EC")]),
        ("GRID",          (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, colors.HexColor("#FF6B00")),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(config_table)
    story.append(Spacer(1, 14))

    figs = build_report_figures(df)
    tabs_to_add = REPORT_TABS if include_all_tabs else [report_tab]
    _cfg = dict(thresholds=thresholds, core_filter_metric=core_filter_metric, extra_dts=extra_dts)
    section_builders = {
        "Fleet Overview":          lambda: _add_fleet_overview_section(story, styles, df, figs, **_cfg),
        "Cost Analysis per Truck": lambda: _add_cost_analysis_section(story, styles, df, figs, **_cfg),
        "Kit Analysis":            lambda: _add_kit_analysis_section(story, styles, df, figs, **_cfg),
        "Reactivation Gantt":      lambda: _add_gantt_section(story, styles, df, **_cfg),
        "Inventory Analysis":      lambda: _add_inventory_section(story, styles, df, **_cfg),
        "Part List":               lambda: _add_part_list_section(story, styles, **_cfg),
    }

    for i, tab_name in enumerate(tabs_to_add):
        if i > 0:
            story.append(PageBreak())
        section_builders[tab_name]()

    doc.build(story, onFirstPage=on_page_cb, onLaterPages=on_page_cb)
    buffer.seek(0)
    return buffer.getvalue()

# ─────────────────────────────────────────────────────────────────
#  SORTING
# ─────────────────────────────────────────────────────────────────

df_cost_sorted  = df.sort_values("Total_Cost", ascending=False).reset_index(drop=True)
df_crack_sorted = df.sort_values("Weighted criteria", ascending=False).reset_index(drop=True)

# ─────────────────────────────────────────────────────────────────
#  PDF REPORT CONTROLS
# ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("---")
    st.markdown("### PDF Reports")
    st.caption("Reports use the current filters and thresholds. CSV/table downloads were removed.")

    report_tab_choice = st.selectbox(
        "Tab report section",
        options=REPORT_TABS,
        index=0,
        help=(
            "Select the tab/section to export. Native Streamlit tabs do not expose the active tab to Python, "
            "so choose the section matching the tab currently being reviewed."
        ),
    )

    # Performance improvement: PDF generation is expensive because it renders Plotly
    # figures through Kaleido. The previous version generated both PDFs on every
    # Streamlit rerun, even when the user did not download them. Now reports are
    # generated only after the user explicitly clicks a button.
    pdf_config_key = (
        report_tab_choice,
        tuple(sorted((k, round(float(v), 4)) for k, v in thresholds.items())),
        core_filter_metric,
        tuple(int(x) for x in extra_dts),
        tuple(int(x) for x in active_dts),
    )

    if st.session_state.get("pdf_config_key") != pdf_config_key:
        st.session_state.pdf_config_key = pdf_config_key
        st.session_state.current_tab_pdf_bytes = None
        st.session_state.current_tab_pdf_name = None
        st.session_state.full_project_pdf_bytes = None

    if "current_tab_pdf_bytes" not in st.session_state:
        st.session_state.current_tab_pdf_bytes = None
        st.session_state.current_tab_pdf_name = None
    if "full_project_pdf_bytes" not in st.session_state:
        st.session_state.full_project_pdf_bytes = None

    if st.button("Generate Tab Report", use_container_width=True):
        with st.spinner("Generating tab PDF report..."):
            st.session_state.current_tab_pdf_bytes = build_dashboard_pdf(
                report_tab_choice,
                include_all_tabs=False,
                thresholds=thresholds,
                core_filter_metric=core_filter_metric,
                extra_dts=extra_dts,
            )
            st.session_state.current_tab_pdf_name = f"EH5000_{report_tab_choice.replace(' ', '_')}_report.pdf"

    if st.session_state.current_tab_pdf_bytes is not None:
        st.download_button(
            "📥 Download Tab Report",
            data=st.session_state.current_tab_pdf_bytes,
            file_name=st.session_state.current_tab_pdf_name or f"EH5000_{report_tab_choice.replace(' ', '_')}_report.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

    if st.button("Generate Full Project Report", use_container_width=True):
        with st.spinner("Generating full project PDF report..."):
            st.session_state.full_project_pdf_bytes = build_dashboard_pdf(
                report_tab_choice,
                include_all_tabs=True,
                thresholds=thresholds,
                core_filter_metric=core_filter_metric,
                extra_dts=extra_dts,
            )

    if st.session_state.full_project_pdf_bytes is not None:
        st.download_button(
            "📋 Download Full Project Report",
            data=st.session_state.full_project_pdf_bytes,
            file_name="EH5000_full_project_report.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

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
    <div class="lc-header" style="margin-top:40px;">
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

tab_fleet, tab_truck, tab_kits, tab_gantt, tab_inventory, tab_inventory_total = st.tabs([
    "Fleet Overview", "Cost Analysis per Truck", "Kit Analysis", "Reactivation Gantt",
    "Inventory Analysis", "Part List",
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

    # ── Avg cost breakdown sub-KPIs (derived from already-computed df columns) ──
    _n_trucks = max(len(df), 1)  # guard against empty fleet
    avg_cost_kits   = df["Total cost per kit"].fillna(0).mean() if "Total cost per kit" in df.columns else 0.0
    avg_cost_labour = df["Total Labour"].fillna(0).mean() * CHM_RATE
    avg_cost_comp   = df["Cost per Components"].fillna(0).mean() if "Cost per Components" in df.columns else 0.0
    # Inventory impact is a fleet-level figure (not per-truck in the source data);
    # divide the same total used by the Inventory Analysis tab by active truck count.
    _cer_col  = "Impact Cerrejon Inventory"   # capital I — matches cerrejon_impact sheet (V10)
    _comp_col = "Impact Cerrejon inventory"   # lowercase i — matches component_impact sheet (V10)
    _cer_tot  = pd.to_numeric(
        cerrejon_impact.get(_cer_col, 0),
        errors="coerce"
    ).fillna(0).sum()
    _comp_tot = pd.to_numeric(
        component_impact.get(_comp_col, 0),
        errors="coerce"
    ).fillna(0).sum()
    avg_cost_inventory = (_cer_tot + _comp_tot) / _n_trucks

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
        <div class="kpi-grid">
          <div class="kpi-card"><div class="kpi-label">Avg Cost — Kits</div>
            <div class="kpi-value">${avg_cost_kits:,.0f}</div>
            <div class="kpi-sub">kit parts cost per truck</div></div>
          <div class="kpi-card"><div class="kpi-label">Avg Cost — Labour</div>
            <div class="kpi-value">${avg_cost_labour:,.0f}</div>
            <div class="kpi-sub">kits + components labour per truck</div></div>
          <div class="kpi-card"><div class="kpi-label">Avg Cost — Component Parts</div>
            <div class="kpi-value">${avg_cost_comp:,.0f}</div>
            <div class="kpi-sub">component replacement per truck</div></div>
          <div class="kpi-card"><div class="kpi-label">Avg Cost — Inventory Impact</div>
            <div class="kpi-value">${avg_cost_inventory:,.0f}</div>
            <div class="kpi-sub">inventory exposure per truck</div></div>
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
        st.markdown(
            '<div class="section-title">Components Required by Type</div>',
            unsafe_allow_html=True,
        )
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
        sev_data = df[["DT"] + SEVERITY_COLS].set_index("DT")
        sev_data.columns = SEVERITY_LABELS
        fig_heat = go.Figure(go.Heatmap(
            z=sev_data.values, x=SEVERITY_LABELS, y=sev_data.index.astype(str),
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
    if not all_dts:
        st.info("No trucks available for analysis")
    else:
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
            lh   = _safe_component_value("Labour hours", comp_name)
            lc   = _safe_component_value("Labour cost", comp_name)
            mech = _safe_component_value("Mechanized & Rebuild", comp_name)
            pts  = _safe_component_value("parts", comp_name)
            chr_ = _safe_component_value("Chrome tube & rod", comp_name)
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



    # ── Suspension-only analysis ──
    st.markdown('<div class="section-title">Suspension Cost Analysis — Selected Truck</div>', unsafe_allow_html=True)
    suspension_components = [
        "Front strut right", "Rear strut right", "Front strut left", "Rear strut left"
    ]
    susp_df = cdf[cdf["Component"].isin(suspension_components)].copy()
    susp_total = float(susp_df["Total"].sum())
    required_susp = int(susp_df["Required"].sum())
    avg_susp_life = float(susp_df["Life_pct_display"].mean()) if not susp_df.empty else 0.0
    sa, sb, sc = st.columns(3)
    with sa:
        st.markdown(f'<div class="kpi-card"><div class="kpi-label">Suspension Cost</div><div class="kpi-value" style="font-size:1.45rem;">${susp_total:,.0f}</div><div class="kpi-sub">selected truck</div></div>', unsafe_allow_html=True)
    with sb:
        st.markdown(f'<div class="kpi-card"><div class="kpi-label">Suspensions Required</div><div class="kpi-value" style="font-size:1.45rem;">{required_susp}</div><div class="kpi-sub">out of {len(susp_df)}</div></div>', unsafe_allow_html=True)
    with sc:
        st.markdown(f'<div class="kpi-card"><div class="kpi-label">Avg Suspension Life</div><div class="kpi-value" style="font-size:1.45rem;">{avg_susp_life:.1f}%</div><div class="kpi-sub">life indicator</div></div>', unsafe_allow_html=True)

    if not susp_df.empty:
        fig_susp = go.Figure()
        fig_susp.add_trace(go.Bar(
            name="Labour Cost", x=susp_df["Component"], y=susp_df["Labour Cost"],
            marker_color="#1A1A1A", hovertemplate="%{x}<br>Labour: $%{y:,.0f}<extra></extra>",
        ))
        fig_susp.add_trace(go.Bar(
            name="Mechanized & Rebuild", x=susp_df["Component"], y=susp_df["Mechanized & Rebuild"],
            marker_color="#FF6B00", hovertemplate="%{x}<br>Mechanized: $%{y:,.0f}<extra></extra>",
        ))
        fig_susp.add_trace(go.Bar(
            name="Parts", x=susp_df["Component"], y=susp_df["Parts"],
            marker_color="#FF9340", hovertemplate="%{x}<br>Parts: $%{y:,.0f}<extra></extra>",
        ))
        fig_susp.add_trace(go.Bar(
            name="Chrome Tube & Rod", x=susp_df["Component"], y=susp_df["Chrome Tube & Rod"],
            marker_color="#888888", hovertemplate="%{x}<br>Chrome: $%{y:,.0f}<extra></extra>",
        ))
        fig_susp.update_layout(
            barmode="stack", height=390, margin=dict(l=10, r=10, t=25, b=80),
            paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
            font=dict(family="Barlow", color="#1A1A1A"),
            legend=dict(orientation="h", y=1.1, x=0, font=dict(size=10, family="Barlow Condensed")),
            xaxis=dict(tickangle=-20, showgrid=False),
            yaxis=dict(title="Cost (USD)", showgrid=True, gridcolor="#F0F0F0", tickformat="$,.0f"),
        )
        st.plotly_chart(fig_susp, use_container_width=True, config={"displayModeBar": False})

        # ── Suspension repair cost KPIs — Front / Rear / Fleet ──
        st.markdown('<div class="section-title">Suspension Repair Cost KPIs — Fleet Scope</div>', unsafe_allow_html=True)
        suspension_summary = build_suspension_cost_summary(df)
        kpi_cols = st.columns(4)
        for col_obj, (display_label, cost_key) in zip(kpi_cols, SUSPENSION_COST_LABELS.items()):
            with col_obj:
                st.markdown(
                    render_suspension_kpi_card(display_label, suspension_summary[cost_key]),
                    unsafe_allow_html=True,
                )

        top_susp = susp_df.sort_values("Total", ascending=False).iloc[0]
        st.markdown(
            f'<p style="font-size:0.9rem;color:#555;line-height:1.5;">'
            f'For DT <b>{int(sel_dt)}</b>, the suspension-only scope includes front and rear struts. '
            f'The current threshold configuration flags <b>{required_susp}</b> suspension position(s), with an estimated '
            f'suspension-related cost of <b>${susp_total:,.0f}</b>. The largest suspension cost contributor is '
            f'<b>{top_susp["Component"]}</b> at <b>${float(top_susp["Total"]):,.0f}</b>.</p>',
            unsafe_allow_html=True,
        )

# ═══════════════════════════════════════════════════════════════
#  TAB 3 — KIT ANALYSIS
# ═══════════════════════════════════════════════════════════════
with tab_kits:
    all_dts_kit = sorted([int(x) for x in df["DT"].tolist()])
    if not all_dts_kit:
        st.info("No trucks available for kit analysis")
    else:
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

        total_labour_hours = kdf["Labour Hours"].sum()
        total_labour_cost = kdf["Labour Cost (USD)"].sum()
        total_parts_cost = kdf["Parts Cost (USD)"].sum()
        total_repair_cost = float(trk.get("Cost per Components", 0) or 0)

        k1, k2, k3, k4, k5, k6 = st.columns(6)
        with k1:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">Total Kit Types</div>'
                f'<div class="kpi-value" style="font-size:1.6rem;">{len(kdf)}</div>'
                f'<div class="kpi-sub">types applied</div></div>',
                unsafe_allow_html=True,
            )
        with k2:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">Total Quantity</div>'
                f'<div class="kpi-value" style="font-size:1.6rem;">{kdf["Quantity"].sum()}</div>'
                f'<div class="kpi-sub">units all kits</div></div>',
                unsafe_allow_html=True,
            )
        with k3:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">Labour Hours</div>'
                f'<div class="kpi-value" style="font-size:1.6rem;">{total_labour_hours:,.0f}</div>'
                f'<div class="kpi-sub">hours</div></div>',
                unsafe_allow_html=True,
            )
        with k4:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">Labour Cost</div>'
                f'<div class="kpi-value" style="font-size:1.6rem;">${total_labour_cost:,.0f}</div>'
                f'<div class="kpi-sub">USD</div></div>',
                unsafe_allow_html=True,
            )
        with k5:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">Part Cost</div>'
                f'<div class="kpi-value" style="font-size:1.6rem;">${total_parts_cost:,.0f}</div>'
                f'<div class="kpi-sub">USD</div></div>',
                unsafe_allow_html=True,
            )
        with k6:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">Repair Cost</div>'
                f'<div class="kpi-value" style="font-size:1.6rem;">${total_repair_cost:,.0f}</div>'
                f'<div class="kpi-sub">USD — components</div></div>',
                unsafe_allow_html=True,
            )

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


# ═══════════════════════════════════════════════════════════════
# INVENTORY ANALYSIS TAB
# ═══════════════════════════════════════════════════════════════
with tab_inventory:
    # ==========================================================
    # SECTION TITLE
    # ==========================================================
    st.markdown(
        '<div class="section-title">Inventory Impact Overview</div>',
        unsafe_allow_html=True
    )
    # ==========================================================
    # MAIN COLUMNS (normalized)
    # ==========================================================
    cer_impact_col  = "Impact Cerrejon Inventory"  # capital I — cerrejon_impact sheet column (V10)
    comp_impact_col = "Impact Cerrejon inventory"   # lowercase i — component_impact sheet column (V10)
    # ==========================================================
    # TOTALS
    # ==========================================================
    total_cer = pd.to_numeric(
        cerrejon_impact.get(cer_impact_col, 0),
        errors="coerce"
    ).fillna(0).sum()
    total_comp = pd.to_numeric(
        component_impact.get(comp_impact_col, 0),
        errors="coerce"
    ).fillna(0).sum()
    total_inventory_impact = total_cer + total_comp
    # ==========================================================
    # KPI CARDS
    # ==========================================================
    k1, k2, k3 = st.columns(3)
    with k1:
        st.markdown(
            f'''
            <div class="kpi-card">
                <div class="kpi-label">TOTAL INVENTORY IMPACT</div>
                <div class="kpi-value">${total_inventory_impact:,.0f}</div>
                <div class="kpi-sub">combined inventory exposure</div>
            </div>
            ''',
            unsafe_allow_html=True
        )
    with k2:
        st.markdown(
            f'''
            <div class="kpi-card">
                <div class="kpi-label">CERREJON INVENTORY IMPACT</div>
                <div class="kpi-value">${total_cer:,.0f}</div>
                <div class="kpi-sub">from Cerrejon inventory impact</div>
            </div>
            ''',
            unsafe_allow_html=True
        )
    with k3:
        st.markdown(
            f'''
            <div class="kpi-card">
                <div class="kpi-label">COMPONENT PARTS IMPACT</div>
                <div class="kpi-value">${total_comp:,.0f}</div>
                <div class="kpi-sub">from Component parts impact</div>
            </div>
            ''',
            unsafe_allow_html=True
        )
    # ==========================================================
    # FILTER TITLE
    # ==========================================================
    st.markdown(
        '<div class="section-title">Inventory Category Filter</div>',
        unsafe_allow_html=True
    )
    # ==========================================================
    # FILTER OPTIONS
    # ==========================================================
    inventory_categories = sorted(
        cerrejon_impact[
            "Category Item"
        ].dropna().astype(str).unique()
    )
    selected_inventory_categories = st.multiselect(
        "Filter inventory category",
        options=inventory_categories,
        default=inventory_categories,
        key="inventory_category_filter"
    )
    # ==========================================================
    # FILTERED DATAFRAME
    # ==========================================================
    filtered_inventory_df = cerrejon_impact[
        cerrejon_impact[
            "Category Item"
        ].astype(str).isin(selected_inventory_categories)
    ].copy()
    # ==========================================================
    # TRUCK COLUMNS
    # ==========================================================
    truck_cols = [
        c for c in filtered_inventory_df.columns
        if str(c).isdigit()
    ]
    active_truck_cols = [
        c for c in truck_cols
        if pd.to_numeric(
            filtered_inventory_df[c],
            errors="coerce"
        ).fillna(0).sum() > 0
    ]
    # ==========================================================
    # REQUIRED PARTS BY TRUCK
    # ==========================================================
    truck_part_totals = (
        filtered_inventory_df[active_truck_cols]
        .apply(pd.to_numeric, errors="coerce")
        .fillna(0)
        .sum()
        .reset_index()
    )
    truck_part_totals.columns = [
        "Truck",
        "Required Parts"
    ]
    truck_part_totals = truck_part_totals.sort_values(
        "Required Parts",
        ascending=False
    )
    # ==========================================================
    # SECTION TITLE
    # ==========================================================
    st.markdown(
        '<div class="section-title">Cerrejon Inventory Impact — Required Parts by Truck</div>',
        unsafe_allow_html=True
    )
    # ==========================================================
    # MAIN CHART
    # ==========================================================
    # Build the same Required Parts by Truck chart, but preserve
    # Category Item as a visual dimension so every inventory category
    # selected in the filter has its own color in the bar.
    inventory_chart_df = filtered_inventory_df[[
        "Category Item",
        *active_truck_cols
    ]].copy()

    inventory_chart_long = inventory_chart_df.melt(
        id_vars="Category Item",
        value_vars=active_truck_cols,
        var_name="Truck",
        value_name="Required Parts"
    )

    inventory_chart_long["Required Parts"] = pd.to_numeric(
        inventory_chart_long["Required Parts"],
        errors="coerce"
    ).fillna(0)

    inventory_chart_long["Category Item"] = (
        inventory_chart_long["Category Item"]
        .astype(str)
        .str.strip()
    )

    inventory_chart_long = (
        inventory_chart_long
        .groupby(["Truck", "Category Item"], as_index=False)["Required Parts"]
        .sum()
    )

    inventory_chart_long = inventory_chart_long[
        inventory_chart_long["Required Parts"] > 0
    ]

    truck_order = truck_part_totals["Truck"].astype(str).tolist()
    inventory_chart_long["Truck"] = inventory_chart_long["Truck"].astype(str)

    inventory_category_palette = [
        "#FF6B00", "#1A1A1A", "#FF9340", "#888888",
        "#FF4500", "#6C757D", "#C45A00", "#B8B8B8",
        "#2F2F2F", "#F4A261", "#A0A0A0", "#D55E00",
    ]

    inventory_category_colors = {
        category: inventory_category_palette[idx % len(inventory_category_palette)]
        for idx, category in enumerate(
            sorted(inventory_chart_long["Category Item"].dropna().unique())
        )
    }

    fig_inventory_required = px.bar(
        inventory_chart_long,
        x="Truck",
        y="Required Parts",
        color="Category Item",
        text="Required Parts",
        title="Total required parts by truck",
        color_discrete_map=inventory_category_colors,
        category_orders={"Truck": truck_order},
    )

    fig_inventory_required.update_traces(
        texttemplate="%{text:,.0f}",
        textposition="inside",
        hovertemplate=(
            "Truck: %{x}<br>"
            "Category: %{legendgroup}<br>"
            "Required parts: %{y:,.0f}<extra></extra>"
        ),
    )

    fig_inventory_required.update_layout(
        paper_bgcolor="white",
        plot_bgcolor="white",
        height=500,
        margin=dict(l=20, r=20, t=60, b=20),
        xaxis_title="",
        yaxis_title="Required parts",
        barmode="stack",
        legend_title_text="Inventory Category",
        font=dict(
            family="Arial",
            size=14,
            color="black"
        )
    )

    st.plotly_chart(
        fig_inventory_required,
        use_container_width=True,
        config={"displayModeBar": False}
    )
    # ==========================================================
    # CATEGORY MIX TOTAL FLEET
    # ==========================================================
    total_cat_cer = _category_summary(
        filtered_inventory_df,
        qty_col="Grand Total",
        value_col=cer_impact_col
    )
    _render_category_cards(
        total_cat_cer,
        "Category Item Mix — Total Fleet"
    )
    # ==========================================================
    # SELECT TRUCK
    # ==========================================================
    selected_inv_dt = st.selectbox(
        "Select Truck for inventory KPIs",
        options=sorted([int(x) for x in active_truck_cols]),
        format_func=lambda x: f"DT {x}",
        key="inventory_dt_sel"
    )
    # ==========================================================
    # TRUCK DATAFRAME
    # ==========================================================
    truck_tmp = filtered_inventory_df.copy()

    truck_col = None

    if str(selected_inv_dt) in truck_tmp.columns:
        truck_col = str(selected_inv_dt)
    elif selected_inv_dt in truck_tmp.columns:
        truck_col = selected_inv_dt
    else:
        possible_cols = [
            c for c in truck_tmp.columns
            if str(c).strip() == str(selected_inv_dt).strip()
        ]

        if possible_cols:
            truck_col = possible_cols[0]

    if truck_col is None:
        st.error(f"Truck column DT {selected_inv_dt} not found in dataframe.")
        st.stop()

    truck_tmp["_truck_qty"] = pd.to_numeric(
        truck_tmp[truck_col],
        errors="coerce"
    ).fillna(0)

    truck_tmp["_truck_cost"] = (
        truck_tmp["_truck_qty"]
        * pd.to_numeric(
            truck_tmp["Price 2026"],
            errors="coerce"
        ).fillna(0)
    )
    # ==========================================================
    # CATEGORY MIX DT
    # ==========================================================
    truck_cat = _category_summary(
        truck_tmp,
        qty_col="_truck_qty",
        value_col="_truck_cost"
    )
    _render_category_cards(
        truck_cat,
        f"Category Item Mix — DT {selected_inv_dt}"
    )
    # ==========================================================
    # COST BY PART NUMBER
    # ==========================================================
    st.markdown(
        '<div class="section-title">Cerrejon Inventory Impact — Cost by Part Number</div>',
        unsafe_allow_html=True
    )
    cer_cost_df = truck_tmp[[
        "Row Labels",
        "_truck_cost"
    ]].copy()
    cer_cost_df = cer_cost_df.sort_values(
        "_truck_cost",
        ascending=False
    ).head(25)
    st.plotly_chart(
        _bar_chart(
            cer_cost_df,
            "Row Labels",
            "_truck_cost",
            "Top 25 part numbers by inventory impact cost",
            "Cost (USD)",
            "$"
        ),
        use_container_width=True,
        config={"displayModeBar": False}
    )
    # ==========================================================
    # COMPONENT PARTS IMPACT
    # ==========================================================
    st.markdown(
        '<hr>',
        unsafe_allow_html=True
    )
    st.markdown(
        '<div class="section-title">Component Parts Impact</div>',
        unsafe_allow_html=True
    )
    comp_parts_df = component_impact[[
        "Component",
        "Total components required"
    ]].copy()
    comp_parts_df[
        "Total components required"
    ] = pd.to_numeric(
        comp_parts_df[
            "Total components required"
        ],
        errors="coerce"
    ).fillna(0)
    comp_parts_df = (
        comp_parts_df
        .groupby("Component", as_index=False)["Total components required"]
        .sum()
        .sort_values(
            "Total components required",
            ascending=False
        )
    )
    st.plotly_chart(
        _bar_chart(
            comp_parts_df,
            "Component",
            "Total components required",
            "Total required parts by component",
            "Required parts"
        ),
        use_container_width=True,
        config={"displayModeBar": False}
    )
    # ==========================================================
    # CATEGORY MIX COMPONENTS
    # ==========================================================
    total_cat_comp = _category_summary(
        component_impact,
        qty_col="Total components required",
        value_col=comp_impact_col
    )
    _render_category_cards(
        total_cat_comp,
        "Category Item Mix — Component Parts"
    )
    # ==========================================================
    # COMPONENT COST
    # ==========================================================
    st.markdown(
        '<div class="section-title">Component Parts Impact — Cost by Component</div>',
        unsafe_allow_html=True
    )
    comp_cost_df = component_impact[[
        "Component",
        comp_impact_col
    ]].copy()
    comp_cost_df[comp_impact_col] = pd.to_numeric(
        comp_cost_df[comp_impact_col],
        errors="coerce"
    ).fillna(0)
    comp_cost_df = (
        comp_cost_df
        .groupby("Component", as_index=False)[comp_impact_col]
        .sum()
        .sort_values(
            comp_impact_col,
            ascending=False
        )
    )
    st.plotly_chart(
        _bar_chart(
            comp_cost_df,
            "Component",
            comp_impact_col,
            "Inventory impact cost by component",
            "Cost (USD)",
            "$"
        ),
        use_container_width=True,
        config={"displayModeBar": False}
    )
    # ==========================================================
    # SELECTED TRUCK KPIs
    # ==========================================================
    st.markdown(
        '<div class="section-title">Selected Truck Inventory KPIs</div>',
        unsafe_allow_html=True
    )
    truck_required = float(
        truck_tmp["_truck_qty"].sum()
    )
    truck_cost = float(
        truck_tmp["_truck_cost"].sum()
    )
    truck_zero = float(
        truck_tmp.loc[
            truck_tmp[
                "Category Item"
            ].astype(str).str.contains(
                "Zero",
                case=False,
                na=False
            ),
            "_truck_qty"
        ].sum()
    )
    truck_not_cat = float(
        truck_tmp.loc[
            truck_tmp[
                "Category Item"
            ].astype(str).str.contains(
                "Not Catalogued",
                case=False,
                na=False
            ),
            "_truck_qty"
        ].sum()
    )
    ka, kb, kc, kd = st.columns(4)
    with ka:
        st.markdown(
            f'''
            <div class="kpi-card">
                <div class="kpi-label">Required Parts</div>
                <div class="kpi-value" style="font-size:1.45rem;">{truck_required:,.0f}</div>
                <div class="kpi-sub">DT {selected_inv_dt}</div>
            </div>
            ''',
            unsafe_allow_html=True
        )
    with kb:
        st.markdown(
            f'''
            <div class="kpi-card">
                <div class="kpi-label">Estimated Inventory Cost</div>
                <div class="kpi-value" style="font-size:1.45rem;">${truck_cost:,.0f}</div>
                <div class="kpi-sub">qty × Price 2026</div>
            </div>
            ''',
            unsafe_allow_html=True
        )
    with kc:
        st.markdown(
            f'''
            <div class="kpi-card">
                <div class="kpi-label">Stock in Zero</div>
                <div class="kpi-value" style="font-size:1.45rem;">{truck_zero:,.0f}</div>
                <div class="kpi-sub">parts</div>
            </div>
            ''',
            unsafe_allow_html=True
        )
    with kd:
        st.markdown(
            f'''
            <div class="kpi-card">
                <div class="kpi-label">Not Catalogued</div>
                <div class="kpi-value" style="font-size:1.45rem;">{truck_not_cat:,.0f}</div>
                <div class="kpi-sub">parts</div>
            </div>
            ''',
            unsafe_allow_html=True
        )
# ═══════════════════════════════════════════════════════════════
#  TAB 6 — KITS TABLE
# ═══════════════════════════════════════════════════════════════
with tab_inventory_total:

    st.markdown(
        '<div class="section-title">Kits Inventory Table</div>',
        unsafe_allow_html=True
    )

    # ==========================================================
    # LOAD SUMMARY INVENTORY TABLE
    # ==========================================================
    inv_tbl = kits_sht.copy()

    inv_tbl.columns = (
        inv_tbl.columns
        .astype(str)
        .str.strip()
    )

    inv_tbl = inv_tbl.dropna(how="all")

    col_map = {}
    for col in inv_tbl.columns:
        lower_col = col.strip().lower()
        if lower_col in {"category", "categoria", "category item"}:
            col_map[col] = "Category"
        elif lower_col in {"pn", "part number", "part no", "part num", "part#"}:
            col_map[col] = "PN"
        elif lower_col in {"description", "descripcion", "desc", "desc."}:
            col_map[col] = "Description"
        elif "qty per truck" in lower_col or lower_col in {"qty", "quantity", "quantity per truck", "qty/truck", "qty per unit"}:
            col_map[col] = "QTY x Truck"
        elif "total required project" in lower_col or lower_col in {"total required", "required project", "total project", "total required project"}:
            col_map[col] = "Total required"

    inv_tbl = inv_tbl.rename(columns=col_map)
    desired_columns = ["Category", "PN", "Description", "QTY x Truck", "Total required"]
    inv_tbl = inv_tbl[[col for col in desired_columns if col in inv_tbl.columns]]

    for col in ["QTY x Truck", "Total required"]:
        if col in inv_tbl.columns:
            inv_tbl[col] = (
                pd.to_numeric(inv_tbl[col], errors="coerce")
                .fillna(0)
            )

    # ==========================================================
    # KPIs
    # ==========================================================
    t1, t2, t3 = st.columns(3)

    with t1:
        st.markdown(
            f'''
            <div class="kpi-card">
                <div class="kpi-label">Rows</div>
                <div class="kpi-value" style="font-size:1.45rem;">
                    {len(inv_tbl):,.0f}
                </div>
            </div>
            ''',
            unsafe_allow_html=True
        )

    with t2:
        total_qty = inv_tbl["QTY x Truck"].sum() if "QTY x Truck" in inv_tbl.columns else 0
        st.markdown(
            f'''
            <div class="kpi-card">
                <div class="kpi-label">Total Quantity</div>
                <div class="kpi-value" style="font-size:1.45rem;">
                    {total_qty:,.0f}
                </div>
            </div>
            ''',
            unsafe_allow_html=True
        )

    with t3:
        total_req = inv_tbl["Total required"].sum() if "Total required" in inv_tbl.columns else 0
        st.markdown(
            f'''
            <div class="kpi-card">
                <div class="kpi-label">Total Required</div>
                <div class="kpi-value" style="font-size:1.45rem;">
                    {total_req:,.0f}
                </div>
            </div>
            ''',
            unsafe_allow_html=True
        )

    filter_col = "Category" if "Category" in inv_tbl.columns else inv_tbl.columns[0]
    inv_tbl[filter_col] = (
        inv_tbl[filter_col]
        .astype(str)
        .str.strip()
    )

    available_values = sorted(
        inv_tbl[filter_col]
        .dropna()
        .unique()
    )

    selected_values = st.multiselect(
        f"Filter table by {filter_col}",
        options=available_values,
        default=[],
        key="inventory_total_kit_filter",
    )

    display_inv = (
        inv_tbl[
            inv_tbl[filter_col]
            .isin(selected_values)
        ].copy()
        if selected_values
        else inv_tbl.copy()
    )

    st.dataframe(
        display_inv,
        use_container_width=True,
        hide_index=True,
        column_config={
            "QTY x Truck": st.column_config.NumberColumn(
                "QTY x Truck",
                format="%.0f"
            ),
            "Total required": st.column_config.NumberColumn(
                "Total required",
                format="%.0f"
            ),
        },
    )

    # CSV/table downloads removed. Reporting is handled only through the PDF controls in the sidebar.

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
