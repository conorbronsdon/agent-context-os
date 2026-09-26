from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
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
        for profile in ("instructions", "handoff", "contextos"):
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
        for key, evidence in LONG.get("expected_by_profile", {}).get(profile, {}).items():
            answers[key].update(evidence)
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

    def test_sentence_handoff_information_and_sentence_shape(self):
        sources = benchmark.selected_sources(LONG, "handoff-sentences")
        self.assertEqual({"AGENTS.md", "HANDOFF.md"}, set(sources))
        self.assertEqual(LONG["sources"]["AGENTS.md"], sources["AGENTS.md"])
        note = sources["HANDOFF.md"]
        self.assertNotRegex(note, r"(?:^|[.!?]\s+)\w+:")
        sentences = re.findall(r"[^.!?]+[.!?]", note)
        sentences = [sentence.strip() for sentence in sentences]
        for sentence in sentences:
            self.assertRegex(sentence, r"^(Atlas|Beacon)(?:'s)? ")
        overrides = LONG["expected_by_profile"]
        self.assertEqual({"handoff-sentences"}, set(overrides))
        self.assertEqual(set(LONG["questions"]), set(overrides["handoff-sentences"]))
        for key, evidence in overrides["handoff-sentences"].items():
            with self.subTest(question=key):
                self.assertEqual({"source", "quote"}, set(evidence))
                self.assertEqual("HANDOFF.md", evidence["source"])
                self.assertIn(evidence["quote"], sentences)
        # Preserve interruption details as well as the ten answer sentences.
        self.assertEqual(set(sentences), {
            evidence["quote"] for evidence in overrides["handoff-sentences"].values()
        } | {"Atlas's staging migration was interrupted before execution.",
             "Beacon's import review was interrupted after the draft."})

    def test_sentence_handoff_grounding_controls(self):
        profile = "handoff-sentences"
        for key in LONG["questions"]:
            for field, value in (("quote", self.answer(profile)["answers"][key]["quote"].split(" ", 1)[1]),
                                 ("quote", self.answer(profile)["answers"][key]["quote"] + " Invented detail."),
                                 ("source", "AGENTS.md"), ("value", "wrong")):
                with self.subTest(question=key, field=field, value=value):
                    response = self.answer(profile)
                    response["answers"][key][field] = value
                    result = benchmark.score(LONG, profile, response)
                    self.assertEqual(9, result["grounded_correct"])
                    self.assertEqual(9 if field == "value" else 10, result["value_correct"])
                    self.assertEqual(0 if field == "value" else 1, result["citation_rejected"])
        response = self.answer(profile)
        for answer in response["answers"].values():
            answer["quote"] = benchmark.selected_sources(LONG, profile)["HANDOFF.md"]
        self.assertEqual(10, benchmark.score(LONG, profile, response)["grounded_correct"])

    def test_september_23_raw_rescore_reproduces_evidence_table(self):
        directory = ROOT / "docs/evidence/continuity-long-2026-09-23"
        lines = [json.loads(line) for line in (directory / "trials.jsonl").read_text(encoding="utf-8").splitlines()]
        readme = (directory / "README.md").read_text(encoding="utf-8")
        table = next(block for block in readme.split("\n\n") if block.startswith("| Model | Profile |"))
        for line in lines:
            prompt = benchmark.prepare(LONG, line["profile"])
            self.assertEqual(line["prompt_sha256"], hashlib.sha256(prompt.encode("utf-8")).hexdigest())
            # Replace cached scores so every summary column exercises today's scorer.
            line["score"] = benchmark.evaluate(LONG, line["profile"], line["raw_response"])
        self.assertEqual(table, benchmark.summarize(lines))

    def test_sentence_handoff_cli_prepare_record_and_summarize(self):
        directory = ROOT / "tests/fixtures/continuity"
        suffix = uuid4().hex
        response = directory / f"response-{suffix}.txt"
        results = directory / f"results-{suffix}.jsonl"
        command = [sys.executable, str(ROOT / "scripts/continuity-benchmark.py")]
        try:
            prepared = subprocess.run(command + ["prepare", "--scenario", "long", "--profile", "handoff-sentences"],
                                      capture_output=True, text=True)
            self.assertEqual(0, prepared.returncode, prepared.stderr)
            self.assertEqual(benchmark.prepare(LONG, "handoff-sentences") + "\n", prepared.stdout)
            self.assertNotIn('"expected_by_profile"', prepared.stdout)
            self.assertNotIn('"state/decisions.md"', prepared.stdout)
            response.write_text(json.dumps(self.answer("handoff-sentences")), encoding="utf-8")
            recorded = subprocess.run(command + ["record", "--scenario", "long", "--profile", "handoff-sentences",
                                                "--response", str(response), "--results", str(results),
                                                "--model", "model-1", "--provider", "provider-1",
                                                "--trial", "1", "--latency", "1.0"],
                                      capture_output=True, text=True)
            self.assertEqual(0, recorded.returncode, recorded.stderr)
            line = json.loads(results.read_text(encoding="utf-8"))
            self.assertEqual(10, line["score"]["grounded_correct"])
            self.assertEqual(771, line["score"]["context_characters"])
            summary = subprocess.run(command + ["summarize", "--results", str(results)],
                                     capture_output=True, text=True)
            self.assertEqual(0, summary.returncode, summary.stderr)
            self.assertIn("| model-1 | handoff-sentences | 771 | 1 | 10.00 | 10.00 | 0.00 | 8.00 | 2.00 | 0.00 | 0 |", summary.stdout)
            unsupported = subprocess.run(command + ["prepare", "--profile", "handoff-sentences"],
                                         capture_output=True, text=True)
            self.assertEqual(2, unsupported.returncode)
            self.assertIn("handoff-sentences requires --scenario long", unsupported.stderr)
        finally:
            response.unlink(missing_ok=True)
            results.unlink(missing_ok=True)

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
            command = [sys.executable, str(benchmark.ROOT / "scripts/continuity-benchmark.py")]
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
