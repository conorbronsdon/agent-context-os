#!/usr/bin/env bash
# check-doc-reachability.sh — fails when a doc exists that nothing points to.
#
# check-links.sh catches one direction of drift: a link whose target is gone.
# This catches the other: a target nothing links to any more. Both happen when
# an index row, hub, or table entry is trimmed and the file behind it is left
# behind — it stays in the tree, keeps aging, and no reader ever reaches it.
#
# A doc counts as reachable when any other tracked markdown file mentions its
# path or filename. Mentions inside inline code spans count on purpose: this
# repo routes to files from CLAUDE.md and ROUTING.md using `docs/foo.md` in
# backticks, which is a real route even though it is not a markdown link.
#
# CHANGELOG.md is excluded as a referrer. A doc mentioned only in the changelog
# is a historical record of its own creation, not a way to find it.
#
# Pure bash + git: no model, no network.
#
# Exit 1 if any tracked doc is unreachable, else 0.

set -uo pipefail

# Docs that are deliberately not linked from anywhere. Keep this empty if you
# can — an entry here is a standing exception, so add a reason with it.
#   docs/example-draft.md   # internal draft, intentionally unlisted
ALLOW_UNREACHABLE=(
)

# Directories whose files must be reachable. Everything else is unchecked.
CHECK_GLOB='docs/*.md'

REPO=$(git rev-parse --show-toplevel 2>/dev/null) || REPO=$(pwd)
cd "$REPO" || { echo "cannot cd to repo root: $REPO" >&2; exit 1; }

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "check-doc-reachability: not a git work tree, skipping" >&2
  exit 0
fi

mapfile -t DOCS < <(git ls-files "$CHECK_GLOB")
mapfile -t ALL_MD < <(git ls-files '*.md')

is_allowed() {
  local needle=$1 entry
  for entry in ${ALLOW_UNREACHABLE[@]+"${ALLOW_UNREACHABLE[@]}"}; do
    [ "$entry" = "$needle" ] && return 0
  done
  return 1
}

UNREACHABLE=0
CHECKED=0

for doc in "${DOCS[@]}"; do
  [ -z "$doc" ] && continue
  [ -f "$doc" ] || continue
  if is_allowed "$doc"; then
    continue
  fi
  CHECKED=$((CHECKED + 1))
  base=${doc##*/}
  # Tracked doc names use portable filename characters, so only the dot needs
  # escaping before the basename is used in an ERE boundary check.
  base_regex=${base//./\\.}
  found=0
  for referrer in "${ALL_MD[@]}"; do
    [ -z "$referrer" ] && continue
    [ -f "$referrer" ] || continue
    [ "$referrer" = "$doc" ] && continue
    [ "$referrer" = "CHANGELOG.md" ] && continue
    # Match the repo-relative path, or a complete bare filename for links from
    # inside docs/. Boundaries keep maintenance.md from riding on a mention of
    # repo-maintenance.md (or any other longer filename).
    if grep -qF "$doc" "$referrer" 2>/dev/null ||
       grep -qE "(^|[^[:alnum:]_./-])${base_regex}([^[:alnum:]_.-]|$)" "$referrer" 2>/dev/null; then
      found=1
      break
    fi
  done
  if [ "$found" -eq 0 ]; then
    printf '  UNREACHABLE  %s — nothing outside CHANGELOG.md points to it\n' "$doc"
    UNREACHABLE=$((UNREACHABLE + 1))
  fi
done

if [ "$UNREACHABLE" -eq 0 ]; then
  echo "✓ All $CHECKED tracked docs are reachable from other markdown"
  exit 0
else
  echo "✗ $UNREACHABLE unreachable doc(s) across $CHECKED checked"
  echo "  Link it from an index (README's documentation table, ROUTING.md), or"
  echo "  add it to ALLOW_UNREACHABLE in scripts/check-doc-reachability.sh with a reason."
  exit 1
fi
