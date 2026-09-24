# Phase H - The final strategy: multi-timeframe confluence scoring

Phases A–F showed that the strategy's risk parameters are **not predictable** from market features,
and Phase G showed that the price-action (Order Blocks) approach was **unstable across market
regimes**. The project therefore returned to a **rules-based indicator strategy**, but with a design
lesson learned from all the previous failures: instead of trusting any single predictive signal,
combine many weak-but-independent confirmations and require broad agreement before trading.

This final strategy lives with the production pipeline in
[`../../backtesting/calculateProfit.py`](../../backtesting/calculateProfit.py), on top of the data
ingestion scripts and indicators already in [`../../backtesting/`](../../backtesting/).

## From strict AND-logic to a scoring system

The order-block research log converged on a **Trend + Momentum** design (EMA 200/50, RSI, ATR,
Bollinger Bands). The first implementation used **strict AND-logic**: a trade required *all* of ~8
conditions to hold at once (daily RSI > 55, 15-min RSI > 65, volume > 1.5x average, hourly EMA-9 >
EMA-21, price > hourly SMA-50, price within 5% of the upper Bollinger Band, controlled BB width, …).

That version worked in strong trends but had two problems:

- It **entered late** - waiting for an overbought 15-min RSI (> 65) and for price to reach the upper
  Bollinger Band meant buying near local tops, right before pullbacks stopped the trade out.
- It was **brittle** - a single marginally-missed condition rejected an otherwise excellent setup, so
  it took few trades and its win rate stayed low (~38%).

The final version replaces rigid AND-logic with a **confluence score**: every factor contributes
points, and a strong factor can compensate for a weaker one. A position is opened only when the total
score clears a high threshold, so the entry is still selective - just not fragile.

## Multi-timeframe structure

| Timeframe | Indicators used |
| --- | --- |
| **Daily** | RSI(14), SMA(14), ADX(30), ATR |
| **Hourly** | RSI(14), SMA(50), EMA(9), EMA(21), Bollinger(20, 2σ), ATR |
| **15-min** | RSI(14), SMA(14), volume vs 100-period average, ATR, OHLC |

Daily indicators are merged onto the 15-min frame with `pd.merge_asof` (`add_1day_to_15min_chart`),
and hourly indicators likewise (`add_1hour_to_15min_chart`); the hourly context used at 15-min bar
`i` is the previous closed hourly candle (`data.iloc[idx - 4]`).

## The scoring system (0–19 points)

| # | Factor | Rule | Points |
| --- | --- | --- | --- |
| 1 | Daily RSI bullish | `RSI_day > 50` (+3), `RSI_day > 55` (+2) | 5 |
| 2 | Price above daily trend | `close > SMA_day` | 3 |
| 3 | Hourly trend alignment | `EMA_9 > EMA_21` (+2), `close > SMA_50` (+2) | 4 |
| 4 | Volume confirmation | `volume > 1.5x avg` (+2), `> 2.0x avg` (+1) | 3 |
| 5 | Price momentum | current 15-min candle bullish (`close > open`) | 2 |
| 6 | Bollinger position | not in a squeeze (`bb_width > 2.2x avg_perDiff_100`) | 2 |

**Entry condition:** `score >= 14` (out of 19 ≈ 74%) and no position already open. The strategy is
**LONG-only**.

## Entry execution and risk management

- **Signal** is evaluated on the close of a 15-min candle; **entry** is the *open* of the next 15-min
  candle (`data.iloc[idx + 1]`).
- **Stop loss** = `2 x ATR_hour` (percent of price) - dynamic, adapts to volatility.
- **Take profit** = `1.5 x stop loss` - a fixed 1 : 1.5 risk/reward.
- **Sizing / fees** (backtest convention): 100 USD per trade, 0.05% taker fee per side, 10x leverage
  parameter.

Orders are modelled as lightweight threads (`Order`) that resolve when price touches the stop or the
target; `backtesting` accumulates realised profit and the stop/target counts.

## Results

Backtested on BTCUSDT (from the project's own runs):

| Year | Market | Profit | Trades | Win rate |
| --- | --- | --- | --- | --- |
| **2024** | trending ($40k → $100k) | **+43.53** | 255 (135 SL / 120 TP) | **47.1%** |
| **2025** | ranging ($93k–$110k) | **−16.34** | 182 (106 SL / 76 TP) | 41.8% |

Compared with the earlier strict-AND version on 2024 (~+100 profit, ~99 trades, ~38% win rate), the
scoring system trades **much more often** with a **higher win rate** but a **lower peak profit** - it
gives up some upside in strong trends in exchange for more consistent, higher-quality entries.

## Honest evaluation

- **Regime dependence / overfitting.** The strategy is profitable in the trending year (2024) and
  loses in the ranging year (2025). It was tuned on mostly trending history, and 2025 was a
  structurally different (range-bound) market. This is the same overfitting lesson that runs through
  the whole project (Phases A–G), now measured directly on out-of-period data.
- **LONG-only.** Short setups are disabled, so downtrends are missed entirely.
- **Momentum weakness in ranges.** Momentum entries are repeatedly stopped out during consolidation.

Reasonable next steps (not yet implemented): a market-regime filter (e.g. trade only when daily
ADX > 20), walk-forward re-calibration of the score threshold, multi-asset testing, lower leverage
and a strict per-trade risk cap, and forward/paper testing before any live use.

## Why this is the end of the research story

The final strategy is deliberately **simple, transparent and rules-based** - the opposite of the
"predict the parameter with ML" ambition of the early phases. The journey is the point: parameter
optimisation (A–D) and predictive modelling (E–F) failed to generalise, price action (G) was
unstable, and what remained was a disciplined confluence system whose **own honest 2025 loss** shows
exactly why robustness and out-of-sample validation matter more than in-sample profit.
