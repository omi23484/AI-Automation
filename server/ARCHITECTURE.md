# NetPulse Server — architecture and decision record

Server-side processing, one central store, every user seeing the same data.
This supersedes the browser build's per-user storage; the browser app in
`diff/netpulse.html` remains the reference implementation for the numbers.

## Decisions taken

| # | Decision | Chosen | Consequence |
|---|---|---|---|
| 1 | Runtime | **ASP.NET Core 8 + SQL Server** | Native to IIS; one runtime to patch. The analytics engine is ported from JavaScript to C#, so every number must be proven identical — see *Numeric parity*. |
| 2 | Scale | **Thousands of links, 100M+ samples, growing** | Fact table partitioned by month from day one; the interactive path reads rollups, never raw; rollups recompute incrementally from a dirty set. |
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

## Finding: `busy-weekday` is dead code in the browser engine

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

It is ported faithfully, dead branch included, because parity is the requirement.
Making it live would change the forecast for every business link. That is a
product decision — see *Open questions*.

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
| Ingestion (server-side XLSX parse → staging → MERGE → dirty set) | Not started |
| Rollup builder | Not started |
| Verdict engine, anomaly detection | Not started (ports of `verdictFor`, the day×hour z-score baseline) |
| ASP.NET Core API + Identity | Not started |
| Frontend against the API | Not started |

Everything marked *not started* is ordinary web work. The risky part — proving the
numbers survive the move off JavaScript — is done and defended by tests.

## Open questions

1. **`busy-weekday`:** leave dormant (parity preserved), or make it live and accept
   that forecasts change for business links? If it goes live, the fix is to test
   the weekday/weekend split on the raw series *before* deseasonalising.
2. **Retention.** The schema keeps raw indefinitely. Spec doc 03 §3.1 proposes
   90 days raw / 13 months at 5-minute / 3 years hourly / daily forever. Worth
   settling before the table is large enough to make it painful.
3. **Report generation** currently runs in the browser and prints to PDF. Server-side
   rendering needs a decision on the engine, since there is no headless browser on
   an IIS host by default.
