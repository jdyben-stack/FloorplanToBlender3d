# Investment Tracker

A small, self-contained tool that keeps track of the stocks and funds you own
and summarises gains plus some financial analysis. It needs only Python 3.8+;
`yfinance` is optional (live prices and risk metrics).

## Quick start

```bash
cd InvestmentTracker
python3 portfolio.py                       # summary using data/ sample files
python3 portfolio.py report --html report.html --csv holdings.csv
pip install yfinance                       # optional
python3 portfolio.py report --live --risk  # live prices + risk metrics
```

## Your data

Replace `data/transactions.csv` with your own transactions:

| column     | meaning |
|------------|---------|
| date       | `YYYY-MM-DD` |
| ticker     | e.g. `AAPL`, `VTI` (use Yahoo symbols such as `EQNR.OL` for `--live`) |
| type       | `BUY`, `SELL`, `DIVIDEND`, `SPLIT`, `FEE` |
| quantity   | shares; for `SPLIT` the ratio (10 = 10-for-1); for `DIVIDEND` shares held, or 0 if `price` is the total amount |
| price      | price per share; dividend per share / total; fee amount |
| fees       | commission (for dividends: withholding tax) |
| asset_type, sector, name | optional, used for allocation and display |

Or append from the command line:

```bash
python3 portfolio.py add buy AAPL 5 230.50 --fees 1 --asset-type Stock --sector Technology --name "Apple Inc."
python3 portfolio.py add dividend VTI 0 31.40 --date 2026-09-30
```

Without `--live`, current prices are read from `data/prices.csv`
(`ticker,price`). If neither has a price, the last trade price is used and a
warning is shown.

## What it reports

- **Per holding:** quantity, average cost, price, market value, unrealized gain
  (amount and %), dividends, total return, portfolio weight
- **Portfolio:** market value, cost basis, total invested, net contributions,
  unrealized and realized gains, dividends, fees, total return, and
  **XIRR** (money-weighted annualised return that accounts for when you put money in)
- **Closed positions** with their realized result
- **Allocation** by asset type and sector
- **Diversification:** largest position, effective number of positions
  (1/Herfindahl index), concentration warning, best/worst performers
- **Risk** (`--risk`, needs yfinance): annualised return, volatility, max
  drawdown, beta vs a benchmark (`--benchmark SPY`), and Sharpe ratio for the
  portfolio, benchmark and each holding over `--period` (default `1y`)

Cost basis uses the **average cost method**. Everything is in a single
currency; enter foreign holdings already converted if you mix currencies.

## Tests

```bash
python3 -m unittest discover -s tests
```
