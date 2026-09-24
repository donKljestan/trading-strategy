# Phase A — Best parameters per 10-day interval

## Goal

The first version of the strategy exposed four tunable parameters:

- **ATR_LOW**, **ATR_HIGH** — the volatility band the strategy is allowed to trade in.
- **Ks** — how far the Stop Loss sits from entry (scaled by ATR).
- **Kt** — how far the Take Profit sits, relative to the Stop Loss.

BTC 15-minute history was split into **rolling 10-day windows**. For each window the market was
summarised (average price, ATR, RSI, SMA, volume) and a brute-force sweep found the parameter
values that maximised profit on that window.

The central question of Phase A:

> Do the best parameters depend in a **meaningful, reusable** way on the measured market
> conditions, or do they vary essentially at random from one regime to the next?

If they were predictable, the strategy could set its parameters adaptively. If not, the whole
parameter-driven approach is fragile.

## How the result is produced

`testing.py` (`main`) walks the 10-day windows and, for each one:

1. sweeps the `(ATR_LOW, ATR_HIGH)` band with `Ks/Kt` fixed and keeps the best band;
2. sweeps `(Ks, Kt)` with the band fixed and keeps the best pair;
3. writes one row — the window's market conditions plus its best parameters — to
   [`../results/best_params_per_interval.csv`](../results/best_params_per_interval.csv).

## Result

| days_back | avg_price | best ATR band → profit | best Ks, Kt → profit | avg_atr | avg_rsi | avg_vol |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 70 276 | 0.40–0.99 → 4.92 | 1.30, 1.50 → **13.82** | 0.354 | 50.4 | 391 |
| 20 | 67 670 | 0.40–0.50 → 2.72 | 1.20, 0.80 → 0.74 | 0.231 | 50.6 | 211 |
| 30 | 63 961 | 0.30–0.40 → 8.63 | 1.30, 1.20 → 11.88 | 0.294 | 52.4 | 269 |
| 40 | 62 851 | 0.25–0.99 → 8.73 | 1.00, 1.30 → 8.73 | 0.297 | 49.2 | 240 |
| 50 | 63 474 | 0.40–0.99 → 0.57 | 1.20, 1.50 → 6.80 | 0.276 | 52.0 | 218 |
| 60 | 58 072 | 0.25–0.99 → 6.81 | 1.40, 0.90 → 10.83 | 0.325 | 52.4 | 269 |
| 70 | 57 458 | 0.40–0.99 → 4.68 | 1.10, 0.80 → 9.03 | 0.344 | 48.1 | 271 |
| 80 | 61 464 | 0.35–0.40 → 4.45 | 1.40, 0.80 → 6.12 | 0.345 | 49.8 | 268 |
| 90 | 59 547 | 0.40–0.50 → 3.83 | 1.60, 0.80 → 6.53 | 0.399 | 49.7 | 246 |
| 100 | 60 167 | 0.25–0.99 → 19.58 | 1.10, 1.00 → **27.34** | 0.662 | 48.5 | 555 |
| 105 | 65 577 | 0.30–0.99 → 12.11 | 1.20, 1.20 → 15.46 | 0.374 | 48.6 | 286 |
| 110 | 67 075 | 0.40–0.99 → 4.78 | 0.80, 1.00 → 3.34 | 0.340 | 50.7 | 283 |
| 115 | 65 688 | none → 0.00 | 1.30, 0.80 → 0.93 | 0.333 | 49.9 | 273 |

## Reading of the result

- **The best parameters jump around.** `Ks` ranges across its whole grid (0.8 → 1.6) and `Kt`
  likewise, with no visible monotonic link to `avg_atr` or any other measured condition
  (e.g. `avg_atr = 0.662` → `Ks = 1.1`, but `avg_atr = 0.399` → `Ks = 1.6`).
- **Profit is very uneven** across windows (from ~0.5 to ~27), and at least one window (115) has
  **no profitable ATR band at all** — the strategy simply does not work there.
- Visually this already looks closer to a **random scatter** than to a stable dependency.

## Conclusion → what comes next

Phase A does not settle the question; it only shows that *if* a dependency exists, it is weak and
not obvious by eye. That motivates the rigorous statistical work in the later phases:

- **C** — replace the fragile fixed thresholds with exponential Ks/Kt risk sizing.
- **D** — a dynamic 6-coefficient model tuned by grid search.
- **E/F** — correlation, regression, Random Forest and SHAP to *quantify* whether the parameters
  are predictable at all (they turn out not to be).
