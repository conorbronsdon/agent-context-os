#!/usr/bin/env bash
#
# Scripted stand-in for a real /start session, used only to render
# docs/assets/start-demo.gif via docs/start-demo.tape.
#
# This reads no state files and calls no model. The numbers and the briefing
# below are the sample data from the example musician project that ships in
# this repo, and they match the transcript quoted in the README under
# "See it work". If you change one, change the other.
#
# Regenerate the GIF with:
#   docker run --rm -v "$PWD:/vhs" ghcr.io/charmbracelet/vhs docs/start-demo.tape

set -euo pipefail

DIM=$'\033[38;2;125;133;144m'
GRAY=$'\033[38;2;201;209;217m'
BLUE=$'\033[38;2;88;166;255m'
GREEN=$'\033[38;2;63;185;80m'
GOLD=$'\033[38;2;227;179;65m'
BOLD=$'\033[1m'
R=$'\033[0m'

say() { printf '%b\n' "$1"; }

say "${GRAY}claude-context-os — example musician project (sample data)${R}"
echo
say "${BLUE}>${R} ${BOLD}${GRAY}/start${R}"
echo
sleep 0.7

for f in \
  CLAUDE.md \
  state/current.md \
  state/decisions.md \
  state/blockers.md \
  state/weekly-priorities.md \
  sessions/2026-06-08.md
do
  say "${GREEN}●${R} ${GRAY}Read${R} ${BLUE}${f}${R}"
  sleep 0.45
done

echo
sleep 0.5
say "${BOLD}${GRAY}Session briefing — Tuesday${R}"
echo
sleep 0.4
say "${BOLD}${GRAY}Top 3 this week${R} ${DIM}(from state/weekly-priorities.md)${R}"
say "${GRAY}  1. Pitch \"Slow Light\" to 10 playlist curators — release window closes Friday${R}"
say "${GRAY}  2. Draft the EP press one-pager${R}"
say "${GRAY}  3. Book one more show for the August run${R}"
echo
sleep 0.6
say "${BOLD}${GRAY}Picking up from last session:${R} ${GRAY}you drafted 4 curator emails and were${R}"
say "${GRAY}waiting on the updated cover art before sending — it landed in inbox/ yesterday.${R}"
echo
sleep 0.6
say "${BOLD}${GRAY}Suggested first move:${R} ${GRAY}send the 4 drafted pitches, then write the next 6.${R}"
echo
sleep 0.5
say "${GOLD}What do you want to focus on today?${R}"
