import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "mine_gemini_workflows", ROOT / "scripts" / "mine-gemini-workflows.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class GeminiWorkflowMinerTests(unittest.TestCase):
    def write_jsonl(self, path: Path, records: list[dict]) -> None:
        path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")

    def current_records(self, session_id: str, validation: str = "passed") -> list[dict]:
        return [
            {
                "type": "session_info",
                "sessionId": session_id,
                "timestamp": "2026-08-12T10:00:00Z",
            },
            {
                "type": "message",
                "timestamp": "2026-08-12T10:01:00Z",
                "message": {
                    "role": "user",
                    "content": [{"text": "Prepare the weekly investor memo at /Users/adam/private.md"}],
                },
            },
            {
                "type": "message",
                "timestamp": "2026-08-12T10:02:00Z",
                "message": {
                    "role": "gemini",
                    "content": [
                        {"thinking": "Never export this chain of thought"},
                        {"text": "Memo complete. token=super-secret-value"},
                    ],
                    "toolCalls": [{"name": "read_file"}, {"name": "write_file"}],
                },
                "memoryScratchpad": {
                    "version": 1,
                    "workflowSummary": "Prepare the weekly investor memo",
                    "toolSequence": ["read_file", "write_file"],
                    "touchedPaths": ["/Users/adam/private.md"],
                    "validationStatus": validation,
                },
            },
        ]

    def test_metadata_only_report_finds_repeated_validated_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session_dir = Path(temp)
            self.write_jsonl(session_dir / "one.jsonl", self.current_records("session-one"))
            self.write_jsonl(session_dir / "two.jsonl", self.current_records("session-two"))

            first, warnings = MODULE.session_summary(session_dir / "one.jsonl", False, False)
            second, _ = MODULE.session_summary(session_dir / "two.jsonl", False, False)
            candidates = MODULE.build_candidates([first, second], 2)

            self.assertEqual(warnings, [])
            self.assertNotIn("observable_messages", first)
            self.assertNotIn("touched_paths", first)
            self.assertEqual(first["source_format"], "jsonl")
            self.assertTrue(first["validation_passed"])
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["occurrences"], 2)
            self.assertEqual(candidates[0]["validated_sessions"], 2)

    def test_opt_in_content_is_redacted_and_private_thoughts_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "session.jsonl"
            self.write_jsonl(path, self.current_records("session-one"))

            session, _ = MODULE.session_summary(path, True, True)
            rendered = json.dumps(session)

            self.assertIn("<ABSOLUTE_PATH>/private.md", rendered)
            self.assertIn("<REDACTED_SECRET>", rendered)
            self.assertNotIn("Never export this chain of thought", rendered)
            self.assertEqual(session["touched_paths"], ["<PATH>/private.md"])

    def test_legacy_json_messages_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "legacy.json"
            path.write_text(
                json.dumps(
                    {
                        "sessionId": "legacy-session",
                        "messages": [
                            {"role": "user", "content": "Draft a brief"},
                            {
                                "role": "assistant",
                                "content": "Done",
                                "tool_calls": [{"name": "write_file"}],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            session, warnings = MODULE.session_summary(path, False, False)

            self.assertEqual(warnings, [])
            self.assertEqual(session["source_format"], "json")
            self.assertEqual(session["session_id"], "legacy-session")
            self.assertEqual(session["tool_sequence"], ["write_file"])

    def test_malformed_jsonl_record_is_reported_not_silently_swallowed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mixed.jsonl"
            path.write_text(
                json.dumps(self.current_records("session-one")[0]) + "\nnot-json\n",
                encoding="utf-8",
            )

            _, warnings = MODULE.session_summary(path, False, False)

            self.assertEqual(len(warnings), 1)
            self.assertIn("skipped malformed JSONL record", warnings[0])


if __name__ == "__main__":
    unittest.main()
