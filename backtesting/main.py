import download_hourly_data
import download_daily_data
import download_15min_data
from split_by_years import split_csv_by_year
from get_trading_pairs import get_pairs
import os


def main():
    # symbols = get_pairs()
    symbols = ['BTCUSDT']
    for symbol in symbols:
        if symbol.endswith("USDT"):
            try:
                print(symbol)
                directory_path = os.path.join(os.getcwd(), "prices", symbol)
                if not os.path.exists(directory_path):
                    os.makedirs(directory_path)
                data1day = download_daily_data.write_data_in_file(symbol)
                if data1day is not None:
                    split_csv_by_year(data1day, directory_path)
                data1hour = download_hourly_data.write_data_in_file(symbol)
                if data1hour is not None:
                    split_csv_by_year(data1hour, directory_path)
                data15min = download_15min_data.write_data_in_file(symbol)
                if data15min is not None:
                    split_csv_by_year(data15min, directory_path)
            except Exception as e:
                print(f"Error for symbol {symbol}: {e}")


if __name__ == "__main__":
    main()