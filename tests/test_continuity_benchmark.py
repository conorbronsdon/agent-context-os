from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("benchmark", ROOT / "scripts/continuity-benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)
SCENARIO = json.loads(benchmark.SCENARIO.read_text(encoding="utf-8"))


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
        self.assertNotIn('"expected"', prompt)
        self.assertNotIn("Use PostgreSQL for concurrent writers.", prompt)
        self.assertNotIn('"HANDOFF.md"', benchmark.prepare(SCENARIO, "contextos"))
        self.assertNotIn('"state/decisions.md"', benchmark.prepare(SCENARIO, "handoff"))

    def test_missing_questions_rejected(self):
        with self.assertRaises(ValueError):
            benchmark.score(SCENARIO, "contextos", {"answers": {}})
