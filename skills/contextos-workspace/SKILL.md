---
name: contextos-workspace
description: Run Context OS continuity and lifecycle workflows in a user-selected Context OS workspace. Use when asked to inspect, set up, update, or close a Context OS session.
license: MIT
---

# Context OS workspace companion

1. Identify the user's intended Context OS workspace. Ask for its path if it is
   not explicit or unambiguous. Never use the plugin installation/cache as a
   workspace, and never create a workspace or import context implicitly.
2. Verify the selected root contains `AGENTS.md`, `ROUTING.md`,
   `scripts/contextos.sh`, and `.agents/skills/`. If not, stop and explain the
   repository-native setup in the bundled `docs/codex-onboarding.md` (relative
   to the plugin root, two directories above this file).
3. Read that workspace's `AGENTS.md`, `ROUTING.md`, and
   `docs/safety-contract.md` completely. Use that workspace as the working
   directory. Do not mix installed-plugin code with another workspace's state.
4. For the operation the user requested, read its canonical
   `.agents/skills/context-setup/SKILL.md`, `context-start/SKILL.md`,
   `context-update/SKILL.md`, or `context-end/SKILL.md` in the selected workspace.
   Follow that file; do not substitute a plugin-local copy or infer an operation
   that would expand the request.
5. Start is read-only. Setup, update and end require a displayed proposal and
   explicit approval of its exact digest before apply. Never write lifecycle
   state directly, install hooks, or commit/push implicitly. Report receipts
   and verification limits. Plugin installation grants no extra authority.
