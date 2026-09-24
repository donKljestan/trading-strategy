"""Returns the list of all trading pairs currently listed on Binance."""

import requests


def get_pairs():
    url = "https://api.binance.com/api/v3/exchangeInfo"

    try:
        pairs = []
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        symbols = data.get("symbols", [])

        for symbol_info in symbols:
            if symbol_info.get("status") == "TRADING":
                pairs.append(symbol_info["symbol"])

        return pairs
    except requests.exceptions.RequestException as e:
        print(f"Error fetching trading pairs: {e}")
    return None