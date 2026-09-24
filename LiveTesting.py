import os
import time
import json
import asyncio
import logging
import threading
from datetime import datetime, timedelta

import requests
import websockets
import pandas as pd
import pandas_ta as ta
from binance.client import Client
from dotenv import load_dotenv

# Security: load API keys from environment variables (.env file)
load_dotenv()
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')

if not api_key or not api_secret:
    raise ValueError("API keys are not set! Check the .env file.")

# Create the Binance client
client = Client(api_key, api_secret)

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

# ============================================================================
# PAPER TRADING MODE
# ============================================================================
# Set PAPER_TRADING=True to run without real money (virtual trading)
# Set PAPER_TRADING=False to run with real orders on Binance
PAPER_TRADING = os.getenv('PAPER_TRADING', 'True').lower() == 'true'

if PAPER_TRADING:
    print("=" * 80)
    print("🎯 PAPER TRADING MODE ACTIVATED")
    print("=" * 80)
    print("✅ No real money will be used")
    print("✅ Orders are simulated based on candlestick high/low")
    print("✅ All trades logged to CSV as if they were real")
    print("=" * 80)
else:
    print("=" * 80)
    print("⚠️  LIVE TRADING MODE - REAL MONEY!")
    print("=" * 80)
    print("💰 Real orders will be placed on Binance")
    print("⚠️  Make sure you know what you're doing!")
    print("=" * 80)

# Trading Parameters
BINANCE_API_BASE_URL = "https://fapi.binance.com"
leverage = int(os.getenv('LEVERAGE', 10))
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
daily_pnl_date = datetime.now().date()
active_positions_count = 0
positions_lock = threading.Lock()

def update_daily_pnl(profit):
    """Update daily PnL and check if we should stop trading."""
    global daily_pnl, daily_pnl_date, active_positions_count
    
    current_date = datetime.now().date()
    
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
        
        today = datetime.now().date()
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
        
        logger.info(f"📊 Daily Performance: {len(today_trades)} trades, {win_rate:.1f}% WR, ${total_pnl:.2f} PnL")
        
    except Exception as e:
        logger.error(f"Error logging daily performance: {e}")

def log_trade_signal(symbol, side, entry_price, sl_price, tp_price, score, 
                     rsi_day, sma_day, close_price_day, ema_9_hour, ema_21_hour, 
                     sma_50_hour, bbu_hour, bbl_hour, bb_width_pct, 
                     avg_bb_width, volume, avg_volume, atr_hour):
    """
    Log detailed trade signal with all strategy parameters to separate file.
    Makes it easy to review why a trade was taken.
    """
    try:
        sl_pct = ((sl_price - entry_price) / entry_price) * 100
        tp_pct = ((tp_price - entry_price) / entry_price) * 100
        
        leverage = int(os.getenv('LEVERAGE', '3'))
        position_size = float(os.getenv('MAX_POSITION_SIZE_USD', '100'))
        
        # Calculate score breakdown
        score_breakdown = []
        
        # RSI scoring
        if rsi_day > 55:
            score_breakdown.append("  RSI_day > 55: +5pts")
        elif rsi_day > 50:
            score_breakdown.append("  RSI_day > 50: +3pts")
        
        # SMA scoring
        if close_price_day > sma_day:
            score_breakdown.append("  Close > SMA_day: +3pts")
        
        # EMA alignment
        if ema_9_hour > ema_21_hour > sma_50_hour:
            score_breakdown.append("  EMA alignment (9>21>50): +4pts")
        
        # Bollinger Bands
        if bb_width_pct > avg_bb_width:
            score_breakdown.append("  BB width > avg: +2pts")
        
        # Volume
        if volume > avg_volume:
            score_breakdown.append("  Volume > avg: +3pts")
        
        # Build log message
        message = f"\n{'='*80}\n"
        message += f"🔔 {side} ENTRY SIGNAL - {symbol}\n"
        message += f"{'='*80}\n\n"
        
        message += f"📊 POSITION DETAILS:\n"
        message += f"  Entry Price:    ${entry_price:,.2f}\n"
        message += f"  Stop Loss:      ${sl_price:,.2f} ({sl_pct:+.2f}%)\n"
        message += f"  Take Profit:    ${tp_price:,.2f} ({tp_pct:+.2f}%)\n"
        message += f"  Leverage:       {leverage}x\n"
        message += f"  Position Size:  ${position_size:.2f}\n"
        message += f"  Risk/Reward:    1:{abs(tp_pct/sl_pct):.2f}\n\n"
        
        message += f"🎯 STRATEGY SCORE: {score}/19 (threshold: 14)\n"
        message += "  Score Breakdown:\n"
        for item in score_breakdown:
            message += f"{item}\n"
        message += f"\n"
        
        message += f"📈 STRATEGY PARAMETERS:\n"
        message += f"  Daily Timeframe:\n"
        message += f"    RSI_day:      {rsi_day:.2f}\n"
        message += f"    SMA_day:      ${sma_day:,.2f}\n"
        message += f"    Close_day:    ${close_price_day:,.2f}\n"
        message += f"    Trend:        {'BULLISH' if close_price_day > sma_day else 'BEARISH'}\n\n"
        
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
        
        message += f"💡 MARKET CONTEXT:\n"
        message += f"  Daily Trend:  {'🟢 BULLISH' if rsi_day > 50 and close_price_day > sma_day else '🔴 BEARISH'}\n"
        message += f"  Hourly Trend: {'🟢 BULLISH' if ema_9_hour > ema_21_hour > sma_50_hour else '🔴 BEARISH'}\n"
        message += f"  Volatility:   {'HIGH' if bb_width_pct > avg_bb_width * 1.5 else 'NORMAL'}\n"
        message += f"  Volume:       {'HIGH' if volume > avg_volume * 1.5 else 'NORMAL'}\n\n"
        
        message += f"{'='*80}\n"
        
        # Log to separate file
        trade_logger.info(message)
        
    except Exception as e:
        logger.error(f"Error logging trade signal: {e}")

def check_missed_candles(last_candle_time):
    """Check if candles were missed during disconnect and alert"""
    now = datetime.now()
    time_diff_minutes = (now - last_candle_time).total_seconds() / 60
    
    if time_diff_minutes > 20:  # More than one candle (15min + buffer)
        missed_candles = int(time_diff_minutes / 15)
        logger.warning(f"⚠️ RECONNECT: Missed {missed_candles} candle(s) during disconnect!")
        logger.warning(f"Last candle: {last_candle_time}, Now: {now}")
        return missed_candles
    
    return 0

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
        logger.info(f"🔄 Fetching {missed_count} missed candles for {symbol}...")
        
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int(last_candle_time.timestamp() * 1000)
        
        url = "https://api.binance.com/api/v3/klines"
        params = {
            'symbol': symbol,
            'interval': '15m',
            'startTime': start_time,
            'endTime': end_time,
            'limit': missed_count + 5  # Extra buffer
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch missed candles: {response.status_code}")
            return False, None, None, None
        
        missed_candles = response.json()
        
        if not missed_candles:
            logger.warning(f"No missed candles returned from API")
            return False, None, None, None
        
        logger.info(f"✅ Fetched {len(missed_candles)} missed candles, processing sequentially...")
        
        # Process each missed candle IN ORDER
        for candle in missed_candles:
            open_price = float(candle[1])
            high_price = float(candle[2])
            low_price = float(candle[3])
            close_price = float(candle[4])
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
                    logger.warning(f"🔴 SL HIT during disconnect: {symbol} @ ${sl_price:.2f} (missed candle)")
                    return True, sl_price, 'StopLoss', close_time
                
                # Check TP only if SL wasn't hit
                elif high_price >= tp_price:
                    logger.info(f"🟢 TP HIT during disconnect: {symbol} @ ${tp_price:.2f} (missed candle)")
                    return True, tp_price, 'TakeProfit', close_time
            else:
                logger.error(f"Unsupported position side: {side}. Only BUY positions are supported.")
                return False, None, None, None
        
        # No SL/TP hit in any missed candle
        logger.info(f"✅ Active order for {symbol} survived disconnect - continuing tracking")
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
    quantity = 100 / price1
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
    start_time = int((datetime.now() - timedelta(days=days_ago)).timestamp() * 1000)
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
    start_time = int((datetime.now() - timedelta(days=days_ago)).timestamp() * 1000)
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
    start_time = int((datetime.now() - timedelta(days=days_ago)).timestamp() * 1000)
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
        with file_lock:  # Lock the resource to avoid race conditions
            with open(file_path, 'r') as file:
                lines = file.readlines()

            # Keep only the lines that do not start with the symbol prefix
            lines_to_keep = [line for line in lines if not line.startswith(symbol)]

            # Reopen the file for writing and write back the remaining lines
            with open(file_path, 'w') as file:
                file.writelines(lines_to_keep)
                
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
    
    # =================================================================
    # SCORING SYSTEM: multi-factor confluence (0-19 points)
    # =================================================================
    score = 0
    
    # 1. Daily RSI bullish (max 5 points)
    if RSI_day > 50:
        score += 3
    if RSI_day > 55:
        score += 2
        
    # 2. Price above daily SMA (3 points)
    if closePrice > SMA_day:
        score += 3
        
    # 3. Hourly trend alignment (4 points)
    if EMA_9_hour > EMA_21_hour:
        score += 2
    if closePrice > SMA_50_hour:
        score += 2
        
    # 4. Volume confirmation (3 points)
    if volume > 1.5 * averageVolume:
        score += 2
    if volume > 2.0 * averageVolume:
        score += 1
        
    # 5. Price momentum (2 points) - bullish candle
    if closePrice > openPrice:
        score += 2
        
    # 6. Bollinger position (2 points) - not in a squeeze
    bb_width = ((BBU_hour - BBL_hour)/BBU_hour)*100
    if bb_width > 2.2 * avg_perDiff_100_hour:
        score += 2
    
    # ENTRY CONDITION: score >= 14 (high threshold for quality trades)
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
        logger.error("🚨 EMERGENCY STOP ACTIVATED! Create 'emergency_stop.txt' to halt trading.")
        return True
    return False

def load_active_order_for_symbol(symbol, file_path="activeOrders.csv"):
    """Load active order for specific symbol from CSV on startup/reconnect"""
    if not os.path.exists(file_path):
        return None
    
    try:
        df = pd.read_csv(file_path)
        symbol_order = df[df['symbol'] == symbol]
        
        if not symbol_order.empty:
            row = symbol_order.iloc[0]
            logger.info(f"📋 Resumed active order for {symbol}: {row['side']} @ {row['OpenPrice']:.2f}")
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
        logger.info(f"✅ Resumed tracking {side} order for {symbol}")
    
    print(f"Started listening for: {symbol}")
    stream = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@kline_15m"
    
    last_candle_time = datetime.now()  # Track last received candle
    reconnect_count = 0
    max_reconnects_before_reset = 10  # reset after too many reconnect attempts
    last_successful_connection = datetime.now()
    
    while True:
        try:
            async with websockets.connect(stream, ping_interval=20, ping_timeout=20, close_timeout=10) as websocket:
                # Check if we missed candles during disconnect
                if reconnect_count > 0:
                    logger.warning(f"🔄 Reconnected to websocket for {symbol} (attempt #{reconnect_count})")
                    
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
                        
                        if PAPER_TRADING:
                            logger.info(f"📄 [PAPER TRADE] Position closed during disconnect: {symbol} - {close_reason} - P/L: ${calculated_profit:.2f}")
                        else:
                            logger.info(f"💰 [LIVE TRADE] Position closed during disconnect: {symbol} - {close_reason} - P/L: ${calculated_profit:.2f}")
                
                reconnect_count += 1
                last_successful_connection = datetime.now()  # Reset timer after successful reconnect
                
                # Health check: too many reconnects may indicate an internet problem
                if reconnect_count >= max_reconnects_before_reset:
                    logger.warning(f"⚠️ {symbol}: {reconnect_count} reconnects - waiting 60s before continuing")
                    await asyncio.sleep(60)
                    reconnect_count = 0
                
                while True:
                    try:
                        data = await websocket.recv()
                        message = json.loads(data)
                        kline = message['k']
                        if kline['x']:
                            start_time = time.time()
                            open_price = float(kline['o'])
                            close_price = float(kline['c'])
                            high_price = float(kline['h'])
                            low_price = float(kline['l'])
                            volume = float(kline['v'])
                            open_time = kline['t']
                            close_time = kline['T']
                            
                            timestamp = pd.to_datetime(kline['T'], unit='ms')
                            last_candle_time = timestamp  # Update last candle timestamp
                            
                            # Format timestamp as readable date/time
                            formatted_time = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                            
                            # Calculate current score for display
                            current_score = 0
                            if not pd.isna(data1day['RSI'].iloc[-1]) and data1day['RSI'].iloc[-1] > 55:
                                current_score += 5
                            elif not pd.isna(data1day['RSI'].iloc[-1]) and data1day['RSI'].iloc[-1] > 50:
                                current_score += 3
                            if close_price > data1day['SMA'].iloc[-1]:
                                current_score += 3
                            if data1hour['EMA_9'].iloc[-1] > data1hour['EMA_21'].iloc[-1] > data1hour['SMA_50'].iloc[-1]:
                                current_score += 4
                            if data1hour['perDiff'].iloc[-1] > data1hour['avg_perDiff_100_hour'].iloc[-1]:
                                current_score += 2
                            if volume > data15min['Average Volume'].iloc[-1]:
                                current_score += 3
                            if close_price > open_price:
                                current_score += 2
                            
                            print(f"\n{'='*80}")
                            print(f"📊 {symbol} | {formatted_time} | Price: ${close_price:,.2f}")
                            print(f"{'='*80}")
                            print(f"🎯 Strategy Score: {current_score}/19 (threshold: 14)")
                            print(f"🕯️  Candle: {'🟢 Bullish' if close_price > open_price else '🔴 Bearish'} (O: ${open_price:,.2f} → C: ${close_price:,.2f})")
                            print(f"\n📈 Daily Indicators:")
                            print(f"   RSI:        {data1day['RSI'].iloc[-1]:>7.2f} {'✅' if data1day['RSI'].iloc[-1] > 55 else '🟡' if data1day['RSI'].iloc[-1] > 50 else '🔴'}")
                            print(f"   SMA:        ${data1day['SMA'].iloc[-1]:>10,.2f}")
                            print(f"   Close:      ${data1day['close'].iloc[-1]:>10,.2f} {'✅ Above SMA' if data1day['close'].iloc[-1] > data1day['SMA'].iloc[-1] else '🔴 Below SMA'}")
                            
                            print(f"\n⏰ Hourly Indicators:")
                            print(f"   EMA 9:      ${data1hour['EMA_9'].iloc[-1]:>10,.2f}")
                            print(f"   EMA 21:     ${data1hour['EMA_21'].iloc[-1]:>10,.2f}")
                            print(f"   SMA 50:     ${data1hour['SMA_50'].iloc[-1]:>10,.2f}")
                            print(f"   Trend:      {'✅ BULLISH (9>21>50)' if data1hour['EMA_9'].iloc[-1] > data1hour['EMA_21'].iloc[-1] > data1hour['SMA_50'].iloc[-1] else '🔴 BEARISH'}")
                            print(f"   BB Upper:   ${data1hour['BBU'].iloc[-1]:>10,.2f}")
                            print(f"   BB Lower:   ${data1hour['BBL'].iloc[-1]:>10,.2f}")
                            print(f"   BB Width:   {data1hour['perDiff'].iloc[-1]:>7.2f}% (avg: {data1hour['avg_perDiff_100_hour'].iloc[-1]:.2f}%) {'✅' if data1hour['perDiff'].iloc[-1] > data1hour['avg_perDiff_100_hour'].iloc[-1] else '🔴'}")
                            print(f"   ATR:        {data1hour['ATR'].iloc[-1]:>7.2f}%")
                            
                            print(f"\n📊 Volume Analysis:")
                            print(f"   Current:    {volume:>15,.0f}")
                            print(f"   Average:    {data15min['Average Volume'].iloc[-1]:>15,.0f}")
                            print(f"   Ratio:      {volume/data15min['Average Volume'].iloc[-1]:>7.2f}x {'✅ High Volume' if volume > data15min['Average Volume'].iloc[-1] * 1.5 else '🟡 Normal' if volume > data15min['Average Volume'].iloc[-1] else '🔴 Low'}")
                            print(f"{'='*80}\n")
                            
                            # ============================================================================
                            # DAILY PERFORMANCE LOGGING (every day at midnight)
                            # ============================================================================
                            if timestamp.hour == 0 and timestamp.minute == 0:
                                log_daily_performance()
                            
                            # Track which timeframes were updated
                            daily_updated = False
                            hourly_updated = False
                            
                            if timestamp.hour == 0 and timestamp.minute == 59: # exactly at 01:00, just after midnight 
                                new_row = pd.DataFrame({'close': [close_price]})
                                data1day = pd.concat([data1day, new_row], ignore_index=True)
                                data1day['RSI'] = ta.rsi(data1day['close'], length=14)
                                data1day['SMA'] = ta.sma(data1day['close'], length=14)
                                daily_updated = True
                                
                                # Keep at least ~100 rows of daily data
                                if len(data1day) > 110:
                                    data1day = data1day.iloc[-100:]
                                    
                            if timestamp.minute == 59: # closes on the full hour
                                new_row = pd.DataFrame({'high': [high_price], 'low': [low_price], 'close': [close_price]})
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
                                hourly_updated = True
                                
                                # Keep at least ~240 rows (10 days) of hourly data
                                if len(data1hour) > 250:
                                    data1hour = data1hour.iloc[-240:]
                                
                            new_row = pd.DataFrame({'close': [close_price], 'volume': [volume]})
                            data15min = pd.concat([data15min, new_row], ignore_index=True)
                            data15min['Average Volume'] = data15min['volume'].rolling(window=100).mean()
                            
                            # Keep at least ~480 rows (5 days) of 15min data
                            if len(data15min) > 500:
                                data15min = data15min.iloc[-480:]
                            
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
                                        
                                        if PAPER_TRADING:
                                            logger.info(f"📄 [PAPER TRADE] Closed BUY position for {symbol} - StopLoss - Profit: {calculated_profit:.2f}")
                                            print(f"📄 [PAPER TRADE] SL Hit: {symbol} @ ${stopLossPrice:.2f} | P/L: ${calculated_profit:.2f}")
                                        else:
                                            logger.info(f"💰 [LIVE TRADE] Closed BUY position for {symbol} - StopLoss - Profit: {calculated_profit:.2f}")
                                            print(f"💰 [LIVE TRADE] SL Hit: {symbol} @ ${stopLossPrice:.2f} | P/L: ${calculated_profit:.2f}")
                                    
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
                                        
                                        if PAPER_TRADING:
                                            logger.info(f"📄 [PAPER TRADE] Closed BUY position for {symbol} - TakeProfit - Profit: {calculated_profit:.2f}")
                                            print(f"📄 [PAPER TRADE] TP Hit: {symbol} @ ${takeProfitPrice:.2f} | P/L: ${calculated_profit:.2f}")
                                        else:
                                            logger.info(f"💰 [LIVE TRADE] Closed BUY position for {symbol} - TakeProfit - Profit: {calculated_profit:.2f}")
                                            print(f"💰 [LIVE TRADE] TP Hit: {symbol} @ ${takeProfitPrice:.2f} | P/L: ${calculated_profit:.2f}")
                                
                            # ============================================================================
                            # EMERGENCY STOP CHECK
                            # ============================================================================
                            if check_emergency_stop():
                                logger.error(f"⚠️ Emergency stop active - skipping new entries for {symbol}")
                                continue
                            
                            if isBullishConditionMet(close_price, open_price, data1day['RSI'].iloc[-1], data1day['SMA'].iloc[-1], volume,\
                                data15min['Average Volume'].iloc[-1], data1hour['EMA_9'].iloc[-1], data1hour['EMA_21'].iloc[-1],\
                                data1hour['SMA_50'].iloc[-1], data1hour['BBU'].iloc[-1],\
                                data1hour['BBL'].iloc[-1], data1hour['avg_perDiff_100_hour'].iloc[-1]) and activeOrder == False:
                                    
                                    # Check whether we can open a new position
                                    if not can_open_position():
                                        logger.warning(f"Cannot open BUY position for {symbol} - limit reached")
                                        continue
                                    
                                    activeOrder = True
                                    increment_positions()
                                    
                                    if PAPER_TRADING:
                                        logger.info(f"📄 [PAPER TRADE] Executed BUY order for {symbol}")
                                        print(f"📄 [PAPER TRADE] BUY order opened for {symbol}")
                                    else:
                                        logger.info(f"💰 [LIVE TRADE] Executed BUY order for {symbol}")
                                        print(f"💰 [LIVE TRADE] BUY order placed on Binance for {symbol}")
                                    
                                    side = "BUY"
                                    openPrice = close_price
                                    stopLossPercent = 2*data1hour['ATR'].iloc[-1]
                                    stopLossPrice = openPrice - (openPrice/100)*stopLossPercent
                                    takeProfitPrice = openPrice + (openPrice/100)*(stopLossPercent*1.5)
                                    openOrderTime = kline['T']
                                    
                                    # Calculate score for logging
                                    score = 0
                                    if data1day['RSI'].iloc[-1] > 55:
                                        score += 5
                                    elif data1day['RSI'].iloc[-1] > 50:
                                        score += 3
                                    if close_price > data1day['SMA'].iloc[-1]:
                                        score += 3
                                    if data1hour['EMA_9'].iloc[-1] > data1hour['EMA_21'].iloc[-1] > data1hour['SMA_50'].iloc[-1]:
                                        score += 4
                                    if data1hour['perDiff'].iloc[-1] > data1hour['avg_perDiff_100_hour'].iloc[-1]:
                                        score += 2
                                    if volume > data15min['Average Volume'].iloc[-1]:
                                        score += 3
                                    if close_price > open_price:
                                        score += 2
                                    
                                    # Log detailed trade signal to separate file
                                    log_trade_signal(
                                        symbol=symbol,
                                        side="BUY",
                                        entry_price=openPrice,
                                        sl_price=stopLossPrice,
                                        tp_price=takeProfitPrice,
                                        score=score,
                                        rsi_day=data1day['RSI'].iloc[-1],
                                        sma_day=data1day['SMA'].iloc[-1],
                                        close_price_day=data1day['close'].iloc[-1],
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
                        logging.error(f"Error while receiving data: {e}")
                        break
        except websockets.exceptions.ConnectionClosedError as e:
            logger.warning(f"WebSocket closed for {symbol}: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)
        except asyncio.TimeoutError:
            logger.warning(f"WebSocket timeout for {symbol}. Reconnecting...")
            await asyncio.sleep(3)
        except Exception as e:
            logging.error(f"Error connection to websocket: {e}")
            print(e)
            await asyncio.sleep(5)
           
async def main():
    
    # Run these preparations at the start of the hour so they finish before the hour closes.
    
    with open('CryptosForBullish.txt', 'r') as file:
         lines = file.readlines()
    
    lines = [line.strip() for line in lines]
    tasks = [] 
    for symbol in lines:
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