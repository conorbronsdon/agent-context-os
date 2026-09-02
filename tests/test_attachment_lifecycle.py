from __future__ import annotations

import json
import io
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout

from contextos.attachment import resolve_root_roles
from contextos.kernel import (
    ContextOSError,
    LOCAL_BINDING_MODE,
    PROJECT_BINDING_PATH,
    _validate_project_proposal_shape,
    apply_proposal,
    canonical_json,
    create_proposal,
    create_project_attachment_proposal,
    hook_report,
    load_project_attachment,
    start_report,
    sha256_text,
    validate_proposal,
)
from contextos.workspace_schema import render_workspace_config
from contextos.cli import main as cli_main


KERNEL_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat("2026-08-31T10:00:00-07:00")


def git(root: Path, *arguments: str) -> str:
    environment = dict(os.environ)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        ["git", "-c", f"safe.directory={root}", "-C", str(root), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    return result.stdout.strip()


def git_bytes(root: Path, *arguments: str) -> bytes:
    environment = dict(os.environ)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        ["git", "-c", f"safe.directory={root}", "-C", str(root), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    return result.stdout


def initialize_repository(root: Path, files: dict[str, str]) -> None:
    root.mkdir()
    git(root, "init", "--quiet")
    git(root, "config", "user.name", "Context OS Test")
    git(root, "config", "user.email", "context-os@example.invalid")
    git(root, "config", "core.autocrlf", "false")
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "fixture")


def tree_snapshot(root: Path) -> dict[str, object]:
    files: dict[str, tuple[bytes, int]] = {}
    directories: dict[str, int] = {}
    links: dict[str, tuple[str, int]] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if ".git" in relative.parts or "__pycache__" in relative.parts:
            continue
        name = relative.as_posix()
        mode = path.lstat().st_mode & 0o7777
        if path.is_symlink():
            links[name] = (os.readlink(path), mode)
        elif path.is_dir():
            directories[name] = mode
        elif path.is_file():
            files[name] = (path.read_bytes(), mode)
    return {
        "files": files,
        "directories": directories,
        "links": links,
        "context_os_exists": (
            (root / ".context-os").exists() or (root / ".context-os").is_symlink()
        ),
        "git_head": git(root, "rev-parse", "HEAD"),
        "git_tree": git(root, "rev-parse", "HEAD^{tree}"),
        "git_index": git_bytes(root, "ls-files", "--stage", "-z"),
        "git_index_flags": git_bytes(root, "ls-files", "-v", "-z"),
        "git_status": git_bytes(
            root, "status", "--porcelain=v1", "-z", "--untracked-files=all"
        ),
    }


def subprocess_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(KERNEL_ROOT)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return environment


class AttachmentLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name).resolve()
        self.context_root = base / "context"
        self.working_root = base / "working"
        workspace = render_workspace_config({
            "schema_version": 1,
            "mode": "full-template",
            "agents": [],
            "paths": {
                "state_dir": "state",
                "sessions_dir": "sessions",
                "task_file": "TODO.md",
            },
            "template": {"version": "0.12.0", "source": "test"},
        })
        initialize_repository(
            self.context_root,
            {
                "contextos.workspace.json": workspace,
                "state/current.md": "**Last Updated:** 2026-08-31\n\n# Current\n",
                "state/current-log.md": "# Current log\n",
                "TODO.md": "# Tasks\n",
                ".gitignore": ".context-os/\n",
            },
        )
        initialize_repository(
            self.working_root,
            {"app.txt": "ordinary application bytes\n"},
        )
        self.roles = resolve_root_roles(
            kernel_root=KERNEL_ROOT,
            context_root=self.context_root,
            working_root=self.working_root,
        )

    def test_attach_apply_start_and_hook_keep_working_root_read_only(self) -> None:
        before = tree_snapshot(self.working_root)
        kernel_before = tree_snapshot(KERNEL_ROOT)
        proposal_path, proposal = create_project_attachment_proposal(
            self.roles, "sample-app", NOW
        )
        receipt_path, receipt = apply_proposal(
            self.context_root,
            proposal_path,
            proposal["proposal_digest"],
            "generic",
            roles=self.roles,
        )
        self.assertTrue(receipt_path.is_file())
        self.assertEqual(receipt["operation"], "project-attach")
        self.assertEqual(tree_snapshot(self.working_root), before)
        manifest, binding = load_project_attachment(self.roles)
        self.assertEqual(manifest["project_id"], "sample-app")
        self.assertIn("sample-app", binding["bindings"])
        self.assertTrue((self.context_root / PROJECT_BINDING_PATH).is_file())

        report = start_report(self.context_root, NOW, roles=self.roles)
        self.assertEqual(report["project"]["project_id"], "sample-app")
        self.assertEqual(
            report["working_repository"]["status"]["entries"],
            [],
            report["working_repository"]["status"],
        )
        self.assertTrue(report["working_repository"]["history"])
        self.assertEqual(tree_snapshot(self.working_root), before)

        relative = hook_report(
            self.context_root,
            "pre-write",
            {"file_path": "state/current.md"},
            roles=self.roles,
        )
        absolute = hook_report(
            self.context_root,
            "pre-write",
            {"file_path": str(self.context_root / "state/current.md")},
            roles=self.roles,
        )
        self.assertEqual(relative["findings"], [])
        self.assertEqual(len(absolute["findings"]), 1)
        self.assertEqual(tree_snapshot(KERNEL_ROOT), kernel_before)

    def test_rebind_is_a_second_digest_bound_transaction(self) -> None:
        proposal_path, proposal = create_project_attachment_proposal(
            self.roles, "sample-app", NOW
        )
        apply_proposal(
            self.context_root,
            proposal_path,
            proposal["proposal_digest"],
            "generic",
            roles=self.roles,
        )
        if os.name != "nt":
            os.chmod(self.context_root / PROJECT_BINDING_PATH, 0o644)
        later = datetime.fromisoformat("2026-08-31T11:00:00-07:00")
        rebind_path, rebind = create_project_attachment_proposal(
            self.roles, "sample-app", later, rebind=True
        )
        _, receipt = apply_proposal(
            self.context_root,
            rebind_path,
            rebind["proposal_digest"],
            "generic",
            roles=self.roles,
        )
        self.assertEqual(receipt["operation"], "project-rebind")
        registry = json.loads((self.context_root / PROJECT_BINDING_PATH).read_text())
        self.assertEqual(
            registry["bindings"]["sample-app"]["bound_at"], later.isoformat()
        )
        self.assertEqual(
            (self.context_root / PROJECT_BINDING_PATH).stat().st_mode & 0o7777,
            LOCAL_BINDING_MODE,
        )

    def test_hand_authored_attach_cannot_replace_tracked_manifest(self) -> None:
        proposal_path, proposal = create_project_attachment_proposal(
            self.roles, "replace-app", NOW
        )
        manifest_change = proposal["changes"][0]
        manifest_change["before_raw_sha256"] = "0" * 64
        manifest_change["before_mode"] = manifest_change["after_mode"]
        unsigned = dict(proposal)
        unsigned.pop("proposal_digest")
        proposal["proposal_digest"] = sha256_text(canonical_json(unsigned))
        proposal_path.write_text(
            json.dumps(proposal, indent=2) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(
            ContextOSError, "project-attach must create a new tracked project manifest"
        ):
            validate_proposal(proposal)
            _validate_project_proposal_shape(self.context_root, proposal)

        binding_path, binding_proposal = create_project_attachment_proposal(
            self.roles,
            "replace-binding-app",
            datetime.fromisoformat("2026-08-31T10:01:00-07:00"),
        )
        binding_change = binding_proposal["changes"][1]
        binding_change["before_raw_sha256"] = "0" * 64
        binding_change["before_mode"] = binding_change["after_mode"]
        unsigned = dict(binding_proposal)
        unsigned.pop("proposal_digest")
        binding_proposal["proposal_digest"] = sha256_text(canonical_json(unsigned))
        binding_path.write_text(
            json.dumps(binding_proposal, indent=2) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(
            ContextOSError, "project-attach must create a new local binding"
        ):
            validate_proposal(binding_proposal)
            _validate_project_proposal_shape(self.context_root, binding_proposal)

    def test_cli_attach_apply_and_start_use_exact_roles(self) -> None:
        roots = [
            "--kernel-root", str(KERNEL_ROOT),
            "--context-root", str(self.context_root),
            "--working-root", str(self.working_root),
        ]
        output = io.StringIO()
        with redirect_stdout(output):
            result = cli_main([
                *roots,
                "project", "attach", "--id", "cli-app",
                "--now", NOW.isoformat(),
            ])
        self.assertEqual(result, 0)
        proposed = json.loads(output.getvalue())
        output = io.StringIO()
        with redirect_stdout(output):
            result = cli_main([
                *roots,
                "apply", proposed["proposal"],
                "--confirm", proposed["proposal_digest"],
                "--runtime", "generic",
            ])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["operation"], "project-attach")
        output = io.StringIO()
        with redirect_stdout(output):
            result = cli_main([*roots, "start", "--now", NOW.isoformat()])
        self.assertEqual(result, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["project"]["project_id"], "cli-app")
        self.assertEqual(report["root_roles"]["working_root"], str(self.working_root))

    @unittest.skipIf(os.name == "nt", "POSIX wrapper execution control")
    def test_split_wrapper_loads_exact_kernel_without_pythonpath(self) -> None:
        proposal_path, proposal = create_project_attachment_proposal(
            self.roles, "wrapper-app", NOW
        )
        apply_proposal(
            self.context_root,
            proposal_path,
            proposal["proposal_digest"],
            "generic",
            roles=self.roles,
        )
        environment = subprocess_environment()
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["CONTEXTOS_PYTHON"] = sys.executable
        (self.working_root / "json.py").write_text(
            'raise RuntimeError("WorkingRoot json.py must not execute")\n',
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                "bash",
                str(KERNEL_ROOT / "scripts" / "contextos.sh"),
                "--context-root", str(self.context_root),
                "--working-root", str(self.working_root),
                "start",
                "--now", NOW.isoformat(),
            ],
            cwd=self.working_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        report = json.loads(result.stdout)
        self.assertEqual(report["root_roles"]["kernel_root"], str(KERNEL_ROOT))
        self.assertEqual(report["root_roles"]["context_root"], str(self.context_root))
        self.assertEqual(report["root_roles"]["working_root"], str(self.working_root))
        contract = (KERNEL_ROOT / "docs" / "root-contract.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "executes Python from that root so\ncaller cwd cannot influence imports",
            contract,
        )
        self.assertNotIn("preserves process cwd", contract)

        linked_kernel = Path(self.temporary.name) / "linked-kernel"
        try:
            linked_kernel.symlink_to(KERNEL_ROOT, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlink creation is unavailable")
        linked_result = subprocess.run(
            [
                "bash",
                str(linked_kernel / "scripts" / "contextos.sh"),
                "--context-root", str(self.context_root),
                "--working-root", str(self.working_root),
                "start",
                "--now", NOW.isoformat(),
            ],
            cwd=self.working_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        linked_report = json.loads(linked_result.stdout)
        self.assertEqual(linked_report["root_roles"]["kernel_root"], str(KERNEL_ROOT))

    def test_split_skills_and_board_cli_keep_one_root_contract(self) -> None:
        roots = [
            "--kernel-root", str(KERNEL_ROOT),
            "--context-root", str(self.context_root),
            "--working-root", str(self.working_root),
        ]
        error = io.StringIO()
        with redirect_stderr(error):
            result = cli_main([
                *roots,
                "board", "sync",
                "--runtime", "codex",
                "--role", "generalist",
                "--run-id", "issue-155-control",
            ])
        self.assertEqual(result, 2)
        self.assertIn("board is not yet a split-root lifecycle surface", error.getvalue())

        split_prefix = (
            "split:     bash <KernelRoot>/scripts/contextos.sh "
            "--context-root <ContextRoot> --working-root <WorkingRoot>"
        )
        skill_names = ("context-setup", "context-start", "context-update", "context-end")
        for name in skill_names:
            with self.subTest(skill=name):
                text = (
                    KERNEL_ROOT / ".agents" / "skills" / name / "SKILL.md"
                ).read_text(encoding="utf-8")
                self.assertIn(split_prefix, text)
                self.assertNotIn("under `.context-os/inputs/`", text)
                self.assertNotIn("Run `bash scripts/contextos.sh start`", text)

        for name in ("context-start", "context-end"):
            with self.subTest(skill=name, surface="coordination"):
                text = (
                    KERNEL_ROOT / ".agents" / "skills" / name / "SKILL.md"
                ).read_text(encoding="utf-8")
                self.assertIn(
                    "skip coordination-board operations explicitly because the CLI",
                    text,
                )
                self.assertIn("do not probe WorkingRoot for board", text)
                self.assertIn("<ContextRoot>/coordination/README.md", text)

    def test_golden_claude_to_codex_handoff_stays_in_context_root(self) -> None:
        working_before = tree_snapshot(self.working_root)
        kernel_before = tree_snapshot(KERNEL_ROOT)
        self.assertFalse(working_before["context_os_exists"])
        self.assertFalse(kernel_before["context_os_exists"])
        attach_path, attach = create_project_attachment_proposal(
            self.roles, "handoff-app", NOW
        )
        apply_proposal(
            self.context_root,
            attach_path,
            attach["proposal_digest"],
            "generic",
            roles=self.roles,
        )
        feature_name = "issue_155_claude_bounded_change.py"
        sentinel = "ISSUE-155-CLAUDE-END: bounded_change=PASS"
        claude_script = r'''
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from contextos.attachment import resolve_root_roles
from contextos.kernel import apply_proposal, create_proposal

kernel_root = Path(sys.argv[1]).resolve()
context_root = Path(sys.argv[2]).resolve()
working_root = Path(sys.argv[3]).resolve()
feature_name = sys.argv[4]
sentinel = sys.argv[5]
feature = working_root / feature_name
feature.write_text('def bounded_result():\n    return "issue-155-pass"\n', encoding='utf-8')
test = subprocess.run(
    [sys.executable, '-c',
     'import issue_155_claude_bounded_change as feature; '
     'assert feature.bounded_result() == "issue-155-pass"; print("PASS")'],
    cwd=working_root,
    check=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)
roles = resolve_root_roles(
    kernel_root=kernel_root,
    context_root=context_root,
    working_root=working_root,
)
proposal_path, proposal = create_proposal(
    context_root,
    'end',
    {
        'what_happened': [sentinel, f'Changed {feature_name}', f'Test result: {test.stdout.strip()}'],
        'decisions': [],
        'next_time': ['Codex: inspect the bounded working-root change'],
    },
    datetime.fromisoformat('2026-08-31T10:30:00-07:00'),
)
receipt_path, receipt = apply_proposal(
    context_root,
    proposal_path,
    proposal['proposal_digest'],
    'claude',
    roles=roles,
)
print(json.dumps({'receipt': str(receipt_path), 'runtime': receipt['runtime']}))
'''
        claude = subprocess.run(
            [
                sys.executable,
                "-c",
                claude_script,
                str(KERNEL_ROOT),
                str(self.context_root),
                str(self.working_root),
                feature_name,
                sentinel,
            ],
            cwd=self.working_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=subprocess_environment(),
        )
        self.assertEqual(json.loads(claude.stdout)["runtime"], "claude")

        codex_script = r'''
import json
import sys
from datetime import datetime
from pathlib import Path

from contextos.attachment import resolve_root_roles
from contextos.kernel import start_report

kernel_root = Path(sys.argv[1]).resolve()
context_root = Path(sys.argv[2]).resolve()
working_root = Path(sys.argv[3]).resolve()
sentinel = sys.argv[4]
roles = resolve_root_roles(
    kernel_root=kernel_root,
    context_root=context_root,
    working_root=working_root,
)
report = start_report(
    context_root,
    datetime.fromisoformat('2026-08-31T10:31:00-07:00'),
    roles=roles,
)
session_path = context_root / report['latest_session']
session_text = session_path.read_text(encoding='utf-8')
print(json.dumps({
    'runtime': 'codex',
    'report': report,
    'sentinel_present': sentinel in session_text,
}))
'''
        codex = subprocess.run(
            [
                sys.executable,
                "-c",
                codex_script,
                str(KERNEL_ROOT),
                str(self.context_root),
                str(self.working_root),
                sentinel,
            ],
            cwd=self.working_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=subprocess_environment(),
        )
        resumed = json.loads(codex.stdout)
        self.assertEqual(resumed["runtime"], "codex")
        self.assertTrue(resumed["sentinel_present"])
        status_paths = {
            entry["path"]
            for entry in resumed["report"]["working_repository"]["status"]["entries"]
        }
        self.assertEqual(status_paths, {feature_name})

        session = (self.context_root / "sessions/2026-08-31.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(sentinel, session)
        self.assertIn("Test result: PASS", session)

        working_after = tree_snapshot(self.working_root)
        expected_files = dict(working_before["files"])
        expected_files[feature_name] = (
            (self.working_root / feature_name).read_bytes(),
            (self.working_root / feature_name).stat().st_mode & 0o7777,
        )
        self.assertEqual(working_after["files"], expected_files)
        for key in (
            "directories",
            "links",
            "context_os_exists",
            "git_head",
            "git_tree",
            "git_index",
            "git_index_flags",
        ):
            self.assertEqual(working_after[key], working_before[key], key)
        self.assertEqual(tree_snapshot(KERNEL_ROOT), kernel_before)

    def test_split_root_crash_recovery_preserves_kernel_and_working_roots(self) -> None:
        attach_path, attach = create_project_attachment_proposal(
            self.roles, "crash-app", NOW
        )
        apply_proposal(
            self.context_root,
            attach_path,
            attach["proposal_digest"],
            "generic",
            roles=self.roles,
        )
        proposal_path, proposal = create_proposal(
            self.context_root,
            "setup",
            {
                "files": {
                    "identity/issue-155-crash-a.md": "# Crash A\n",
                    "identity/issue-155-crash-b.md": "# Crash B\n",
                }
            },
            datetime.fromisoformat("2026-08-31T10:45:00-07:00"),
        )
        kernel_before = tree_snapshot(KERNEL_ROOT)
        working_before = tree_snapshot(self.working_root)
        self.assertFalse(kernel_before["context_os_exists"])
        self.assertFalse(working_before["context_os_exists"])
        first = self.context_root / proposal["changes"][0]["path"]
        crash_script = r'''
import os
import sys
from pathlib import Path
from unittest import mock

import contextos.kernel as kernel
from contextos.attachment import resolve_root_roles

kernel_root = Path(sys.argv[1]).resolve()
context_root = Path(sys.argv[2]).resolve()
working_root = Path(sys.argv[3]).resolve()
proposal = Path(sys.argv[4]).resolve()
digest = sys.argv[5]
first = Path(sys.argv[6]).resolve()
after = bytes.fromhex(sys.argv[7])
roles = resolve_root_roles(
    kernel_root=kernel_root,
    context_root=context_root,
    working_root=working_root,
)
real_sync = kernel._fsync_directory

def crash_after_first_target(directory):
    real_sync(directory)
    if Path(directory) == first.parent and first.is_file() and first.read_bytes() == after:
        os._exit(86)

with mock.patch('contextos.kernel._fsync_directory', side_effect=crash_after_first_target):
    kernel.apply_proposal(context_root, proposal, digest, 'codex', roles=roles)
'''
        crashed = subprocess.run(
            [
                sys.executable,
                "-c",
                crash_script,
                str(KERNEL_ROOT),
                str(self.context_root),
                str(self.working_root),
                str(proposal_path),
                proposal["proposal_digest"],
                str(first),
                proposal["changes"][0]["after_text"].encode("utf-8").hex(),
            ],
            cwd=self.working_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=subprocess_environment(),
        )
        self.assertEqual(crashed.returncode, 86, crashed.stderr.decode(errors="replace"))
        journal = self.context_root / ".context-os/journals" / proposal["proposal_id"]
        self.assertTrue(journal.is_dir())
        self.assertEqual(tree_snapshot(KERNEL_ROOT), kernel_before)
        self.assertEqual(tree_snapshot(self.working_root), working_before)

        (self.context_root / ".context-os/apply.lock").unlink()
        receipt_path, receipt = apply_proposal(
            self.context_root,
            proposal_path,
            proposal["proposal_digest"],
            "codex",
            roles=self.roles,
        )
        self.assertTrue(receipt_path.is_file())
        self.assertEqual(receipt["runtime"], "codex")
        self.assertFalse(journal.exists())
        self.assertEqual(
            (self.context_root / "identity/issue-155-crash-a.md").read_text(),
            "# Crash A\n",
        )
        self.assertEqual(
            (self.context_root / "identity/issue-155-crash-b.md").read_text(),
            "# Crash B\n",
        )
        self.assertEqual(tree_snapshot(KERNEL_ROOT), kernel_before)
        self.assertEqual(tree_snapshot(self.working_root), working_before)

    def test_root_snapshot_must_not_fire_mutation_controls(self) -> None:
        mutations = {
            "file bytes": lambda root: (root / "app.txt").write_bytes(b"mutated\n"),
            "directory": lambda root: (root / "unexpected-directory").mkdir(),
            "local state": lambda root: (root / ".context-os").mkdir(),
            "git index": lambda root: git(
                root, "update-index", "--assume-unchanged", "app.txt"
            ),
        }
        if os.name != "nt":
            mutations["file mode"] = lambda root: os.chmod(root / "app.txt", 0o600)
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                root = Path(self.temporary.name) / f"control-{label.replace(' ', '-')}"
                initialize_repository(root, {"app.txt": "ordinary application bytes\n"})
                before = tree_snapshot(root)
                mutate(root)
                with self.assertRaises(AssertionError):
                    self.assertEqual(tree_snapshot(root), before)

        tree_root = Path(self.temporary.name) / "control-git-tree"
        initialize_repository(tree_root, {"app.txt": "ordinary application bytes\n"})
        tree_before = tree_snapshot(tree_root)
        (tree_root / "tree-change.txt").write_text("tracked tree change\n", encoding="utf-8")
        git(tree_root, "add", "tree-change.txt")
        git(tree_root, "commit", "--quiet", "-m", "tree mutation control")
        with self.assertRaises(AssertionError):
            self.assertEqual(tree_snapshot(tree_root), tree_before)

    def test_resigned_project_proposal_cannot_escape_attachment_allowlist(self) -> None:
        before = tree_snapshot(self.working_root)
        proposal_path, proposal = create_project_attachment_proposal(
            self.roles, "tamper-app", NOW
        )
        proposal["changes"][0]["path"] = "../working/owned.txt"
        unsigned = dict(proposal)
        unsigned.pop("proposal_digest")
        proposal["proposal_digest"] = sha256_text(canonical_json(unsigned))
        proposal_path.write_text(
            json.dumps(proposal, indent=2) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ContextOSError, "invalid ordered path set"):
            apply_proposal(
                self.context_root,
                proposal_path,
                proposal["proposal_digest"],
                "generic",
                roles=self.roles,
            )
        self.assertEqual(tree_snapshot(self.working_root), before)

    def test_apply_rejects_explicit_roles_different_from_proposal(self) -> None:
        proposal_path, proposal = create_project_attachment_proposal(
            self.roles, "role-app", NOW
        )
        alternate = self.working_root.parent / "alternate-working"
        subprocess.run(
            ["git", "clone", "--quiet", str(self.working_root), str(alternate)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        alternate_roles = resolve_root_roles(
            kernel_root=KERNEL_ROOT,
            context_root=self.context_root,
            working_root=alternate,
        )
        with self.assertRaisesRegex(ContextOSError, "do not match explicit apply roles"):
            apply_proposal(
                self.context_root,
                proposal_path,
                proposal["proposal_digest"],
                "generic",
                roles=alternate_roles,
            )
        self.assertFalse((self.context_root / PROJECT_BINDING_PATH).exists())

    def test_attachment_requires_and_rechecks_local_binding_ignore_rule(self) -> None:
        (self.context_root / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
        git(self.context_root, "add", ".gitignore")
        git(self.context_root, "commit", "--quiet", "-m", "remove local-state ignore")
        with self.assertRaisesRegex(ContextOSError, "must be ignored by ContextRoot Git"):
            create_project_attachment_proposal(self.roles, "ignore-app", NOW)

        (self.context_root / ".gitignore").write_text(".context-os/\n", encoding="utf-8")
        git(self.context_root, "add", ".gitignore")
        git(self.context_root, "commit", "--quiet", "-m", "restore local-state ignore")
        proposal_path, proposal = create_project_attachment_proposal(
            self.roles, "ignore-app", NOW
        )
        apply_proposal(
            self.context_root,
            proposal_path,
            proposal["proposal_digest"],
            "generic",
            roles=self.roles,
        )
        (self.context_root / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
        git(self.context_root, "add", ".gitignore")
        git(self.context_root, "commit", "--quiet", "-m", "remove binding ignore")
        with self.assertRaisesRegex(ContextOSError, "must be ignored by ContextRoot Git"):
            load_project_attachment(self.roles)

    def test_project_apply_requires_explicit_split_roles(self) -> None:
        proposal_path, proposal = create_project_attachment_proposal(
            self.roles, "role-required-app", NOW
        )
        with self.assertRaisesRegex(
            ContextOSError, "project attachment apply requires explicit split root roles"
        ):
            apply_proposal(
                self.context_root,
                proposal_path,
                proposal["proposal_digest"],
                "generic",
            )
        self.assertFalse((self.context_root / PROJECT_BINDING_PATH).exists())

    def test_apply_reasserts_canonical_context_configuration(self) -> None:
        before = tree_snapshot(self.working_root)
        proposal_path, proposal = create_project_attachment_proposal(
            self.roles, "config-app", NOW
        )
        config_path = self.context_root / "contextos.workspace.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config_path.write_text(
            json.dumps(config, separators=(",", ":")), encoding="utf-8"
        )
        with self.assertRaisesRegex(
            ContextOSError, "requires canonical contextos.workspace.json"
        ):
            apply_proposal(
                self.context_root,
                proposal_path,
                proposal["proposal_digest"],
                "generic",
                roles=self.roles,
            )
        self.assertFalse((self.context_root / PROJECT_BINDING_PATH).exists())
        self.assertEqual(tree_snapshot(self.working_root), before)

    def test_attachment_read_rejects_linked_local_binding(self) -> None:
        proposal_path, proposal = create_project_attachment_proposal(
            self.roles, "linked-binding-app", NOW
        )
        apply_proposal(
            self.context_root,
            proposal_path,
            proposal["proposal_digest"],
            "generic",
            roles=self.roles,
        )
        binding_path = self.context_root / PROJECT_BINDING_PATH
        external = self.context_root.parent / "external-binding.json"
        external.write_bytes(binding_path.read_bytes())
        binding_path.unlink()
        try:
            binding_path.symlink_to(external)
        except OSError:
            self.skipTest("file symlink creation is unavailable")
        with self.assertRaisesRegex(ContextOSError, "symlink or reparse point"):
            load_project_attachment(self.roles)

    def test_attachment_read_rejects_linked_tracked_manifest_parent(self) -> None:
        proposal_path, proposal = create_project_attachment_proposal(
            self.roles, "linked-manifest-app", NOW
        )
        apply_proposal(
            self.context_root,
            proposal_path,
            proposal["proposal_digest"],
            "generic",
            roles=self.roles,
        )
        manifest_dir = self.context_root / "projects" / "linked-manifest-app"
        external = self.context_root.parent / "external-project-manifest"
        manifest_dir.rename(external)
        try:
            manifest_dir.symlink_to(external, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlink creation is unavailable")
        with self.assertRaisesRegex(ContextOSError, "symlink or reparse point"):
            load_project_attachment(self.roles)


if __name__ == "__main__":
    unittest.main()
