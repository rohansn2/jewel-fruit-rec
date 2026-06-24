"""
Claude API chatbot for the Jewel-Osco Fruit Recommender.

Builds a rich store-specific context from the loyalty data and injects it into
every conversation so Claude can answer free-form questions from store managers.

Model: claude-haiku-4-5-20251001 (fast, low-cost, fits the chatbot use-case)
Auth:  ANTHROPIC_API_KEY in .streamlit/secrets.toml
"""

import anthropic
from datetime import date

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

ETHNICITIES = ["Asian", "Black", "Hispanic", "White"]

# ──────────────────────────────────────────────────────────────
# Context builder
# ──────────────────────────────────────────────────────────────

def build_system_prompt(
    store_id: int,
    selected_city: str,
    data: dict,
    backend: dict,
    scores: dict,
    ranked: list,
    top5: list,
    weekly_loyalty: int,
    fallback_costs: dict,
    freight_costs: dict,
    shrink_rates: dict,
    seasonality: dict,
    financial_metrics_fn,
) -> str:
    """
    Serialize all store-level data into a structured system prompt so Claude
    can answer any question a store manager might ask.
    """
    sid       = str(store_id)
    share     = data["eth_share"][sid]
    chain     = data["chain_eth"]
    spend     = backend["eth_fruit_spend"][sid]
    lbs_data  = data["lbs"]
    descs     = backend.get("descriptions", {})
    insights  = backend.get("insights", {}).get(sid, {})
    today     = date.today().strftime("%B %d, %Y")   # e.g. "June 24, 2026"

    lines = []

    # ── Role & guidelines ─────────────────────────────────────
    lines.append(f"""\
You are a fruit assortment advisor embedded in a seasonal assortment builder for Jewel-Osco.

You help store managers make data-driven decisions based on the ethnic demographics of the \
selected store about stocking a selection from a list of pre-determined specialty fruits. \
Questions may include topics like: ethnic breakdown of a store, fruit spend share, and what \
fruits should be carried to target a determined mix of ethnic groups. All of this data is \
provided below from the Fruit_store_backend table.

Today's date is {today}. Use this to determine whether a fruit is currently in season based \
on the seasonality data provided.

You are currently advising on the **{selected_city}** store. Always refer to this store by \
name in your answers — never just "this store."

## Guidelines

- **Be concise.** Store managers are busy. Lead with a 1–2 sentence qualitative answer, \
then back it up with a few key figures. Don't recite the full dataset.
- **When comparing fruits or presenting an assortment**, structure your answer as a short \
table or ranked list. Limit to the top 3 most relevant options unless explicitly asked for more.
- **If asked about a fruit not in the dataset**, say so in one sentence and redirect to the \
8 candidate fruits listed below.
- **Tone must be practical and direct.** Avoid academic language like "it is worth noting" \
or "one could argue."
- **When recommending a fruit**, always mention: opportunity score, the demographic that \
drives the most volume (by lbs/yr), estimated margin, and whether it is currently in season. \
Base demographic targeting on lbs/yr and store shopper share — not on any index scores.
- **Flag high-shrink fruits (≥20% shrink rate)** whenever recommending them for a new \
stocking decision. Note the shrink rate and its impact on effective cost.
- **Caveat financial figures.** Cost and margin estimates are based on hypothetical wholesale \
costs unless otherwise noted. Do not present them as guaranteed.
- **End every recommendation** with a single bolded bottom line: the one thing the manager \
should do or remember.
- **If a question falls outside** store demographics, fruit data, or financial feasibility \
for the 8 candidate fruits, say so in one sentence and redirect.\
""")

    # ── Store profile ─────────────────────────────────────────
    top_eth   = max(ETHNICITIES, key=lambda e: share.get(e, 0))
    top_pct   = share.get(top_eth, 0) * 100
    chain_pct = chain.get(top_eth, 0) * 100

    lines.append(f"\n## Store Profile: {selected_city} (Store #{store_id})")
    lines.append(f"- Weekly loyalty customers: {weekly_loyalty:,}")
    lines.append(f"- Largest demographic: {top_eth} ({top_pct:.1f}% of shoppers, "
                 f"{top_pct - chain_pct:+.1f}pp vs chain avg)")
    lines.append(f"- Overall fruit basket share: {spend.get('Overall', 0):.2f}% of total grocery spend")

    # ── Demographics table ────────────────────────────────────
    lines.append("\n## Shopper Demographics vs Chain Average")
    lines.append("| Demographic | This Store | Chain Avg | Difference |")
    lines.append("|-------------|-----------|-----------|------------|")
    for eth in ETHNICITIES:
        sp = share.get(eth, 0) * 100
        cp = chain.get(eth, 0) * 100
        lines.append(f"| {eth} | {sp:.1f}% | {cp:.1f}% | {sp - cp:+.1f}pp |")

    # ── Fruit spend share ─────────────────────────────────────
    lines.append("\n## Fruit Spend Share (% of grocery basket by demographic)")
    for eth in ["Asian", "Hispanic", "White", "Black", "Overall"]:
        lines.append(f"- {eth}: {spend.get(eth, 0):.2f}%")

    # ── Per-fruit data ────────────────────────────────────────
    lines.append("\n## Candidate Fruit Data (all 8 fruits)")
    lines.append(
        "Opportunity score: indexed to 100 = chain average. "
        "A score above 100 means this store is a stronger-than-average fit for that fruit. "
        "lbs/yr = estimated annual consumption per loyalty customer, derived from transaction data. "
        "Use opportunity score and lbs/yr as the primary signals for recommendations. "
        "Do not reference or infer any consumer index (CI) values — they are not reliable."
    )

    for fruit in lbs_data:
        sc   = scores.get(fruit, 100)
        lbs  = lbs_data[fruit]
        fb   = fallback_costs.get(fruit, {})
        fc   = freight_costs.get(fruit, {})
        sr   = shrink_rates.get(fruit, 0.10)
        sea  = seasonality.get(fruit, "—")
        desc = descs.get(fruit, "")
        ins  = insights.get(fruit, "")

        fm = financial_metrics_fn(fruit, fb.get("low", 1.0), fb.get("high", 2.0), 45)

        shrink_flag = " ⚠️ HIGH SHRINK" if sr >= 0.20 else ""
        lines.append(f"\n### {fruit}  (opportunity score: {sc}){shrink_flag}")
        lines.append(f"Description: {desc}")
        lines.append(f"Seasonality: {sea}")
        lines.append(
            f"Financials (hypothetical est.): "
            f"wholesale ${fb.get('low', 0):.2f}–${fb.get('high', 0):.2f}/unit | "
            f"freight ${fm['freight_mid']:.2f}/unit via {fc.get('port', '—')} | "
            f"shrink {sr * 100:.0f}%{shrink_flag} | "
            f"effective cost ${fm['effective_cost']:.2f} | "
            f"est. retail ${fm['retail_price']:.2f} | "
            f"gross margin ~{fm['gross_margin_pct']:.0f}%"
        )
        lines.append("Estimated annual lbs/yr consumed per loyalty customer by demographic:")
        for eth in ETHNICITIES:
            lines.append(f"  - {eth}: {lbs.get(eth, 0):.1f} lbs/yr")
        if ins:
            lines.append(f"Store-specific insight: {ins}")

    # ── Top 5 ─────────────────────────────────────────────────
    lines.append(f"\n## Top 5 Recommendations for {selected_city}")
    for i, (fruit, sc) in enumerate(top5):
        lines.append(f"{i + 1}. {fruit} — score {sc}")

    # ── Full ranking ──────────────────────────────────────────
    lines.append(f"\n## Full Fruit Ranking for {selected_city} (all 8)")
    for i, (fruit, sc) in enumerate(ranked):
        lines.append(f"{i + 1}. {fruit}: {sc}")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# API call
# ──────────────────────────────────────────────────────────────

def stream_claude_response(
    messages: list[dict],
    system_prompt: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
):
    """
    Stream a response from the Claude API.
    `messages` is the full conversation history in
    [{"role": "user"|"assistant", "content": str}, ...] format.

    Yields text chunks as they arrive so Streamlit can render them with
    st.write_stream().
    """
    client = anthropic.Anthropic(api_key=api_key)

    with client.messages.stream(
        model=model,
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text
