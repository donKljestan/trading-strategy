import os
import time
import json
import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone

import requests
import websockets
import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv

# Load paper-trading configuration from .env when present.
load_dotenv()

# ============================================================================
# LOGGING SETUP - Main Log + Trade Signals Log
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Separate logger for trade signals and strategy parameters
trade_logger = logging.getLogger('trade_signals')
trade_logger.setLevel(logging.INFO)
trade_handler = logging.FileHandler('trade_signals.log', encoding='utf-8')
trade_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
trade_logger.addHandler(trade_handler)
trade_logger.propagate = False  # Don't send to root logger

print("=" * 72)
print("REAL-TIME PAPER TRADING SIMULATOR")
print("Public Binance market data; no exchange orders are submitted")
print("=" * 72)

# Paper-trading risk parameters
MAX_POSITION_SIZE_USD = float(os.getenv('MAX_POSITION_SIZE_USD', 100))
MAX_DAILY_LOSS_USD = float(os.getenv('MAX_DAILY_LOSS_USD', 500))
MAX_OPEN_POSITIONS = int(os.getenv('MAX_OPEN_POSITIONS', 5))

logger = logging.getLogger()
logger.setLevel(logging.INFO)  # INFO instead of DEBUG to reduce verbose output

# Silence DEBUG logs from the websockets library
logging.getLogger('websockets').setLevel(logging.WARNING)

info_handler = logging.FileHandler('info.log', encoding='utf-8')
info_handler.setLevel(logging.INFO)

error_handler = logging.FileHandler('error.log', encoding='utf-8')
error_handler.setLevel(logging.ERROR)

formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s')

info_handler.setFormatter(formatter)
error_handler.setFormatter(formatter)

class MaxLevelFilter(logging.Filter):
    def __init__(self, level):
        self.max_level = level
    
    def filter(self, record):
        return record.levelno <=  self.max_level
        
info_handler.addFilter(MaxLevelFilter(logging.WARNING))

logger.addHandler(info_handler)
logger.addHandler(error_handler)

# Global counters for risk management
daily_pnl = 0
daily_pnl_date = datetime.now(timezone.utc).date()
active_positions_count = 0
positions_lock = threading.Lock()

def update_daily_pnl(profit):
    """Update daily PnL and check if we should stop trading."""
    global daily_pnl, daily_pnl_date, active_positions_count
    
    current_date = datetime.now(timezone.utc).date()
    
    with positions_lock:
        # Reset daily PnL if it's a new day
        if current_date != daily_pnl_date:
            logger.info(f"New day. Resetting daily PnL. Previous PnL: {daily_pnl:.2f}")
            daily_pnl = 0
            daily_pnl_date = current_date
        
        daily_pnl += profit
        logger.info(f"Daily PnL: {daily_pnl:.2f} USD")
        
        # Check if we hit max daily loss
        if daily_pnl <= -MAX_DAILY_LOSS_USD:
            logger.error(f"WARNING: Maximum daily loss reached! PnL: {daily_pnl:.2f}")
            return False
        
        return True

def can_open_position():
    """Check if we can open a new position."""
    with positions_lock:
        if active_positions_count >= MAX_OPEN_POSITIONS:
            logger.warning(f"Cannot open position. Max open positions: {active_positions_count}/{MAX_OPEN_POSITIONS}")
            return False
        
        if daily_pnl <= -MAX_DAILY_LOSS_USD:
            logger.error(f"Cannot open position. Maximum daily loss reached: {daily_pnl:.2f}")
            return False
        
        return True

def increment_positions():
    """Increment active positions counter."""
    global active_positions_count
    with positions_lock:
        active_positions_count += 1
        logger.info(f"Active positions: {active_positions_count}")

def decrement_positions():
    """Decrement active positions counter."""
    global active_positions_count
    with positions_lock:
        active_positions_count = max(0, active_positions_count - 1)
        logger.info(f"Active positions: {active_positions_count}")

def log_daily_performance():
    """Log daily performance metrics to CSV"""
    try:
        if not os.path.exists('completedOrders.csv'):
            logger.warning("No completed orders to log")
            return
        
        completed = pd.read_csv('completedOrders.csv')
        completed['CloseTime'] = pd.to_datetime(completed['CloseTime'])
        
        today = datetime.now(timezone.utc).date()
        today_trades = completed[completed['CloseTime'].dt.date == today]
        
        if len(today_trades) == 0:
            logger.info("No trades today")
            return
        
        wins = (today_trades['CalculatedProfit'] > 0).sum()
        losses = (today_trades['CalculatedProfit'] <= 0).sum()
        win_rate = (wins / len(today_trades) * 100) if len(today_trades) > 0 else 0
        total_pnl = today_trades['CalculatedProfit'].sum()
        
        # Calculate cumulative metrics
        cumulative_pnl = completed['CalculatedProfit'].sum()
        total_trades = len(completed)
        total_wins = (completed['CalculatedProfit'] > 0).sum()
        overall_win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        
        performance_data = pd.DataFrame([{
            'Date': today,
            'DailyTrades': len(today_trades),
            'DailyWins': wins,
            'DailyLosses': losses,
            'DailyWinRate': f"{win_rate:.2f}%",
            'DailyPnL': f"{total_pnl:.2f}",
            'CumulativeTrades': total_trades,
            'CumulativePnL': f"{cumulative_pnl:.2f}",
            'OverallWinRate': f"{overall_win_rate:.2f}%"
        }])
        
        # Append to performance log
        if not os.path.exists('performance_log.csv'):
            performance_data.to_csv('performance_log.csv', index=False)
        else:
            performance_data.to_csv('performance_log.csv', mode='a', header=False, index=False)
        
        logger.info(f"Daily performance: {len(today_trades)} trades, {win_rate:.1f}% WR, ${total_pnl:.2f} PnL")
        
    except Exception as e:
        logger.error(f"Error logging daily performance: {e}")

def calculate_strategy_score(close_price, open_price, rsi_day, sma_day, volume,
                             average_volume, ema_9_hour, ema_21_hour, sma_50_hour,
                             bbu_hour, bbl_hour, avg_bb_width):
    """Return the 0-19 entry score and an auditable point breakdown."""
    score = 0
    breakdown = []

    if rsi_day > 50:
        score += 3
        breakdown.append("RSI_day > 50: +3")
    if rsi_day > 55:
        score += 2
        breakdown.append("RSI_day > 55: +2")
    if close_price > sma_day:
        score += 3
        breakdown.append("Close > SMA_day: +3")
    if ema_9_hour > ema_21_hour:
        score += 2
        breakdown.append("EMA_9 > EMA_21: +2")
    if close_price > sma_50_hour:
        score += 2
        breakdown.append("Close > SMA_50: +2")
    if volume > 1.5 * average_volume:
        score += 2
        breakdown.append("Volume > 1.5x average: +2")
    if volume > 2.0 * average_volume:
        score += 1
        breakdown.append("Volume > 2.0x average: +1")
    if close_price > open_price:
        score += 2
        breakdown.append("Bullish 15-minute candle: +2")

    bb_width = ((bbu_hour - bbl_hour) / bbu_hour) * 100
    if bb_width > 2.2 * avg_bb_width:
        score += 2
        breakdown.append("BB width > 2.2x average: +2")

    return score, breakdown


def log_trade_signal(symbol, side, entry_price, sl_price, tp_price, score,
                     score_breakdown, rsi_day, sma_day, close_price,
                     ema_9_hour, ema_21_hour,
                     sma_50_hour, bbu_hour, bbl_hour, bb_width_pct, 
                     avg_bb_width, volume, avg_volume, atr_hour):
    """
    Log detailed trade signal with all strategy parameters to separate file.
    Makes it easy to review why a trade was taken.
    """
    try:
        sl_pct = ((sl_price - entry_price) / entry_price) * 100
        tp_pct = ((tp_price - entry_price) / entry_price) * 100
        position_size = MAX_POSITION_SIZE_USD
        
        # Build log message
        message = f"\n{'='*80}\n"
        message += f"{side} ENTRY SIGNAL - {symbol}\n"
        message += f"{'='*80}\n\n"
        
        message += "POSITION DETAILS:\n"
        message += f"  Entry Price:    ${entry_price:,.2f}\n"
        message += f"  Stop Loss:      ${sl_price:,.2f} ({sl_pct:+.2f}%)\n"
        message += f"  Take Profit:    ${tp_price:,.2f} ({tp_pct:+.2f}%)\n"
        message += f"  Position Size:  ${position_size:.2f}\n"
        message += f"  Risk/Reward:    1:{abs(tp_pct/sl_pct):.2f}\n\n"
        
        message += f"STRATEGY SCORE: {score}/19 (threshold: 14)\n"
        message += "  Score Breakdown:\n"
        for item in score_breakdown:
            message += f"    {item}\n"
        message += f"\n"
        
        message += "STRATEGY PARAMETERS:\n"
        message += f"  Daily Timeframe:\n"
        message += f"    RSI_day:      {rsi_day:.2f}\n"
        message += f"    SMA_day:      ${sma_day:,.2f}\n"
        message += f"    Current Price:${close_price:,.2f}\n"
        message += f"    Trend:        {'BULLISH' if close_price > sma_day else 'BEARISH'}\n\n"
        
        message += f"  Hourly Timeframe:\n"
        message += f"    EMA_9:        ${ema_9_hour:,.2f}\n"
        message += f"    EMA_21:       ${ema_21_hour:,.2f}\n"
        message += f"    SMA_50:       ${sma_50_hour:,.2f}\n"
        message += f"    EMA Trend:    {'BULLISH' if ema_9_hour > ema_21_hour else 'BEARISH'}\n"
        message += f"    BB Upper:     ${bbu_hour:,.2f}\n"
        message += f"    BB Lower:     ${bbl_hour:,.2f}\n"
        message += f"    BB Width:     {bb_width_pct:.2f}% (avg: {avg_bb_width:.2f}%)\n"
        message += f"    ATR:          {atr_hour:.2f}%\n\n"
        
        message += f"  Volume Analysis:\n"
        message += f"    Current:      {volume:,.0f}\n"
        message += f"    Average:      {avg_volume:,.0f}\n"
        message += f"    Ratio:        {volume/avg_volume:.2f}x\n\n"
        
        message += "MARKET CONTEXT:\n"
        message += f"  Daily Trend:  {'BULLISH' if rsi_day > 50 and close_price > sma_day else 'BEARISH'}\n"
        message += f"  Hourly Trend: {'BULLISH' if ema_9_hour > ema_21_hour else 'BEARISH'}\n"
        message += f"  Volatility:   {'HIGH' if bb_width_pct > avg_bb_width * 1.5 else 'NORMAL'}\n"
        message += f"  Volume:       {'HIGH' if volume > avg_volume * 1.5 else 'NORMAL'}\n\n"
        
        message += f"{'='*80}\n"
        
        # Log to separate file
        trade_logger.info(message)
        
    except Exception as e:
        logger.error(f"Error logging trade signal: {e}")

def check_missed_candles(last_candle_time):
    """Check if candles were missed during disconnect and alert"""
    now = datetime.now(timezone.utc)
    time_diff_minutes = (now - last_candle_time).total_seconds() / 60
    
    if time_diff_minutes >= 15:
        missed_candles = int(time_diff_minutes // 15)
        logger.warning(f"Reconnect gap: approximately {missed_candles} candle(s) missed")
        logger.warning(f"Last candle: {last_candle_time}, Now: {now}")
        return missed_candles
    
    return 0

def fetch_closed_kline(symbol, interval, end_time_ms, max_retries=3):
    """Fetch the latest exchange-confirmed candle closed by end_time_ms."""
    url = "https://api.binance.com/api/v3/klines"
    params = {
        'symbol': symbol,
        'interval': interval,
        'endTime': end_time_ms,
        'limit': 2,
    }

    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code in (418, 429):
                retry_after = int(response.headers.get('Retry-After', 2 ** (attempt + 1)))
                logger.warning(f"REST rate limit for {symbol} {interval}; retrying in {retry_after}s")
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            candles = [candle for candle in response.json() if int(candle[6]) <= end_time_ms]
            if candles:
                return max(candles, key=lambda candle: candle[6])
        except requests.RequestException as exc:
            logger.warning(
                f"REST fetch failed for {symbol} {interval} "
                f"(attempt {attempt + 1}/{max_retries}): {exc}"
            )
            if attempt + 1 < max_retries:
                time.sleep(2 ** attempt)

    raise RuntimeError(f"Could not fetch a closed {interval} candle for {symbol}")

def process_missed_candles(symbol, last_candle_time):
    """
    Fetch and process candles missed during internet disconnection.
    Checks if active order's SL/TP was hit during downtime.
    Returns: (position_closed, close_price, close_reason, close_time) or (False, None, None, None)
    """
    missed_count = check_missed_candles(last_candle_time)
    
    if missed_count == 0:
        return False, None, None, None
    
    # Load active order for this symbol
    active_order = load_active_order_for_symbol(symbol, file_path="activeOrders.csv")
    
    if not active_order:
        logger.info(f"No active order for {symbol} during reconnect - no processing needed")
        return False, None, None, None
    
    try:
        # Fetch missing candlesticks from Binance REST API
        logger.info(f"Fetching {missed_count} missed candles for {symbol}")
        
        end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_time = int(last_candle_time.timestamp() * 1000)
        
        url = "https://api.binance.com/api/v3/klines"
        params = {
            'symbol': symbol,
            'interval': '15m',
            'startTime': start_time,
            'endTime': end_time,
            'limit': min(missed_count + 5, 1000)
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch missed candles: {response.status_code}")
            return False, None, None, None
        
        missed_candles = sorted(response.json(), key=lambda candle: candle[6])
        last_close_ms = int(last_candle_time.timestamp() * 1000)
        missed_candles = [
            candle for candle in missed_candles
            if last_close_ms < int(candle[6]) <= end_time
        ]
        
        if not missed_candles:
            logger.warning(f"No missed candles returned from API")
            return False, None, None, None
        
        logger.info(f"Fetched {len(missed_candles)} missed candles; processing in timestamp order")
        
        # Process each missed candle IN ORDER
        for candle in missed_candles:
            high_price = float(candle[2])
            low_price = float(candle[3])
            close_time = candle[6]  # Close timestamp
            
            # Extract active order details
            side = active_order['side']
            entry_price = float(active_order['openPrice'])
            sl_price = float(active_order['stopLossPrice'])
            tp_price = float(active_order['takeProfitPrice'])
            
            # Only BUY positions are supported (LONG-only strategy)
            if side == "BUY":
                # WORST CASE: Check SL first (assume price went against us first)
                if low_price <= sl_price:
                    logger.warning(f"Stop loss hit during disconnect: {symbol} @ ${sl_price:.2f}")
                    return True, sl_price, 'StopLoss', close_time
                
                # Check TP only if SL wasn't hit
                elif high_price >= tp_price:
                    logger.info(f"Take profit hit during disconnect: {symbol} @ ${tp_price:.2f}")
                    return True, tp_price, 'TakeProfit', close_time
            else:
                logger.error(f"Unsupported position side: {side}. Only BUY positions are supported.")
                return False, None, None, None
        
        # No SL/TP hit in any missed candle
        logger.info(f"Active order for {symbol} survived disconnect; continuing tracking")
        return False, None, None, None
        
    except Exception as e:
        logger.error(f"Error processing missed candles for {symbol}: {e}")
        return False, None, None, None

def calculate_profit(side, price1, price2, fee_percentage = 0.05):
    """
    Calculate profit for BUY (LONG) positions only.
    
    Args:
        side: "BUY" (only LONG positions supported)
        price1: Entry price (buy price)
        price2: Exit price (sell price)
        fee_percentage: Trading fee (default 0.05%)
    
    Returns:
        Profit in USD (positive = profit, negative = loss)
    """
    if side != "BUY":
        logger.error(f"Unsupported side: {side}. Only BUY positions are supported.")
        return 0
    
    buy_price = float(price1)
    sell_price = float(price2)
    quantity = MAX_POSITION_SIZE_USD / buy_price
    total_sell = sell_price * quantity
    total_buy = buy_price * quantity
    total_fee = (total_sell + total_buy) * (fee_percentage / 100)
    profit = total_sell - total_buy - total_fee
    return profit
    
def calculate_ATR(data, atr_length=14):

    # Ensure the DataFrame has the required columns
    if not all(col in data.columns for col in ['high', 'low', 'close']):
        raise ValueError("Data must contain the columns: 'high', 'low', 'close'")
    
    # True Range
    high_prices = data['high']
    low_prices = data['low']
    close_prices = data['close']
    tr = ta.true_range(high_prices, low_prices, close_prices)
    
    # Scale True Range to a percentage of price
    close_prices_shifted = close_prices.shift(1)
    scaled_tr = tr * (100 / close_prices_shifted)
    
    # ATR as an SMA of the scaled True Range
    data['ATR'] = ta.sma(scaled_tr, length=atr_length)
    return data
    
    
def get_previous_1day_candles(symbol, interval="1d", days = 10, days_ago = 10):

    data1day = pd.DataFrame()
    data1day['close'] = None
    
    limit = days * 24  # 24 candles per day
    start_time = int((datetime.now(timezone.utc) - timedelta(days=days_ago)).timestamp() * 1000)
    all_candles = []
    retry_count = 0
    max_retries = 3
    
    while True:
        try:
            url = "https://api.binance.com/api/v3/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': limit,
                'startTime': start_time
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
            elif response.status_code == 429:
                logger.warning(f"Rate limit hit for {symbol}. Waiting 60 seconds...")
                time.sleep(60)
                continue
            else:
                logger.error(f"API error {response.status_code} for {symbol}: {response.text}")
                retry_count += 1
                if retry_count >= max_retries:
                    raise Exception(f"Failed to get data after {max_retries} retries")
                time.sleep(5)
                continue
        
            if not data:
                break
            
            all_candles.extend(data)
            start_time = data[-1][0] + 1
            time.sleep(0.5)
            if len(all_candles) >= (days * 24):
                break
        except Exception as e:
            logger.error(f"Error fetching 1day candles for {symbol}: {e}")
            retry_count += 1
            if retry_count >= max_retries:
                raise
            time.sleep(5)
            
    data1day['close'] = [float(kline[4]) for kline in all_candles]
    
    # Data validation
    if data1day['close'].isnull().any():
        logger.warning(f"NULL values in 1day data for {symbol}")
    
    return data1day

def get_previous_1hour_candles(symbol, interval="1h", days = 10, days_ago = 10):

    data1hour = pd.DataFrame()
    data1hour['close'] = None
    data1hour['low'] = None
    data1hour['high'] = None
    
    limit = days * 24  # 24 candles per day
    start_time = int((datetime.now(timezone.utc) - timedelta(days=days_ago)).timestamp() * 1000)
    all_candles = []
    retry_count = 0
    max_retries = 3
    
    while True:
        try:
            url = "https://api.binance.com/api/v3/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': limit,
                'startTime': start_time
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
            elif response.status_code == 429:
                logger.warning(f"Rate limit hit for {symbol}. Waiting 60 seconds...")
                time.sleep(60)
                continue
            else:
                logger.error(f"API error {response.status_code} for {symbol}")
                retry_count += 1
                if retry_count >= max_retries:
                    raise Exception(f"Failed to get data after {max_retries} retries")
                time.sleep(5)
                continue
        
            if not data:
                break
            
            all_candles.extend(data)
            start_time = data[-1][0] + 1
            time.sleep(0.5)
            if len(all_candles) >= (days * 24):
                break
        except Exception as e:
            logger.error(f"Error fetching 1hour candles for {symbol}: {e}")
            retry_count += 1
            if retry_count >= max_retries:
                raise
            time.sleep(5)
            
    data1hour['high'] = [float(kline[2]) for kline in all_candles]
    data1hour['low']  = [float(kline[3]) for kline in all_candles]
    data1hour['close'] = [float(kline[4]) for kline in all_candles]
    
    return data1hour
    
def get_previous_15min_candles(symbol, interval="15m", days = 10, days_ago = 10):

    data15min = pd.DataFrame()
    data15min['close'] = None
    data15min['volume'] = None
    
    limit = days * 96  # 96 candles per day
    start_time = int((datetime.now(timezone.utc) - timedelta(days=days_ago)).timestamp() * 1000)
    all_candles = []
    retry_count = 0
    max_retries = 3
    
    while True:
        try:
            url = "https://api.binance.com/api/v3/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': limit,
                'startTime': start_time
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
            elif response.status_code == 429:
                logger.warning(f"Rate limit hit for {symbol}. Waiting 60 seconds...")
                time.sleep(60)
                continue
            else:
                logger.error(f"API error {response.status_code} for {symbol}")
                retry_count += 1
                if retry_count >= max_retries:
                    raise Exception(f"Failed to get data after {max_retries} retries")
                time.sleep(5)
                continue
        
            if not data:
                break
            
            all_candles.extend(data)
            start_time = data[-1][0] + 1
            time.sleep(0.5)
            if len(all_candles) >= (days * 96):
                break
        except Exception as e:
            logger.error(f"Error fetching 15min candles for {symbol}: {e}")
            retry_count += 1
            if retry_count >= max_retries:
                raise
            time.sleep(5)
            
    data15min['close'] = [float(kline[4]) for kline in all_candles]
    data15min['volume'] = [float(kline[5]) for kline in all_candles]
    
    return data15min
file_lock = threading.Lock()

def remove_order_from_activeOrders(symbol, file_path="activeOrders.csv"):
    try:
        with file_lock:
            if not os.path.exists(file_path):
                return

            with open(file_path, 'r') as file:
                lines = file.readlines()

            lines_to_keep = [
                line for index, line in enumerate(lines)
                if index == 0 or line.split(',', 1)[0] != symbol
            ]

            temporary_path = f"{file_path}.tmp"
            with open(temporary_path, 'w') as file:
                file.writelines(lines_to_keep)
            os.replace(temporary_path, file_path)

    except Exception as e:
        print(f"Error in write_in_file: {e}")
        logging.error(f"Error while removing order from {file_path}: {e}")
    
        
def write_in_file(filtered_data, file_path="activeOrders.csv"):
    """
    Safely writes data to a file using a lock to prevent race conditions.
    
    Parameters:
        filtered_data (DataFrame): Data to write into the file.
        file_path (str): Path to the file where data will be written.
    """
    try:
        with file_lock:  # Lock the resource to avoid race conditions
            # Check if the file exists
            if not os.path.exists(file_path):
                # Write with header if the file doesn't exist
                filtered_data.to_csv(file_path, index=False)
            else:
                # Append data without writing the header
                filtered_data.to_csv(file_path, mode='a', header=False, index=False)
    except Exception as e:
        print(f"Error in write_in_file: {e}")
        logging.error(f"Error while writing to file {file_path}: {e}")
        
def isBullishConditionMet(closePrice, openPrice, RSI_day, SMA_day, volume, averageVolume, EMA_9_hour, EMA_21_hour, SMA_50_hour, BBU_hour, BBL_hour, avg_perDiff_100_hour):
    """
    SCORING SYSTEM: multi-factor confluence (0-19 points).
    Score each factor; enter only when the score is >= 14.
    """
    
    # Data validation
    if pd.isna(RSI_day) or pd.isna(SMA_day) or pd.isna(EMA_9_hour) or pd.isna(EMA_21_hour):
        logger.warning("Invalid indicators for the bullish condition")
        return False
    
    if pd.isna(SMA_50_hour) or pd.isna(BBU_hour) or pd.isna(BBL_hour):
        logger.warning("Invalid indicators for the bullish condition (2)")
        return False
    
    if pd.isna(avg_perDiff_100_hour) or averageVolume == 0:
        logger.warning("Invalid volume data for the bullish condition")
        return False

    score, _ = calculate_strategy_score(
        closePrice, openPrice, RSI_day, SMA_day, volume, averageVolume,
        EMA_9_hour, EMA_21_hour, SMA_50_hour, BBU_hour, BBL_hour,
        avg_perDiff_100_hour,
    )
    logger.info(f"Bullish Score: {score}/19 (threshold: 14)")
    return score >= 14

# ============================================================================
# STRATEGY: LONG-ONLY MOMENTUM SYSTEM
# ============================================================================
# Scoring-based entry (0-19 points, threshold: >= 14).
# SHORT trading is intentionally disabled - focus on LONG momentum.
# ============================================================================

def check_emergency_stop():
    """Check if emergency stop file exists"""
    if os.path.exists('emergency_stop.txt'):
        logger.error("Emergency stop active; remove 'emergency_stop.txt' to resume new entries")
        return True
    return False

def load_active_order_for_symbol(symbol, file_path="activeOrders.csv"):
    """Load active order for specific symbol from CSV on startup/reconnect"""
    try:
        with file_lock:
            if not os.path.exists(file_path):
                return None
            df = pd.read_csv(file_path)
        symbol_order = df[df['symbol'] == symbol]
        
        if not symbol_order.empty:
            row = symbol_order.iloc[0]
            logger.info(f"Resumed active order for {symbol}: {row['side']} @ {row['OpenPrice']:.2f}")
            return {
                'openPrice': float(row['OpenPrice']),
                'stopLossPrice': float(row['stopLossPrice']),
                'takeProfitPrice': float(row['takeProfitPrice']),
                'side': row['side'],
                'openTime': row['OpenTime']
            }
    except Exception as e:
        logger.error(f"Error loading active order for {symbol}: {e}")
    
    return None

async def connect_websocket(symbol, data1day, data1hour, data15min):  # websocket for closed candles
    
    # ============================================================================
    # CRASH RECOVERY: Check if there's an active order from previous session
    # ============================================================================
    resumed_order = load_active_order_for_symbol(symbol)
    
    activeOrder = False
    openPrice = 0
    stopLossPrice = 0
    takeProfitPrice = 0
    calculated_profit = 0
    openOrderTime = None
    side = ""
    
    if resumed_order:
        activeOrder = True
        openPrice = resumed_order['openPrice']
        stopLossPrice = resumed_order['stopLossPrice']
        takeProfitPrice = resumed_order['takeProfitPrice']
        side = resumed_order['side']
        openOrderTime = resumed_order['openTime']
        increment_positions()  # Restore position count
        logger.info(f"Resumed tracking {side} order for {symbol}")
    
    print(f"Started listening for: {symbol}")
    stream = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@kline_15m"
    
    last_candle_time = datetime.now(timezone.utc)
    last_processed_close_ms = None
    reconnect_count = 0
    duplicate_messages = 0
    detected_gaps = 0
    
    while True:
        try:
            async with websockets.connect(stream, ping_interval=20, ping_timeout=20, close_timeout=10) as websocket:
                # Check if we missed candles during disconnect
                if reconnect_count > 0:
                    logger.warning(f"Reconnected websocket for {symbol} after {reconnect_count} failed attempt(s)")
                    
                    # Process missed candles and check if active order was closed
                    position_closed, close_price_missed, close_reason, close_time_missed = process_missed_candles(symbol, last_candle_time)
                    
                    if position_closed and activeOrder:
                        # Order was closed during disconnect - update state
                        calculated_profit = calculate_profit(side, openPrice, close_price_missed)
                        
                        activeOrder = False
                        decrement_positions()
                        update_daily_pnl(calculated_profit)
                        remove_order_from_activeOrders(symbol, file_path="activeOrders.csv")
                        
                        dataForWrite = pd.DataFrame([{
                            'symbol': symbol,
                            'OpenTime': pd.to_datetime(openOrderTime, unit='ms'),
                            'CloseTime': pd.to_datetime(close_time_missed, unit='ms'),
                            'OpenPrice': openPrice,
                            'ClosePrice': close_price_missed,
                            'CalculatedProfit': calculated_profit,
                            'ExitReason': close_reason
                        }])
                        write_in_file(dataForWrite, file_path="completedOrders.csv")
                        
                        # Reset variables
                        openPrice = 0
                        stopLossPrice = 0
                        takeProfitPrice = 0
                        side = ""
                        openOrderTime = None
                        
                        logger.info(f"[PAPER] Position closed during disconnect: {symbol} - {close_reason} - P/L: ${calculated_profit:.2f}")

                    reconnect_count = 0
                
                while True:
                    try:
                        data = await websocket.recv()
                        message = json.loads(data)
                        kline = message['k']
                        if kline['x']:
                            open_price = float(kline['o'])
                            close_price = float(kline['c'])
                            high_price = float(kline['h'])
                            low_price = float(kline['l'])
                            volume = float(kline['v'])
                            close_time = int(kline['T'])

                            if last_processed_close_ms is not None:
                                if close_time <= last_processed_close_ms:
                                    duplicate_messages += 1
                                    logger.warning(
                                        "%s ignored duplicate/out-of-order candle close=%d count=%d",
                                        symbol, close_time, duplicate_messages,
                                    )
                                    continue

                                gap_size = (close_time - last_processed_close_ms) // 900_000 - 1
                                if gap_size > 0:
                                    detected_gaps += 1
                                    logger.warning(
                                        "%s sequence gap: missing=%d previous_close=%d current_close=%d total_gaps=%d",
                                        symbol, gap_size, last_processed_close_ms,
                                        close_time, detected_gaps,
                                    )

                            last_processed_close_ms = close_time
                            timestamp = pd.to_datetime(close_time, unit='ms', utc=True)
                            last_candle_time = timestamp.to_pydatetime()
                            
                            # Format timestamp as readable date/time
                            formatted_time = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                            
                            if timestamp.hour == 23 and timestamp.minute == 59:
                                log_daily_performance()

                                daily_candle = await asyncio.to_thread(
                                    fetch_closed_kline, symbol, "1d", close_time
                                )
                                new_row = pd.DataFrame({'close': [float(daily_candle[4])]})
                                data1day = pd.concat([data1day, new_row], ignore_index=True)
                                data1day['RSI'] = ta.rsi(data1day['close'], length=14)
                                data1day['SMA'] = ta.sma(data1day['close'], length=14)

                                # Keep at least ~100 rows of daily data
                                if len(data1day) > 110:
                                    data1day = data1day.iloc[-100:]

                            if timestamp.minute == 59:
                                hourly_candle = await asyncio.to_thread(
                                    fetch_closed_kline, symbol, "1h", close_time
                                )
                                new_row = pd.DataFrame({
                                    'high': [float(hourly_candle[2])],
                                    'low': [float(hourly_candle[3])],
                                    'close': [float(hourly_candle[4])],
                                })
                                data1hour = pd.concat([data1hour, new_row], ignore_index=True)
                                bollinger = ta.bbands(close=data1hour['close'], length=20, std=2)
                                data1hour = calculate_ATR(data1hour, atr_length=14)
                                data1hour['EMA_9'] = ta.ema(data1hour['close'], length=9)
                                data1hour['EMA_21'] = ta.ema(data1hour['close'], length=21)
                                data1hour['SMA_50'] = ta.sma(data1hour['close'], length=50)
                                data1hour['BBU'] = bollinger['BBU_20_2.0']
                                data1hour['BBL'] = bollinger['BBL_20_2.0']
                                data1hour['perDiff'] = ((data1hour['BBU'] - data1hour['BBL'])/data1hour['BBU'])*100
                                data1hour['avg_perDiff_100_hour'] = data1hour['perDiff'].rolling(window=100).mean()

                                # Keep at least ~240 rows (10 days) of hourly data
                                if len(data1hour) > 250:
                                    data1hour = data1hour.iloc[-240:]
                                
                            new_row = pd.DataFrame({'close': [close_price], 'volume': [volume]})
                            data15min = pd.concat([data15min, new_row], ignore_index=True)
                            data15min['Average Volume'] = data15min['volume'].rolling(window=100).mean()
                            
                            # Keep at least ~480 rows (5 days) of 15min data
                            if len(data15min) > 500:
                                data15min = data15min.iloc[-480:]

                            current_score, score_breakdown = calculate_strategy_score(
                                close_price, open_price,
                                data1day['RSI'].iloc[-1], data1day['SMA'].iloc[-1],
                                volume, data15min['Average Volume'].iloc[-1],
                                data1hour['EMA_9'].iloc[-1], data1hour['EMA_21'].iloc[-1],
                                data1hour['SMA_50'].iloc[-1], data1hour['BBU'].iloc[-1],
                                data1hour['BBL'].iloc[-1],
                                data1hour['avg_perDiff_100_hour'].iloc[-1],
                            )
                            logger.info(
                                "%s candle=%s close=%.8f score=%d/19 active_order=%s",
                                symbol, formatted_time, close_price, current_score, activeOrder,
                            )
                            print(
                                f"{symbol} | {formatted_time} | close=${close_price:,.2f} | "
                                f"score={current_score}/19 | candle="
                                f"{'bullish' if close_price > open_price else 'bearish'}"
                            )
                            
                            if activeOrder == True:
                                if side == "BUY":
                                    closePrice = 0
                                    
                                    # WORST CASE: Assume SL hit first if both triggered in same candle
                                    # Check SL first (lower priority = worse outcome)
                                    if low_price <= stopLossPrice:
                                        calculated_profit = calculate_profit("BUY", openPrice, stopLossPrice)
                                        closePrice = stopLossPrice
                                        activeOrder = False
                                        side = ""
                                        decrement_positions()
                                        update_daily_pnl(calculated_profit)
                                        remove_order_from_activeOrders(symbol, file_path="activeOrders.csv")
                                        dataForWrite = pd.DataFrame([{
                                                'symbol': symbol,
                                                'OpenTime': pd.to_datetime(openOrderTime, unit='ms'),
                                                'CloseTime': pd.to_datetime(kline['T'], unit='ms'),
                                                'OpenPrice': openPrice,
                                                'ClosePrice': closePrice,
                                                'CalculatedProfit': calculated_profit,
                                                'ExitReason': 'StopLoss'
                                            }])
                                        #write to completed orders
                                        write_in_file(dataForWrite, file_path="completedOrders.csv")
                                        
                                        logger.info(f"[PAPER] Closed BUY position for {symbol} - StopLoss - P/L: ${calculated_profit:.2f}")
                                        print(f"[PAPER] SL hit: {symbol} @ ${stopLossPrice:.2f} | P/L: ${calculated_profit:.2f}")
                                    
                                    # Check TP only if SL wasn't hit
                                    elif high_price >= takeProfitPrice:
                                        calculated_profit = calculate_profit("BUY", openPrice, takeProfitPrice)
                                        closePrice = takeProfitPrice
                                        activeOrder = False
                                        side = ""
                                        decrement_positions()
                                        update_daily_pnl(calculated_profit)
                                        remove_order_from_activeOrders(symbol, file_path="activeOrders.csv")
                                        dataForWrite = pd.DataFrame([{
                                                'symbol': symbol,
                                                'OpenTime': pd.to_datetime(openOrderTime, unit='ms'),
                                                'CloseTime': pd.to_datetime(kline['T'], unit='ms'),
                                                'OpenPrice': openPrice,
                                                'ClosePrice': closePrice,
                                                'CalculatedProfit': calculated_profit,
                                                'ExitReason': 'TakeProfit'
                                            }])
                                        #write to completed orders
                                        write_in_file(dataForWrite, file_path="completedOrders.csv")
                                        
                                        logger.info(f"[PAPER] Closed BUY position for {symbol} - TakeProfit - P/L: ${calculated_profit:.2f}")
                                        print(f"[PAPER] TP hit: {symbol} @ ${takeProfitPrice:.2f} | P/L: ${calculated_profit:.2f}")
                                
                            # ============================================================================
                            # EMERGENCY STOP CHECK
                            # ============================================================================
                            if check_emergency_stop():
                                logger.error(f"Emergency stop active; skipping new entries for {symbol}")
                                continue
                            
                            if current_score >= 14 and not activeOrder:
                                    
                                    # Check whether we can open a new position
                                    if not can_open_position():
                                        logger.warning(f"Cannot open BUY position for {symbol} - limit reached")
                                        continue
                                    
                                    activeOrder = True
                                    increment_positions()
                                    
                                    logger.info(f"[PAPER] Opened BUY position for {symbol}")
                                    print(f"[PAPER] BUY position opened for {symbol}")
                                    
                                    side = "BUY"
                                    openPrice = close_price
                                    stopLossPercent = 2*data1hour['ATR'].iloc[-1]
                                    stopLossPrice = openPrice - (openPrice/100)*stopLossPercent
                                    takeProfitPrice = openPrice + (openPrice/100)*(stopLossPercent*1.5)
                                    openOrderTime = kline['T']
                                    
                                    # Log detailed trade signal to separate file
                                    log_trade_signal(
                                        symbol=symbol,
                                        side="BUY",
                                        entry_price=openPrice,
                                        sl_price=stopLossPrice,
                                        tp_price=takeProfitPrice,
                                        score=current_score,
                                        score_breakdown=score_breakdown,
                                        rsi_day=data1day['RSI'].iloc[-1],
                                        sma_day=data1day['SMA'].iloc[-1],
                                        close_price=close_price,
                                        ema_9_hour=data1hour['EMA_9'].iloc[-1],
                                        ema_21_hour=data1hour['EMA_21'].iloc[-1],
                                        sma_50_hour=data1hour['SMA_50'].iloc[-1],
                                        bbu_hour=data1hour['BBU'].iloc[-1],
                                        bbl_hour=data1hour['BBL'].iloc[-1],
                                        bb_width_pct=data1hour['perDiff'].iloc[-1],
                                        avg_bb_width=data1hour['avg_perDiff_100_hour'].iloc[-1],
                                        volume=volume,
                                        avg_volume=data15min['Average Volume'].iloc[-1],
                                        atr_hour=data1hour['ATR'].iloc[-1]
                                    )
                                    
                                    dataForWrite = pd.DataFrame([{
                                        'symbol': symbol,
                                        'OpenTime': pd.to_datetime(kline['T'], unit='ms'),
                                        'OpenPrice': openPrice,
                                        'stopLossPrice': stopLossPrice,
                                        'takeProfitPrice': takeProfitPrice,
                                        'side': "BUY"
                                    }])
                                    write_in_file(dataForWrite, file_path="activeOrders.csv")  
                            
                    except Exception as e:
                        logger.warning(f"Receive loop failed for {symbol}: {e}")
                        raise
        except websockets.exceptions.ConnectionClosedError as e:
            reconnect_count += 1
            reconnect_delay = min(2 ** reconnect_count, 60)
            logger.warning(f"WebSocket closed for {symbol}: {e}. Reconnecting in {reconnect_delay}s")
            await asyncio.sleep(reconnect_delay)
        except asyncio.TimeoutError:
            reconnect_count += 1
            reconnect_delay = min(2 ** reconnect_count, 60)
            logger.warning(f"WebSocket timeout for {symbol}. Reconnecting in {reconnect_delay}s")
            await asyncio.sleep(reconnect_delay)
        except Exception as e:
            reconnect_count += 1
            reconnect_delay = min(2 ** reconnect_count, 60)
            logger.exception(f"WebSocket error for {symbol}; reconnecting in {reconnect_delay}s: {e}")
            await asyncio.sleep(reconnect_delay)
           
async def main():
    if os.path.exists('CryptosForBullish.txt'):
        with open('CryptosForBullish.txt', 'r') as file:
            symbols = [line.strip().upper() for line in file if line.strip()]
    else:
        symbols = [
            symbol.strip().upper()
            for symbol in os.getenv('TRADING_SYMBOLS', 'BTCUSDT').split(',')
            if symbol.strip()
        ]

    symbols = list(dict.fromkeys(symbols))
    logger.info(f"Starting paper-trading feeds for: {', '.join(symbols)}")

    tasks = [] 
    for symbol in symbols:
        print(symbol)
        # Compute previous indicators
        data1day = get_previous_1day_candles(symbol, interval="1d", days = 100, days_ago = 100)
        data1hour = get_previous_1hour_candles(symbol, interval="1h", days = 10, days_ago = 10)
        data15min = get_previous_15min_candles(symbol, interval="15m", days = 5, days_ago = 5)
        
        data1day = data1day.iloc[:-1]  # drop the last candle (not yet closed)
        data1day['RSI'] = ta.rsi(data1day['close'], length=14)
        data1day['SMA'] = ta.sma(data1day['close'], length=14)
        
        data1hour = data1hour.iloc[:-1]  # drop the last candle (not yet closed)
        bollinger = ta.bbands(close=data1hour['close'], length=20, std=2)
        data1hour = calculate_ATR(data1hour, atr_length=14)
        data1hour['EMA_9'] = ta.ema(data1hour['close'], length=9)
        data1hour['EMA_21'] = ta.ema(data1hour['close'], length=21)
        data1hour['SMA_50'] = ta.sma(data1hour['close'], length=50)
        data1hour['BBU'] = bollinger['BBU_20_2.0']
        data1hour['BBL'] = bollinger['BBL_20_2.0']
        data1hour['perDiff'] = ((data1hour['BBU'] - data1hour['BBL'])/data1hour['BBU'])*100
        data1hour['avg_perDiff_100_hour'] = data1hour['perDiff'].rolling(window=100).mean()
        
        data15min = data15min.iloc[:-1]  # drop the last candle (not yet closed)
        data15min['Average Volume'] = data15min['volume'].rolling(window=100).mean()
        
        tasks.append(connect_websocket(symbol, data1day, data1hour, data15min))
        # The websockets library keeps the connection alive via its built-in ping/pong mechanism
    await asyncio.gather(*tasks)
    
if __name__ == "__main__":
    asyncio.run(main())