# Backtesting Methodology

## 1. Purpose

The purpose of this document is to describe the methodology used to evaluate trading strategies in this repository. The objective is to assess strategy performance using historical market data while accounting for trading costs and reducing the risk of misleading results caused by look-ahead bias, overfitting, or unrealistic execution assumptions.

Backtest results are research estimates, not a guarantee of future performance.

## 2. Historical Data

Strategies are evaluated using historical cryptocurrency market data, including OHLCV candlestick data. Depending on the experiment, additional market fields and derived indicators may be used.

Before running an experiment, the data should be checked for:

- Missing or duplicated candles.
- Correct timestamp ordering and consistent time intervals.
- Invalid OHLC relationships or otherwise implausible values.
- Consistent symbol and timeframe definitions.
- Sufficient history for indicator warm-up periods.

Any data cleaning or exclusion should be applied consistently and documented so that results remain reproducible.

## 3. Signal Timing and Look-Ahead Bias

A strategy must only use information that would have been available at the time the decision was made.

For candle-based strategies, indicators and signals calculated from a candle's closing price should be treated as available only after that candle has closed. The backtest must not use future candles, future indicator values, or information from a higher timeframe before that higher-timeframe candle has closed.

Execution prices should reflect the strategy's stated execution assumptions. A signal calculated at candle close should not automatically be assumed to have been filled at that same closing price unless the execution model explicitly justifies that assumption.

## 4. Trading Fees and Transaction Costs

**Trading fees are included in the backtesting process.** They are an explicit cost of opening and closing positions and must be deducted when calculating net trading performance.

For each simulated trade, the fee calculation should follow the configured fee assumptions and the applicable traded notional. Where fees are charged on both entry and exit, both sides must be included. Fee assumptions should be kept consistent across strategies and experiments so their results can be compared fairly.

Trading fees are not the same as slippage or market impact. Unless separately modelled in a particular experiment, these should be treated as additional costs that may reduce real-world performance. Funding payments may also matter for perpetual futures and should be included when the strategy and backtest data support their calculation.

When reporting results, distinguish gross performance from net performance after fees and any other modelled transaction costs. Record the fee assumptions used for each experiment.

## 5. Position and Trade Accounting

The backtest should apply consistent rules for:

- Entry and exit signals.
- Position sizing and available capital.
- Stop-loss and take-profit handling, where applicable.
- Trade direction and position state.
- Realized and unrealized profit and loss.
- Trading fees and any other modelled costs.

If a candle's high and low cross both a stop-loss and a take-profit level, OHLC data alone may not establish which level was reached first. The backtest should use a documented conservative rule or finer-grained data rather than silently assuming the more favourable outcome.
