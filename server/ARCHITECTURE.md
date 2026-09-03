# NetPulse Server — architecture and decision record

Server-side processing, one central store, every user seeing the same data.
This supersedes the browser build's per-user storage; the browser app in
`diff/netpulse.html` remains the reference implementation for the numbers.

## Decisions taken

| # | Decision | Chosen | Consequence |
|---|---|---|---|
| 1 | Runtime | **ASP.NET Core 8 + SQL Server** | Native to IIS; one runtime to patch. The analytics engine is ported from JavaScript to C#, so every number must be proven identical — see *Numeric parity*. |
| 2 | Scale | **Thousands of links, 100M+ samples, growing** | One clustered fact table plus a daily rollup for fleet-wide views. Month partitioning, an hourly tier and incremental dirty-set recompute were cut — see *What was deliberately left out*. |
| 3 | Visibility | **Everyone sees everything** | No scope filter on queries yet. `Interface.ScopeKey` exists and is indexed so per-team or per-customer scoping can be added later without reshaping the schema or rewriting history. |
| 4 | Authentication | **Local accounts in the app** | Built on ASP.NET Core Identity, so password hashing (PBKDF2), lockout, and reset flows are the framework's audited implementation rather than hand-rolled. See *Security notes*. |

## Numeric parity — the central constraint

The server must publish the same numbers as the tool the existing threshold and
regulatory reports were validated against. A report that says 88.5 % in one place
and 88.7 % in another is worse than no report.

So the port is not trusted on inspection. `scripts/capture-golden.mjs` drives the
real browser engine in `diff/netpulse.html` and captures its outputs to
`tests/NetPulse.Analytics.Tests/golden/*.json`; the C# is asserted against those
fixtures to 1e-9.

**Status: 36 tests, all passing** — 24 forecast scenarios, 8 risk scenarios, and
the statistical primitives (percentile at ten quantiles, mean/max/min, rolling
median at three windows, Theil–Sen at three confidence levels).

The suite was mutation-tested rather than assumed adequate. Deliberately breaking
the port — rolling-median window, Theil–Sen stride, slope ceiling, growth floor,
minimum-history gate, backtest gate, upgrade-window floor, the risk curve
exponent, the violations divisor, the impact multiplier — makes it fail every
time. The first round of fixtures missed three of those, which is why boundary
cases were added.

### Regenerating the fixtures

```bash
node scripts/capture-golden.mjs          # drives diff/netpulse.html in Chromium
cd server/tests/NetPulse.Analytics.Tests && dotnet test
```

Fixtures change only when the browser engine's behaviour is deliberately changed.
A fixture diff in a pull request means the published numbers move, and should be
read as carefully as the code.

## Finding: `busy-weekday` was dead code — dropped, no numbers change

While pinning branch boundaries, one mutation could not be made to fail. It turns
out the branch it guards cannot execute.

`forecastFrom()` intends to fit the trend from weekdays only when weekdays run
clearly hotter than weekends. But `rollingMedian(ys, 7)` runs immediately before
the test, and a centred 7-day window over a 5-on/2-off cycle always contains five
weekday values and two weekend values — so its median is the weekday value at
every point, weekend-labelled points included.

Measured against the running engine with a raw 9:1 weekday-to-weekend ratio, both
smoothed medians come out identical at 0.90, so `wdMed > weMed * 1.35 + 0.02` is
false. Irregular patterns do not fire it either. The deseasonalisation destroys
the signal the test looks for.

Consequently no link has ever been forecast on a weekday-only basis and no report
has carried the "busy-weekday" model note.

It is also **redundant**, which is what settles it. The rolling median is already
doing what the branch was trying to do. Fitting weekday-only points instead gives
the same slope to ~1e-19 on clean weekly patterns and 2.5e-6 (0.00025 %/day) on
noisy ones — invisible in any report.

So the branch is simply not ported. The 36 parity tests stayed green through its
removal, which is the proof that no published number moves. The browser build
keeps it (harmless dead code); changing a shipped, validated file for zero
behaviour change would not be worth the re-test.

## Data model notes

Full model in `db/001-schema.sql`. Three choices worth calling out:

**Interface identity is internal, never `ifIndex`.** SNMP renumbers `ifIndex` on a
line-card change; keying history to it would silently re-point a year of samples
at the wrong port.

**Attributes are effective-dated.** Speed, class and business impact change, and
analytics must use the value in force at the sample's timestamp. A 1G→10G upgrade
must not rewrite last year's utilisation percentages.

**Maintenance exclusion is evaluated at query time, never stamped on the sample.**
The browser build stamped it at upload and never re-evaluated, so a window deleted
later left its samples hidden from the chart forever while the audit export still
listed them (fixed there in v60). The server does not repeat the mistake: exclusion
is a join against `MaintenanceWindow`, so edits apply in both directions
immediately.

## Where the work is divided

Heavy aggregation belongs in SQL; only the light statistical layer belongs in C#.
Per-link, per-day p95/avg/peak over 100M rows is a set operation the database does
far better than any loop. What is left for application code — Theil–Sen, the
z-score baseline, verdicts, risk — operates on roughly 180 daily points per link
and is cheap, which is also what makes it straightforward to pin against fixtures.

## Security notes

Local accounts were chosen with the trade-off understood. Two things follow:

- Credential handling is **ASP.NET Core Identity**, not a bespoke user table. Do
  not replace its hasher, lockout or token providers.
- The application therefore stores and must protect credentials. That means a
  password policy, lockout thresholds, and rotation belong in configuration and
  in the security review — obligations that Windows or OIDC authentication would
  have carried for you.

Identity is behind an abstraction so a later move to OIDC changes the
authentication handler and nothing else.

`AuditEvent` is append-only by grant: no application role receives UPDATE or
DELETE on it, so an administrator cannot rewrite history either.

## Status

| Component | State |
|---|---|
| `NetPulse.Analytics` — statistics, forecast, risk, states | **Built and parity-tested** (36 tests green, mutation-checked) |
| `db/001-schema.sql` | **Written, never executed** — no SQL Server was available. Review before trusting. |
| Ingestion (server-side XLSX parse → staging → MERGE) | Not started |
| Nightly rollup MERGE | Not started |
| Verdict engine, anomaly detection | Not started (ports of `verdictFor`, the day×hour z-score baseline) |
| ASP.NET Core API + Identity | Not started |
| Frontend against the API | Not started |

Everything marked *not started* is ordinary web work. The risky part — proving the
numbers survive the move off JavaScript — is done and defended by tests.

## What was deliberately left out

| Cut | Why | Add when |
|---|---|---|
| Month partitioning of `Sample` | It buys cheap archival, which is a retention feature, and retention is undecided. A clustered index on `(InterfaceId, TsUtc)` answers the queries without it. | Retention is agreed and old months need switching out. |
| Hourly rollup tier | The forecast reads daily p95; a single link's chart reads raw off the clustered index and is fast. Nothing asked for an hourly tier. | A view appears that scans many links at hourly resolution. |
| Dirty-set incremental rollup | One nightly full MERGE is a few minutes at 100M samples. The dirty set is an optimisation for a job nobody is waiting on. | The nightly rebuild stops fitting its window, or rollups must be fresh within the day. |

Each is additive — none requires reshaping the schema or rewriting history.

## Open questions

1. **Retention.** The schema keeps raw indefinitely. Spec doc 03 §3.1 proposes
   90 days raw / 13 months at 5-minute / 3 years hourly / daily forever. Worth
   settling before the table is large enough to make it painful.
2. **Report generation** currently runs in the browser and prints to PDF. Server-side
   rendering needs a decision on the engine, since there is no headless browser on
   an IIS host by default.
