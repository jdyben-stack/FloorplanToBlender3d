#!/usr/bin/env python3
"""
Investment Tracker
==================

Keeps track of the stocks and funds you own, based on a simple CSV log of
transactions, and produces a summary with gains and financial analysis.

Transactions file (CSV) columns:
    date        YYYY-MM-DD
    ticker      e.g. AAPL, VTI
    type        BUY | SELL | DIVIDEND | SPLIT | FEE
    quantity    shares (BUY/SELL), split ratio (SPLIT, e.g. 10 for 10-for-1),
                shares held (DIVIDEND, optional - 0 means "price is the total")
    price       price per share (BUY/SELL), dividend per share or total
                amount (DIVIDEND), fee amount (FEE)
    fees        brokerage fees/commission (optional)
    asset_type  Stock, Fund, ETF, Bond ... (optional, used for allocation)
    sector      Technology, Healthcare ... (optional, used for allocation)
    name        Display name (optional)

Current prices come from (first match wins):
    1. --live  : downloads current prices with the optional `yfinance` package
    2. prices.csv (ticker,price)
    3. last transaction price for the ticker (a warning is printed)

Only the Python standard library is required. `yfinance` is optional and
enables live prices and risk metrics (volatility, drawdown, beta, Sharpe).
"""

import argparse
import csv
import html
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TRANSACTIONS = os.path.join(HERE, "data", "transactions.csv")
DEFAULT_PRICES = os.path.join(HERE, "data", "prices.csv")

VALID_TYPES = {"BUY", "SELL", "DIVIDEND", "SPLIT", "FEE"}


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class Transaction:
    date: date
    ticker: str
    type: str
    quantity: float
    price: float
    fees: float = 0.0
    asset_type: str = ""
    sector: str = ""
    name: str = ""


@dataclass
class Holding:
    ticker: str
    name: str = ""
    asset_type: str = "Unknown"
    sector: str = "Unknown"
    quantity: float = 0.0
    cost_basis: float = 0.0  # total cost of shares currently held (incl. fees)
    total_invested: float = 0.0  # all money ever put in (buys + fees)
    realized_gain: float = 0.0
    dividends: float = 0.0
    fees_paid: float = 0.0
    first_buy: date = None
    price: float = 0.0
    price_source: str = ""
    last_trade_price: float = 0.0

    @property
    def avg_cost(self):
        return self.cost_basis / self.quantity if self.quantity else 0.0

    @property
    def market_value(self):
        return self.quantity * self.price

    @property
    def unrealized_gain(self):
        return self.market_value - self.cost_basis

    @property
    def unrealized_pct(self):
        return self.unrealized_gain / self.cost_basis if self.cost_basis else 0.0

    @property
    def total_return(self):
        return self.unrealized_gain + self.realized_gain + self.dividends

    @property
    def total_return_pct(self):
        return self.total_return / self.total_invested if self.total_invested else 0.0

    @property
    def is_open(self):
        return self.quantity > 1e-9


@dataclass
class Portfolio:
    holdings: dict = field(default_factory=dict)
    cash_flows: list = field(default_factory=list)  # (date, amount) investor view
    warnings: list = field(default_factory=list)

    @property
    def open_holdings(self):
        return sorted(
            (h for h in self.holdings.values() if h.is_open),
            key=lambda h: h.market_value,
            reverse=True,
        )

    @property
    def closed_holdings(self):
        return [h for h in self.holdings.values() if not h.is_open]

    def total(self, attr):
        return sum(getattr(h, attr) for h in self.holdings.values())

    @property
    def market_value(self):
        return self.total("market_value")


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def _num(value, default=0.0):
    value = (value or "").strip().replace(",", "")
    return float(value) if value else default


def load_transactions(path):
    transactions = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for line_no, row in enumerate(csv.DictReader(f), start=2):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            if not row.get("ticker"):
                continue
            ttype = row.get("type", "").upper()
            if ttype not in VALID_TYPES:
                raise ValueError(f"{path}:{line_no}: unknown type '{ttype}'")
            transactions.append(
                Transaction(
                    date=datetime.strptime(row["date"], "%Y-%m-%d").date(),
                    ticker=row["ticker"].upper(),
                    type=ttype,
                    quantity=_num(row.get("quantity")),
                    price=_num(row.get("price")),
                    fees=_num(row.get("fees")),
                    asset_type=row.get("asset_type", ""),
                    sector=row.get("sector", ""),
                    name=row.get("name", ""),
                )
            )
    # stable sort keeps file order for same-day transactions
    transactions.sort(key=lambda t: t.date)
    return transactions


def load_prices(path):
    prices = {}
    if path and os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                if row.get("ticker") and row.get("price"):
                    prices[row["ticker"].upper()] = _num(row["price"])
    return prices


def fetch_live_prices(tickers):
    try:
        import yfinance as yf
    except ImportError:
        print("! yfinance not installed (pip install yfinance) - skipping live prices",
              file=sys.stderr)
        return {}
    prices = {}
    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period="5d")
            if not hist.empty:
                prices[t] = float(hist["Close"].iloc[-1])
        except Exception as exc:  # network errors, unknown tickers...
            print(f"! could not fetch {t}: {exc}", file=sys.stderr)
    return prices


# --------------------------------------------------------------------------- #
# Portfolio construction (average cost method)
# --------------------------------------------------------------------------- #
def build_portfolio(transactions, prices=None, live_prices=None):
    pf = Portfolio()
    prices = prices or {}
    live_prices = live_prices or {}

    for t in transactions:
        h = pf.holdings.setdefault(t.ticker, Holding(ticker=t.ticker))
        if t.name:
            h.name = t.name
        if t.asset_type:
            h.asset_type = t.asset_type
        if t.sector:
            h.sector = t.sector

        if t.type == "BUY":
            cost = t.quantity * t.price + t.fees
            h.quantity += t.quantity
            h.cost_basis += cost
            h.total_invested += cost
            h.fees_paid += t.fees
            h.first_buy = h.first_buy or t.date
            h.last_trade_price = t.price
            pf.cash_flows.append((t.date, -cost))

        elif t.type == "SELL":
            if t.quantity > h.quantity + 1e-9:
                pf.warnings.append(
                    f"{t.date} {t.ticker}: selling {t.quantity} but only {h.quantity:g} held")
            qty = min(t.quantity, h.quantity)
            proceeds = qty * t.price - t.fees
            cost_removed = h.avg_cost * qty
            h.realized_gain += proceeds - cost_removed
            h.cost_basis -= cost_removed
            h.quantity -= qty
            h.fees_paid += t.fees
            h.last_trade_price = t.price
            pf.cash_flows.append((t.date, proceeds))

        elif t.type == "DIVIDEND":
            amount = t.quantity * t.price if t.quantity else t.price
            amount -= t.fees  # e.g. withholding tax
            h.dividends += amount
            pf.cash_flows.append((t.date, amount))

        elif t.type == "SPLIT":
            if t.quantity <= 0:
                pf.warnings.append(f"{t.date} {t.ticker}: split ratio must be > 0")
                continue
            h.quantity *= t.quantity
            h.last_trade_price /= t.quantity

        elif t.type == "FEE":
            amount = t.price + t.fees
            h.realized_gain -= amount
            h.fees_paid += amount
            pf.cash_flows.append((t.date, -amount))

    for ticker, h in pf.holdings.items():
        if ticker in live_prices:
            h.price, h.price_source = live_prices[ticker], "live"
        elif ticker in prices:
            h.price, h.price_source = prices[ticker], "prices.csv"
        else:
            h.price, h.price_source = h.last_trade_price, "last trade"
            if h.is_open:
                pf.warnings.append(
                    f"{ticker}: no current price, using last trade price {h.price:.2f}")
    return pf


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #
def xirr(cash_flows, guess=0.1):
    """Money-weighted annualised return (like Excel's XIRR)."""
    if not cash_flows:
        return None
    if not (any(a < 0 for _, a in cash_flows) and any(a > 0 for _, a in cash_flows)):
        return None
    d0 = min(d for d, _ in cash_flows)

    def npv(rate):
        return sum(a / (1 + rate) ** ((d - d0).days / 365.0) for d, a in cash_flows)

    # bisection is slow but robust
    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def allocation(pf, attr):
    total = pf.market_value
    groups = defaultdict(float)
    for h in pf.open_holdings:
        groups[getattr(h, attr) or "Unknown"] += h.market_value
    return sorted(((k, v, v / total if total else 0) for k, v in groups.items()),
                  key=lambda x: x[1], reverse=True)


def analyze(pf, as_of=None):
    as_of = as_of or date.today()
    mv = pf.market_value
    open_h = pf.open_holdings
    weights = [h.market_value / mv for h in open_h] if mv else []

    flows = list(pf.cash_flows)
    if mv:
        flows.append((as_of, mv))  # pretend we sell everything today

    invested = pf.total("total_invested")
    total_return = pf.total("total_return")
    first = min((d for d, _ in pf.cash_flows), default=None)

    return {
        "as_of": as_of,
        "market_value": mv,
        "cost_basis": pf.total("cost_basis"),
        "total_invested": invested,
        "unrealized_gain": pf.total("unrealized_gain"),
        "realized_gain": pf.total("realized_gain"),
        "dividends": pf.total("dividends"),
        "fees": pf.total("fees_paid"),
        "total_return": total_return,
        "total_return_pct": total_return / invested if invested else 0.0,
        "net_contributions": -sum(a for _, a in pf.cash_flows),
        "xirr": xirr(flows),
        "years_invested": (as_of - first).days / 365.0 if first else 0.0,
        "positions": len(open_h),
        "largest_position": (open_h[0].ticker, weights[0]) if open_h else None,
        # Herfindahl index: 1/N for perfectly equal weights, 1.0 for one position
        "hhi": sum(w * w for w in weights),
        "effective_positions": 1 / sum(w * w for w in weights) if weights else 0,
        "winners": [h for h in open_h if h.unrealized_gain > 0],
        "losers": [h for h in open_h if h.unrealized_gain < 0],
        "by_asset_type": allocation(pf, "asset_type"),
        "by_sector": allocation(pf, "sector"),
    }


def risk_metrics(pf, benchmark="SPY", period="1y", risk_free=0.04):
    """Volatility, max drawdown, beta and Sharpe from daily prices (needs yfinance)."""
    try:
        import yfinance as yf
    except ImportError:
        print("! yfinance not installed (pip install yfinance) - skipping risk metrics",
              file=sys.stderr)
        return None

    open_h = pf.open_holdings
    tickers = [h.ticker for h in open_h]
    try:
        data = yf.download(tickers + [benchmark], period=period, auto_adjust=True,
                           progress=False)["Close"].dropna(how="all").ffill().dropna()
    except Exception as exc:
        print(f"! could not download history: {exc}", file=sys.stderr)
        return None
    if data.empty:
        return None

    rets = data.pct_change().dropna()
    bench = rets[benchmark]
    mv = pf.market_value
    weights = {h.ticker: h.market_value / mv for h in open_h if h.ticker in rets}
    port = sum(rets[t] * w for t, w in weights.items())

    def stats(series, prices=None):
        ann_ret = (1 + series).prod() ** (252 / len(series)) - 1
        vol = series.std() * math.sqrt(252)
        cum = (1 + series).cumprod()
        mdd = (cum / cum.cummax() - 1).min()
        beta = series.cov(bench) / bench.var() if bench.var() else float("nan")
        sharpe = (ann_ret - risk_free) / vol if vol else float("nan")
        return {"return": ann_ret, "volatility": vol, "max_drawdown": mdd,
                "beta": beta, "sharpe": sharpe}

    result = {"period": period, "benchmark": benchmark, "risk_free": risk_free,
              "portfolio": stats(port), "benchmark_stats": stats(bench), "holdings": {}}
    for t in weights:
        result["holdings"][t] = stats(rets[t])
    corr = rets[list(weights)].corr()
    result["correlation"] = corr
    return result


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def money(x):
    return f"{x:,.2f}"


def pct(x):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:+.2f}%"


def table(headers, rows, aligns=None):
    aligns = aligns or ["<"] + [">"] * (len(headers) - 1)
    widths = [max(len(str(c)) for c in col) for col in zip(headers, *rows)]
    fmt = "  ".join(f"{{:{a}{w}}}" for a, w in zip(aligns, widths))
    lines = [fmt.format(*headers), "  ".join("-" * w for w in widths)]
    lines += [fmt.format(*map(str, r)) for r in rows]
    return "\n".join(lines)


def holding_rows(pf, mv):
    return [
        [h.ticker, (h.name or "")[:28], h.asset_type, f"{h.quantity:g}", money(h.avg_cost),
         money(h.price), money(h.market_value), money(h.unrealized_gain),
         pct(h.unrealized_pct), money(h.dividends), money(h.total_return),
         f"{h.market_value / mv * 100:.1f}%" if mv else "-"]
        for h in pf.open_holdings
    ]


HOLDING_HEADERS = ["Ticker", "Name", "Type", "Qty", "Avg cost", "Price", "Value",
                   "Unrealized", "Unreal %", "Dividends", "Total return", "Weight"]


def print_report(pf, a, risk=None):
    out = []
    w = out.append
    w("=" * 78)
    w(f" PORTFOLIO SUMMARY  (as of {a['as_of']})")
    w("=" * 78)
    summary = [
        ("Market value", money(a["market_value"])),
        ("Cost basis (current holdings)", money(a["cost_basis"])),
        ("Total ever invested", money(a["total_invested"])),
        ("Net contributions (in - out)", money(a["net_contributions"])),
        ("Unrealized gain", f"{money(a['unrealized_gain'])}  "
                            f"({pct(a['unrealized_gain'] / a['cost_basis'] if a['cost_basis'] else 0)})"),
        ("Realized gain", money(a["realized_gain"])),
        ("Dividends received", money(a["dividends"])),
        ("Fees paid", money(a["fees"])),
        ("TOTAL RETURN", f"{money(a['total_return'])}  ({pct(a['total_return_pct'])})"),
        ("Annualised return (XIRR)", pct(a["xirr"])),
        ("Years invested", f"{a['years_invested']:.1f}"),
    ]
    for k, v in summary:
        w(f"  {k:<32} {v:>22}")

    w("\nHOLDINGS")
    w(table(HOLDING_HEADERS, holding_rows(pf, a["market_value"]),
            ["<", "<", "<"] + [">"] * 9))

    closed = pf.closed_holdings
    if closed:
        w("\nCLOSED POSITIONS")
        w(table(["Ticker", "Realized", "Dividends", "Total return"],
                [[h.ticker, money(h.realized_gain), money(h.dividends), money(h.total_return)]
                 for h in closed]))

    for title, key in (("ALLOCATION BY ASSET TYPE", "by_asset_type"),
                       ("ALLOCATION BY SECTOR", "by_sector")):
        w(f"\n{title}")
        for name, value, share in a[key]:
            bar = "#" * round(share * 40)
            w(f"  {name:<18} {money(value):>14} {share * 100:6.1f}%  {bar}")

    w("\nDIVERSIFICATION")
    if a["largest_position"]:
        t, wt = a["largest_position"]
        w(f"  Largest position: {t} ({wt * 100:.1f}% of portfolio)")
    w(f"  Positions: {a['positions']}, effective positions (1/HHI): "
      f"{a['effective_positions']:.1f}")
    if a["hhi"] > 0.25:
        w("  ! Portfolio is concentrated (HHI > 0.25)")
    w(f"  Winners: {len(a['winners'])}   Losers: {len(a['losers'])}")
    open_h = pf.open_holdings
    if open_h:
        best = max(open_h, key=lambda h: h.unrealized_pct)
        worst = min(open_h, key=lambda h: h.unrealized_pct)
        w(f"  Best performer:  {best.ticker} {pct(best.unrealized_pct)}")
        w(f"  Worst performer: {worst.ticker} {pct(worst.unrealized_pct)}")

    if risk:
        w(f"\nRISK METRICS  (last {risk['period']}, daily data, benchmark {risk['benchmark']}, "
          f"risk-free {risk['risk_free'] * 100:.1f}%)")
        rows = [["PORTFOLIO", *_risk_cells(risk["portfolio"])],
                [risk["benchmark"], *_risk_cells(risk["benchmark_stats"])]]
        rows += [[t, *_risk_cells(s)] for t, s in risk["holdings"].items()]
        w(table(["", "Return", "Volatility", "Max DD", "Beta", "Sharpe"], rows))

    if pf.warnings:
        w("\nWARNINGS")
        for msg in pf.warnings:
            w(f"  ! {msg}")
    print("\n".join(out))


def _risk_cells(s):
    return [pct(s["return"]), f"{s['volatility'] * 100:.2f}%", pct(s["max_drawdown"]),
            f"{s['beta']:.2f}", f"{s['sharpe']:.2f}"]


def write_holdings_csv(pf, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["ticker", "name", "asset_type", "sector", "quantity", "avg_cost",
                     "cost_basis", "price", "price_source", "market_value",
                     "unrealized_gain", "unrealized_pct", "realized_gain", "dividends",
                     "total_return"])
        for h in pf.holdings.values():
            wr.writerow([h.ticker, h.name, h.asset_type, h.sector, round(h.quantity, 6),
                         round(h.avg_cost, 4), round(h.cost_basis, 2), h.price,
                         h.price_source, round(h.market_value, 2),
                         round(h.unrealized_gain, 2), round(h.unrealized_pct, 4),
                         round(h.realized_gain, 2), round(h.dividends, 2),
                         round(h.total_return, 2)])


def write_html(pf, a, path, risk=None):
    e = html.escape

    def cls(x):
        return "pos" if x > 0 else "neg" if x < 0 else ""

    cards = [
        ("Market value", money(a["market_value"]), 0),
        ("Total return", f"{money(a['total_return'])} ({pct(a['total_return_pct'])})",
         a["total_return"]),
        ("Unrealized", money(a["unrealized_gain"]), a["unrealized_gain"]),
        ("Realized", money(a["realized_gain"]), a["realized_gain"]),
        ("Dividends", money(a["dividends"]), a["dividends"]),
        ("XIRR (annualised)", pct(a["xirr"]), a["xirr"] or 0),
    ]
    card_html = "".join(
        f'<div class="card"><div class="lbl">{e(k)}</div>'
        f'<div class="val {cls(s)}">{e(v)}</div></div>' for k, v, s in cards)

    rows = ""
    for h in pf.open_holdings:
        mv = a["market_value"]
        rows += (
            f"<tr><td><b>{e(h.ticker)}</b><br><small>{e(h.name)}</small></td>"
            f"<td>{e(h.asset_type)}</td><td>{h.quantity:g}</td><td>{money(h.avg_cost)}</td>"
            f"<td>{money(h.price)}</td><td>{money(h.market_value)}</td>"
            f'<td class="{cls(h.unrealized_gain)}">{money(h.unrealized_gain)}<br>'
            f"<small>{pct(h.unrealized_pct)}</small></td>"
            f"<td>{money(h.dividends)}</td>"
            f'<td class="{cls(h.total_return)}">{money(h.total_return)}</td>'
            f"<td>{h.market_value / mv * 100 if mv else 0:.1f}%</td></tr>")

    def alloc(items):
        return "".join(
            f'<div class="arow"><span>{e(n)}</span><div class="bar">'
            f'<div style="width:{s * 100:.1f}%"></div></div><span>{s * 100:.1f}%</span></div>'
            for n, _, s in items)

    risk_html = ""
    if risk:
        rr = [("Portfolio", risk["portfolio"]), (risk["benchmark"], risk["benchmark_stats"])]
        rr += list(risk["holdings"].items())
        risk_html = (
            f"<h2>Risk ({e(risk['period'])}, vs {e(risk['benchmark'])})</h2><table>"
            "<tr><th></th><th>Return</th><th>Volatility</th><th>Max DD</th><th>Beta</th>"
            "<th>Sharpe</th></tr>" + "".join(
                f"<tr><td>{e(n)}</td>" + "".join(f"<td>{e(c)}</td>" for c in _risk_cells(s))
                + "</tr>" for n, s in rr) + "</table>")

    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Portfolio Summary</title><style>
:root{{--bg:#f7f7f5;--fg:#1d1d1b;--card:#fff;--muted:#6b6b66;--line:#e3e3df;--acc:#2f6fdf;--pos:#1b8a4a;--neg:#c23b3b}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--fg:#ececea;--card:#1f1f1d;--muted:#9a9a94;--line:#33332f;--acc:#6e9cf0;--pos:#4cc27f;--neg:#ec6b6b}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0;padding:24px 16px;}}
main{{max-width:1100px;margin:auto}} h1{{margin:0 0 4px}} .muted{{color:var(--muted)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:20px 0}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}}
.lbl{{color:var(--muted);font-size:13px}} .val{{font-size:20px;font-weight:600;font-variant-numeric:tabular-nums}}
.pos{{color:var(--pos)}} .neg{{color:var(--neg)}}
.scroll{{overflow-x:auto}} table{{width:100%;border-collapse:collapse;background:var(--card);font-variant-numeric:tabular-nums}}
th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}} th{{color:var(--muted);font-weight:500}}
.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:24px}}
.arow{{display:grid;grid-template-columns:120px 1fr 56px;gap:8px;align-items:center;margin:6px 0}}
.bar{{background:var(--line);border-radius:4px;height:10px}} .bar div{{background:var(--acc);height:100%;border-radius:4px}}
</style></head><body><main>
<h1>Portfolio Summary</h1><div class="muted">As of {a['as_of']} &middot; {a['positions']} positions
&middot; {a['years_invested']:.1f} years invested</div>
<div class="cards">{card_html}</div>
<h2>Holdings</h2><div class="scroll"><table><tr><th>Holding</th><th>Type</th><th>Qty</th>
<th>Avg cost</th><th>Price</th><th>Value</th><th>Unrealized</th><th>Dividends</th>
<th>Total return</th><th>Weight</th></tr>{rows}</table></div>
<div class="grid2"><div><h2>By asset type</h2>{alloc(a['by_asset_type'])}</div>
<div><h2>By sector</h2>{alloc(a['by_sector'])}</div></div>
<div class="scroll">{risk_html}</div>
<p class="muted">Effective number of positions: {a['effective_positions']:.1f}.
Cost basis uses the average cost method.</p>
</main></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def add_transaction(path, args):
    exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        if not exists:
            wr.writerow(["date", "ticker", "type", "quantity", "price", "fees",
                         "asset_type", "sector", "name"])
        wr.writerow([args.date, args.ticker.upper(), args.type.upper(), args.quantity,
                     args.price, args.fees, args.asset_type, args.sector, args.name])
    print(f"Added {args.type.upper()} {args.ticker.upper()} to {path}")


def main(argv=None):
    p = argparse.ArgumentParser(description="Track your stocks and funds.")
    p.add_argument("-t", "--transactions", default=DEFAULT_TRANSACTIONS)
    p.add_argument("-p", "--prices", default=DEFAULT_PRICES)
    sub = p.add_subparsers(dest="cmd")

    rep = sub.add_parser("report", help="show portfolio summary (default)")
    rep.add_argument("--live", action="store_true", help="fetch live prices (yfinance)")
    rep.add_argument("--risk", action="store_true",
                     help="volatility/drawdown/beta/Sharpe (yfinance)")
    rep.add_argument("--benchmark", default="SPY")
    rep.add_argument("--period", default="1y", help="history period for --risk")
    rep.add_argument("--html", help="also write an HTML report to this file")
    rep.add_argument("--csv", help="also write holdings to this CSV file")

    add = sub.add_parser("add", help="append a transaction")
    add.add_argument("type", choices=sorted(t.lower() for t in VALID_TYPES))
    add.add_argument("ticker")
    add.add_argument("quantity", type=float)
    add.add_argument("price", type=float)
    add.add_argument("--date", default=date.today().isoformat())
    add.add_argument("--fees", type=float, default=0.0)
    add.add_argument("--asset-type", default="")
    add.add_argument("--sector", default="")
    add.add_argument("--name", default="")

    args = p.parse_args(argv)
    if args.cmd == "add":
        add_transaction(args.transactions, args)
        return 0
    if args.cmd is None:
        args = p.parse_args((argv or sys.argv[1:]) + ["report"])

    transactions = load_transactions(args.transactions)
    tickers = sorted({t.ticker for t in transactions})
    live = fetch_live_prices(tickers) if args.live else {}
    pf = build_portfolio(transactions, load_prices(args.prices), live)
    a = analyze(pf)
    risk = risk_metrics(pf, args.benchmark, args.period) if args.risk else None

    print_report(pf, a, risk)
    if args.html:
        write_html(pf, a, args.html, risk)
        print(f"\nHTML report written to {args.html}")
    if args.csv:
        write_holdings_csv(pf, args.csv)
        print(f"Holdings written to {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
