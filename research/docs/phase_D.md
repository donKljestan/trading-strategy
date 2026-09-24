# Phase D — Dynamic Ks/Kt from market conditions (6-coefficient grid search)

## Idea

Phases A–C used **fixed** risk coefficients Ks and Kt. Phase A already suggested the best values
drift across market regimes, so Phase D makes Ks and Kt **adaptive**: they are recomputed on every
candle from the current market conditions, through six tunable coefficients `A..F`.

## The model

Each condition is measured relative to its own recent average, then combined:

```
Ks = 0.7   + A·ATRp + B·numTradesP + C·priceFreqP
Kt = 1.2·Ks + D·ATRp + E·numTradesP + F·priceFreqP
```

where `ATRp`, `numTradesP`, `priceFreqP` are the (normalised) deviations of ATR, number of trades
and price frequency from their averages. Implemented as `get_ks` / `get_kt` in
[`../testing.py`](../testing.py). The stop loss itself was also refined to a two-term exponential
that depends on **both** Ks and ATR:

```
StopLoss% = -0.0280·e^(2.0145·Ks) + 0.411·e^(2.0145·ATR)
```

## The search

`main()` grid-searches `A..F`. Because six dimensions explode combinatorially, the search was run
in stages (a coarse pass and then refinements around the best region). The **full search --
79,668 configurations across three sweeps (`par1`, `par2`, `par3`)** -- is in
[`../results/grid_search_ABCDEF.csv`](../results/grid_search_ABCDEF.csv) (the `SWEEP` column marks
the stage).

Profit across the search ranged from **-2068 to +215**. The single highest-profit configuration
sat at the **extreme edge** of the grid:

| SWEEP | A | B | C | D | E | F | profit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| par2 | -1.0 | -1.0 | -1.0 | -1.0 | 0.98 | -1.0 | 214.82 |

A "best" result pinned to the corners of the parameter box is a warning, not a discovery -- it is
almost always fitting noise.

## Best coefficients chosen

Rather than the corner-of-the-grid maximum (which is almost certainly overfit), the set adopted
after refinement and manual verification was **moderate**:

```
A = 0.03,  B = 0.06,  C = 0.38,  D = 0.00,  E = 0.03,  F = -0.35
```

- On a **1500-day** test this gave roughly **27% annual ROI**.
- But it **broke down during the 2020 resistance breakout** (a regime unlike the training period).
- And it was **extremely sensitive**: changing any coefficient by even 0.01–0.02 measurably reduced
  profit.

## Reading of the result

The high sensitivity and the regime-specific failure are the classic fingerprints of
**overfitting**: with six free coefficients and manual refinement toward the best region, the model
fits the quirks of the test window rather than a durable edge. A 6-D grid search optimised by
inspection is powerful but fragile.

This is exactly what pushed the project to stop hand-tuning and instead **measure predictability
directly** — the correlation, regression, Random Forest and SHAP analyses of Phase E.
