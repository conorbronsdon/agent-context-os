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
test -f state/current-log.md || fail "missing current.md history seed"

skills=(context-setup context-start context-update context-end)
commands=(setup start update end)
aliases=(setup start update end)

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

for index in "${!aliases[@]}"; do
  alias_name="${aliases[$index]}"
  core_name="${skills[$index]}"
  alias_file=".agents/skills/$alias_name/SKILL.md"
  metadata_file=".agents/skills/$alias_name/agents/openai.yaml"

  test -f "$alias_file" || fail "missing $alias_file"
  test -f "$metadata_file" || fail "missing $metadata_file"
  grep -qx "name: $alias_name" "$alias_file" || fail "$alias_file name does not match its directory"
  grep -Fq "../$core_name/SKILL.md" "$alias_file" || fail "$alias_file does not route to $core_name"
  python3 tests/validate-openai-metadata.py "$metadata_file" "$alias_name" || fail "$metadata_file failed schema validation"
  [ "$(wc -l < "$alias_file")" -le 15 ] || fail "$alias_file is no longer a thin alias"
done

for command in "${commands[@]}"; do
  lines=$(wc -l < ".claude/commands/$command.md")
  [ "$lines" -le 40 ] || fail ".claude/commands/$command.md is no longer a thin adapter"
done

side_effecting_commands=(
  capture content-shipped dream dream-apply migrate-gemini mine-gemini-workflows
  reconcile recover setup today update end
)
for command in "${side_effecting_commands[@]}"; do
  python3 tests/validate-openai-metadata.py --command ".claude/commands/$command.md" "$command" \
    || fail ".claude/commands/$command.md failed strict side-effecting frontmatter validation"
done

grep -qx 'allowed-tools: "Read"' .claude/commands/clean-ai-writing.md \
  || fail "clean-ai-writing must remain read-only when it is model-invocable"
grep -qx 'allowed-tools: "Read, Glob, Grep"' .claude/commands/find-context.md \
  || fail "find-context must not pre-approve Bash when it is model-invocable"

for skill in "${skills[@]}"; do
  grep -Fq "\$$skill" AGENTS.md || fail "AGENTS.md does not route to \$$skill"
done

for alias_name in "${aliases[@]}"; do
  grep -Fq "\$$alias_name" AGENTS.md || fail "AGENTS.md does not route to \$$alias_name"
done

while IFS= read -r portable_skill; do
  frontmatter=$(awk '
    NR == 1 && $0 == "---" { inside = 1; next }
    inside && $0 == "---" { exit }
    inside { print }
  ' "$portable_skill")
  if grep -Eq '^(requires|allowed-tools):' <<<"$frontmatter"; then
    fail "$portable_skill puts nonstandard dependencies or host permissions in portable frontmatter"
  fi
done < <(find .agents/skills projects/example-musician/workflow-examples -name SKILL.md -type f | sort)

test ! -d projects/example-musician/skills || fail "example project still presents a nested skills directory as discoverable"

[ "$(wc -l < AGENTS.md)" -le 100 ] || fail "AGENTS.md should stay under 100 lines"
grep -Fq 'hooks and settings' docs/codex-onboarding.md || fail "Codex guide must disclose host-only hooks and settings"
grep -Fq 'auto-memory' docs/codex-onboarding.md || fail "Codex guide must disclose the auto-memory boundary"
grep -Fq '/import' docs/codex-onboarding.md || fail "Codex guide must explain optional import"

grep -Fq 'trusted repository-scoped' docs/codex-onboarding.md || fail "Codex guide must describe supported project configuration accurately"

setup_skill=.agents/skills/context-setup/SKILL.md
storage_line=$(grep -n 'Confirm storage and audience before collecting context' "$setup_skill" | cut -d: -f1)
source_line=$(grep -n 'Choose the starting point' "$setup_skill" | cut -d: -f1)
test -n "$storage_line" && test -n "$source_line" && test "$storage_line" -lt "$source_line" \
  || fail "portable setup does not confirm storage before reading or collecting context"
grep -Fq 'does not erase them from git history' "$setup_skill" \
  || fail "portable setup omits git-history retention disclosure"
grep -Fq 'explicitly confirm' "$setup_skill" \
  || fail "portable setup does not require audience confirmation"
grep -Fq 'auto-memory is enabled by default' .claude/commands/setup.md \
  || fail "Claude setup adapter omits the host auto-memory default"
grep -Fq '/memory' .claude/commands/setup.md \
  || fail "Claude setup adapter omits memory inspection"
grep -Fq 'autoMemoryEnabled: false' .claude/commands/setup.md \
  || fail "Claude setup adapter omits the auto-memory opt-out"

portability_tmp=$(mktemp -d)
# Native git on Windows cannot cd to MSYS-style /tmp paths; resolve to a
# native path when cygpath is available. No-op on Linux.
if command -v cygpath >/dev/null 2>&1; then
  portability_tmp=$(cygpath -m "$portability_tmp")
fi
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

wildcard_start="$portability_tmp/wildcard-start.md"
sed 's/^allowed-tools:.*/allowed-tools: "Read, Glob, Bash(gws drive files list:*)"/' .claude/commands/start.md > "$wildcard_start"
if python3 tests/validate-openai-metadata.py --command "$wildcard_start" start >/dev/null 2>&1; then
  fail "gws trailing-wildcard pre-approval passed command validation"
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

duplicate_gate="$portability_tmp/duplicate-gate-dream.md"
sed '/^disable-model-invocation: true$/a disable-model-invocation: false' \
  .claude/commands/dream.md > "$duplicate_gate"
if python3 tests/validate-openai-metadata.py --command "$duplicate_gate" dream >/dev/null 2>&1; then
  fail "duplicate false invocation gate passed command validation"
fi

help_output=$(bash scripts/setup.sh --help)
grep -Fq -- '--agent auto|claude|codex|hermes|cursor|openclaw|none' <<<"$help_output" || fail "setup help does not describe agent selection"
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
setup_output=$(printf '%s\n' y "$special_name" n n n n | (cd "$setup_fixture" && bash scripts/setup.sh --agent none))

grep -Fqx "# $special_name — Context" "$setup_fixture/CLAUDE.md" || fail "setup did not preserve a literal special-character name"
test "$(git -C "$setup_fixture" rev-list --count HEAD)" -eq 1 || fail "setup committed despite the default-no commit prompt"
setup_git_dir=$(git -C "$setup_fixture" rev-parse --absolute-git-dir)
test ! -e "$setup_git_dir/hooks/pre-commit" || fail "setup installed a hook without approval"
git -C "$setup_fixture" diff --summary | grep -Fq 'mode change' && fail "setup changed tracked script modes"
git -C "$setup_fixture" status --short | grep -Fq '?? unrelated-user-work.txt' || fail "setup altered unrelated user work"
# setup.sh prints REPO_ROOT from bash pwd, which on MSYS is the POSIX form
# (/c/...) even when the fixture path is native (C:/...). Quote the same
# form the script will print so the expectation matches on every host.
fixture_pwd=$(cd "$setup_fixture" && pwd)
printf -v quoted_fixture '%q' "$fixture_pwd"
grep -Fq "cd $quoted_fixture && codex" <<<"$setup_output" || fail "setup did not shell-quote a spaced launch path"

before_second_run=$(git -C "$setup_fixture" status --porcelain=v1 && git -C "$setup_fixture" diff --binary)
printf 'y\nCarol\nn\nn\nn\n' | (cd "$setup_fixture" && bash scripts/setup.sh --agent none) >/dev/null
after_second_run=$(git -C "$setup_fixture" status --porcelain=v1 && git -C "$setup_fixture" diff --binary)
test "$before_second_run" = "$after_second_run" || fail "a second setup run changed the reviewed write set"
grep -Fqx "# $special_name — Context" "$setup_fixture/CLAUDE.md" || fail "a second name corrupted an already initialized header"

commit_fixture="$portability_tmp/commit-scope"
make_setup_fixture "$commit_fixture"
printf 'unrelated\n' > "$commit_fixture/unrelated-user-work.txt"
printf 'y\nAda & Bob\nn\nn\nn\ny\n' | (cd "$commit_fixture" && bash scripts/setup.sh --agent none) >/dev/null
test "$(git -C "$commit_fixture" rev-list --count HEAD)" -eq 2 || fail "approved setup commit was not created"
test "$(git -C "$commit_fixture" show --pretty= --name-only HEAD)" = "CLAUDE.md" || fail "setup commit included a path outside its reviewed write set"
git -C "$commit_fixture" status --short | grep -Fq '?? unrelated-user-work.txt' || fail "setup commit captured unrelated user work"

privacy_fixture="$portability_tmp/public-existing-remote"
make_setup_fixture "$privacy_fixture"
git -C "$privacy_fixture" remote set-url origin https://github.com/example/public-context.git
privacy_output=$(printf 'n\n' | (cd "$privacy_fixture" && bash scripts/setup.sh --agent none))
grep -Fq 'Keep it local-only or use a private remote by default' <<<"$privacy_output" || fail "existing-remote setup omitted privacy preflight"
grep -Fq 'stopped before collecting or writing personal context' <<<"$privacy_output" || fail "default-no setup did not stop before personalization"
git -C "$privacy_fixture" diff --quiet || fail "default-no privacy path wrote tracked content"
test "$(git -C "$privacy_fixture" rev-list --count HEAD)" -eq 1 || fail "default-no privacy path created a commit"

no_remote_fixture="$portability_tmp/no-remote"
make_setup_fixture "$no_remote_fixture"
git -C "$no_remote_fixture" remote remove origin
no_remote_output=$(printf 'n\n' | (cd "$no_remote_fixture" && bash scripts/setup.sh --agent none))
grep -Fq 'visibility and intended audience' <<<"$no_remote_output" || fail "no-remote setup omitted unconditional audience warning"
git -C "$no_remote_fixture" diff --quiet || fail "no-remote default-no path wrote tracked content"

memory_notice_fixture="$portability_tmp/claude-memory-notice"
make_setup_fixture "$memory_notice_fixture"
memory_notice_output=$(printf 'y\n\nn\nn\nn\n' | (cd "$memory_notice_fixture" && PATH="$(dirname "$(command -v python3)"):/usr/bin:/bin" bash scripts/setup.sh --agent claude))
grep -Fq 'auto-memory is enabled by default' <<<"$memory_notice_output" || fail "local Claude onboarding omitted auto-memory default"
grep -Fq 'Inspect it with /memory' <<<"$memory_notice_output" || fail "local Claude onboarding omitted /memory inspection"
grep -Fq 'autoMemoryEnabled: false' <<<"$memory_notice_output" || fail "local Claude onboarding omitted opt-out setting"

template_fixture="$portability_tmp/template-remote"
make_setup_fixture "$template_fixture"
git -C "$template_fixture" remote set-url origin https://github.com/conorbronsdon/agent-context-os.git
template_output=$(printf 'y\n\n\n\nn\nn\nn\n' | (cd "$template_fixture" && bash scripts/setup.sh --agent none))
grep -Fq 'Your git remote still points to the template repo' <<<"$template_output" || fail "template remote replacement path was not offered"
warning_line=$(grep -n 'This workspace can contain identity' scripts/setup.sh | cut -d: -f1)
name_line=$(grep -n 'Name to place in CLAUDE.md' scripts/setup.sh | cut -d: -f1)
test -n "$warning_line" && test -n "$name_line" && test "$warning_line" -lt "$name_line" || fail "privacy warning did not precede personalization"

for skill in context-update context-end; do
  grep -Fq 'current-log.md' ".agents/skills/$skill/SKILL.md" || fail "$skill lacks current.md history handling"
  grep -Fq '**Last Updated:**' ".agents/skills/$skill/SKILL.md" || fail "$skill lacks current.md timestamp handling"
  grep -Fq 'old_date != today && old_date != newest_history_date' ".agents/skills/$skill/SKILL.md" || fail "$skill lacks the same-day history invariant"
done

echo "Portability checks passed"
