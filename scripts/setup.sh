#!/usr/bin/env bash
# setup.sh — Interactive first-run setup after cloning.
# Run once: bash scripts/setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

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

# ── Welcome ─────────────────────────────────────────────────────────────────

echo ""
echo "  claude-context-os — setup"
echo "  ─────────────────────────"
echo ""

# ── 1. Your name ────────────────────────────────────────────────────────────

read -rp "  What's your name? " USER_NAME

if [ -n "$USER_NAME" ]; then
  # Inject name into CLAUDE.md header
  sed -i "s/\[Your Name\]/$USER_NAME/g" CLAUDE.md 2>/dev/null || true
  echo "  → Updated CLAUDE.md with your name"
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
    echo "  → Removed projects/example-musician/"
  else
    echo "  → Kept example project as reference"
  fi
fi

# ── 4. Install pre-commit hook ──────────────────────────────────────────────

echo ""
if [ ! -f ".git/hooks/pre-commit" ]; then
  cp scripts/pre-commit-hook.sh .git/hooks/pre-commit
  chmod +x .git/hooks/pre-commit
  echo "  → Installed pre-commit hook"
else
  echo "  → Pre-commit hook already installed"
fi

# ── 5. Make scripts executable ──────────────────────────────────────────────

chmod +x scripts/*.sh 2>/dev/null || true

# ── 6. Generate REPO_MAP.md ─────────────────────────────────────────────────

if [ -f "scripts/generate-repo-map.sh" ]; then
  bash scripts/generate-repo-map.sh 2>/dev/null
  echo "  → Generated REPO_MAP.md"
fi

# ── 7. Check for tools ──────────────────────────────────────────────────────

echo ""
echo "  Checking tools..."

CLAUDE_FOUND=false
if command -v claude &>/dev/null; then
  echo "    Found: claude"
  CLAUDE_FOUND=true
else
  echo "    Missing: claude — install with: npm install -g @anthropic-ai/claude-code"
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

# ── 8. Initial commit ───────────────────────────────────────────────────────

echo ""
if prompt_yn "  Create an initial commit with your setup?" "y"; then
  git add -A
  git commit -m "Initial setup for ${USER_NAME:-user}" --quiet 2>/dev/null || echo "  → Nothing to commit (already clean)"
  echo "  → Committed"
fi

# ── 9. Next steps ───────────────────────────────────────────────────────────

echo ""
echo "  ─────────────────────────────"
echo "  Setup complete. Next:"
echo ""
echo "  1. cd $REPO_ROOT && claude"
echo "  2. Type: /setup"
echo "     Claude will interview you and build your context files."
echo "     (~10 minutes, fully conversational)"
echo ""
echo "  Or if you prefer claude.ai:"
echo "     Open SETUP-PROMPTS.md and paste the prompts there."
echo ""

if [ "$CLAUDE_FOUND" = true ]; then
  if prompt_yn "  Launch Claude Code now?" "y"; then
    cd "$REPO_ROOT"
    exec claude
  fi
fi
