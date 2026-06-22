"""
Opportunity score computation — mirrors the JavaScript logic in the HTML app.
Score = store-level raw score / chain-average raw score × 100.
Raw score = Σ_eth [ share(eth)^w_share × (baseVol×w_vol)^w_vol × (CI/100×w_aff)^w_aff ]
At default weights (all 1.0) this reduces to Σ_eth [ share(eth) × lbs(eth) ].
"""

from __future__ import annotations


def compute_raw(store_share: dict, lbs: dict, ci: dict,
                comp_baseline: float, novelty_discount: float,
                w_share: float = 1.0, w_vol: float = 1.0, w_aff: float = 1.0) -> float:
    ethnicities = ["Asian", "Black", "Hispanic", "White"]
    base_vol = comp_baseline * novelty_discount
    total = 0.0
    for eth in ethnicities:
        s  = (store_share.get(eth, 0) ** w_share)
        v  = (base_vol * w_vol) ** w_vol
        c  = ((ci.get(eth, 100) / 100) * w_aff) ** w_aff
        total += s * v * c
    return total


def compute_scores(store_id: int | str, data: dict,
                   w_share: float = 1.0, w_vol: float = 1.0, w_aff: float = 1.0) -> dict[str, float]:
    """Return dict of fruit → opportunity score (indexed, 100 = chain avg)."""
    sid = str(store_id)
    store_share = data["eth_share"][sid]
    fruits = list(data["lbs"].keys())

    store_raws = {}
    for fruit in fruits:
        store_raws[fruit] = compute_raw(
            store_share, data["lbs"][fruit], data["consumer_index"][fruit],
            data["comp_baseline"][fruit], data["novelty_discount"][fruit],
            w_share, w_vol, w_aff,
        )

    # Chain average
    chain_avgs = {}
    for fruit in fruits:
        total = 0.0
        for st in data["stores"]:
            total += compute_raw(
                data["eth_share"][str(st["id"])],
                data["lbs"][fruit], data["consumer_index"][fruit],
                data["comp_baseline"][fruit], data["novelty_discount"][fruit],
                w_share, w_vol, w_aff,
            )
        chain_avgs[fruit] = total / len(data["stores"])

    return {f: round((store_raws[f] / chain_avgs[f]) * 100, 1) for f in fruits}


def score_color(score: float) -> str:
    if score >= 115: return "🟢"
    if score >= 100: return "🟩"
    if score >= 85:  return "🟡"
    return "🔴"


def top_n(scores: dict[str, float], n: int = 5) -> list[tuple[str, float]]:
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:n]
