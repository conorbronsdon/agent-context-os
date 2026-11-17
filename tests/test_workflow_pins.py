"""Supply-chain guard for GitHub Actions. Run: python3 -m unittest discover tests

Every third-party `uses:` in .github/workflows and .github/actions must be pinned
to a full 40-character commit SHA (the tag goes in a trailing comment), every
workflow declares top-level `permissions:`, and Dependabot watches the
github-actions ecosystem so the pins stay current. Stdlib only.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GITHUB = ROOT / ".github"

USES_RE = re.compile(r"""^\s*(?:-\s+)?uses:\s*["']?([^\s"'#]+)""")
FULL_SHA_RE = re.compile(r"@[0-9a-f]{40}$")


def unpinned_uses(yaml_text):
    """Return every `uses:` ref that is not a full-SHA pin, local action or docker image."""
    bad = []
    for line in yaml_text.replace("\r\n", "\n").split("\n"):
        m = USES_RE.match(line)
        if not m:
            continue
        ref = m.group(1)
        if ref.startswith("./") or ref.startswith("docker://"):
            continue
        if not FULL_SHA_RE.search(ref):
            bad.append(ref)
    return bad


def workflow_files():
    files = []
    for sub in ("workflows", "actions"):
        d = GITHUB / sub
        if d.is_dir():
            files += sorted(p for p in d.rglob("*") if p.suffix in (".yml", ".yaml"))
    return files


class ParserControls(unittest.TestCase):
    def test_flags_tag_short_sha_and_branch(self):
        text = (
            "      - uses: actions/checkout@v4\n"
            "      - uses: actions/setup-node@49933ea\n"
            "        uses: 'owner/action@main'\n"
        )
        self.assertEqual(
            unpinned_uses(text),
            ["actions/checkout@v4", "actions/setup-node@49933ea", "owner/action@main"],
        )

    def test_accepts_full_sha_local_and_docker(self):
        text = (
            "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0\n"
            "        uses: ./\n"
            "        uses: ./.github/actions/setup\n"
            "        uses: docker://alpine:3.20\n"
            "      # uses: actions/checkout@v4 (a comment, not a step)\n"
        )
        self.assertEqual(unpinned_uses(text), [])


class RepositoryWorkflows(unittest.TestCase):
    def test_workflows_exist(self):
        self.assertTrue(workflow_files(), "no workflow files found under .github/")

    def test_every_uses_is_sha_pinned(self):
        bad = {}
        for p in workflow_files():
            refs = unpinned_uses(p.read_text(encoding="utf-8"))
            if refs:
                bad[str(p.relative_to(ROOT))] = refs
        self.assertEqual(bad, {}, "pin these to a full commit SHA with a version comment")

    def test_every_workflow_sets_top_level_permissions(self):
        missing = [
            str(p.relative_to(ROOT))
            for p in sorted((GITHUB / "workflows").glob("*.y*ml"))
            if not re.search(r"^permissions:", p.read_text(encoding="utf-8"), re.M)
        ]
        self.assertEqual(missing, [])

    def test_dependabot_watches_github_actions(self):
        path = GITHUB / "dependabot.yml"
        self.assertTrue(path.is_file(), ".github/dependabot.yml is missing")
        text = path.read_text(encoding="utf-8")
        self.assertRegex(text, r"package-ecosystem:\s*[\"']?github-actions[\"']?")


if __name__ == "__main__":
    unittest.main()
