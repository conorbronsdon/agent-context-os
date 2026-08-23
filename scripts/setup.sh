#!/usr/bin/env bash
# setup.sh — Interactive first-run setup after cloning.
# Safe to rerun: bash scripts/setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

AGENT_TARGET="auto"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --agent)
      if [ "$#" -lt 2 ]; then
        echo "Usage: bash scripts/setup.sh [--agent auto|claude|codex|hermes|cursor|openclaw|none]" >&2
        exit 2
      fi
      AGENT_TARGET="$2"
      shift 2
      ;;
    --agent=*)
      AGENT_TARGET="${1#--agent=}"
      shift
      ;;
    -h|--help)
      echo "Usage: bash scripts/setup.sh [--agent auto|claude|codex|hermes|cursor|openclaw|none]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: bash scripts/setup.sh [--agent auto|claude|codex|hermes|cursor|openclaw|none]" >&2
      exit 2
      ;;
  esac
done

case "$AGENT_TARGET" in
  auto|claude|codex|hermes|cursor|openclaw|none) ;;
  *)
    echo "Invalid --agent value: $AGENT_TARGET" >&2
    echo "Expected one of: auto, claude, codex, hermes, cursor, openclaw, none" >&2
    exit 2
    ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required for setup and validation." >&2
  exit 1
fi

# ── Helpers ─────────────────────────────────────────────────────────────────

prompt_yn() {
  local question="$1" default="${2:-y}"
  local yn
  if [ "$default" = "y" ]; then
    read -rp "$question [Y/n] " yn
    yn="${yn:-y}"
  else
    read -rp "$question [y/N] " yn
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

# ── 1. Your name ────────────────────────────────────────────────────────────

read -rp "  Name to place in CLAUDE.md (or press Enter to skip): " USER_NAME

if [ -n "$USER_NAME" ]; then
  if grep -Fq '[Your Name]' CLAUDE.md; then
    python3 - "$USER_NAME" <<'PY'
from pathlib import Path
import sys

path = Path("CLAUDE.md")
path.write_text(path.read_text(encoding="utf-8").replace("[Your Name]", sys.argv[1]), encoding="utf-8")
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
    python3 - <<'PY'
from pathlib import Path

path = Path("ROUTING.md")
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
path.write_text("".join(line for line in lines if "example-musician" not in line), encoding="utf-8")
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

CURSOR_FOUND=false
if command -v cursor-agent &>/dev/null || command -v cursor &>/dev/null; then
  echo "    Found: cursor"
  CURSOR_FOUND=true
else
  echo "    Optional: cursor (Cursor CLI)"
fi

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

echo "    Found: python3"

if command -v gws &>/dev/null; then
  echo "    Found: gws (Google Workspace CLI)"
else
  echo "    Optional: gws; see references/google-workspace-cli-setup.md"
fi

echo "    Optional add-ons: see references/integrations.md (nothing is installed automatically)"

echo ""
echo "  Checking the provider-neutral lifecycle kernel..."
if python3 -m contextos doctor >/dev/null; then
  echo "    Found: context-os kernel"
else
  echo "    Kernel doctor found a required repository problem." >&2
  python3 -m contextos doctor >&2 || true
  exit 1
fi

# ── 7. Initial commit ───────────────────────────────────────────────────────

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

# ── 8. Next steps ───────────────────────────────────────────────────────────

echo ""
echo "  ─────────────────────────────"
echo "  Setup complete. Next:"
echo ""
echo "  Starting fresh: run the guided setup for your selected host."
echo "  Bringing existing context: review docs/migration-guide.md first."
echo "  Adding tools later: review references/integrations.md; nothing is enabled automatically."
echo ""

SELECTED_AGENT="$AGENT_TARGET"
if [ "$SELECTED_AGENT" = "auto" ]; then
  if [ "$CLAUDE_FOUND" = true ]; then
    SELECTED_AGENT="claude"
  elif [ "$CODEX_FOUND" = true ]; then
    SELECTED_AGENT="codex"
  elif [ "$HERMES_FOUND" = true ]; then
    SELECTED_AGENT="hermes"
  else
    SELECTED_AGENT="none"
  fi
fi

case "$SELECTED_AGENT" in
  claude)
    python3 -m contextos install --runtime claude >/dev/null
    echo "  Claude Code auto-memory is enabled by default and may write machine-local memory."
    echo "  Inspect it with /memory; to opt out, set autoMemoryEnabled: false in"
    echo "  .claude/settings.local.json. Setup does not change that host setting."
    echo ""
    printf '  1. cd %q && claude\n' "$REPO_ROOT"
    echo "  2. Type: /setup"
    echo "     Claude will interview you and build your context files."
    echo "     Import and integration choices remain separate, review-gated steps."
    echo ""
    if [ "$CLAUDE_FOUND" = true ] && prompt_yn "  Launch Claude Code now?" "y"; then
      cd "$REPO_ROOT"
      exec claude
    fi
    ;;
  codex)
    python3 -m contextos install --runtime codex >/dev/null
    printf '  1. cd %q && codex\n' "$REPO_ROOT"
    echo '  2. Type: $setup'
    echo "     Codex will interview you and build your context files."
    echo "     See docs/getting-started.md for migration, integrations, and host limits."
    echo ""
    if [ "$CODEX_FOUND" = true ] && prompt_yn "  Launch Codex now?" "y"; then
      cd "$REPO_ROOT"
      exec codex
    fi
    ;;
  hermes)
    python3 -m contextos install --runtime hermes >/dev/null
    printf '  1. cd %q && hermes\n' "$REPO_ROOT"
    echo "  2. Hermes reads AGENTS.md automatically. Expose .agents/skills/ as an"
    echo "     external skill directory, then type /setup. If you copy skills instead,"
    echo "     install the short aliases and context-* cores together."
    echo "     See adapters/hermes/ and docs/memory-across-agents.md."
    echo ""
    if [ "$HERMES_FOUND" = true ] && prompt_yn "  Launch Hermes now?" "y"; then
      cd "$REPO_ROOT"
      exec hermes
    fi
    ;;
  cursor)
    printf '  1. cd %q\n' "$REPO_ROOT"
    echo "  2. Open the repository in Cursor; Cursor reads AGENTS.md from the"
    echo "     repository root. The portable lifecycle skills in .agents/skills/"
    echo "     can be pasted or referenced in Cursor rules as needed."
    echo ""
    if [ "$CURSOR_FOUND" = true ] && prompt_yn "  Launch Cursor CLI now?" "y"; then
      cd "$REPO_ROOT"
      if command -v cursor-agent &>/dev/null; then exec cursor-agent; else exec cursor; fi
    fi
    ;;
  openclaw)
    printf '  1. cd %q && openclaw\n' "$REPO_ROOT"
    echo "  2. OpenClaw reads AGENTS.md and agentskills.io-compatible skills from"
    echo "     .agents/skills/. See AGENTS.md for the session loop."
    echo ""
    if [ "$OPENCLAW_FOUND" = true ] && prompt_yn "  Launch OpenClaw now?" "y"; then
      cd "$REPO_ROOT"
      exec openclaw
    fi
    ;;
  none)
    printf '  Claude Code: cd %q && claude, then run /setup\n' "$REPO_ROOT"
    printf '  Codex:       cd %q && codex, then run $setup\n' "$REPO_ROOT"
    printf '  Hermes:      cd %q && hermes (reads AGENTS.md; see AGENTS.md Hermes section)\n' "$REPO_ROOT"
    printf '  Cursor:      cd %q and open in Cursor (reads AGENTS.md)\n' "$REPO_ROOT"
    printf '  OpenClaw:    cd %q && openclaw (reads AGENTS.md + .agents/skills/)\n' "$REPO_ROOT"
    echo "  claude.ai:   open SETUP-PROMPTS.md and paste the prompts there"
    echo "  Guide:       docs/getting-started.md"
    echo ""
    ;;
esac
