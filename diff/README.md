# `diff/` — Separate Design Workspace

This folder is intentionally **isolated** from the existing `neteng-toolkit.sh`
application at the repository root. Nothing here modifies, imports, or depends on
the current NetEng Toolkit code.

It contains a **planning-only product specification** for a new, standalone
product:

> **NetPulse** — a Production-Ready Network Analytics & Capacity Planning
> Platform.

No application code is produced here. These are architecture, product, UX, data,
and analytics design documents intended to be handed to an engineering team to
implement as a separate product.

## Contents

| Path | Purpose |
| --- | --- |
| [`network-analytics-platform/`](./network-analytics-platform/) | The full product specification, organized as numbered documents. |

Start at
[`network-analytics-platform/00-INDEX.md`](./network-analytics-platform/00-INDEX.md).

## Why a `diff/` folder

The root of this repository ships the offline NetEng Toolkit. The request that
produced this specification explicitly required the new work to be **separate**
and kept in a **diff folder** so the existing toolkit is never touched or merged
with the new design. Treat this directory as a design "changeset" that can be
reviewed, iterated on, and later spun out into its own repository when
implementation begins.
