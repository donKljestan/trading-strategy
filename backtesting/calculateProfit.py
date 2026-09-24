"""Final strategy: multi-timeframe momentum with a confluence scoring system.

Indexing note: every indicator is computed so that ``indicator[i]`` belongs to
``candle[i]`` (it already includes candle[i]'s own value). Backtests must therefore
use data only up to index ``i-1`` when reacting to candle ``i``. The hourly context
uses the previous closed hourly candle (``data.iloc[idx - 4]`` on the 15-min frame)
and entries are taken on the open of the next candle (``data.iloc[idx + 1]``) - so
there is no look-ahead bias.

Entry logic scores six technical factors on a 0-19 scale (see ``backtesting``) and
opens a LONG position only when the score is at least 14. The stop loss is sized
from the hourly ATR (2x ATR) and the take profit is 1.5x the stop loss.

Bollinger note (kept from the research): the squeeze filter
    ((BBU_hour - BBL_hour) / BBU_hour) * 100  vs  2.2 * avg_perDiff_100_hour
was flagged for extra testing when the number of trades is reduced. The pre-scoring
version required price to be inside the squeeze (width < 2.2x average); the scoring
version below instead rewards NOT being in a squeeze (width > 2.2x average).
"""

import os
import threading

import pandas as pd
import pandas_ta as ta

from ADX import calculate_adx
from ATR import calculate_ATR_and_average
from volume import calculate_average_volume
from RSIandSMA import calculate_RSI, calculate_SMA


def load_ohlcv_data(file_path):
    data = pd.read_csv(file_path)
    data['Timestamp'] = pd.to_datetime(data['OpenTime'])
    data['quoteAssetVolume'] = data['ObimTrgovanja']
    data['numOfTransactions'] = data['BrojTransakcija']
    data['takerBuyBaseAssetVolume'] = data['ObimTrgovanja']
    data.set_index('Timestamp', inplace=True)
    return data[['open', 'high', 'low', 'close', 'volume',
                 'quoteAssetVolume', 'numOfTransactions', 'takerBuyBaseAssetVolume']]


def calculate_profit(side, price1, price2, fee_percentage=0.05):
    if side == "BUY":
        buy_price = float(price1)
        sell_price = float(price2)
    if side == "SELL":
        sell_price = float(price1)
        buy_price = float(price2)
    quantity = 100 / price1
    total_sell = sell_price * quantity
    total_buy = buy_price * quantity
    total_fee = (total_sell + total_buy) * (fee_percentage / 100)
    profit = total_sell - total_buy - total_fee
    return profit


def backtesting(data):
    orders = []
    stop_loss_count = 0
    take_profit_count = 0
    calculated_profit = 0
    data = data.reset_index()
    active_order = False

    for idx, row in data.iterrows():

        # Skip the first and last rows to avoid index errors
        if idx < 10 or idx >= len(data) - 2:
            continue

        previous_hour_candle = data.iloc[idx - 4]
        if not pd.isna(row['RSI'])\
            and not pd.isna(row['Average Volume'])\
            and not pd.isna(row['RSI_day'])\
            and not pd.isna(row['SMA'])\
            and not pd.isna(row['volume'])\
            and not pd.isna(row['ATR'])\
            and not pd.isna(previous_hour_candle['RSI_hour'])\
            and not pd.isna(previous_hour_candle['SMA_50_hour'])\
            and not pd.isna(previous_hour_candle['EMA_9_hour'])\
            and not pd.isna(previous_hour_candle['EMA_21_hour'])\
            and not pd.isna(previous_hour_candle['BBL_hour'])\
            and not pd.isna(previous_hour_candle['BBM_hour'])\
            and not pd.isna(previous_hour_candle['BBU_hour'])\
            and not pd.isna(previous_hour_candle['avg_perDiff_100_hour']):

            # =================================================================
            # SCORING SYSTEM: multi-factor confluence (0-19 points).
            # Score each factor; enter a position only when the score is >= 14.
            # =================================================================
            score = 0

            # 1. Daily RSI bullish (max 5 points)
            if row['RSI_day'] > 50:
                score += 3
            if row['RSI_day'] > 55:
                score += 2

            # 2. Price above the daily SMA (3 points)
            if row['close'] > row['SMA_day']:
                score += 3

            # 3. Hourly trend alignment (4 points)
            if previous_hour_candle['EMA_9_hour'] > previous_hour_candle['EMA_21_hour']:
                score += 2
            if previous_hour_candle['close'] > previous_hour_candle['SMA_50_hour']:
                score += 2

            # 4. Volume confirmation (3 points)
            if row['volume'] > 1.5 * row['Average Volume']:
                score += 2
            if row['volume'] > 2.0 * row['Average Volume']:
                score += 1

            # 5. Price momentum (2 points) - current candle is bullish
            if row['close'] > row['open']:
                score += 2

            # 6. Bollinger position (2 points) - not in a squeeze
            bb_width = ((previous_hour_candle['BBU_hour'] - previous_hour_candle['BBL_hour'])
                        / previous_hour_candle['BBU_hour']) * 100
            if bb_width > 2.2 * previous_hour_candle['avg_perDiff_100_hour']:
                score += 2

            # ENTRY CONDITION: score >= 14 (high threshold for quality trades)
            if score >= 14 and active_order == False:

                order_candle = data.iloc[idx + 1]
                open_price = order_candle['open']

                # Risk: stop loss = 2x hourly ATR (as %), take profit = 1.5x stop loss
                sl_percent = 2 * previous_hour_candle['ATR_hour']
                tp_percent = 1.5
                stop_loss = (open_price / 100) * sl_percent
                take_profit = stop_loss * tp_percent
                stop_loss_price = open_price - stop_loss
                take_profit_price = open_price + take_profit

                active_order = True
                order = Order(idx, "BUY", open_price, stop_loss_price,
                              take_profit_price, order_candle['Timestamp'])
                order.start()
                orders.append(order)

        low_price = row['low']
        high_price = row['high']
        active_ids = []
        for order in orders:
            if order.check_status(low_price, high_price, row['Timestamp']):
                order.join()
                active_order = False
                calculated_profit += order.calculated_profit
                stop_loss_count += order.stop_loss_hit
                take_profit_count += order.take_profit_hit
            else:
                active_ids.append(order.iD)
        orders = [order for order in orders if order.iD in active_ids]

    data.set_index('Timestamp', inplace=True)
    return stop_loss_count, take_profit_count, calculated_profit


completed_orders = pd.DataFrame(columns=['OpenTime', 'CloseTime', 'OpenPrice', 'ClosePrice'])
file_lock = threading.Lock()


class Order(threading.Thread):
    def __init__(self, iD, side, open_price, stop_loss_price, take_profit_price, open_time):
        super().__init__()
        self.iD = iD
        self.side = side
        self.daemon = True
        self.open_price = float(open_price)
        self.stop_loss_price = float(stop_loss_price)
        self.take_profit_price = float(take_profit_price)
        self.open_time = open_time
        self.close_time = None
        self.close_price = 0
        self.calculated_profit = 0
        self.stop_loss_hit = 0
        self.take_profit_hit = 0
        self.event = None

    def check_status(self, low_price, high_price, close_time):
        self.close_time = close_time
        if self.side == "SELL":
            if low_price < self.take_profit_price:
                self.calculated_profit = calculate_profit("SELL", self.open_price, self.take_profit_price)
                self.close_price = self.take_profit_price
                self.event.set()
                self.take_profit_hit = 1
                return True
            elif high_price > self.stop_loss_price:
                self.calculated_profit = calculate_profit("SELL", self.open_price, self.stop_loss_price)
                self.close_price = self.stop_loss_price
                self.event.set()
                self.stop_loss_hit = 1
                return True
        if self.side == "BUY":
            if low_price < self.stop_loss_price:
                self.calculated_profit = calculate_profit("BUY", self.open_price, self.stop_loss_price)
                self.close_price = self.stop_loss_price
                self.event.set()
                self.stop_loss_hit = 1
                return True
            elif high_price > self.take_profit_price:
                self.calculated_profit = calculate_profit("BUY", self.open_price, self.take_profit_price)
                self.close_price = self.take_profit_price
                self.event.set()
                self.take_profit_hit = 1
                return True
        return False

    def run(self):
        self.event = threading.Event()
        global completed_orders
        try:
            self.event.wait()
            with file_lock:
                completed_orders.loc[len(completed_orders)] = {
                    'OpenTime': pd.to_datetime(self.open_time, unit='ms'),
                    'CloseTime': pd.to_datetime(self.close_time, unit='ms'),
                    'OpenPrice': self.open_price,
                    'ClosePrice': self.close_price,
                }
        except Exception as e:
            print(e)


def add_1day_to_15min_chart(data1day, data15min):
    # Merge daily indicators onto the 15-min frame using the most recent daily value
    data1day_copy = data1day[['ADX', 'RSI', 'SMA', 'ATR']].copy()
    data1day_copy.columns = ['ADX_day', 'RSI_day', 'SMA_day', 'ATR_day']
    data15min = pd.merge_asof(
        data15min.reset_index(),
        data1day_copy.reset_index(),
        left_on='Timestamp',
        right_on='Timestamp',
        direction='backward'
    ).set_index('Timestamp')
    return data15min


def add_1hour_to_15min_chart(data1hour, data15min):
    # Merge hourly indicators onto the 15-min frame using the most recent hourly value
    cols_to_add = ['RSI', 'SMA_50', 'EMA_21', 'EMA_9', 'BBL', 'BBM', 'BBU', 'BBP', 'BBB', 'ATR', 'avg_perDiff_100']
    data1hour_copy = data1hour[cols_to_add].copy()
    data1hour_copy.columns = [col + '_hour' for col in cols_to_add]
    data15min = pd.merge_asof(
        data15min.reset_index(),
        data1hour_copy.reset_index(),
        left_on='Timestamp',
        right_on='Timestamp',
        direction='backward'
    ).set_index('Timestamp')
    return data15min


def prepare_data_and_run_test(symbol):
    try:
        inputs = "_2024.csv"

        # 15-minute frame: entry timing, volume and short-term indicators
        file_name = symbol + "_15minutni" + inputs
        file_path = os.path.join(os.getcwd(), "prices", symbol, file_name)
        data = load_ohlcv_data(file_path)
        data = calculate_ATR_and_average(data)
        data = calculate_average_volume(data, length=100)
        data = calculate_RSI(data)
        data = calculate_SMA(data)

        # Hourly frame: trend alignment (EMA/SMA), Bollinger Bands and ATR
        file_name = symbol + "_1casovni" + inputs
        file_path = os.path.join(os.getcwd(), "prices", symbol, file_name)
        data1hour = load_ohlcv_data(file_path)
        data1hour = calculate_RSI(data1hour, length=14)
        data1hour = calculate_ATR_and_average(data1hour)
        data1hour['SMA_50'] = ta.sma(data1hour['close'], length=50)
        data1hour['EMA_9'] = ta.ema(data1hour['close'], length=9)
        data1hour['EMA_21'] = ta.ema(data1hour['close'], length=21)
        bollinger = ta.bbands(close=data1hour['close'], length=20, std=2)
        data1hour['BBL'] = bollinger['BBL_20_2.0']
        data1hour['BBM'] = bollinger['BBM_20_2.0']
        data1hour['BBU'] = bollinger['BBU_20_2.0']
        data1hour['BBB'] = bollinger['BBB_20_2.0']
        data1hour['BBP'] = bollinger['BBP_20_2.0']
        data1hour['perDiff'] = ((data1hour['BBU'] - data1hour['BBL']) / data1hour['BBU']) * 100
        # 100-hour window ~ the typical period over which Bollinger "bubbles" form
        data1hour['avg_perDiff_100'] = data1hour['perDiff'].rolling(window=100).mean()

        # Daily frame: overall trend and momentum (ADX/RSI/SMA/ATR)
        file_name = symbol + "_1dnevni" + inputs
        file_path = os.path.join(os.getcwd(), "prices", symbol, file_name)
        data1day = load_ohlcv_data(file_path)
        data1day = calculate_adx(data1day, period=30)
        data1day = calculate_RSI(data1day, length=14)
        data1day = calculate_SMA(data1day, length=14)
        data1day = calculate_ATR_and_average(data1day)

        data = add_1day_to_15min_chart(data1day, data)
        data = add_1hour_to_15min_chart(data1hour, data)

        stop_loss_count, take_profit_count, calculated_profit = backtesting(data)
        print(f"{symbol} from {inputs} - SL: {stop_loss_count}, TP: {take_profit_count}, "
              f"Profit: {calculated_profit:.2f}")
    except Exception as e:
        print(f"Error for {symbol}: {e}")


def main():
    prepare_data_and_run_test("BTCUSDT")


if __name__ == "__main__":
    main()
