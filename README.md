# Crypto Trading Strategy - Research & Implementation

A multi-month, solo research project on building and validating an algorithmic trading strategy for
BTCUSDT (Binance). The repository documents the **full journey**: from parameter optimisation and
machine-learning experiments, through price-action (Smart Money Concepts), to a final multi-timeframe
**confluence scoring** strategy - including the honest negative results that shaped each pivot.

The emphasis is on **process and intellectual honesty**, not on a "holy grail": several promising
ideas were tested rigorously and abandoned when they failed to generalise.

> This repository is a curated reconstruction of research conducted over several months; the Git
> history records its publication and cleanup, not the original experiment dates.

## The research journey

The [`research/`](research/) folder reconstructs the work chronologically, phase by phase. Each phase
has a short write-up in [`research/docs/`](research/docs/) with methodology, results and honest
findings.

| Phase | Topic | Outcome |
| --- | --- | --- |
| [A](research/docs/phase_A.md) | Best fixed parameters per interval | Best settings scattered, no visible dependency |
| [B](research/docs/phase_B.md) | Stop-Loss / Take-Profit per ATR band | Per-band tuning overfits; combined result negative |
| [C](research/docs/phase_C.md) | Exponential risk sizing (curve fitting) | `SL = 1400·(e^(Ks·ATR)−1)`, `TP = SL·(e^(0.8459·Kt)−1)` |
| [D](research/docs/phase_D.md) | Dynamic 6-coefficient model (grid search) | Good in-sample, super-sensitive → overfitting |
| [E](research/docs/phase_E.md) | Predicting `Ks`/`Kt` from features (regression, Random Forest, SHAP, GA, NN) | Not predictable (real R² ≈ 0.24; data-leakage caveat) |
| [F](research/docs/phase_F.md) | What drives price (feature importance) | Level-vs-return / non-stationarity trap (83% spurious) |
| [G](research/docs/phase_G.md) | Order Blocks / Smart Money Concepts (+ Decision-Tree classifier) | Structure detectable, but regime-dependent; ML couldn't predict SL |
| [H](research/docs/phase_H.md) | **Final strategy** - multi-timeframe confluence scoring | Profitable in 2024, negative in 2025 (honest out-of-sample result) |

See [`research/README.md`](research/README.md) for a deeper walkthrough of the backtester and the
methodology.

## The final strategy (Phase H)

A **LONG-only, multi-timeframe momentum** strategy that scores six independent technical factors on a
0–19 scale (daily RSI, price vs daily SMA, hourly EMA/SMA trend, volume confirmation, candle
momentum, and Bollinger position) and enters only when the total score is **≥ 14**. Risk is sized
dynamically: stop loss = `2 × hourly ATR`, take profit = `1.5 × stop loss`.

Implementation: [`backtesting/calculateProfit.py`](backtesting/calculateProfit.py).

Backtest results (BTCUSDT):

| Year | Market | Profit | Trades | Win rate |
| --- | --- | --- | --- | --- |
| 2024 | trending | +43.53 | 255 | 47.1% |
| 2025 | ranging | −16.34 | 182 | 41.8% |

The negative 2025 (out-of-period) result is kept deliberately: it demonstrates awareness of
overfitting and regime dependence rather than cherry-picking a good year.

## Repository structure

```
research/          Chronological R&D (phases A–H)
  docs/            Per-phase write-ups (methodology, results, findings)
  order_blocks/    Smart Money Concepts engine + Decision-Tree classifier (Phase G)
  results/         Extracted result tables (CSV)
  figures/         Charts referenced by the docs
  *.py             Cleaned research scripts (backtester, curve fitting, feature analysis)
backtesting/       Production pipeline
  download_*.py    Binance data ingestion (daily / hourly / 15-min)
  ADX/ATR/RSIandSMA/volume.py   Technical indicators
  calculateProfit.py            Final scoring strategy (backtest)
LiveTesting.py     Live / paper trading bot (Binance WebSocket) running the scoring strategy
requirements.txt   Python dependencies
.env.example       Template for API keys and runtime settings
```

## From backtest to live

[`LiveTesting.py`](LiveTesting.py) deploys the same scoring strategy in real time: it streams 15-min
candles over the Binance WebSocket, recomputes the multi-timeframe indicators on the fly, and manages
positions with risk controls (max open positions, daily-loss limit, emergency stop) plus
disconnect/reconnect recovery. It supports a **paper-trading mode** (`PAPER_TRADING=True`) so it can
run without real money.

## Tech stack

Python · pandas · pandas-ta · scikit-learn · SHAP · scipy · matplotlib · python-binance · websockets

## Running it

```bash
pip install -r requirements.txt

# API keys / settings (never commit real keys)
copy .env.example .env   # then edit .env

# Fetch historical data (writes to backtesting/prices/)
python backtesting/main.py

# Backtest the final strategy
python backtesting/calculateProfit.py

# Paper-trade live (PAPER_TRADING defaults to True)
python LiveTesting.py
```

> **Data note:** raw price CSVs are not committed - they are easily re-fetched from Binance via
> `backtesting/main.py`.

## Disclaimer

This project is for **research and educational purposes only**. It is not financial advice. Trading
cryptocurrencies carries substantial risk; past backtested performance does not guarantee future
results.
