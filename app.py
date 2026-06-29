"""
Jewel-Osco Fruit Assortment Recommender — Streamlit App
Run: streamlit run app.py
"""

import json
import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils.scoring import compute_scores, score_color, top_n
from utils.usda_api import (
    FALLBACK_COSTS, FREIGHT_COSTS, SEASONALITY, SHRINK_RATES,
    financial_metrics, get_wholesale_prices,
)
from utils.competitor_api import get_competitor_prices
from utils.claude_chat import build_system_prompt, stream_claude_response

# ── Page config ────────────────────────────────────────────────
st.set_page_config(
    page_title="Jewel-Osco Fruit Recommender",
    page_icon="🍎",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  [data-testid="stMetricValue"] { font-size: 1.6rem; }
  .score-card { border:1px solid #e2e8f0; border-radius:10px; padding:14px;
                background:#fff; margin-bottom:10px; }
  .score-great { color:#14532d; font-weight:700; }
  .score-good  { color:#166534; font-weight:700; }
  .score-ok    { color:#92400e; font-weight:700; }
  .score-low   { color:#991b1b; font-weight:700; }
</style>
""", unsafe_allow_html=True)


# ── Load data ──────────────────────────────────────────────────
@st.cache_data
def load_data() -> dict:
    path = Path(__file__).parent / "data" / "backend.json"
    with open(path, encoding="utf-8") as f:
        backend = json.load(f)

    # Inline DATA (mirrors HTML app)
    data = {
        "stores": [
            {"id":1,"city":"Lincoln Park"},{"id":2,"city":"Pilsen"},
            {"id":3,"city":"Evanston"},{"id":4,"city":"Bridgeport"},
            {"id":5,"city":"Oak Park"},{"id":6,"city":"Skokie"},
            {"id":7,"city":"Wicker Park"},{"id":8,"city":"South Shore"},
            {"id":9,"city":"Naperville"},{"id":10,"city":"Logan Square"},
            {"id":11,"city":"Rogers Park"},{"id":12,"city":"Schaumburg"},
            {"id":13,"city":"Hyde Park"},{"id":14,"city":"Berwyn"},
            {"id":15,"city":"Edgewater"},
        ],
        "eth_share": {
            "1":{"Asian":0.1258,"Black":0.1581,"Hispanic":0.2226,"Other":0.0387,"White":0.4548},
            "2":{"Asian":0.0623,"Black":0.1869,"Hispanic":0.2226,"Other":0.0415,"White":0.4866},
            "3":{"Asian":0.1292,"Black":0.1846,"Hispanic":0.1815,"Other":0.0462,"White":0.4585},
            "4":{"Asian":0.1171,"Black":0.1832,"Hispanic":0.2072,"Other":0.033, "White":0.4595},
            "5":{"Asian":0.0862,"Black":0.1753,"Hispanic":0.2328,"Other":0.0489,"White":0.4569},
            "6":{"Asian":0.1084,"Black":0.1717,"Hispanic":0.2349,"Other":0.0392,"White":0.4458},
            "7":{"Asian":0.1095,"Black":0.1931,"Hispanic":0.2075,"Other":0.0259,"White":0.464},
            "8":{"Asian":0.1222,"Black":0.1556,"Hispanic":0.2556,"Other":0.05,  "White":0.4167},
            "9":{"Asian":0.1014,"Black":0.1723,"Hispanic":0.2365,"Other":0.0439,"White":0.4459},
            "10":{"Asian":0.0892,"Black":0.1631,"Hispanic":0.2277,"Other":0.0369,"White":0.4831},
            "11":{"Asian":0.0966,"Black":0.1818,"Hispanic":0.179, "Other":0.0284,"White":0.5142},
            "12":{"Asian":0.0801,"Black":0.2017,"Hispanic":0.2541,"Other":0.0276,"White":0.4365},
            "13":{"Asian":0.0862,"Black":0.1446,"Hispanic":0.2185,"Other":0.0369,"White":0.5138},
            "14":{"Asian":0.0958,"Black":0.1856,"Hispanic":0.1976,"Other":0.0359,"White":0.485},
            "15":{"Asian":0.0796,"Black":0.172, "Hispanic":0.2229,"Other":0.035, "White":0.4904},
        },
        "chain_eth": {"Asian":0.0992,"Black":0.1756,"Hispanic":0.2202,"Other":0.0378,"White":0.4672},
        "lbs": {
            "Jackfruit":             {"Asian":8.3333,"Black":1.0,"Hispanic":1.5,"White":0.5},
            "Soursop (Guanábana)":  {"Asian":1.6667,"Black":2.0,"Hispanic":8.0,"White":0.5},
            "Dragonfruit (Pitaya)":  {"Asian":5.6667,"Black":1.5,"Hispanic":3.0,"White":1.0},
            "Starfruit (Carambola)": {"Asian":4.6667,"Black":1.0,"Hispanic":1.5,"White":0.5},
            "Tomatillos":            {"Asian":0.5,   "Black":1.0,"Hispanic":12.0,"White":2.0},
            "Prickly Pear":          {"Asian":0.3333,"Black":1.0,"Hispanic":6.0,"White":1.0},
            "Lychee":                {"Asian":6.6667,"Black":1.0,"Hispanic":1.5,"White":0.5},
            "Sitafal (Sugar Apple)": {"Asian":4.8333,"Black":0.5,"Hispanic":0.5,"White":0.2},
        },
        "consumer_index": {
            "Jackfruit":             {"Asian":443.3,"Black":90,"Hispanic":110,"White":60},
            "Soursop (Guanábana)":  {"Asian":116.7,"Black":180,"Hispanic":500,"White":40},
            "Dragonfruit (Pitaya)":  {"Asian":290.0,"Black":90, "Hispanic":180,"White":80},
            "Starfruit (Carambola)": {"Asian":300.0,"Black":80, "Hispanic":120,"White":60},
            "Tomatillos":            {"Asian":23.3, "Black":40, "Hispanic":700,"White":90},
            "Prickly Pear":          {"Asian":30.0, "Black":60, "Hispanic":450,"White":70},
            "Lychee":                {"Asian":400.0,"Black":70, "Hispanic":100,"White":60},
            "Sitafal (Sugar Apple)": {"Asian":313.3,"Black":50, "Hispanic":60, "White":20},
        },
        "novelty_discount": {
            "Jackfruit":0.1,"Soursop (Guanábana)":0.08,"Dragonfruit (Pitaya)":0.25,
            "Starfruit (Carambola)":0.1,"Tomatillos":0.2,"Prickly Pear":0.12,
            "Lychee":0.15,"Sitafal (Sugar Apple)":0.07,
        },
        "comp_baseline": {
            "Jackfruit":0.916,"Soursop (Guanábana)":1.188,"Dragonfruit (Pitaya)":0.916,
            "Starfruit (Carambola)":1.188,"Tomatillos":1.163,"Prickly Pear":1.163,
            "Lychee":0.916,"Sitafal (Sugar Apple)":1.188,
        },
    }
    return data, backend


DATA, BACKEND = load_data()
WEEKLY_LOYALTY    = BACKEND.get("weekly_loyalty_customers", {})
OBSERVED_RETAIL   = BACKEND.get("observed_retail_prices", {})
FRUITS      = list(DATA["lbs"].keys())
ETHNICITIES = ["Asian", "Black", "Hispanic", "White"]
ETH_COLORS  = {"Asian":"#7c3aed","Black":"#0ea5e9","Hispanic":"#f59e0b","White":"#94a3b8","Other":"#6b7280"}


# ══════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/3/38/Jewel-Osco_logo.svg/320px-Jewel-Osco_logo.svg.png", width=140)
    st.title("🍎 Fruit Recommender")
    st.caption("Jewel-Osco Non-Traditional Fruit Opportunity Tool")
    st.markdown(
        "This tool helps store managers identify which specialty fruits to stock "
        "based on the ethnic demographics of their location and estimated financial returns.\n\n"
        "**What's in each tab:**\n"
        "- 🏆 **Recommendations** — Top 5 fruits ranked for this store, with demographic context and seasonality\n"
        "- 💰 **Financial Feasibility** — Cost, margin, and revenue estimates for all 8 candidate fruits\n"
        "- 🔬 **Analyst** — Adjust scoring weights, pricing assumptions, and capture rate\n"
        "- 💬 **Ask the Recommender** — Ask questions about this store's data in plain English"
    )
    st.divider()

    store_names = {s["id"]: s["city"] for s in DATA["stores"]}
    selected_city = st.selectbox("Select Store", list(store_names.values()))
    current_store = next(s["id"] for s in DATA["stores"] if s["city"] == selected_city)

    st.divider()
    st.subheader("🤖 Claude API")
    st.caption("Powers the free-form chatbot. [Get a key ↗](https://console.anthropic.com)")
    _claude_default = st.secrets.get("ANTHROPIC_API_KEY", "")
    claude_api_key = st.text_input("Anthropic API Key", type="password",
                                    value=_claude_default, placeholder="sk-ant-…")

    st.divider()
    st.subheader("🔑 USDA API Key")
    st.caption("Pre-loaded from app secrets. Override below if needed.")
    _usda_default = st.secrets.get("USDA_API_KEY", "")
    usda_key = st.text_input("My Market News API Key", type="password",
                              value=_usda_default,
                              placeholder="Paste your key here…")

    st.divider()
    st.subheader("🏪 Kroger / Mariano's API")
    st.caption("Pulls live Chicago Mariano's retail prices as competitor baseline. "
               "[Register free ↗](https://developer.kroger.com)")
    _kroger_id_default     = st.secrets.get("KROGER_CLIENT_ID", "")
    _kroger_secret_default = st.secrets.get("KROGER_CLIENT_SECRET", "")
    kroger_id     = st.text_input("Kroger Client ID",     type="password",
                                   value=_kroger_id_default,     placeholder="client_id…")
    kroger_secret = st.text_input("Kroger Client Secret", type="password",
                                   value=_kroger_secret_default, placeholder="client_secret…")


# ══════════════════════════════════════════════════════════════
# ANALYST DEFAULTS — read from session_state (Analyst tab writes these)
# ══════════════════════════════════════════════════════════════
w_share            = st.session_state.get("w_share", 1.0)
w_vol              = st.session_state.get("w_vol", 1.0)
w_aff              = st.session_state.get("w_aff", 1.0)
markup_pct         = st.session_state.get("markup_pct", 45)
positioning_pct    = st.session_state.get("positioning_pct", 0)
freight_multiplier = st.session_state.get("freight_multiplier", 1.0)
capture_pct        = st.session_state.get("capture_pct", 15)

# ══════════════════════════════════════════════════════════════
# COMPUTE SCORES
# ══════════════════════════════════════════════════════════════
scores    = compute_scores(current_store, DATA, w_share, w_vol, w_aff)
ranked    = top_n(scores, len(FRUITS))
top5      = ranked[:5]
sid       = str(current_store)
share     = DATA["eth_share"][sid]
spend     = BACKEND["eth_fruit_spend"][sid]
store_observed = OBSERVED_RETAIL.get(sid, {})   # {fruit: avg_retail_price} for this store

def get_observed(fruit: str) -> float | None:
    """Return the loyalty-data observed retail price for this store/fruit, or None."""
    return store_observed.get(fruit)


# ══════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════
st.header(f"🏪 {selected_city} Store", divider="green")


# ══════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════
tab_recs, tab_finance, tab_analyst, tab_chat = st.tabs([
    "🏆 Recommendations", "💰 Financial Feasibility", "🔬 Analyst", "💬 Ask the Recommender"
])


# ──────────────────────────────────────────────────────────────
# TAB 1: RECOMMENDATIONS
# ──────────────────────────────────────────────────────────────
with tab_recs:
    st.caption(
        "Which specialty fruits are the best fit for this store? "
        "Rankings are based on who shops here and how much each demographic typically buys. "
        "Use the **Analyst** tab to adjust the assumptions behind these rankings."
    )
    st.divider()

    # ── Section 1: Top 5 Recommendations ─────────────────────
    st.subheader(f"🏆 Top 5 Recommendations — {selected_city}")

    with st.expander("ℹ️ What do the labels mean?", expanded=False):
        st.markdown(
            "**Appeal badges** describe how many different shopper groups buy this fruit in meaningful volume:\n\n"
            "- 🎯 **Targeted Pick** — strong fit for one specific shopper group at this store. "
            "Not a weakness — if that group is well-represented here, this can be a high-confidence add.\n"
            "- 📊 **Crossover Pick** — two distinct shopper groups buy this fruit regularly. "
            "Broader shelf justification and lower demand risk.\n"
            "- 🌐 **Community Staple** — three or more shopper groups buy it in solid volume. "
            "Best candidate for a permanent fixture rather than a seasonal test.\n\n"
            "**Opportunity tiers** are based on how well this store's shopper mix matches the fruit's buyer profile, "
            "indexed against the chain average (100 = average store):\n\n"
            "- 🟢 **High opportunity** — this store over-indexes significantly. Strong case to stock.\n"
            "- 🟡 **Medium opportunity** — reasonable fit, worth a small-footprint trial.\n"
            "- 🔴 **Lower opportunity** — below chain average. Consider only if shelf space allows."
        )

    def _opp_tier(score):
        if score >= 110: return "🟢 High opportunity"
        if score >= 90:  return "🟡 Medium opportunity"
        return "🔴 Low opportunity"

    def _appeal_label(fruit):
        """Count how many demographics buy ≥1.5 lbs/yr to gauge breadth."""
        lbs = DATA["lbs"][fruit]
        count = sum(1 for e in ETHNICITIES if lbs.get(e, 0) >= 1.5)
        if count >= 3: return "🌐 Community Staple"
        if count >= 2: return "📊 Crossover Pick"
        return "🎯 Targeted Pick"

    def _quick_fin(fruit):
        """Quick estimate using fallback costs + 45% markup. No API calls."""
        fb = FALLBACK_COSTS[fruit]
        return financial_metrics(fruit, fb["low"], fb["high"], 45)

    _chain_eth = DATA["chain_eth"]

    for i, (fruit, score) in enumerate(top5):
        insight = BACKEND["insights"][sid].get(fruit, "")
        desc    = BACKEND["descriptions"].get(fruit, "")
        lbs     = DATA["lbs"][fruit]
        qfm     = _quick_fin(fruit)
        badge   = _appeal_label(fruit)

        # Sort demographics by demand potential at this store (store_share × lbs)
        drivers = sorted(
            [(e, share.get(e, 0) * 100, lbs.get(e, 0)) for e in ETHNICITIES],
            key=lambda x: (x[1] / 100) * x[2],
            reverse=True,
        )

        with st.container():
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(f"**#{i+1} — {fruit}** &nbsp;&nbsp; `{badge}`")
                st.caption(desc)
                if insight:
                    st.info(insight, icon="💡")
                sub_s, sub_f = st.columns(2)
                sub_s.caption(f"🗓 **Timing:** {SEASONALITY.get(fruit, '—')}")
                sub_f.caption(
                    f"💰 **Est. retail ~${qfm['retail_price']:.2f} · ~{qfm['gross_margin_pct']:.0f}% margin** "
                    f"(fallback estimate — see Financial tab for full analysis)"
                )
            with c2:
                st.markdown(f"**{_opp_tier(score)}**")
                st.markdown("**👥 Who drives demand:**")
                for eth, store_pct, eth_lbs in drivers:
                    if eth_lbs >= 0.3:
                        chain_pct = _chain_eth.get(eth, 0) * 100
                        diff = store_pct - chain_pct
                        arrow = "↑" if diff > 1 else ("↓" if diff < -1 else "→")
                        st.caption(f"{eth}: {store_pct:.1f}% {arrow} · {eth_lbs:.1f} lbs/yr")
            st.divider()

    st.divider()

    # ── Section 2: Store Demographics ────────────────────────
    st.subheader("👥 Store Demographics")
    col_left, col_right = st.columns(2)

    with col_left:
        st.caption("Shopper share vs chain average")
        chain     = DATA["chain_eth"]
        eth_order = ["Hispanic", "White", "Black", "Asian", "Other"]

        fig_demo = go.Figure()
        fig_demo.add_trace(go.Bar(
            name="This Store", y=eth_order,
            x=[share.get(e, 0) * 100 for e in eth_order],
            orientation="h", marker_color="#2d7a3a",
        ))
        fig_demo.add_trace(go.Bar(
            name="Chain Avg", y=eth_order,
            x=[chain.get(e, 0) * 100 for e in eth_order],
            orientation="h", marker_color="#94a3b8",
        ))
        fig_demo.update_layout(
            barmode="group", height=280, margin=dict(l=0, r=0, t=10, b=0),
            xaxis_title="% of shoppers", legend=dict(orientation="h", y=1.12),
        )
        st.plotly_chart(fig_demo, use_container_width=True)

        diff_rows = []
        for eth in eth_order:
            sp = share.get(eth, 0) * 100
            cp = chain.get(eth, 0) * 100
            diff_rows.append({"Ethnicity": eth, "Store %": f"{sp:.1f}%",
                               "Chain %": f"{cp:.1f}%", "Diff": f"{sp-cp:+.1f}pp"})
        st.dataframe(pd.DataFrame(diff_rows).set_index("Ethnicity"), use_container_width=True)

    with col_right:
        st.caption("Fruit spend share (% of basket)")
        spend_eths = ["Asian", "Hispanic", "White", "Black"]
        fig_spend = go.Figure(go.Bar(
            x=[spend.get(e, 0) for e in spend_eths], y=spend_eths,
            orientation="h", marker_color="#d97706",
            text=[f"{spend.get(e,0):.2f}%" for e in spend_eths],
            textposition="outside",
        ))
        fig_spend.update_layout(
            height=280, margin=dict(l=0, r=60, t=10, b=0),
            xaxis=dict(title="% of basket", range=[0, 13]),
        )
        st.plotly_chart(fig_spend, use_container_width=True)
        st.info(
            f"Overall store average: **{spend['Overall']:.2f}%** of basket on fruit  \n"
            f"Chain range: 7.76% – 8.26%  \n"
            f"Asian shoppers spend the most on fruit at this store ({spend['Asian']:.2f}%)."
        )

    st.divider()

    # ── Section 3: Candidate Fruits ──────────────────────────
    st.subheader("🍎 Candidate Fruits")
    st.caption("Annual lbs consumed per customer by ethnicity — estimated from loyalty data. Filter to sort by demographic.")

    sel_eth = st.radio("Sort by demographic", ETHNICITIES, horizontal=True, key="recs_eth_filter")
    lbs_ranked = sorted(FRUITS, key=lambda f: DATA["lbs"][f].get(sel_eth, 0), reverse=True)

    for fruit in lbs_ranked:
        lbs  = DATA["lbs"][fruit]
        sc   = scores[fruit]
        desc = BACKEND["descriptions"].get(fruit, "")
        with st.expander(
            f"{score_color(sc)} **{fruit}** — {lbs.get(sel_eth, 0):.1f} lbs/yr ({sel_eth}) · {_opp_tier(sc)}",
            expanded=False,
        ):
            c1, c2 = st.columns([2, 1])
            with c1:
                fig_lbs = go.Figure(go.Bar(
                    x=ETHNICITIES,
                    y=[lbs.get(e, 0) for e in ETHNICITIES],
                    marker_color=[ETH_COLORS[e] for e in ETHNICITIES],
                    text=[f"{lbs.get(e,0):.1f}" for e in ETHNICITIES],
                    textposition="outside",
                ))
                fig_lbs.update_layout(
                    height=220, margin=dict(l=0, r=0, t=10, b=0),
                    yaxis_title="Lbs/yr per customer", showlegend=False,
                )
                st.plotly_chart(fig_lbs, use_container_width=True)
            with c2:
                st.write(desc)
                st.caption(f"**Seasonality:** {SEASONALITY.get(fruit, '—')}")
                st.markdown(f"**{_opp_tier(sc)}**")


# ──────────────────────────────────────────────────────────────
# TAB 4: FINANCIAL FEASIBILITY
# ──────────────────────────────────────────────────────────────
with tab_finance:
    st.caption(
        "Estimated costs, pricing, and revenue for each fruit at this store. "
        "Wholesale prices come from USDA market data where available, with hypothetical estimates as a fallback. "
        "Retail pricing uses Mariano's Chicago as a competitor baseline. "
        "To adjust markup, freight, or capture rate assumptions, go to the **Analyst** tab."
    )
    st.divider()
    st.subheader("💰 Financial Feasibility")

    # ── Fetch competitor prices ───────────────────────────────
    if kroger_id and kroger_secret:
        with st.spinner("Fetching Chicago Mariano's prices…"):
            comp_prices, comp_error = get_competitor_prices(kroger_id, kroger_secret)
        if comp_error:
            st.warning(f"⚠️ Kroger API: {comp_error}")
            comp_prices = {}
        elif comp_prices:
            n_found = len(comp_prices)
            st.success(f"✅ Mariano's prices loaded for {n_found}/8 fruits.")
    else:
        comp_prices = {}
        st.info("🏪 Add Kroger credentials in the sidebar to load competitor pricing as retail baseline.")

    loyalty_default  = int(WEEKLY_LOYALTY.get(sid, 150))
    num_customers    = st.session_state.get(f"num_customers_{sid}", loyalty_default)
    annual_customers = num_customers * 52

    # Fetch prices
    if usda_key:
        with st.spinner("Fetching latest USDA Chicago terminal prices…"):
            prices, api_error = get_wholesale_prices(usda_key)
        if api_error:
            st.warning(f"⚠️ USDA API issue: {api_error}. Showing hypothetical costs.")
        else:
            st.success("✅ Live USDA Chicago Terminal Market prices loaded.")
    else:
        prices = {f: {**fb, "source": "Hypothetical estimate", "date": "", "package": "", "origin": ""}
                  for f, fb in FALLBACK_COSTS.items()}
        st.info("🔑 Enter your USDA API key in the sidebar to load live wholesale prices. "
                "Showing hypothetical estimates for now.")

    def resolve_retail(fruit: str, fm_effective_cost: float) -> tuple[float | None, str]:
        """
        Returns (observed_retail, retail_source_label).
        Priority: 1) Mariano's competitor price ± positioning, 2) loyalty observed, 3) None (markup).
        """
        if fruit in comp_prices:
            base = comp_prices[fruit]["avg"]
            retail = round(base * (1 + positioning_pct / 100), 2)
            label = f"Mariano's avg ${base:.2f} {positioning_pct:+d}%"
            return retail, label
        obs = get_observed(fruit)
        if obs:
            return obs, "Jewel avg (loyalty data)"
        return None, f"Est. {markup_pct}% markup"

    # ── At a Glance ──────────────────────────────────────────
    st.divider()
    st.subheader("🔍 At a Glance")
    glance_fruit = st.selectbox(
        "Select a fruit to inspect",
        [f for f, _ in ranked],
        format_func=lambda f: f"{f}  (#{[x[0] for x in ranked].index(f)+1} ranked)",
        key="glance_fruit",
    )
    gp    = prices.get(glance_fruit, {})
    gws_l = gp.get("low",  FALLBACK_COSTS[glance_fruit]["low"])
    gws_h = gp.get("high", FALLBACK_COSTS[glance_fruit]["high"])
    _gfm_pre = financial_metrics(glance_fruit, gws_l, gws_h, markup_pct,
                                  freight_multiplier=freight_multiplier)
    g_retail, g_retail_label = resolve_retail(glance_fruit, _gfm_pre["effective_cost"])
    gfm   = financial_metrics(glance_fruit, gws_l, gws_h, markup_pct,
                               freight_multiplier=freight_multiplier, observed_retail=g_retail)
    gfc          = FREIGHT_COSTS.get(glance_fruit, {})
    gwlbs        = sum(share.get(eth, 0) * DATA["lbs"][glance_fruit].get(eth, 0) for eth in ETHNICITIES)
    glbs_ordered = gwlbs * (capture_pct / 100) * annual_customers
    glbs         = glbs_ordered * (1 - gfm["shrink_pct"] / 100)   # shrink-adjusted sellable units
    grev         = glbs * gfm["retail_price"]
    gcost        = glbs * gfm["effective_cost"]
    gsrc  = gp.get("source", "Hypothetical estimate")
    gdate = gp.get("date", "")

    retail_label = "Retail Price"
    retail_delta = g_retail_label + f"  ·  implied {gfm['implied_markup']:.0f}% markup"

    g1, g2, g3, g4, g5, g6 = st.columns(6)
    g1.metric("Wholesale",    f"${gfm['wholesale_mid']:.2f}/unit", f"Range ${gws_l:.2f}–${gws_h:.2f}")
    g2.metric("Freight",      f"${gfm['freight_mid']:.2f}/unit",   gfc.get("port", ""))
    g3.metric("Landed Cost",  f"${gfm['landed_cost']:.2f}/unit",
              f"after {gfm['shrink_pct']:.0f}% shrink → ${gfm['effective_cost']:.2f} effective")
    g4.metric(retail_label,   f"${gfm['retail_price']:.2f}/unit",  retail_delta)
    g5.metric("Gross Margin", f"{gfm['gross_margin_pct']:.1f}%",
              f"${gfm['retail_price'] - gfm['effective_cost']:.2f}/unit")
    g6.metric("Est. Annual Revenue", f"${grev:,.0f}", f"Net ${grev - gcost:,.0f} after COGS")

    st.caption(
        f"Freight: {gfc.get('origin','—')} via {gfc.get('port','—')}  ·  {gfc.get('note','')}  \n"
        f"Price source: **{gsrc}**" + (f" · as of {gdate}" if gdate else "") +
        f"  ·  {capture_pct}% capture × {gwlbs:.2f} wtd lbs/customer/yr × {annual_customers:,} annual customers "
        f"= {glbs_ordered:,.0f} lbs ordered → {glbs:,.0f} lbs sold after {gfm['shrink_pct']:.0f}% shrink"
    )

    st.divider()

    # ── Build all rows (one pass, reused by both tables) ─────
    rows = []
    summary_rows = []
    for fruit, score in ranked:
        p = prices.get(fruit, {})
        ws_low  = p.get("low",  FALLBACK_COSTS[fruit]["low"])
        ws_high = p.get("high", FALLBACK_COSTS[fruit]["high"])
        _fm_pre = financial_metrics(fruit, ws_low, ws_high, markup_pct, freight_multiplier=freight_multiplier)
        t_retail, t_retail_label = resolve_retail(fruit, _fm_pre["effective_cost"])
        fm = financial_metrics(fruit, ws_low, ws_high, markup_pct, freight_multiplier=freight_multiplier, observed_retail=t_retail)
        weighted_lbs    = sum(share.get(eth, 0) * DATA["lbs"][fruit].get(eth, 0) for eth in ETHNICITIES)
        est_lbs_ordered = weighted_lbs * (capture_pct / 100) * annual_customers
        est_lbs_sold    = est_lbs_ordered * (1 - fm["shrink_pct"] / 100)
        est_revenue     = est_lbs_sold * fm["retail_price"]
        fc = FREIGHT_COSTS.get(fruit, {})

        # Raw numeric row for summary tables
        summary_rows.append({
            "Fruit":             fruit,
            "_revenue":          est_revenue,
            "_margin":           fm["gross_margin_pct"],
            "Est. Retail":       f"${fm['retail_price']:.2f}",
            "Gross Margin":      f"{fm['gross_margin_pct']:.1f}%",
            "Est. Annual Revenue": f"${est_revenue:,.0f}",
            "Price Source":      t_retail_label,
        })

        # Formatted row for full detail table
        rows.append({
            "Fruit":               fruit,
            "Opp. Score":          score,
            "Wholesale (mid)":     f"${fm['wholesale_mid']:.2f}",
            "Freight (mid)":       f"${fm['freight_mid']:.2f}",
            "Landed Cost":         f"${fm['landed_cost']:.2f}",
            "Shrink":              f"{fm['shrink_pct']:.0f}%",
            "Effective Cost":      f"${fm['effective_cost']:.2f}",
            "Retail Price":        f"${fm['retail_price']:.2f} ({t_retail_label})",
            "Gross Margin":        f"{fm['gross_margin_pct']:.1f}%",
            "Wtd lbs/customer/yr": f"{weighted_lbs:.2f}",
            f"Est. lbs ordered ({capture_pct}%)": f"{est_lbs_ordered:,.0f}",
            f"Est. lbs sold (after shrink)": f"{est_lbs_sold:,.0f}",
            "Est. Annual Revenue": f"${est_revenue:,.0f}",
            "Freight Origin":      fc.get("origin", "—"),
            "Entry Port":          fc.get("port", "—"),
            "WS Source":           p.get("source", "—"),
        })

    # ── Full detail table ─────────────────────────────────────
    st.subheader("📋 Full Cost & Revenue Breakdown")
    df_fin = pd.DataFrame(rows).set_index("Fruit")
    st.dataframe(df_fin, use_container_width=True)
    st.caption(
        f"Lbs ordered = wtd lbs/customer/yr × {capture_pct}% capture × {annual_customers:,} annual customers. "
        f"Lbs sold = lbs ordered × (1 − shrink%)."
    )

    st.divider()
    st.subheader("Detailed View — Top 5 Fruits")

    for i, (fruit, score) in enumerate(top5):
        p = prices.get(fruit, {})
        ws_low  = p.get("low",  FALLBACK_COSTS[fruit]["low"])
        ws_high = p.get("high", FALLBACK_COSTS[fruit]["high"])
        _fm_pre_d       = financial_metrics(fruit, ws_low, ws_high, markup_pct, freight_multiplier=freight_multiplier)
        d_retail, d_retail_label = resolve_retail(fruit, _fm_pre_d["effective_cost"])
        fm = financial_metrics(fruit, ws_low, ws_high, markup_pct, freight_multiplier=freight_multiplier, observed_retail=d_retail)
        src = p.get("source", "—")
        pkg = p.get("package", "")
        orig= p.get("origin",  "")
        date= p.get("date",    "")

        weighted_lbs_d    = sum(share.get(eth, 0) * DATA["lbs"][fruit].get(eth, 0) for eth in ETHNICITIES)
        est_lbs_ordered_d = weighted_lbs_d * (capture_pct / 100) * annual_customers
        est_lbs_d         = est_lbs_ordered_d * (1 - fm["shrink_pct"] / 100)   # shrink-adjusted sellable units
        est_rev_d         = est_lbs_d * fm["retail_price"]

        dfc = FREIGHT_COSTS.get(fruit, {})
        with st.expander(f"**#{i+1} {fruit}** — Score {score} · Est. revenue ${est_rev_d:,.0f}/yr"):
            mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
            mc1.metric("Wholesale",   f"${fm['wholesale_mid']:.2f}", pkg or None)
            mc2.metric("Freight",     f"${fm['freight_mid']:.2f}",   dfc.get("port", ""))
            mc3.metric("Landed Cost", f"${fm['landed_cost']:.2f}",   f"→ ${fm['effective_cost']:.2f} after {fm['shrink_pct']:.0f}% shrink")
            mc4.metric("Est. Retail", f"${fm['retail_price']:.2f}",  f"@ {markup_pct}% markup")
            mc5.metric("Gross Margin",f"{fm['gross_margin_pct']:.1f}%", f"${fm['retail_price']-fm['effective_cost']:.2f}/unit")
            mc6.metric("Est. Revenue",f"${est_rev_d:,.0f}",
                       f"{est_lbs_d:,.0f} lbs sold ({est_lbs_ordered_d:,.0f} ordered − {fm['shrink_pct']:.0f}% shrink)")

            if orig or date:
                st.caption(f"Source: {src}" + (f" · Origin: {orig}" if orig else "") +
                           (f" · As of: {date}" if date else ""))
            else:
                st.caption(f"Source: {src}")

            st.info(SEASONALITY.get(fruit, ""), icon="🗓️")

            shrink_override = st.slider(
                f"Adjust shrink for {fruit.split('(')[0].strip()}",
                0.0, 0.25, SHRINK_RATES.get(fruit, 0.08), 0.01,
                format="%.0f%%", key=f"shrink_{fruit}",
            ) if st.checkbox("Override shrink rate", key=f"shrink_cb_{fruit}") else None

            if shrink_override is not None:
                fm2 = financial_metrics(fruit, ws_low, ws_high, markup_pct, shrink_override)
                st.caption(f"With {shrink_override*100:.0f}% shrink → retail ${fm2['retail_price']:.2f}, "
                           f"margin {fm2['gross_margin_pct']:.1f}%")


# ──────────────────────────────────────────────────────────────
# TAB 3: ANALYST
# ──────────────────────────────────────────────────────────────
with tab_analyst:
    st.caption(
        "Adjust the assumptions that drive scores, pricing, and revenue estimates. "
        "Changes here update the Recommendations and Financial tabs in real time."
    )
    st.divider()

    st.subheader("⚙️ Scoring Weights")
    st.caption("Control how much each factor influences the opportunity score. 1.0 is the default — increase to emphasize that factor.")
    a1, a2, a3 = st.columns(3)
    with a1:
        st.slider("Shopper Share", 0.5, 2.0, 1.0, 0.1, key="w_share",
                  help="Weight on how well this store's demographic mix matches the fruit's buyer profile.")
    with a2:
        st.slider("Volume Potential", 0.5, 2.0, 1.0, 0.1, key="w_vol",
                  help="Weight on estimated purchase volume, adjusted for novelty and comparability.")
    with a3:
        st.slider("Ethnic Affinity", 0.5, 2.0, 1.0, 0.1, key="w_aff",
                  help="Weight on how strongly each demographic skews toward this fruit vs. average.")
    if st.button("↺ Reset to defaults", key="reset_weights"):
        for k in ["w_share", "w_vol", "w_aff"]:
            st.session_state[k] = 1.0
        st.rerun()

    st.divider()
    st.subheader("💰 Pricing & Cost Assumptions")
    b1, b2, b3 = st.columns(3)
    with b1:
        st.slider("Price vs. Mariano's (%)", -20, 20, 0, 1, key="positioning_pct",
                  help="0% = match competitor price. Positive = price above market. Negative = undercut.")
        st.number_input("Fallback Markup %", min_value=10, max_value=100, value=45, step=5,
                        key="markup_pct",
                        help="Used when no competitor or loyalty price is available.")
    with b2:
        st.slider("Freight Multiplier", 0.5, 2.0, 1.0, 0.1, key="freight_multiplier",
                  help="Scale freight estimates up or down. 1.0 = baseline. Increase during peak season.")
    with b3:
        loyalty_default_a = int(WEEKLY_LOYALTY.get(sid, 150))
        st.number_input("Weekly Customers", min_value=100, max_value=50000,
                        value=loyalty_default_a, step=50,
                        key=f"num_customers_{sid}",
                        help=f"Default from loyalty data: {loyalty_default_a:,}/wk. "
                             "Adjust upward to account for non-loyalty shoppers.")
        st.slider("Capture Rate (%)", 1, 100, 15, 1, key="capture_pct",
                  help="What share of modeled demand you expect to actually sell. "
                       "15% is a reasonable starting point for a new specialty item.")


# ──────────────────────────────────────────────────────────────
# TAB 4: CHATBOT
# ──────────────────────────────────────────────────────────────

# Fruit / demographic patterns
FRUIT_PATTERNS = [
    (re.compile(r"jackfruit",           re.I), "Jackfruit"),
    (re.compile(r"soursop|guan[aá]bana",re.I), "Soursop (Guanábana)"),
    (re.compile(r"dragon.?fruit|pitaya",re.I), "Dragonfruit (Pitaya)"),
    (re.compile(r"star.?fruit|carambola",re.I),"Starfruit (Carambola)"),
    (re.compile(r"tomatillo",           re.I), "Tomatillos"),
    (re.compile(r"prickly.?pear",       re.I), "Prickly Pear"),
    (re.compile(r"lychee|litchi",       re.I), "Lychee"),
    (re.compile(r"sitafal|sugar.?apple|custard.?apple", re.I), "Sitafal (Sugar Apple)"),
]
ETH_PATTERNS = [
    (re.compile(r"asian|chinese|korean|japanese|indian|south asian|southeast|vietnamese|filipino|thai", re.I), "Asian"),
    (re.compile(r"hispanic|latin|mexican|spanish|puerto rican|cuban", re.I), "Hispanic"),
    (re.compile(r"black|african",   re.I), "Black"),
    (re.compile(r"white|caucasian|european", re.I), "White"),
]


def parse_fruit(msg: str) -> str | None:
    for pat, name in FRUIT_PATTERNS:
        if pat.search(msg):
            return name
    return None


def parse_eths(msg: str) -> list[str]:
    return [eth for pat, eth in ETH_PATTERNS if pat.search(msg)]


def parse_intent(msg: str) -> str | None:
    m = msg.lower()
    if re.search(r"spend|basket|fruit spend|spending", m): return "spend"
    if re.search(r"overview|summary|about.*(this )?store|store.*(summary|overview|profile)|give me.*store", m): return "overview"
    if re.search(r"rank all|all fruits?|compare all|full (list|rank)|list all|show all", m): return "all_fruits"
    if re.search(r"best store|top store|where.*sell|which store", m): return "best_stores"
    if re.search(r"descri|what is|tell me about|info.*(on|about)|details", m): return "describe"
    if re.search(r"score.*(for|of)|opportunity score|how.*scor", m): return "score"
    if re.search(r"wholesale|price|cost|cheap|expensive", m): return "price"
    if re.search(r"season|available|when.*available|timing", m): return "season"
    if re.search(r"margin|profit|markup|feasib", m): return "margin"
    return None


def generate_response(msg: str) -> str:
    fruit  = parse_fruit(msg)
    eths   = parse_eths(msg)
    intent = parse_intent(msg)
    city   = selected_city

    # ── Spend share ──────────────────────────────────────────
    if intent == "spend":
        lines = "\n".join(
            f"- **{e}**: {spend.get(e,0):.2f}% of basket"
            for e in ["Asian","Hispanic","White","Black"]
        )
        return (f"**Fruit spend share at {city}:**\n\n{lines}\n\n"
                f"Overall store average: **{spend['Overall']:.2f}%**  \n"
                f"Asian shoppers spend the most on fruit across all stores (~10–11%).")

    # ── Store overview ───────────────────────────────────────
    if intent == "overview":
        top_eth = max(ETHNICITIES, key=lambda e: share.get(e, 0))
        top_fruit, top_score = top5[0]
        lines = "\n".join(f"- **{f}**: {s:.1f}" for f,s in ranked[:5])
        return (f"**{city} store overview:**\n\n"
                f"- Largest demographic: **{top_eth}** ({share.get(top_eth,0)*100:.1f}%)\n"
                f"- Overall fruit basket share: **{spend['Overall']:.2f}%**\n"
                f"- Top recommendation: **{top_fruit}** (score {top_score})\n\n"
                f"**Top 5 scores:**\n{lines}")

    # ── All fruits ranked ────────────────────────────────────
    if intent == "all_fruits":
        lines = "\n".join(f"{i+1}. **{f}** — {s:.1f}" for i,(f,s) in enumerate(ranked))
        return f"**All fruits ranked for {city} (100 = chain avg):**\n\n{lines}"

    # ── Wholesale price ──────────────────────────────────────
    if intent == "price" and fruit:
        if usda_key:
            p = prices.get(fruit, {})  # prices from USDA fetch above
            src  = p.get("source","—")
            ws_l = p.get("low",  FALLBACK_COSTS[fruit]["low"])
            ws_h = p.get("high", FALLBACK_COSTS[fruit]["high"])
            pkg  = p.get("package","")
            date = p.get("date","")
        else:
            fb   = FALLBACK_COSTS[fruit]
            ws_l, ws_h, src, pkg, date = fb["low"], fb["high"], "Hypothetical estimate", "", ""
        fm = financial_metrics(fruit, ws_l, ws_h, markup_pct)
        return (f"**Wholesale price — {fruit}:**\n\n"
                f"- Range: **${ws_l:.2f} – ${ws_h:.2f}** {(pkg or '').strip()}\n"
                f"- Est. retail (at {markup_pct}% markup): **${fm['retail_price']:.2f}**\n"
                f"- Gross margin after {fm['shrink_pct']:.1f}% shrink: **{fm['gross_margin_pct']:.1f}%**\n"
                f"- Source: {src}" + (f" · as of {date}" if date else ""))

    # ── Seasonality ──────────────────────────────────────────
    if intent == "season" and fruit:
        return f"**Seasonality — {fruit}:**\n\n{SEASONALITY.get(fruit,'No data available.')}"

    # ── Margin ───────────────────────────────────────────────
    if intent == "margin" and fruit:
        p   = prices.get(fruit, FALLBACK_COSTS[fruit]) if usda_key else FALLBACK_COSTS[fruit]
        ws_l = p.get("low",  FALLBACK_COSTS[fruit]["low"])
        ws_h = p.get("high", FALLBACK_COSTS[fruit]["high"])
        fm  = financial_metrics(fruit, ws_l, ws_h, markup_pct)
        return (f"**Margin estimate — {fruit} at {markup_pct}% markup:**\n\n"
                f"- Wholesale (mid): ${fm['wholesale_mid']:.2f}/unit\n"
                f"- Shrink: {fm['shrink_pct']:.1f}% → effective cost ${fm['effective_cost']:.2f}\n"
                f"- Est. retail: **${fm['retail_price']:.2f}**\n"
                f"- **Gross margin: {fm['gross_margin_pct']:.1f}%**")

    # ── Fruit profile / describe ─────────────────────────────
    if fruit and (intent in ("describe", "score", None)):
        desc    = BACKEND["descriptions"].get(fruit, "")
        sc      = scores[fruit]
        insight = BACKEND["insights"][sid].get(fruit, "")
        lbs_lines = "\n".join(
            f"- **{e}**: {DATA['lbs'][fruit].get(e,0):.1f} lbs/yr"
            for e in ETHNICITIES
        )
        return (f"**{fruit}** (score: **{sc}** — {sc-100:+.1f} vs chain avg)\n\n"
                f"{desc}\n\n"
                f"**Annual lbs consumed per customer:**\n{lbs_lines}\n\n"
                f"💡 {insight}")

    # ── Best stores for a fruit ──────────────────────────────
    if intent == "best_stores" and fruit:
        store_scores = []
        for st_info in DATA["stores"]:
            sh = DATA["eth_share"][str(st_info["id"])]
            raw = sum(sh.get(e,0)*DATA["lbs"][fruit].get(e,0) for e in ETHNICITIES)
            store_scores.append((st_info["city"], st_info["id"], raw))
        chain_avg = sum(r for _,_,r in store_scores) / len(store_scores)
        ranked_stores = sorted(store_scores, key=lambda x: x[2], reverse=True)
        lines = "\n".join(
            f"{i+1}. **{c}** — {round(r/chain_avg*100,1)}" +
            (" ← your store" if sid2==current_store else "")
            for i,(c,sid2,r) in enumerate(ranked_stores[:5])
        )
        return f"**Top 5 stores for {fruit} (score vs chain avg):**\n\n{lines}"

    # ── Demographic targeting ────────────────────────────────
    if eths:
        other_eths = [e for e in ETHNICITIES if e not in eths]
        total_target = sum(share.get(e,0) for e in eths) or 1
        fruit_scores = []
        for f in FRUITS:
            t_score = sum(share.get(e,0)*DATA["lbs"][f].get(e,0) for e in eths) / total_target
            cross   = sum(share.get(e,0)*DATA["lbs"][f].get(e,0) for e in other_eths)
            fruit_scores.append((f, t_score, cross))
        max_t = max(s for _,s,_ in fruit_scores) or 1
        max_c = max(c for _,_,c in fruit_scores) or 1
        combined = sorted(fruit_scores, key=lambda x: 0.6*(x[1]/max_t)+0.4*(x[2]/max_c), reverse=True)
        group = " + ".join(eths)
        pct   = sum(share.get(e,0) for e in eths)*100
        lines = []
        for i,(f,t,c) in enumerate(combined[:5]):
            tlines = " · ".join(f"{e} ({share.get(e,0)*100:.1f}%): ~{DATA['lbs'][f].get(e,0):.1f} lbs/yr"
                                for e in eths)
            cross_eth = max(other_eths, key=lambda e: share.get(e,0)*DATA["lbs"][f].get(e,0))
            cx_lbs    = DATA["lbs"][f].get(cross_eth, 0)
            cx_line   = f"  · {cross_eth} shoppers also buy ~{cx_lbs:.1f} lbs/yr" if cx_lbs>0.3 else ""
            lines.append(f"**#{i+1} {f}**\n  {tlines}{cx_line}")
        return (f"**Top picks for {group} shoppers at {city} ({pct:.1f}% combined):**\n\n"
                + "\n\n".join(lines))

    # ── Fallback ─────────────────────────────────────────────
    return (
        "I didn't catch a specific fruit or demographic. Try:\n\n"
        '- *"How would Dragonfruit do?"*\n'
        '- *"Rank all fruits for this store"*\n'
        '- *"What\'s the fruit spend share here?"*\n'
        '- *"I want to target Asian and Hispanic shoppers"*\n'
        '- *"What\'s the wholesale price of Lychee?"*\n'
        '- *"Give me a store overview"*'
    )


with tab_chat:
    st.caption(
        "Ask questions about this store's data in plain English — "
        "which fruits to stock, how demographics affect recommendations, margins, seasonality, or anything else. "
        "Add your Anthropic API key in the sidebar to unlock AI-powered answers."
    )
    st.divider()
    st.subheader(f"💬 Ask the Recommender — {selected_city}")

    # ── Mode banner ───────────────────────────────────────────
    if claude_api_key:
        st.success(
            "✅ **Claude AI mode** — ask anything about this store's data. "
            "Responses are generated by Claude using your store's loyalty data.",
            icon="🤖",
        )
    else:
        st.info(
            "⚡ **Quick-answer mode** — add your Anthropic API key in the sidebar "
            "to unlock free-form AI answers. Currently using pattern-matched responses.",
            icon="ℹ️",
        )

    # ── Build Claude context (once per store selection) ───────
    if claude_api_key:
        _loyalty_default = int(WEEKLY_LOYALTY.get(sid, 150))
        _system_prompt = build_system_prompt(
            store_id=current_store,
            selected_city=selected_city,
            data=DATA,
            backend=BACKEND,
            scores=scores,
            ranked=ranked,
            top5=top5,
            weekly_loyalty=_loyalty_default,
            fallback_costs=FALLBACK_COSTS,
            freight_costs=FREIGHT_COSTS,
            shrink_rates=SHRINK_RATES,
            seasonality=SEASONALITY,
            financial_metrics_fn=financial_metrics,
        )

    if "messages" not in st.session_state:
        st.session_state.messages = []

    # ── Suggestion chips ──────────────────────────────────────
    suggestions = [
        "Give me a store overview",
        "What's the fruit spend share here?",
        "How would Dragonfruit do here?",
        "Which fruit has the best margin?",
        "What should I pitch to Hispanic shoppers?",
        "Compare Lychee vs Jackfruit for this store",
    ]
    cols = st.columns(3)
    for i, sug in enumerate(suggestions):
        if cols[i % 3].button(sug, use_container_width=True, key=f"sug_{i}"):
            st.session_state.messages.append({"role": "user", "content": sug})
            if claude_api_key:
                # Collect full streamed response synchronously for history
                full = "".join(stream_claude_response(
                    [{"role": "user", "content": sug}],
                    _system_prompt, claude_api_key,
                ))
            else:
                full = generate_response(sug)
            st.session_state.messages.append({"role": "assistant", "content": full})
            st.rerun()

    st.divider()

    # ── Render history ────────────────────────────────────────
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # ── Input ─────────────────────────────────────────────────
    if prompt := st.chat_input("Ask about fruits, demographics, prices, margins…"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        if claude_api_key:
            # Pass full history (excluding latest; it's already appended above)
            api_messages = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.messages
            ]
            with st.chat_message("assistant"):
                response = st.write_stream(
                    stream_claude_response(api_messages, _system_prompt, claude_api_key)
                )
        else:
            response = generate_response(prompt)
            with st.chat_message("assistant"):
                st.markdown(response)

        st.session_state.messages.append({"role": "assistant", "content": response})

    if st.button("🗑️ Clear chat", key="clear_chat"):
        st.session_state.messages = []
        st.rerun()
