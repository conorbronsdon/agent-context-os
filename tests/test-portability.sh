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
  python3 tests/validate-openai-metadata.py "$metadata_file" "$skill" || fail "$metadata_file failed schema validation"
  grep -Fq ".agents/skills/$skill/SKILL.md" "$command_file" || fail "$command_file does not route to $skill"
  python3 tests/validate-openai-metadata.py --command "$command_file" "$command" || fail "$command_file failed frontmatter validation"

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

grep -Fq 'trusted repository-scoped' docs/codex-onboarding.md || fail "Codex guide must describe supported project configuration accurately"

portability_tmp=$(mktemp -d)
trap 'rm -rf "$portability_tmp"' EXIT
invalid_metadata="$portability_tmp/invalid-openai.yaml"
cp .agents/skills/context-start/agents/openai.yaml "$invalid_metadata"
printf 'malformed: [\n' >> "$invalid_metadata"
if python3 tests/validate-openai-metadata.py "$invalid_metadata" context-start >/dev/null 2>&1; then
  fail "malformed openai.yaml metadata passed validation"
fi

invalid_policy="$portability_tmp/string-policy-openai.yaml"
sed 's/allow_implicit_invocation: false/allow_implicit_invocation: "false"/' \
  .agents/skills/context-start/agents/openai.yaml > "$invalid_policy"
if python3 tests/validate-openai-metadata.py "$invalid_policy" context-start >/dev/null 2>&1; then
  fail "string-valued invocation policy passed validation"
fi

invalid_prompt="$portability_tmp/prefixed-skill-openai.yaml"
sed 's/\$context-start /\$context-started /' \
  .agents/skills/context-start/agents/openai.yaml > "$invalid_prompt"
if python3 tests/validate-openai-metadata.py "$invalid_prompt" context-start >/dev/null 2>&1; then
  fail "prefixed skill token passed metadata validation"
fi

control_prompt="$portability_tmp/control-prompt-openai.yaml"
sed 's/brief me/brief\\u000a me/' \
  .agents/skills/context-start/agents/openai.yaml > "$control_prompt"
if python3 tests/validate-openai-metadata.py "$control_prompt" context-start >/dev/null 2>&1; then
  fail "escaped control character passed metadata validation"
fi

body_only_command="$portability_tmp/body-only-start.md"
sed '/^disable-model-invocation: true$/d' .claude/commands/start.md > "$body_only_command"
printf '\ndisable-model-invocation: true\n' >> "$body_only_command"
if python3 tests/validate-openai-metadata.py --command "$body_only_command" start >/dev/null 2>&1; then
  fail "body-only invocation gate passed command validation"
fi

unrestricted_start="$portability_tmp/unrestricted-start.md"
sed 's/^allowed-tools:.*/allowed-tools: [Read, Bash]/' .claude/commands/start.md > "$unrestricted_start"
if python3 tests/validate-openai-metadata.py --command "$unrestricted_start" start >/dev/null 2>&1; then
  fail "unrestricted inline Bash grant passed command validation"
fi

for bad_scalar in false null 123; do
  typed_command="$portability_tmp/non-string-description-$bad_scalar.md"
  sed "s/^description:.*/description: $bad_scalar/" .claude/commands/setup.md > "$typed_command"
  if python3 tests/validate-openai-metadata.py --command "$typed_command" setup >/dev/null 2>&1; then
    fail "$bad_scalar command description passed scalar-type validation"
  fi
done

boolean_tools="$portability_tmp/boolean-tools-start.md"
sed 's/^allowed-tools:.*/allowed-tools: false/' .claude/commands/start.md > "$boolean_tools"
if python3 tests/validate-openai-metadata.py --command "$boolean_tools" start >/dev/null 2>&1; then
  fail "boolean allowed-tools passed scalar-type validation"
fi

help_output=$(bash scripts/setup.sh --help)
grep -Fq -- '--agent auto|claude|codex|none' <<<"$help_output" || fail "setup help does not describe agent selection"
if bash scripts/setup.sh --agent invalid >/dev/null 2>&1; then
  fail "setup accepted an invalid agent"
fi

make_setup_fixture() {
  local destination="$1"
  mkdir -p "$destination"
  tar --exclude='.git' -cf - . | tar -xf - -C "$destination"
  git -C "$destination" init -q
  git -C "$destination" config user.name "Portability Test"
  git -C "$destination" config user.email "portability@example.invalid"
  git -C "$destination" add -A
  git -C "$destination" commit -qm baseline
  git -C "$destination" remote add origin https://example.invalid/context.git
}

setup_fixture="$portability_tmp/repo with spaces"
make_setup_fixture "$setup_fixture"
printf 'unrelated\n' > "$setup_fixture/unrelated-user-work.txt"
special_name='Ada & Bob/Team\Ops|One'
setup_output=$(printf '%s\n' "$special_name" n n n n | (cd "$setup_fixture" && bash scripts/setup.sh --agent none))

grep -Fqx "# $special_name — Context" "$setup_fixture/CLAUDE.md" || fail "setup did not preserve a literal special-character name"
test "$(git -C "$setup_fixture" rev-list --count HEAD)" -eq 1 || fail "setup committed despite the default-no commit prompt"
setup_git_dir=$(git -C "$setup_fixture" rev-parse --absolute-git-dir)
test ! -e "$setup_git_dir/hooks/pre-commit" || fail "setup installed a hook without approval"
git -C "$setup_fixture" diff --summary | grep -Fq 'mode change' && fail "setup changed tracked script modes"
git -C "$setup_fixture" status --short | grep -Fq '?? unrelated-user-work.txt' || fail "setup altered unrelated user work"
printf -v quoted_fixture '%q' "$setup_fixture"
grep -Fq "cd $quoted_fixture && codex" <<<"$setup_output" || fail "setup did not shell-quote a spaced launch path"

before_second_run=$(git -C "$setup_fixture" status --porcelain=v1 && git -C "$setup_fixture" diff --binary)
printf 'Carol\nn\nn\nn\n' | (cd "$setup_fixture" && bash scripts/setup.sh --agent none) >/dev/null
after_second_run=$(git -C "$setup_fixture" status --porcelain=v1 && git -C "$setup_fixture" diff --binary)
test "$before_second_run" = "$after_second_run" || fail "a second setup run changed the reviewed write set"
grep -Fqx "# $special_name — Context" "$setup_fixture/CLAUDE.md" || fail "a second name corrupted an already initialized header"

commit_fixture="$portability_tmp/commit-scope"
make_setup_fixture "$commit_fixture"
printf 'unrelated\n' > "$commit_fixture/unrelated-user-work.txt"
printf 'Ada & Bob\nn\nn\nn\ny\n' | (cd "$commit_fixture" && bash scripts/setup.sh --agent none) >/dev/null
test "$(git -C "$commit_fixture" rev-list --count HEAD)" -eq 2 || fail "approved setup commit was not created"
test "$(git -C "$commit_fixture" show --pretty= --name-only HEAD)" = "CLAUDE.md" || fail "setup commit included a path outside its reviewed write set"
git -C "$commit_fixture" status --short | grep -Fq '?? unrelated-user-work.txt' || fail "setup commit captured unrelated user work"

for skill in context-update context-end; do
  grep -Fq 'current-log.md' ".agents/skills/$skill/SKILL.md" || fail "$skill lacks current.md history handling"
  grep -Fq '**Last Updated:**' ".agents/skills/$skill/SKILL.md" || fail "$skill lacks current.md timestamp handling"
  grep -Fq 'old_date != today && old_date != newest_history_date' ".agents/skills/$skill/SKILL.md" || fail "$skill lacks the same-day history invariant"
done

echo "Portability checks passed"
