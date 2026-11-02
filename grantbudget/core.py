"""Donor budget tracking. Amounts are whole units of currency held as integers in paisa.

The questions a programme manager faces each month: are we on pace, will we run out or
underspend, and does a shift between budget lines need the donor's approval?
"""
from dataclasses import dataclass
from datetime import date


@dataclass
class Line:
    code: str
    name: str
    budget: int
    category: str = "Programme"


@dataclass
class Spend:
    day: date
    line: str
    amount: int
    note: str = ""


def months_between(start, end):
    """Whole months covered, counting both end months."""
    return (end.year - start.year) * 12 + end.month - start.month + 1


def elapsed(start, end, today):
    """Share of the grant period used, by days."""
    span = (end - start).days + 1
    return min(max((today - start).days + 1, 0), span) / span


def actuals(spends, upto=None):
    out = {}
    for s in spends:
        if upto is None or s.day <= upto:
            out[s.line] = out.get(s.line, 0) + s.amount
    return out


def monthly(spends):
    out = {}
    for s in spends:
        k = (s.day.year, s.day.month)
        out[k] = out.get(k, 0) + s.amount
    return dict(sorted(out.items()))


def line_report(lines, spends, start, end, today):
    """One row per line: spent, share used, expected share, and a plain state."""
    act = actuals(spends, today)
    pace = elapsed(start, end, today)
    rows = []
    for l in lines:
        spent = act.get(l.code, 0)
        used = spent / l.budget if l.budget else None
        if l.budget == 0:
            state = "overspent" if spent else "no budget"
        elif spent > l.budget:
            state = "overspent"
        elif used > pace + 0.15:
            state = "ahead of plan"
        elif used < pace - 0.25:
            state = "slow"
        else:
            state = "on plan"
        rows.append({"line": l, "spent": spent, "left": l.budget - spent, "used": used, "pace": pace, "state": state})
    return rows


def forecast(lines, spends, start, end, today, window=3):
    """Project the final spend from the recent monthly rate. A one-off lump can mislead, so the
    recent rate is the median of the last few months, not the mean."""
    budget = sum(l.budget for l in lines)
    months = monthly([s for s in spends if s.day <= today])
    spent = sum(months.values())
    remaining = max(0, months_between(today, end) - 1)
    if not months:
        return {"budget": budget, "spent": 0, "rate": 0, "projected": 0, "variance": budget, "share": 0.0, "run_out": None}
    recent = sorted(list(months.values())[-window:])
    rate = recent[len(recent) // 2]
    projected = spent + rate * remaining
    run_out = None
    if rate > 0 and projected > budget:
        left = budget - spent
        m = today.year * 12 + today.month - 1 + max(left, 0) // rate
        run_out = (m // 12, m % 12 + 1)
    return {"budget": budget, "spent": spent, "rate": rate, "projected": projected, "variance": budget - projected, "share": projected / budget if budget else None, "run_out": run_out}


def transfer_check(lines, source, target, amount, limit=0.10):
    """Many donors allow moves between lines up to a share of the line, without approval.
    The limit differs by donor, so read your own agreement."""
    by = {l.code: l for l in lines}
    if source not in by or target not in by:
        raise ValueError("unknown budget line")
    if amount <= 0:
        raise ValueError("the amount must be above zero")
    if amount > by[source].budget:
        return False, "this is more than the source line holds"
    share = amount / by[target].budget if by[target].budget else float("inf")
    if share > limit:
        return False, f"{share:.0%} of {by[target].name} is above the {limit:.0%} limit, so ask the donor first"
    return True, "within the flexibility limit"


def apply_transfer(lines, source, target, amount):
    out = []
    for l in lines:
        change = (-amount if l.code == source else amount if l.code == target else 0)
        out.append(Line(l.code, l.name, l.budget + change, l.category))
    return out


def overhead_check(lines, cap=0.07):
    """Is the indirect cost share within the rate the donor allows?"""
    direct = sum(l.budget for l in lines if l.category != "Overhead")
    indirect = sum(l.budget for l in lines if l.category == "Overhead")
    rate = indirect / direct if direct else 0.0
    return rate, rate <= cap + 1e-12


def donor_report(lines, spends, start, end, today):
    """A financial statement in the common format: budget, this period, to date, balance."""
    rows = line_report(lines, spends, start, end, today)
    this = actuals([s for s in spends if s.day.year == today.year and s.day.month == today.month])
    return [{"code": r["line"].code, "name": r["line"].name, "budget": r["line"].budget, "period": this.get(r["line"].code, 0), "to_date": r["spent"], "balance": r["left"], "used": r["used"]} for r in rows]
