#!/usr/bin/env bash
# Validate the provider-neutral lifecycle core and its host adapters.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
source "$ROOT/scripts/python-env.sh"

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

  tr -d '\r' < "$skill_file" | grep -qx "name: $skill" || fail "$skill_file name does not match its directory"
  "$CONTEXTOS_PYTHON_CMD" tests/validate-openai-metadata.py "$metadata_file" "$skill" || fail "$metadata_file failed schema validation"
  grep -Fq ".agents/skills/$skill/SKILL.md" "$command_file" || fail "$command_file does not route to $skill"
  "$CONTEXTOS_PYTHON_CMD" tests/validate-openai-metadata.py --command "$command_file" "$command" || fail "$command_file failed frontmatter validation"

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
  tr -d '\r' < "$alias_file" | grep -qx "name: $alias_name" || fail "$alias_file name does not match its directory"
  grep -Fq "../$core_name/SKILL.md" "$alias_file" || fail "$alias_file does not route to $core_name"
  "$CONTEXTOS_PYTHON_CMD" tests/validate-openai-metadata.py "$metadata_file" "$alias_name" || fail "$metadata_file failed schema validation"
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
  "$CONTEXTOS_PYTHON_CMD" tests/validate-openai-metadata.py --command ".claude/commands/$command.md" "$command" \
    || fail ".claude/commands/$command.md failed strict side-effecting frontmatter validation"
done

tr -d '\r' < .claude/commands/clean-ai-writing.md | grep -qx 'allowed-tools: "Read"' \
  || fail "clean-ai-writing must remain read-only when it is model-invocable"
tr -d '\r' < .claude/commands/find-context.md | grep -qx 'allowed-tools: "Read, Glob, Grep"' \
  || fail "find-context must not pre-approve Bash when it is model-invocable"

for skill in "${skills[@]}"; do
  grep -Fq "\$$skill" AGENTS.md || fail "AGENTS.md does not route to \$$skill"
done

for alias_name in "${aliases[@]}"; do
  grep -Fq "\$$alias_name" AGENTS.md || fail "AGENTS.md does not route to \$$alias_name"
done

portable_skill_roots=(.agents/skills)
if [ -d projects/example-musician/workflow-examples ]; then
  portable_skill_roots+=(projects/example-musician/workflow-examples)
fi
while IFS= read -r portable_skill; do
  frontmatter=$(awk '
    NR == 1 && $0 == "---" { inside = 1; next }
    inside && $0 == "---" { exit }
    inside { print }
  ' "$portable_skill")
  if grep -Eq '^(requires|allowed-tools):' <<<"$frontmatter"; then
    fail "$portable_skill puts nonstandard dependencies or host permissions in portable frontmatter"
  fi
done < <(find "${portable_skill_roots[@]}" -name SKILL.md -type f | sort)

test ! -d projects/example-musician/skills || fail "example project still presents a nested skills directory as discoverable"

[ "$(wc -l < AGENTS.md)" -le 100 ] || fail "AGENTS.md should stay under 100 lines"
grep -Fq 'repository hooks' docs/codex-onboarding.md || fail "Codex guide must describe repository hooks"
grep -Fq 'Native memory' docs/codex-onboarding.md || fail "Codex guide must disclose the native-memory boundary"
grep -Fq '/import' docs/codex-onboarding.md || fail "Codex guide must explain optional import"

grep -Fq '`.codex` layer is trusted' docs/codex-onboarding.md || fail "Codex guide must describe project trust"

setup_skill=.agents/skills/context-setup/SKILL.md
storage_line=$(grep -n 'Confirm storage and audience' "$setup_skill" | cut -d: -f1)
source_line=$(grep -n 'Choose and inspect the starting point' "$setup_skill" | cut -d: -f1)
test -n "$storage_line" && test -n "$source_line" && test "$storage_line" -lt "$source_line" \
  || fail "portable setup does not confirm storage before reading or collecting context"
grep -Fq 'does not erase git history' "$setup_skill" \
  || fail "portable setup omits git-history retention disclosure"
grep -Fq 'explicitly confirms the audience' "$setup_skill" \
  || fail "portable setup does not require audience confirmation"
grep -Fq 'auto-memory is enabled by default' .claude/commands/setup.md \
  || fail "Claude setup adapter omits the host auto-memory default"
grep -Fq '/memory' .claude/commands/setup.md \
  || fail "Claude setup adapter omits memory inspection"
grep -Fq 'autoMemoryEnabled: false' .claude/commands/setup.md \
  || fail "Claude setup adapter omits the auto-memory opt-out"

portability_tmp_parent=""
if command -v cygpath >/dev/null 2>&1; then
  # Managed Windows workspaces may deny writes to the user's native temp tree.
  # Keep Git-Bash fixtures in ignored repository-local state and retain the
  # shell-native path spelling for mkdir/tar/rm.
  portability_tmp_parent="$ROOT/.context-os/portability-tests"
  mkdir -p "$portability_tmp_parent"
  portability_tmp=$(mktemp -d "$portability_tmp_parent/run.XXXXXX")
  case "$portability_tmp" in
    "$portability_tmp_parent"/run.*) ;;
    *) fail "Windows portability temp escaped its repository-local parent" ;;
  esac
else
  portability_tmp=$(mktemp -d)
fi
cleanup_portability_tmp() {
  rm -rf -- "$portability_tmp"
  if [ -n "$portability_tmp_parent" ]; then
    rmdir "$portability_tmp_parent" 2>/dev/null || true
    rmdir "$ROOT/.context-os" 2>/dev/null || true
  fi
}
trap cleanup_portability_tmp EXIT

# Windows commonly exposes Python 3 as `python` without a usable `python3`.
# Exercise that fallback with an isolated PATH so a host python3 cannot mask it.
python_fallback_bin="$portability_tmp/python-fallback-bin"
mkdir -p "$python_fallback_bin"
python_fallback_path="$python_fallback_bin"
if command -v cygpath >/dev/null 2>&1; then
  python_fallback_path=$(cygpath -u "$python_fallback_bin")
fi
resolved_bash=${BASH:?}
resolved_python=$(command -v "$CONTEXTOS_PYTHON_CMD")
resolver_tool_path=$PATH
printf '#!%s\nexit 1\n' "$resolved_bash" > "$python_fallback_bin/python3"
printf '#!%s\nexec %q "$@"\n' "$resolved_bash" "$resolved_python" > "$python_fallback_bin/python"
chmod +x "$python_fallback_bin/python3" "$python_fallback_bin/python"
fallback_python=$(
  PATH="$python_fallback_path:$resolver_tool_path" CONTEXTOS_PYTHON= "$resolved_bash" -c \
    'source "$1"; printf "%s" "$CONTEXTOS_PYTHON_CMD"' _ "$ROOT/scripts/python-env.sh"
)
[ "$fallback_python" = "python" ] || fail "Python resolver did not fall back from python3 to python"

bytecode_policy=$(
  "$resolved_bash" -c 'source "$1"; printf "%s" "$PYTHONDONTWRITEBYTECODE"' _ "$ROOT/scripts/python-env.sh"
)
[ "$bytecode_policy" = "1" ] || fail "Python resolver does not disable repository bytecode writes"
encoding_policy=$(
  "$resolved_bash" -c 'source "$1"; printf "%s" "$PYTHONIOENCODING"' _ "$ROOT/scripts/python-env.sh"
)
[ "$encoding_policy" = "utf-8" ] || fail "Python resolver does not force UTF-8 subprocess output"

# An explicit CONTEXTOS_PYTHON is an instruction, not a hint. A working override
# must win, and a broken one must fail loudly instead of silently resolving to a
# different interpreter than the one that was asked for.
override_python=$(
  CONTEXTOS_PYTHON="$resolved_python" "$resolved_bash" -c \
    'source "$1"; printf "%s" "$CONTEXTOS_PYTHON_CMD"' _ "$ROOT/scripts/python-env.sh"
)
[ "$override_python" = "$resolved_python" ] || fail "CONTEXTOS_PYTHON override was not honored"

if CONTEXTOS_PYTHON="$portability_tmp/no-such-python" "$resolved_bash" -c \
  'source "$1"' _ "$ROOT/scripts/python-env.sh" >/dev/null 2>&1; then
  fail "unresolvable CONTEXTOS_PYTHON silently fell back to another interpreter"
fi

# The kernel uses Path.write_text(newline=...), so Python older than 3.10 must be
# rejected rather than accepted and left to fail later.
grep -Fq 'sys.version_info >= (3, 10)' scripts/python-env.sh \
  || fail "POSIX resolver does not enforce the Python 3.10 floor"
grep -Fq 'sys.version_info >= (3, 10)' scripts/context-os-hook.ps1 \
  || fail "PowerShell resolver does not enforce the Python 3.10 floor"
old_python_bin="$portability_tmp/old-python-bin"
mkdir -p "$old_python_bin"
printf '#!%s\nif [ "$1" = "-c" ]; then exit 1; fi\nexit 1\n' "$resolved_bash" > "$old_python_bin/python3"
printf '#!%s\nexit 1\n' "$resolved_bash" > "$old_python_bin/python"
chmod +x "$old_python_bin/python3" "$old_python_bin/python"
old_python_path="$old_python_bin"
if command -v cygpath >/dev/null 2>&1; then
  old_python_path=$(cygpath -u "$old_python_bin")
fi
if PATH="$old_python_path:$resolver_tool_path" CONTEXTOS_PYTHON= "$resolved_bash" -c \
  'source "$1"' _ "$ROOT/scripts/python-env.sh" >/dev/null 2>&1; then
  fail "Python resolver accepted an interpreter that failed the version probe"
fi

# A Windows shim can return success for a version probe yet write UTF-16/NUL
# output that corrupts command substitution. Reject it and continue to python.
nul_python_bin="$portability_tmp/nul-python-bin"
mkdir -p "$nul_python_bin"
cat > "$nul_python_bin/python3" <<EOF
#!$resolved_bash
printf '\\342\\0\\234\\0\\223\\0'
EOF
chmod +x "$nul_python_bin/python3"
printf '#!%s\nexec %q "$@"\n' "$resolved_bash" "$resolved_python" > "$nul_python_bin/python"
chmod +x "$nul_python_bin/python"
nul_python_path="$nul_python_bin"
if command -v cygpath >/dev/null 2>&1; then
  nul_python_path=$(cygpath -u "$nul_python_bin")
fi
nul_fallback=$(
  PATH="$nul_python_path:$resolver_tool_path" CONTEXTOS_PYTHON= "$resolved_bash" -c \
    'source "$1"; printf "%s" "$CONTEXTOS_PYTHON_CMD"' _ "$ROOT/scripts/python-env.sh"
)
[ "$nul_fallback" = "python" ] || fail "Python resolver accepted NUL-delimited probe output"
if PATH="$nul_python_path:$resolver_tool_path" CONTEXTOS_PYTHON="$nul_python_path/python3" \
  "$resolved_bash" -c 'source "$1"' _ "$ROOT/scripts/python-env.sh" >/dev/null 2>&1; then
  fail "explicit NUL-delimited CONTEXTOS_PYTHON silently fell back to another interpreter"
fi

# The lifecycle wrapper must run the kernel through the resolver.
"$resolved_bash" "$ROOT/scripts/contextos.sh" doctor >/dev/null \
  || fail "scripts/contextos.sh could not run the lifecycle kernel"

# User-facing documentation must use the same interpreter-neutral entry point
# that setup and lifecycle skills use. CHANGELOG preserves historical commands.
if git grep -n -F 'python3 -m contextos' -- '*.md' ':(exclude)CHANGELOG.md'; then
  fail "user-facing documentation bypasses scripts/contextos.sh"
fi

invalid_metadata="$portability_tmp/invalid-openai.yaml"
cp .agents/skills/context-start/agents/openai.yaml "$invalid_metadata"
printf 'malformed: [\n' >> "$invalid_metadata"
if "$CONTEXTOS_PYTHON_CMD" tests/validate-openai-metadata.py "$invalid_metadata" context-start >/dev/null 2>&1; then
  fail "malformed openai.yaml metadata passed validation"
fi

invalid_policy="$portability_tmp/string-policy-openai.yaml"
sed 's/allow_implicit_invocation: false/allow_implicit_invocation: "false"/' \
  .agents/skills/context-start/agents/openai.yaml > "$invalid_policy"
if "$CONTEXTOS_PYTHON_CMD" tests/validate-openai-metadata.py "$invalid_policy" context-start >/dev/null 2>&1; then
  fail "string-valued invocation policy passed validation"
fi

invalid_prompt="$portability_tmp/prefixed-skill-openai.yaml"
sed 's/\$context-start /\$context-started /' \
  .agents/skills/context-start/agents/openai.yaml > "$invalid_prompt"
if "$CONTEXTOS_PYTHON_CMD" tests/validate-openai-metadata.py "$invalid_prompt" context-start >/dev/null 2>&1; then
  fail "prefixed skill token passed metadata validation"
fi

control_prompt="$portability_tmp/control-prompt-openai.yaml"
sed 's/brief me/brief\\u000a me/' \
  .agents/skills/context-start/agents/openai.yaml > "$control_prompt"
if "$CONTEXTOS_PYTHON_CMD" tests/validate-openai-metadata.py "$control_prompt" context-start >/dev/null 2>&1; then
  fail "escaped control character passed metadata validation"
fi

normalized_start="$portability_tmp/normalized-start.md"
normalized_setup="$portability_tmp/normalized-setup.md"
normalized_dream="$portability_tmp/normalized-dream.md"
tr -d '\r' < .claude/commands/start.md > "$normalized_start"
tr -d '\r' < .claude/commands/setup.md > "$normalized_setup"
tr -d '\r' < .claude/commands/dream.md > "$normalized_dream"

body_only_command="$portability_tmp/body-only-start.md"
sed '/^disable-model-invocation: true$/d' "$normalized_start" > "$body_only_command"
printf '\ndisable-model-invocation: true\n' >> "$body_only_command"
if "$CONTEXTOS_PYTHON_CMD" tests/validate-openai-metadata.py --command "$body_only_command" start >/dev/null 2>&1; then
  fail "body-only invocation gate passed command validation"
fi

unrestricted_start="$portability_tmp/unrestricted-start.md"
sed 's/^allowed-tools:.*/allowed-tools: [Read, Bash]/' "$normalized_start" > "$unrestricted_start"
if "$CONTEXTOS_PYTHON_CMD" tests/validate-openai-metadata.py --command "$unrestricted_start" start >/dev/null 2>&1; then
  fail "unrestricted inline Bash grant passed command validation"
fi

wildcard_start="$portability_tmp/wildcard-start.md"
sed 's/^allowed-tools:.*/allowed-tools: "Read, Glob, Bash(gws drive files list:*)"/' "$normalized_start" > "$wildcard_start"
if "$CONTEXTOS_PYTHON_CMD" tests/validate-openai-metadata.py --command "$wildcard_start" start >/dev/null 2>&1; then
  fail "gws trailing-wildcard pre-approval passed command validation"
fi

for bad_scalar in false null 123; do
  typed_command="$portability_tmp/non-string-description-$bad_scalar.md"
  sed "s/^description:.*/description: $bad_scalar/" "$normalized_setup" > "$typed_command"
  if "$CONTEXTOS_PYTHON_CMD" tests/validate-openai-metadata.py --command "$typed_command" setup >/dev/null 2>&1; then
    fail "$bad_scalar command description passed scalar-type validation"
  fi
done

boolean_tools="$portability_tmp/boolean-tools-start.md"
sed 's/^allowed-tools:.*/allowed-tools: false/' "$normalized_start" > "$boolean_tools"
if "$CONTEXTOS_PYTHON_CMD" tests/validate-openai-metadata.py --command "$boolean_tools" start >/dev/null 2>&1; then
  fail "boolean allowed-tools passed scalar-type validation"
fi

duplicate_gate="$portability_tmp/duplicate-gate-dream.md"
sed '/^disable-model-invocation: true$/a disable-model-invocation: false' \
  "$normalized_dream" > "$duplicate_gate"
if "$CONTEXTOS_PYTHON_CMD" tests/validate-openai-metadata.py --command "$duplicate_gate" dream >/dev/null 2>&1; then
  fail "duplicate false invocation gate passed command validation"
fi

help_output=$(bash scripts/setup.sh --help)
grep -Fq -- '--agents claude,codex,cursor,devin,hermes,openclaw|auto|none' <<<"$help_output" || fail "setup help does not describe multi-agent selection"
grep -Fq -- '--agent auto|RUNTIME|none' <<<"$help_output" || fail "setup help omits the singleton compatibility alias"
grep -Fq 'Setup does not launch OpenClaw' scripts/setup.sh \
  || fail "OpenClaw setup omits the private-workspace launch boundary"
openclaw_setup_case=$(sed -n '/^  openclaw)/,/^    ;;/p' scripts/setup.sh)
test -n "$openclaw_setup_case" \
  || fail "OpenClaw setup case could not be inspected for launch behavior"
if grep -Eq '(^|[[:space:]])exec[[:space:]]+openclaw([[:space:]]|$)' <<<"$openclaw_setup_case"; then
  fail "setup can launch OpenClaw before private-workspace configuration is verified"
fi
grep -Fq '/contextos <alias> setup' <<<"$openclaw_setup_case" \
  || fail "OpenClaw setup omits the plugin command surface"
if grep -Fq 'Gateway agent RPC cwd' <<<"$openclaw_setup_case" || grep -Fq '/skill setup' <<<"$openclaw_setup_case"; then
  fail "OpenClaw setup still prints the rejected pre-plugin invocation path"
fi
grep -Fq 'Setup does not launch Cursor' scripts/setup.sh \
  || fail "Cursor setup omits the separate-surface launch boundary"
cursor_setup_case=$(sed -n '/^  cursor)/,/^    ;;/p' scripts/setup.sh)
test -n "$cursor_setup_case" \
  || fail "Cursor setup case could not be inspected for launch behavior"
if grep -Eq '(^|[[:space:]])exec[[:space:]]+(cursor|agent)([[:space:]]|$)' <<<"$cursor_setup_case"; then
  fail "setup launches an unverified Cursor surface"
fi
devin_setup_case=$(sed -n '/^  devin)/,/^    ;;/p' scripts/setup.sh)
test -n "$devin_setup_case" \
  || fail "Devin setup case could not be inspected for managed-account behavior"
grep -Fq 'Setup records tracked intent only' <<<"$devin_setup_case" \
  || fail "Devin setup omits the managed-account boundary"
if grep -Fq 'contextos install' <<<"$devin_setup_case"; then
  fail "Devin setup case locally installs a managed-account runtime"
fi
if grep -Eq '(^|[[:space:]])exec[[:space:]]+devin([[:space:]]|$)' <<<"$devin_setup_case"; then
  fail "setup launches an unverified Devin account surface"
fi
if bash scripts/setup.sh --agent invalid >/dev/null 2>&1; then
  fail "setup accepted an invalid agent"
fi
setup_write_count=$(grep -Fc 'path.write_text(' scripts/setup.sh)
setup_lf_count=$(grep -Fc 'newline="\n",' scripts/setup.sh)
test "$setup_write_count" -eq "$setup_lf_count" \
  || fail "every setup Python rewrite must explicitly preserve LF line endings"

skill_validator_fixture="$portability_tmp/skill-validator-pruning"
mkdir -p "$skill_validator_fixture/scripts" \
  "$skill_validator_fixture/.context-os/skills/ignored-local" \
  "$skill_validator_fixture/node_modules/package/skills/ignored-dependency"
cp scripts/validate-skills.sh "$skill_validator_fixture/scripts/"
cp CLAUDE.md "$skill_validator_fixture/"
git -C "$skill_validator_fixture" init -q
git -C "$skill_validator_fixture" add CLAUDE.md scripts/validate-skills.sh
git -C "$skill_validator_fixture" -c user.name=Test -c user.email=test@example.invalid commit -qm baseline
(cd "$skill_validator_fixture" && bash scripts/validate-skills.sh) >/dev/null \
  || fail "skill validation inspected ignored local or dependency trees"
mkdir -p "$skill_validator_fixture/.agents/skills/missing-skill-file"
if (cd "$skill_validator_fixture" && bash scripts/validate-skills.sh) >/dev/null 2>&1; then
  fail "skill validation stopped enforcing repository skill directories"
fi

make_setup_fixture() {
  local destination="$1"
  local source="${2:-.}"
  local fixture_path
  local product_files=()
  mkdir -p "$destination"
  while IFS= read -r -d '' fixture_path; do
    if [ -e "$source/$fixture_path" ] || [ -L "$source/$fixture_path" ]; then
      product_files+=("$fixture_path")
    fi
  done < <("$CONTEXTOS_PYTHON_CMD" - "$ROOT/components/manifest.json" <<'PY'
import json
from pathlib import Path
import sys

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for component in manifest["components"]:
    for entry in component["paths"]:
        if entry["policy"] in {"managed", "development"}:
            sys.stdout.buffer.write(entry["path"].encode() + b"\0")
PY
  )
  (cd "$source" && tar -cf - -- "${product_files[@]}") | tar -xf - -C "$destination"
  # Seed files are user-owned. Create deterministic fixture seeds instead of
  # importing personalized content from the invoking workspace.
  while IFS= read -r -d '' fixture_path; do
    mkdir -p "$destination/$(dirname "$fixture_path")"
    : > "$destination/$fixture_path"
  done < <("$CONTEXTOS_PYTHON_CMD" - "$ROOT/components/manifest.json" <<'PY'
import json
from pathlib import Path
import sys

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for component in manifest["components"]:
    for entry in component["paths"]:
        if entry["policy"] == "seed":
            sys.stdout.buffer.write(entry["path"].encode() + b"\0")
PY
  )
  printf '# [Your Name] — Context\n' > "$destination/CLAUDE.md"
  printf '# Routing\n' > "$destination/ROUTING.md"
  printf '{}\n' > "$destination/.claude/settings.json"
  # Tracked workspace configuration is caller-owned and extensible; it is not
  # part of a clean setup fixture regardless of JSON or legacy YAML format.
  # Setup's prompt sequence must remain stable after a user removes the optional
  # seed project from their own workspace. An empty fixture directory is enough
  # to exercise the removal prompt without fabricating tracked source content.
  mkdir -p "$destination/projects/example-musician"
  git -C "$destination" init -q
  git -C "$destination" config user.name "Portability Test"
  git -C "$destination" config user.email "portability@example.invalid"
  git -C "$destination" config core.autocrlf false
  git -C "$destination" add -A
  git -C "$destination" commit -qm baseline
  git -C "$destination" remote add origin https://example.invalid/context.git
}

contaminated_source="$portability_tmp/setup-source-with-user-config"
contamination_fixture="$portability_tmp/setup-fixture-without-user-config"
mkdir -p "$contaminated_source"
printf '{"agents":["openclaw"]}\n' > "$contaminated_source/contextos.workspace.json"
printf 'agents:\n  - openclaw\n' > "$contaminated_source/workspace.yaml"
mkdir -p "$contaminated_source/scripts"
printf 'tracked fixture\n' > "$contaminated_source/scripts/setup.sh"
mkdir -p "$contaminated_source/.claude"
printf '{"private":true}\n' > "$contaminated_source/.claude/settings.local.json"
printf 'secret\n' > "$contaminated_source/.env.local"
git -C "$contaminated_source" init -q
git -C "$contaminated_source" config user.name "Portability Test"
git -C "$contaminated_source" config user.email "portability@example.invalid"
git -C "$contaminated_source" add contextos.workspace.json workspace.yaml scripts/setup.sh
git -C "$contaminated_source" commit -qm baseline
make_setup_fixture "$contamination_fixture" "$contaminated_source"
test ! -e "$contamination_fixture/contextos.workspace.json" \
  || fail "setup fixture copied caller-owned contextos.workspace.json"
test ! -e "$contamination_fixture/workspace.yaml" \
  || fail "setup fixture copied caller-owned workspace.yaml"
test ! -e "$contamination_fixture/.claude/settings.local.json" \
  || fail "setup fixture copied ignored Claude settings"
test ! -e "$contamination_fixture/.env.local" \
  || fail "setup fixture copied ignored environment data"
test -f "$contamination_fixture/scripts/setup.sh" \
  || fail "setup fixture inventory dropped a declared product file"

invalid_workspace_fixture="$portability_tmp/invalid-workspace-validation"
make_setup_fixture "$invalid_workspace_fixture"
"$CONTEXTOS_PYTHON_CMD" - "$invalid_workspace_fixture/contextos.workspace.json" \
  "$ROOT/workspace/example.json" <<'PY'
from pathlib import Path
import json
import sys

config = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
config["agents"] = ["not-a-runtime"]
Path(sys.argv[1]).write_text(json.dumps(config) + "\n", encoding="utf-8", newline="\n")
PY
if (cd "$invalid_workspace_fixture" && \
  "$resolved_bash" scripts/contextos.sh workspace show) >/dev/null 2>&1; then
  fail "workspace show accepted an otherwise-valid config with an unknown runtime"
fi
grep -Fq '"$BASH" scripts/contextos.sh workspace show' scripts/validate-all.sh \
  || fail "workspace validation does not gate on the caller configuration"

for invalid_setup_args in \
  '--agents claude,claude' \
  '--agents none,claude' \
  '--agents missing' \
  '--agent claude,codex' \
  '--agent claude --agents codex' \
  '--agents claude --agents codex'; do
  read -r -a invalid_setup_argv <<<"$invalid_setup_args"
  if bash scripts/setup.sh "${invalid_setup_argv[@]}" >/dev/null 2>&1; then
    fail "setup accepted invalid or ambiguous selection: $invalid_setup_args"
  fi
done

setup_test_path="$(dirname "$(command -v "$CONTEXTOS_PYTHON_CMD")"):$(dirname "$(command -v git)"):/usr/bin:/bin"

hostile_bash_bin="$portability_tmp/hostile-bash-bin"
hostile_bash_marker="$portability_tmp/hostile-bash-launched"
mkdir -p "$hostile_bash_bin"
printf '#!%s\nprintf launched > %q\nexit 97\n' \
  "$resolved_bash" "$hostile_bash_marker" > "$hostile_bash_bin/bash"
chmod +x "$hostile_bash_bin/bash"
hostile_bash_path="$hostile_bash_bin"
if command -v cygpath >/dev/null 2>&1; then
  hostile_bash_path=$(cygpath -u "$hostile_bash_bin")
fi

multi_agent_fixture="$portability_tmp/multi-agent-selection"
make_setup_fixture "$multi_agent_fixture"
multi_agent_output=$(printf 'y\n\nn\nn\ny\ny\nn\n' | (
  cd "$multi_agent_fixture" &&
  PATH="$hostile_bash_path:$setup_test_path" "$resolved_bash" scripts/setup.sh --agents codex,claude
) 2>&1)
test ! -e "$hostile_bash_marker" \
  || fail "setup re-resolved a hostile nested bash instead of reusing its current shell"
"$CONTEXTOS_PYTHON_CMD" - "$multi_agent_fixture/contextos.workspace.json" <<'PY'
from pathlib import Path
import json
import sys

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert config["agents"] == ["claude", "codex"], config["agents"]
PY
"$CONTEXTOS_PYTHON_CMD" - "$multi_agent_fixture/.context-os/hosts.json" <<'PY'
from pathlib import Path
import json
import sys

hosts = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["hosts"]
assert sorted(hosts) == ["claude", "codex"], sorted(hosts)
PY
test ! -e "$multi_agent_fixture/workspace.yaml" \
  || fail "multi-agent setup did not transactionally retire legacy YAML"
grep -Fq 'Apply this exact tracked-agent proposal?' <<<"$multi_agent_output" \
  || fail "multi-agent setup did not present an exact proposal approval gate"
grep -Fq '"runtime_identity": "self-reported"' <<<"$multi_agent_output" \
  || fail "multi-agent setup did not report its transaction receipt"
unexpected_setup_paths=$(git -C "$multi_agent_fixture" status --short | \
  grep -Ev '^( D workspace\.yaml|\?\? contextos\.workspace\.json)$' || true)
test -z "$unexpected_setup_paths" \
  || fail "multi-agent setup changed unselected adapter or unrelated paths: $unexpected_setup_paths"

devin_fixture="$portability_tmp/devin-managed-account-selection"
make_setup_fixture "$devin_fixture"
devin_output=$(printf 'y\n\nn\nn\nn\ny\nn\n' | (
  cd "$devin_fixture" &&
  PATH="$setup_test_path" bash scripts/setup.sh --agents devin
) 2>&1)
"$CONTEXTOS_PYTHON_CMD" - "$devin_fixture/contextos.workspace.json" <<'PY'
from pathlib import Path
import json
import sys

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert config["agents"] == ["devin"], config["agents"]
hosts_path = Path(sys.argv[1]).parent / ".context-os" / "hosts.json"
if hosts_path.exists():
    assert "devin" not in json.loads(hosts_path.read_text(encoding="utf-8"))["hosts"]
PY
grep -Fq 'remote onboarding remains unverified: devin' <<<"$devin_output" \
  || fail "managed-account setup implied that Devin was locally configured"

# Subset and none reruns are no-ops; a disjoint selection expands the set.
subset_output=$(printf 'y\n\nn\nn\nn\n' | (
  cd "$multi_agent_fixture" &&
  PATH="$setup_test_path" bash scripts/setup.sh --agents claude
))
grep -Fq 'already contains this selection' <<<"$subset_output" \
  || fail "subset setup rerun did not preserve the configured set"
printf 'y\n\nn\nn\nn\ny\nn\n' | (
  cd "$multi_agent_fixture" &&
  PATH="$setup_test_path" bash scripts/setup.sh --agents hermes,openclaw
) >/dev/null
"$CONTEXTOS_PYTHON_CMD" - "$multi_agent_fixture/contextos.workspace.json" <<'PY'
from pathlib import Path
import json
import sys

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert config["agents"] == ["claude", "codex", "hermes", "openclaw"], config["agents"]
PY
none_output=$(printf 'y\n\nn\nn\nn\n' | (
  cd "$multi_agent_fixture" &&
  PATH="$setup_test_path" bash scripts/setup.sh --agents none
))
grep -Fq 'already contains this selection' <<<"$none_output" \
  || fail "none setup rerun shrank or rewrote a non-empty configured set"

non_tty_fixture="$portability_tmp/non-tty-auto"
make_setup_fixture "$non_tty_fixture"
fake_agent_bin="$non_tty_fixture/fake-agent-bin"
fake_agent_marker="$non_tty_fixture/fake-agent-launched"
mkdir -p "$fake_agent_bin"
printf '#!%s\nprintf launched > %q\n' "$resolved_bash" "$fake_agent_marker" > "$fake_agent_bin/claude"
chmod +x "$fake_agent_bin/claude"
fake_agent_path="$fake_agent_bin"
if command -v cygpath >/dev/null 2>&1; then
  fake_agent_path=$(cygpath -u "$fake_agent_bin")
fi
printf 'y\n\nn\nn\nn\n' | (
  cd "$non_tty_fixture" && PATH="$fake_agent_path:$setup_test_path" bash scripts/setup.sh --agents auto
) >/dev/null
test ! -e "$non_tty_fixture/contextos.workspace.json" \
  || fail "non-TTY auto selection inferred tracked agent intent"
test ! -e "$fake_agent_marker" \
  || fail "non-TTY setup launched an installed runtime"
"$CONTEXTOS_PYTHON_CMD" - "$non_tty_fixture/.context-os/hosts.json" <<'PY'
from pathlib import Path
import json
import sys

hosts = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["hosts"]
assert sorted(hosts) == ["claude"], sorted(hosts)
PY

omitted_non_tty_fixture="$portability_tmp/non-tty-omitted"
make_setup_fixture "$omitted_non_tty_fixture"
printf 'y\n\nn\nn\nn\n' | (
  cd "$omitted_non_tty_fixture" && PATH="$setup_test_path" bash scripts/setup.sh
) >/dev/null
test ! -e "$omitted_non_tty_fixture/contextos.workspace.json" \
  || fail "non-TTY omitted selection inferred tracked agent intent"

if command -v script >/dev/null 2>&1; then
  tty_fixture="$portability_tmp/tty-selection"
  make_setup_fixture "$tty_fixture"
  tty_output=$(printf 'y\nclaude,codex\n\nn\nn\nn\ny\nn\n' | (
    cd "$tty_fixture" &&
    script -q -c "env PATH='$setup_test_path' bash scripts/setup.sh" /dev/null
  ))
  grep -Fq 'Repository agents (comma-separated' <<<"$tty_output" \
    || fail "TTY setup did not prompt for repository agents"
  "$CONTEXTOS_PYTHON_CMD" - "$tty_fixture/contextos.workspace.json" <<'PY'
from pathlib import Path
import json
import sys

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert config["agents"] == ["claude", "codex"], config["agents"]
PY
fi

# Both inline Python rewrites must preserve an LF checkout on Windows. Without
# newline="\n", TextIO converts every line to CRLF and turns the reviewed setup
# diff into a whole-file rewrite under core.autocrlf=false.
line_endings_fixture="$portability_tmp/lf-preservation"
make_setup_fixture "$line_endings_fixture"
"$CONTEXTOS_PYTHON_CMD" - "$line_endings_fixture/CLAUDE.md" "$line_endings_fixture/ROUTING.md" <<'PY'
from pathlib import Path
import sys

for raw_path in sys.argv[1:]:
    path = Path(raw_path)
    path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
PY
git -C "$line_endings_fixture" add CLAUDE.md ROUTING.md
git -C "$line_endings_fixture" commit --amend --no-edit -q
printf 'y\nAda\ny\nn\nn\nn\n' | (cd "$line_endings_fixture" && bash scripts/setup.sh --agent none) >/dev/null
test "$(git -C "$line_endings_fixture" diff --numstat -- CLAUDE.md)" = $'1\t1\tCLAUDE.md' \
  || fail "setup name replacement rewrote more than one CLAUDE.md line"
git -C "$line_endings_fixture" diff --quiet -- ROUTING.md \
  || fail "setup sample-route cleanup rewrote ROUTING.md despite no matching route"
if LC_ALL=C grep -q $'\r' "$line_endings_fixture/CLAUDE.md" "$line_endings_fixture/ROUTING.md"; then
  fail "setup rewrites converted an LF checkout to CRLF"
fi

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
printf 'y\nAda & Bob\nn\nn\nn\nn\ny\n' | (cd "$commit_fixture" && bash scripts/setup.sh --agent none) >/dev/null
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
memory_notice_output=$(printf 'y\n\nn\nn\nn\ny\nn\n' | (cd "$memory_notice_fixture" && PATH="$(dirname "$(command -v "$CONTEXTOS_PYTHON_CMD")"):$(dirname "$(command -v git)"):/usr/bin:/bin" bash scripts/setup.sh --agent claude))
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

for skill in context-setup context-update context-end; do
  grep -Fq 'scripts/contextos.sh propose' ".agents/skills/$skill/SKILL.md" || fail "$skill does not route mutation through the kernel"
  if grep -Fq 'python3 -m contextos' ".agents/skills/$skill/SKILL.md"; then
    fail "$skill hardcodes python3 instead of the resolved interpreter wrapper"
  fi
  grep -Fq 'scripts/contextos.sh apply' ".agents/skills/$skill/SKILL.md" || fail "$skill does not route approval through the kernel"
done

test -f .codex/hooks.json || fail "missing Codex hook adapter"
test -f adapters/hermes/hooks.example.yaml || fail "missing Hermes hook adapter"
test -f contextos/__main__.py || fail "missing deterministic lifecycle kernel"
"$CONTEXTOS_PYTHON_CMD" -m unittest discover -s tests -p 'test_contextos_kernel.py' >/dev/null \
  || fail "kernel conformance failed"
"$CONTEXTOS_PYTHON_CMD" -m unittest discover -s tests -p 'test_runtime_manifests.py' >/dev/null \
  || fail "kernel or runtime manifest conformance failed"

echo "Portability checks passed"
