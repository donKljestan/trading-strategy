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

## 6. Train, Validation, and Test Separation

Where strategy parameters or machine-learning models are tuned, data should be separated chronologically rather than randomly shuffled.

- **Training period:** used to fit model parameters or develop the strategy.
- **Validation period:** used to compare candidate configurations and make development decisions.
- **Out-of-sample test period:** reserved for final evaluation and not used to tune the strategy.

Repeatedly changing a strategy in response to out-of-sample results makes that period part of the research process and weakens its value as an independent test. The final test period should therefore be used sparingly and its role clearly documented.

## 7. Multi-Timeframe and Machine-Learning Considerations

For strategies using multiple timeframes, every feature must be aligned to the time at which it would actually have been available. Higher-timeframe values should not be propagated into earlier lower-timeframe candles before the higher-timeframe candle closes.

For machine-learning experiments, preprocessing and feature selection should be fitted using training data only. Validation and test data must not influence training-time transformations. Chronological evaluation is essential because random splits can leak temporal information between neighbouring observations.

Predictive metrics alone do not establish trading value. A model should also be evaluated through a trading simulation that accounts for signal timing, trading fees, and other costs included in the experiment.

## 8. Performance Evaluation

Performance should be assessed using multiple metrics rather than total profit alone. Useful metrics include:

- Net return after modelled costs.
- Maximum drawdown.
- Number of completed trades.
- Win rate and average win/loss.
- Expectancy per trade.
- Profit factor.
- Sharpe ratio, with its calculation assumptions documented.
- Performance by time period, symbol, and market regime where relevant.

Metrics should be calculated consistently across experiments. A high win rate by itself does not demonstrate profitability, and a profitable backtest may still have unacceptable drawdown or insufficient trade count.

## 9. Robustness and Sensitivity Checks

Before drawing strong conclusions from a result, assess whether it remains plausible under reasonable changes to assumptions. Useful checks include:

- Increasing assumed trading fees.
- Adding or increasing slippage where it is not already modelled.
- Comparing performance across different chronological periods.
- Checking performance across multiple symbols.
- Testing nearby parameter values rather than relying on a single optimum.
- Comparing the strategy with a simple baseline.
- Measuring how much each major filter or feature contributes to the result.

These checks help identify strategies whose performance depends on unusually favourable assumptions or a narrow historical period.

## 10. Reproducibility and Experiment Records

Each experiment should record enough information to reproduce and interpret its results:

- Strategy and code version.
- Symbols and date range.
- Data source and timeframe(s).
- Parameters and feature definitions.
- Train, validation, and test boundaries, where applicable.
- Trading fee assumptions and any other modelled costs.
- Execution, stop-loss, take-profit, and position-sizing assumptions.
- Performance metrics and known limitations.

Comparisons between experiments are meaningful only when their data scope and cost assumptions are understood.

## 11. Limitations

Historical backtesting cannot fully reproduce live market conditions. Results may be affected by data quality, liquidity, latency, order-book depth, partial fills, slippage, market impact, funding payments, exchange rule changes, and differences between simulated and actual execution.

Including trading fees improves the realism of the simulation, but does not by itself guarantee that all transaction costs or execution risks have been captured.

A positive historical result should therefore be treated as a hypothesis for further validation, not as proof of future profitability.
