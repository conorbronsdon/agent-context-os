from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from contextos.component_schema import (
    COMPONENT_MANIFEST_SCHEMA_VERSION,
    ComponentManifestError,
    component_closure,
    component_owners,
    resolved_component_paths,
    untracked_owned_paths,
    component_schema_document,
    load_component_manifest,
    unclassified_tracked_paths,
    validate_component_manifest,
    write_generated_file,
)


ROOT = Path(__file__).resolve().parents[1]


def fixture() -> dict:
    return {
        "schema_version": 1,
        "extensible_roots": ["extensions"],
        "components": [
            {
                "id": "feature",
                "description": "Optional feature.",
                "depends_on": ["adapter", "foundation"],
                "paths": [{"path": "feature.txt", "policy": "development"}],
            },
            {
                "id": "foundation",
                "description": "Base contract.",
                "depends_on": [],
                "paths": [{"path": "foundation.txt", "policy": "managed"}],
            },
            {
                "id": "adapter",
                "description": "Host adapter.",
                "depends_on": ["foundation"],
                "paths": [{"path": "adapters/codex.txt", "policy": "seed"}],
            },
        ],
    }


class ComponentManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "adapters").mkdir()
        (self.root / "extensions").mkdir()
        for relative in ("feature.txt", "foundation.txt", "adapters/codex.txt"):
            (self.root / relative).write_text("fixture\n", encoding="utf-8")

    def validate(self, manifest: dict, *, check_paths: bool = True) -> dict:
        return validate_component_manifest(
            manifest, root=self.root, check_paths=check_paths
        )

    def test_valid_contract_and_deterministic_dependency_closure(self) -> None:
        manifest = fixture()
        self.assertIs(manifest, self.validate(manifest))
        self.assertEqual(
            ["foundation", "adapter", "feature"],
            component_closure(manifest, ["feature"]),
        )
        self.assertEqual(
            ["foundation", "adapter", "feature"],
            component_closure(manifest, ["feature", "adapter"]),
        )

    def test_repository_manifest_validates(self) -> None:
        path = ROOT / "components/manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        validated = validate_component_manifest(manifest, root=ROOT)
        self.assertEqual(COMPONENT_MANIFEST_SCHEMA_VERSION, validated["schema_version"])

    def test_checked_in_schema_matches_authoritative_contract(self) -> None:
        path = ROOT / "components/schema.json"
        self.assertEqual(
            component_schema_document(),
            json.loads(path.read_text(encoding="utf-8")),
        )

    def test_exact_keys_are_enforced_at_every_level(self) -> None:
        mutations = []
        top = fixture()
        top["surprise"] = True
        mutations.append((top, "unknown surprise"))
        component = fixture()
        component["components"][0]["surprise"] = True
        mutations.append((component, "unknown surprise"))
        path = fixture()
        path["components"][0]["paths"][0]["surprise"] = True
        mutations.append((path, "unknown surprise"))
        missing = fixture()
        del missing["components"][0]["description"]
        mutations.append((missing, "missing description"))
        for manifest, message in mutations:
            with self.subTest(message=message), self.assertRaisesRegex(
                ComponentManifestError, message
            ):
                self.validate(manifest, check_paths=False)

    def test_invalid_json_is_reported_as_a_component_error(self) -> None:
        path = self.root / "manifest.json"
        path.write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(ComponentManifestError, "invalid JSON"):
            load_component_manifest(path, root=self.root, check_paths=False)

    def test_schema_types_arrays_text_and_policies_are_closed(self) -> None:
        mutations = []
        boolean_version = fixture()
        boolean_version["schema_version"] = True
        mutations.append((boolean_version, "integer 1"))
        empty_components = fixture()
        empty_components["components"] = []
        mutations.append((empty_components, "non-empty array"))
        empty_paths = fixture()
        empty_paths["components"][0]["paths"] = []
        mutations.append((empty_paths, "non-empty array"))
        bad_policy = fixture()
        bad_policy["components"][0]["paths"][0]["policy"] = "generated"
        mutations.append((bad_policy, "unsupported value"))
        bad_description = fixture()
        bad_description["components"][0]["description"] = " padded "
        mutations.append((bad_description, "surrounding whitespace"))
        bad_id = fixture()
        bad_id["components"][0]["id"] = "Feature Name"
        mutations.append((bad_id, "lowercase kebab-case"))
        for manifest, message in mutations:
            with self.subTest(message=message), self.assertRaisesRegex(
                ComponentManifestError, message
            ):
                self.validate(manifest, check_paths=False)

    def test_paths_are_safe_canonical_posix_relative_paths(self) -> None:
        unsafe = (
            "../escape.txt", "/absolute.txt", "C:/absolute.txt", "a\\b.txt",
            "a//b.txt", "a/./b.txt", "a/../b.txt", "trailing/", " padded.txt ",
        )
        for value in unsafe:
            manifest = fixture()
            manifest["components"][0]["paths"][0]["path"] = value
            with self.subTest(value=value), self.assertRaises(ComponentManifestError):
                self.validate(manifest, check_paths=False)

    def test_local_ignored_and_user_owned_paths_cannot_be_managed(self) -> None:
        for value in (
            ".context-os/runtime.json", ".git/hooks/pre-commit",
            ".claude/settings.local.json", "REPO_MAP.md", "cache/__pycache__/x",
            "cache/result.pyc", "debug.log", "private.pem", ".VSCODE/settings.json",
            ".Context-OS/runtime.json", ".DS_Store", "secrets/.ENV.production",
            "node_modules/package/index.js", "cache/module.pyd",
        ):
            manifest = fixture()
            manifest["components"][0]["paths"][0]["path"] = value
            with self.subTest(value=value), self.assertRaisesRegex(
                ComponentManifestError, "must not claim"
            ):
                self.validate(manifest, check_paths=False)

        for value in (".Context-OS", "node_modules", ".VSCODE"):
            manifest = fixture()
            manifest["extensible_roots"] = [value]
            with self.subTest(value=value), self.assertRaisesRegex(
                ComponentManifestError, "must not claim"
            ):
                self.validate(manifest, check_paths=False)

        for value in ("folder/name.", "folder/CON", "folder/file:stream"):
            manifest = fixture()
            manifest["components"][0]["paths"][0]["path"] = value
            with self.subTest(value=value), self.assertRaisesRegex(
                ComponentManifestError, "Windows-aliased or illegal"
            ):
                self.validate(manifest, check_paths=False)

        managed_extension = fixture()
        managed_extension["components"][0]["paths"][0] = {
            "path": "extensions/product-owned.md", "policy": "managed"
        }
        self.assertIs(
            managed_extension,
            self.validate(managed_extension, check_paths=False),
        )

    def test_unicode_nfc_casefold_duplicates_and_prefixes_are_rejected(self) -> None:
        path_duplicate = fixture()
        path_duplicate["components"][0]["paths"][0]["path"] = "Readme.md"
        path_duplicate["components"][1]["paths"][0]["path"] = "README.md"
        with self.assertRaisesRegex(ComponentManifestError, "Unicode NFC case-folding"):
            self.validate(path_duplicate, check_paths=False)

        root_duplicate = fixture()
        root_duplicate["extensible_roots"] = ["Extensions", "extensions"]
        with self.assertRaisesRegex(ComponentManifestError, "Unicode NFC case-folding"):
            self.validate(root_duplicate, check_paths=False)

        path_prefix = fixture()
        path_prefix["components"][0]["paths"][0]["path"] = "owned"
        path_prefix["components"][1]["paths"][0]["path"] = "owned/child"
        with self.assertRaisesRegex(ComponentManifestError, "prefix conflict"):
            self.validate(path_prefix, check_paths=False)

        root_prefix = fixture()
        root_prefix["extensible_roots"] = ["extensions", "extensions/nested"]
        with self.assertRaisesRegex(ComponentManifestError, "prefix conflict"):
            self.validate(root_prefix, check_paths=False)

    def test_paths_must_be_existing_regular_non_symlink_files(self) -> None:
        missing = fixture()
        missing["components"][0]["paths"][0]["path"] = "missing.txt"
        with self.assertRaisesRegex(ComponentManifestError, "does not exist"):
            self.validate(missing)

        directory = fixture()
        directory["components"][0]["paths"][0] = {
            "path": "extensions", "policy": "seed"
        }
        with self.assertRaisesRegex(ComponentManifestError, "regular file"):
            self.validate(directory)

        link = self.root / "linked.txt"
        try:
            link.symlink_to(self.root / "feature.txt")
        except OSError:
            pass
        else:
            symlink = fixture()
            symlink["components"][0]["paths"][0]["path"] = "linked.txt"
            with self.assertRaisesRegex(ComponentManifestError, "symlink"):
                self.validate(symlink)

        real_directory = self.root / "real-directory"
        real_directory.mkdir()
        (real_directory / "nested.txt").write_text("fixture\n", encoding="utf-8")
        linked_directory = self.root / "linked-directory"
        try:
            linked_directory.symlink_to(real_directory, target_is_directory=True)
        except OSError:
            pass
        else:
            ancestor = fixture()
            ancestor["components"][0]["paths"][0]["path"] = (
                "linked-directory/nested.txt"
            )
            with self.assertRaisesRegex(ComponentManifestError, "symlink"):
                self.validate(ancestor)

    def test_generated_write_rejects_symlink_leaf_and_ancestor(self) -> None:
        generated = self.root / "generated"
        generated.mkdir()
        outside = self.root / "outside.txt"
        outside.write_text("unchanged\n", encoding="utf-8")
        leaf = generated / "schema.json"
        try:
            leaf.symlink_to(outside)
        except OSError:
            self.skipTest("symlink creation is not available on this platform")
        with self.assertRaisesRegex(ComponentManifestError, "must not be a symlink"):
            write_generated_file(leaf, "changed\n", root=self.root)
        self.assertEqual("unchanged\n", outside.read_text(encoding="utf-8"))

        leaf.unlink()
        generated.rmdir()
        generated.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ComponentManifestError, "traverses a symlink"):
            write_generated_file(
                generated / "replacement.json", "changed\n", root=self.root
            )
        self.assertFalse((self.root / "replacement.json").exists())

    def test_dependency_unknown_self_duplicate_and_cycles_are_rejected(self) -> None:
        unknown = fixture()
        unknown["components"][0]["depends_on"] = ["missing"]
        self_ref = fixture()
        self_ref["components"][0]["depends_on"] = ["FEATURE"]
        duplicate = fixture()
        duplicate["components"][0]["depends_on"] = ["adapter", "ADAPTER"]
        cycle = fixture()
        cycle["components"][1]["depends_on"] = ["feature"]
        for manifest, message in (
            (unknown, "unknown component"),
            (self_ref, "itself"),
            (duplicate, "Unicode NFC case-folding"),
            (cycle, "dependency cycle"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(
                ComponentManifestError, message
            ):
                self.validate(manifest, check_paths=False)

    def test_closure_rejects_unknown_and_duplicate_requests(self) -> None:
        with self.assertRaisesRegex(ComponentManifestError, "unknown components"):
            component_closure(fixture(), ["missing"])
        with self.assertRaisesRegex(ComponentManifestError, "Unicode NFC case-folding"):
            component_closure(fixture(), ["feature", "FEATURE"])

    def test_tracked_coverage_requires_exact_classification_with_extensible_escape(self) -> None:
        manifest = fixture()
        tracked = [
            "feature.txt", "foundation.txt", "adapters/codex.txt",
            "extensions/new-plugin.txt", "unowned.txt",
        ]
        self.assertEqual(
            ["extensions/new-plugin.txt", "unowned.txt"],
            unclassified_tracked_paths(manifest, tracked, root=self.root),
        )
        tracked.remove("unowned.txt")
        self.assertEqual(
            ["extensions/new-plugin.txt"],
            unclassified_tracked_paths(manifest, tracked, root=self.root),
        )
        self.assertEqual(
            [],
            unclassified_tracked_paths(
                manifest, tracked, root=self.root, allow_extensible=True
            ),
        )

    def test_tracked_coverage_rejects_portable_path_collisions(self) -> None:
        with self.assertRaisesRegex(ComponentManifestError, "portable path collision"):
            unclassified_tracked_paths(
                fixture(), ["unowned.txt", "UNOWNED.txt"], root=self.root
            )

    def test_workspace_extensions_reject_secrets_and_sibling_prefixes(self) -> None:
        manifest = fixture()
        with self.assertRaisesRegex(ComponentManifestError, "must not claim"):
            unclassified_tracked_paths(
                manifest,
                ["extensions/.env.local"],
                root=self.root,
                allow_extensible=True,
            )
        self.assertEqual(
            ["extensions-extra/user.md"],
            unclassified_tracked_paths(
                manifest,
                ["extensions-extra/user.md"],
                root=self.root,
                allow_extensible=True,
            ),
        )

    def test_every_owned_path_must_come_from_the_tracked_source_set(self) -> None:
        tracked = ["feature.txt", "foundation.txt", "adapters/codex.txt"]
        self.assertEqual(
            [], untracked_owned_paths(fixture(), tracked, root=self.root)
        )
        tracked.remove("feature.txt")
        self.assertEqual(
            ["feature.txt"],
            untracked_owned_paths(fixture(), tracked, root=self.root),
        )

    def test_repository_component_boundaries_and_static_resolution(self) -> None:
        manifest = json.loads(
            (ROOT / "components/manifest.json").read_text(encoding="utf-8")
        )
        owners = component_owners(manifest)
        policies = {
            path_entry["path"]: path_entry["policy"]
            for component in manifest["components"]
            for path_entry in component["paths"]
        }
        self.assertEqual("agents-instructions", owners["AGENTS.md"])
        self.assertEqual("claude-adapter", owners["CLAUDE.md"])
        self.assertEqual(
            "openai-skill-metadata",
            owners[".agents/skills/start/agents/openai.yaml"],
        )
        self.assertEqual("codex-adapter", owners[".codex/hooks.json"])
        self.assertEqual("hermes-adapter", owners["adapters/hermes/README.md"])
        self.assertEqual("seed", policies["identity/who-i-am.md"])
        self.assertEqual("seed", policies["state/current.md"])

        codex = component_closure(manifest, ["codex-adapter"])
        self.assertEqual(
            [
                "core", "portable-skills", "agents-instructions",
                "openai-skill-metadata", "codex-adapter",
            ],
            codex,
        )
        combined = resolved_component_paths(
            manifest, ["claude-adapter", "codex-adapter"]
        )
        paths = [item["path"] for item in combined]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertIn(".claude/settings.json", paths)
        self.assertIn(".codex/hooks.json", paths)
        self.assertIn(".agents/skills/start/agents/openai.yaml", paths)
        self.assertNotIn("adapters/hermes/README.md", paths)
        self.assertNotIn("tests/test_component_manifests.py", paths)

        tracked_with_workspace_extensions = [
            *owners,
            ".agents/skills/standup/SKILL.md",
            ".claude/commands/standup.md",
            "sessions/2026-08-25.md",
        ]
        self.assertEqual(
            [
                ".agents/skills/standup/SKILL.md",
                ".claude/commands/standup.md",
                "sessions/2026-08-25.md",
            ],
            unclassified_tracked_paths(
                manifest, tracked_with_workspace_extensions, root=ROOT
            ),
        )
        self.assertEqual(
            [],
            unclassified_tracked_paths(
                manifest,
                tracked_with_workspace_extensions,
                root=ROOT,
                allow_extensible=True,
            ),
        )


if __name__ == "__main__":
    unittest.main()
