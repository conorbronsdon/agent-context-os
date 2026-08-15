#!/usr/bin/env bash
# Validate the provider-neutral lifecycle core and its host adapters.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

fail() {
  echo "portability: $*" >&2
  exit 1
}

test -f AGENTS.md || fail "missing root AGENTS.md"
test -f docs/codex-onboarding.md || fail "missing Codex onboarding guide"

skills=(context-setup context-start context-update context-end)
commands=(setup start update end)

for index in "${!skills[@]}"; do
  skill="${skills[$index]}"
  command="${commands[$index]}"
  skill_file=".agents/skills/$skill/SKILL.md"
  metadata_file=".agents/skills/$skill/agents/openai.yaml"
  command_file=".claude/commands/$command.md"

  test -f "$skill_file" || fail "missing $skill_file"
  test -f "$metadata_file" || fail "missing $metadata_file"
  test -f "$command_file" || fail "missing $command_file"

  grep -qx "name: $skill" "$skill_file" || fail "$skill_file name does not match its directory"
  grep -Fq "\$${skill}" "$metadata_file" || fail "$metadata_file default prompt must name \$$skill"
  grep -Eq '^  allow_implicit_invocation: false$' "$metadata_file" || fail "$metadata_file must disable implicit invocation"
  grep -Fq ".agents/skills/$skill/SKILL.md" "$command_file" || fail "$command_file does not route to $skill"

  lines=$(wc -l < "$skill_file")
  [ "$lines" -le 180 ] || fail "$skill_file is too long to remain a focused workflow core"

  if grep -Eiq '(mcp__|allowed-tools|~/.claude|\.claude/|claude code|codex|gemini)' "$skill_file"; then
    fail "$skill_file contains a provider-specific adapter detail"
  fi
done

for command in "${commands[@]}"; do
  lines=$(wc -l < ".claude/commands/$command.md")
  [ "$lines" -le 40 ] || fail ".claude/commands/$command.md is no longer a thin adapter"
done

for skill in "${skills[@]}"; do
  grep -Fq "\$$skill" AGENTS.md || fail "AGENTS.md does not route to \$$skill"
done

[ "$(wc -l < AGENTS.md)" -le 100 ] || fail "AGENTS.md should stay under 100 lines"
grep -Fq 'hooks and settings' docs/codex-onboarding.md || fail "Codex guide must disclose host-only hooks and settings"
grep -Fq 'auto-memory' docs/codex-onboarding.md || fail "Codex guide must disclose the auto-memory boundary"
grep -Fq '/import' docs/codex-onboarding.md || fail "Codex guide must explain optional import"

if git ls-files --error-unmatch '.codex/config.toml' >/dev/null 2>&1; then
  fail "personal .codex/config.toml must not be committed"
fi

help_output=$(bash scripts/setup.sh --help)
grep -Fq -- '--agent auto|claude|codex|none' <<<"$help_output" || fail "setup help does not describe agent selection"
if bash scripts/setup.sh --agent invalid >/dev/null 2>&1; then
  fail "setup accepted an invalid agent"
fi

echo "Portability checks passed"
