import yfinance as yf
dat = yf.Ticker("AAPL")
print(dat.fast_info['last_price'])
