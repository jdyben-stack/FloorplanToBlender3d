import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import portfolio as p  # noqa: E402


def tx(d, ticker, ttype, qty, price, fees=0.0):
    return p.Transaction(date.fromisoformat(d), ticker, ttype, qty, price, fees)


class PortfolioTests(unittest.TestCase):
    def test_average_cost_and_realized_gain(self):
        pf = p.build_portfolio([
            tx("2024-01-01", "ABC", "BUY", 10, 100, 1),
            tx("2024-02-01", "ABC", "BUY", 10, 120, 1),
            tx("2024-03-01", "ABC", "SELL", 5, 150, 1),
        ], prices={"ABC": 130})
        h = pf.holdings["ABC"]
        self.assertAlmostEqual(h.quantity, 15)
        self.assertAlmostEqual(h.avg_cost, 110.1)  # (1001 + 1201) / 20
        self.assertAlmostEqual(h.realized_gain, 749 - 5 * 110.1)
        self.assertAlmostEqual(h.unrealized_gain, 15 * 130 - 15 * 110.1)

    def test_split_and_dividend(self):
        pf = p.build_portfolio([
            tx("2024-01-01", "XYZ", "BUY", 2, 1000),
            tx("2024-06-01", "XYZ", "SPLIT", 10, 0),
            tx("2024-07-01", "XYZ", "DIVIDEND", 20, 0.5),
            tx("2024-08-01", "XYZ", "DIVIDEND", 0, 7),
        ], prices={"XYZ": 110})
        h = pf.holdings["XYZ"]
        self.assertAlmostEqual(h.quantity, 20)
        self.assertAlmostEqual(h.avg_cost, 100)
        self.assertAlmostEqual(h.dividends, 17)
        self.assertAlmostEqual(h.total_return, 200 + 17)

    def test_missing_price_falls_back_to_last_trade(self):
        pf = p.build_portfolio([tx("2024-01-01", "Q", "BUY", 1, 50)])
        self.assertEqual(pf.holdings["Q"].price_source, "last trade")
        self.assertTrue(pf.warnings)

    def test_xirr_simple_doubling(self):
        r = p.xirr([(date(2020, 1, 1), -100), (date(2021, 1, 1), 110)])
        self.assertAlmostEqual(r, 0.0997, places=3)  # 366-day year

    def test_sample_report_runs(self):
        self.assertEqual(p.main(["report"]), 0)


if __name__ == "__main__":
    unittest.main()
