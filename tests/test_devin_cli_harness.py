from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODULE_PATH = ROOT / "adapters/devin/cli_conformance.py"
SPEC = importlib.util.spec_from_file_location("contextos_devin_cli", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
cli = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cli
SPEC.loader.exec_module(cli)

VERSION = "3000.11.3"
NL = chr(10)


def atif(steps: list[dict], *, version: str = VERSION, mode: str = "Normal") -> dict:
    """Return an ATIF document shaped like Devin CLI 3000.11.3 --export output."""
    numbered = [{"step_id": index + 1, **step} for index, step in enumerate(steps)]
    return {
        "schema_version": "ATIF-v1.7",
        "session_id": "synthetic",
        "agent": {"name": "devin", "version": version, "model_name": "SWE-2 High",
                  "tool_definitions": [], "extra": {"permission_mode": mode}},
        "steps": numbered,
    }


def rules(*bodies: tuple[str, str]) -> dict:
    inner = "".join(f'<rule name="{name}" path="/x/{name}.md">\n{body}\n</rule>\n' for name, body in bodies)
    return {"source": "system", "message": f'<rules type="always-on">\n{inner}</rules>'}


SKILLS = {"source": "system", "message": "<available_skills>\n- **devin-cli**: docs\n</available_skills>"}


def agent(message: str = "", calls: list[tuple[str, str, dict, str]] | None = None) -> dict:
    step: dict = {"source": "agent", "message": message, "model_name": "swe-2-high"}
    if calls:
        step["tool_calls"] = [{"tool_call_id": cid, "function_name": name, "arguments": args}
                              for cid, name, args, _ in calls]
        step["observation"] = {"results": [{"source_call_id": cid, "content": content}
                                           for cid, _, _, content in calls]}
    return step


class TrajectoryTest(unittest.TestCase):
    def test_reads_context_skills_tools_and_final_message(self) -> None:
        document = atif([
            {"source": "system", "message": "You are Devin"},
            rules(("AGENTS", "ROOT=abc")),
            {"source": "user", "message": "question"},
            SKILLS,
            agent("", [("c1", "write", {"file_path": "x.txt"}, cli.REJECTED_BY_MODE)]),
            agent("abc"),
        ])
        trajectory = cli.Trajectory(document, VERSION)
        self.assertIn("ROOT=abc", trajectory.system_block("<rules"))
        self.assertIn("devin-cli", trajectory.system_block("<available_skills>"))
        self.assertEqual("abc", trajectory.final_message())
        self.assertEqual(["swe-2-high"], trajectory.models)
        self.assertEqual("Normal", trajectory.permission_mode)
        [call] = trajectory.tool_calls()
        self.assertEqual(("write", (cli.REJECTED_BY_MODE,)), (call.name, call.observations))
        self.assertNotIn("abc\n", trajectory.context.split("ROOT=")[0])

    def test_rejects_foreign_agent_version_and_malformed_steps(self) -> None:
        good = atif([rules(("AGENTS", "x")), agent("ok")])
        for mutate, message in (
            (lambda d: d["agent"].update(name="other"), "not produced by Devin"),
            (lambda d: d["agent"].update(version="1.0"), "version differs"),
            (lambda d: d.update(schema_version="ATIF-v2.0"), "unsupported schema"),
            (lambda d: d["steps"][1].update(step_id=9), "not contiguous"),
            (lambda d: d["steps"][1].update(source="tool"), "malformed step"),
        ):
            document = json.loads(json.dumps(good))
            mutate(document)
            with self.subTest(message=message), self.assertRaisesRegex(cli.HarnessError, message):
                cli.Trajectory(document, VERSION)

    def test_tool_observation_must_reference_a_known_call(self) -> None:
        step = agent("", [("c1", "exec", {"command": "ls"}, "ok")])
        step["observation"]["results"][0]["source_call_id"] = "other"
        trajectory = cli.Trajectory(atif([rules(("AGENTS", "x")), step]), VERSION)
        with self.assertRaisesRegex(cli.HarnessError, "unknown tool call"):
            trajectory.tool_calls()

    def test_repeated_call_identifier_is_rejected(self) -> None:
        trajectory = cli.Trajectory(atif([
            rules(("AGENTS", "x")),
            agent("", [("c1", "read", {"file_path": "a"}, "ok")]),
            agent("", [("c1", "read", {"file_path": "b"}, "ok")]),
        ]), VERSION)
        with self.assertRaisesRegex(cli.HarnessError, "repeats"):
            trajectory.tool_calls()

    def test_system_block_must_be_unique(self) -> None:
        trajectory = cli.Trajectory(atif([rules(("AGENTS", "x")), rules(("AGENTS", "y")), agent("ok")]), VERSION)
        with self.assertRaisesRegex(cli.HarnessError, "exactly one"):
            trajectory.system_block("<rules")


class ControlCheckTest(unittest.TestCase):
    def test_absence_checks_injected_context_not_model_file_reads(self) -> None:
        trajectory = cli.Trajectory(atif([
            rules(("AGENTS", "root")),
            {"source": "user", "message": "go"},
            agent("", [("c1", "read", {"file_path": "CLAUDE.md"}, "FOREIGN_CANARY")]),
            agent("done"),
        ]), VERSION)
        cli.require_absent(trajectory, ["FOREIGN_CANARY"], "control")
        self.assertTrue(cli.tool_read(trajectory, "CLAUDE.md"))
        injected = cli.Trajectory(atif([rules(("CLAUDE", "FOREIGN_CANARY")), agent("x")]), VERSION)
        with self.assertRaisesRegex(cli.HarnessError, "must stay out of context"):
            cli.require_absent(injected, ["FOREIGN_CANARY"], "control")

    def test_rejected_attempt_requires_an_attempt_and_the_expected_reason(self) -> None:
        def make(content: str | None) -> cli.Trajectory:
            calls = [("c1", "write", {"file_path": "/w/protected.txt"}, content)] if content else None
            return cli.Trajectory(atif([rules(("AGENTS", "x")), agent("", calls), agent("done")]), VERSION)

        cli.require_rejected_attempt(make(cli.REJECTED_BY_MODE), "write", cli.REJECTED_BY_MODE,
                                     "control", argument="protected.txt")
        with self.assertRaisesRegex(cli.HarnessError, "did not attempt"):
            cli.require_rejected_attempt(make(None), "write", cli.REJECTED_BY_MODE, "control")
        with self.assertRaisesRegex(cli.HarnessError, "expected control"):
            cli.require_rejected_attempt(make("File created successfully"), "write",
                                         cli.REJECTED_BY_MODE, "control")

    def test_deny_reason_matches_project_and_project_local_settings(self) -> None:
        for content in (
            "Write access to '/w/p.txt' was denied by a deny rule in the project settings.",
            "Write access to '/w/p.txt' was denied by a deny rule in the project-local settings override.",
            "Permission denied for this tool by a deny rule in the project settings.",
        ):
            with self.subTest(content=content):
                self.assertIn(cli.REJECTED_BY_DENY, content)

    def test_canary_reply_tolerates_only_code_formatting(self) -> None:
        def reply(text: str) -> cli.Trajectory:
            return cli.Trajectory(atif([rules(("AGENTS", "x")), agent(text)]), VERSION)

        cli.require_canary_only(reply("`ABC`"), "ABC", "control")
        with self.assertRaisesRegex(cli.HarnessError, "only its canary"):
            cli.require_canary_only(reply("The value is ABC"), "ABC", "control")


class FixtureAndIsolationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_guarded_fixture_carries_exact_shipped_config_bytes(self) -> None:
        canaries = {name: name.upper() for name in ("root", "repo_claude", "user_claude", "foreign_skill", "skill")}
        workspace, home = self.root / "w", self.root / "h"
        cli.write_fixture(workspace, home, canaries, guarded=True)
        self.assertEqual(cli.SHIPPED_PROJECT_CONFIG.read_bytes(),
                         (workspace / ".devin/config.json").read_bytes())
        self.assertIn("USER_CLAUDE", (home / ".claude/CLAUDE.md").read_text(encoding="utf-8"))
        skill = (workspace / ".agents/skills" / cli.CONTROL_SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('triggers: ["user"]', skill)
        unguarded = self.root / "u"
        cli.write_fixture(unguarded, home, canaries, guarded=False)
        self.assertFalse((unguarded / ".devin").exists())

    def test_local_permissions_never_touch_shipped_config(self) -> None:
        canaries = {name: name for name in ("root", "repo_claude", "user_claude", "foreign_skill", "skill")}
        workspace = self.root / "w"
        cli.write_fixture(workspace, self.root / "h", canaries, guarded=True)
        cli.write_local_permissions(workspace, {"deny": ["exec"]})
        self.assertEqual(cli.SHIPPED_PROJECT_CONFIG.read_bytes(),
                         (workspace / ".devin/config.json").read_bytes())
        self.assertEqual({"permissions": {"deny": ["exec"]}},
                         json.loads((workspace / ".devin/config.local.json").read_text(encoding="utf-8")))

    @unittest.skipIf(os.name == "nt", "isolation runs only on POSIX hosts")
    def test_isolated_environment_replaces_home_and_config_but_pins_data_home(self) -> None:
        data = self.root / "data"
        (data / "devin").mkdir(parents=True)
        (data / "devin/credentials.toml").write_text("synthetic = true\n", encoding="utf-8")
        binary = self.root / "devin"
        binary.write_text("fixture", encoding="utf-8")
        with mock.patch.dict(os.environ, {"DEVIN_PERMISSION_MODE": "dangerous", "XDG_CONFIG_HOME": "/real"}):
            harness = cli.DevinCliHarness(binary, VERSION, "0" * 40, data)
            with harness.isolated() as base:
                env = harness.env
                self.assertEqual(str(base / "home"), env["HOME"])
                self.assertEqual(str(base / "config"), env["XDG_CONFIG_HOME"])
                self.assertEqual(str(data), env["XDG_DATA_HOME"])
                self.assertNotIn("DEVIN_PERMISSION_MODE", env)
                self.assertEqual("{}\n", (base / "config/devin/config.json").read_text(encoding="utf-8"))
            self.assertFalse(base.exists())
            self.assertEqual("removed", harness.evidence.workspace_cleanup)

    def test_native_windows_is_refused(self) -> None:
        with mock.patch.object(cli.os, "name", "nt"):
            with self.assertRaisesRegex(cli.HarnessError, "native Windows"):
                cli.DevinCliHarness(self.root, VERSION, "0" * 40, self.root)

    @unittest.skipIf(os.name == "nt", "isolation runs only on POSIX hosts")
    def test_missing_credentials_fail_before_any_model_call(self) -> None:
        binary = self.root / "devin"
        binary.write_text("fixture", encoding="utf-8")
        (self.root / "data").mkdir()
        with self.assertRaisesRegex(cli.HarnessError, "credentials are missing"):
            cli.DevinCliHarness(binary, VERSION, "0" * 40, self.root / "data")

    def test_evidence_must_stay_outside_source(self) -> None:
        with self.assertRaisesRegex(cli.HarnessError, "outside the source repository"):
            cli.require_outside_source(ROOT / "evidence.json")


class ShippedConfigTest(unittest.TestCase):
    def test_project_config_only_disables_foreign_imports(self) -> None:
        document = json.loads(cli.SHIPPED_PROJECT_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual({"read_config_from": {name: False for name in cli.FOREIGN_IMPORTS}}, document)
        self.assertNotIn("agents_standard", document["read_config_from"])

    def test_shipped_config_is_owned_by_the_devin_component(self) -> None:
        manifest = json.loads((ROOT / "components/manifest.json").read_text(encoding="utf-8"))
        owners = [component["id"] for component in manifest["components"]
                  for entry in component["paths"] if entry["path"] == ".devin/config.json"]
        self.assertEqual(["devin-adapter"], owners)



LIFECYCLE_PATH = ROOT / "adapters/devin/cli_lifecycle_conformance.py"
LIFECYCLE_SPEC = importlib.util.spec_from_file_location("contextos_devin_cli_lifecycle", LIFECYCLE_PATH)
assert LIFECYCLE_SPEC is not None and LIFECYCLE_SPEC.loader is not None
lifecycle = importlib.util.module_from_spec(LIFECYCLE_SPEC)
sys.modules[LIFECYCLE_SPEC.name] = lifecycle
LIFECYCLE_SPEC.loader.exec_module(lifecycle)


class LifecycleControlTest(unittest.TestCase):
    def call(self, command: str):
        return cli.ToolCall("c1", "exec", {"command": command}, ())

    def test_apply_detection_covers_quoting_paths_chaining_and_module_forms(self) -> None:
        for command in (
            'bash scripts/contextos.sh "apply" p.json --confirm x',
            "cd /w && bash /w/scripts/contextos.sh apply p.json --confirm x",
            "python3 -m contextos apply p.json --confirm x",
            "true; sh scripts/contextos.sh 'apply' p.json",
        ):
            with self.subTest(command=command):
                self.assertTrue(lifecycle.is_kernel_command(self.call(command), "apply"))
        self.assertFalse(lifecycle.is_kernel_command(self.call(
            "bash scripts/contextos.sh propose update --input .context-os/inputs/apply-notes.json"), "apply"))
        # Over-matching is deliberate: a flagged call must show a deny, so the
        # harness fails closed rather than missing an unusual spelling.
        self.assertTrue(lifecycle.is_kernel_command(
            self.call("bash scripts/contextos.sh start; echo apply"), "apply"))
        self.assertFalse(lifecycle.is_kernel_command(
            cli.ToolCall("c1", "read", {"command": "contextos apply"}, ()), "apply"))

    def test_skill_expansion_requires_the_shipped_skill_body_in_a_user_turn(self) -> None:
        body = lifecycle.skill_body(ROOT, "start")
        self.assertTrue(body.startswith("# Start a workspace session"))
        expanded = cli.Trajectory(atif([rules(("AGENTS", "x")), {"source": "user", "message": body},
                                        agent("done")]), VERSION)
        lifecycle.require_skill_expanded(expanded, ROOT, "start")
        bare = cli.Trajectory(atif([rules(("AGENTS", "x")),
                                    {"source": "user", "message": "/context-start please"}, agent("ok")]), VERSION)
        with self.assertRaisesRegex(lifecycle.HarnessError, "did not expand"):
            lifecycle.require_skill_expanded(bare, ROOT, "start")

    def test_end_fact_must_be_saved_as_the_next_action(self) -> None:
        def doc(path: str, *lines: str) -> dict:
            return {"changes": [{"path": path, "after_text": NL.join(lines)}]}

        lifecycle.require_next_action(
            doc("sessions/d.md", "## What happened", "- x", "", "## Next time", "- FACT", ""), "FACT")
        for wrong in (
            doc("sessions/d.md", "## What happened", "- FACT", "", "## Next time", "- None recorded"),
            doc("sessions/d.md", "## Next time", "- y", "", "## Notes", "- FACT"),
            doc("state/current.md", "## Next time", "- FACT"),
        ):
            with self.subTest(wrong=wrong), self.assertRaisesRegex(lifecycle.HarnessError, "next action"):
                lifecycle.require_next_action(wrong, "FACT")

    def test_start_inventory_requires_the_wrapper_success_and_inventory_json(self) -> None:
        good = NL.join(["Output from command in shell a:",
                        json.dumps({"schema_version": 1, "initialized": True}), "", "", "Exit code: 0"])
        self.assertTrue(lifecycle.ran_kernel_inventory(
            cli.ToolCall("c", "exec", {"command": "bash scripts/contextos.sh start"}, (good,))))
        for command, observation in (
            ("grep 'schema_version' contextos/kernel.py # start", good),
            ("bash scripts/contextos.sh doctor", good),
            ("bash scripts/contextos.sh start", good.replace("Exit code: 0", "Exit code: 1")),
            ("bash scripts/contextos.sh start",
             NL.join(["Output:", json.dumps({"schema_version": 1}), "Exit code: 0"])),
        ):
            with self.subTest(command=command, observation=observation):
                self.assertFalse(lifecycle.ran_kernel_inventory(
                    cli.ToolCall("c", "exec", {"command": command}, (observation,))))

    def test_apply_detection_covers_ansi_quoting_and_nested_shells(self) -> None:
        for command in ("bash scripts/contextos.sh $'apply' p.json",
                        "bash -c 'bash scripts/contextos.sh apply p.json'"):
            with self.subTest(command=command):
                self.assertTrue(lifecycle.is_kernel_command(self.call(command), "apply"))
        self.assertFalse(lifecycle.is_kernel_command(
            self.call("bash scripts/contextos.sh propose end --input apply-notes.json"), "apply"))

    def test_read_only_phases_deny_writes_and_proposals_but_keep_apply_denied_everywhere(self) -> None:
        root = Path("/w")
        mutation = lifecycle.lifecycle_permissions(root)
        read_only = lifecycle.lifecycle_permissions(root, read_only=True)
        self.assertIn("Write(.context-os/inputs/**)", mutation["allow"])
        self.assertNotIn("Write(.context-os/inputs/**)", read_only["allow"])
        for permissions in (mutation, read_only):
            self.assertIn("Exec(bash scripts/contextos.sh apply)", permissions["deny"])
            self.assertIn("Exec(bash /w/scripts/contextos.sh apply)", permissions["deny"])
            self.assertIn("Exec(python3)", permissions["deny"])
            for form in ("sh /w/scripts/contextos.sh", "./scripts/contextos.sh", "/w/scripts/contextos.sh"):
                self.assertIn(f"Exec({form} apply)", permissions["deny"])
        self.assertIn("Exec(bash scripts/contextos.sh propose)", read_only["deny"])
        self.assertIn("write", read_only["deny"])
        self.assertNotIn("Exec(bash scripts/contextos.sh propose)", mutation["deny"])

if __name__ == "__main__":
    unittest.main()
