import yfinance as yf


def get_price(ticker):
    print(ticker)
    ticker = ticker.strip().upper()
    if not ticker:
        return None
    dat = yf.Ticker(ticker)
    info = dat.fast_info
    price = info['last_price']
    if price is None:
        return None
    return {
        "ticker": ticker,
        "price": float(price),
        "currency": info.get("currency") or "USD",
    }


if __name__ == "__main__":
    print(get_price("AAPL"))
