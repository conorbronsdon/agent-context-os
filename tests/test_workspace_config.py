from __future__ import annotations

import json
import io
import os
import re
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from contextos import __version__
from contextos.kernel import (
    ContextOSError,
    doctor,
    migrate_legacy_runtime_state,
    plan_workspace_migration,
    resolve_workspace,
    workspace_resolution_report,
)
from contextos.cli import main as cli_main
from contextos.workspace_schema import (
    DEFAULT_PATHS,
    DEFAULT_TEMPLATE_VERSION,
    WorkspaceConfigError,
    analyze_legacy_workspace,
    load_workspace_config,
    parse_agent_selection,
    render_workspace_config,
    strict_json_loads,
    validate_workspace_config,
    workspace_schema_document,
)


ROOT = Path(__file__).resolve().parents[1]
KNOWN = {"claude", "codex", "hermes"}


def make_directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise OSError(result.stderr or result.stdout)
    else:
        link.symlink_to(target, target_is_directory=True)


def config(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "mode": "full-template",
        "agents": ["claude", "codex"],
        "paths": dict(DEFAULT_PATHS),
        "template": {
            "version": "0.12.0",
            "source": "agent-context-os-template",
        },
    }
    value.update(overrides)
    return value


class WorkspaceConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "state").mkdir()
        (self.root / "sessions").mkdir()
        (self.root / "runtimes").mkdir()
        (self.root / "AGENTS.md").write_text("# Fixture\n", encoding="utf-8")
        (self.root / "TODO.md").write_text("# Tasks\n", encoding="utf-8")
        for runtime in KNOWN:
            (self.root / "runtimes" / f"{runtime}.json").write_text(
                "{}\n", encoding="utf-8"
            )

    def write_json(self, value: object) -> Path:
        path = self.root / "contextos.workspace.json"
        if isinstance(value, str):
            path.write_text(value, encoding="utf-8")
        else:
            path.write_text(render_workspace_config(value), encoding="utf-8")
        return path

    def test_repository_config_and_generated_schema_are_current(self) -> None:
        loaded, canonical = load_workspace_config(
            ROOT / "workspace/example.json",
            root=ROOT,
            known_runtime_ids=KNOWN,
        )
        self.assertTrue(canonical)
        self.assertEqual([], loaded["agents"])
        self.assertEqual(__version__, loaded["template"]["version"])
        self.assertEqual(__version__, DEFAULT_TEMPLATE_VERSION)
        live_path = ROOT / "contextos.workspace.json"
        if os.environ.get("CONTEXTOS_VALIDATION_PROFILE") == "workspace" \
                and live_path.exists():
            live, _live_canonical = load_workspace_config(
                live_path, root=ROOT, known_runtime_ids=KNOWN
            )
            self.assertLessEqual(set(live["agents"]), KNOWN)
        else:
            self.assertFalse(live_path.exists())
        self.assertEqual(
            workspace_schema_document(),
            json.loads((ROOT / "workspace/schema.json").read_text(encoding="utf-8")),
        )

    def test_agents_are_an_unordered_canonical_set(self) -> None:
        value = validate_workspace_config(
            config(agents=["hermes", "claude", "codex"]),
            known_runtime_ids=KNOWN,
        )
        self.assertEqual(["claude", "codex", "hermes"], value["agents"])
        self.assertEqual(
            [],
            validate_workspace_config(config(agents=[]), known_runtime_ids=KNOWN)[
                "agents"
            ],
        )
        for agents, message in (
            (["claude", "claude"], "duplicate"),
            (["claude", "CLAUDE"], "lowercase"),
            (["missing"], "unknown"),
            (["none"], "registered lowercase"),
            (["auto"], "registered lowercase"),
            (["generic"], "registered lowercase"),
            ("claude", "array"),
        ):
            with self.subTest(agents=agents), self.assertRaisesRegex(
                WorkspaceConfigError, message
            ):
                validate_workspace_config(config(agents=agents), known_runtime_ids=KNOWN)

    def test_agent_selection_none_auto_alias_and_ambiguity(self) -> None:
        self.assertEqual([], parse_agent_selection("none", known_runtime_ids=KNOWN))
        self.assertEqual(
            ["claude", "codex"],
            parse_agent_selection("codex, claude", known_runtime_ids=KNOWN),
        )
        self.assertIsNone(
            parse_agent_selection("auto", known_runtime_ids=KNOWN, allow_auto=True)
        )
        for selection in ("", "claude,", "none,claude", "auto,claude", "claude,claude"):
            with self.subTest(selection=selection), self.assertRaises(
                WorkspaceConfigError
            ):
                parse_agent_selection(selection, known_runtime_ids=KNOWN)

    def test_schema_objects_types_paths_and_template_are_closed(self) -> None:
        mutations: list[tuple[dict[str, object], str]] = []
        extra = config()
        extra["unknown"] = True
        mutations.append((extra, "unknown unknown"))
        boolean = config(schema_version=True)
        mutations.append((boolean, "integer 1"))
        future = config(schema_version=2)
        mutations.append((future, "integer 1"))
        mode = config(mode="composed")
        mutations.append((mode, "full-template"))
        missing_path = config(paths={"state_dir": "state", "sessions_dir": "sessions"})
        mutations.append((missing_path, "missing task_file"))
        blank_template = config(template={"version": " ", "source": "bundle"})
        mutations.append((blank_template, "non-empty"))
        for value, message in mutations:
            with self.subTest(message=message), self.assertRaisesRegex(
                WorkspaceConfigError, message
            ):
                validate_workspace_config(value, known_runtime_ids=KNOWN)

        unsafe = (
            "/absolute", "C:/absolute", "//server/share", "a\\b", "a/./b",
            "a/../b", "a//b", "trailing/", ".git/config", ".context-os/state",
            "folder/CON", "folder/name.", "folder/file:stream",
        )
        for path in unsafe:
            with self.subTest(path=path), self.assertRaises(WorkspaceConfigError):
                validate_workspace_config(
                    config(paths={**DEFAULT_PATHS, "state_dir": path}),
                    known_runtime_ids=KNOWN,
                )

        for paths in (
            {"state_dir": "STATE", "sessions_dir": "state", "task_file": "TODO.md"},
            {"state_dir": "data", "sessions_dir": "data/sessions", "task_file": "TODO.md"},
            {"state_dir": "state", "sessions_dir": "sessions", "task_file": "STATE"},
            {"state_dir": "data/state", "sessions_dir": "sessions", "task_file": "data"},
            {"state_dir": "state", "sessions_dir": "data/sessions", "task_file": "data"},
        ):
            with self.subTest(paths=paths), self.assertRaisesRegex(
                WorkspaceConfigError, "paths"
            ):
                validate_workspace_config(config(paths=paths), known_runtime_ids=KNOWN)

    def test_generated_path_pattern_rejects_dot_segments_not_dotfiles(self) -> None:
        pattern = workspace_schema_document()["properties"]["paths"]["properties"][
            "state_dir"
        ]["pattern"]
        for accepted in (".github/state", "a/.private/state", "state"):
            with self.subTest(accepted=accepted):
                self.assertIsNotNone(re.match(pattern, accepted))
        for rejected in (
            ".",
            "..",
            "./state",
            "a/./state",
            "a/../state",
            " state",
            "state ",
            "state\t",
            "state\n",
            "state\x00",
            "state\x08",
            "state\x7f",
        ):
            with self.subTest(rejected=rejected):
                self.assertIsNone(re.match(pattern, rejected))

    def test_strict_json_rejects_duplicates_constants_bom_and_invalid_json(self) -> None:
        for raw, message in (
            ('{"a": 1, "a": 2}', "duplicate"),
            ('{"a": NaN}', "constant"),
            ('\ufeff{"a": 1}', "BOM"),
            ('{"a":', "invalid JSON"),
        ):
            with self.subTest(raw=raw), self.assertRaisesRegex(
                WorkspaceConfigError, message
            ):
                strict_json_loads(raw, source="fixture.json")

    def test_json_precedence_is_whole_document_and_fails_closed(self) -> None:
        self.write_json(config())
        (self.root / "workspace.yaml").write_text(
            "state_dir: other-state\n", encoding="utf-8"
        )
        resolution = resolve_workspace(self.root)
        self.assertEqual("json", resolution.source)
        self.assertEqual(
            (self.root / "state").resolve(), resolution.workspace.state_dir
        )
        self.assertIn("conflicts", resolution.notices[0]["message"])

        self.write_json("{")
        with self.assertRaisesRegex(ContextOSError, "invalid tracked"):
            resolve_workspace(self.root)

        (self.root / "contextos.workspace.json").write_bytes(b"\xff")
        with self.assertRaisesRegex(ContextOSError, "invalid tracked"):
            resolve_workspace(self.root)

        self.write_json(
            '{"schema_version":1,"schema_version":1,"mode":"full-template",'
            '"agents":[],"paths":{"state_dir":"state","sessions_dir":"sessions",'
            '"task_file":"TODO.md"},"template":{"version":"1","source":"x"}}'
        )
        with self.assertRaisesRegex(ContextOSError, "duplicate JSON"):
            resolve_workspace(self.root)

    def test_valid_json_ignores_but_reports_malformed_shadowed_yaml(self) -> None:
        self.write_json(config())
        (self.root / "workspace.yaml").write_bytes(b"\xff")
        resolution = resolve_workspace(self.root)
        self.assertEqual("json", resolution.source)
        self.assertIn("cannot be read", resolution.notices[0]["message"])

    def test_shadowed_legacy_symlink_is_reported_without_being_read(self) -> None:
        self.write_json(config())
        outside = self.root / "outside.yaml"
        outside.write_text("state_dir: secret\n", encoding="utf-8")
        link = self.root / "workspace.yaml"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("symlink creation is unavailable")
        resolution = resolve_workspace(self.root)
        self.assertIn("must not be a symlink", resolution.notices[0]["message"])
        self.assertNotIn("secret", resolution.notices[0]["message"])

    def test_doctor_reports_invalid_json_without_falling_back_or_crashing(self) -> None:
        self.write_json("{")
        (self.root / "workspace.yaml").write_text(
            "state_dir: state\n", encoding="utf-8"
        )
        report = doctor(self.root)
        check = next(
            item for item in report["checks"] if item["name"] == "workspace-config"
        )
        self.assertEqual("fail", check["status"])
        self.assertIn("invalid tracked", check["detail"])

    def test_doctor_warns_for_noncanonical_or_shadowed_json(self) -> None:
        self.write_json(json.dumps(config(), separators=(",", ":")))
        report = doctor(self.root)
        check = next(
            item for item in report["checks"] if item["name"] == "workspace-config"
        )
        self.assertEqual("warn", check["status"])

        self.write_json(config())
        (self.root / "workspace.yaml").write_text(
            "state_dir: state\n", encoding="utf-8"
        )
        report = doctor(self.root)
        check = next(
            item for item in report["checks"] if item["name"] == "workspace-config"
        )
        self.assertEqual("warn", check["status"])

    def test_legacy_reader_remains_compatible_but_preview_is_loss_aware(self) -> None:
        legacy = self.root / "workspace.yaml"
        legacy.write_text(
            "state_dir: first\nstate_dir: second\nunknown: ignored\n",
            encoding="utf-8",
        )
        resolution = resolve_workspace(self.root)
        self.assertEqual("legacy-yaml", resolution.source)
        self.assertEqual(
            (self.root / "second").resolve(), resolution.workspace.state_dir
        )
        with self.assertRaisesRegex(ContextOSError, "cannot be migrated losslessly"):
            plan_workspace_migration(self.root, ["claude"])

        legacy.write_text('state_dir: "foo#bar"\n', encoding="utf-8")
        self.assertEqual(
            (self.root / "foo").resolve(),
            resolve_workspace(self.root).workspace.state_dir,
        )
        with self.assertRaisesRegex(ContextOSError, "historical reader"):
            plan_workspace_migration(self.root, ["claude"])

    def test_legacy_benign_noncanonical_paths_still_run_and_migrate(self) -> None:
        legacy = self.root / "workspace.yaml"
        for raw, expected in (
            ("./custom-state", "custom-state"),
            ("custom-state/", "custom-state"),
            ("custom//state", "custom/state"),
        ):
            with self.subTest(raw=raw):
                legacy.write_text(f"state_dir: {raw}\n", encoding="utf-8")
                resolution = resolve_workspace(self.root)
                self.assertEqual(
                    (self.root / expected).resolve(), resolution.workspace.state_dir
                )
                preview = plan_workspace_migration(self.root, ["claude"])
                self.assertEqual(expected, preview["config"]["paths"]["state_dir"])

        legacy.write_text("state_dir: custom\\state\n", encoding="utf-8")
        self.assertEqual(
            (self.root / Path("custom\\state")).resolve(),
            resolve_workspace(self.root).workspace.state_dir,
        )
        with self.assertRaisesRegex(ContextOSError, "POSIX separators"):
            plan_workspace_migration(self.root, ["claude"])

    def test_normative_legacy_migration_fixtures(self) -> None:
        cases = json.loads(
            (ROOT / "tests/fixtures/workspace-migrations.json").read_text(
                encoding="utf-8"
            )
        )
        for case in cases:
            with self.subTest(case=case["id"]):
                legacy = self.root / "workspace.yaml"
                legacy.unlink(missing_ok=True)
                if case["legacy"] is not None:
                    legacy.write_text(case["legacy"], encoding="utf-8")
                if "error" in case:
                    with self.assertRaisesRegex(ContextOSError, case["error"]):
                        plan_workspace_migration(self.root, ["claude"])
                else:
                    first = plan_workspace_migration(self.root, ["claude"])
                    second = plan_workspace_migration(self.root, ["claude"])
                    self.assertFalse(first["writes"])
                    self.assertEqual(first, second)
                    self.assertEqual(case["expected_paths"], first["config"]["paths"])
                    self.assertFalse((self.root / "contextos.workspace.json").exists())

    def test_normative_precedence_rerun_and_local_conflict_fixtures(self) -> None:
        cases = json.loads(
            (ROOT / "tests/fixtures/workspace-conflicts.json").read_text(
                encoding="utf-8"
            )
        )
        for case in cases:
            with self.subTest(case=case["id"]):
                (self.root / "contextos.workspace.json").unlink(missing_ok=True)
                (self.root / "workspace.yaml").unlink(missing_ok=True)
                local = self.root / ".context-os"
                if local.exists():
                    for child in local.iterdir():
                        child.unlink()
                else:
                    local.mkdir()

                if case["kind"] == "precedence":
                    self.write_json(
                        config(
                            paths={
                                **DEFAULT_PATHS,
                                "state_dir": case["json_state_dir"],
                            }
                        )
                    )
                    (self.root / "workspace.yaml").write_text(
                        f"state_dir: {case['yaml_state_dir']}\n", encoding="utf-8"
                    )
                    resolution = resolve_workspace(self.root)
                    self.assertEqual(case["expected_source"], resolution.source)
                    self.assertIn(case["expected_notice"], resolution.notices[0]["message"])
                elif case["kind"] == "invalid-json":
                    self.write_json("{")
                    (self.root / "workspace.yaml").write_text(
                        f"state_dir: {case['yaml_state_dir']}\n", encoding="utf-8"
                    )
                    with self.assertRaisesRegex(ContextOSError, case["error"]):
                        resolve_workspace(self.root)
                elif case["kind"] == "agent-rerun":
                    self.write_json(config(agents=case["configured"]))
                    if "error" in case:
                        with self.assertRaisesRegex(ContextOSError, case["error"]):
                            plan_workspace_migration(self.root, case["requested"])
                    else:
                        report = plan_workspace_migration(self.root, case["requested"])
                        self.assertEqual(case["expected_action"], report["action"])
                elif case["kind"] == "local-host":
                    first = {
                        "installed_at": "2026-08-20T12:00:00+00:00",
                        "source_manifest_sha256": "a" * 64,
                    }
                    second = first if case["same_entry"] else {
                        "installed_at": "2026-08-21T12:00:00+00:00",
                        "source_manifest_sha256": "b" * 64,
                    }
                    (local / "runtime.json").write_text(
                        json.dumps({
                            "schema_version": 1,
                            "runtime": case["scalar_runtime"],
                            **first,
                        }),
                        encoding="utf-8",
                    )
                    (local / "hosts.json").write_text(
                        json.dumps({
                            "schema_version": 1,
                            "hosts": {case["host_runtime"]: second},
                        }),
                        encoding="utf-8",
                    )
                    if "error" in case:
                        with self.assertRaisesRegex(ContextOSError, case["error"]):
                            migrate_legacy_runtime_state(self.root)
                    else:
                        _, state, changed, migrated = migrate_legacy_runtime_state(
                            self.root
                        )
                        self.assertTrue(changed)
                        self.assertEqual(case["scalar_runtime"], migrated)
                        self.assertEqual(case["expected_hosts"], list(state["hosts"]))

    def test_existing_json_rerun_expands_but_never_shrinks_or_replaces(self) -> None:
        self.write_json(config(
            agents=["claude"],
            template={"version": "9.9.9", "source": "private-bundle"},
        ))
        same = plan_workspace_migration(self.root, ["claude"])
        self.assertEqual("noop", same["action"])
        expanded = plan_workspace_migration(self.root, ["claude", "codex"])
        self.assertEqual("update", expanded["action"])
        self.assertIn('"codex"', expanded["diff"])
        self.assertEqual(
            {"version": "9.9.9", "source": "private-bundle"},
            expanded["config"]["template"],
        )
        for agents in ([], ["codex"], ["hermes"]):
            with self.subTest(agents=agents), self.assertRaisesRegex(
                ContextOSError, "will not shrink or replace"
            ):
                plan_workspace_migration(self.root, agents)

    def test_unsorted_json_is_read_without_mutation_and_reported_noncanonical(self) -> None:
        raw = json.dumps(config(agents=["codex", "claude"]), separators=(",", ":"))
        path = self.write_json(raw)
        before = path.read_bytes()
        report = workspace_resolution_report(self.root)
        self.assertEqual(["claude", "codex"], report["agents"])
        self.assertFalse(report["canonical"])
        self.assertEqual(before, path.read_bytes())

    def test_workspace_config_symlink_is_rejected(self) -> None:
        outside = self.root / "outside.json"
        outside.write_text(render_workspace_config(config()), encoding="utf-8")
        link = self.root / "contextos.workspace.json"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("symlink creation is unavailable")
        with self.assertRaisesRegex(ContextOSError, "symlink"):
            resolve_workspace(self.root)

    def test_workspace_config_case_alias_is_rejected_portably(self) -> None:
        alias = self.root / "ContextOS.Workspace.json"
        alias.write_text(render_workspace_config(config()), encoding="utf-8")
        with self.assertRaisesRegex(ContextOSError, "filename collision"):
            resolve_workspace(self.root)
        with self.assertRaisesRegex(ContextOSError, "filename collision"):
            plan_workspace_migration(self.root, ["claude"])

    def test_configured_path_symlink_ancestor_is_rejected(self) -> None:
        real = self.root / "real-state"
        real.mkdir()
        link = self.root / "linked-state"
        try:
            make_directory_link(link, real)
        except OSError:
            self.skipTest("directory link creation is unavailable")
        self.write_json(config(paths={**DEFAULT_PATHS, "state_dir": "linked-state"}))
        with self.assertRaisesRegex(ContextOSError, "symlink"):
            resolve_workspace(self.root)

    def test_default_path_symlink_keeps_legacy_runtime_behavior_but_cannot_migrate(self) -> None:
        real = self.root / "real-state"
        real.mkdir()
        (self.root / "state").rmdir()
        try:
            make_directory_link(self.root / "state", real)
        except OSError:
            self.skipTest("directory link creation is unavailable")

        resolution = resolve_workspace(self.root)
        self.assertEqual("defaults", resolution.source)
        self.assertEqual(real.resolve(), resolution.workspace.state_dir)
        with self.assertRaisesRegex(ContextOSError, "cannot be activated safely"):
            plan_workspace_migration(self.root, ["claude"])

    def test_legacy_linked_path_cannot_preview_unloadable_json(self) -> None:
        real = self.root / "real-state"
        real.mkdir()
        linked = self.root / "linked-state"
        try:
            make_directory_link(linked, real)
        except OSError:
            self.skipTest("directory link creation is unavailable")
        (self.root / "workspace.yaml").write_text(
            "state_dir: linked-state\n", encoding="utf-8"
        )

        resolution = resolve_workspace(self.root)
        self.assertEqual("legacy-yaml", resolution.source)
        self.assertEqual(real.resolve(), resolution.workspace.state_dir)
        with self.assertRaisesRegex(ContextOSError, "cannot be activated safely"):
            plan_workspace_migration(self.root, ["claude"])

    def test_legacy_analyzer_reports_every_ambiguous_line(self) -> None:
        analysis = analyze_legacy_workspace(
            "state_dir: state\nstate_dir: other\nunknown: x\n  nested: y\n"
        )
        self.assertEqual({"state_dir": "state"}, analysis.values)
        self.assertEqual(3, len(analysis.issues))

    def test_workspace_cli_show_preview_alias_and_auto_semantics(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(
                0,
                cli_main(["--root", str(self.root), "workspace", "show"]),
            )
        self.assertEqual("defaults", json.loads(output.getvalue())["source"])

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(
                0,
                cli_main(
                    [
                        "--root", str(self.root), "workspace", "migrate",
                        "--agents", "none",
                    ]
                ),
            )
        preview = json.loads(output.getvalue())
        self.assertFalse(preview["writes"])
        self.assertEqual([], preview["config"]["agents"])

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(
                0,
                cli_main(
                    [
                        "--root", str(self.root), "workspace", "migrate",
                        "--agent", "claude",
                    ]
                ),
            )
        self.assertIn("deprecated", " ".join(json.loads(output.getvalue())["notices"]))

        errors = io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(
                2,
                cli_main(
                    [
                        "--root", str(self.root), "workspace", "migrate",
                        "--agent", "claude,codex",
                    ]
                ),
            )
        self.assertIn("singleton", errors.getvalue())

        for repeated in (
            ["--agents", "claude", "--agents", "codex"],
            ["--agent", "claude", "--agent", "codex"],
        ):
            errors = io.StringIO()
            with self.subTest(repeated=repeated), redirect_stderr(errors):
                self.assertEqual(
                    2,
                    cli_main(
                        ["--root", str(self.root), "workspace", "migrate", *repeated]
                    ),
                )
            self.assertIn("only once", errors.getvalue())

        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli_main(
                [
                    "--root", str(self.root), "workspace", "migrate",
                    "--agent", "claude", "--agents", "codex",
                ]
            )

        errors = io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(
                2,
                cli_main(
                    [
                        "--root", str(self.root), "workspace", "migrate",
                        "--agents", "auto",
                    ]
                ),
            )
        self.assertIn("local launch behavior", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
