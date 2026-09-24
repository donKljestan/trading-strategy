# Phase B — Per-ATR-band SL/TP tuning and the overfitting trap

## What was tried

Two things were explored with **fixed** Stop Loss / Take Profit sizing (before the exponential
formulation of Phase C):

1. **Per-band tuning.** Stop Loss / Take Profit were tuned *separately* inside four ATR bands
   (`0.25–0.30`, `0.30–0.40`, `0.40–0.50`, `> 0.50`), by only allowing signals whose ATR fell in
   the band. Each band, in isolation, could be made to look profitable.

2. **A continuous walk-forward backtest** of the baseline configuration
   (`RSI 40/60`, `SMA 55/45`, `ATR ≈ 0.21`) over Feb–May 2024, with **10× leverage on a $500
   account**, reporting profit per 7-day window
   ([`../results/fixed_params_backtest_7day.csv`](../results/fixed_params_backtest_7day.csv)).

## The surprising result

- When the per-band settings were combined into a single run over the full history, the result
  was **negative** — the opposite of adding up the per-band profits.
- The walk-forward backtest, on the other hand, looked *spectacular*: reported window returns of
  `+40%` to `+180%` and a cumulative figure growing into the hundreds of thousands of USDT.

| window start | window end | cumulative profit (USDT) | window return % | positions |
| --- | --- | --- | --- | --- |
| 2024-02-22 | 2024-02-29 | 17 533 | 88.4 | 86 |
| 2024-03-14 | 2024-03-21 | 101 652 | 179.3 | 170 |
| 2024-04-11 | 2024-04-18 | 191 609 | 167.1 | 159 |
| 2024-05-02 | 2024-05-09 | 245 458 | 70.0 | 148 |

## Why this is a warning, not a win

Both observations are textbook signs that the backtest — not the market — is being optimised:

- **Selection bias / segment optimisation.** Tuning each ATR band on its own picks the settings
  that happened to fit that slice; those settings do not generalise, so the combined run collapses.
- **Unrealistic execution.** The walk-forward figures assume perfect fills, **no slippage, no
  funding**, and only the 0.05% fee — with **10× leverage compounding**, small modelling errors
  explode into fantasy returns.
- **Over-restriction.** Gating on narrow ATR bands throws away most signals and leaves a tiny,
  cherry-picked sample.

ChatGPT's diagnosis at the time named the same causes: trading fees, slippage, over-restriction of
signals, and over-optimisation.

## Lesson → what comes next

These results were recognised as **overfitting**, not edge. That recognition drove the next steps:

- **Phase C** — replace the brittle fixed Stop Loss / Take Profit with **ATR-based exponential
  risk sizing** (coefficients Ks/Kt), so risk adapts to volatility instead of being hand-picked
  per band.
- **Phases E/F** — stop trusting eye-balled backtests and **quantify** predictability with
  correlation, regression, Random Forest and SHAP (which confirm the edge is weak).
