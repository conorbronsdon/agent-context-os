#!/usr/bin/env bash
# check-links.sh — deterministic broken-link checker for tracked markdown.
#
# Walks every inline ](target) link in tracked .md files, skips fenced code
# blocks and external URLs, and fails if a local target doesn't resolve. Pure
# bash + awk + git: no model, no network. This is the CI backstop that catches
# SSOT drift — when a cross-referenced file is renamed or moved, the stale link
# breaks silently until something misfires mid-session. Here it fails the build
# instead.
#
# Limitations (acceptable, matches the inline-link convention this repo uses):
#   - inline links only — reference-style [text][ref] is not resolved
#   - a literal ) inside a path truncates the match (rare; URL-encode it)
#
# Exit 1 if any broken local link, else 0.

set -uo pipefail

# Third-party / vendored trees whose links we don't own, anchored to repo root.
# Empty by default — this starter ships only first-party markdown. If you vendor
# a skill collection or docs you don't maintain, add it here, e.g.
#   EXCLUDE_RE='^(references/vendored/|some-collection/)'
EXCLUDE_RE=''

REPO=$(git rev-parse --show-toplevel 2>/dev/null) || REPO=$(pwd)
cd "$REPO" || { echo "cannot cd to repo root: $REPO" >&2; exit 1; }

# Tracked markdown only — local untracked scratch never fails CI.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if [ -n "$EXCLUDE_RE" ]; then
    mapfile -t MD < <(git ls-files '*.md' | grep -Ev "$EXCLUDE_RE" || true)
  else
    mapfile -t MD < <(git ls-files '*.md')
  fi
else
  mapfile -t MD < <(find . -name '*.md' -not -path './.git/*')
fi

BROKEN=0
CHECKED=0

for f in "${MD[@]}"; do
  [ -z "$f" ] && continue
  # A tracked file can be absent locally while a rename or deletion is staged.
  # CI sees only committed paths, but local validation should skip the removed
  # side of an in-progress change instead of asking awk to open it.
  [ -f "$f" ] || continue
  CHECKED=$((CHECKED + 1))
  dir=$(dirname "$f")
  # awk skips fenced code blocks, then prints every ](target) target on its own
  # line. We then strip the optional "title" and #anchor and resolve the path.
  while IFS= read -r raw; do
    tgt=${raw%% *}   # drop a trailing "title"
    tgt=${tgt%%#*}   # drop a #anchor (pure-anchor links become empty -> skip)
    [ -z "$tgt" ] && continue
    case "$tgt" in
      http://*|https://*|mailto:*|tel:*|//*) continue ;;
    esac
    # Skip placeholder tokens: a bare word with no path separator and no file
    # extension (e.g. (LINK), (URL), (TBD)) is a fill-in marker, not a real path.
    if [[ "$tgt" != */* && "$tgt" != *.* ]]; then
      continue
    fi
    # Leading / is GitHub repo-root-relative; everything else is file-relative.
    if [[ "$tgt" == /* ]]; then
      path=".$tgt"
    else
      path="$dir/$tgt"
    fi
    if [ ! -e "$path" ]; then
      printf '  BROKEN  %s -> %s\n' "$f" "$raw"
      BROKEN=$((BROKEN + 1))
    fi
  done < <(awk '
    /^```/ { infence = !infence; next }
    infence { next }
    {
      line = $0
      gsub(/`[^`]*`/, "", line)   # drop inline code spans
      while (match(line, /\]\([^)]+\)/)) {
        print substr(line, RSTART + 2, RLENGTH - 3)
        line = substr(line, RSTART + RLENGTH)
      }
    }
  ' "$f")
done

if [ "$BROKEN" -eq 0 ]; then
  echo "✓ No broken local links in $CHECKED tracked markdown files"
  exit 0
else
  echo "✗ $BROKEN broken local link(s) across $CHECKED files"
  exit 1
fi
