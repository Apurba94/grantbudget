import unittest
from datetime import date

from grantbudget import core, create_app
from grantbudget.core import Line, Spend, apply_transfer, elapsed, forecast, line_report, monthly, months_between, overhead_check, transfer_check

S, E = date(2026, 1, 1), date(2026, 12, 31)
L = [Line("A", "Staff", 120000, "Staff"), Line("B", "Supplies", 240000), Line("C", "Overhead", 24000, "Overhead")]


def month_spends(values, line="A", year=2026):
    return [Spend(date(year, i + 1, 15), line, v) for i, v in enumerate(values)]


class TestTime(unittest.TestCase):
    def test_elapsed(self):
        self.assertAlmostEqual(elapsed(S, E, date(2026, 7, 2)), 183 / 365)
        self.assertEqual(elapsed(S, E, date(2025, 1, 1)), 0)
        self.assertEqual(elapsed(S, E, date(2030, 1, 1)), 1)

    def test_months(self):
        self.assertEqual(months_between(S, E), 12)
        self.assertEqual(months_between(date(2026, 11, 1), date(2027, 2, 1)), 4)


class TestLines(unittest.TestCase):
    def state(self, spent, line="A"):
        rows = line_report(L, [Spend(date(2026, 6, 1), line, spent)], S, E, date(2026, 7, 1))
        return next(r for r in rows if r["line"].code == line)["state"]

    def test_states(self):
        self.assertEqual(self.state(60000), "on plan")
        self.assertEqual(self.state(90000), "ahead of plan")
        self.assertEqual(self.state(20000), "slow")
        self.assertEqual(self.state(130000), "overspent")

    def test_zero_budget_line(self):
        rows = line_report([Line("Z", "z", 0)], [Spend(date(2026, 6, 1), "Z", 5)], S, E, date(2026, 7, 1))
        self.assertEqual(rows[0]["state"], "overspent")

    def test_future_spending_is_left_out(self):
        rows = line_report(L, [Spend(date(2026, 12, 1), "A", 5000)], S, E, date(2026, 7, 1))
        self.assertEqual(rows[0]["spent"], 0)


class TestForecast(unittest.TestCase):
    def test_steady_spending(self):
        f = forecast(L, month_spends([32000] * 6), S, E, date(2026, 6, 20))
        self.assertEqual(f["spent"], 192000)
        self.assertEqual(f["projected"], 192000 + 6 * 32000)
        self.assertEqual(f["variance"], 0)

    def test_underspend(self):
        f = forecast(L, month_spends([10000] * 6), S, E, date(2026, 6, 20))
        self.assertLess(f["share"], 0.5)

    def test_run_out_date(self):
        f = forecast(L, month_spends([100000] * 3), S, E, date(2026, 3, 20))
        self.assertGreater(f["projected"], f["budget"])
        self.assertEqual(f["run_out"], (2026, 3))

    def test_one_large_purchase_does_not_swing_the_rate(self):
        f = forecast(L, month_spends([10000, 10000, 200000, 10000]), S, E, date(2026, 4, 20))
        self.assertEqual(f["rate"], 10000)

    def test_nothing_spent(self):
        f = forecast(L, [], S, E, date(2026, 2, 1))
        self.assertEqual((f["spent"], f["projected"]), (0, 0))

    def test_monthly(self):
        self.assertEqual(monthly(month_spends([1, 2])), {(2026, 1): 1, (2026, 2): 2})


class TestRules(unittest.TestCase):
    def test_transfers(self):
        self.assertTrue(transfer_check(L, "B", "A", 12000)[0])
        ok, why = transfer_check(L, "B", "A", 13000)
        self.assertFalse(ok)
        self.assertIn("ask the donor", why)
        self.assertFalse(transfer_check(L, "A", "B", 500000)[0])
        with self.assertRaises(ValueError):
            transfer_check(L, "A", "ZZ", 1)
        with self.assertRaises(ValueError):
            transfer_check(L, "A", "B", 0)

    def test_transfer_keeps_the_total(self):
        new = apply_transfer(L, "B", "A", 5000)
        self.assertEqual(sum(x.budget for x in new), sum(x.budget for x in L))
        self.assertEqual(new[0].budget, 125000)

    def test_overhead(self):
        self.assertEqual(overhead_check(L), (24000 / 360000, True))
        self.assertFalse(overhead_check(L + [Line("D", "More", 50000, "Overhead")])[1])


class TestApp(unittest.TestCase):
    def setUp(self):
        self.a = create_app(":memory:", lambda: date(2026, 7, 1))
        self.a.post("/", donor="Test Donor", start="2026-01-01", end="2026-12-31")
        self.a.post("/lines", code="A", name="Staff", budget=1200, category="Staff")
        self.a.post("/lines", code="B", name="Supplies", budget=2400, category="Programme")

    def text(self, url="/"):
        return self.a.get(url).body.decode()

    def test_first_run_asks_for_the_grant(self):
        self.assertIn("Set up the grant", create_app(":memory:").get("/").body.decode())

    def test_flow(self):
        self.assertEqual(self.a.post("/spend", day="2026-06-01", line="A", amount=600).status, 303)
        page = self.text()
        self.assertIn("Test Donor", page)
        self.assertIn("600.00", page)
        report = self.text("/report")
        self.assertIn("Total", report)
        self.assertIn("A,Staff,1200.0,0.0,600.0,600.0", self.a.get("/report.csv").body.decode())

    def test_outside_the_grant_period_is_refused(self):
        self.assertEqual(self.a.post("/spend", day="2027-01-05", line="A", amount=1).status, 400)

    def test_overrun_warning(self):
        for m in range(1, 7):
            self.a.post("/spend", day=f"2026-{m:02d}-10", line="A", amount=2000)
        self.assertIn("runs out", self.text())

    def test_transfer_page(self):
        self.assertIn("within the flexibility", self.a.post("/transfer", source="B", target="A", amount=100, limit=10).body.decode())
        self.assertIn("ask the donor", self.a.post("/transfer", source="B", target="A", amount=500, limit=10).body.decode())

    def test_bad_grant_dates(self):
        self.assertEqual(self.a.post("/", donor="x", start="2026-12-31", end="2026-01-01").status, 400)


if __name__ == "__main__":
    unittest.main()
