# Pre-Order-Blocks Research

This folder reconstructs the first research era of the project: an attempt to build a
**parameter-driven trading strategy** on BTCUSDT 15-minute candles and to discover whether the
strategy's risk parameters can be **predicted from market conditions**.

The work here is presented chronologically. It ends with an honest negative result that motivated
the later pivot to price-action (Order Blocks). The reconstruction evolves across a series of
commits (phases A–G); this first commit establishes the baseline backtester.

## The strategy

A position is opened on a closed 15-minute candle when **all** of the following agree:

- **Momentum** — RSI, together with an SMA computed on the RSI series
  (`SELL` when `RSI < 40`, `RSI < SMA`, `SMA < 55`; `BUY` when `RSI > 60`, `RSI > SMA`, `SMA > 45`).
- **Volatility band** — ATR (scaled to % of price) inside `[ATR_LOW, ATR_HIGH]`.
- **Volume confirmation** — the previous candle's volume exceeds `VOLUME_FACTOR × recent average`.

Risk is sized dynamically from volatility through two coefficients:

- **Ks** scales the Stop Loss: `StopLoss = 1400 · (e^(Ks · ATR) − 1)`
- **Kt** scales the Take Profit relative to the Stop Loss: `TakeProfit = StopLoss · (e^(0.8459 · Kt) − 1)`

Both exponential forms come from the curve-fitting work documented in phase C.

## `testing.py`

The baseline backtester. Key components:

| Function / class | Role |
| --- | --- |
| `read_lines_from_file` | Loads raw 15-minute candles from `prices.txt`. |
| `get_previous_candles` | Slices the candles inside a `[days_back, days_back − days]` window. |
| `Order` (thread) | Represents one open position; resolves when its stop loss or take profit is hit and accumulates the realised profit. |
| `calculate_profit` | Round-trip profit net of the 0.05% Binance fee per side. |
| `get_current_RSI` / `get_current_SMA` / `get_current_ATR` | Indicator values for the current candle (`ATR` scaled to % of price). |
| `initialize_RSIs` | Warm-up of the RSI series before the main loop. |
| `get_stop_loss_function` / `get_take_profit_function` | Exponential Ks/Kt risk sizing (phase C). |
| `backtesting` | Runs the strategy over one window; returns profit plus market statistics (average price/ATR/RSI/SMA/volume, and the trend and frequency of price and volume). |
| `find_best_parameters` | Sweeps Ks/Kt for a single date and returns the best profit (helper, superseded by `main`). |
| `Parameters` | Container describing one configuration and its measured profit. |
| `main` | Drives the full parameter sweep and writes `parameters.csv`. |

### Output: `parameters.csv`

For every rolling 5-day window (`days_back` from 20 to 400, step 5), `main` sweeps:

1. the `(ATR_LOW, ATR_HIGH)` volatility band with `Ks/Kt` fixed, then
2. the `(Ks, Kt)` coefficients with the band fixed,

writing one row per configuration:

```
AVERAGE_PRICE, PRICE_FREQUENCY, PRICE_TREND, AVERAGE_VOLUME, VOLUME_FREQUENCY,
VOLUME_TREND, AVERAGE_ATR, AVERAGE_RSI, AVERAGE_SMA, ATR_LOW, ATR_HIGH, KS, KT, PROFIT
```

This table is the dataset used in later phases to test whether the measured market conditions
can predict the profitable `Ks`/`Kt` (and `ATR_LOW`/`ATR_HIGH`) settings.

## Data

`testing.py` expects `prices.txt` in the working directory: one 15-minute candle per line,
comma separated (`open_time, close_time, open, high, low, close, volume, ...`).

## Roadmap (phases)

- **A** — 4-parameter tactic (`ATR_LOW`, `ATR_HIGH`, `Ks`, `Kt`); best parameters per interval.
- **B** — Stop Loss / Take Profit testing per ATR band.
- **C** — exponential Ks/Kt risk sizing (curve fitting).
- **D** — dynamic 6-coefficient model (grid search).
- **E** — predicting `Ks`/`Kt` from features (correlation, regression, Random Forest, SHAP).
- **F** — full-feature importance analysis (includes the `AverageOfAverageNumberOfTrades` case).
- **G** — transition to Order Blocks.
