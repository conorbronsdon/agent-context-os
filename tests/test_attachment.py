from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from contextos.attachment import (
    AttachmentError,
    _contains,
    create_local_binding,
    create_tracked_manifest,
    git_evidence,
    observe_git_identity,
    resolve_root_roles,
    tracked_manifest_relative_path,
    validate_git_identity,
    validate_local_binding,
    validate_tracked_manifest,
)


BOUND_AT = "2026-08-31T12:00:00-07:00"


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=Context OS Tests", "-c",
         "user.email=context-os-tests@example.invalid", *arguments],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def initialize_repository(root: Path, *, filename: str = "app.txt") -> str:
    root.mkdir()
    git(root, "init", "--quiet")
    (root / filename).write_text(f"initial {root.name}\n", encoding="utf-8")
    git(root, "add", filename)
    git(root, "commit", "--quiet", "-m", "initial fixture")
    return git(root, "rev-parse", "HEAD")


class AttachmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.kernel = self.base / "kernel"
        self.context = self.base / "context"
        self.working = self.base / "working"
        self.kernel.mkdir()
        self.context.mkdir()
        self.head = initialize_repository(self.working)

    def roles(
        self,
        *,
        kernel: Path | None = None,
        context: Path | None = None,
        working: Path | None = None,
    ):
        return resolve_root_roles(
            kernel_root=kernel or self.kernel,
            context_root=context or self.context,
            working_root=working or self.working,
        )

    def manifest(self, project_id: str = "example-app") -> dict:
        return create_tracked_manifest(project_id, self.working)

    def binding(self, project_id: str = "example-app") -> tuple[dict, dict]:
        manifest = self.manifest(project_id)
        return manifest, create_local_binding(
            self.roles(), manifest, bound_at=BOUND_AT
        )

    def test_root_roles_are_exact_and_legacy_colocation_is_explicit(self) -> None:
        roles = self.roles()
        self.assertEqual(self.kernel, roles.kernel_root)
        self.assertEqual(self.context, roles.context_root)
        self.assertEqual(self.working, roles.working_root)
        self.assertFalse(roles.colocated)

        legacy = resolve_root_roles(
            kernel_root=self.context, legacy_root=self.context
        )
        self.assertTrue(legacy.colocated)
        self.assertEqual(self.context, legacy.context_root)
        self.assertEqual(self.context, legacy.working_root)

        with self.assertRaisesRegex(AttachmentError, "both context_root and working_root"):
            resolve_root_roles(kernel_root=self.kernel, context_root=self.context)
        with self.assertRaisesRegex(AttachmentError, "cannot be combined"):
            resolve_root_roles(
                kernel_root=self.kernel,
                legacy_root=self.context,
                context_root=self.context,
                working_root=self.working,
            )
        # The control needs only a relative spelling. Building one from the
        # temporary fixture fails when hosted Windows puts TEMP and checkout
        # on different drive letters.
        relative = Path("relative-working-root")
        with self.assertRaisesRegex(AttachmentError, "exact absolute"):
            resolve_root_roles(
                kernel_root=self.kernel,
                context_root=self.context,
                working_root=relative,
            )

    def test_split_roles_reject_equal_nested_and_link_roots(self) -> None:
        with self.assertRaisesRegex(AttachmentError, "must be distinct"):
            resolve_root_roles(
                kernel_root=self.kernel,
                context_root=self.context,
                working_root=self.context,
            )

        nested = self.context / "application"
        nested.mkdir()
        with self.assertRaisesRegex(AttachmentError, "must not overlap"):
            resolve_root_roles(
                kernel_root=self.kernel,
                context_root=self.context,
                working_root=nested,
            )

        link = self.base / "working-link"
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link), str(self.working)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if result.returncode != 0:
                    self.skipTest("Windows junction creation is unavailable")
            else:
                link.symlink_to(self.working, target_is_directory=True)
        except OSError:
            self.skipTest("directory links are unavailable")
        with self.assertRaisesRegex(AttachmentError, "symlink or reparse|link traversal"):
            resolve_root_roles(
                kernel_root=self.kernel,
                context_root=self.context,
                working_root=link,
            )

    def test_overlap_uses_filesystem_identity_not_lexical_case(self) -> None:
        parent = Path("/Volumes/Application")
        child = Path("/volumes/application/context")

        def samefile(left: Path, right: Path) -> bool:
            return str(left).casefold() == str(right).casefold()

        with mock.patch(
            "contextos.attachment.os.path.samefile", side_effect=samefile
        ) as identity_check:
            self.assertTrue(_contains(parent, child))
            self.assertGreater(identity_check.call_count, 0)

    def test_tracked_manifest_is_closed_portable_and_contains_no_path(self) -> None:
        manifest = self.manifest()
        self.assertEqual(
            {
                "schema_version": 1,
                "project_id": "example-app",
                "repository_identity": {
                    "object_format": "sha1",
                    "anchor_commit": self.head,
                },
            },
            manifest,
        )
        self.assertNotIn(str(self.working), json.dumps(manifest))
        self.assertEqual(
            "projects/example-app/contextos.project.json",
            tracked_manifest_relative_path("example-app"),
        )
        self.assertEqual(manifest, validate_tracked_manifest(manifest))

        for project_id in ("", "Example", "1example", "example_app", "a" * 65):
            with self.subTest(project_id=project_id):
                with self.assertRaises(AttachmentError):
                    create_tracked_manifest(project_id, self.working)
        altered = {**manifest, "working_root": str(self.working)}
        with self.assertRaisesRegex(AttachmentError, "exactly"):
            validate_tracked_manifest(altered)

    def test_local_binding_is_closed_and_revalidates_tracked_identity(self) -> None:
        manifest, binding = self.binding()
        roles = validate_local_binding(binding, manifest)
        self.assertEqual(self.kernel, roles.kernel_root)
        self.assertEqual(self.context, roles.context_root)
        self.assertEqual(self.working, roles.working_root)
        entry = binding["bindings"]["example-app"]
        self.assertEqual(BOUND_AT, entry["bound_at"])
        self.assertEqual(str(self.working), entry["working_root"])

        altered = json.loads(json.dumps(binding))
        altered["bindings"]["example-app"]["repository_identity"][
            "anchor_commit"
        ] = "0" * len(self.head)
        with self.assertRaisesRegex(AttachmentError, "differs from tracked"):
            validate_local_binding(altered, manifest)

        unknown = {**binding, "unknown": True}
        with self.assertRaisesRegex(AttachmentError, "exactly"):
            validate_local_binding(unknown, manifest)

    def test_git_identity_survives_commits_and_a_repository_move(self) -> None:
        identity = observe_git_identity(self.working)
        (self.working / "second.txt").write_text("second\n", encoding="utf-8")
        git(self.working, "add", "second.txt")
        git(self.working, "commit", "--quiet", "-m", "second fixture")
        self.assertEqual(self.working, validate_git_identity(self.working, identity))

        moved = self.base / "moved-working"
        self.working.rename(moved)
        self.working = moved
        self.assertEqual(moved, validate_git_identity(moved, identity))

    def test_git_evidence_separates_stable_identity_from_head_and_status(self) -> None:
        identity = observe_git_identity(self.working)
        (self.working / "app.txt").write_text("dirty\n", encoding="utf-8")
        (self.working / "untracked.txt").write_text("new\n", encoding="utf-8")
        evidence = git_evidence(self.working, identity=identity, max_commits=1)
        self.assertEqual(identity, evidence["repository_identity"])
        self.assertEqual(self.head, evidence["head"])
        self.assertFalse(evidence["status"]["clean"])
        self.assertEqual(2, len(evidence["status"]["entries"]))
        self.assertEqual(1, len(evidence["history"]))
        self.assertEqual(self.head, evidence["history"][0]["commit"])
        self.assertIsInstance(evidence["branch"], (str, type(None)))
        with self.assertRaisesRegex(AttachmentError, "0 through 100"):
            git_evidence(self.working, max_commits=101)

    def test_git_evidence_handles_commit_subject_control_separators(self) -> None:
        identity = observe_git_identity(self.working)
        (self.working / "control.txt").write_text("control\n", encoding="utf-8")
        git(self.working, "add", "control.txt")
        subject = "record\x1e separator and field\x1f separator"
        git(self.working, "commit", "--quiet", "-m", subject)
        evidence = git_evidence(self.working, identity=identity, max_commits=2)
        self.assertEqual(subject, evidence["history"][0]["subject"])
        json.dumps(evidence, ensure_ascii=False).encode("utf-8")

    @unittest.skipIf(os.name == "nt", "POSIX arbitrary path-byte control")
    def test_git_evidence_escapes_non_utf8_status_paths(self) -> None:
        raw_path = os.fsencode(self.working) + b"/invalid-\xff.txt"
        descriptor = os.open(raw_path, os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, b"arbitrary path bytes\n")
        finally:
            os.close(descriptor)
        evidence = git_evidence(self.working, max_commits=0)
        self.assertIn("\\xff", evidence["status"]["entries"][0]["path"])
        json.dumps(evidence, ensure_ascii=False).encode("utf-8")

    def test_nested_working_directory_is_not_repository_identity(self) -> None:
        nested = self.working / "src"
        nested.mkdir()
        with self.assertRaisesRegex(AttachmentError, "exact Git top-level"):
            observe_git_identity(nested)

        nested_repo = self.working / "nested-repository"
        nested_head = initialize_repository(nested_repo)
        nested_identity = observe_git_identity(nested_repo)
        self.assertEqual(nested_head, nested_identity["anchor_commit"])
        with self.assertRaisesRegex(AttachmentError, "does not contain"):
            validate_git_identity(nested_repo, self.manifest()["repository_identity"])

    def test_stale_replaced_repository_binding_fails(self) -> None:
        manifest, binding = self.binding()
        displaced = self.base / "displaced-working"
        self.working.rename(displaced)
        initialize_repository(self.working, filename="replacement.txt")

        with self.assertRaisesRegex(AttachmentError, "does not contain"):
            validate_local_binding(binding, manifest)

    def test_move_requires_explicit_rebinding_after_identity_validation(self) -> None:
        manifest, old_binding = self.binding()
        moved = self.base / "moved-working"
        self.working.rename(moved)

        with self.assertRaisesRegex(AttachmentError, "cannot resolve working_root"):
            validate_local_binding(old_binding, manifest)

        moved_roles = self.roles(working=moved)
        new_binding = create_local_binding(
            moved_roles, manifest, bound_at="2026-09-01T09:00:00-07:00"
        )
        validated = validate_local_binding(new_binding, manifest)
        self.assertEqual(moved, validated.working_root)

    def test_two_context_roots_may_make_nonexclusive_claims(self) -> None:
        second_kernel = self.base / "second-kernel"
        second_context = self.base / "second-context"
        second_kernel.mkdir()
        second_context.mkdir()
        first_manifest = self.manifest("first-context-app")
        second_manifest = self.manifest("second-context-app")
        first_binding = create_local_binding(
            self.roles(), first_manifest, bound_at=BOUND_AT
        )
        second_binding = create_local_binding(
            self.roles(kernel=second_kernel, context=second_context),
            second_manifest,
            bound_at=BOUND_AT,
        )

        first = validate_local_binding(first_binding, first_manifest)
        second = validate_local_binding(second_binding, second_manifest)
        self.assertEqual(first.working_root, second.working_root)
        self.assertNotEqual(first.context_root, second.context_root)


if __name__ == "__main__":
    unittest.main()
