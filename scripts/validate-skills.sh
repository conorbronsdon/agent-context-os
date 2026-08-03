#!/usr/bin/env bash
# Validates skill structure, command files, and repo conventions.
# Run before pushing: bash scripts/validate-skills.sh
# Exits 1 if any check fails.

set -euo pipefail

ERRORS=()

# ── Helpers ──────────────────────────────────────────────────────────────────

check_frontmatter() {
  local file="$1"
  local min_desc="${2:-60}"
  local content
  content=$(cat "$file")

  if ! echo "$content" | grep -q "^---"; then
    ERRORS+=("MISSING FRONTMATTER: $file")
    return
  fi
  if ! echo "$content" | grep -q "^name:"; then
    ERRORS+=("MISSING name: field — $file")
  fi
  if ! echo "$content" | grep -q "^description:"; then
    ERRORS+=("MISSING description: field — $file")
  fi

  local desc
  desc=$(echo "$content" | grep "^description:" | head -1)
  if [ ${#desc} -lt "$min_desc" ]; then
    ERRORS+=("DESCRIPTION TOO SHORT (<$min_desc chars) — $file")
  fi
}

# ── Check 1: All skill directories have a SKILL.md ──────────────────────────

SKILL_DIRS=$(find . \
  -path './.git' -prune -o \
  -type d -name 'skills' -print | \
  xargs -I{} find {} -mindepth 1 -maxdepth 1 -type d 2>/dev/null)

for dir in $SKILL_DIRS; do
  if [ ! -f "$dir/SKILL.md" ]; then
    ERRORS+=("MISSING SKILL.md in $dir")
  fi
done

# ── Check 2: All SKILL.md files have valid frontmatter ──────────────────────

while IFS= read -r -d '' skill; do
  check_frontmatter "$skill" 60
done < <(find . -path './.git' -prune -o -name 'SKILL.md' -print0)

# ── Check 3: All command .md files have valid frontmatter ───────────────────

if [ -d "commands" ]; then
  while IFS= read -r -d '' cmd; do
    check_frontmatter "$cmd" 20
  done < <(find ./commands -name '*.md' -print0)
fi

# ── Check 4: CLAUDE.md exists and is under 100 lines ────────────────────────

if [ ! -f "CLAUDE.md" ]; then
  ERRORS+=("MISSING CLAUDE.md at repo root")
else
  lines=$(wc -l < "CLAUDE.md")
  if [ "$lines" -gt 100 ]; then
    ERRORS+=("CLAUDE.md is $lines lines — keep it under 100 for efficient context loading")
  fi
fi

# ── Check 5: No secrets in tracked files ─────────────────────────────────────

SECRET_PATTERNS='(AKIA[0-9A-Z]{16}|sk-[a-zA-Z0-9]{48}|ghp_[a-zA-Z0-9]{36}|xox[bps]-[a-zA-Z0-9-]+|-----BEGIN (RSA |EC )?PRIVATE KEY)'

# -E only. `grep -qEP` is not "both engines" — it is a usage error: grep rejects
# it with "conflicting matchers specified" and exits 2. Exit 2 is not 0, so the
# `if` never fired, and `2>/dev/null` hid the message. This check reported clean
# on every file since it was written, including files that did contain a key.
# Demonstrated 2026-08-03 by planting a fake AWS-style access key in a tracked
# file: the script printed "All checks passed". (No sample literal is written
# here on purpose — a real one in this comment makes the file flag itself.)
#
# -P alone is not the fix either. Git Bash on Windows builds grep without PCRE,
# so `grep -qP` also exits 2 there and would reintroduce the same silent pass on
# the machine this repo is maintained from. -E covers every pattern above.
while IFS= read -r tracked_file; do
  if grep -qE "$SECRET_PATTERNS" "$tracked_file" 2>/dev/null; then
    ERRORS+=("POSSIBLE SECRET in $tracked_file — review before pushing")
  fi
done < <(git ls-files 2>/dev/null)

# ── Check 6: Staleness — context files older than 90 days ───────────────────

for dir in identity career investing projects; do
  if [ -d "$dir" ]; then
    while IFS= read -r -d '' ctx_file; do
      if grep -q "^\*\*Last Updated:\*\*" "$ctx_file" 2>/dev/null; then
        date_str=$(grep "^\*\*Last Updated:\*\*" "$ctx_file" | head -1 | sed 's/.*\*\*Last Updated:\*\* *//' | sed 's/ *$//')
        if parsed=$(date -d "$date_str" +%s 2>/dev/null); then
          days_ago=$(( ($(date +%s) - parsed) / 86400 ))
          if [ "$days_ago" -gt 90 ]; then
            ERRORS+=("STALE ($days_ago days): $ctx_file — Last Updated: $date_str")
          fi
        fi
      fi
    done < <(find "$dir" -name '*.md' -print0 2>/dev/null)
  fi
done

# ── Report ───────────────────────────────────────────────────────────────────

if [ ${#ERRORS[@]} -eq 0 ]; then
  echo "All checks passed"
  exit 0
else
  echo "Validation failed:"
  for err in "${ERRORS[@]}"; do
    echo "  - $err"
  done
  exit 1
fi
