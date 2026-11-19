#!/usr/bin/env python3
"""slate-xray: event-level concentration audit for last30days canonical output.

Reads the canonical text a last30days v4 run prints (the block that ends with
`# END OF last30days CANONICAL OUTPUT`), reconstructs the ranked story slate,
groups clusters into events with a TF-IDF single-link pass, and reports whether
one event occupies more than --max-slots of the ranked slots.

Offline only. Zero third-party dependencies.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

VERSION = "1.0.0"

HEADER_RE = re.compile(
    r"^###\s+(\d+)\.\s+(.*?)\s+\(score\s+(-?\d+),\s+(\d+)\s+items?,\s+sources:\s*(.*?)\)\s*$"
)
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
RANGE_RE = re.compile(r"Date range:\s*(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})")
TITLE_RE = re.compile(r"#\s+last30days\s+v[\d.]+\s*:\s*(.+)$", re.M)
ITEM_HEAD_RE = re.compile(r"^\d+\.\s+\[([a-z0-9_-]+)\]\s*(.*)$")
ITEM_META_RE = re.compile(
    r"^\s*-\s+(\d{4}-\d{2}-\d{2})\s+\|\s+(.*?)\s+\|\s+\[([^\]]*)\]\s+\|\s+score:(-?\d+)"
)
EVIDENCE_RE = re.compile(r"^\s*-\s+Evidence:\s*(.*)$")
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z]+_[0-9a-z]+\}\}")

STOPWORDS = set(
    """a an and are as at be been but by for from had has have he her his how i if in into is it its
    just me more most my no not of on or our out over said says she so some than that the their them
    then there these they this those to too up was we were what when where which who why will with
    would you your about after all also can could did do does get got his like make many may much
    new now one only other people said say still such take two us very well""".split()
)

TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


def _norm_tokens(text: str) -> list[str]:
    text = PLACEHOLDER_RE.sub(" ", text.lower())
    return [t for t in TOKEN_RE.findall(text) if t not in STOPWORDS]


def parse_canonical(text: str) -> dict:
    """Parse the canonical block. Raises ValueError when no slate is present."""
    window = None
    m = RANGE_RE.search(text)
    if m:
        window = {"start": m.group(1), "end": m.group(2)}
    topic = None
    m = TITLE_RE.search(text)
    if m:
        topic = m.group(1).strip()

    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == "## Ranked Evidence Clusters")
    except StopIteration:
        raise ValueError("no '## Ranked Evidence Clusters' section found")
    clusters: list[dict] = []
    cur = None
    for ln in lines[start + 1 :]:
        if ln.startswith("## "):
            break
        hm = HEADER_RE.match(ln.strip())
        if hm:
            cur = {
                "rank": int(hm.group(1)),
                "title": hm.group(2).strip(),
                "score": int(hm.group(3)),
                "declared_items": int(hm.group(4)),
                "sources": [s.strip() for s in hm.group(5).split(",") if s.strip()],
                "items": [],
            }
            clusters.append(cur)
            continue
        if cur is None:
            continue
        im = ITEM_META_RE.match(ln)
        if im:
            cur["items"].append(
                {
                    "date": im.group(1),
                    "voice": im.group(2).strip(),
                    "metrics": im.group(3).strip(),
                    "score": int(im.group(4)),
                }
            )
            continue
        em = EVIDENCE_RE.match(ln)
        if em and cur["items"]:
            cur["items"][-1]["evidence"] = em.group(1).strip()
    if not clusters:
        raise ValueError("ranked-clusters section contains no '### N. ... (score ...)' headers")
    for c in clusters:
        c["items"] = [it for it in c["items"] if it.get("date")]
    return {"topic": topic, "window": window, "clusters": clusters}


def _overlap(idf: dict, a: set, b: set) -> float:
    """IDF-weighted overlap coefficient: shared mass / smaller doc mass."""
    if not a or not b:
        return 0.0
    shared = sum(idf[t] for t in a & b)
    denom = min(sum(idf[t] for t in a), sum(idf[t] for t in b))
    return shared / denom if denom else 0.0


def group_events(clusters: list[dict], threshold: float = 0.10) -> list[dict]:
    """Single-link grouping of clusters into events, on title tokens only.

    Tokens present in every title (the topic entity) get idf 0, so grouping is
    driven by the words that distinguish one story from another. The overlap
    coefficient (not cosine) is used because headlines are short and uneven:
    two short headlines that share one distinctive word should link.
    """
    docs = [set(_norm_tokens(c["title"])) for c in clusters]
    n = len(docs)
    df: Counter = Counter()
    for d in docs:
        df.update(d)
    idf = {t: math.log(n / c) for t, c in df.items()} if n > 1 else {t: 0.0 for t in df}

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    links = []
    for i in range(n):
        for j in range(i + 1, n):
            score = _overlap(idf, docs[i], docs[j])
            if score >= threshold:
                links.append((i, j, score))
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    events = []
    for members in sorted(groups.values(), key=lambda ms: min(clusters[i]["rank"] for i in ms)):
        members = sorted(members, key=lambda i: clusters[i]["rank"])
        first = clusters[members[0]]
        events.append(
            {
                "label": first["title"],
                "clusters": [
                    {"rank": clusters[i]["rank"], "title": clusters[i]["title"], "score": clusters[i]["score"]}
                    for i in members
                ],
                "slots": len(members),
            }
        )
    for idx, ev in enumerate(events, 1):
        ev["id"] = idx
    return events


def audit(doc: dict, max_slots: int, similarity: float = 0.10) -> dict:
    clusters = doc["clusters"]
    events = group_events(clusters, similarity)
    violations = []

    for ev in events:
        if ev["slots"] > max_slots:
            violations.append(
                {
                    "code": "event-oversubscribed",
                    "detail": f"event {ev['id']} takes {ev['slots']} slots (limit {max_slots})",
                    "ranks": [c["rank"] for c in ev["clusters"]],
                }
            )

    for prev, cur in zip(clusters, clusters[1:]):
        if cur["score"] > prev["score"]:
            violations.append(
                {
                    "code": "score-order",
                    "detail": f"cluster {cur['rank']} scores {cur['score']} above cluster {prev['rank']} ({prev['score']})",
                }
            )

    window = doc.get("window")
    if window:
        bad = []
        for c in clusters:
            for it in c["items"]:
                if it["date"] < window["start"] or it["date"] > window["end"]:
                    bad.append({"rank": c["rank"], "date": it["date"]})
        if bad:
            violations.append(
                {
                    "code": "out-of-window",
                    "detail": f"{len(bad)} item(s) dated outside {window['start']}..{window['end']}",
                    "items": bad[:10],
                }
            )

    top = max(events, key=lambda e: e["slots"]) if events else None
    total = len(clusters)
    return {
        "tool": "slate-xray",
        "version": VERSION,
        "topic": doc.get("topic"),
        "window": window,
        "max_slots": max_slots,
        "clusters": total,
        "events": events,
        "event_count": len(events),
        "top_event": {"id": top["id"], "label": top["label"], "slots": top["slots"]} if top else None,
        "top_event_share": round(top["slots"] / total, 4) if top and total else 0.0,
        "distinct_event_ratio": round(len(events) / total, 4) if total else 0.0,
        "verdict": "violation" if violations else "pass",
        "violations": violations,
    }


def render_text(report: dict, source: str) -> str:
    out = []
    out.append(f"slate-xray {VERSION} | {report.get('topic') or 'unknown topic'} | {source}")
    if report.get("window"):
        out.append(f"window: {report['window']['start']} .. {report['window']['end']}")
    out.append(f"clusters: {report['clusters']} | events: {report['event_count']} "
               f"| top event share: {report['top_event_share']:.1%}")
    out.append("")
    for ev in report["events"]:
        flag = "!!" if ev["slots"] > report["max_slots"] else "  "
        ranks = ",".join(str(c["rank"]) for c in ev["clusters"])
        out.append(f"{flag} event {ev['id']}: {ev['slots']} slot(s) [ranks {ranks}] {ev['label'][:90]}")
    if report["violations"]:
        out.append("")
        for v in report["violations"]:
            out.append(f"VIOLATION {v['code']}: {v['detail']}")
    out.append("")
    out.append(f"verdict: {report['verdict']}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="slate-xray",
        description="Event-level concentration audit for a last30days canonical output block.",
    )
    ap.add_argument("input", help="file with the last30days canonical output (use '-' for stdin)")
    ap.add_argument("--max-slots", type=int, default=3, help="max ranked slots one event may take (default 3)")
    ap.add_argument("--similarity", type=float, default=0.10,
                    help="title-overlap threshold for calling two clusters the same event (default 0.10)")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--version", action="version", version=f"slate-xray {VERSION}")
    args = ap.parse_args(argv)

    if args.max_slots < 1:
        print("slate-xray: --max-slots must be >= 1", file=sys.stderr)
        return 2
    if not 0.0 < args.similarity <= 1.0:
        print("slate-xray: --similarity must be in (0, 1]", file=sys.stderr)
        return 2
    try:
        if args.input == "-":
            text = sys.stdin.read()
            source = "<stdin>"
        else:
            source = args.input
            text = Path(args.input).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"slate-xray: cannot read input: {exc}", file=sys.stderr)
        return 2
    try:
        doc = parse_canonical(text)
        report = audit(doc, args.max_slots, args.similarity)
    except ValueError as exc:
        print(f"slate-xray: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_text(report, source))
    return 1 if report["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())