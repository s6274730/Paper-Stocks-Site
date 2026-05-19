import yfinance as yf


def get_price(ticker):
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


def get_history(ticker, period="1y"):
    ticker = ticker.strip().upper()
    if not ticker:
        return None
    hist = yf.Ticker(ticker).history(period=period)
    if hist.empty:
        return None
    interval_fmt = "%H:%M" if period in ("1d", "5d") else "%Y-%m-%d"
    labels = [d.strftime(interval_fmt) for d in hist.index]
    closes = [float(c) for c in hist["Close"].tolist()]
    return {"labels": labels, "closes": closes}


if __name__ == "__main__":
    print(get_price("AAPL"))
