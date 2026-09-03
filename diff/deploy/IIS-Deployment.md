# Hosting NetPulse on Windows IIS

## Read this first: hosting the app is not the same as centralising the data

NetPulse computes everything in the browser and stores everything in the browser
(IndexedDB). Putting the file on IIS gives everyone a **URL instead of an emailed
file** — it does **not** create a shared dataset.

| | On IIS today | What people usually assume |
|---|---|---|
| Where data lives | Each visitor's own browser, on their own PC | One server database |
| Two people, same URL | Two completely separate datasets | The same data |
| Someone clears site data | Their copy is gone | Server copy survives |
| Backup / retention | None — it is browser storage | Server backup |
| Access control | Controls who can open the *page* | Controls who can see the *data* |

That is fine, and even desirable, for one or a few analysts who each work their
own uploads — nothing leaves the machine, so there is no data-at-rest question on
a server at all. It is the wrong shape if you want one upload that the whole team
reports from. See **Where to go from here** at the end.

---

## Option A — static hosting (what this folder configures)

Roughly half a day, no code changes.

### 1. Server prerequisites

Windows Server with the **Web Server (IIS)** role. Role services needed:

- **Static Content** (the only one strictly required)
- **Windows Authentication** — for restricting access to a domain group
- **HTTP Redirection** and the **URL Rewrite** module — for the HTTP→HTTPS rule

You do **not** need ASP.NET, .NET Hosting Bundle, MVC, or a database.

### 2. Lay out the site

```
C:\inetpub\netpulse\
    netpulse.html      <- the app (rename the versioned file to this)
    web.config         <- from this folder
```

Keep the versioned copy (`netpulse-v63.html`) in source control, not in the site
folder — `web.config` only allows `.html` and `.ico` to be served, and only `GET`
and `HEAD`, so nothing else in that directory is reachable anyway.

### 3. Create the site

```powershell
Import-Module WebAdministration

New-Item IIS:\Sites\NetPulse -bindings @{protocol="https";bindingInformation="*:443:netpulse.corp.example"} -physicalPath "C:\inetpub\netpulse"
New-WebAppPool -Name NetPulsePool
Set-ItemProperty IIS:\AppPools\NetPulsePool -Name managedRuntimeVersion -Value ""   # No Managed Code
Set-ItemProperty IIS:\Sites\NetPulse -Name applicationPool -Value NetPulsePool
```

Bind the certificate in IIS Manager (**Site Bindings → https → certificate**), or:

```powershell
New-WebBinding -Name NetPulse -Protocol https -Port 443 -HostHeader netpulse.corp.example
(Get-ChildItem Cert:\LocalMachine\My | Where-Object Subject -like "*netpulse*") |
    New-Item -Path IIS:\SslBindings\0.0.0.0!443
```

An internal CA certificate is fine — it only has to be trusted by the machines
that will open the site.

### 4. HTTPS is not optional here — a measured reason, not a slogan

Browsers withhold a set of APIs from pages that are not a *secure context*.
Measured on this build across three origins:

| Origin | Secure context | `navigator.storage` | Consequence |
|---|---|---|---|
| `file:///…/netpulse.html` | yes | available | full function |
| `http://localhost:8919/…` | yes | available | full function |
| `http://192.0.2.2:8919/…` | **no** | **unavailable** | see below |

Over plain HTTP from a hostname or IP, NetPulse still loads, still parses XLSX and
still stores data — but it **cannot ask the browser to keep that data**
(`navigator.storage.persist()` is gone), so the browser is free to evict a
workspace under disk pressure with no warning, and **Admin → Storage** shows
nothing. Serve it over HTTPS.

### 5. Lock down who can open it

In IIS Manager, on the site:

- **Authentication** → disable *Anonymous Authentication*, enable *Windows
  Authentication*.
- **Authorization Rules** → remove *Allow All Users*, add *Allow → specified
  roles or user groups* → `YOURDOMAIN\NetPulse-Users`.

Everyone is then authenticated as themselves by the domain; the app stores no
credentials of its own, so there is nothing to leak.

Note this authenticates access to the **page**. Since each person's data is in
their own browser profile, it is already isolated per user by the operating
system — the group restriction is about who may run the tool.

### 6. Application pool hardening

- Identity: `ApplicationPoolIdentity` (the default) — do not use a domain account.
- NTFS on `C:\inetpub\netpulse`: `IIS AppPool\NetPulsePool` needs **Read &
  execute** only. It must not have Write. The app never writes to the server.
- Set *Load User Profile* = True, and leave *Enable 32-Bit Applications* = False.

### 7. Verify after deploying

```powershell
# 1. Redirect works
curl.exe -I http://netpulse.corp.example/            # expect 301 to https

# 2. Headers are present
curl.exe -I https://netpulse.corp.example/
#   expect: Content-Security-Policy: frame-ancestors 'none'
#           X-Content-Type-Options: nosniff
#           Referrer-Policy: no-referrer
#   expect NOT: Server: Microsoft-IIS/…  or  X-Powered-By

# 3. Nothing else is reachable
curl.exe -I https://netpulse.corp.example/web.config   # expect 404
curl.exe -I https://netpulse.corp.example/deploy/      # expect 404
```

Then open the site in a browser and check **Admin → Storage** — if it shows a
usage figure and the chip reads `✓ persistent`, the secure context is working.
If it says the browser reports no estimate, you are still on HTTP.

### 8. HSTS

`Strict-Transport-Security` is commented out in `web.config`. Turn it on once
HTTPS is confirmed working — and be aware the header applies to the whole
hostname, so if other things are served from `corp.example` subdomains, agree the
`max-age` and whether to add `includeSubDomains` with whoever owns that DNS name.

### 9. Upgrading

Replace `netpulse.html`. `clientCache` is set to revalidate on every load, so the
next refresh gets the new build — nobody keeps running an old one. The build
number is in the header chip next to the logo, so you can confirm at a glance.

**Data survives an upgrade** (it is in the browser, keyed to the origin, not to
the file), which is exactly why the URL should stay stable. Changing the hostname
strands every user's data behind the old origin.

---

## Where to go from here

If what you actually want is *"one upload, everyone reports from it, backed up"*,
static hosting does not get you there. Two realistic routes:

### Option B — shared library, analytics still in the browser

A thin server-side store for the **source workbooks and configuration only**:
ASP.NET Core (or even a plain file share behind the same IIS site) holding the
uploaded `.xlsx` files plus a small JSON per workspace for thresholds, market
hours and custom fields. The browser fetches them on load and computes exactly as
it does now.

- Central, backed up, access-controlled by AD group — that is the real win.
- No database schema for a million rows; no analytics rewritten server-side.
- Roughly 1–2 weeks. Requires opening `connect-src` from `'none'` to `'self'` in
  the app's CSP, which retires the "runs air-gapped" property.
- Ceiling: each browser still loads the whole dataset to compute, so the practical
  limit stays a few million samples per workspace.

### Option C — full server application

ASP.NET Core + SQL Server, analytics moved server-side, the browser becomes a
view. Central data, row-level access control, real retention and audit, no
per-browser limit.

- 4–8 weeks, and it becomes an application with a lifecycle: patching, backups,
  a DBA conversation, a security review, and someone who owns it.
- Worth it if this is going to serve a team and outlive one person's laptop.

**Recommendation:** deploy Option A now — it is half a day, it is compatible with
both of the others, and it gets people using it from a stable URL. Take the
Option B / C decision on evidence of how many people actually need the *same*
dataset, not up front.
