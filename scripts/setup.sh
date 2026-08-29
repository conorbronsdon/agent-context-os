#!/usr/bin/env bash
# setup.sh — Interactive first-run setup after cloning.
# Safe to rerun: bash scripts/setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

SETUP_USAGE="Usage: bash scripts/setup.sh [--agents claude,codex,cursor,devin,hermes,openclaw|auto|none] [--agent auto|RUNTIME|none]"
AGENT_SELECTION_KIND=""
AGENT_SELECTION_RAW=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --agents)
      if [ "$#" -lt 2 ]; then
        echo "$SETUP_USAGE" >&2
        exit 2
      fi
      if [ -n "$AGENT_SELECTION_KIND" ]; then
        echo "Agent selection may be specified only once" >&2
        exit 2
      fi
      AGENT_SELECTION_KIND="agents"
      AGENT_SELECTION_RAW="$2"
      shift 2
      ;;
    --agents=*)
      if [ -n "$AGENT_SELECTION_KIND" ]; then
        echo "Agent selection may be specified only once" >&2
        exit 2
      fi
      AGENT_SELECTION_KIND="agents"
      AGENT_SELECTION_RAW="${1#--agents=}"
      shift
      ;;
    --agent)
      if [ "$#" -lt 2 ]; then
        echo "$SETUP_USAGE" >&2
        exit 2
      fi
      if [ -n "$AGENT_SELECTION_KIND" ]; then
        echo "Agent selection may be specified only once" >&2
        exit 2
      fi
      AGENT_SELECTION_KIND="agent"
      AGENT_SELECTION_RAW="$2"
      shift 2
      ;;
    --agent=*)
      if [ -n "$AGENT_SELECTION_KIND" ]; then
        echo "Agent selection may be specified only once" >&2
        exit 2
      fi
      AGENT_SELECTION_KIND="agent"
      AGENT_SELECTION_RAW="${1#--agent=}"
      shift
      ;;
    -h|--help)
      echo "$SETUP_USAGE"
      echo "  --agents records an additive tracked runtime set; it never removes agents."
      echo "  --agent is the deprecated singleton alias."
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "$SETUP_USAGE" >&2
      exit 2
      ;;
  esac
done

source "$SCRIPT_DIR/python-env.sh"

TRACKED_AGENT_SELECTION=""
REQUESTED_REGISTERED_AGENTS=""
LAUNCH_SELECTION="auto"

validate_agent_selection() {
  local kind="$1" raw="$2"
  if [ "$kind" = "agent" ]; then
    echo "  Note: --agent is deprecated; use --agents for tracked runtime selection."
    if [[ "$raw" == *,* ]]; then
      echo "--agent is a deprecated singleton alias and accepts exactly one runtime id" >&2
      exit 2
    fi
    case "$raw" in
      auto)
        LAUNCH_SELECTION="auto"
        return
        ;;
      none)
        TRACKED_AGENT_SELECTION="none"
        LAUNCH_SELECTION="none"
        return
        ;;
    esac
  fi

  if [ "$kind" = "agents" ] && [ "$raw" = "auto" ]; then
    LAUNCH_SELECTION="auto"
    return
  fi

  if ! TRACKED_AGENT_SELECTION=$("$CONTEXTOS_PYTHON_CMD" - "$raw" <<'PY'
from pathlib import Path
import sys

from contextos.kernel import ContextOSError, runtime_ids
from contextos.workspace_schema import WorkspaceConfigError, parse_agent_selection

try:
    selected = parse_agent_selection(
        sys.argv[1], known_runtime_ids=runtime_ids(Path.cwd())
    )
except (ContextOSError, WorkspaceConfigError) as exc:
    print(f"context-os: {exc}", file=sys.stderr)
    raise SystemExit(2)
print(",".join(selected) or "none")
PY
  ); then
    exit 2
  fi
  if [ "$TRACKED_AGENT_SELECTION" = "none" ]; then
    LAUNCH_SELECTION="none"
  else
    REQUESTED_REGISTERED_AGENTS="$TRACKED_AGENT_SELECTION"
    LAUNCH_SELECTION="$TRACKED_AGENT_SELECTION"
  fi
}

if [ -n "$AGENT_SELECTION_KIND" ]; then
  validate_agent_selection "$AGENT_SELECTION_KIND" "$AGENT_SELECTION_RAW"
fi

# ── Helpers ─────────────────────────────────────────────────────────────────

prompt_yn() {
  local question="$1" default="${2:-y}"
  local yn
  if [ "$default" = "y" ]; then
    printf '%s [Y/n] ' "$question" >&2
    if ! IFS= read -r yn; then
      return 1
    fi
    yn="${yn:-y}"
  else
    printf '%s [y/N] ' "$question" >&2
    if ! IFS= read -r yn; then
      return 1
    fi
    yn="${yn:-n}"
  fi
  [[ "$yn" =~ ^[Yy] ]]
}

SETUP_PATHS=()
track_setup_path() {
  local candidate="$1" existing
  for existing in "${SETUP_PATHS[@]:-}"; do
    [ "$existing" = "$candidate" ] && return
  done
  SETUP_PATHS+=("$candidate")
}

# ── Welcome ─────────────────────────────────────────────────────────────────

echo ""
echo "  Context OS: setup"
echo "  ─────────────────────────"
echo ""

# Privacy comes before personalization. This warning is unconditional because
# an existing non-template remote may also be public or broadly shared.
echo "  This workspace can contain identity, project, state, and session data."
echo "  A remote is optional. Keep it local-only or use a private remote by default. Before committing"
echo "  or pushing, verify the repository's visibility and intended audience."
echo "  Deleting a file later does not erase sensitive data from git history."
echo "  Setup never pushes; every commit and push requires separate review."
echo ""
if ! prompt_yn "  Continue after reviewing this storage and audience boundary?" "n"; then
  echo "  → Setup stopped before collecting or writing personal context"
  exit 0
fi

if [ -z "$AGENT_SELECTION_KIND" ] && [ -t 0 ]; then
  REGISTERED_AGENTS=$("$CONTEXTOS_PYTHON_CMD" - <<'PY'
from pathlib import Path
from contextos.kernel import runtime_ids

print(",".join(runtime_ids(Path.cwd())))
PY
  )
  echo ""
  echo "  Registered runtimes: $REGISTERED_AGENTS"
  read -rp "  Repository agents (comma-separated, none for core-only, Enter for local auto-detection): " AGENT_SELECTION_RAW
  if [ -n "$AGENT_SELECTION_RAW" ]; then
    AGENT_SELECTION_KIND="agents"
    validate_agent_selection "$AGENT_SELECTION_KIND" "$AGENT_SELECTION_RAW"
  fi
fi

# ── 1. Your name ────────────────────────────────────────────────────────────

read -rp "  Name to place in CLAUDE.md (or press Enter to skip): " USER_NAME

if [ -n "$USER_NAME" ]; then
  if grep -Fq '[Your Name]' CLAUDE.md; then
    "$CONTEXTOS_PYTHON_CMD" - "$USER_NAME" <<'PY'
from pathlib import Path
import sys

path = Path("CLAUDE.md")
path.write_text(
    path.read_text(encoding="utf-8").replace("[Your Name]", sys.argv[1]),
    encoding="utf-8",
    newline="\n",
)
PY
    track_setup_path "CLAUDE.md"
    echo "  → Updated CLAUDE.md with your name"
  else
    echo "  → CLAUDE.md has no [Your Name] placeholder; left it unchanged"
  fi
fi

# ── 2. Git remote ───────────────────────────────────────────────────────────

echo ""
CURRENT_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")

if echo "$CURRENT_REMOTE" | grep -q "agent-context-os"; then
  echo "  Your git remote still points to the template repo."
  echo "  A replacement remote is optional; the privacy boundary above still applies."
  echo ""
  read -rp "  Your repo URL (or press Enter to skip): " NEW_REMOTE
  if [ -n "$NEW_REMOTE" ]; then
    echo "  Proposed remote: $NEW_REMOTE"
    if prompt_yn "  Have you verified its visibility and intended audience?" "n"; then
      git remote set-url origin "$NEW_REMOTE"
      echo "  → Remote updated to $NEW_REMOTE (nothing was pushed)"
    else
      echo "  → Remote unchanged"
    fi
  else
    echo "  → Skipped. Run 'git remote set-url origin <your-repo>' later."
  fi
fi

# ── 3. Example project ─────────────────────────────────────────────────────

echo ""
if [ -d "projects/example-musician" ]; then
  if prompt_yn "  Remove the example musician project? (You can always reference it on GitHub)" "n"; then
    rm -rf projects/example-musician
    # Clean any explicit sample-project route without platform-specific sed flags.
    "$CONTEXTOS_PYTHON_CMD" - <<'PY'
from pathlib import Path

path = Path("ROUTING.md")
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
path.write_text(
    "".join(line for line in lines if "example-musician" not in line),
    encoding="utf-8",
    newline="\n",
)
PY
    track_setup_path "projects/example-musician"
    track_setup_path "ROUTING.md"
    echo "  → Removed projects/example-musician/"
  else
    echo "  → Kept example project as reference"
  fi
fi

# ── 4. Install pre-commit hook ──────────────────────────────────────────────

echo ""
HOOK_PATH=$(git rev-parse --git-path hooks/pre-commit 2>/dev/null || true)
if [ -n "$HOOK_PATH" ] && [ ! -f "$HOOK_PATH" ]; then
  if prompt_yn "  Install the local pre-commit hook at $HOOK_PATH?" "n"; then
    mkdir -p "$(dirname "$HOOK_PATH")"
    cp scripts/pre-commit-hook.sh "$HOOK_PATH"
    chmod +x "$HOOK_PATH"
    echo "  → Installed pre-commit hook"
  else
    echo "  → Skipped pre-commit hook"
  fi
elif [ -n "$HOOK_PATH" ]; then
  echo "  → Pre-commit hook already installed"
else
  echo "  → Not a git checkout; skipped pre-commit hook"
fi

# ── 5. Generate REPO_MAP.md ─────────────────────────────────────────────────

if [ -f "scripts/generate-repo-map.sh" ]; then
  if prompt_yn "  Regenerate the local, gitignored REPO_MAP.md from the current tree?" "n"; then
    bash scripts/generate-repo-map.sh
    echo "  → Generated REPO_MAP.md"
  else
    echo "  → Kept the existing REPO_MAP.md"
  fi
fi

# ── 6. Check for tools ──────────────────────────────────────────────────────

echo ""
echo "  Checking tools..."

CLAUDE_FOUND=false
if command -v claude &>/dev/null; then
  echo "    Found: claude"
  CLAUDE_FOUND=true
else
  echo "    Missing: claude — see https://code.claude.com/docs/en/installation"
  echo "             Native install is recommended; npm is an advanced Node.js alternative."
fi

CODEX_FOUND=false
if command -v codex &>/dev/null; then
  echo "    Found: codex"
  CODEX_FOUND=true
else
  echo "    Optional: codex — see docs/codex-onboarding.md"
fi

HERMES_FOUND=false
if command -v hermes &>/dev/null; then
  echo "    Found: hermes"
  HERMES_FOUND=true
else
  echo "    Optional: hermes — see AGENTS.md (Hermes Agent section)"
fi

CURSOR_IDE_FOUND=false
if command -v cursor &>/dev/null; then
  echo "    Found: cursor (IDE launcher)"
  CURSOR_IDE_FOUND=true
else
  echo "    Optional: cursor (IDE launcher)"
fi
echo "    Cursor Agent CLI uses the generic 'agent' name; verify it manually with agent --version."

OPENCLAW_FOUND=false
if command -v openclaw &>/dev/null; then
  echo "    Found: openclaw"
  OPENCLAW_FOUND=true
else
  echo "    Optional: openclaw"
fi

if command -v git &>/dev/null; then
  echo "    Found: git"
else
  echo "    Missing: git"
fi

echo "    Found: $CONTEXTOS_PYTHON_CMD (Python 3)"

if command -v gws &>/dev/null; then
  echo "    Found: gws (Google Workspace CLI)"
else
  echo "    Optional: gws; see references/google-workspace-cli-setup.md"
fi

echo "    Optional add-ons: see references/integrations.md (nothing is installed automatically)"

echo ""
echo "  Checking the provider-neutral lifecycle kernel..."
if "$CONTEXTOS_PYTHON_CMD" -m contextos doctor >/dev/null; then
  echo "    Found: context-os kernel"
else
  echo "    Kernel doctor found a required repository problem." >&2
  "$CONTEXTOS_PYTHON_CMD" -m contextos doctor >&2 || true
  exit 1
fi

# ── 7. Tracked agent selection ──────────────────────────────────────────────

SETUP_SELECTION_ACTIVATED=false
if [ -n "$TRACKED_AGENT_SELECTION" ]; then
  echo ""
  echo "  Preparing additive tracked agent selection: $TRACKED_AGENT_SELECTION"
  SETUP_PROPOSAL_JSON=$(bash "$SCRIPT_DIR/contextos.sh" workspace propose-setup \
    --agents "$TRACKED_AGENT_SELECTION")
  SETUP_PROPOSAL_ACTION=$(printf '%s' "$SETUP_PROPOSAL_JSON" | \
    "$CONTEXTOS_PYTHON_CMD" -c 'import json,sys; print(json.load(sys.stdin)["action"])')

  if [ "$SETUP_PROPOSAL_ACTION" = "noop" ]; then
    SETUP_SELECTION_ACTIVATED=true
    echo "  → Tracked agent set already contains this selection; nothing to apply"
  else
    printf '%s' "$SETUP_PROPOSAL_JSON" | "$CONTEXTOS_PYTHON_CMD" -c '
import json
import sys

report = json.load(sys.stdin)
print("  Proposed tracked workspace changes:")
for change in report["changes"]:
    print(change["diff"], end="" if change["diff"].endswith("\n") else "\n")
print("  Source Git commit: {}".format(report["source_git_head"]))
print("  Proposal digest: {}".format(report["proposal_digest"]))
'
    IFS=$'\t' read -r SETUP_PROPOSAL_PATH SETUP_PROPOSAL_DIGEST < <(
      printf '%s' "$SETUP_PROPOSAL_JSON" | "$CONTEXTOS_PYTHON_CMD" -c '
import json
import sys

report = json.load(sys.stdin)
print("{}\t{}".format(report["proposal"], report["proposal_digest"]))
'
    )
    SETUP_PROPOSAL_PATH="${SETUP_PROPOSAL_PATH%$'\r'}"
    SETUP_PROPOSAL_DIGEST="${SETUP_PROPOSAL_DIGEST%$'\r'}"
    if prompt_yn "  Apply this exact tracked-agent proposal?" "n"; then
      bash "$SCRIPT_DIR/contextos.sh" apply "$SETUP_PROPOSAL_PATH" \
        --confirm "$SETUP_PROPOSAL_DIGEST" --runtime generic
      track_setup_path "contextos.workspace.json"
      track_setup_path "workspace.yaml"
      SETUP_SELECTION_ACTIVATED=true
      echo "  → Applied the exact reviewed tracked-agent proposal"
    else
      echo "  → Tracked agent set unchanged; proposal retained locally for review"
    fi
  fi
else
  echo ""
  echo "  → Local auto-detection does not create or change tracked agent intent"
fi

if [ "$SETUP_SELECTION_ACTIVATED" = true ] && [ -n "$REQUESTED_REGISTERED_AGENTS" ]; then
  IFS=',' read -r -a SETUP_RUNTIME_IDS <<<"$REQUESTED_REGISTERED_AGENTS"
  SETUP_REGISTERED_RUNTIMES=()
  SETUP_MANAGED_RUNTIMES=()
  for setup_runtime in "${SETUP_RUNTIME_IDS[@]}"; do
    setup_install_mode=$("$CONTEXTOS_PYTHON_CMD" - "$setup_runtime" <<'PY'
import json
from pathlib import Path
import sys

manifest = json.loads((Path("runtimes") / f"{sys.argv[1]}.json").read_text(encoding="utf-8"))
print(manifest["install"]["mode"])
PY
)
    if [ "$setup_install_mode" = "managed-account" ]; then
      SETUP_MANAGED_RUNTIMES+=("$setup_runtime")
    else
      "$CONTEXTOS_PYTHON_CMD" -m contextos install --runtime "$setup_runtime" >/dev/null
      SETUP_REGISTERED_RUNTIMES+=("$setup_runtime")
    fi
  done
  if [ "${#SETUP_REGISTERED_RUNTIMES[@]}" -gt 0 ]; then
    setup_registered_csv=$(IFS=,; echo "${SETUP_REGISTERED_RUNTIMES[*]}")
    echo "  Registered selected runtimes on this host: $setup_registered_csv"
  fi
  if [ "${#SETUP_MANAGED_RUNTIMES[@]}" -gt 0 ]; then
    setup_managed_csv=$(IFS=,; echo "${SETUP_MANAGED_RUNTIMES[*]}")
    echo "  Tracked managed-account intent; remote onboarding remains unverified: $setup_managed_csv"
    echo "  Complete each managed host's account checks in its adapter guide."
  fi
elif [ -n "$REQUESTED_REGISTERED_AGENTS" ]; then
  LAUNCH_SELECTION="none"
fi

# ── 8. Initial commit ───────────────────────────────────────────────────────

echo ""
SETUP_STATUS=""
if [ "${#SETUP_PATHS[@]}" -gt 0 ]; then
  SETUP_STATUS=$(git status --short -- "${SETUP_PATHS[@]}")
fi

if [ -n "$SETUP_STATUS" ]; then
  echo "  Proposed setup commit paths and exact unstaged diff:"
  printf '%s\n' "$SETUP_STATUS"
  git diff -- "${SETUP_PATHS[@]}"

  if ! git diff --cached --quiet; then
    echo "  → Existing staged changes detected; setup will not combine or alter them."
    echo "     Review and commit the setup paths manually when ready."
  elif prompt_yn "  Commit only the setup paths shown above?" "n"; then
    git add -- "${SETUP_PATHS[@]}"
    if git diff --cached --quiet; then
      echo "  → Nothing to commit"
    elif git commit -m "Initial setup for ${USER_NAME:-user}" --quiet; then
      echo "  → Committed only the reviewed setup paths"
    else
      echo "  → Commit failed; reviewed setup changes remain staged" >&2
      exit 1
    fi
  else
    echo "  → Left setup changes uncommitted"
  fi
else
  echo "  → No setup file changes to commit"
fi

# ── 9. Next steps ───────────────────────────────────────────────────────────

echo ""
echo "  ─────────────────────────────"
echo "  Setup complete. Next:"
echo ""
echo "  Starting fresh: run the guided setup for your selected host."
echo "  Bringing existing context: review docs/migration-guide.md first."
echo "  Adding tools later: review references/integrations.md; nothing is enabled automatically."
echo ""

SELECTED_AGENT="$LAUNCH_SELECTION"
if [[ "$SELECTED_AGENT" == *,* ]]; then
  if [[ ",$SELECTED_AGENT," == *,claude,* ]] && [ "$CLAUDE_FOUND" = true ]; then
    SELECTED_AGENT="claude"
  elif [[ ",$SELECTED_AGENT," == *,codex,* ]] && [ "$CODEX_FOUND" = true ]; then
    SELECTED_AGENT="codex"
  elif [[ ",$SELECTED_AGENT," == *,hermes,* ]] && [ "$HERMES_FOUND" = true ]; then
    SELECTED_AGENT="hermes"
  elif [[ ",$SELECTED_AGENT," == *,cursor,* ]] && [ "$CURSOR_IDE_FOUND" = true ]; then
    SELECTED_AGENT="cursor"
  elif [[ ",$SELECTED_AGENT," == *,openclaw,* ]] && [ "$OPENCLAW_FOUND" = true ]; then
    SELECTED_AGENT="openclaw"
  else
    SELECTED_AGENT="none"
  fi
fi
if [ "$SELECTED_AGENT" = "auto" ]; then
  if [ "$CLAUDE_FOUND" = true ]; then
    SELECTED_AGENT="claude"
  elif [ "$CODEX_FOUND" = true ]; then
    SELECTED_AGENT="codex"
  elif [ "$HERMES_FOUND" = true ]; then
    SELECTED_AGENT="hermes"
  elif [ "$CURSOR_IDE_FOUND" = true ]; then
    SELECTED_AGENT="cursor"
  elif [ "$OPENCLAW_FOUND" = true ]; then
    SELECTED_AGENT="openclaw"
  else
    SELECTED_AGENT="none"
  fi
fi

case "$SELECTED_AGENT" in
  claude)
    if [ -z "$REQUESTED_REGISTERED_AGENTS" ]; then
      "$CONTEXTOS_PYTHON_CMD" -m contextos install --runtime claude >/dev/null
    fi
    echo "  Claude Code auto-memory is enabled by default and may write machine-local memory."
    echo "  Inspect it with /memory; to opt out, set autoMemoryEnabled: false in"
    echo "  .claude/settings.local.json. Setup does not change that host setting."
    echo ""
    printf '  1. cd %q && claude\n' "$REPO_ROOT"
    echo "  2. Type: /setup"
    echo "     Claude will interview you and build your context files."
    echo "     Import and integration choices remain separate, review-gated steps."
    echo ""
    if [ -t 0 ] && [ "$CLAUDE_FOUND" = true ] && prompt_yn "  Launch Claude Code now?" "y"; then
      cd "$REPO_ROOT"
      exec claude
    fi
    ;;
  codex)
    if [ -z "$REQUESTED_REGISTERED_AGENTS" ]; then
      "$CONTEXTOS_PYTHON_CMD" -m contextos install --runtime codex >/dev/null
    fi
    printf '  1. cd %q && codex\n' "$REPO_ROOT"
    echo '  2. Type: $setup'
    echo "     Codex will interview you and build your context files."
    echo "     See docs/getting-started.md for migration, integrations, and host limits."
    echo ""
    if [ -t 0 ] && [ "$CODEX_FOUND" = true ] && prompt_yn "  Launch Codex now?" "y"; then
      cd "$REPO_ROOT"
      exec codex
    fi
    ;;
  hermes)
    if [ -z "$REQUESTED_REGISTERED_AGENTS" ]; then
      "$CONTEXTOS_PYTHON_CMD" -m contextos install --runtime hermes >/dev/null
    fi
    printf '  1. cd %q && hermes\n' "$REPO_ROOT"
    echo "  2. Hermes reads AGENTS.md automatically. Expose .agents/skills/ as an"
    echo "     external skill directory, then type /setup. If you copy skills instead,"
    echo "     install the short aliases and context-* cores together."
    echo "     See adapters/hermes/ and docs/memory-across-agents.md."
    echo ""
    if [ -t 0 ] && [ "$HERMES_FOUND" = true ] && prompt_yn "  Launch Hermes now?" "y"; then
      cd "$REPO_ROOT"
      exec hermes
    fi
    ;;
  cursor)
    if [ -z "$REQUESTED_REGISTERED_AGENTS" ]; then
      "$CONTEXTOS_PYTHON_CMD" -m contextos install --runtime cursor >/dev/null
    fi
    printf '  IDE: open %q as the Cursor workspace, then run /context-setup.\n' "$REPO_ROOT"
    printf '  CLI: cd %q && agent, then run /context-setup.\n' "$REPO_ROOT"
    echo "  Cursor discovers AGENTS.md and .agents/skills/ natively."
    echo "  See adapters/cursor/README.md for separate IDE/CLI permission boundaries."
    echo "  Setup does not launch Cursor because it cannot safely distinguish or"
    echo "  verify both experimental surfaces and their authorization settings."
    echo ""
    ;;
  devin)
    echo "  1. Connect and authorize this repository in the intended Devin organization."
    echo "  2. Verify its Blueprint build and active snapshot in Devin Settings."
    echo "  3. Start a fresh cloud session, then invoke @skills:context-setup."
    echo "     See adapters/devin/README.md for the repository/account boundary."
    echo "     Setup records tracked intent only; it does not authenticate, launch,"
    echo "     configure, or verify any Devin account state."
    echo ""
    ;;
  openclaw)
    if [ -z "$REQUESTED_REGISTERED_AGENTS" ]; then
      "$CONTEXTOS_PYTHON_CMD" -m contextos install --runtime openclaw >/dev/null
    fi
    echo "  1. Create or choose a private OpenClaw workspace outside this repository."
    echo "  2. Synchronize and verify all eight lifecycle skills with:"
    echo "     python adapters/openclaw/sync_skills.py sync --workspace <private-workspace>"
    echo "     python adapters/openclaw/sync_skills.py check --workspace <private-workspace>"
    echo "  3. From the reviewed source commit, package and install adapters/openclaw/plugin."
    echo "  4. Bind a project alias to this canonical root in the plugin config."
    echo "  5. Invoke: /contextos <alias> setup"
    echo "     Native OpenClaw memory stays in the private workspace."
    echo "     See adapters/openclaw/README.md for configuration and limits."
    echo "     Setup does not launch OpenClaw because it cannot verify that private"
    echo "     workspace configuration without reading or changing host state."
    echo ""
    ;;
  none)
    printf '  Claude Code: cd %q && claude, then run /setup\n' "$REPO_ROOT"
    printf '  Codex:       cd %q && codex, then run $setup\n' "$REPO_ROOT"
    printf '  Hermes:      cd %q && hermes (reads AGENTS.md; see AGENTS.md Hermes section)\n' "$REPO_ROOT"
    printf '  Cursor:      see adapters/cursor/README.md (separate IDE and Agent CLI paths)\n'
    echo "  Devin:       see adapters/devin/README.md (managed cloud account + Review)"
    echo "  OpenClaw:    see adapters/openclaw/README.md (private workspace + copied skills)"
    echo "  claude.ai:   open SETUP-PROMPTS.md and paste the prompts there"
    echo "  Guide:       docs/getting-started.md"
    echo ""
    ;;
esac
