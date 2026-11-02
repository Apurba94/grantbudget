"""The offline web app."""
from datetime import date

from . import core
from .fieldkit import App, Fail, Raw, bar_chart, card, download, form, h, line_chart, redirect, stats, table

SCHEMA = """
CREATE TABLE IF NOT EXISTS grant_info (id INTEGER PRIMARY KEY CHECK (id = 1), donor TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS lines (code TEXT PRIMARY KEY, name TEXT NOT NULL, budget INTEGER NOT NULL, category TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS spends (id INTEGER PRIMARY KEY, day TEXT NOT NULL, line TEXT NOT NULL REFERENCES lines(code), amount INTEGER NOT NULL, note TEXT NOT NULL DEFAULT '');
"""


def amt(p):
    return f"{p / 100:,.2f}"


def create_app(db="grant.db", today=date.today):
    a = App("GrantBudget", db, SCHEMA, [("Overview", "/"), ("Record spending", "/spend"), ("Budget lines", "/lines"), ("Transfer check", "/transfer"), ("Report", "/report")])

    def info():
        r = a.row("SELECT * FROM grant_info")
        if r is None:
            return None
        return r["donor"], date.fromisoformat(r["start"]), date.fromisoformat(r["end"])

    def lines():
        return [core.Line(r["code"], r["name"], r["budget"], r["category"]) for r in a.rows("SELECT * FROM lines ORDER BY code")]

    def spends():
        return [core.Spend(date.fromisoformat(r["day"]), r["line"], r["amount"], r["note"]) for r in a.rows("SELECT * FROM spends ORDER BY day")]

    @a.route("/", ("GET", "POST"))
    def home(req):
        if req.method == "POST":
            s, e = req.date("start"), req.date("end")
            if e <= s:
                raise Fail("The end must be after the start")
            a.run("INSERT OR REPLACE INTO grant_info (id, donor, start, end) VALUES (1, ?, ?, ?)", req.text("donor"), s, e)
            return redirect("/")
        g = info()
        if g is None:
            return a.page("Set up the grant", card("Grant", form(a, "/", [("donor", "Donor"), ("start", "Start", "date"), ("end", "End", "date")], "Save")))
        donor, start, end = g
        now = today()
        ls, sp = lines(), spends()
        f = core.forecast(ls, sp, start, end, now)
        rows = core.line_report(ls, sp, start, end, now)
        rate, ok = core.overhead_check(ls)
        body = stats([("Budget", amt(f["budget"])), ("Spent", amt(f["spent"])), ("Time used", f"{core.elapsed(start, end, now):.0%}"), ("Forecast at end", amt(f["projected"])), ("Forecast balance", amt(f["variance"]))])
        if f["run_out"]:
            body += f'<div class="flash bad">At this rate the money runs out around {f["run_out"][1]:02d}/{f["run_out"][0]}, before the grant ends.</div>'
        elif f["budget"] and f["share"] < 0.85 and f["spent"]:
            body += f'<div class="flash warn">At this rate {1 - f["share"]:.0%} of the grant would be left unspent.</div>'
        if ls and not ok:
            body += f'<div class="flash bad">Overhead is {rate:.1%} of direct costs, above the 7% default.</div>'
        colour = {"overspent": "bad", "ahead of plan": "warn", "slow": "warn"}
        body += card("Budget lines", table(rows, [("Line", lambda r: f"{r['line'].code} {r['line'].name}"), ("Budget", lambda r: amt(r["line"].budget)), ("Spent", lambda r: amt(r["spent"])), ("Left", lambda r: amt(r["left"])), ("Used", lambda r: "" if r["used"] is None else f"{r['used']:.0%}"), ("State", lambda r: Raw(f'<span class="{colour.get(r["state"], "good")}">{r["state"]}</span>'))], "Add budget lines to begin."))
        body += card("Spending by month", line_chart([(f"{y}-{m:02d}", v / 100) for (y, m), v in core.monthly(sp).items()]))
        return a.page(donor, body)

    @a.route("/lines", ("GET", "POST"))
    def line_page(req):
        if req.method == "POST":
            a.run("INSERT INTO lines (code, name, budget, category) VALUES (?, ?, ?, ?) ON CONFLICT(code) DO UPDATE SET name = excluded.name, budget = excluded.budget, category = excluded.category", req.text("code"), req.text("name"), round(req.number("budget", low=0) * 100), req.text("category"))
            a.log("budget line", req.text("code"))
            return redirect("/lines")
        return a.page("Budget lines", card("Add or change a line", form(a, "/lines", [("code", "Code"), ("name", "Name"), ("budget", "Budget", "number"), ("category", "Category", "select", [("Programme", "Programme"), ("Staff", "Staff"), ("Overhead", "Overhead")])], "Save")) + card("Lines", table(lines(), [("Code", lambda l: l.code), ("Name", lambda l: l.name), ("Budget", lambda l: amt(l.budget)), ("Category", lambda l: l.category)])))

    @a.route("/spend", ("GET", "POST"))
    def spend(req):
        if req.method == "POST":
            d = req.date("day")
            g = info()
            if g and not g[1].isoformat() <= d <= g[2].isoformat():
                raise Fail(f"{d} is outside the grant period, so the donor may not accept it")
            a.run("INSERT INTO spends (day, line, amount, note) VALUES (?, ?, ?, ?)", d, req.text("line"), round(req.number("amount", low=0.01) * 100), req.text("note", False))
            return redirect("/")
        rows = a.rows("SELECT * FROM spends ORDER BY day DESC, id DESC LIMIT 30")
        return a.page("Record spending", card("Spending", form(a, "/spend", [("day", "Date", "date", today().isoformat()), ("line", "Line", "select", [(l.code, f"{l.code} {l.name}") for l in lines()]), ("amount", "Amount", "number"), ("note", "Receipt or note")], "Save")) + card("Latest", table(rows, [("Date", "day"), ("Line", "line"), ("Amount", lambda r: amt(r["amount"])), ("Note", "note")], "No spending recorded.")))

    @a.route("/transfer", ("GET", "POST"))
    def transfer(req):
        note = ""
        if req.method == "POST":
            try:
                ok, text = core.transfer_check(lines(), req.text("source"), req.text("target"), round(req.number("amount", low=0.01) * 100), req.number("limit", 10, 0, 100) / 100)
            except ValueError as exc:
                raise Fail(str(exc)) from None
            note = f'<p class="{"good" if ok else "bad"}">{h(text)}</p>'
        opts = [(l.code, f"{l.code} {l.name}") for l in lines()]
        return a.page("Transfer check", card("Can this move be made without approval?", form(a, "/transfer", [("source", "From", "select", opts), ("target", "To", "select", opts), ("amount", "Amount", "number"), ("limit", "Donor's flexibility limit %", "number", 10)], "Check") + note))

    @a.route("/report")
    def report(req):
        g = info()
        if g is None:
            raise Fail("Set up the grant first")
        rows = core.donor_report(lines(), spends(), g[1], g[2], today())
        total = {k: sum(r[k] for r in rows) for k in ("budget", "period", "to_date", "balance")}
        t = table(rows + [{"code": "", "name": "Total", **total, "used": None}], [("Code", "code"), ("Line", "name"), ("Budget", lambda r: amt(r["budget"])), ("This month", lambda r: amt(r["period"])), ("To date", lambda r: amt(r["to_date"])), ("Balance", lambda r: amt(r["balance"])), ("Used", lambda r: "" if r["used"] is None else f"{r['used']:.0%}")])
        return a.page(f"Financial report: {g[0]}", f'<div class="card">{t}</div><p><a href="/report.csv">Download CSV</a></p>')

    @a.route("/report.csv")
    def report_csv(req):
        g = info()
        if g is None:
            raise Fail("Set up the grant first")
        rows = [[r["code"], r["name"], r["budget"] / 100, r["period"] / 100, r["to_date"] / 100, r["balance"] / 100] for r in core.donor_report(lines(), spends(), g[1], g[2], today())]
        return download(rows, ["code", "line", "budget", "this_month", "to_date", "balance"], "financial-report.csv")

    return a
