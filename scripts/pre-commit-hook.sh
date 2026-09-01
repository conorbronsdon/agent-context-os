#!/usr/bin/env bash
# Pre-commit hook — runs validation before allowing commits.
# Install: bash scripts/setup.sh (or manually: cp scripts/pre-commit-hook.sh .git/hooks/pre-commit)

set -euo pipefail

ERRORS=()
WARNINGS=()

# ── 1. Run validation script ────────────────────────────────────────────────

if [ -f "scripts/validate-skills.sh" ]; then
  output=$(bash scripts/validate-skills.sh 2>&1) || {
    echo "$output"
    echo ""
    echo "Pre-commit blocked: validate-skills.sh failed."
    echo "Fix the issues above, then try again."
    exit 1
  }
fi

# ── 2. CLAUDE.md size guard (100 lines max) ──────────────────────────────────

if [ -f "CLAUDE.md" ]; then
  lines=$(wc -l < "CLAUDE.md")
  if [ "$lines" -gt 100 ]; then
    ERRORS+=("CLAUDE.md is $lines lines (max 100). Move detail to skills or ROUTING.md.")
  fi
fi

# ── 3. Context file size warnings ────────────────────────────────────────────

CONTEXT_LIMIT=300

while IFS= read -r -d '' staged_file; do
  case "$staged_file" in
    identity/*|projects/*/skills/*)
      if [ -f "$staged_file" ]; then
        flines=$(wc -l < "$staged_file")
        if [ "$flines" -gt "$CONTEXT_LIMIT" ]; then
          WARNINGS+=("$staged_file is $flines lines — skills load this into context. Consider splitting.")
        fi
      fi
      ;;
  esac
done < <(git diff --cached --name-only --diff-filter=ACMR -z 2>/dev/null)

# ── 4. Prevent committing common secret files ───────────────────────────────

# This is a filename tripwire, not a content scanner. Match the basename so
# nested secret files cannot bypass it, and exclude deletions so the hook never
# tries to block removal of an already tracked secret.
while IFS= read -r -d '' staged_file; do
  staged_basename=${staged_file##*/}
  case "$staged_basename" in
    .env|.env.*|credentials.json|token.json|client_secret*)
      ERRORS+=("BLOCKED: $staged_file looks like a secrets file. Remove from staging.")
      ;;
  esac
done < <(git diff --cached --name-only --diff-filter=ACMRT -z 2>/dev/null)

# ── Report ───────────────────────────────────────────────────────────────────

if [ ${#WARNINGS[@]} -gt 0 ]; then
  echo "Warnings:"
  for w in "${WARNINGS[@]}"; do
    echo "  - $w"
  done
  echo ""
fi

if [ ${#ERRORS[@]} -gt 0 ]; then
  echo "Pre-commit blocked:"
  for err in "${ERRORS[@]}"; do
    echo "  - $err"
  done
  exit 1
fi

echo "Pre-commit checks passed"
exit 0
