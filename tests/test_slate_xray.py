import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import slate_xray as sx  # noqa: E402

REAL = ROOT / "examples" / "in" / "microsoft-2026-11-15.canonical.txt"

DIVERSE = """# last30days v4.0.2: Acme

- Date range: 2026-10-16 to 2026-11-15

## Ranked Evidence Clusters

### 1. Acme router firmware update breaks IPv6 (score 50, 1 item, sources: Reddit)
1. [reddit] Acme router firmware update breaks IPv6
   - 2026-11-10 | r/networking | [500pts, 40cmt] | score:50
   - Evidence: after the 4.2.1 firmware update IPv6 stopped routing
### 2. Acme hires a new CFO (score 44, 1 item, sources: Digg)
1. [digg] Acme hires a new CFO
   - 2026-11-11 | Digg | [120 Digg Score, 10posts] | score:44
   - Evidence: the company named a new chief financial officer
### 3. Acme quarterly revenue beats estimates (score 40, 1 item, sources: Hacker News)
1. [hackernews] Acme quarterly revenue beats estimates
   - 2026-11-12 | Hacker News | [900pts, 120cmt] | score:40
   - Evidence: revenue rose on cloud demand
### 4. Acme open-sources its YAML linter (score 35, 1 item, sources: GitHub)
1. [github] Acme open-sources its YAML linter
   - 2026-11-13 | GitHub | [80react, 5cmt] | score:35
   - Evidence: a new repository publishes the linter
### 5. Acme solar roof pilot in Spain (score 30, 1 item, sources: YouTube)
1. [youtube] Acme solar roof pilot in Spain
   - 2026-11-14 | YouTube | [1000views, 20likes] | score:30
   - Evidence: a pilot project installs solar roofs
"""


def run(*args, stdin=None):
    return subprocess.run(
        [sys.executable, str(ROOT / "slate_xray.py"), *args],
        capture_output=True, text=True, input=stdin,
    )


class ParseTests(unittest.TestCase):
    def test_real_cluster_count(self):
        doc = sx.parse_canonical(REAL.read_text())
        self.assertEqual(len(doc["clusters"]), 8)

    def test_real_window(self):
        doc = sx.parse_canonical(REAL.read_text())
        self.assertEqual(doc["window"], {"start": "2026-10-16", "end": "2026-11-15"})

    def test_real_topic(self):
        doc = sx.parse_canonical(REAL.read_text())
        self.assertEqual(doc["topic"], "Microsoft")

    def test_missing_section_raises(self):
        with self.assertRaises(ValueError):
            sx.parse_canonical("# nothing here\n")


class GroupingTests(unittest.TestCase):
    def test_real_groups_into_two_events(self):
        doc = sx.parse_canonical(REAL.read_text())
        report = sx.audit(doc, 3)
        self.assertEqual(report["event_count"], 2)
        self.assertEqual(report["top_event"]["slots"], 7)

    def test_real_reports_oversubscription(self):
        report = sx.audit(sx.parse_canonical(REAL.read_text()), 3)
        codes = [v["code"] for v in report["violations"]]
        self.assertIn("event-oversubscribed", codes)
        self.assertEqual(report["verdict"], "violation")

    def test_high_slot_limit_passes(self):
        report = sx.audit(sx.parse_canonical(REAL.read_text()), 8)
        self.assertEqual(report["verdict"], "pass")

    def test_diverse_slate_has_five_events(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write(DIVERSE)
            path = fh.name
        doc = sx.parse_canonical(Path(path).read_text())
        report = sx.audit(doc, 3)
        self.assertEqual(report["event_count"], 5)
        self.assertEqual(report["verdict"], "pass")

    def test_out_of_window_detected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write(DIVERSE.replace("2026-11-14", "2026-12-24"))
            path = fh.name
        report = sx.audit(sx.parse_canonical(Path(path).read_text()), 3)
        self.assertIn("out-of-window", [v["code"] for v in report["violations"]])

    def test_score_order_detected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write(DIVERSE.replace("score 44", "score 99"))
            path = fh.name
        report = sx.audit(sx.parse_canonical(Path(path).read_text()), 3)
        self.assertIn("score-order", [v["code"] for v in report["violations"]])


class CliTests(unittest.TestCase):
    def test_cli_real_exit_1(self):
        p = run(str(REAL))
        self.assertEqual(p.returncode, 1)
        self.assertIn("event-oversubscribed", p.stdout)

    def test_cli_diverse_exit_0(self):
        p = run("-", stdin=DIVERSE)
        self.assertEqual(p.returncode, 0)

    def test_cli_missing_file_exit_2(self):
        p = run("/nonexistent/input.txt")
        self.assertEqual(p.returncode, 2)

    def test_cli_bad_input_exit_2(self):
        p = run("-", stdin="hello\n")
        self.assertEqual(p.returncode, 2)

    def test_cli_json_is_parseable(self):
        p = run(str(REAL), "--json")
        data = json.loads(p.stdout)
        self.assertEqual(data["clusters"], 8)
        self.assertEqual(data["top_event"]["slots"], 7)
        self.assertEqual(data["verdict"], "violation")
        self.assertEqual(p.returncode, 1)

    def test_cli_json_diverse_exit_0(self):
        p = run("-", "--json", stdin=DIVERSE)
        data = json.loads(p.stdout)
        self.assertEqual(data["verdict"], "pass")
        self.assertEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)