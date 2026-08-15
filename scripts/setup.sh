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
        echo "Usage: bash scripts/setup.sh [--agent auto|claude|codex|none]" >&2
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
      echo "Usage: bash scripts/setup.sh [--agent auto|claude|codex|none]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: bash scripts/setup.sh [--agent auto|claude|codex|none]" >&2
      exit 2
      ;;
  esac
done

case "$AGENT_TARGET" in
  auto|claude|codex|none) ;;
  *)
    echo "Invalid --agent value: $AGENT_TARGET" >&2
    echo "Expected one of: auto, claude, codex, none" >&2
    exit 2
    ;;
esac

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
echo "  claude-context-os — setup"
echo "  ─────────────────────────"
echo ""

# ── 1. Your name ────────────────────────────────────────────────────────────

read -rp "  Name to place in CLAUDE.md (or press Enter to skip): " USER_NAME

if [ -n "$USER_NAME" ]; then
  if grep -Fq '[Your Name]' CLAUDE.md; then
    # Escape the complete sed replacement so &, backslashes, and the delimiter
    # remain literal user text rather than replacement syntax.
    SAFE_USER_NAME=$(printf '%s' "$USER_NAME" | sed 's/[\\&|]/\\&/g')
    sed -i "s|\[Your Name\]|$SAFE_USER_NAME|g" CLAUDE.md
    track_setup_path "CLAUDE.md"
    echo "  → Updated CLAUDE.md with your name"
  else
    echo "  → CLAUDE.md has no [Your Name] placeholder; left it unchanged"
  fi
fi

# ── 2. Git remote ───────────────────────────────────────────────────────────

echo ""
CURRENT_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")

if echo "$CURRENT_REMOTE" | grep -q "claude-context-os"; then
  echo "  Your git remote still points to the template repo."
  echo "  You'll want your own repo so you can push your context."
  echo ""
  read -rp "  Your repo URL (or press Enter to skip): " NEW_REMOTE
  if [ -n "$NEW_REMOTE" ]; then
    git remote set-url origin "$NEW_REMOTE"
    echo "  → Remote updated to $NEW_REMOTE"
  else
    echo "  → Skipped. Run 'git remote set-url origin <your-repo>' later."
  fi
fi

# ── 3. Example project ─────────────────────────────────────────────────────

echo ""
if [ -d "projects/example-musician" ]; then
  if prompt_yn "  Remove the example musician project? (You can always reference it on GitHub)" "n"; then
    rm -rf projects/example-musician
    # Clean ROUTING.md reference
    sed -i '/example-musician/d' ROUTING.md 2>/dev/null || true
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
  echo "    Missing: claude — install with: npm install -g @anthropic-ai/claude-code"
fi

CODEX_FOUND=false
if command -v codex &>/dev/null; then
  echo "    Found: codex"
  CODEX_FOUND=true
else
  echo "    Optional: codex — see docs/codex-onboarding.md"
fi

if command -v git &>/dev/null; then
  echo "    Found: git"
else
  echo "    Missing: git"
fi

if command -v python3 &>/dev/null; then
  echo "    Found: python3"
else
  echo "    Missing: python3 — required by safety hooks and Gemini workflow migration"
fi

if command -v gws &>/dev/null; then
  echo "    Found: gws (Google Workspace CLI)"
else
  echo "    Optional: gws — see references/gws-mcp-setup.md for Google Workspace integration"
fi

echo "    Optional add-ons: see references/integrations.md (nothing is installed automatically)"

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

SELECTED_AGENT="$AGENT_TARGET"
if [ "$SELECTED_AGENT" = "auto" ]; then
  if [ "$CLAUDE_FOUND" = true ]; then
    SELECTED_AGENT="claude"
  elif [ "$CODEX_FOUND" = true ]; then
    SELECTED_AGENT="codex"
  else
    SELECTED_AGENT="none"
  fi
fi

case "$SELECTED_AGENT" in
  claude)
    printf '  1. cd %q && claude\n' "$REPO_ROOT"
    echo "  2. Type: /setup"
    echo "     Claude will interview you and build your context files."
    echo "     (~10 minutes, fully conversational)"
    echo ""
    if [ "$CLAUDE_FOUND" = true ] && prompt_yn "  Launch Claude Code now?" "y"; then
      cd "$REPO_ROOT"
      exec claude
    fi
    ;;
  codex)
    printf '  1. cd %q && codex\n' "$REPO_ROOT"
    echo '  2. Type: $context-setup'
    echo "     Codex will interview you and build your context files."
    echo "     See docs/codex-onboarding.md for the session loop and limitations."
    echo ""
    if [ "$CODEX_FOUND" = true ] && prompt_yn "  Launch Codex now?" "y"; then
      cd "$REPO_ROOT"
      exec codex
    fi
    ;;
  none)
    printf '  Claude Code: cd %q && claude, then run /setup\n' "$REPO_ROOT"
    printf '  Codex:       cd %q && codex, then run $context-setup\n' "$REPO_ROOT"
    echo "  claude.ai:   open SETUP-PROMPTS.md and paste the prompts there"
    echo ""
    ;;
esac
