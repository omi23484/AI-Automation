# Working rules for `diff/` (NetPulse)

## 🔒 OFFLINE INVARIANT — always, no exceptions

`diff/netpulse.html` is a **single, fully self-contained, offline-forever** web app.
It must run correctly with the network physically disconnected. This is a hard
product requirement — treat it as non-negotiable in every change.

**Never introduce any of the following** (they break the invariant):

- External `<script src>`, `<link rel="stylesheet">`, or `<link rel="preconnect/dns-prefetch">`
- Web fonts of any kind (Google Fonts / Typekit / `@font-face` with a remote `src`) — use **system font stacks** only
- CDN URLs, `@import url(http…)`, or `url(https://…)` in CSS
- `fetch()`, `XMLHttpRequest`, `WebSocket`, `EventSource`, `navigator.sendBeacon`, `importScripts`, or any other network call
- Remote images/media/iframes, analytics, telemetry, or "phone-home" of any kind
- A build step or package manager for the app itself — it stays a single hand-editable `.html`

**How it's allowed to work instead:** everything inline (CSS in `<style>`, JS in `<script>`);
storage in **IndexedDB**; file parsing with browser-native **DOMParser** + **DecompressionStream**;
downloads via **Blob + `URL.createObjectURL`**; icons as **unicode glyphs**; fonts as **system stacks**.

**Enforcement:** the file ships a `Content-Security-Policy` meta tag with
`default-src 'none'; … connect-src 'none'` so the browser itself blocks any accidental
network reference. If you add a feature, keep the CSP intact and re-run the offline audit:

```bash
grep -nE "https?://(?!schemas\.openxmlformats|www\.w3\.org)|fonts\.google|cdn\.|<script[^>]*src=|<link |@import|fetch\(|XMLHttpRequest|WebSocket|EventSource" diff/netpulse.html
# expect: no matches (OOXML XML namespaces inside the .xlsx writer are literal strings, not fetched)
```

Any UI/UX or design change (including anything from the `ui-ux-pro-max` skill) must be
implemented **offline-safe**: inline SVG or unicode glyphs instead of icon CDNs, system
fonts instead of web fonts, local `data:`/`blob:` assets instead of remote ones.

## Testing

Regression check (Playwright, drives the real page): `node scripts/regression.mjs` from the
repository root. It renders every view, builds every export, and covers maintenance exclusion,
link merge, workspace isolation, storage rollback, and the multi-link PDF/Excel pack — including
a cross-check of its hit counts against the Threshold Report's printed numbers. It asserts zero
console/page errors (CSP violations surface as console errors, so this also guards the offline
invariant) and exits non-zero on any failure. Run it after any change to `netpulse.html`.

Numeric parity of the server-side analytics against this file's engine is separate:
`node scripts/capture-golden.mjs`, then `dotnet test` in `server/tests/NetPulse.Analytics.Tests`.
