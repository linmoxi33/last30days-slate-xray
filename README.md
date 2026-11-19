# slate-xray

Event-level concentration audit for a real `last30days` v4 run: it rebuilds the ranked story slate from the canonical output and shows whether one event took more slots than the documented cap of three.

Upstream: https://github.com/mvanhorn/last30days-skill

Why now: `last30days` ranks ~190 evidence items into a top-8 slate, and its own 4.0.1 Microsoft run printed eight outage/buyout clusters while earnings and AI stories sat only in the raw file. The maintainer fixed ordering in 4.0.2 but explicitly deferred the case this tool measures: *"headlines about one event worded very differently ... can still take more than 3 slots when no subquery names the event."*

## What the upstream does and what is missing

`last30days` (70k+ stars, MIT) searches Reddit, X, YouTube, HN, Polymarket and more, scores items, and prints a `## Ranked Evidence Clusters` block. Its documented rule is that one story takes at most 3 of the top 8 slots ([issue #1449](https://github.com/mvanhorn/last30days-skill/issues/1449), maintainer comment, 2026-11-15). There is no offline check that the emitted slate actually obeys that rule: the check runs inside an LLM-authored pipeline and depends on subquery names.

This tool reads the saved canonical text instead, so the check is deterministic, offline, and repeatable on any past run.

## What it does / does not do

- Parses `## Ranked Evidence Clusters` (titles, scores, sources, item dates).
- Groups clusters into events with an IDF-weighted title-overlap pass; tokens present in every title (the topic entity) get weight 0.
- Reports slots per event, top-event share, distinct-event ratio.
- Flags: `event-oversubscribed` (slots > `--max-slots`, default 3), `score-order`, `out-of-window`.
- Does **not** call any API, re-rank items, judge relevance, or claim an event grouping is ground truth. Grouping is a stated heuristic; `--similarity` exposes the knob.

## Install / run

Zero dependencies. Python 3.9+.

```bash
python3 slate_xray.py examples/in/microsoft-2026-11-15.canonical.txt
```

Real output (exit code 1):

```
clusters: 8 | events: 2 | top event share: 87.5%
!! event 1: 7 slot(s) [ranks 1,2,3,4,5,6,8] Widespread outage hits Microsoft platforms ...
   event 2: 1 slot(s) [ranks 7] 'Joyless & Demoralising': Microsoft Employees ...
VIOLATION event-oversubscribed: event 1 takes 7 slots (limit 3)
verdict: violation
```

Machine output:

```bash
python3 slate_xray.py examples/in/microsoft-2026-11-15.canonical.txt --json
```

Exit codes: `0` pass, `1` violation found, `2` usage/input error (unreadable file, no ranked-cluster block, bad flag).

## 本轮创新

First offline measurement of **event-level slot concentration** in an agent research report, rather than schema/lint checks: on the upstream's own published 4.0.1 Microsoft run it finds **7 of 8 slots belong to one event** (87.5%), which the maintainer's deferred note predicts but no tool or test reports. Dated ledger entries in this cluster audit static schemas, argument types, or performance; none measures narrative monopoly in the emitted slate. B tier.

## 与同类项目的差异

`gh search repos "last30days audit"` and `"agent research report diversity"` returned no repositories (2026-11-20). Generic JSON-schema validators cannot see event identity across headline wordings; this tool's unit is the event, not the cluster.

## Limits

- Grouping is lexical (title tokens, IDF). Paraphrases sharing no distinctive token stay separate; very short headlines that share one rare word may merge. `--similarity` (default 0.10) is the documented knob.
- The input must be the canonical text block; it does not parse `--emit=json` reports.
- The 3-slot cap comes from the upstream comment, not from a published schema.

## Evidence

- Issue: https://github.com/mvanhorn/last30days-skill/issues/1449 (open; maintainer deferred the cross-wording case)
- Real run artifacts used as the example: https://gist.github.com/mvanhorn/39784ee137d4937cddbc4b566aa54789 (`engine.out.txt`, 4.0.1, 2026-11-15)
- Code: https://github.com/mvanhorn/last30days-skill/blob/main/skills/last30days/scripts/briefing.py

MIT. Test data derived from the public gist above.