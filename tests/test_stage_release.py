from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "stage_release", ROOT / "scripts/stage-release.py"
)
assert SPEC is not None and SPEC.loader is not None
stage_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage_release)


REPOSITORY = "conorbronsdon/agent-context-os"
TAG = "v0.12.0"
TITLE = "Context OS v0.12.0"
RELEASE_ID = 24680


class FakeRunner:
    def __init__(
        self, responses: list[tuple[int | None, dict[str, object] | None]], *,
        create_returncode: int = 0,
    ) -> None:
        self.responses = list(responses)
        self.create_returncode = create_returncode
        self.create_count = 0
        self.calls: list[tuple[str, ...]] = []

    def run(self, arguments, *, check=True):
        args = tuple(str(value) for value in arguments)
        self.calls.append(args)
        if args[:3] == ("gh", "api", "--include"):
            if not self.responses:
                raise AssertionError("unexpected lookup")
            status, value = self.responses.pop(0)
            if status is None:
                return subprocess.CompletedProcess(args, 1, "", "transport failure")
            body = json.dumps(value or {"message": "Not Found"})
            output = f"HTTP/2.0 {status} status\r\ncontent-type: application/json\r\n\r\n{body}\n"
            return subprocess.CompletedProcess(
                args, 0 if 200 <= status < 300 else 1, output, f"HTTP {status}"
            )
        if args[:3] == ("gh", "release", "create"):
            self.create_count += 1
            return subprocess.CompletedProcess(
                args, self.create_returncode, "", "duplicate" if self.create_returncode else ""
            )
        raise AssertionError(f"unexpected command: {args}")


class StageReleaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.notes = root / "notes.md"
        self.notes.write_text("release notes\n", encoding="utf-8")
        self.artifacts = []
        for index in range(5):
            path = root / f"artifact-{index}"
            path.write_text(str(index), encoding="utf-8")
            self.artifacts.append(path)

    def _release(self, **changes: object) -> dict[str, object]:
        value: dict[str, object] = {
            "id": RELEASE_ID, "tag_name": TAG, "name": TITLE,
            "body": "release notes\n", "draft": True, "prerelease": False,
        }
        value.update(changes)
        return value

    def _stage(self, fake: FakeRunner):
        return stage_release.stage_release(
            repository=REPOSITORY, tag=TAG, title=TITLE,
            notes_file=self.notes, artifacts=self.artifacts,
            visibility_attempts=3, visibility_seconds=0, runner=fake,
        )

    def test_existing_exact_draft_is_reused_without_create(self) -> None:
        fake = FakeRunner([(200, self._release())])
        result = self._stage(fake)
        self.assertEqual(result["release_id"], RELEASE_ID)
        self.assertFalse(result["created_by_this_run"])
        self.assertEqual(fake.create_count, 0)

    def test_only_classified_404_creates_once(self) -> None:
        fake = FakeRunner([(404, None), (200, self._release())])
        result = self._stage(fake)
        self.assertEqual(result["release_id"], RELEASE_ID)
        self.assertTrue(result["created_by_this_run"])
        self.assertEqual(fake.create_count, 1)

    def test_auth_rate_limit_server_and_transport_fail_without_create(self) -> None:
        for status in (401, 403, 429, 500, 503, None):
            with self.subTest(status=status):
                fake = FakeRunner([(status, None)])
                with self.assertRaisesRegex(
                    stage_release.StageReleaseError, "HTTP|status"
                ):
                    self._stage(fake)
                self.assertEqual(fake.create_count, 0)

    def test_duplicate_create_race_rereads_exact_draft_without_retry(self) -> None:
        fake = FakeRunner(
            [(404, None), (200, self._release())], create_returncode=1
        )
        result = self._stage(fake)
        self.assertEqual(result["release_id"], RELEASE_ID)
        self.assertFalse(result["created_by_this_run"])
        self.assertEqual(fake.create_count, 1)

    def test_create_failure_with_continued_404_fails_without_retry(self) -> None:
        fake = FakeRunner(
            [(404, None), (404, None), (404, None), (404, None)],
            create_returncode=1,
        )
        with self.assertRaisesRegex(
            stage_release.StageReleaseError, "creation failed"
        ):
            self._stage(fake)
        self.assertEqual(fake.create_count, 1)

    def test_malformed_existing_or_race_winner_fails_closed(self) -> None:
        malformed = (
            {"id": 0}, {"id": "24680"}, {"draft": False},
            {"prerelease": True}, {"tag_name": "v0.12.1"},
            {"name": "wrong"}, {"body": "wrong"},
        )
        for initial in (True, False):
            for change in malformed:
                with self.subTest(initial=initial, change=change):
                    response = self._release(**change)
                    sequence = [(200, response)] if initial else [
                        (404, None), (200, response)
                    ]
                    fake = FakeRunner(sequence, create_returncode=1)
                    with self.assertRaises(stage_release.StageReleaseError):
                        self._stage(fake)
                    self.assertEqual(fake.create_count, 0 if initial else 1)

    def test_successful_create_tolerates_only_bounded_404_visibility_delay(self) -> None:
        fake = FakeRunner([
            (404, None), (404, None), (200, self._release()),
        ])
        result = self._stage(fake)
        self.assertEqual(result["release_id"], RELEASE_ID)
        self.assertEqual(fake.create_count, 1)

    def test_post_create_fatal_lookup_is_not_reclassified_as_absent(self) -> None:
        fake = FakeRunner([(404, None), (503, None)])
        with self.assertRaisesRegex(stage_release.StageReleaseError, "HTTP 503"):
            self._stage(fake)
        self.assertEqual(fake.create_count, 1)


if __name__ == "__main__":
    unittest.main()
