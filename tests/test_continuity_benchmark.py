from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("benchmark", ROOT / "scripts/continuity-benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)
SCENARIO = json.loads(benchmark.SCENARIO.read_text(encoding="utf-8"))
LONG = json.loads(benchmark.LONG_SCENARIO.read_text(encoding="utf-8"))


class BenchmarkTest(unittest.TestCase):
    def answer(self, profile):
        answers = copy.deepcopy(SCENARIO["expected"])
        if profile == "handoff":
            for answer in answers.values():
                answer["source"] = "HANDOFF.md"
        if profile == "instructions":
            answers = {key: {"value": "unknown", "source": None, "quote": ""} for key in answers}
        return {"answers": answers}

    def test_valid_answers_and_equal_information_handoff_baseline(self):
        for profile in benchmark.PROFILES:
            with self.subTest(profile=profile):
                result = benchmark.score(SCENARIO, profile, self.answer(profile))
                self.assertEqual(4, result["grounded_correct"])
                self.assertEqual(0 if profile == "instructions" else 3, result["known_decisions_retained"])

    def test_each_wrong_decision_or_invented_certainty_fails(self):
        for key, wrong in (("database", "sqlite"), ("export", "pdf"), ("retries", "yes"), ("launch", "confirmed")):
            response = self.answer("contextos")
            response["answers"][key]["value"] = wrong
            self.assertEqual(3, benchmark.score(SCENARIO, "contextos", response)["grounded_correct"])

    def test_correct_guess_without_support_fails(self):
        response = self.answer("contextos")
        response["answers"]["database"]["quote"] = "PostgreSQL is always best"
        self.assertEqual(3, benchmark.score(SCENARIO, "contextos", response)["grounded_correct"])
        self.assertEqual(0, benchmark.score(SCENARIO, "instructions", self.answer("contextos"))["grounded_correct"])

    def test_prompt_does_not_leak_answer_key_or_unselected_sources(self):
        prompt = benchmark.prepare(SCENARIO, "instructions")
        self.assertIn("keyed by the four question IDs", prompt)
        self.assertNotIn('"expected"', prompt)
        self.assertNotIn("Use PostgreSQL for concurrent writers.", prompt)
        self.assertNotIn('"HANDOFF.md"', benchmark.prepare(SCENARIO, "contextos"))
        self.assertNotIn('"state/decisions.md"', benchmark.prepare(SCENARIO, "handoff"))

    def test_missing_questions_rejected(self):
        with self.assertRaises(ValueError):
            benchmark.score(SCENARIO, "contextos", {"answers": {}})


class LongSequenceTest(unittest.TestCase):
    def answer(self, profile="contextos"):
        answers = copy.deepcopy(LONG["expected"])
        if profile == "handoff":
            for answer in answers.values():
                answer["source"] = "HANDOFF.md"
        if profile == "instructions":
            answers = {key: {"value": "unknown", "source": None, "quote": ""} for key in answers}
        return {"answers": answers}

    def test_fixture_and_profiles(self):
        self.assertEqual(10, len(LONG["questions"]))
        self.assertEqual(5, len(set(LONG["categories"].values())))
        for profile in benchmark.PROFILES:
            with self.subTest(profile=profile):
                result = benchmark.score(LONG, profile, self.answer(profile))
                self.assertEqual(10, result["grounded_correct"])
                self.assertEqual(10, result["value_correct"])
                self.assertEqual(0, result["citation_rejected"])
                self.assertEqual(2, result["category_counts"]["retained_decision"]["value_correct"])
                self.assertEqual(8 if profile != "instructions" else 0,
                                 result["decision_retention"])
                self.assertEqual(2 if profile != "instructions" else 10,
                                 result["safe_uncertainty"])
                self.assertEqual(2 if profile != "instructions" else 0,
                                 result["corrections"])
                self.assertGreater(result["context_characters"], 0)
        self.assertNotIn("state/decisions.md", benchmark.prepare(LONG, "handoff"))
        self.assertNotIn("HANDOFF.md", benchmark.prepare(LONG, "contextos"))
        self.assertIn("keyed by the 10 question IDs", benchmark.prepare(LONG, "contextos"))

    def test_negative_controls_each_category(self):
        controls = (("atlas_delivery", "queue", "retained_decision"),
                    ("atlas_cron_current", "yes", "replaced_decision"),
                    ("atlas_release", "confirmed", "unresolved"),
                    ("atlas_migration", "ran", "interrupted_status"),
                    ("atlas_ids", "include", "cross_project_constraint"))
        for key, wrong, category in controls:
            with self.subTest(category=category):
                response = self.answer()
                response["answers"][key]["value"] = wrong
                result = benchmark.score(LONG, "contextos", response)
                self.assertEqual(9, result["grounded_correct"])
                self.assertEqual(category, next(item["category"] for item in result["results"]
                                                if item["question"] == key))
                if category == "cross_project_constraint":
                    self.assertEqual(1, result["missed_constraints"])
                if category == "replaced_decision":
                    self.assertEqual(1, result["corrections"])
                if category == "unresolved":
                    self.assertEqual(1, result["invented_certainty"])

    def test_quote_and_format_controls(self):
        response = self.answer()
        response["answers"]["beacon_review"]["quote"] = "before approval."
        result = benchmark.score(LONG, "contextos", response)
        self.assertEqual(9, result["grounded_correct"])
        self.assertEqual(10, result["value_correct"])
        self.assertEqual(1, result["citation_rejected"])
        self.assertEqual(1, result["category_counts"]["interrupted_status"]["citation_rejected"])
        self.assertTrue(next(item for item in result["results"] if item["question"] == "beacon_review")["citation_rejected"])
        response["answers"]["beacon_review"]["value"] = "approved"
        wrong = benchmark.score(LONG, "contextos", response)
        self.assertEqual(9, wrong["value_correct"])
        self.assertEqual(0, wrong["citation_rejected"])
        self.assertEqual(9, wrong["grounded_correct"])
        instructions = self.answer("instructions")
        instructions["answers"]["atlas_delivery"] = {
            "value": "unknown", "source": "AGENTS.md", "quote": "Use the latest explicit project decision."}
        unsupported = benchmark.score(LONG, "instructions", instructions)
        self.assertEqual(10, unsupported["value_correct"])
        self.assertEqual(1, unsupported["citation_rejected"])
        self.assertEqual(9, unsupported["grounded_correct"])
        malformed = benchmark.evaluate(LONG, "contextos", "{broken")
        self.assertTrue(malformed["format_failure"])
        self.assertNotIn("grounded_correct", malformed)
        missing = self.answer()
        del missing["answers"]["atlas_ids"]
        self.assertIn("exactly", benchmark.evaluate(LONG, "contextos", json.dumps(missing))["format_failure"])
        wrong_source_type = self.answer()
        wrong_source_type["answers"]["atlas_ids"]["source"] = ["state/decisions.md"]
        self.assertIn("source must be", benchmark.evaluate(LONG, "contextos", json.dumps(wrong_source_type))["format_failure"])

    def test_record_and_summary_keep_failures(self):
        raw = json.dumps(self.answer())
        good = benchmark.record(LONG, "contextos", raw, "model-1", "provider-1", 1, 1.25, 100, 50)
        bad = benchmark.record(LONG, "contextos", "{broken", "model-1", "provider-1", 2, 2.0)
        self.assertEqual(raw, good["raw_response"])
        self.assertEqual(64, len(good["prompt_sha256"]))
        self.assertEqual(100, good["input_tokens"])
        self.assertTrue(bad["score"]["format_failure"])
        table = benchmark.summarize([good, bad])
        self.assertIn(f"| model-1 | contextos | {good['score']['context_characters']} | 2 | 10.00 | 10.00 | 0.00 | 8.00 | 2.00 | 0.00 | 1 |", table)
        old = copy.deepcopy(good)
        del old["score"]["value_correct"]
        del old["score"]["citation_rejected"]
        self.assertEqual(benchmark.summarize([good]), benchmark.summarize([old]))
        old["prompt_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "stored prompt"):
            benchmark.summarize([old])
        for trial, latency, input_tokens, model in ((0, 1.0, None, "model-1"),
                                                    (1, -1.0, None, "model-1"),
                                                    (1, 1.0, -1, "model-1"),
                                                    (1, 1.0, None, "")):
            with self.assertRaises(ValueError):
                benchmark.record(LONG, "contextos", raw, model, "provider-1",
                                 trial, latency, input_tokens)
        with self.assertRaises(ValueError):
            benchmark.record(LONG, "contextos", raw, "model-1", "provider-1", 1, 1.0,
                             output_tokens=-1)
        with self.assertRaises(ValueError):
            benchmark.record(LONG, "contextos", raw, "model-1", "", 1, 1.0)

    def test_record_cli_appends_raw_failure_and_summarizes(self):
        directory = ROOT / "tests/fixtures/continuity"
        suffix = uuid4().hex
        response = directory / f"response-{suffix}.txt"
        results = directory / f"results-{suffix}.jsonl"
        try:
            response.write_bytes(b"{broken\r\n")
            command = ["python", str(benchmark.ROOT / "scripts/continuity-benchmark.py")]
            recorded = subprocess.run(command + ["record", "--scenario", "long", "--profile", "contextos",
                                                "--response", str(response), "--results", str(results),
                                                "--model", "model-1", "--provider", "provider-1",
                                                "--trial", "1", "--latency", "2.4"],
                                      capture_output=True, text=True)
            self.assertEqual(0, recorded.returncode, recorded.stderr)
            line = json.loads(results.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual("{broken\r\n", line["raw_response"])
            self.assertTrue(line["score"]["format_failure"])
            summary = subprocess.run(command + ["summarize", "--results", str(results)],
                                     capture_output=True, text=True)
            self.assertEqual(0, summary.returncode, summary.stderr)
            self.assertIn("| 1 | n/a | n/a | n/a | n/a | n/a | n/a | 1 |", summary.stdout)
        finally:
            response.unlink(missing_ok=True)
            results.unlink(missing_ok=True)
