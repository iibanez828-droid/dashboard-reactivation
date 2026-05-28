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
import re
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
#  TAB SPACING FIX
# ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Keep the top tab navigation compact and evenly spaced after adding the integrated tabs. */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px !important;
    flex-wrap: wrap !important;
}
.stTabs [data-baseweb="tab"] {
    padding: 8px 12px !important;
    margin-right: 0 !important;
    min-width: fit-content !important;
}
.stTabs [data-baseweb="tab"] p {
    font-size: 0.88rem !important;
    white-space: nowrap !important;
}
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

    # All v25 global controls are grouped in a collapsed expander so the sidebar
    # only shows the tab name until the user needs to adjust that section.
    with st.expander("Fleet Overview", expanded=False):
        st.caption("Core fleet selection and component threshold controls used by the v25 dashboard tabs.")

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

    # The v25 dashboard controls are intentionally centralized in this single
    # expander. The original v25 tabs below all use these same global filters,
    # so separate sidebar placeholders for Cost Analysis, Kit Analysis, Gantt,
    # Inventory, and Part List are not rendered to avoid repeated menu items.

    # Reserved sidebar positions for the integrated project controls.
    # These containers are filled later by the embedded apps, but their position
    # stays here so the sidebar order remains clean and predictable:
    # Fleet Overview -> Availability report & Forecast -> Strut model risk assessment -> PDF Reports.
    AVAILABILITY_SIDEBAR_SLOT = st.container()
    STRUT_SIDEBAR_SLOT = st.container()
    PDF_REPORTS_SIDEBAR_SLOT = st.container()
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

@st.cache_data(show_spinner=False)
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


@st.cache_data(show_spinner=False)
def build_active_dataset_cached(df_base_input: pd.DataFrame, active_dts_tuple: tuple[int, ...], thresholds_tuple: tuple[tuple[str, float], ...]) -> pd.DataFrame:
    """Return the filtered active fleet with dynamic component flags and costs.

    This is the main cache layer affected by the Fleet Overview sidebar.
    It avoids recalculating component flags and total costs when the user
    navigates between tabs without changing thresholds or selected trucks.
    """
    thresholds_dict = {str(k): float(v) for k, v in thresholds_tuple}
    dataframe = df_base_input[df_base_input["DT"].isin(active_dts_tuple)].copy()
    dataframe.columns = dataframe.columns.str.strip()

    for flag_col, comp_name in FLAG_COL_TO_COMP.items():
        life_col = COMP_LIFE_COL.get(comp_name)
        cat = COMP_CATEGORY.get(comp_name)

        if life_col and life_col in dataframe.columns and cat in thresholds_dict:
            thr = thresholds_dict[cat]
            dataframe[f"_flag_{comp_name}"] = (pd.to_numeric(dataframe[life_col], errors="coerce") >= thr).astype(int)
        else:
            dataframe[f"_flag_{comp_name}"] = 0

    return apply_dynamic_component_costs(dataframe)

# ─────────────────────────────────────────────────────────────────
#  ACTIVE DATASET
# ─────────────────────────────────────────────────────────────────

active_dts = list(dict.fromkeys(TOP19_DTS + [int(x) for x in extra_dts]))
thresholds_cache_key = tuple(sorted((str(k), round(float(v), 6)) for k, v in thresholds.items()))
df = build_active_dataset_cached(df_base, tuple(int(x) for x in active_dts), thresholds_cache_key)

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

@st.cache_data(show_spinner=False)
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
#  INTEGRATED PROJECTS — EMBEDDED SOURCE CODE
#  Added to integrate the Availability/Reliability Forecast app and
#  the Strut Forecast risk model inside this v25 dashboard without
#  requiring additional .py files at runtime.
# ─────────────────────────────────────────────────────────────────
AVAILABILITY_PROJECT_SOURCE = '# availability_reliability_embedded_values_historical_minimal_streamlit.py\n# Streamlit app for truck availability, reliability, and down-by-system analysis.\n# Runtime data is embedded in this file. No Excel workbook is required.\n# Scope: trucks 823 to 852, January 2024 to March 2025.\n# Historical embedded fields come only from Excel columns:\n# A = Equipo, H = Sistema, Y = Dur. Evento, E = Fecha Hora Inicial, F = Fecha Hora Final.\n\nfrom __future__ import annotations\n\nimport base64\nimport gzip\nfrom io import StringIO\n\nimport numpy as np\nimport pandas as pd\nimport plotly.express as px\nimport plotly.graph_objects as go\nimport streamlit as st\n\nMIN_TRUCK = 823\nMAX_TRUCK = 852\nSTART_PERIOD = pd.Timestamp("2024-01-01")\nEND_PERIOD = pd.Timestamp("2025-03-31")\n\nVALUES_CSV_GZ_B64 = """\n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\n"""\n\nHISTORICAL_SYSTEM_DOWNS_CSV_GZ_B64 = """\n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\n"""\n\n\n\nPONDERATE_KIT_CSV = r"""System,Ponderate weight Kit\nSEIS-SERVICIOS E INSPECCIONES,0%\nSES-SISTEMA ESTRUCTURAL,18%\nSPO-SISTEMA DE POTENCIA,10%\nSAC-SISTEMA DE ACCESORIOS,2%\nLLAN-SISTEMA DE LLANTAS,0\nND,0\nSPR-SISTEMA DE PROPULSION MECANICA,"1,5%"\nSPC-SISTEMA DE PROTECCION Y CONTROL CENTRAL,1%\nSPRE-SISTEMA DE PROPULSIÓN ELÉCTRICA,12%\nARC-SISTEMA DE ARRANQUE Y CARGA,1%\nSAUX-SISTEMA AUXILIAR ENFRIAMIENTO SIEMENS,28%\n-TEMPORY CODE,0\nSDIR-SISTEMA DE DIRECCIÓN,15%\nOPER-EVENTOS OPERACIONALES,0\nSHI-SISTEMA HIDRAULICO,10%\nSGEN-SISTEMA DE GENERACION,8%\nSLEV-SISTEMA DE LEVANTE,1%\nSFR-SISTEMA DE FRENOS,1%\nLUCE-SISTEMA DE LUCES,0%\nSCO-SISTEMA DE CONTROL,8%\nSLUC-SISTEMA CENTRALIZADO DE GRASA,0%\nPROT-SISTEMA DE PROTECCIONES,0%\nSEL-SISTEMA ELÉCTRICO,1%\nEL24-SISTEMA ELÉCTRICO DE 24 / 12 VOLTIOS,0%\nSAD-SISTEMA DE ADITAMENTOS,8%\n"""\n\ndef pct(x):\n    return "-" if pd.isna(x) else f"{x:.1%}"\n\n\ndef num(x, decimals=1):\n    return "-" if pd.isna(x) else f"{x:,.{decimals}f}"\n\n\n@st.cache_data(show_spinner=False)\ndef load_values_data() -> pd.DataFrame:\n    csv_text = gzip.decompress(base64.b64decode(VALUES_CSV_GZ_B64)).decode("utf-8")\n    df = pd.read_csv(StringIO(csv_text))\n    df["DT"] = pd.to_numeric(df["DT"], errors="coerce").astype("Int64")\n    df["Period"] = pd.to_datetime(df["Period"], errors="coerce")\n    df["YearMonth"] = df["Period"].dt.to_period("M").astype(str)\n    for col in df.columns:\n        if col not in ["DT", "Period", "YearMonth"]:\n            \n            converted = pd.to_numeric(df[col], errors="coerce")\n            # Keep the converted numeric series only when conversion is meaningful.\n            # This avoids pandas/Streamlit Cloud errors from errors="ignore" in newer pandas versions.\n            if converted.notna().sum() > 0:\n                df[col] = converted\n    return df[df["DT"].between(MIN_TRUCK, MAX_TRUCK) & df["Period"].between(START_PERIOD, END_PERIOD)].copy()\n\n\n@st.cache_data(show_spinner=False)\ndef load_historical_system_downs() -> pd.DataFrame:\n    csv_text = gzip.decompress(base64.b64decode(HISTORICAL_SYSTEM_DOWNS_CSV_GZ_B64)).decode("utf-8")\n    df = pd.read_csv(StringIO(csv_text))\n    df["DT"] = pd.to_numeric(df["DT"], errors="coerce").astype("Int64")\n    df["Event start"] = pd.to_datetime(df["Event start"], errors="coerce")\n    df["Event end"] = pd.to_datetime(df["Event end"], errors="coerce")\n    df["Period"] = pd.to_datetime(df["Period"], errors="coerce")\n    df["YearMonth"] = df["Period"].dt.to_period("M").astype(str)\n    df["System"] = df["System"].fillna("ND").astype(str).str.strip().replace({"": "ND", "nan": "ND"})\n    df["Event duration hours"] = pd.to_numeric(df["Event duration hours"], errors="coerce")\n    return df[df["DT"].between(MIN_TRUCK, MAX_TRUCK) & df["Period"].between(START_PERIOD, END_PERIOD)].copy()\n\n\n\n@st.cache_data(show_spinner=False)\ndef load_ponderate_kit_data() -> pd.DataFrame:\n    kit_df = pd.read_csv(StringIO(PONDERATE_KIT_CSV))\n    kit_df["System"] = kit_df["System"].astype(str).str.strip()\n\n    def parse_weight(value):\n        if pd.isna(value):\n            return 0.0\n        text = str(value).strip().replace("%", "").replace(",", ".")\n        if text == "":\n            return 0.0\n        try:\n            number = float(text)\n        except ValueError:\n            return 0.0\n        # Values in the source are percentages: 18 means 18%.\n        return number / 100 if number > 1 else number\n\n    kit_df["Kit improvement factor"] = kit_df["Ponderate weight Kit"].apply(parse_weight)\n    kit_df["Kit improvement factor"] = kit_df["Kit improvement factor"].clip(lower=0, upper=1)\n    return kit_df[["System", "Ponderate weight Kit", "Kit improvement factor"]]\n\n\ndef build_kit_adjusted_data(values_df: pd.DataFrame, historical_df: pd.DataFrame, kit_df: pd.DataFrame, apply_improvement: bool):\n    hist = historical_df.merge(kit_df, on="System", how="left")\n    hist["Kit improvement factor"] = hist["Kit improvement factor"].fillna(0.0)\n    hist["Ponderate weight Kit"] = hist["Ponderate weight Kit"].fillna("0%")\n\n    # Base values from each Historical event.\n    hist["Base event duration hours"] = hist["Event duration hours"]\n    hist["Base event count"] = 1.0\n\n    # The Ponderate weight Kit reduces both down hours and event count in the same proportion.\n    hist["Kit adjusted event duration hours"] = hist["Base event duration hours"] * (1 - hist["Kit improvement factor"])\n    hist["Kit reduced down hours"] = hist["Base event duration hours"] - hist["Kit adjusted event duration hours"]\n    hist["Kit adjusted event count"] = hist["Base event count"] * (1 - hist["Kit improvement factor"])\n    hist["Kit reduced event count"] = hist["Base event count"] - hist["Kit adjusted event count"]\n\n    monthly_reduction = (\n        hist.groupby(["DT", "Period"], dropna=False)\n        .agg(\n            Historical_base_down_hours=("Base event duration hours", "sum"),\n            Historical_adjusted_down_hours=("Kit adjusted event duration hours", "sum"),\n            Kit_reduced_down_hours=("Kit reduced down hours", "sum"),\n            Historical_base_events=("Base event count", "sum"),\n            Historical_adjusted_events=("Kit adjusted event count", "sum"),\n            Kit_reduced_events=("Kit reduced event count", "sum"),\n        )\n        .reset_index()\n    )\n\n    values = values_df.merge(monthly_reduction, on=["DT", "Period"], how="left")\n    for col in [\n        "Historical_base_down_hours", "Historical_adjusted_down_hours", "Kit_reduced_down_hours",\n        "Historical_base_events", "Historical_adjusted_events", "Kit_reduced_events",\n    ]:\n        values[col] = values[col].fillna(0.0)\n\n    values["Base Hours down (EVs)"] = values["Hours down (EVs)"]\n    values["Kit adjusted Hours down (EVs)"] = (values["Base Hours down (EVs)"] - values["Kit_reduced_down_hours"]).clip(lower=0)\n\n    values["Base Events MTBF"] = values["Number of events (According MTBF)"]\n    values["Kit adjusted Events MTBF"] = (values["Base Events MTBF"] - values["Kit_reduced_events"]).clip(lower=0)\n\n    if apply_improvement:\n        values["Hours down (EVs)"] = values["Kit adjusted Hours down (EVs)"]\n        values["Number of events (According MTBF)"] = values["Kit adjusted Events MTBF"]\n\n    values["Base Availability"] = np.where(\n        values["hours scheduled"] > 0,\n        1 - values["Base Hours down (EVs)"] / values["hours scheduled"],\n        np.nan,\n    )\n    values["Kit adjusted Availability"] = np.where(\n        values["hours scheduled"] > 0,\n        1 - values["Kit adjusted Hours down (EVs)"] / values["hours scheduled"],\n        np.nan,\n    )\n    values["Availability improvement points"] = values["Kit adjusted Availability"] - values["Base Availability"]\n\n    values["Base MTBF"] = np.where(values["Base Events MTBF"] > 0, values["hours operated"] / values["Base Events MTBF"], np.nan)\n    values["Kit adjusted MTBF"] = np.where(values["Kit adjusted Events MTBF"] > 0, values["hours operated"] / values["Kit adjusted Events MTBF"], np.nan)\n    values["MTBF improvement hours"] = values["Kit adjusted MTBF"] - values["Base MTBF"]\n\n    return values, hist\n\n\n@st.cache_data(show_spinner=False)\ndef fleet_monthly(values: pd.DataFrame) -> pd.DataFrame:\n    rows = []\n    for period, grp in values.groupby("Period"):\n        scheduled = grp["hours scheduled"].sum(min_count=1)\n        operated = grp["hours operated"].sum(min_count=1)\n        down = grp["Hours down (EVs)"].sum(min_count=1)\n        events = grp["Number of events (According MTBF)"].sum(min_count=1)\n        base_down = grp["Base Hours down (EVs)"].sum(min_count=1) if "Base Hours down (EVs)" in grp.columns else down\n        kit_down = grp["Kit adjusted Hours down (EVs)"].sum(min_count=1) if "Kit adjusted Hours down (EVs)" in grp.columns else down\n        base_events = grp["Base Events MTBF"].sum(min_count=1) if "Base Events MTBF" in grp.columns else events\n        kit_events = grp["Kit adjusted Events MTBF"].sum(min_count=1) if "Kit adjusted Events MTBF" in grp.columns else events\n\n        mtbf = operated / events if pd.notna(events) and events > 0 else np.nan\n        availability = 1 - down / scheduled if pd.notna(scheduled) and scheduled > 0 else np.nan\n        base_availability = 1 - base_down / scheduled if pd.notna(scheduled) and scheduled > 0 else np.nan\n        kit_availability = 1 - kit_down / scheduled if pd.notna(scheduled) and scheduled > 0 else np.nan\n        base_mtbf = operated / base_events if pd.notna(base_events) and base_events > 0 else np.nan\n        kit_mtbf = operated / kit_events if pd.notna(kit_events) and kit_events > 0 else np.nan\n\n        rows.append({\n            "Period": period,\n            "YearMonth": pd.Period(period, freq="M").strftime("%Y-%m"),\n            "Availability": availability,\n            "MTBF": mtbf,\n            "Base Availability": base_availability,\n            "Kit adjusted Availability": kit_availability,\n            "Base MTBF": base_mtbf,\n            "Kit adjusted MTBF": kit_mtbf,\n            "Hours scheduled": scheduled,\n            "Hours operated": operated,\n            "Hours down": down,\n            "Base hours down": base_down,\n            "Kit adjusted hours down": kit_down,\n            "Events MTBF": events,\n            "Base Events MTBF": base_events,\n            "Kit adjusted Events MTBF": kit_events,\n            "Active trucks": grp["DT"].nunique(),\n        })\n    return pd.DataFrame(rows).sort_values("Period")\n\n\n@st.cache_data(show_spinner=False)\ndef truck_summary(values: pd.DataFrame, mission_hours: float) -> pd.DataFrame:\n    rows = []\n    for dt, grp in values.groupby("DT"):\n        scheduled = grp["hours scheduled"].sum(min_count=1)\n        operated = grp["hours operated"].sum(min_count=1)\n        down = grp["Hours down (EVs)"].sum(min_count=1)\n        base_down = grp["Base Hours down (EVs)"].sum(min_count=1) if "Base Hours down (EVs)" in grp.columns else down\n        kit_down = grp["Kit adjusted Hours down (EVs)"].sum(min_count=1) if "Kit adjusted Hours down (EVs)" in grp.columns else down\n        kit_reduction = grp["Kit_reduced_down_hours"].sum(min_count=1) if "Kit_reduced_down_hours" in grp.columns else 0.0\n\n        events = grp["Number of events (According MTBF)"].sum(min_count=1)\n        base_events = grp["Base Events MTBF"].sum(min_count=1) if "Base Events MTBF" in grp.columns else events\n        kit_events = grp["Kit adjusted Events MTBF"].sum(min_count=1) if "Kit adjusted Events MTBF" in grp.columns else events\n        kit_event_reduction = grp["Kit_reduced_events"].sum(min_count=1) if "Kit_reduced_events" in grp.columns else 0.0\n\n        mtbf = operated / events if pd.notna(events) and events > 0 else np.nan\n        base_mtbf = operated / base_events if pd.notna(base_events) and base_events > 0 else np.nan\n        kit_adjusted_mtbf = operated / kit_events if pd.notna(kit_events) and kit_events > 0 else np.nan\n        availability = 1 - down / scheduled if pd.notna(scheduled) and scheduled > 0 else np.nan\n        base_availability = 1 - base_down / scheduled if pd.notna(scheduled) and scheduled > 0 else np.nan\n        kit_adjusted_availability = 1 - kit_down / scheduled if pd.notna(scheduled) and scheduled > 0 else np.nan\n        improvement_points = kit_adjusted_availability - base_availability if pd.notna(base_availability) and pd.notna(kit_adjusted_availability) else np.nan\n        reliability = np.exp(-mission_hours / mtbf) if pd.notna(mtbf) and mtbf > 0 else np.nan\n        base_reliability = np.exp(-mission_hours / base_mtbf) if pd.notna(base_mtbf) and base_mtbf > 0 else np.nan\n        kit_adjusted_reliability = np.exp(-mission_hours / kit_adjusted_mtbf) if pd.notna(kit_adjusted_mtbf) and kit_adjusted_mtbf > 0 else np.nan\n\n        rows.append({\n            "DT": int(dt),\n            "Availability": availability,\n            "Reliability": reliability,\n            "MTBF": mtbf,\n            "Base MTBF": base_mtbf,\n            "Kit adjusted MTBF": kit_adjusted_mtbf,\n            "MTBF improvement hours": kit_adjusted_mtbf - base_mtbf if pd.notna(base_mtbf) and pd.notna(kit_adjusted_mtbf) else np.nan,\n            "Hours down": down,\n            "Base hours down": base_down,\n            "Kit adjusted hours down": kit_down,\n            "Kit reduced down hours": kit_reduction,\n            "Events MTBF": events,\n            "Base Events MTBF": base_events,\n            "Kit adjusted Events MTBF": kit_events,\n            "Kit reduced events": kit_event_reduction,\n            "Hours scheduled": scheduled,\n            "Base Availability": base_availability,\n            "Kit adjusted Availability": kit_adjusted_availability,\n            "Availability improvement points": improvement_points,\n            "Base Reliability": base_reliability,\n            "Kit adjusted Reliability": kit_adjusted_reliability,\n        })\n    summary = pd.DataFrame(rows)\n    if summary.empty:\n        return pd.DataFrame(columns=[\n            "DT", "Availability", "Reliability", "MTBF", "Base MTBF", "Kit adjusted MTBF",\n            "MTBF improvement hours", "Hours down", "Base hours down", "Kit adjusted hours down",\n            "Kit reduced down hours", "Events MTBF", "Base Events MTBF", "Kit adjusted Events MTBF",\n            "Kit reduced events", "Hours scheduled", "Base Availability", "Kit adjusted Availability",\n            "Availability improvement points", "Base Reliability", "Kit adjusted Reliability"\n        ])\n    return summary.sort_values("Availability", ascending=False)\n\n\ndef _safe_div(numerator: float, denominator: float, default: float = np.nan) -> float:\n    return numerator / denominator if denominator and pd.notna(denominator) and denominator != 0 else default\n\n\ndef build_forecast_profiles(values: pd.DataFrame, hist: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:\n    """Build bottom-up truck/system profiles from the selected historical period."""\n    avg_scheduled = values.groupby("DT")["hours scheduled"].mean()\n    if avg_scheduled.empty:\n        avg_scheduled = pd.Series(dtype=float)\n\n    hist_valid = hist.dropna(subset=["DT", "System", "Base event duration hours"]).copy()\n    if hist_valid.empty:\n        return avg_scheduled, pd.DataFrame()\n\n    months_by_truck = values.groupby("DT")["Period"].nunique().replace(0, np.nan)\n    profiles = (\n        hist_valid.groupby(["DT", "System"], dropna=False)\n        .agg(\n            historical_events=("Base event count", "sum"),\n            historical_down_hours=("Base event duration hours", "sum"),\n            mean_duration=("Base event duration hours", "mean"),\n            std_duration=("Base event duration hours", "std"),\n            kit_factor=("Kit improvement factor", "max"),\n        )\n        .reset_index()\n    )\n    profiles["months_observed"] = profiles["DT"].map(months_by_truck).fillna(values["Period"].nunique())\n    profiles["events_per_month"] = profiles["historical_events"] / profiles["months_observed"].replace(0, np.nan)\n    profiles["mean_duration"] = profiles["mean_duration"].fillna(0).clip(lower=0.01)\n    # Gamma needs a positive standard deviation. Use a conservative CV when only one event exists.\n    fallback_std = profiles["mean_duration"].clip(lower=0.01)\n    profiles["std_duration"] = profiles["std_duration"].fillna(fallback_std).clip(lower=0.01)\n    profiles["kit_factor"] = profiles["kit_factor"].fillna(0.0).clip(lower=0, upper=1)\n    profiles["events_per_month"] = profiles["events_per_month"].fillna(0.0).clip(lower=0)\n    return avg_scheduled, profiles\n\n\n@st.cache_data(show_spinner=False)\ndef run_monte_carlo_forecast(\n    values_csv_key: str,\n    hist_csv_key: str,\n    kit_csv_key: str,\n    selected_trucks_tuple: tuple[int, ...],\n    selected_systems_tuple: tuple[str, ...],\n    apply_kit_impact: bool,\n    target_availability_2027: float,\n    annual_availability_decline: float,\n    annual_aging_factor: float,\n    simulations: int,\n    random_seed: int,\n) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:\n    """\n    Hybrid forecast: historical bottom-up profiles + Monte Carlo uncertainty + Kit impact.\n\n    Cache keys are CSV strings to make Streamlit cache deterministic with embedded data.\n    """\n    values_all = pd.read_csv(StringIO(values_csv_key), parse_dates=["Period"])\n    hist_all = pd.read_csv(StringIO(hist_csv_key), parse_dates=["Period", "Event start", "Event end"])\n    kit_all = pd.read_csv(StringIO(kit_csv_key))\n\n    values_sel = values_all[values_all["DT"].isin(selected_trucks_tuple)].copy()\n    hist_sel = hist_all[\n        hist_all["DT"].isin(selected_trucks_tuple)\n        & hist_all["System"].isin(selected_systems_tuple)\n    ].copy()\n    values_adj, hist_adj = build_kit_adjusted_data(values_sel, hist_sel, kit_all, False)\n    avg_scheduled, profiles = build_forecast_profiles(values_adj, hist_adj)\n\n    forecast_months = pd.date_range("2027-01-01", "2030-12-01", freq="MS")\n    rng = np.random.default_rng(random_seed)\n    n = int(simulations)\n    selected_trucks = list(selected_trucks_tuple)\n\n    if profiles.empty or len(selected_trucks) == 0:\n        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()\n\n    fleet_month = {\n        period: {\n            "base_down": np.zeros(n),\n            "base_events": np.zeros(n),\n            "kit_down": np.zeros(n),\n            "kit_events": np.zeros(n),\n            "scheduled": 0.0,\n        }\n        for period in forecast_months\n    }\n    truck_year = {}\n    fleet_default_sched = float(avg_scheduled.mean()) if not avg_scheduled.empty and pd.notna(avg_scheduled.mean()) else 720.0\n\n    for dt in selected_trucks:\n        dt_sched = float(avg_scheduled.get(dt, fleet_default_sched))\n        for period in forecast_months:\n            fleet_month[period]["scheduled"] += dt_sched\n            truck_year.setdefault((dt, period.year), {\n                "base_down": np.zeros(n),\n                "base_events": np.zeros(n),\n                "kit_down": np.zeros(n),\n                "kit_events": np.zeros(n),\n                "scheduled": 0.0,\n            })\n            truck_year[(dt, period.year)]["scheduled"] += dt_sched\n\n    for _, row in profiles.iterrows():\n        dt = int(row["DT"])\n        if dt not in selected_trucks:\n            continue\n        lam0 = float(row["events_per_month"])\n        if lam0 <= 0:\n            continue\n        mean_dur = float(row["mean_duration"])\n        std_dur = float(row["std_duration"])\n        kit_factor = float(row["kit_factor"])\n        shape_single = (mean_dur / std_dur) ** 2 if std_dur > 0 else 1.0\n        scale_single = (std_dur ** 2) / mean_dur if mean_dur > 0 else 1.0\n        shape_single = max(shape_single, 0.05)\n        scale_single = max(scale_single, 0.01)\n\n        for period in forecast_months:\n            # Simulate the historical baseline first. Aging is applied later,\n            # after the 2027 calibration factor has been fixed. This avoids\n            # hiding the effect of the sidebar aging parameter through repeated\n            # year-by-year recalibration.\n            lam = max(0.0, lam0)\n            events = rng.poisson(lam, size=n).astype(float)\n            total_duration = np.zeros(n)\n            positive = events > 0\n            if positive.any():\n                total_duration[positive] = rng.gamma(\n                    shape=shape_single * events[positive],\n                    scale=scale_single,\n                )\n            kit_multiplier = 1 - kit_factor\n            base_down = total_duration\n            base_events = events\n            kit_down = total_duration * kit_multiplier\n            kit_events = events * kit_multiplier\n\n            fm = fleet_month[period]\n            fm["base_down"] += base_down\n            fm["base_events"] += base_events\n            fm["kit_down"] += kit_down\n            fm["kit_events"] += kit_events\n            ty = truck_year[(dt, period.year)]\n            ty["base_down"] += base_down\n            ty["base_events"] += base_events\n            ty["kit_down"] += kit_down\n            ty["kit_events"] += kit_events\n\n    # Calibrate ONLY the 2027 BASE scenario to the selected starting target.\n    # The 2027 calibration factor is then kept fixed for the full horizon.\n    #\n    # Correct behavior after the strategy change:\n    #   - Base forecast comes from historical bottom-up + Monte Carlo.\n    #   - The base forecast is calibrated once in 2027, then left free to move.\n    #   - Annual aging is applied AFTER that fixed calibration.\n    #   - Annual availability reduction is applied as an explicit visible\n    #     penalty in down-hour equivalent units.\n    #   - Improved forecast reactivation is a second comparative line calculated\n    #     from the same calibrated/aged base simulation with the kit impact.\n    sched_2027 = sum(v["scheduled"] for p, v in fleet_month.items() if p.year == 2027)\n    raw_base_down_2027 = sum(\n        v["base_down"].mean()\n        for p, v in fleet_month.items() if p.year == 2027\n    )\n    target_down_2027 = sched_2027 * (1 - np.clip(target_availability_2027, 0.50, 0.98))\n    calibration_2027 = target_down_2027 / raw_base_down_2027 if raw_base_down_2027 > 0 else 1.0\n\n    monthly_rows = []\n    yearly_rows = []\n    for period, arrays in fleet_month.items():\n        year_index = period.year - 2027\n        aging = max(0.0, 1 + annual_aging_factor * year_index)\n        scheduled = arrays["scheduled"]\n\n        # Fixed 2027 calibration, then aging.\n        base_down = arrays["base_down"] * calibration_2027 * aging\n        kit_down = arrays["kit_down"] * calibration_2027 * aging\n        base_events = arrays["base_events"] * calibration_2027 * aging\n        kit_events = arrays["kit_events"] * calibration_2027 * aging\n\n        # Visible annual availability reduction penalty. This is expressed as\n        # additional equivalent down hours so the line visibly moves downward\n        # when the sidebar parameter increases. It is applied to both scenarios\n        # so the kit/improved line remains a fair comparison over the same aging path.\n        availability_penalty_points = max(0.0, annual_availability_decline * year_index)\n        penalty_down = scheduled * availability_penalty_points\n        if penalty_down > 0:\n            base_down = base_down + penalty_down\n            kit_down = kit_down + penalty_down\n\n        base_operated = np.clip(scheduled - base_down, 0, None)\n        kit_operated = np.clip(scheduled - kit_down, 0, None)\n        base_av = np.clip(1 - base_down / scheduled, 0, 1) if scheduled > 0 else np.full(n, np.nan)\n        kit_av = np.clip(1 - kit_down / scheduled, 0, 1) if scheduled > 0 else np.full(n, np.nan)\n        base_mtbf = np.divide(base_operated, base_events, out=np.full(n, np.nan), where=base_events > 0)\n        kit_mtbf = np.divide(kit_operated, kit_events, out=np.full(n, np.nan), where=kit_events > 0)\n        active_av = kit_av if apply_kit_impact else base_av\n        active_mtbf = kit_mtbf if apply_kit_impact else base_mtbf\n        target_path = np.clip(target_availability_2027 - annual_availability_decline * year_index, 0.50, 0.98)\n        monthly_rows.append({\n            "Period": period,\n            "Year": period.year,\n            "YearMonth": period.strftime("%Y-%m"),\n            "Scheduled hours": scheduled,\n            "Base Availability mean": np.nanmean(base_av),\n            "Base Availability P10": np.nanpercentile(base_av, 10),\n            "Base Availability P50": np.nanpercentile(base_av, 50),\n            "Base Availability P90": np.nanpercentile(base_av, 90),\n            "Kit Availability mean": np.nanmean(kit_av),\n            "Kit Availability P10": np.nanpercentile(kit_av, 10),\n            "Kit Availability P50": np.nanpercentile(kit_av, 50),\n            "Kit Availability P90": np.nanpercentile(kit_av, 90),\n            "Active Availability mean": np.nanmean(active_av),\n            "Active Availability P10": np.nanpercentile(active_av, 10),\n            "Active Availability P50": np.nanpercentile(active_av, 50),\n            "Active Availability P90": np.nanpercentile(active_av, 90),\n            "Base MTBF mean": np.nanmean(base_mtbf),\n            "Kit MTBF mean": np.nanmean(kit_mtbf),\n            "Active MTBF mean": np.nanmean(active_mtbf),\n            "Base down hours mean": np.nanmean(base_down),\n            "Kit down hours mean": np.nanmean(kit_down),\n            "Base events mean": np.nanmean(base_events),\n            "Kit events mean": np.nanmean(kit_events),\n            "Calibration factor": calibration_2027,\n            "Aging factor": aging,\n            "Availability penalty points": availability_penalty_points,\n            "Target availability": target_path,\n        })\n\n    monthly_df = pd.DataFrame(monthly_rows)\n\n    for year, grp in monthly_df.groupby("Year"):\n        sched = grp["Scheduled hours"].sum()\n        base_down = grp["Base down hours mean"].sum()\n        kit_down = grp["Kit down hours mean"].sum()\n        base_events = grp["Base events mean"].sum()\n        kit_events = grp["Kit events mean"].sum()\n        yearly_rows.append({\n            "Year": year,\n            "Target availability": grp["Target availability"].iloc[0],\n            "Base Availability": 1 - base_down / sched if sched > 0 else np.nan,\n            "Kit Availability": 1 - kit_down / sched if sched > 0 else np.nan,\n            "Active Availability": (1 - kit_down / sched) if apply_kit_impact and sched > 0 else (1 - base_down / sched if sched > 0 else np.nan),\n            "Base MTBF": _safe_div(sched - base_down, base_events),\n            "Kit MTBF": _safe_div(sched - kit_down, kit_events),\n            "Active MTBF": _safe_div(sched - (kit_down if apply_kit_impact else base_down), kit_events if apply_kit_impact else base_events),\n            "Base down hours": base_down,\n            "Kit down hours": kit_down,\n            "Down hours avoided by kit": base_down - kit_down,\n            "Base events": base_events,\n            "Kit events": kit_events,\n            "Events avoided by kit": base_events - kit_events,\n            "Calibration factor": grp["Calibration factor"].mean(),\n        })\n    yearly_df = pd.DataFrame(yearly_rows)\n\n    truck_rows = []\n    for (dt, year), arrays in truck_year.items():\n        year_index = year - 2027\n        aging = max(0.0, 1 + annual_aging_factor * year_index)\n        scheduled = arrays["scheduled"]\n        base_down = arrays["base_down"] * calibration_2027 * aging\n        kit_down = arrays["kit_down"] * calibration_2027 * aging\n        base_events = arrays["base_events"] * calibration_2027 * aging\n        kit_events = arrays["kit_events"] * calibration_2027 * aging\n        availability_penalty_points = max(0.0, annual_availability_decline * year_index)\n        penalty_down = scheduled * availability_penalty_points\n        if penalty_down > 0:\n            base_down = base_down + penalty_down\n            kit_down = kit_down + penalty_down\n        active_down = kit_down if apply_kit_impact else base_down\n        active_events = kit_events if apply_kit_impact else base_events\n        active_operated = np.clip(scheduled - active_down, 0, None)\n        active_av = np.clip(1 - active_down / scheduled, 0, 1) if scheduled > 0 else np.full(n, np.nan)\n        active_mtbf = np.divide(active_operated, active_events, out=np.full(n, np.nan), where=active_events > 0)\n        truck_rows.append({\n            "DT": dt,\n            "Year": year,\n            "Availability mean": np.nanmean(active_av),\n            "Availability P10": np.nanpercentile(active_av, 10),\n            "Availability P50": np.nanpercentile(active_av, 50),\n            "Availability P90": np.nanpercentile(active_av, 90),\n            "MTBF mean": np.nanmean(active_mtbf),\n            "Down hours mean": np.nanmean(active_down),\n            "Events mean": np.nanmean(active_events),\n            "Scheduled hours": scheduled,\n        })\n    truck_df = pd.DataFrame(truck_rows).sort_values(["Year", "Availability mean"])\n    return monthly_df, yearly_df, truck_df\n\n\nvalues_df = load_values_data()\nhistorical_df = load_historical_system_downs()\nkit_df = load_ponderate_kit_data()\n\nst.markdown("<h2 style=\'font-size:24px; margin-bottom:0;\'>Truck Availability, Reliability & System Down Analysis</h2>", unsafe_allow_html=True)\nst.caption("Embedded data only | Values sheet + Historical columns A, E, F, H, Y | Trucks 823–852 | Jan 2024–Mar 2025")\n\nwith st.sidebar:\n    st.header("Report controls")\n    truck_options = sorted([int(x) for x in values_df["DT"].dropna().unique()])\n    selected_trucks = st.multiselect("Trucks", truck_options, default=truck_options)\n    min_month = values_df["Period"].min().to_pydatetime()\n    max_month = values_df["Period"].max().to_pydatetime()\n    selected_range = st.slider("Period", min_value=min_month, max_value=max_month, value=(min_month, max_month), format="YYYY-MM")\n    mission_hours = st.number_input("Mission time for reliability R(t) [hours]", min_value=1.0, value=50.0, step=10.0, help="This value recalculates Reliability R(t)=exp(-t/MTBF). Lower values make the effect easier to visualize when MTBF is low.")\n    availability_target = st.slider("Availability target", 0.50, 1.00, 0.85, 0.01)\n    top_n_systems = st.slider("Top systems to show", 5, 25, 10, 1)\n    system_options = sorted(historical_df["System"].dropna().unique().tolist())\n    selected_systems = st.multiselect("Systems", system_options, default=system_options)\n    kits_reactivation_improvement = st.toggle("Kit reactivation impact", value=False, help="Apply the Ponderate weight Kit factor to reduce down hours and event counts by system, then show the comparative Improved forecast reactivation line.")\n    with st.expander("Forecast 2027-2030 controls", expanded=False):\n        forecast_target_2027 = st.slider("Target availability 2027", 0.75, 0.95, 0.85, 0.005, format="%.3f")\n        forecast_annual_decline = st.slider("Annual availability reduction", 0.000, 0.030, 0.005, 0.001, format="%.3f")\n        forecast_aging_factor = st.slider("Annual aging factor on events/down", 0.000, 0.150, 0.040, 0.005, format="%.3f")\n        forecast_simulations = st.select_slider("Monte Carlo simulations", options=[100, 250, 500, 1000], value=500)\n        forecast_seed = st.number_input("Random seed", min_value=1, max_value=999999, value=2027, step=1)\n\nstart_sel = pd.Timestamp(selected_range[0]).replace(day=1)\nend_sel = pd.Timestamp(selected_range[1]) + pd.offsets.MonthEnd(0)\nbase_filtered_values = values_df[values_df["DT"].isin(selected_trucks) & values_df["Period"].between(start_sel, end_sel)].copy()\nbase_filtered_hist = historical_df[historical_df["DT"].isin(selected_trucks) & historical_df["Period"].between(start_sel, end_sel) & historical_df["System"].isin(selected_systems)].copy()\n\nfiltered_values, filtered_hist = build_kit_adjusted_data(\n    base_filtered_values,\n    base_filtered_hist,\n    kit_df,\n    kits_reactivation_improvement,\n)\n\nfleet = fleet_monthly(filtered_values)\ntrucks = truck_summary(filtered_values, mission_hours)\n\nvalues_cache_key = values_df.to_csv(index=False)\nhistorical_cache_key = historical_df.to_csv(index=False)\nkit_cache_key = kit_df.to_csv(index=False)\nforecast_monthly, forecast_yearly, forecast_truck = run_monte_carlo_forecast(\n    values_cache_key,\n    historical_cache_key,\n    kit_cache_key,\n    tuple(selected_trucks),\n    tuple(selected_systems),\n    kits_reactivation_improvement,\n    forecast_target_2027,\n    forecast_annual_decline,\n    forecast_aging_factor,\n    forecast_simulations,\n    int(forecast_seed),\n)\n\nbase_fleet_availability = 1 - filtered_values["Base Hours down (EVs)"].sum() / filtered_values["hours scheduled"].sum()\nkit_fleet_availability = 1 - filtered_values["Kit adjusted Hours down (EVs)"].sum() / filtered_values["hours scheduled"].sum()\nactive_fleet_availability = 1 - filtered_values["Hours down (EVs)"].sum() / filtered_values["hours scheduled"].sum()\nkit_down_reduction = filtered_hist["Kit reduced down hours"].sum() if not filtered_hist.empty else 0.0\n\nk1, k2, k3, k4, k5 = st.columns(5)\nk1.metric("Fleet availability", pct(active_fleet_availability), delta=pct(kit_fleet_availability - base_fleet_availability) if kits_reactivation_improvement else None)\nk2.metric("Fleet MTBF", f"{num(fleet[\'MTBF\'].mean())} h")\nk3.metric("System-down events", f"{len(filtered_hist):,}")\nk4.metric("Base system-down duration", f"{num(filtered_hist[\'Base event duration hours\'].sum())} h")\nk5.metric("Kit down reduction", f"{num(kit_down_reduction)} h")\n\ntab1, tab2, tab3, tab4, tab5 = st.tabs(["Fleet trend", "Truck ranking", "Down by system", "Forecast 2027-2030", "Embedded data quality"])\n\nwith tab1:\n    st.subheader("Fleet availability and MTBF trend")\n\n    fig_av = px.line(\n        fleet,\n        x="Period",\n        y="Base Availability",\n        markers=True,\n        hover_data=["YearMonth", "Base hours down", "Base Events MTBF", "Active trucks"],\n        title="Fleet availability: base vs Improved forecast reactivation",\n        labels={"Base Availability": "Base availability"},\n    )\n    fig_av.update_traces(name="Base availability", showlegend=True)\n    if kits_reactivation_improvement:\n        fig_av.add_trace(\n            go.Scatter(\n                x=fleet["Period"],\n                y=fleet["Kit adjusted Availability"],\n                mode="lines+markers",\n                name="Improved forecast reactivation",\n                line=dict(color="green", dash="dot"),\n                customdata=np.stack([\n                    fleet["YearMonth"],\n                    fleet["Kit adjusted hours down"],\n                    fleet["Kit adjusted Events MTBF"],\n                    fleet["Active trucks"],\n                ], axis=-1),\n                hovertemplate=(\n                    "Period=%{customdata[0]}<br>"\n                    "Kit adjusted availability=%{y:.1%}<br>"\n                    "Kit adjusted hours down=%{customdata[1]:,.1f}<br>"\n                    "Kit adjusted events=%{customdata[2]:,.1f}<br>"\n                    "Active trucks=%{customdata[3]}<extra></extra>"\n                ),\n            )\n        )\n    fig_av.add_hline(y=availability_target, line_dash="dash", annotation_text="Availability target")\n    fig_av.update_yaxes(tickformat=".0%")\n    st.plotly_chart(fig_av, use_container_width=True)\n\n    fig_mtbf = px.line(\n        fleet,\n        x="Period",\n        y="Base MTBF",\n        markers=True,\n        hover_data=["YearMonth", "Base Events MTBF", "Hours operated"],\n        title="Fleet MTBF: base vs Improved forecast reactivation",\n        labels={"Base MTBF": "Base MTBF"},\n    )\n    fig_mtbf.update_traces(name="Base MTBF", showlegend=True)\n    if kits_reactivation_improvement:\n        fig_mtbf.add_trace(\n            go.Scatter(\n                x=fleet["Period"],\n                y=fleet["Kit adjusted MTBF"],\n                mode="lines+markers",\n                name="Improved forecast reactivation",\n                line=dict(color="green", dash="dot"),\n                customdata=np.stack([\n                    fleet["YearMonth"],\n                    fleet["Kit adjusted Events MTBF"],\n                    fleet["Hours operated"],\n                ], axis=-1),\n                hovertemplate=(\n                    "Period=%{customdata[0]}<br>"\n                    "Kit adjusted MTBF=%{y:,.1f} h<br>"\n                    "Kit adjusted events=%{customdata[1]:,.1f}<br>"\n                    "Hours operated=%{customdata[2]:,.1f}<extra></extra>"\n                ),\n            )\n        )\n    st.plotly_chart(fig_mtbf, use_container_width=True)\n\nwith tab2:\n    st.subheader("Truck ranking")\n    st.caption(f"Reliability R(t) is recalculated with the selected mission time: {mission_hours:,.0f} hours. This slicer does not change Availability or MTBF; it changes only the Reliability R(t) metric.")\n    rel_cols = st.columns(3)\n    rel_cols[0].metric("Mission time", f"{mission_hours:,.0f} h")\n    rel_cols[1].metric("Fleet avg Reliability R(t)", pct(trucks["Reliability"].mean()))\n    rel_cols[2].metric("Lowest truck Reliability", pct(trucks["Reliability"].min()))\n\n    fig_rank = px.bar(trucks.sort_values("Availability"), x="DT", y="Availability", text="Availability", hover_data=["Reliability", "MTBF", "Hours down", "Events MTBF", "Base Availability", "Kit adjusted Availability", "Availability improvement points"], title="Availability ranking by truck")\n    fig_rank.update_traces(texttemplate="%{text:.1%}", textposition="outside")\n    fig_rank.update_yaxes(tickformat=".0%")\n    fig_rank.update_xaxes(type="category")\n    st.plotly_chart(fig_rank, use_container_width=True)\n\n    fig_rel = px.bar(trucks.sort_values("Reliability"), x="DT", y="Reliability", text="Reliability", hover_data=["MTBF", "Availability", "Hours down", "Events MTBF"], title=f"Reliability R(t) ranking by truck - mission time {mission_hours:,.0f} h")\n    fig_rel.update_traces(texttemplate="%{text:.1%}", textposition="outside", marker_color="#2E7D32")\n    fig_rel.update_yaxes(tickformat=".0%", title="Reliability R(t)")\n    fig_rel.update_xaxes(type="category")\n    st.plotly_chart(fig_rel, use_container_width=True)\n\n    st.dataframe(\n        trucks.style.format({\n            "Availability": "{:.1%}",\n            "Reliability": "{:.1%}",\n            "MTBF": "{:,.1f}",\n            "Hours down": "{:,.1f}",\n            "Base hours down": "{:,.1f}",\n            "Kit adjusted hours down": "{:,.1f}",\n            "Kit reduced down hours": "{:,.1f}",\n            "Base Availability": "{:.1%}",\n            "Kit adjusted Availability": "{:.1%}",\n            "Availability improvement points": "{:.2%}",\n        }),\n        use_container_width=True,\n    )\n\nwith tab3:\n    st.subheader("Analysis of down by system")\n    st.caption("This section is built from Historical and applies the Ponderate weight Kit by system when the sidebar option **Improved forecast reactivation** is enabled.")\n    if filtered_hist.empty:\n        st.warning("No historical system-down records for the selected filters.")\n    else:\n        system_summary = (\n            filtered_hist.groupby("System", dropna=False)\n            .agg(\n                Events=("System", "size"),\n                Duration_hours=("Base event duration hours", "sum"),\n                Kit_adjusted_duration_hours=("Kit adjusted event duration hours", "sum"),\n                Kit_reduced_down_hours=("Kit reduced down hours", "sum"),\n                Base_events=("Base event count", "sum"),\n                Kit_adjusted_events=("Kit adjusted event count", "sum"),\n                Kit_reduced_events=("Kit reduced event count", "sum"),\n                Kit_improvement_factor=("Kit improvement factor", "max"),\n                Avg_duration=("Base event duration hours", "mean"),\n                Trucks_affected=("DT", "nunique"),\n                First_event=("Event start", "min"),\n                Last_event=("Event end", "max"),\n            )\n            .reset_index()\n            .sort_values("Duration_hours", ascending=False)\n        )\n        total_duration = system_summary["Duration_hours"].sum()\n        total_adjusted_duration = system_summary["Kit_adjusted_duration_hours"].sum()\n        system_summary["Duration share"] = np.where(total_duration > 0, system_summary["Duration_hours"] / total_duration, np.nan)\n        system_summary["Pareto cumulative"] = system_summary["Duration share"].cumsum()\n        system_summary["Reduction share"] = np.where(system_summary["Duration_hours"] > 0, system_summary["Kit_reduced_down_hours"] / system_summary["Duration_hours"], 0)\n        system_summary["Event reduction share"] = np.where(system_summary["Base_events"] > 0, system_summary["Kit_reduced_events"] / system_summary["Base_events"], 0)\n        top_systems = system_summary.head(top_n_systems)\n\n        c1, c2, c3, c4 = st.columns(4)\n        c1.metric("Events", f"{len(filtered_hist):,}")\n        c2.metric("Base duration", f"{num(total_duration)} h")\n        c3.metric("Kit adjusted duration", f"{num(total_adjusted_duration)} h")\n        c4.metric("Down reduction", f"{num(total_duration - total_adjusted_duration)} h", delta=pct((total_duration - total_adjusted_duration) / total_duration) if total_duration > 0 else None)\n\n        fig_system = px.bar(\n            top_systems,\n            x="System",\n            y=["Duration_hours", "Kit_adjusted_duration_hours"],\n            barmode="group",\n            hover_data=["Events", "Avg_duration", "Trucks_affected", "Kit_improvement_factor", "Kit_reduced_down_hours", "First_event", "Last_event"],\n            title="Base vs kit-adjusted down duration by system [hours]",\n        )\n        fig_system.update_layout(xaxis_tickangle=-35, yaxis_title="Duration [h]", legend_title_text="")\n        st.plotly_chart(fig_system, use_container_width=True)\n\n        monthly_system = (\n            filtered_hist.groupby(["Period", "YearMonth", "System"], dropna=False)\n            .agg(\n                Duration_hours=("Base event duration hours", "sum"),\n                Kit_adjusted_duration_hours=("Kit adjusted event duration hours", "sum"),\n                Kit_reduced_down_hours=("Kit reduced down hours", "sum"),\n                Events=("System", "size"),\n                Kit_adjusted_events=("Kit adjusted event count", "sum"),\n                Kit_reduced_events=("Kit reduced event count", "sum"),\n            )\n            .reset_index()\n        )\n        monthly_top = monthly_system[monthly_system["System"].isin(top_systems["System"])]\n        monthly_top["Displayed down hours"] = np.where(\n            kits_reactivation_improvement,\n            monthly_top["Kit_adjusted_duration_hours"],\n            monthly_top["Duration_hours"],\n        )\n        fig_monthly = px.line(monthly_top, x="Period", y="Displayed down hours", color="System", markers=True, hover_data=["YearMonth", "Events", "Duration_hours", "Kit_adjusted_duration_hours", "Kit_reduced_down_hours"], title="Monthly down duration by system")\n        st.plotly_chart(fig_monthly, use_container_width=True)\n\n        truck_system = filtered_hist.pivot_table(\n            index="DT",\n            columns="System",\n            values="Kit adjusted event duration hours" if kits_reactivation_improvement else "Base event duration hours",\n            aggfunc="sum",\n            fill_value=0,\n        )\n        truck_system = truck_system[[c for c in top_systems["System"] if c in truck_system.columns]]\n        fig_heat = px.imshow(truck_system, aspect="auto", text_auto=".1f", labels=dict(x="System", y="Truck", color="Duration [h]"), title="Duration matrix by truck and system")\n        st.plotly_chart(fig_heat, use_container_width=True)\n\n        truck_impact = (\n            filtered_values.groupby("DT", dropna=False)\n            .agg(\n                Base_hours_down=("Base Hours down (EVs)", "sum"),\n                Kit_adjusted_hours_down=("Kit adjusted Hours down (EVs)", "sum"),\n                Kit_reduced_down_hours=("Kit_reduced_down_hours", "sum"),\n                Base_events_MTBF=("Base Events MTBF", "sum"),\n                Kit_adjusted_events_MTBF=("Kit adjusted Events MTBF", "sum"),\n                Kit_reduced_events=("Kit_reduced_events", "sum"),\n                Scheduled_hours=("hours scheduled", "sum"),\n                Operated_hours=("hours operated", "sum"),\n                Base_availability=("Base Availability", "mean"),\n                Kit_adjusted_availability=("Kit adjusted Availability", "mean"),\n            )\n            .reset_index()\n        )\n        truck_impact["Availability improvement points"] = truck_impact["Kit_adjusted_availability"] - truck_impact["Base_availability"]\n        truck_impact["Base_MTBF"] = np.where(truck_impact["Base_events_MTBF"] > 0, truck_impact["Operated_hours"] / truck_impact["Base_events_MTBF"], np.nan)\n        truck_impact["Kit_adjusted_MTBF"] = np.where(truck_impact["Kit_adjusted_events_MTBF"] > 0, truck_impact["Operated_hours"] / truck_impact["Kit_adjusted_events_MTBF"], np.nan)\n        truck_impact["MTBF improvement hours"] = truck_impact["Kit_adjusted_MTBF"] - truck_impact["Base_MTBF"]\n\n        st.markdown("**Truck availability impact from Improved forecast reactivation**")\n        fig_truck_impact = px.bar(\n            truck_impact.sort_values("Availability improvement points", ascending=False),\n            x="DT",\n            y="Availability improvement points",\n            text="Availability improvement points",\n            hover_data=["Base_hours_down", "Kit_adjusted_hours_down", "Kit_reduced_down_hours", "Base_availability", "Kit_adjusted_availability"],\n            title="Availability improvement by truck",\n        )\n        fig_truck_impact.update_traces(texttemplate="%{text:.2%}", textposition="outside")\n        fig_truck_impact.update_yaxes(tickformat=".1%")\n        fig_truck_impact.update_xaxes(type="category")\n        st.plotly_chart(fig_truck_impact, use_container_width=True)\n\n        st.markdown("**System summary**")\n        st.dataframe(\n            system_summary.style.format(\n                {\n                    "Duration_hours": "{:,.1f}",\n                    "Kit_adjusted_duration_hours": "{:,.1f}",\n                    "Kit_reduced_down_hours": "{:,.1f}",\n                    "Kit_improvement_factor": "{:.1%}",\n                    "Avg_duration": "{:,.1f}",\n                    "Duration share": "{:.1%}",\n                    "Pareto cumulative": "{:.1%}",\n                    "Reduction share": "{:.1%}",\n                }\n            ),\n            use_container_width=True,\n        )\n\n        st.markdown("**Truck impact summary**")\n        st.dataframe(\n            truck_impact.style.format(\n                {\n                    "Base_hours_down": "{:,.1f}",\n                    "Kit_adjusted_hours_down": "{:,.1f}",\n                    "Kit_reduced_down_hours": "{:,.1f}",\n                    "Base_availability": "{:.1%}",\n                    "Kit_adjusted_availability": "{:.1%}",\n                    "Availability improvement points": "{:.2%}",\n                }\n            ),\n            use_container_width=True,\n        )\n\n        with st.expander("Embedded Historical event detail"):\n            detail_cols = [\n                "DT", "System", "Event start", "Event end", "Base event duration hours",\n                "Ponderate weight Kit", "Kit adjusted event duration hours", "Kit reduced down hours",\n                "Kit adjusted event count", "Kit reduced event count"\n            ]\n            st.dataframe(filtered_hist[detail_cols], use_container_width=True)\n\n\n\nwith tab4:\n    st.subheader("Forecast 2027-2030: Hybrid bottom-up + Monte Carlo model")\n    st.caption(\n        "The forecast uses historical truck/system event intensity, simulated event counts and durations, "\n        "annual degradation, annual availability reduction, and the Improved forecast reactivation factor. "\n        "The base scenario is calibrated only in 2027; that calibration is fixed across the horizon. "\n        "The comparative improved line is displayed as Improved forecast reactivation."\n    )\n    if forecast_monthly.empty:\n        st.warning("No forecast could be generated for the current truck/system selection.")\n    else:\n        f1, f2, f3, f4 = st.columns(4)\n        f1.markdown("""<div style="background:#FFFFFF; border:1px solid #E6E6E6; border-radius:10px; padding:0.65rem 0.75rem;"><div style="font-size:0.78rem; color:#666666; margin-bottom:0.15rem;">Forecast horizon</div><div style="font-size:24px; font-weight:700; color:#1A1A1A; line-height:1.1;">Jan 2027-Dec 2030</div></div>""", unsafe_allow_html=True)\n        f2.metric("Simulations", f"{forecast_simulations:,}")\n        f3.metric("2027 target", pct(forecast_target_2027))\n        f4.metric("Annual reduction", pct(forecast_annual_decline))\n\n        st.markdown("**Fleet availability forecast**")\n        fig_f_av = go.Figure()\n        fig_f_av.add_trace(go.Scatter(\n            x=forecast_monthly["Period"],\n            y=forecast_monthly["Base Availability mean"],\n            mode="lines",\n            name="Base forecast",\n            hovertemplate="%{x|%Y-%m}<br>Base availability=%{y:.1%}<extra></extra>",\n        ))\n        fig_f_av.add_trace(go.Scatter(\n            x=forecast_monthly["Period"],\n            y=forecast_monthly["Base Availability P90"],\n            mode="lines",\n            line=dict(width=0),\n            showlegend=False,\n            hoverinfo="skip",\n        ))\n        fig_f_av.add_trace(go.Scatter(\n            x=forecast_monthly["Period"],\n            y=forecast_monthly["Base Availability P10"],\n            mode="lines",\n            fill="tonexty",\n            line=dict(width=0),\n            name="Base P10-P90 band",\n            hoverinfo="skip",\n            opacity=0.25,\n        ))\n        if kits_reactivation_improvement:\n            fig_f_av.add_trace(go.Scatter(\n                x=forecast_monthly["Period"],\n                y=forecast_monthly["Kit Availability mean"],\n                mode="lines+markers",\n                name="Improved forecast reactivation",\n                line=dict(color="green", dash="dot"),\n                hovertemplate="%{x|%Y-%m}<br>Improved availability=%{y:.1%}<extra></extra>",\n            ))\n        fig_f_av.add_trace(go.Scatter(\n            x=forecast_monthly["Period"],\n            y=forecast_monthly["Target availability"],\n            mode="lines",\n            name="Target path",\n            line=dict(dash="dash"),\n            hovertemplate="%{x|%Y-%m}<br>Target=%{y:.1%}<extra></extra>",\n        ))\n        fig_f_av.update_layout(title="Monthly fleet availability forecast with uncertainty band", yaxis_tickformat=".0%", yaxis_title="Availability")\n        st.plotly_chart(fig_f_av, use_container_width=True)\n\n        st.markdown("**Fleet MTBF forecast**")\n        fig_f_mtbf = go.Figure()\n        fig_f_mtbf.add_trace(go.Scatter(\n            x=forecast_monthly["Period"],\n            y=forecast_monthly["Base MTBF mean"],\n            mode="lines+markers",\n            name="Base MTBF forecast",\n            hovertemplate="%{x|%Y-%m}<br>Base MTBF=%{y:,.1f} h<extra></extra>",\n        ))\n        if kits_reactivation_improvement:\n            fig_f_mtbf.add_trace(go.Scatter(\n                x=forecast_monthly["Period"],\n                y=forecast_monthly["Kit MTBF mean"],\n                mode="lines+markers",\n                name="Improved forecast reactivation",\n                line=dict(color="green", dash="dot"),\n                hovertemplate="%{x|%Y-%m}<br>Improved MTBF=%{y:,.1f} h<extra></extra>",\n            ))\n        fig_f_mtbf.update_layout(title="Monthly fleet MTBF forecast", yaxis_title="MTBF [hours/event]")\n        st.plotly_chart(fig_f_mtbf, use_container_width=True)\n\n        st.markdown("**Yearly forecast summary**")\n        st.dataframe(\n            forecast_yearly.style.format({\n                "Target availability": "{:.1%}",\n                "Base Availability": "{:.1%}",\n                "Kit Availability": "{:.1%}",\n                "Active Availability": "{:.1%}",\n                "Base MTBF": "{:,.1f}",\n                "Kit MTBF": "{:,.1f}",\n                "Active MTBF": "{:,.1f}",\n                "Base down hours": "{:,.1f}",\n                "Kit down hours": "{:,.1f}",\n                "Down hours avoided by kit": "{:,.1f}",\n                "Base events": "{:,.1f}",\n                "Kit events": "{:,.1f}",\n                "Events avoided by kit": "{:,.1f}",\n                "Calibration factor": "{:.3f}",\n            }),\n            use_container_width=True,\n        )\n\n        st.markdown("**Truck risk ranking by forecast availability**")\n        selected_forecast_year = st.selectbox("Forecast year for truck ranking", [2027, 2028, 2029, 2030], index=3)\n        truck_year_view = forecast_truck[forecast_truck["Year"] == selected_forecast_year].copy()\n        fig_truck_forecast = px.bar(\n            truck_year_view.sort_values("Availability mean"),\n            x="DT",\n            y="Availability mean",\n            text="Availability mean",\n            hover_data=["Availability P10", "Availability P50", "Availability P90", "MTBF mean", "Down hours mean", "Events mean"],\n            title=f"Truck forecast availability ranking - {selected_forecast_year}",\n        )\n        fig_truck_forecast.update_traces(texttemplate="%{text:.1%}", textposition="outside")\n        fig_truck_forecast.update_yaxes(tickformat=".0%")\n        fig_truck_forecast.update_xaxes(type="category")\n        st.plotly_chart(fig_truck_forecast, use_container_width=True)\n        st.dataframe(\n            truck_year_view.style.format({\n                "Availability mean": "{:.1%}",\n                "Availability P10": "{:.1%}",\n                "Availability P50": "{:.1%}",\n                "Availability P90": "{:.1%}",\n                "MTBF mean": "{:,.1f}",\n                "Down hours mean": "{:,.1f}",\n                "Events mean": "{:,.1f}",\n                "Scheduled hours": "{:,.1f}",\n            }),\n            use_container_width=True,\n        )\n\n        with st.expander("Model calculation notes"):\n            st.markdown(\n                """\n                **Events** are simulated with a Poisson distribution using the historical monthly event rate by truck and system.\n\n                **Event duration** is simulated with a Gamma distribution fitted from the historical mean and standard deviation of each truck/system duration.\n\n                **Improved forecast reactivation** reduces both simulated events and simulated down hours by the Ponderate weight Kit factor for each system.\n\n                **Annual degradation** is applied after the fixed 2027 calibration and increases simulated events/down hours year by year.\n\n                **Annual availability reduction** is applied as an explicit visible penalty after calibration and aging, so increasing it lowers the forecast line year by year.\n\n                **Improved forecast reactivation** is the second comparative line calculated from the same calibrated and aged base simulation after applying the system-level kit impact.\n                """\n            )\n\n\nwith tab5:\n    st.subheader("Embedded data quality")\n    expected_trucks = set(range(MIN_TRUCK, MAX_TRUCK + 1))\n    values_trucks = set(int(x) for x in values_df["DT"].dropna().unique())\n    hist_trucks = set(int(x) for x in historical_df["DT"].dropna().unique())\n    st.write("Historical embedded columns:", ["DT", "Event start", "Event end", "System", "Event duration hours", "Period", "YearMonth"])\n    st.write("Missing trucks in Values:", sorted(expected_trucks - values_trucks) or "None")\n    st.write("Missing trucks in Historical:", sorted(expected_trucks - hist_trucks) or "None")\n    st.write(f"Values rows: {len(values_df):,}")\n    st.write(f"Historical rows embedded from A/E/F/H/Y: {len(historical_df):,}")\n    st.write("Null count in embedded Historical fields:")\n    st.dataframe(historical_df[["DT", "Event start", "Event end", "System", "Event duration hours"]].isna().sum().rename("Nulls").to_frame(), use_container_width=True)\n'

STRUT_PROJECT_SOURCE = 'import streamlit as st\nimport pandas as pd\nimport plotly.express as px\nimport plotly.graph_objects as go\nfrom io import StringIO\n\n\n# ============================================================\n# 1. EMBEDDED DATA\n# ============================================================\n# Source columns in the embedded CSV:\n# Truck; Strut location; Type of strut; Strut accumulated hours; Strut current hours\n#\n# Correct interpretation:\n# - Strut accumulated hours = accumulated life hours of the physical strut.\n# - Strut current hours = current operating cycle hours for that strut position.\n#\n# Forecast logic:\n# - Operating change-out interval uses Current Cycle Hours.\n# - Maximum total life rule uses Strut Accumulated Life Hours.\n# - New struts required are counted only when a strut reaches maximum total life.\n\nEMBEDDED_STRUT_CSV = """Truck;Strut location;Type of strut;Strut accumulated hours;Strut current hours\n823;Right rear strut;Standard;0;1194,7\n823;Left reat strut;Standard;0;1194,7\n823;Left front strut;Standard;20823,53;1954,2\n824;Right front strut;Standard;76178,88;3401,24\n824;Left reat strut;Standard;27505,09;2414,7\n824;Right rear strut;Standard;19801,05;2396,9\n825;Right front strut;Standard;79424,13;2608,9\n825;Left front strut;Standard;44419,69;2608,9\n825;Right rear strut;Standard;12639,56;9972,06\n825;Left reat strut;Standard;0;1178,1\n826;Right front strut;Standard;39009,64;7558,66\n826;Left front strut;Standard;21534,76;2582,8\n826;Right rear strut;Standard;6452,53;347,5\n826;Left reat strut;Standard;0;1185\n827;Left front strut;Standard;80898,4;1889,6\n827;Right rear strut;Heavy Duty;0;353\n827;Left reat strut;Heavy Duty;0;353\n827;Right front strut;Standard;0;847,7\n828;Left front strut;Standard;80544,67;5198,84\n828;Right front strut;Standard;46058,11;7298,94\n828;Right rear strut;Heavy Duty;0;15304,32\n828;Left reat strut;Heavy Duty;0;15304,32\n829;Right front strut;Standard;38962,98;9376,77\n829;Right rear strut;Heavy Duty;16291,17;901,7\n829;Left reat strut;Heavy Duty;0;453,1\n829;Left front strut;Standard;0;453,1\n830;Left front strut;Standard;70134,59;5217,97\n830;Right front strut;Standard;30365,97;267,9\n830;Left reat strut;Heavy Duty;0;300,1\n830;Right rear strut;Heavy Duty;0;300,1\n831;Left front strut;Standard;92427,77;309\n831;Right front strut;Standard;20505,06;309\n831;Right rear strut;Standard;2603,5;4211,03\n831;Left reat strut;Standard;0;990,7\n832;Right front strut;Standard;86110,17;3384,16\n832;Right rear strut;Standard;16308,99;909,1\n832;Left reat strut;Standard;3507,5;909,1\n832;Left front strut;Standard;0;3803,36\n833;Right front strut;Standard;71054,16;5902,77\n833;Left reat strut;Standard;14430,94;2572,1\n833;Right rear strut;Standard;13440;50,7\n833;Left front strut;Standard;0;1315,7\n834;Left front strut;Standard;36116,17;3019,1\n834;Right front strut;Standard;12077,37;6854,95\n834;Right rear strut;Standard;52306,92;2083,1\n834;Left reat strut;Standard;15135,21;2525,2\n835;Right front strut;Standard;74646,12;4327,5\n835;Left front strut;Standard;41655,97;2684,1\n835;Right rear strut;Standard;22419,38;4768,3\n835;Left reat strut;Standard;0;1430,8\n836;Left front strut;Standard;69963,13;9932,11\n836;Right front strut;Standard;23982,76;14849,55\n836;Left reat strut;Standard;31441,34;997,8\n836;Right rear strut;Standard;16705,97;997,8\n837;Right front strut;Standard;74319,11;6144,06\n837;Left reat strut;Standard;60957,38;3253,5\n837;Right rear strut;Standard;8500,22;5127,86\n837;Left front strut;Standard;0;1167,6\n838;Right front strut;Standard;18203,06;3836,7\n838;Left front strut;Standard;6560,91;2069,5\n838;Right rear strut;Heavy Duty;0;348,2\n838;Left reat strut;Heavy Duty;0;348,2\n839;Left front strut;Standard;42249,26;9711,72\n839;Left reat strut;Standard;122,3;7432\n839;Right rear strut;Standard;0;1560,4\n840;Right front strut;Standard;79977,13;14390,54\n840;Left front strut;Standard;20878,53;9844,54\n840;Right rear strut;Standard;39083,96;2335\n840;Left reat strut;Standard;3645,4;2736,4\n841;Left front strut;Standard;76704,77;4233,59\n841;Right front strut;Standard;43743,15;591,4\n841;Right rear strut;Standard;58790,57;2503,2\n841;Left reat strut;Standard;5137,3;2503,2\n842;Right rear strut;Heavy Duty;16351,84;1086\n842;Left reat strut;Heavy Duty;0;9128,35\n842;Left front strut;Standard;;447,9\n842;Right front strut;Standard;;447,9\n843;Right front strut;Standard;38762,86;611,6\n843;Left front strut;Standard;21955,41;611,6\n843;Right rear strut;Standard;57679,67;122,5\n843;Left reat strut;Standard;0;1585\n844;Right front strut;Standard;79462,5;5561,55\n844;Left front strut;Standard;43274,15;10270,45\n844;Left reat strut;Standard;30792,31;5771\n844;Right rear strut;Standard;16621,27;2846,8\n845;Right front strut;Standard;16690,84;9490,35\n845;Right rear strut;Heavy Duty;14315,27;6323,05\n845;Left reat strut;Heavy Duty;10514,73;6323,05\n845;Left front strut;Standard;0;404,4\n846;Right front strut;Standard;78622,13;14562,47\n846;Left front strut;Standard;52302,54;7824,38\n846;Right rear strut;Standard;78264,55;8828,08\n846;Left reat strut;Standard;8182,98;9292\n847;Left front strut;Standard;88590,68;1580,9\n847;Right front strut;Standard;64161,48;9365,22\n847;Left reat strut;Standard;77278,72;1476,2\n847;Right rear strut;Standard;41638,15;1949,9\n848;Right front strut;Standard;15931,73;7102,69\n848;Left front strut;Standard;13355,22;8463,69\n848;Left reat strut;Standard;70979,48;3178,4\n848;Right rear strut;Standard;13377,87;4132,99\n849;Right front strut;Standard;0;7846,12\n849;Left front strut;Standard;0;1061,3\n849;Right rear strut;Standard;22248,57;2555,5\n849;Left reat strut;Standard;0;1545\n850;Right front strut;Standard;24947,32;4382,98\n850;Left front strut;Standard;15316,69;5936,58\n850;Left reat strut;Standard;20714,93;4490,88\n850;Right rear strut;Standard;0;431,3\n851;Right front strut;Standard;74024,61;592,2\n851;Left front strut;Standard;31720,55;115,2\n851;Left reat strut;Standard;4364,65;592,2\n851;Right rear strut;Standard;0;7044,73\n852;Right front strut;Standard;23151,73;819,5\n852;Left front strut;Standard;0;3828,21\n852;Left reat strut;Standard;87784,73;3560,91\n852;Right rear strut;Standard;73080,36;3559,41"""\n\nPOSITION_MAP = {\n    "Right rear strut": "Rear Right",\n    "Left reat strut": "Rear Left",\n    "Left rear strut": "Rear Left",\n    "Right front strut": "Front Right",\n    "Left front strut": "Front Left",\n}\n\nTYPE_MAP = {\n    "Standard": "Std",\n    "Heavy Duty": "HD",\n}\n\n\n@st.cache_data(show_spinner=False)\ndef load_embedded_data() -> pd.DataFrame:\n    df = pd.read_csv(StringIO(EMBEDDED_STRUT_CSV), sep=";", decimal=",")\n\n    df = df.rename(\n        columns={\n            "Truck": "Truck ID",\n            "Strut location": "Strut Position",\n            "Type of strut": "Strut Type",\n            "Strut accumulated hours": "Strut Accumulated Life Hours",\n            "Strut current hours": "Current Cycle Hours",\n        }\n    )\n\n    df["Truck ID"] = df["Truck ID"].astype(str)\n    df["Strut Position"] = df["Strut Position"].map(POSITION_MAP).fillna(df["Strut Position"])\n    df["Strut Type"] = df["Strut Type"].map(TYPE_MAP).fillna(df["Strut Type"])\n\n    numeric_columns = ["Strut Accumulated Life Hours", "Current Cycle Hours"]\n    for col in numeric_columns:\n        # Keep missing values as NaN. Do not convert missing data to zero,\n        # because missing accumulated life or cycle hours should be excluded\n        # from the forecast and cost analysis.\n        df[col] = pd.to_numeric(df[col], errors="coerce")\n\n    return df[\n        [\n            "Truck ID",\n            "Strut Position",\n            "Strut Type",\n            "Strut Accumulated Life Hours",\n            "Current Cycle Hours",\n        ]\n    ]\n\n\n# ============================================================\n# 2. VALIDATION\n# ============================================================\n\ndef validate_input_data(df: pd.DataFrame) -> list:\n    required_columns = [\n        "Truck ID",\n        "Strut Position",\n        "Strut Type",\n        "Strut Accumulated Life Hours",\n        "Current Cycle Hours",\n    ]\n\n    errors = []\n\n    missing_columns = [col for col in required_columns if col not in df.columns]\n    if missing_columns:\n        errors.append(f"Missing required columns: {missing_columns}")\n\n    valid_positions = {"Front Left", "Front Right", "Rear Left", "Rear Right"}\n    valid_types = {"Std", "HD"}\n\n    if "Strut Position" in df.columns:\n        invalid_positions = set(df["Strut Position"]) - valid_positions\n        if invalid_positions:\n            errors.append(f"Invalid strut positions found: {invalid_positions}")\n\n    if "Strut Type" in df.columns:\n        invalid_types = set(df["Strut Type"]) - valid_types\n        if invalid_types:\n            errors.append(f"Invalid strut types found: {invalid_types}")\n\n    for col in ["Strut Accumulated Life Hours", "Current Cycle Hours"]:\n        if col in df.columns:\n            valid_numeric_values = df[col].dropna()\n            if (valid_numeric_values < 0).any():\n                errors.append(f"Column \'{col}\' contains negative values.")\n\n    return errors\n\n\n# ============================================================\n# 3. FORECAST ENGINE\n# ============================================================\n\n@st.cache_data(show_spinner=False)\ndef simulate_strut_forecast(\n    input_df: pd.DataFrame,\n    start_year: int,\n    end_year: int,\n    annual_operating_hours: float,\n    std_interval: float,\n    hd_interval: float,\n    max_life_hours: float,\n):\n    records = []\n    working_df = input_df.copy()\n\n    for year in range(start_year, end_year + 1):\n        for idx, row in working_df.iterrows():\n            truck_id = row["Truck ID"]\n            position = row["Strut Position"]\n            strut_type = row["Strut Type"]\n            interval = std_interval if strut_type == "Std" else hd_interval\n\n            current_cycle_hours = float(row["Current Cycle Hours"])\n            accumulated_life_hours = float(row["Strut Accumulated Life Hours"])\n            remaining_annual_hours = float(annual_operating_hours)\n            event_number = 0\n\n            while remaining_annual_hours > 0:\n                hours_to_interval = interval - current_cycle_hours\n                hours_to_end_of_life = max_life_hours - accumulated_life_hours\n\n                # Immediate event at the beginning of the year if already beyond a limit.\n                if hours_to_interval <= 0 or hours_to_end_of_life <= 0:\n                    event_number += 1\n                    is_eol = hours_to_end_of_life <= 0\n                    event_reason = "End of Life" if is_eol else "Operating Interval"\n\n                    records.append(\n                        {\n                            "Year": year,\n                            "Truck ID": truck_id,\n                            "Strut Position": position,\n                            "Strut Type": strut_type,\n                            "Event Number in Year": event_number,\n                            "Event Reason": event_reason,\n                            "Hours Into Year at Event": annual_operating_hours - remaining_annual_hours,\n                            "Cycle Hours at Event": current_cycle_hours,\n                            "Strut Life Hours at Event": accumulated_life_hours,\n                            "Operating Change-Out Required": 0 if is_eol else 1,\n                            "End-of-Life Replacement": 1 if is_eol else 0,\n                            "Total Replacement Events": 1,\n                            "New Strut Required": 1 if is_eol else 0,\n                        }\n                    )\n\n                    if is_eol:\n                        # New physical strut installed: both counters restart.\n                        current_cycle_hours = 0\n                        accumulated_life_hours = 0\n                    else:\n                        # Operating change-out: operating cycle restarts, physical life remains.\n                        current_cycle_hours = 0\n\n                    continue\n\n                next_event_hours = min(hours_to_interval, hours_to_end_of_life)\n\n                if remaining_annual_hours >= next_event_hours:\n                    event_number += 1\n                    current_cycle_hours += next_event_hours\n                    accumulated_life_hours += next_event_hours\n                    remaining_annual_hours -= next_event_hours\n\n                    is_eol = hours_to_end_of_life <= hours_to_interval\n                    event_reason = "End of Life" if is_eol else "Operating Interval"\n\n                    records.append(\n                        {\n                            "Year": year,\n                            "Truck ID": truck_id,\n                            "Strut Position": position,\n                            "Strut Type": strut_type,\n                            "Event Number in Year": event_number,\n                            "Event Reason": event_reason,\n                            "Hours Into Year at Event": annual_operating_hours - remaining_annual_hours,\n                            "Cycle Hours at Event": current_cycle_hours,\n                            "Strut Life Hours at Event": accumulated_life_hours,\n                            "Operating Change-Out Required": 0 if is_eol else 1,\n                            "End-of-Life Replacement": 1 if is_eol else 0,\n                            "Total Replacement Events": 1,\n                            "New Strut Required": 1 if is_eol else 0,\n                        }\n                    )\n\n                    if is_eol:\n                        current_cycle_hours = 0\n                        accumulated_life_hours = 0\n                    else:\n                        current_cycle_hours = 0\n\n                else:\n                    current_cycle_hours += remaining_annual_hours\n                    accumulated_life_hours += remaining_annual_hours\n                    remaining_annual_hours = 0\n\n            working_df.at[idx, "Current Cycle Hours"] = current_cycle_hours\n            working_df.at[idx, "Strut Accumulated Life Hours"] = accumulated_life_hours\n\n    schedule_df = pd.DataFrame(records)\n    all_years = pd.DataFrame({"Year": list(range(start_year, end_year + 1))})\n\n    if schedule_df.empty:\n        yearly_summary = all_years.copy()\n        for col in [\n            "Std Operating Change-Outs",\n            "HD Operating Change-Outs",\n            "Std End-of-Life Replacements",\n            "HD End-of-Life Replacements",\n            "Total Operating Change-Outs",\n            "Total End-of-Life Replacements",\n            "Total Replacement Events",\n            "New Std Struts Required",\n            "New HD Struts Required",\n            "Total New Struts Required",\n        ]:\n            yearly_summary[col] = 0\n        truck_summary = pd.DataFrame()\n        position_summary = pd.DataFrame()\n        return yearly_summary, schedule_df, truck_summary, position_summary, working_df\n\n    yearly_operating = (\n        schedule_df\n        .pivot_table(index="Year", columns="Strut Type", values="Operating Change-Out Required", aggfunc="sum", fill_value=0)\n        .reset_index()\n        .rename(columns={"Std": "Std Operating Change-Outs", "HD": "HD Operating Change-Outs"})\n    )\n\n    yearly_eol = (\n        schedule_df\n        .pivot_table(index="Year", columns="Strut Type", values="End-of-Life Replacement", aggfunc="sum", fill_value=0)\n        .reset_index()\n        .rename(columns={"Std": "Std End-of-Life Replacements", "HD": "HD End-of-Life Replacements"})\n    )\n\n    yearly_new = (\n        schedule_df\n        .pivot_table(index="Year", columns="Strut Type", values="New Strut Required", aggfunc="sum", fill_value=0)\n        .reset_index()\n        .rename(columns={"Std": "New Std Struts Required", "HD": "New HD Struts Required"})\n    )\n\n    yearly_summary = (\n        all_years\n        .merge(yearly_operating, on="Year", how="left")\n        .merge(yearly_eol, on="Year", how="left")\n        .merge(yearly_new, on="Year", how="left")\n        .fillna(0)\n    )\n\n    for col in [\n        "Std Operating Change-Outs",\n        "HD Operating Change-Outs",\n        "Std End-of-Life Replacements",\n        "HD End-of-Life Replacements",\n        "New Std Struts Required",\n        "New HD Struts Required",\n    ]:\n        if col not in yearly_summary.columns:\n            yearly_summary[col] = 0\n        yearly_summary[col] = yearly_summary[col].astype(int)\n\n    yearly_summary["Total Operating Change-Outs"] = (\n        yearly_summary["Std Operating Change-Outs"] + yearly_summary["HD Operating Change-Outs"]\n    )\n    yearly_summary["Total End-of-Life Replacements"] = (\n        yearly_summary["Std End-of-Life Replacements"] + yearly_summary["HD End-of-Life Replacements"]\n    )\n    yearly_summary["Total Replacement Events"] = (\n        yearly_summary["Total Operating Change-Outs"] + yearly_summary["Total End-of-Life Replacements"]\n    )\n    yearly_summary["Total New Struts Required"] = (\n        yearly_summary["New Std Struts Required"] + yearly_summary["New HD Struts Required"]\n    )\n\n    truck_summary = (\n        schedule_df\n        .groupby(["Truck ID", "Strut Type"], as_index=False)\n        .agg(\n            **{\n                "Total Replacement Events": ("Total Replacement Events", "sum"),\n                "Operating Change-Outs": ("Operating Change-Out Required", "sum"),\n                "End-of-Life Replacements": ("End-of-Life Replacement", "sum"),\n                "New Struts Required": ("New Strut Required", "sum"),\n            }\n        )\n        .sort_values(["Truck ID", "Strut Type"])\n    )\n\n    position_summary = (\n        schedule_df\n        .groupby(["Strut Position", "Strut Type"], as_index=False)\n        .agg(\n            **{\n                "Total Replacement Events": ("Total Replacement Events", "sum"),\n                "Operating Change-Outs": ("Operating Change-Out Required", "sum"),\n                "End-of-Life Replacements": ("End-of-Life Replacement", "sum"),\n                "New Struts Required": ("New Strut Required", "sum"),\n            }\n        )\n        .sort_values(["Strut Position", "Strut Type"])\n    )\n\n    return yearly_summary, schedule_df, truck_summary, position_summary, working_df\n\n\n# ============================================================\n# 4. COST ANALYSIS ENGINE\n# ============================================================\n\ndef calculate_annuity_factor(discount_rate: float, periods: int) -> float:\n    if periods <= 0:\n        return 0.0\n    if discount_rate == 0:\n        return 1 / periods\n    return (discount_rate * (1 + discount_rate) ** periods) / (((1 + discount_rate) ** periods) - 1)\n\n\n@st.cache_data(show_spinner=False)\ndef build_cost_analysis(\n    yearly_summary: pd.DataFrame,\n    selected_truck_count: int,\n    annual_operating_hours: float,\n    start_year: int,\n    end_year: int,\n    discount_rate: float,\n    ppi_adjustments: dict,\n    current_std_new_cost: float,\n    current_hd_new_cost: float,\n    current_repair_cost: float,\n    oem_std_new_cost: float,\n    oem_hd_new_cost: float,\n    oem_repair_cost: float,\n):\n    horizon_years = end_year - start_year + 1\n    annuity_factor = calculate_annuity_factor(discount_rate, horizon_years)\n    annual_fleet_hours = selected_truck_count * annual_operating_hours\n\n    scenario_inputs = [\n        {\n            "Scenario": "Current Cost Strategy",\n            "Std New Strut Unit Cost": current_std_new_cost,\n            "HD New Strut Unit Cost": current_hd_new_cost,\n            "Repair Unit Cost": current_repair_cost,\n        },\n        {\n            "Scenario": "OEM Reman Strategy",\n            "Std New Strut Unit Cost": oem_std_new_cost,\n            "HD New Strut Unit Cost": oem_hd_new_cost,\n            "Repair Unit Cost": oem_repair_cost,\n        },\n    ]\n\n    cost_records = []\n\n    for scenario in scenario_inputs:\n        for _, row in yearly_summary.iterrows():\n            year = int(row["Year"])\n            year_index = year - start_year + 1\n            discount_factor = 1 / ((1 + discount_rate) ** year_index) if discount_rate > 0 else 1.0\n            yearly_annuity_factor = calculate_annuity_factor(discount_rate, year_index)\n\n            ppi_adjustment = ppi_adjustments.get(year, 0.0)\n            ppi_multiplier = 1 + ppi_adjustment\n\n            std_new_qty = int(row["New Std Struts Required"])\n            hd_new_qty = int(row["New HD Struts Required"])\n            operating_change_out_qty = int(row["Total Operating Change-Outs"])\n\n            adjusted_std_new_unit_cost = scenario["Std New Strut Unit Cost"] * ppi_multiplier\n            adjusted_hd_new_unit_cost = scenario["HD New Strut Unit Cost"] * ppi_multiplier\n            adjusted_repair_unit_cost = scenario["Repair Unit Cost"] * ppi_multiplier\n\n            std_new_cost_total = std_new_qty * adjusted_std_new_unit_cost\n            hd_new_cost_total = hd_new_qty * adjusted_hd_new_unit_cost\n            repair_cost_total = operating_change_out_qty * adjusted_repair_unit_cost\n            total_year_cost = std_new_cost_total + hd_new_cost_total + repair_cost_total\n            present_value_cost = total_year_cost * discount_factor\n            annuity_cost_per_year = present_value_cost * yearly_annuity_factor\n            yearly_hourly_rate = total_year_cost / annual_fleet_hours if annual_fleet_hours > 0 else 0\n            annuity_hourly_rate = annuity_cost_per_year / annual_fleet_hours if annual_fleet_hours > 0 else 0\n\n            cost_records.append(\n                {\n                    "Scenario": scenario["Scenario"],\n                    "Year": year,\n                    "Std New Struts Required": std_new_qty,\n                    "HD New Struts Required": hd_new_qty,\n                    "Operating Change-Outs": operating_change_out_qty,\n                    "PPI Adjustment %": ppi_adjustment * 100,\n                    "PPI Multiplier": ppi_multiplier,\n                    "Base Std New Strut Unit Cost": scenario["Std New Strut Unit Cost"],\n                    "Base HD New Strut Unit Cost": scenario["HD New Strut Unit Cost"],\n                    "Base Repair Unit Cost": scenario["Repair Unit Cost"],\n                    "Adjusted Std New Strut Unit Cost": adjusted_std_new_unit_cost,\n                    "Adjusted HD New Strut Unit Cost": adjusted_hd_new_unit_cost,\n                    "Adjusted Repair Unit Cost": adjusted_repair_unit_cost,\n                    "Std New Strut Cost": std_new_cost_total,\n                    "HD New Strut Cost": hd_new_cost_total,\n                    "Repair Cost": repair_cost_total,\n                    "Total Year Cost": total_year_cost,\n                    "Discount Factor": discount_factor,\n                    "Present Value Cost": present_value_cost,\n                    "Yearly Annuity Factor": yearly_annuity_factor,\n                    "Annuity Cost per Year": annuity_cost_per_year,\n                    "Annual Fleet Hours": annual_fleet_hours,\n                    "Yearly Hourly Rate": yearly_hourly_rate,\n                    "Annuity Hourly Rate": annuity_hourly_rate,\n                }\n            )\n\n    cost_detail_df = pd.DataFrame(cost_records)\n    cost_detail_df = cost_detail_df.sort_values(["Scenario", "Year"]).reset_index(drop=True)\n    cost_detail_df["Accumulated Budget"] = cost_detail_df.groupby("Scenario")["Total Year Cost"].cumsum()\n    cost_detail_df["Accumulated Present Value Cost"] = cost_detail_df.groupby("Scenario")["Present Value Cost"].cumsum()\n\n    scenario_summary = (\n        cost_detail_df\n        .groupby("Scenario", as_index=False)\n        .agg(\n            **{\n                "Total Nominal Cost": ("Total Year Cost", "sum"),\n                "Present Value Cost": ("Present Value Cost", "sum"),\n                "Total Annuity Cost by Year": ("Annuity Cost per Year", "sum"),\n                "Total Repair Cost": ("Repair Cost", "sum"),\n                "Total New Std Strut Cost": ("Std New Strut Cost", "sum"),\n                "Total New HD Strut Cost": ("HD New Strut Cost", "sum"),\n                "Total Operating Change-Outs": ("Operating Change-Outs", "sum"),\n                "Total New Std Struts": ("Std New Struts Required", "sum"),\n                "Total New HD Struts": ("HD New Struts Required", "sum"),\n            }\n        )\n    )\n\n    scenario_summary["Annuity Factor"] = annuity_factor\n    scenario_summary["Equivalent Annual Cost"] = scenario_summary["Present Value Cost"] * annuity_factor\n    scenario_summary["Annual Fleet Hours"] = annual_fleet_hours\n    scenario_summary["Scenario Hourly Rate"] = scenario_summary["Equivalent Annual Cost"] / annual_fleet_hours if annual_fleet_hours > 0 else 0\n    scenario_summary["Estimated Monthly Cost"] = scenario_summary["Equivalent Annual Cost"] / 12\n\n    monthly_invoice_df = scenario_summary[\n        [\n            "Scenario",\n            "Equivalent Annual Cost",\n            "Estimated Monthly Cost",\n            "Scenario Hourly Rate",\n        ]\n    ].copy()\n\n    current_monthly = monthly_invoice_df.loc[\n        monthly_invoice_df["Scenario"] == "Current Cost Strategy",\n        "Estimated Monthly Cost",\n    ].sum()\n    oem_monthly = monthly_invoice_df.loc[\n        monthly_invoice_df["Scenario"] == "OEM Reman Strategy",\n        "Estimated Monthly Cost",\n    ].sum()\n\n    monthly_invoice_comparison = pd.DataFrame(\n        [\n            {\n                "OEM Reman Estimated Monthly Invoice": oem_monthly,\n                "Current Strategy Estimated Monthly Cost": current_monthly,\n                "Monthly Difference OEM vs Current": oem_monthly - current_monthly,\n                "Monthly Difference %": ((oem_monthly - current_monthly) / current_monthly * 100) if current_monthly != 0 else 0,\n            }\n        ]\n    )\n\n    return cost_detail_df, scenario_summary, monthly_invoice_df, monthly_invoice_comparison\n\n\n# ============================================================\n# 5. STREAMLIT APP\n# ============================================================\n\nst.markdown("<h2 style=\'font-size:24px; margin-bottom:0;\'>Truck Strut Replacement Forecast</h2>", unsafe_allow_html=True)\nst.caption("Forecast of operating change-outs and end-of-life new-strut demand")\n\nst.sidebar.header("Forecast Assumptions")\n\nstart_year = st.sidebar.number_input("Start Year", min_value=2026, max_value=2050, value=2027, step=1)\nend_year = st.sidebar.number_input("End Year", min_value=int(start_year), max_value=2050, value=2030, step=1)\nannual_operating_hours = st.sidebar.number_input("Annual Truck Operating Hours", min_value=0, value=6000, step=100)\nstd_interval = st.sidebar.number_input("Std Strut Operating Change-Out Interval", min_value=1, value=4500, step=100)\nhd_interval = st.sidebar.number_input("HD Strut Operating Change-Out Interval", min_value=1, value=7500, step=100)\nmax_life_hours = st.sidebar.number_input("Strut Maximum Total Life Hours", min_value=1, value=45000, step=1000)\n\nst.sidebar.header("Cost Analysis Assumptions")\nst.sidebar.caption("Enter unit costs for each strategy. New strut costs are applied only to end-of-life replacements. Repair costs are applied to operating change-outs.")\n\nst.sidebar.subheader("Current Cost Strategy")\ncurrent_std_new_cost = st.sidebar.number_input(\n    "Current Strategy - Std New Strut Cost",\n    min_value=0.0,\n    value=0.0,\n    step=1000.0,\n)\ncurrent_hd_new_cost = st.sidebar.number_input(\n    "Current Strategy - HD New Strut Cost",\n    min_value=0.0,\n    value=0.0,\n    step=1000.0,\n)\ncurrent_repair_cost = st.sidebar.number_input(\n    "Current Strategy - Repair Cost per Operating Change-Out",\n    min_value=0.0,\n    value=0.0,\n    step=1000.0,\n)\n\nst.sidebar.subheader("OEM Reman Strategy")\noem_std_new_cost = st.sidebar.number_input(\n    "OEM Reman Strategy - Std New Strut Cost",\n    min_value=0.0,\n    value=0.0,\n    step=1000.0,\n)\noem_hd_new_cost = st.sidebar.number_input(\n    "OEM Reman Strategy - HD New Strut Cost",\n    min_value=0.0,\n    value=0.0,\n    step=1000.0,\n)\noem_repair_cost = st.sidebar.number_input(\n    "OEM Reman Strategy - Repair Cost per Operating Change-Out",\n    min_value=0.0,\n    value=0.0,\n    step=1000.0,\n)\n\ndiscount_rate = st.sidebar.number_input(\n    "Annual Discount Rate for Annuity Calculation (%)",\n    min_value=0.0,\n    max_value=100.0,\n    value=10.0,\n    step=0.5,\n) / 100\n\nst.sidebar.subheader("Yearly PPI Adjustment")\nst.sidebar.caption(\n    "Enter the price adjustment percentage for each forecast year. "\n    "The adjustment impacts only that specific year. Example: 5 means costs in that year increase by 5%."\n)\n\nppi_adjustments = {}\nfor ppi_year in range(int(start_year), int(end_year) + 1):\n    ppi_adjustments[ppi_year] = st.sidebar.number_input(\n        f"PPI Adjustment {ppi_year} (%)",\n        min_value=-100.0,\n        max_value=300.0,\n        value=0.0,\n        step=0.5,\n    ) / 100\n\nfull_input_df = load_embedded_data()\n\navailable_trucks = sorted(\n    full_input_df["Truck ID"].unique(),\n    key=lambda x: int(x) if str(x).isdigit() else str(x),\n)\n\nst.sidebar.header("Truck Selection")\nst.sidebar.caption(\n    "Select the trucks that must be included in the forecast and analysis. "\n    "Trucks not selected are excluded from all calculations."\n)\n\nselected_trucks = st.sidebar.multiselect(\n    "Trucks included in forecast",\n    options=available_trucks,\n    default=available_trucks,\n)\n\nif not selected_trucks:\n    st.error("Select at least one truck to run the analysis and forecast.")\n    st.stop()\n\nselected_input_df = full_input_df[full_input_df["Truck ID"].isin(selected_trucks)].copy()\n\nrequired_forecast_columns = ["Strut Accumulated Life Hours", "Current Cycle Hours"]\nmissing_required_info_df = selected_input_df[\n    selected_input_df[required_forecast_columns].isna().any(axis=1)\n].copy()\n\n# Only rows with complete required hour data enter the forecast, charts, KPIs,\n# and cost analysis. Missing data is not assumed as zero.\ninput_df = selected_input_df.dropna(subset=required_forecast_columns).copy()\n\nst.subheader("Selected Embedded Input Data")\nst.caption("Only the selected trucks with complete required hour data are included in all tables, charts, KPIs, forecast calculations, and cost analysis.")\nst.dataframe(input_df, use_container_width=True)\n\nif not missing_required_info_df.empty:\n    st.warning(\n        "Some selected strut rows have missing required information and were excluded from the forecast and cost analysis. "\n        "Missing values are not assumed as zero."\n    )\n    st.dataframe(missing_required_info_df, use_container_width=True)\n\nif input_df.empty:\n    st.error("No complete strut records are available for the selected trucks. Please select trucks with complete strut hour data.")\n    st.stop()\n\ntotal_available_trucks = full_input_df["Truck ID"].nunique()\ntotal_selected_trucks = selected_input_df["Truck ID"].nunique()\ntotal_included_trucks = input_df["Truck ID"].nunique()\ntotal_trucks = total_included_trucks\ntotal_struts = len(input_df)\ntotal_excluded_struts = len(missing_required_info_df)\n\ncol_a, col_b, col_c, col_d, col_e = st.columns(5)\ncol_a.metric("Available Trucks", total_available_trucks)\ncol_b.metric("Selected Trucks", total_selected_trucks)\ncol_c.metric("Included Trucks", total_included_trucks)\ncol_d.metric("Included Struts", total_struts)\ncol_e.metric("Excluded Struts", total_excluded_struts)\n\nerrors = validate_input_data(input_df)\nif errors:\n    st.error("Input data validation failed.")\n    for error in errors:\n        st.warning(error)\n    st.stop()\n\nposition_check = input_df.groupby("Truck ID")["Strut Position"].nunique().reset_index(name="Number of Included Positions")\nincomplete_trucks = position_check[position_check["Number of Included Positions"] < 4]\nif not incomplete_trucks.empty:\n    st.warning("Some trucks have fewer than 4 struts. The forecast will only simulate the listed struts.")\n    st.dataframe(incomplete_trucks, use_container_width=True)\n\nalready_over_life = input_df[input_df["Strut Accumulated Life Hours"] >= max_life_hours]\nif not already_over_life.empty:\n    st.warning("Some struts already exceed the maximum total life assumption and will be counted as immediate end-of-life replacements in the first forecast year.")\n    st.dataframe(already_over_life, use_container_width=True)\n\nwith st.expander("View strut position completeness by truck"):\n    position_count_table = (\n        input_df\n        .pivot_table(index="Truck ID", columns="Strut Position", values="Current Cycle Hours", aggfunc="count", fill_value=0)\n        .reset_index()\n    )\n    st.dataframe(position_count_table, use_container_width=True)\n\n\n# ============================================================\n# 5. STRUT AGE POPULATION CHARTS\n# ============================================================\n\nst.subheader("Strut Age Population by Total Accumulated Life Hours")\n\nage_bin_size = st.number_input(\n    "Hour bin size for strut age population",\n    min_value=500,\n    max_value=10000,\n    value=2500,\n    step=500,\n)\n\nage_population_df = input_df.copy()\nmax_strut_hours = age_population_df["Strut Accumulated Life Hours"].max()\nupper_bin_limit = int(((max_strut_hours // age_bin_size) + 1) * age_bin_size)\nbins = list(range(0, upper_bin_limit + age_bin_size, age_bin_size))\nlabels = [f"{bins[i]:,} - {bins[i + 1]:,}" for i in range(len(bins) - 1)]\n\nage_population_df["Life Hour Bucket"] = pd.cut(\n    age_population_df["Strut Accumulated Life Hours"],\n    bins=bins,\n    labels=labels,\n    include_lowest=True,\n    right=False,\n)\n\nage_bucket_summary = (\n    age_population_df\n    .groupby(["Life Hour Bucket", "Strut Type"], observed=False)\n    .size()\n    .reset_index(name="Strut Count")\n)\n\nfig_age_population = px.bar(\n    age_bucket_summary,\n    x="Life Hour Bucket",\n    y="Strut Count",\n    color="Strut Type",\n    title="Strut Age Population by Accumulated Life Hour Buckets",\n    text_auto=True,\n)\nfig_age_population.update_layout(xaxis_title="Accumulated Strut Life Hours", yaxis_title="Number of Struts")\nst.plotly_chart(fig_age_population, use_container_width=True)\n\nst.subheader("Population Over Strut Accumulated Life Hours")\n\nsorted_population_df = age_population_df.sort_values("Strut Accumulated Life Hours").reset_index(drop=True)\nsorted_population_df["Cumulative Strut Population"] = sorted_population_df.index + 1\nsorted_population_df["Cumulative Population %"] = (\n    sorted_population_df["Cumulative Strut Population"] / len(sorted_population_df) * 100\n)\n\nfig_cumulative_population = px.line(\n    sorted_population_df,\n    x="Strut Accumulated Life Hours",\n    y="Cumulative Strut Population",\n    color="Strut Type",\n    markers=True,\n    title="Cumulative Strut Population Over Accumulated Life Hours",\n    hover_data=["Truck ID", "Strut Position", "Current Cycle Hours", "Cumulative Population %"],\n)\nfig_cumulative_population.update_layout(\n    xaxis_title="Accumulated Strut Life Hours",\n    yaxis_title="Cumulative Number of Struts",\n)\nst.plotly_chart(fig_cumulative_population, use_container_width=True)\n\nwith st.expander("View strut age bucket summary"):\n    st.dataframe(age_bucket_summary, use_container_width=True)\n\n\n# ============================================================\n# 6. RUN FORECAST\n# ============================================================\n\nrun_forecast = st.button("Run Forecast", type="primary")\n\nif run_forecast:\n    st.info(f"Forecast running only for selected trucks with complete required hour data: {\', \'.join(sorted(input_df[\'Truck ID\'].unique(), key=lambda x: int(x) if str(x).isdigit() else str(x)))}")\n\n    yearly_summary, schedule_df, truck_summary, position_summary, ending_state_df = simulate_strut_forecast(\n        input_df=input_df,\n        start_year=int(start_year),\n        end_year=int(end_year),\n        annual_operating_hours=float(annual_operating_hours),\n        std_interval=float(std_interval),\n        hd_interval=float(hd_interval),\n        max_life_hours=float(max_life_hours),\n    )\n\n    st.success("Forecast completed successfully.")\n\n    total_operating = yearly_summary["Total Operating Change-Outs"].sum()\n    total_eol = yearly_summary["Total End-of-Life Replacements"].sum()\n    total_events = yearly_summary["Total Replacement Events"].sum()\n    total_new_std = yearly_summary["New Std Struts Required"].sum()\n    total_new_hd = yearly_summary["New HD Struts Required"].sum()\n    total_new = yearly_summary["Total New Struts Required"].sum()\n\n    kpi1, kpi2, kpi3, kpi4, kpi5, kpi6 = st.columns(6)\n    kpi1.metric("Operating Change-Outs", int(total_operating))\n    kpi2.metric("End-of-Life Replacements", int(total_eol))\n    kpi3.metric("Total Events", int(total_events))\n    kpi4.metric("New Std Struts", int(total_new_std))\n    kpi5.metric("New HD Struts", int(total_new_hd))\n    kpi6.metric("Total New Struts", int(total_new))\n\n    st.subheader("Yearly Summary")\n    st.dataframe(yearly_summary, use_container_width=True)\n\n    cost_detail_df, scenario_cost_summary, monthly_invoice_df, monthly_invoice_comparison = build_cost_analysis(\n        yearly_summary=yearly_summary,\n        selected_truck_count=total_included_trucks,\n        annual_operating_hours=float(annual_operating_hours),\n        start_year=int(start_year),\n        end_year=int(end_year),\n        discount_rate=float(discount_rate),\n        ppi_adjustments=ppi_adjustments,\n        current_std_new_cost=float(current_std_new_cost),\n        current_hd_new_cost=float(current_hd_new_cost),\n        current_repair_cost=float(current_repair_cost),\n        oem_std_new_cost=float(oem_std_new_cost),\n        oem_hd_new_cost=float(oem_hd_new_cost),\n        oem_repair_cost=float(oem_repair_cost),\n    )\n\n    st.subheader("Cost Analysis Summary")\n    st.caption("Costs use the specific PPI adjustment entered for each forecast year. Equivalent annual cost uses the present value of yearly forecast costs multiplied by the annuity factor. Scenario hourly rate = equivalent annual cost / selected fleet annual operating hours.")\n    st.dataframe(scenario_cost_summary, use_container_width=True)\n\n    cost_kpi_col1, cost_kpi_col2 = st.columns(2)\n    current_summary = scenario_cost_summary[scenario_cost_summary["Scenario"] == "Current Cost Strategy"].iloc[0]\n    oem_summary = scenario_cost_summary[scenario_cost_summary["Scenario"] == "OEM Reman Strategy"].iloc[0]\n\n    with cost_kpi_col1:\n        st.metric("Current Strategy Hourly Rate", f"{current_summary[\'Scenario Hourly Rate\']:,.2f}")\n        st.metric("Current Strategy Equivalent Annual Cost", f"{current_summary[\'Equivalent Annual Cost\']:,.2f}")\n\n    with cost_kpi_col2:\n        st.metric("OEM Reman Strategy Hourly Rate", f"{oem_summary[\'Scenario Hourly Rate\']:,.2f}")\n        st.metric("OEM Reman Strategy Equivalent Annual Cost", f"{oem_summary[\'Equivalent Annual Cost\']:,.2f}")\n\n    st.subheader("Estimated Monthly Invoice Comparison")\n    st.caption("The OEM Reman monthly invoice is estimated from the OEM Reman equivalent annual cost divided by 12. The Current Strategy monthly cost is calculated the same way for comparison.")\n    st.dataframe(monthly_invoice_comparison, use_container_width=True)\n\n    invoice_kpi_col1, invoice_kpi_col2, invoice_kpi_col3 = st.columns(3)\n    invoice_kpi_col1.metric(\n        "OEM Reman Estimated Monthly Invoice",\n        f"{monthly_invoice_comparison[\'OEM Reman Estimated Monthly Invoice\'].iloc[0]:,.2f}",\n    )\n    invoice_kpi_col2.metric(\n        "Current Strategy Estimated Monthly Cost",\n        f"{monthly_invoice_comparison[\'Current Strategy Estimated Monthly Cost\'].iloc[0]:,.2f}",\n    )\n    invoice_kpi_col3.metric(\n        "Monthly Difference OEM vs Current",\n        f"{monthly_invoice_comparison[\'Monthly Difference OEM vs Current\'].iloc[0]:,.2f}",\n        delta=f"{monthly_invoice_comparison[\'Monthly Difference %\'].iloc[0]:,.2f}%",\n    )\n\n    st.subheader("Monthly Cost by Scenario")\n    st.dataframe(monthly_invoice_df, use_container_width=True)\n\n    st.subheader("Cost Analysis by Year")\n    st.dataframe(cost_detail_df, use_container_width=True)\n\n    st.subheader("Detailed Replacement Schedule")\n    st.dataframe(schedule_df, use_container_width=True)\n\n    st.subheader("Demand by Truck")\n    st.dataframe(truck_summary, use_container_width=True)\n\n    st.subheader("Demand by Strut Position")\n    st.dataframe(position_summary, use_container_width=True)\n\n    with st.expander("View Ending State After Forecast"):\n        st.dataframe(ending_state_df, use_container_width=True)\n\n    st.subheader("Monthly Invoice Charts")\n\n    fig_monthly_cost = px.bar(\n        monthly_invoice_df,\n        x="Scenario",\n        y="Estimated Monthly Cost",\n        title="Estimated Monthly Cost by Scenario",\n        text_auto=True,\n    )\n    st.plotly_chart(fig_monthly_cost, use_container_width=True)\n\n    st.subheader("Cost Analysis Charts")\n\n    fig_cost_year = px.bar(\n        cost_detail_df,\n        x="Year",\n        y="Total Year Cost",\n        color="Scenario",\n        barmode="group",\n        title="Total Forecast Cost by Year and Scenario",\n        text_auto=True,\n    )\n    fig_cost_year.update_layout(xaxis=dict(tickmode="linear", dtick=1, tickformat="d"))\n    st.plotly_chart(fig_cost_year, use_container_width=True)\n\n    fig_cost_components = px.bar(\n        cost_detail_df,\n        x="Year",\n        y=["Std New Strut Cost", "HD New Strut Cost", "Repair Cost"],\n        color="Scenario",\n        facet_col="Scenario",\n        title="Cost Components by Year",\n        text_auto=True,\n    )\n    fig_cost_components.update_xaxes(tickmode="linear", dtick=1, tickformat="d")\n    st.plotly_chart(fig_cost_components, use_container_width=True)\n\n    fig_hourly_rate_year = px.line(\n        cost_detail_df,\n        x="Year",\n        y="Yearly Hourly Rate",\n        color="Scenario",\n        markers=True,\n        title="Hourly Rate by Year and Scenario",\n        line_shape="spline",\n    )\n    fig_hourly_rate_year.update_layout(\n        yaxis_title="Hourly Rate",\n        xaxis_title="Year",\n        xaxis=dict(tickmode="linear", dtick=1, tickformat="d"),\n    )\n    st.plotly_chart(fig_hourly_rate_year, use_container_width=True)\n\n    fig_accumulated_budget = px.line(\n        cost_detail_df,\n        x="Year",\n        y="Accumulated Budget",\n        color="Scenario",\n        markers=True,\n        title="Accumulated Budget by Scenario and Year",\n        line_shape="spline",\n    )\n    fig_accumulated_budget.update_layout(\n        yaxis_title="Accumulated Total Cost",\n        xaxis_title="Year",\n        xaxis=dict(tickmode="linear", dtick=1, tickformat="d"),\n    )\n    st.plotly_chart(fig_accumulated_budget, use_container_width=True)\n\n    fig_annuity_cost = px.bar(\n        cost_detail_df,\n        x="Year",\n        y="Annuity Cost per Year",\n        color="Scenario",\n        barmode="group",\n        title="Annuity Cost per Year by Scenario",\n        text_auto=True,\n    )\n    fig_annuity_cost.update_layout(\n        yaxis_title="Annuity Cost per Year",\n        xaxis_title="Year",\n        xaxis=dict(tickmode="linear", dtick=1, tickformat="d"),\n    )\n    st.plotly_chart(fig_annuity_cost, use_container_width=True)\n\n    fig_hourly_rate_comparison = px.line(\n        cost_detail_df,\n        x="Year",\n        y="Yearly Hourly Rate",\n        color="Scenario",\n        markers=True,\n        title="Hourly Rate by Year and Scenario Comparison",\n        line_shape="spline",\n    )\n    fig_hourly_rate_comparison.update_layout(\n        yaxis_title="Hourly Rate",\n        xaxis_title="Year",\n        xaxis=dict(tickmode="linear", dtick=1, tickformat="d"),\n    )\n    st.plotly_chart(fig_hourly_rate_comparison, use_container_width=True)\n\n    st.subheader("Forecast Charts")\n\n    chart_col1, chart_col2 = st.columns(2)\n\n    with chart_col1:\n        fig_operating = px.bar(\n            yearly_summary,\n            x="Year",\n            y=["Std Operating Change-Outs", "HD Operating Change-Outs"],\n            title="Operating Change-Outs by Year and Strut Type",\n            barmode="group",\n            text_auto=True,\n        )\n        fig_operating.update_layout(\n            xaxis=dict(tickmode="linear", dtick=1, tickformat="d")\n        )\n        st.plotly_chart(fig_operating, use_container_width=True)\n\n    with chart_col2:\n        fig_new = px.bar(\n            yearly_summary,\n            x="Year",\n            y=["New Std Struts Required", "New HD Struts Required"],\n            title="New Struts Required by Year Due to End of Life",\n            barmode="group",\n            text_auto=True,\n        )\n        fig_new.update_layout(\n            xaxis=dict(tickmode="linear", dtick=1, tickformat="d")\n        )\n        st.plotly_chart(fig_new, use_container_width=True)\n\n    fig_total = px.bar(\n        yearly_summary,\n        x="Year",\n        y="Total Replacement Events",\n        title="Total Replacement Events by Year",\n        text_auto=True,\n    )\n    fig_total.update_layout(\n        xaxis=dict(tickmode="linear", dtick=1, tickformat="d")\n    )\n    st.plotly_chart(fig_total, use_container_width=True)\n\n    fig_truck = px.bar(\n        truck_summary,\n        x="Truck ID",\n        y="Total Replacement Events",\n        color="Strut Type",\n        title="Total Replacement Events by Truck",\n        text_auto=True,\n    )\n    fig_truck.update_layout(xaxis_type="category")\n    st.plotly_chart(fig_truck, use_container_width=True)\n\n    fig_truck_new = px.bar(\n        truck_summary,\n        x="Truck ID",\n        y="New Struts Required",\n        color="Strut Type",\n        title="New Struts Required by Truck Due to End of Life",\n        text_auto=True,\n    )\n    fig_truck_new.update_layout(xaxis_type="category")\n    st.plotly_chart(fig_truck_new, use_container_width=True)\n\n    fig_position = px.bar(\n        position_summary,\n        x="Strut Position",\n        y="Total Replacement Events",\n        color="Strut Type",\n        title="Total Replacement Events by Strut Position",\n        text_auto=True,\n    )\n    st.plotly_chart(fig_position, use_container_width=True)\n\n    if not schedule_df.empty:\n        reason_chart_df = (\n            schedule_df\n            .groupby(["Year", "Event Reason"], as_index=False)["Total Replacement Events"]\n            .sum()\n        )\n\n        fig_reason = px.bar(\n            reason_chart_df,\n            x="Year",\n            y="Total Replacement Events",\n            color="Event Reason",\n            title="Replacement Events by Reason",\n            text_auto=True,\n        )\n        fig_reason.update_layout(\n            xaxis=dict(tickmode="linear", dtick=1, tickformat="d")\n        )\n        st.plotly_chart(fig_reason, use_container_width=True)\n\nelse:\n    st.info("Click \'Run Forecast\' to generate the replacement forecast.")\n'

_INTEGRATED_CORE_CACHE = {}

def _exec_embedded_streamlit_project(source: str, module_name: str, sidebar_group_name: str | None = None):
    """Execute an embedded Streamlit app inside the current tab.

    The child apps are executed in isolated namespaces to avoid overwriting
    global variables from the v25 dashboard. During the execution, common
    Streamlit widgets are temporarily wrapped to inject deterministic keys when
    the embedded source does not define them. This prevents DuplicateElementId
    errors when a child project reuses widget labels from the parent dashboard
    or repeats the same widget label internally.
    """
    import functools

    widget_names = [
        "button",
        "checkbox",
        "radio",
        "selectbox",
        "multiselect",
        "slider",
        "select_slider",
        "number_input",
        "text_input",
        "text_area",
        "date_input",
        "time_input",
        "file_uploader",
        "download_button",
        "toggle",
        "plotly_chart",
    ]

    counters = {}
    patched = []

    # When an embedded project has its own sidebar controls, route all of them
    # into a collapsed expander named exactly like the tab. This keeps the main
    # sidebar clean: only the tab name is visible until the user expands it.
    embedded_sidebar = None
    if sidebar_group_name:
        # Use reserved sidebar slots when available so the integrated project
        # menus are always visible in the correct order and do not appear at
        # the bottom after the PDF controls.
        slot = None
        if sidebar_group_name == "Availability report & Forecast":
            slot = globals().get("AVAILABILITY_SIDEBAR_SLOT")
        elif sidebar_group_name == "Strut model risk assessment":
            slot = globals().get("STRUT_SIDEBAR_SLOT")

        if slot is not None:
            embedded_sidebar = slot.expander(sidebar_group_name, expanded=False)
        else:
            embedded_sidebar = st.sidebar.expander(sidebar_group_name, expanded=False)

        # Route all embedded sidebar calls into the expander for that project.
        source = source.replace("st.sidebar.", "_EMBEDDED_SIDEBAR.")
        source = source.replace("with st.sidebar:", "with _EMBEDDED_SIDEBAR:")

    def make_key(scope, func_name, args):
        label = ""
        if args:
            try:
                label = str(args[0])[:80]
            except Exception:
                label = ""
        base = f"{module_name}::{scope}::{func_name}::{label}"
        idx = counters.get(base, 0)
        counters[base] = idx + 1
        safe_label = re.sub(r"[^A-Za-z0-9_]+", "_", label).strip("_")[:60]
        return f"{module_name}_{scope}_{func_name}_{safe_label}_{idx}"

    def patch_target(target, scope):
        for func_name in widget_names:
            if not hasattr(target, func_name):
                continue
            original = getattr(target, func_name)

            @functools.wraps(original)
            def wrapped(*args, __original=original, __func_name=func_name, __scope=scope, **kwargs):
                if "key" not in kwargs or kwargs.get("key") is None:
                    kwargs["key"] = make_key(__scope, __func_name, args)
                return __original(*args, **kwargs)

            try:
                setattr(target, func_name, wrapped)
                patched.append((target, func_name, original))
            except Exception:
                pass

    patch_target(st, "main")
    patch_target(st.sidebar, "sidebar")

    # Patch DeltaGenerator methods as well. This covers widgets rendered from
    # containers/columns/tabs/placeholders, e.g. col.number_input(...),
    # sidebar_container.selectbox(...), or container.plotly_chart(...).
    try:
        from streamlit.delta_generator import DeltaGenerator
        patch_target(DeltaGenerator, "container")
    except Exception:
        pass

    ns = {
        "__name__": module_name,
        "__file__": str(BASE_DIR / f"{module_name}.py"),
        "_EMBEDDED_SIDEBAR": embedded_sidebar if embedded_sidebar is not None else st.sidebar,
    }
    try:
        exec(compile(source, f"<embedded {module_name}>", "exec"), ns)
    finally:
        for target, func_name, original in reversed(patched):
            try:
                setattr(target, func_name, original)
            except Exception:
                pass


@st.cache_resource(show_spinner=False)
def _get_embedded_project_core(project_key: str):
    """Load only data/model functions from the embedded projects for PDF sections.

    Important: PDF generation must not execute the Streamlit UI section of the
    embedded apps. Executing the full embedded apps during PDF generation creates
    temporary sidebar widgets and can also prevent the PDF from receiving the
    calculated results. This loader cuts each embedded source exactly before its
    first Streamlit UI/title block and keeps only imports, embedded data and
    calculation functions.
    """
    if project_key in _INTEGRATED_CORE_CACHE:
        return _INTEGRATED_CORE_CACHE[project_key]

    if project_key == "availability":
        module_name = "embedded_availability_core"
        marker_candidates = [
            "\nst.title(",
            "\nst.markdown(",
            "\nwith st.sidebar:",
        ]
        source = AVAILABILITY_PROJECT_SOURCE
    elif project_key == "strut":
        module_name = "embedded_strut_core"
        marker_candidates = [
            "# ============================================================\n# 5. STREAMLIT APP",
            "# 5. STREAMLIT APP",
            "\nst.title(",
            "\nst.markdown(",
            "\nst.sidebar.",
        ]
        source = STRUT_PROJECT_SOURCE
    else:
        raise ValueError(f"Unknown embedded project key: {project_key}")

    cut_positions = [source.find(marker) for marker in marker_candidates if source.find(marker) != -1]
    if cut_positions:
        source = source[:min(cut_positions)]

    ns = {
        "__name__": module_name,
        "__file__": str(BASE_DIR / f"{module_name}.py"),
    }
    exec(compile(source, f"<{module_name}>", "exec"), ns)
    _INTEGRATED_CORE_CACHE[project_key] = ns
    return ns


def render_availability_project_tab():
    """Render Project 1 lazily to avoid recalculating the Monte Carlo module on every app rerun."""
    st.markdown("### Availability report & Forecast")
    st.caption("Integrated module: historical availability, reliability, down-by-system analysis, Improved forecast reactivation, and Monte Carlo forecast 2027-2030.")
    load_key = "load_availability_forecast_module"
    load_module = st.toggle(
        "Load Availability forecast module",
        value=st.session_state.get(load_key, False),
        key=load_key,
        help="Keep this off while working in the cost dashboard to avoid unnecessary Monte Carlo recalculations. Turn it on only when reviewing this module.",
    )
    if not load_module:
        st.info(
            "The Availability forecast module is ready but not loaded. Activate the switch above to render the full analysis and its sidebar controls. "
            "PDF generation still includes this section when selected from PDF Reports."
        )
        return
    _exec_embedded_streamlit_project(AVAILABILITY_PROJECT_SOURCE, "embedded_availability_project", "Availability report & Forecast")


def render_strut_project_tab():
    """Render Project 2 lazily to avoid loading strut widgets and charts unless required."""
    st.markdown("### Strut model risk assessment")
    st.caption("Integrated module: strut change-out forecast, end-of-life replacement risk, and cost strategy comparison.")
    load_key = "load_strut_risk_module"
    load_module = st.toggle(
        "Load Strut risk assessment module",
        value=st.session_state.get(load_key, False),
        key=load_key,
        help="Keep this off while working in other tabs. Turn it on only when reviewing the strut model.",
    )
    if not load_module:
        st.info(
            "The Strut risk assessment module is ready but not loaded. Activate the switch above to render the full analysis and its sidebar controls. "
            "PDF generation still includes this section when selected from PDF Reports."
        )
        return
    _exec_embedded_streamlit_project(STRUT_PROJECT_SOURCE, "embedded_strut_project", "Strut model risk assessment")

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
    "Availability report & Forecast",
    "Strut model risk assessment",
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
_HITACHI_LOGO_B64 = "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A2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgTC4IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgTC4IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgTC4IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgTC4IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgXhpfmTmNSA/z4FdISIiIiJFZcoBZcpafZjJbDabNTU4NQpIOqa3W0RERERkj55TgF5TrT6M07JEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiID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"

# Footer orange band (image4.png from the letterhead) — full-width branded strip
_HITACHI_LOGO_B64 = "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A2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgTC4IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgTC4IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgTC4IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgTC4IyIiIjIQBndEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiIDYXBHREREZCAM7oiIiIgMhMEdERERkYEwuCMiIiIyEAZ3RERERAbC4I6IiIjIQBjcERERERkIgzsiIiIiA2FwR0RERGQgDO6IiIiIDITBHREREZGBMLgjIiIiMhAGd0REREQGwuCOiIiIyEAY3BEREREZCIM7IiIiIgNhcEdERERkIAzuiIiIiAyEwR0RERGRgXhpfmTmNSA/z4FdISIiIiJFZcoBZcpafZjJbDabNTU4NQpIOqa3W0RERERkj55TgF5TrT6M07JEREREBsLgjoiIiMhAGNwRERERGQiDOyIiIiID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"

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


PDF_ORANGE = "#FF6B00"
PDF_DARK = "#1A1A1A"
PDF_GREEN = "#2E7D32"
PDF_GREY = "#777777"
PDF_LIGHT_ORANGE = "#FFB37A"
PDF_LIGHT_GREEN = "#A5D6A7"
PDF_BLUE = "#1F77B4"
PDF_PALETTE = [PDF_ORANGE, PDF_DARK, PDF_GREEN, PDF_GREY, PDF_LIGHT_ORANGE, PDF_BLUE]


def _apply_pdf_plot_theme(fig):
    """Apply the same report color system used by the Streamlit dashboard.

    This prevents Kaleido/Plotly export from falling back to all-black traces
    in the PDF and also adds safe margins so axes and legends stay inside
    the branded report template.
    """
    fig.update_layout(
        template="plotly_white",
        colorway=PDF_PALETTE,
        font=dict(family="Helvetica", size=10, color=PDF_DARK),
        title_font=dict(size=13, color=PDF_DARK),
        paper_bgcolor="white",
        plot_bgcolor="white",
        legend=dict(font=dict(size=9), orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=75, r=35, t=70, b=75),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#EEEEEE", zeroline=False, automargin=True)
    fig.update_yaxes(showgrid=True, gridcolor="#EEEEEE", zeroline=False, automargin=True)
    return fig


def _fig_to_pdf_element(fig, width=500, height=235):
    """Convert a Plotly figure into a ReportLab image element with safe margins/colors."""
    from reportlab.platypus import Image, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet
    styles = getSampleStyleSheet()
    try:
        fig = _apply_pdf_plot_theme(fig)
        img_bytes = fig.to_image(format="png", engine="kaleido", width=1200, height=700, scale=2)
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


@st.cache_data(show_spinner=False)
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


@st.cache_data(show_spinner=False)
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


@st.cache_data(show_spinner=False)
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


@st.cache_data(show_spinner=False)
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


@st.cache_data(show_spinner=False)
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


@st.cache_data(show_spinner=False)
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



def _add_availability_forecast_section(story, styles, report_df,
                                       thresholds=None, core_filter_metric="", extra_dts=None):
    """Full PDF section for the integrated Availability report & Forecast project.

    This builder intentionally uses the embedded calculation/data functions only.
    It does not execute the embedded Streamlit UI, so PDF generation does not
    create temporary sidebar widgets and does not depend on the tab being loaded.
    """
    from reportlab.platypus import Paragraph, Spacer, PageBreak
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go

    def _pct(value):
        try:
            return f"{float(value) * 100:.2f}%"
        except Exception:
            return "N/A"

    def _num(value, decimals=1):
        try:
            return f"{float(value):,.{decimals}f}"
        except Exception:
            return "N/A"

    def _add_safe(title, fn):
        try:
            return fn()
        except Exception as exc:
            story.append(Paragraph(f"{title} could not be calculated: {exc}", styles["BodyText"]))
            story.append(Spacer(1, 8))

    story.append(Paragraph("Availability report & Forecast", styles["Heading2"]))
    story.append(Paragraph(
        "This section summarizes the integrated availability, reliability, system down analysis and Monte Carlo forecast model. "
        "The PDF is generated from the embedded model data and functions, without executing the Streamlit UI of the embedded tab.",
        styles["BodyText"],
    ))
    story.append(Spacer(1, 8))

    try:
        core = _get_embedded_project_core("availability")
        values = core["load_values_data"]()
        hist = core["load_historical_system_downs"]()
        kit = core["load_ponderate_kit_data"]()

        availability_col = "Availability" if "Availability" in values.columns else "% Avaiability"
        mtbf_col = "MTBF"
        down_col = "Hours down (EVs)" if "Hours down (EVs)" in values.columns else "Hours down (% availability)"
        events_col = "Number of events (According MTBF)"
        scheduled_col = "hours scheduled"

        active = []
        if "DT" in report_df.columns:
            for x in report_df["DT"].dropna().unique():
                try:
                    xi = int(x)
                    if 823 <= xi <= 852:
                        active.append(xi)
                except Exception:
                    pass
        active = sorted(set(active))
        if not active:
            active = sorted(int(x) for x in values["DT"].dropna().unique())

        vals_sel = values[values["DT"].isin(active)].copy()
        hist_sel = hist[hist["DT"].isin(active)].copy()
        systems = tuple(sorted(hist_sel["System"].dropna().astype(str).unique()))

        hist_avg_av = vals_sel[availability_col].mean() if not vals_sel.empty else 0
        hist_avg_mtbf = vals_sel[mtbf_col].mean() if mtbf_col in vals_sel.columns and not vals_sel.empty else 0
        total_down = vals_sel[down_col].sum() if down_col in vals_sel.columns and not vals_sel.empty else hist_sel["Event duration hours"].sum()
        total_events = vals_sel[events_col].sum() if events_col in vals_sel.columns and not vals_sel.empty else len(hist_sel)
        total_sched = vals_sel[scheduled_col].sum() if scheduled_col in vals_sel.columns and not vals_sel.empty else 0

        kpi_rows = [
            ["Metric", "Value"],
            ["Trucks included", ", ".join(str(x) for x in active)],
            ["Historical period", "January 2024 to March 2025"],
            ["Historical average availability", _pct(hist_avg_av)],
            ["Historical average MTBF", f"{_num(hist_avg_mtbf)} h/event"],
            ["Historical down hours", f"{_num(total_down)} h"],
            ["Historical event count", _num(total_events, 0)],
            ["Scheduled hours", f"{_num(total_sched)} h"],
            ["Forecast horizon", "January 2027 to December 2030"],
            ["Monte Carlo simulations used in PDF", "500"],
            ["Improved forecast reactivation", "Applied to down hours and event counts by system"],
        ]
        story.append(_pdf_table(kpi_rows, col_widths=[220, 300]))
        story.append(Spacer(1, 10))

        def historical_monthly_section():
            story.append(Paragraph("Historical fleet monthly performance", styles["Heading3"]))
            monthly = vals_sel.groupby("YearMonth", as_index=False).agg({
                availability_col: "mean",
                mtbf_col: "mean",
                down_col: "sum",
                events_col: "sum",
            })
            monthly["Period"] = monthly["YearMonth"].astype(str)
            table_rows = [["Month", "Availability", "MTBF", "Down hours", "Events"]]
            for _, r in monthly.tail(15).iterrows():
                table_rows.append([
                    str(r["Period"]),
                    _pct(r[availability_col]),
                    _num(r[mtbf_col]),
                    _num(r[down_col]),
                    _num(r[events_col], 0),
                ])
            story.append(_pdf_table(table_rows, col_widths=[80, 95, 85, 110, 80]))
            story.append(Spacer(1, 8))
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=monthly["Period"], y=monthly[availability_col], mode="lines+markers", name="Availability", line=dict(color=PDF_ORANGE, width=2), marker=dict(color=PDF_ORANGE)))
            fig.update_layout(title="Historical fleet availability", yaxis_tickformat=".0%", height=280, margin=dict(l=75, r=30, t=55, b=55))
            story.append(_fig_to_pdf_element(fig))
            story.append(Spacer(1, 8))
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=monthly["Period"], y=monthly[mtbf_col], mode="lines+markers", name="MTBF", line=dict(color=PDF_DARK, width=2), marker=dict(color=PDF_DARK)))
            fig2.update_layout(title="Historical fleet MTBF", yaxis_title="h/event", height=280, margin=dict(l=75, r=30, t=55, b=55))
            story.append(_fig_to_pdf_element(fig2))
            story.append(Spacer(1, 10))
        _add_safe("Historical monthly performance", historical_monthly_section)

        def truck_section():
            story.append(Paragraph("Historical performance by truck", styles["Heading3"]))
            truck = vals_sel.groupby("DT", as_index=False).agg({
                availability_col: "mean",
                mtbf_col: "mean",
                down_col: "sum",
                events_col: "sum",
                scheduled_col: "sum",
            })
            truck = truck.sort_values(availability_col, ascending=True)
            rows = [["Truck", "Availability", "MTBF", "Down hours", "Events", "Scheduled hours"]]
            for _, r in truck.iterrows():
                rows.append([
                    str(int(r["DT"])),
                    _pct(r[availability_col]),
                    _num(r[mtbf_col]),
                    _num(r[down_col]),
                    _num(r[events_col], 0),
                    _num(r[scheduled_col]),
                ])
            story.append(_pdf_table(rows, col_widths=[55, 85, 75, 95, 65, 105]))
            story.append(Spacer(1, 8))
            fig = px.bar(truck, x="DT", y=availability_col, title="Availability by truck", color_discrete_sequence=[PDF_ORANGE])
            fig.update_traces(marker_color=PDF_ORANGE)
            fig.update_layout(xaxis_type="category", yaxis_tickformat=".0%", height=300, margin=dict(l=75, r=30, t=55, b=55))
            story.append(_fig_to_pdf_element(fig))
            story.append(Spacer(1, 10))
        _add_safe("Historical truck performance", truck_section)

        story.append(PageBreak())

        def system_down_section():
            story.append(Paragraph("System down analysis and Improved forecast reactivation", styles["Heading3"]))
            system = hist_sel.groupby("System", as_index=False).agg(
                Events=("System", "size"),
                Base_down_hours=("Event duration hours", "sum"),
                Avg_event_duration=("Event duration hours", "mean"),
                Trucks_affected=("DT", "nunique"),
            )
            kit_map = kit[["System", "Kit improvement factor"]].copy() if "Kit improvement factor" in kit.columns else kit.copy()
            system = system.merge(kit_map, on="System", how="left")
            system["Kit improvement factor"] = pd.to_numeric(system.get("Kit improvement factor", 0), errors="coerce").fillna(0)
            system["Kit_adjusted_down_hours"] = system["Base_down_hours"] * (1 - system["Kit improvement factor"])
            system["Down_hours_reduced"] = system["Base_down_hours"] - system["Kit_adjusted_down_hours"]
            system["Kit_adjusted_events"] = system["Events"] * (1 - system["Kit improvement factor"])
            system["Events_reduced"] = system["Events"] - system["Kit_adjusted_events"]
            system = system.sort_values("Base_down_hours", ascending=False)
            rows = [["System", "Events", "Base down h", "Kit adj. h", "Reduction h", "Impact", "Avg h"]]
            for _, r in system.head(15).iterrows():
                rows.append([
                    str(r["System"])[:30],
                    _num(r["Events"], 0),
                    _num(r["Base_down_hours"]),
                    _num(r["Kit_adjusted_down_hours"]),
                    _num(r["Down_hours_reduced"]),
                    _pct(r["Kit improvement factor"]),
                    _num(r["Avg_event_duration"]),
                ])
            # Total width kept below the 540 pt usable page width to avoid overflow on page 29.
            story.append(_pdf_table(rows, col_widths=[125, 48, 70, 70, 70, 55, 55]))
            story.append(Spacer(1, 8))
            top = system.head(12).melt(
                id_vars=["System"],
                value_vars=["Base_down_hours", "Kit_adjusted_down_hours"],
                var_name="Scenario",
                value_name="Down hours",
            )
            top["Scenario"] = top["Scenario"].replace({
                "Base_down_hours": "Base down hours",
                "Kit_adjusted_down_hours": "Improved forecast reactivation",
            })
            fig = px.bar(
                top, x="System", y="Down hours", color="Scenario", barmode="group",
                title="Down hours by system: base vs Kit adjusted",
                color_discrete_map={"Base down hours": PDF_ORANGE, "Improved forecast reactivation": PDF_GREEN},
            )
            fig.update_layout(height=330, margin=dict(l=75, r=35, t=70, b=115), xaxis_tickangle=-35)
            story.append(_fig_to_pdf_element(fig, width=500, height=250))
            story.append(Spacer(1, 8))
            reduction = system.sort_values("Down_hours_reduced", ascending=False).head(10)
            fig2 = px.bar(
                reduction, x="System", y="Down_hours_reduced",
                title="Estimated down hours avoided by Improved forecast reactivation",
                color_discrete_sequence=[PDF_GREEN],
            )
            fig2.update_traces(marker_color=PDF_GREEN)
            fig2.update_layout(height=300, margin=dict(l=75, r=35, t=70, b=110), xaxis_tickangle=-35)
            story.append(_fig_to_pdf_element(fig2, width=500, height=235))
            story.append(Spacer(1, 10))
        _add_safe("System down analysis", system_down_section)

        story.append(PageBreak())

        def forecast_section():
            story.append(Paragraph("Forecast 2027-2030 — Bottom-up + Monte Carlo model", styles["Heading3"]))
            fleet_month, annual_summary, truck_year = core["run_monte_carlo_forecast"](
                values.to_csv(index=False),
                hist.to_csv(index=False),
                kit.to_csv(index=False),
                tuple(active),
                systems,
                True,
                0.85,
                0.005,
                0.04,
                500,
                42,
            )
            annual_rows = [["Year", "Target", "Base avail.", "Kit avail.", "Active avail.", "Active MTBF", "Down h avoided", "Events avoided"]]
            for _, r in annual_summary.iterrows():
                annual_rows.append([
                    str(int(r.get("Year", 0))),
                    _pct(r.get("Target availability", 0)),
                    _pct(r.get("Base Availability", 0)),
                    _pct(r.get("Kit Availability", 0)),
                    _pct(r.get("Active Availability", 0)),
                    _num(r.get("Active MTBF", 0)),
                    _num(r.get("Down hours avoided by kit", 0)),
                    _num(r.get("Events avoided by kit", 0), 0),
                ])
            story.append(_pdf_table(annual_rows, col_widths=[45, 55, 65, 65, 70, 70, 85, 75]))
            story.append(Spacer(1, 8))

            fm = fleet_month.copy()
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=fm["Period"], y=fm["Active Availability P50"], mode="lines", name="Active availability P50", line=dict(color=PDF_ORANGE, width=2)))
            fig.add_trace(go.Scatter(x=fm["Period"], y=fm["Active Availability P90"], mode="lines", name="P90", line=dict(width=0), showlegend=False))
            fig.add_trace(go.Scatter(x=fm["Period"], y=fm["Active Availability P10"], mode="lines", name="P10-P90 band", fill="tonexty", line=dict(width=0), fillcolor="rgba(255,107,0,0.18)"))
            if "Target availability" in fm.columns:
                fig.add_trace(go.Scatter(x=fm["Period"], y=fm["Target availability"], mode="lines", name="Target", line=dict(color=PDF_DARK, dash="dash")))
            fig.update_layout(title="Availability forecast with uncertainty band", yaxis_tickformat=".0%", height=320, margin=dict(l=75, r=30, t=55, b=55))
            story.append(_fig_to_pdf_element(fig, width=500, height=245))
            story.append(Spacer(1, 8))

            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=fm["Period"], y=fm["Base MTBF mean"], mode="lines", name="Base MTBF", line=dict(color=PDF_DARK, width=2)))
            fig2.add_trace(go.Scatter(x=fm["Period"], y=fm["Kit MTBF mean"], mode="lines", name="Kit adjusted MTBF", line=dict(color=PDF_GREEN, width=2, dash="dot")))
            fig2.add_trace(go.Scatter(x=fm["Period"], y=fm["Active MTBF mean"], mode="lines", name="Active MTBF", line=dict(color=PDF_ORANGE, width=2)))
            fig2.update_layout(title="MTBF forecast 2027-2030", yaxis_title="h/event", height=300, margin=dict(l=75, r=30, t=55, b=55))
            story.append(_fig_to_pdf_element(fig2, width=500, height=235))
            story.append(Spacer(1, 8))

            truck_risk = truck_year.sort_values(["Year", "Availability P50"], ascending=[True, True]).copy()
            risk_rows = [["Year", "Truck", "Availability P50", "P10", "P90", "MTBF", "Down h", "Events"]]
            for _, r in truck_risk.groupby("Year", group_keys=False).head(5).iterrows():
                risk_rows.append([
                    str(int(r["Year"])),
                    str(int(r["DT"])),
                    _pct(r["Availability P50"]),
                    _pct(r["Availability P10"]),
                    _pct(r["Availability P90"]),
                    _num(r["MTBF mean"]),
                    _num(r["Down hours mean"]),
                    _num(r["Events mean"], 0),
                ])
            story.append(Paragraph("Lowest forecast availability trucks by year", styles["Heading3"]))
            story.append(_pdf_table(risk_rows, col_widths=[45, 50, 80, 55, 55, 65, 70, 55]))
            story.append(Spacer(1, 8))

            top_risk = truck_year.groupby("DT", as_index=False).agg({"Availability P50": "mean", "Down hours mean": "sum", "Events mean": "sum"}).sort_values("Availability P50").head(15)
            fig3 = px.bar(top_risk, x="DT", y="Availability P50", title="Lowest average forecast availability by truck", color_discrete_sequence=[PDF_ORANGE])
            fig3.update_traces(marker_color=PDF_ORANGE)
            fig3.update_layout(xaxis_type="category", yaxis_tickformat=".0%", height=300, margin=dict(l=75, r=30, t=55, b=55))
            story.append(_fig_to_pdf_element(fig3, width=500, height=235))
            story.append(Spacer(1, 10))
        _add_safe("Forecast 2027-2030", forecast_section)

    except Exception as exc:
        story.append(Paragraph(f"Availability report & Forecast PDF section could not be calculated: {exc}", styles["BodyText"]))
        story.append(Spacer(1, 8))


def _add_strut_risk_section(story, styles, report_df,
                            thresholds=None, core_filter_metric="", extra_dts=None):
    """Full PDF section for the integrated Strut model risk assessment project.

    Uses the embedded strut calculation functions only. The Streamlit UI is not
    executed during PDF generation, which prevents sidebar flicker and allows the
    full project report and individual tab report to use the same content.
    """
    from reportlab.platypus import Paragraph, Spacer, PageBreak
    import pandas as pd
    import plotly.express as px

    def _num(value, decimals=0):
        try:
            return f"{float(value):,.{decimals}f}"
        except Exception:
            return "N/A"

    def _add_safe(title, fn):
        try:
            return fn()
        except Exception as exc:
            story.append(Paragraph(f"{title} could not be calculated: {exc}", styles["BodyText"]))
            story.append(Spacer(1, 8))

    story.append(Paragraph("Strut model risk assessment", styles["Heading2"]))
    story.append(Paragraph(
        "This section summarizes the integrated strut replacement forecast. It estimates operating change-outs, end-of-life replacements, new strut requirements, replacement reason, truck exposure and position exposure by year.",
        styles["BodyText"],
    ))
    story.append(Spacer(1, 8))

    try:
        core = _get_embedded_project_core("strut")
        data = core["load_embedded_data"]()
        active = []
        if "DT" in report_df.columns:
            for x in report_df["DT"].dropna().unique():
                try:
                    active.append(int(x))
                except Exception:
                    pass
        active = sorted(set(active))
        if "Truck ID" in data.columns and active:
            active_str = [str(x) for x in active]
            data = data[data["Truck ID"].astype(str).isin(active_str)].copy()
        if data.empty:
            story.append(Paragraph("No matching active trucks were found in the embedded strut database.", styles["BodyText"]))
            return

        yearly_summary, schedule_df, truck_summary, position_summary, ending_state_df = core["simulate_strut_forecast"](
            data,
            2027,
            2030,
            6000,
            4500,
            7500,
            45000,
        )
        if yearly_summary.empty:
            story.append(Paragraph("No strut replacement results were generated for the selected fleet.", styles["BodyText"]))
            return

        yearly = yearly_summary.copy()
        if "Total New Struts Required" in yearly.columns and "New Struts Required" not in yearly.columns:
            yearly["New Struts Required"] = yearly["Total New Struts Required"]
        if "Total End-of-Life Replacements" in yearly.columns and "End-of-Life Replacements" not in yearly.columns:
            yearly["End-of-Life Replacements"] = yearly["Total End-of-Life Replacements"]

        kpi_rows = [
            ["Metric", "Value"],
            ["Trucks included", ", ".join(str(x) for x in active) if active else "All embedded trucks"],
            ["Forecast horizon", "2027 to 2030"],
            ["Annual operating hours", "6,000 h/truck"],
            ["Standard interval", "4,500 h"],
            ["HD interval", "7,500 h"],
            ["Maximum strut total life", "45,000 h"],
            ["Total replacement events", _num(yearly["Total Replacement Events"].sum())],
            ["Total operating change-outs", _num(yearly["Total Operating Change-Outs"].sum())],
            ["Total new struts required", _num(yearly["New Struts Required"].sum())],
        ]
        story.append(_pdf_table(kpi_rows, col_widths=[220, 300]))
        story.append(Spacer(1, 10))

        def annual_section():
            story.append(Paragraph("Annual strut replacement forecast", styles["Heading3"]))
            annual_cols = [
                "Year", "HD Operating Change-Outs", "Std Operating Change-Outs",
                "HD End-of-Life Replacements", "Std End-of-Life Replacements",
                "New HD Struts Required", "New Std Struts Required",
                "Total Operating Change-Outs", "Total Replacement Events", "New Struts Required",
            ]
            rows = [["Year", "HD Op.", "Std Op.", "HD EOL", "Std EOL", "New HD", "New Std", "Total Op.", "Total Events", "New Struts"]]
            for _, r in yearly.iterrows():
                rows.append([
                    str(int(r.get("Year", 0))),
                    _num(r.get("HD Operating Change-Outs", 0)),
                    _num(r.get("Std Operating Change-Outs", 0)),
                    _num(r.get("HD End-of-Life Replacements", 0)),
                    _num(r.get("Std End-of-Life Replacements", 0)),
                    _num(r.get("New HD Struts Required", 0)),
                    _num(r.get("New Std Struts Required", 0)),
                    _num(r.get("Total Operating Change-Outs", 0)),
                    _num(r.get("Total Replacement Events", 0)),
                    _num(r.get("New Struts Required", 0)),
                ])
            story.append(_pdf_table(rows, col_widths=[42, 48, 48, 48, 48, 50, 50, 60, 65, 65]))
            story.append(Spacer(1, 8))

            fig = px.bar(yearly, x="Year", y=["Std Operating Change-Outs", "HD Operating Change-Outs"], barmode="group", title="Operating change-outs by year and strut type", color_discrete_sequence=[PDF_ORANGE, PDF_DARK])
            fig.update_layout(height=300, margin=dict(l=75, r=30, t=55, b=55), xaxis=dict(tickmode="linear", dtick=1, tickformat="d"))
            story.append(_fig_to_pdf_element(fig, width=500, height=235))
            story.append(Spacer(1, 8))
            fig2 = px.bar(yearly, x="Year", y=["New Std Struts Required", "New HD Struts Required"], barmode="group", title="New struts required by year due to end of life", color_discrete_sequence=[PDF_GREEN, PDF_LIGHT_GREEN])
            fig2.update_layout(height=300, margin=dict(l=75, r=30, t=55, b=55), xaxis=dict(tickmode="linear", dtick=1, tickformat="d"))
            story.append(_fig_to_pdf_element(fig2, width=500, height=235))
            story.append(Spacer(1, 8))
            fig3 = px.bar(yearly, x="Year", y="Total Replacement Events", title="Total replacement events by year", color_discrete_sequence=[PDF_ORANGE])
            fig3.update_traces(marker_color=PDF_ORANGE)
            fig3.update_layout(height=280, margin=dict(l=75, r=30, t=55, b=55), xaxis=dict(tickmode="linear", dtick=1, tickformat="d"))
            story.append(_fig_to_pdf_element(fig3, width=500, height=225))
            story.append(Spacer(1, 10))
        _add_safe("Annual strut replacement forecast", annual_section)

        story.append(PageBreak())

        def truck_position_section():
            story.append(Paragraph("Truck, position and reason exposure", styles["Heading3"]))
            truck_rows = [["Truck", "Type", "Events", "Operating", "End-of-life", "New struts"]]
            truck_view = truck_summary.sort_values("Total Replacement Events", ascending=False).head(30)
            for _, r in truck_view.iterrows():
                truck_rows.append([
                    str(r.get("Truck ID", "")),
                    str(r.get("Strut Type", "")),
                    _num(r.get("Total Replacement Events", 0)),
                    _num(r.get("Operating Change-Outs", 0)),
                    _num(r.get("End-of-Life Replacements", 0)),
                    _num(r.get("New Struts Required", 0)),
                ])
            story.append(_pdf_table(truck_rows, col_widths=[65, 65, 70, 80, 90, 80]))
            story.append(Spacer(1, 8))

            fig = px.bar(truck_summary, x="Truck ID", y="Total Replacement Events", color="Strut Type", title="Total replacement events by truck", color_discrete_sequence=[PDF_ORANGE, PDF_DARK])
            fig.update_layout(height=300, margin=dict(l=75, r=30, t=55, b=55), xaxis_type="category")
            story.append(_fig_to_pdf_element(fig, width=500, height=235))
            story.append(Spacer(1, 8))

            fig2 = px.bar(truck_summary, x="Truck ID", y="New Struts Required", color="Strut Type", title="New struts required by truck due to end of life", color_discrete_sequence=[PDF_GREEN, PDF_LIGHT_GREEN])
            fig2.update_layout(height=300, margin=dict(l=75, r=30, t=55, b=55), xaxis_type="category")
            story.append(_fig_to_pdf_element(fig2, width=500, height=235))
            story.append(Spacer(1, 8))

            pos_rows = [["Position", "Type", "Events", "Operating", "End-of-life", "New struts"]]
            for _, r in position_summary.sort_values("Total Replacement Events", ascending=False).iterrows():
                pos_rows.append([
                    str(r.get("Strut Position", "")),
                    str(r.get("Strut Type", "")),
                    _num(r.get("Total Replacement Events", 0)),
                    _num(r.get("Operating Change-Outs", 0)),
                    _num(r.get("End-of-Life Replacements", 0)),
                    _num(r.get("New Struts Required", 0)),
                ])
            story.append(_pdf_table(pos_rows, col_widths=[115, 55, 70, 80, 90, 80]))
            story.append(Spacer(1, 8))
            fig3 = px.bar(position_summary, x="Strut Position", y="Total Replacement Events", color="Strut Type", title="Total replacement events by strut position", color_discrete_sequence=[PDF_ORANGE, PDF_DARK])
            fig3.update_layout(height=300, margin=dict(l=75, r=30, t=55, b=70), xaxis_tickangle=-25)
            story.append(_fig_to_pdf_element(fig3, width=500, height=235))
            story.append(Spacer(1, 10))
        _add_safe("Truck and position exposure", truck_position_section)

        story.append(PageBreak())

        def schedule_section():
            story.append(Paragraph("Replacement schedule and event reason", styles["Heading3"]))
            if schedule_df.empty:
                story.append(Paragraph("No detailed schedule rows were generated.", styles["BodyText"]))
                return

            reason_chart_df = schedule_df.groupby(["Year", "Event Reason"], as_index=False)["Total Replacement Events"].sum()
            reason_rows = [["Year", "Event reason", "Events"]]
            for _, r in reason_chart_df.iterrows():
                reason_rows.append([str(int(r["Year"])), str(r["Event Reason"]), _num(r["Total Replacement Events"])])
            story.append(_pdf_table(reason_rows, col_widths=[60, 260, 90]))
            story.append(Spacer(1, 8))
            fig = px.bar(reason_chart_df, x="Year", y="Total Replacement Events", color="Event Reason", title="Replacement events by reason", color_discrete_sequence=PDF_PALETTE)
            fig.update_layout(height=300, margin=dict(l=75, r=30, t=55, b=55), xaxis=dict(tickmode="linear", dtick=1, tickformat="d"))
            story.append(_fig_to_pdf_element(fig, width=500, height=235))
            story.append(PageBreak())

            detailed = schedule_df.sort_values(["Year", "Truck ID", "Strut Position"]).head(30)
            detail_rows = [["Year", "Truck", "Position", "Type", "Reason", "Hours into year", "Life h"]]
            for _, r in detailed.iterrows():
                detail_rows.append([
                    str(int(r.get("Year", 0))),
                    str(r.get("Truck ID", "")),
                    str(r.get("Strut Position", ""))[:18],
                    str(r.get("Strut Type", "")),
                    str(r.get("Event Reason", ""))[:22],
                    _num(r.get("Hours Into Year at Event", 0)),
                    _num(r.get("Strut Life Hours at Event", 0)),
                ])
            story.append(Paragraph("Detailed replacement schedule sample", styles["Heading3"]))
            story.append(Paragraph("Showing the first 30 forecast events to keep the PDF readable and inside the report margins.", styles["BodyText"]))
            story.append(_pdf_table(detail_rows, col_widths=[42, 45, 95, 45, 130, 80, 80]))
            story.append(Spacer(1, 10))
        _add_safe("Replacement schedule and event reason", schedule_section)

    except Exception as exc:
        story.append(Paragraph(f"Strut model risk assessment PDF section could not be calculated: {exc}", styles["BodyText"]))
        story.append(Spacer(1, 8))


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
        "Part List":                    lambda: _add_part_list_section(story, styles, **_cfg),
        "Availability report & Forecast": lambda: _add_availability_forecast_section(story, styles, df, **_cfg),
        "Strut model risk assessment":    lambda: _add_strut_risk_section(story, styles, df, **_cfg),
        # Backward-compatible aliases for older session state values.
        "Availability forecast":          lambda: _add_availability_forecast_section(story, styles, df, **_cfg),
        "Struts risk assessment":         lambda: _add_strut_risk_section(story, styles, df, **_cfg),
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
with PDF_REPORTS_SIDEBAR_SLOT:
    with st.expander("PDF Reports", expanded=False):
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
        # figures through Kaleido. Reports are generated only after the user clicks a button.
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

tab_fleet, tab_truck, tab_kits, tab_gantt, tab_inventory, tab_inventory_total, tab_availability_forecast, tab_strut_risk = st.tabs([
    "Fleet Overview", "Cost Analysis per Truck", "Kit Analysis", "Reactivation Gantt",
    "Inventory Analysis", "Part List", "Availability report & Forecast", "Strut model risk assessment",
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


# ═══════════════════════════════════════════════════════════════
#  INTEGRATED TAB — AVAILABILITY REPORT & FORECAST
#  Source: availability_reliability_embedded_values_system_downs_streamlit_v7_forecast_montecarlo.py
# ═══════════════════════════════════════════════════════════════
with tab_availability_forecast:
    render_availability_project_tab()

# ═══════════════════════════════════════════════════════════════
#  INTEGRATED TAB — STRUT MODEL RISK ASSESSMENT
#  Source: streamlit run strut_forecast_app.py
# ═══════════════════════════════════════════════════════════════
with tab_strut_risk:
    render_strut_project_tab()
