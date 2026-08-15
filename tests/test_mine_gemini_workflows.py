import contextlib
import importlib.util
import io
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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")

    def current_records(
        self,
        session_id: str,
        validation: str = "passed",
        tools: list[str] | None = None,
        last_updated: str = "2026-08-15T10:03:00Z",
    ) -> list[dict]:
        tool_sequence = tools or ["read_file", "write_file"]
        return [
            {
                "sessionId": session_id,
                "projectHash": "project-hash",
                "startTime": "2026-08-15T10:00:00Z",
                "lastUpdated": "2026-08-15T10:00:00Z",
                "kind": "main",
            },
            {
                "id": f"{session_id}-user",
                "type": "user",
                "timestamp": "2026-08-15T10:01:00Z",
                "content": [{"text": "Prepare the weekly investor memo"}],
            },
            {
                "id": f"{session_id}-gemini",
                "type": "gemini",
                "timestamp": "2026-08-15T10:02:00Z",
                "content": [{"text": "Memo complete"}],
                "thoughts": [{"subject": "private", "description": "Never export this"}],
                "toolCalls": [
                    {"id": f"call-{index}", "name": name, "args": {}, "status": "success"}
                    for index, name in enumerate(tool_sequence)
                ],
            },
            {
                "$set": {
                    "lastUpdated": last_updated,
                    "memoryScratchpad": {
                        "version": 1,
                        "workflowSummary": "Prepare the weekly investor memo",
                        "toolSequence": tool_sequence,
                        "touchedPaths": ["/Users/adam/private.md"],
                        "validationStatus": validation,
                    },
                }
            },
        ]

    def run_main(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = MODULE.main(args)
        return status, stdout.getvalue(), stderr.getvalue()

    def test_current_jsonl_is_folded_and_repeated_validated_workflow_is_ranked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session_dir = Path(temp)
            self.write_jsonl(session_dir / "one.jsonl", self.current_records("session-one"))
            self.write_jsonl(session_dir / "two.jsonl", self.current_records("session-two"))

            first, warnings = MODULE.session_summary(session_dir / "one.jsonl")
            second, _ = MODULE.session_summary(session_dir / "two.jsonl")
            candidates = MODULE.build_candidates([first, second], 2)

            self.assertEqual(warnings, [])
            self.assertEqual(first["message_records"], 2)
            self.assertEqual(first["updated_at"], "2026-08-15T10:03:00Z")
            self.assertNotIn("workflow_summary", first)
            self.assertTrue(first["validation_passed"])
            self.assertFalse(first["scratchpad_stale"])
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["validation_ratio"], 1.0)

    def test_rewind_and_set_use_only_surviving_messages_and_latest_scratchpad(self) -> None:
        records = [
            {
                "sessionId": "rewind-session",
                "projectHash": "project-hash",
                "startTime": "2026-08-01T10:00:00Z",
                "lastUpdated": "2026-08-01T10:00:00Z",
            },
            {"id": "u1", "type": "user", "timestamp": "2026-08-01T10:01:00Z", "content": "keep"},
            {
                "id": "g-old",
                "type": "gemini",
                "timestamp": "2026-08-01T10:02:00Z",
                "content": "abandoned content",
                "toolCalls": [{"id": "old", "name": "abandoned_tool", "args": {}, "status": "success"}],
            },
            {
                "$set": {
                    "memoryScratchpad": {
                        "version": 1,
                        "workflowSummary": "Abandoned workflow",
                        "toolSequence": ["abandoned_tool"],
                        "validationStatus": "passed",
                    }
                }
            },
            {"$rewindTo": "g-old"},
            {
                "id": "g-new",
                "type": "gemini",
                "timestamp": "2026-08-15T10:02:00Z",
                "content": "replacement content",
                "toolCalls": [{"id": "new", "name": "replacement_tool", "args": {}, "status": "failed"}],
            },
            {
                "$set": {
                    "lastUpdated": "2026-08-15T10:03:00Z",
                    "memoryScratchpad": {
                        "version": 1,
                        "workflowSummary": "Replacement workflow",
                        "toolSequence": ["replacement_tool"],
                        "validationStatus": "failed",
                    },
                }
            },
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "session.jsonl"
            self.write_jsonl(path, records)

            session, _ = MODULE.session_summary(
                path,
                selected_ids={"rewind-session"},
                include_content=True,
                include_summaries=True,
            )
            rendered = json.dumps(session)

            self.assertEqual(session["message_records"], 2)
            self.assertEqual(session["tool_sequence"], ["replacement_tool"])
            self.assertEqual(session["workflow_summary"], "Replacement workflow")
            self.assertFalse(session["validation_passed"])
            self.assertEqual(session["updated_at"], "2026-08-15T10:03:00Z")
            self.assertNotIn("abandoned content", rendered)
            self.assertIn("replacement content", rendered)

    def test_sensitive_output_requires_and_honors_session_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session_dir = Path(temp)
            first = self.current_records("session-one")
            first[1]["content"] = [
                {
                    "text": 'Bearer very-secret-bearer {"apiKey": "supersecretvalue"} alice@example.com'
                }
            ]
            self.write_jsonl(session_dir / "one.jsonl", first)
            self.write_jsonl(session_dir / "two.jsonl", self.current_records("session-two"))

            status, _, stderr = self.run_main([str(session_dir), "--include-content"])
            self.assertEqual(status, 2)
            self.assertIn("require at least one --session-id", stderr)

            status, stdout, _ = self.run_main(
                [str(session_dir), "--include-content", "--session-id", "session-one"]
            )
            report = json.loads(stdout)
            one, two = report["sessions"]
            rendered = json.dumps(one)
            self.assertEqual(status, 0)
            self.assertIn("observable_messages", one)
            self.assertNotIn("observable_messages", two)
            self.assertNotIn("very-secret-bearer", rendered)
            self.assertNotIn("supersecretvalue", rendered)
            self.assertNotIn("alice@example.com", rendered)
            self.assertTrue(report["privacy"]["content_is_sensitive"])

    def test_since_excludes_unknown_dates_instead_of_failing_open(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session_dir = Path(temp)
            self.write_jsonl(
                session_dir / "unknown.jsonl",
                [{"sessionId": "unknown", "projectHash": "project"}],
            )
            status, stdout, _ = self.run_main([str(session_dir), "--since", "2099-01-01"])
            report = json.loads(stdout)
            self.assertEqual(status, 0)
            self.assertEqual(report["sessions"], [])
            self.assertIn("update date is unknown", report["warnings"][0])

    def test_minimum_applies_to_validated_sessions_and_ratio_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session_dir = Path(temp)
            for session_id, status in (("one", "passed"), ("two", "passed"), ("three", "failed")):
                path = session_dir / f"{session_id}.jsonl"
                self.write_jsonl(path, self.current_records(session_id, validation=status))
            sessions = [MODULE.session_summary(path)[0] for path in sorted(session_dir.glob("*.jsonl"))]
            candidates = MODULE.build_candidates(sessions, 2)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["validated_sessions"], 2)
            self.assertEqual(candidates[0]["validation_ratio"], 0.667)

            for session in sessions:
                if session["session_id"] == "two":
                    session["validation_passed"] = False
            self.assertEqual(MODULE.build_candidates(sessions, 2), [])

    def test_repeated_tool_calls_preserve_order_and_repetition(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "repeat.jsonl"
            self.write_jsonl(
                path,
                self.current_records("repeat", tools=["read_file", "edit_file", "read_file"]),
            )
            session, _ = MODULE.session_summary(path)
            self.assertEqual(session["tool_sequence"], ["read_file", "edit_file", "read_file"])

    def test_provenance_separates_session_identity_from_recording_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first_path = root / "a" / "session.jsonl"
            second_path = root / "b" / "session.jsonl"
            self.write_jsonl(first_path, self.current_records("session-one"))
            self.write_jsonl(second_path, self.current_records("session-two"))
            first, _ = MODULE.session_summary(first_path)
            second, _ = MODULE.session_summary(second_path)
            self.assertNotEqual(first["session_fingerprint"], second["session_fingerprint"])
            self.assertNotEqual(first["recording_digest"], second["recording_digest"])

    def test_sensitive_output_rejects_duplicate_session_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = self.current_records("duplicate-session")
            second = self.current_records("duplicate-session")
            second[1]["content"] = "different private content"
            self.write_jsonl(root / "legacy" / "session.jsonl", first)
            self.write_jsonl(root / "migrated" / "session.jsonl", second)

            status, _, stderr = self.run_main(
                [str(root), "--include-content", "--session-id", "duplicate-session"]
            )
            self.assertEqual(status, 2)
            self.assertIn("resolve to multiple recordings", stderr)

    def test_legacy_json_record_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "legacy.json"
            path.write_text(
                json.dumps(
                    {
                        "sessionId": "legacy-session",
                        "projectHash": "legacy-project",
                        "lastUpdated": "2026-08-15T10:00:00Z",
                        "messages": [
                            {"id": "u1", "type": "user", "timestamp": "2026-08-15T09:00:00Z", "content": "Draft"},
                            {
                                "id": "g1",
                                "type": "gemini",
                                "timestamp": "2026-08-15T09:01:00Z",
                                "content": "Done",
                                "toolCalls": [{"id": "c1", "name": "write_file", "args": {}, "status": "success"}],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            session, warnings = MODULE.session_summary(path)
            self.assertEqual(warnings, [])
            self.assertEqual(session["source_format"], "json")
            self.assertEqual(session["session_id"], "legacy-session")
            self.assertEqual(session["tool_sequence"], ["write_file"])

    def test_malformed_jsonl_is_incomplete_and_ineligible_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mixed.jsonl"
            path.write_text(
                "\n".join(json.dumps(record) for record in self.current_records("session-one"))
                + "\nnot-json\n",
                encoding="utf-8",
            )
            session, warnings = MODULE.session_summary(path)
            self.assertEqual(len(warnings), 1)
            self.assertIn("skipped malformed JSONL record", warnings[0])
            self.assertFalse(session["recording_complete"])
            self.assertFalse(session["validation_passed"])
            self.assertEqual(MODULE.build_candidates([session], 1), [])

            status, _, stderr = self.run_main(
                [str(Path(temp)), "--include-content", "--session-id", "session-one"]
            )
            self.assertEqual(status, 2)
            self.assertIn("incomplete or malformed", stderr)


if __name__ == "__main__":
    unittest.main()
