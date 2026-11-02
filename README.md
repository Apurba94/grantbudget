# GrantBudget

Track a donor grant offline. It shows whether spending is on pace, when the money runs out or how much would go unspent, and whether a shift between budget lines needs the donor's approval.

```
python -m grantbudget
```

Then open http://127.0.0.1:8044. It needs Python 3.10 or newer.

## What it does

- **Budget against actual** by line, with a plain state: on plan, slow, ahead of plan or overspent
- **Time against money:** progress is compared with the share of the grant period used
- **A forecast of the final spend,** with a warning if the money runs out early, or if much would be left unspent
- **A transfer check** against the donor's flexibility limit, since many donors allow moves of up to about 10% of a line
- **An overhead check** of indirect costs against a cap
- **A financial report** in the usual format: budget, this month, to date and balance, with CSV export
- **Dates outside the grant period are refused,** because a donor may not accept them

## Forecasting

The forecast takes the spending so far and adds the median of the last three months for each month left. The median is used so that one large purchase does not swing the rate. It is a simple projection and knows nothing about planned purchases, so use it to raise questions, not to answer them.

## Check your agreement

Flexibility limits, overhead caps and eligible dates differ by donor. The 10% and 7% defaults are placeholders. Your grant agreement always decides.

## How it is tested

Line states, forecasts, transfers and overhead are tested on worked numbers, including a one-off lump, a zero-budget line and future-dated spending. App tests run from setup to the exported report.

## Limits

One grant in one file, in one currency, with no exchange rates or staff time allocation. It does not replace your accounting system.

## Tests

```
python -m unittest discover -s tests
```

MIT licence.
