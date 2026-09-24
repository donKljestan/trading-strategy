# Phase E — Can Ks/Kt be predicted from market conditions?

## The question

Phases A–D kept hoping the risk coefficients Ks/Kt could be set from the market. Phase E stops
guessing and **measures it directly**: given the market features of a window (ATR, number of
trades, price frequency, volume, RSI, SMA, momentum), can we predict the profitable Ks/Kt — or the
profit itself?

## Methods and results

Predictability was attacked with **both linear and non-linear** tools, escalating each time the
simpler model failed. Full metrics in
[`../results/ks_kt_predictability_metrics.csv`](../results/ks_kt_predictability_metrics.csv).

**Predicting Ks / Kt from market features**

| method (increasing non-linearity) | target | MSE | R² |
| --- | --- | --- | --- |
| Correlation | Ks vs ATR_HIGH | — | corr = 0.21 |
| Correlation | Kt vs ATR_LOW | — | corr = 0.10 |
| Linear regression | Ks | 0.059 | 0.051 |
| Linear regression | Kt | 0.058 | 0.007 |
| Random Forest (non-linear) | Ks | 0.049 | 0.21 |
| Random Forest (non-linear) | Kt | — | -0.005 |
| Neural network (non-linear) | Ks / Kt | — | negative |
| Genetic-algorithm search | Ks / Kt | — | best Ks≈1.21, Kt≈1.04 (profit still negative) |

**Non-linear analysis of the tuning parameters' effect on profit** (ATR_LOW, ATR_HIGH, StopLoss,
TakeProfit → profit)

| method | MSE | R² |
| --- | --- | --- |
| Random Forest (non-linear) | 17.43 | -0.04 |
| Polynomial regression (degree 2) | 16.69 | 0.0025 |

The escalation is the whole point: moving from linear regression to **non-linear** models — Random
Forest, a degree-2 polynomial, a neural network, even a genetic-algorithm search — barely moved the
needle. Random Forest lifted the Ks fit from R²=0.05 only to 0.21; Kt stayed negative; the
polynomial (R²=0.0025) and the neural net (negative R²) added nothing. **The dependency is absent
both linearly and non-linearly.** `feature_analysis.py` reproduces the Random Forest + SHAP part.

## Which measured features drive profit (Random Forest importance)

Turned around — which market conditions most influence *profit* — a Random Forest on the interval
dataset gave the split below, with an overall **R² = 0.237** (about 24% of profit variance
explained). Full data in
[`../results/profit_feature_importance_intervals.csv`](../results/profit_feature_importance_intervals.csv):

| feature | importance on profit (%) |
| --- | --- |
| Average Price Frequency | 18.98 |
| Average ATR | 17.53 |
| Average Volume | 16.75 |
| Average Taker Buy Base Asset Volume | 15.94 |
| Average of Average Number of Trades | 9.56 |

A separate check on trading activity: the raw number of trades contributed ~11% while its rolling
average contributed ~27% — activity matters somewhat, but no single feature dominates and the
overall explanatory power stays low (R² = 0.237).

## Visual evidence

- Profit is spread across the whole Ks/Kt plane rather than concentrated — no strong dependency:

  ![Profit vs Ks/Kt](../figures/profit_dependency_ks_kt.jpg)

- Ks/Kt show only a faint tie to ATR:

  ![Ks vs ATR_HIGH and Kt vs ATR_LOW](../figures/KSvsATR_high_and_KVvsATR_low.jpg)

- SHAP ranks PriceFrequency, AverageATR and VolumeTrend as the most influential features for
  profit — but their overall contribution is still small:

  ![SHAP summary](../figures/SHAP_analysis.jpeg)

## The trap that made it look solved (data leakage)

At one point a Random Forest predicting profit reported **R² = 0.91** (MSE 28.74), and held at
**R² = 0.91** (MSE 26.51) even on a much larger dataset — apparently excellent, and consistently
so. But that model **included Ks and Kt among its inputs**, and profit in the dataset was *computed
from* Ks and Kt. The model was simply reading back its own answer — textbook **data leakage**.
Removing Ks/Kt and predicting profit from genuine market features drops R² to **0.237**.

This is the key lesson of the whole pre-order-blocks era: a headline metric (0.91) can be an
artefact; the honest number (0.237) says the edge is weak.

## Conclusion → the pivot

Across correlation, linear and polynomial regression, Random Forest, SHAP and a neural network,
the profitable parameters are **not reliably predictable** from market conditions, and profit
itself is only weakly explained. The parameter-driven approach had hit a ceiling.

That negative result — not a failure but a finding — is what motivated the change of direction in
the next phase: from predicting parameters to reading **price action / market structure** (Order
Blocks).
