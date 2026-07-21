# 18 — Security & RBAC Model

NetPulse is deployed in mission-critical NOCs, so security and auditability are
first-class, not afterthoughts. The model covers **who can see/do what**, **complete
auditing**, and **data protection** — with everything configurable and traceable.

## 1. Roles (RBAC)

| Role | Can see | Can do | Cannot |
| --- | --- | --- | --- |
| **Admin** | Everything | Manage users/roles, rules, thresholds, calendars, classifications, maintenance, data sources, retention; all operations | — |
| **Architect** | Everything (analytics) | Capacity/trend analysis, generate/schedule reports, classify interfaces, propose thresholds | User mgmt, destructive admin |
| **L3 (NOC Lead)** | All operational data | Triage, RCA, ack/mute (bounded), annotate, comment, generate reports, define maintenance | Rule/threshold/user admin (unless delegated) |
| **L2 (NOC Eng)** | Assigned scope + operational data | Triage assigned, RCA, annotate/comment, attach KB, ack | Change rules/thresholds, manage users, define maintenance |
| **NOC** | Operational dashboards | View, acknowledge, comment | Config, exports of restricted scope |
| **Read-Only** | Permitted dashboards/reports | View + export within scope | Any change |
| **Viewer** | High-level dashboards | View only | Export/change |

- **Least privilege** by default; capabilities are additive permissions grouped into
  roles. Roles are **customizable** (create custom roles from the permission set).
- **Scoped access:** a role can be constrained to a **scope** (site/customer/class), so
  a customer-facing L2 sees only that customer's interfaces. Multi-tenancy is achievable
  by scoping (an MSP/ISP use case).

## 2. Permission model

- Fine-grained **permissions** (e.g., `verdict.view`, `rule.edit`, `maintenance.create`,
  `report.export`, `user.manage`, `assistant.query`) assigned to roles.
- **Scope filters** attach to assignments: `role=L2, scope=customer:ACME`.
- Every data query, report, and AI answer is **filtered by the caller's effective scope**
  — enforced server-side, not just hidden in the UI.

## 3. Authentication & session

- **SSO/enterprise identity:** SAML / OIDC integration; SCIM for user/role provisioning.
- **MFA** supported/enforced by policy.
- **Session security:** short-lived tokens, refresh, idle timeout, device/session
  listing and revocation.
- **Service accounts / API keys** (for future integrations) are scoped and rotatable.

## 4. Audit trail (complete, append-only)

Every meaningful action is recorded immutably (doc 03 `audit_event`):

| Category | Examples audited |
| --- | --- |
| **Data** | Uploads, batch supersede, validation decisions, deletions/decommissions. |
| **Config** | Rule changes, threshold changes, calendar/holiday edits, classification/policy changes, maintenance windows. |
| **User actions** | Acks, mutes (with reason + expiry), comments, annotations. |
| **Access** | Logins, failed logins, role/scope changes, permission grants. |
| **Outputs** | Exports, report generation, AI queries + returned scope. |
| **Admin** | User lifecycle, source/adapter config, retention changes. |

Each entry captures **who, when, role, action, target, before→after, source IP, and
references** (batch/report/case). The **Audit Logs** screen (doc 05 §5.13) is read-only
for everyone (even Admin can't rewrite it), filterable, and exportable as compliance
evidence. Verdicts, forecasts, and reports stamp the ruleset/model version used, so the
audit + versioning together make any past state reproducible.

## 5. Data protection

- **Encryption:** TLS in transit; encryption at rest for stored samples, uploads, and
  derived data. Original uploaded files stored in encrypted object storage.
- **Tenancy isolation:** scope enforcement + optional per-tenant data partitioning for
  MSP/ISP deployments.
- **Secrets:** future integration credentials (SNMP communities, API tokens) stored in a
  secrets vault, never in plain config; scoped and rotatable.
- **Retention & purge:** configurable retention per tier (doc 03 §3.1); decommission vs
  purge, with purge always audited. Supports data-minimization/regulatory needs.
- **PII posture:** the data is primarily network telemetry (low PII), but user accounts,
  comments, and customer mappings are protected and access-controlled.

## 6. AI-specific security (doc 13)

- Assistant queries are **scope-enforced** (only authorized entities) and **audited**.
- **On-prem/self-hosted model option** so sensitive telemetry never leaves the
  environment.
- **Prompt-injection resistance:** external/free-text content (comments, KB, uploaded
  descriptions, filenames) is treated as untrusted data, not instructions.
- The assistant is **read-only**; any future action-taking requires explicit permission +
  confirmation + audit.

## 7. Operational security & hardening

- **RBAC enforced server-side** on every API; UI hiding is convenience, not the control.
- **Rate limiting / abuse protection** on uploads, exports, and AI queries.
- **Change safety:** rules/thresholds are versioned with dry-run/backtest (doc 07) and
  are reversible — reducing the risk of a bad policy change causing an alert storm or
  blind spot.
- **Separation of duties:** the platform recommends and reports; it does **not** execute
  network changes in v1, minimizing blast radius. Any future actioning is gated behind
  the strictest permissions and full audit.
