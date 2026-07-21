# 16 — Data Center Digital Twin

The Digital Twin is NetPulse's signature navigation experience: instead of scrolling
tables, engineers **move through a visual model of the data center** — Site → Room →
Rack → Device → Line Card → Interface — with health expressed as color at every level.
It is what makes the product feel like an operations center, not a BI tool.

## 1. Navigation hierarchy

```
Site            (campus / DC building — a map or site grid)
  └─ Room       (floor plan of halls / cooling zones)
       └─ Rack  (rack elevation, U-positions, devices seated)
            └─ Device      (front-panel view with modules)
                 └─ Line Card / Module   (slot with ports)
                      └─ Interface        (a port — click → full analytics)
```

Each level is a **zoom** into the previous, with smooth animated transitions
(doc 17) so the mental model of "where am I in the building" is preserved. Breadcrumb +
back gesture always show and retrace the path.

## 2. Health as color (the LED metaphor)

- **Every entity glows with its verdict color** (doc 09 severity tiers): a Site tile,
  a Rack, a Device, and each **interface port LED** reflect health at their altitude.
- **Roll-up coloring:** a level shows the **worst impactful** child state (a Site with
  one Critical trading link is not "green"), tempered by business impact so a Low-impact
  blip doesn't alarm a whole site.
- **Interface LEDs** map directly to verdict/state: Normal (calm cyan/green), Warning
  (amber), High (orange), Critical (red, subtly pulsing). Down/admin-down and
  no-data/maintenance have distinct, unmistakable treatments (never faked as green).
- **At a glance:** an engineer opening the twin sees *where* trouble is before reading a
  single number — spatial triage.

## 3. Interaction model

| Action | Result |
| --- | --- |
| **Hover** any entity | Mini-verdict popover: title, risk, a sparkline, key metric. |
| **Click** a Site/Room/Rack/Device | Zoom one level deeper (animated). |
| **Click** an interface LED | Open the full **Interface Dashboard** (doc 05 §5.5). |
| **Right-click / context** | Quick actions: open dashboard, explain (RCA), add comment, mute, report. |
| **Search / ⌘K jump** | Fly directly to any entity in the twin ("Core-01 Eth1/2"). |
| **Filter overlay** | Recolor the twin by a chosen lens: verdict, risk, class, capacity urgency, customer. |

- **Lens overlays** are powerful: switch the whole twin to "capacity urgency" and the
  ports about to saturate light up; switch to "class = Trading" to see only trading
  links; switch to "customer = ACME" to see one tenant's footprint across racks.

## 4. Front-panel & rack realism

- **Device front-panel view** renders modules/line cards in their slots with ports laid
  out as on the real chassis (port order, breakout ports grouped), so an engineer
  recognizes the hardware.
- **Rack elevation** shows devices at their real U-positions with row/rack labels, so the
  twin doubles as a **spatial inventory** that matches walking the floor.
- Where structural data (room/rack/slot/U) isn't in the source, entities gracefully fall
  back to a **logical layout** (grouped by device/card) — the twin still works with just
  device+interface data, and gets richer as topology data is added.

## 5. Data & performance (100k interfaces in a twin)

- The twin is **level-of-detail (LOD)** rendered: only the currently-focused level's
  entities are drawn in detail; deeper levels load on zoom (lazy). A site view shows
  aggregated room/device health, not 100k individual LEDs at once.
- Health colors come from **pre-computed verdict/risk rollups** (docs 08/09/12), so
  painting the twin is a cheap read, not a live recompute.
- **Virtualized/canvas/WebGL rendering** for dense levels (a device with hundreds of
  ports, a room with many racks) keeps it fluid (doc 17/19).
- **Live-ish refresh:** colors update as new batches/streams land (incremental), with a
  freshness indicator; in the Excel era the twin reflects the latest committed upload.

## 6. Why it matters

- **Faster orientation:** spatial memory ("it's the top-of-rack in R14") beats scanning
  tables for on-call engineers under pressure.
- **Shared language:** NOC, field techs, and architects all point at the same visual
  model.
- **Wall-ready:** the twin (or an Executive/NOC overview derived from it) runs on the NOC
  video wall in fullscreen auto-rotating mode (doc 05 §5.18).
- **Extensible:** environmental overlays (power/thermal), traffic-flow animations between
  links, and topology path highlighting are natural future additions on the same model.
