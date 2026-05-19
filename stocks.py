import yfinance as yf


class StockService:
    PERIOD_INTERVAL = {
        "1h":  ("1d",  "1m"),
        "1d":  ("1d",  "5m"),
        "1w":  ("5d",  "30m"),
        "1mo": ("1mo", "1d"),
        "3mo": ("3mo", "1d"),
        "6mo": ("6mo", "1d"),
        "1y":  ("1y",  "1d"),
        "5y":  ("5y",  "1wk"),
    }

    def get_price(self, ticker):
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

    def get_history(self, ticker, period="1y"):
        ticker = ticker.strip().upper()
        if not ticker:
            return None
        yf_period, interval = self.PERIOD_INTERVAL.get(period, ("1y", "1d"))
        hist = yf.Ticker(ticker).history(period=yf_period, interval=interval)
        if hist.empty:
            return None
        if period == "1h":
            hist = hist.tail(60)
        intraday = interval.endswith("m") or interval.endswith("h")
        fmt = "%H:%M" if intraday else "%Y-%m-%d"
        labels = [d.strftime(fmt) for d in hist.index]
        closes = [float(c) for c in hist["Close"].tolist()]
        times = [int(d.timestamp() * 1000) for d in hist.index]
        return {"labels": labels, "closes": closes, "times": times, "intraday": intraday}


if __name__ == "__main__":
    print(StockService().get_price("AAPL"))
