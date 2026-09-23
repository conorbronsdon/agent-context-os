# OpenCode first-class support

This promotion adds OpenCode as a first-class Context OS runtime without
installing or changing host-global state.

The shipped adapter uses native repository discovery for `AGENTS.md` and
`.agents/skills/`, plus checked-in `/context-setup`, `/context-start`,
`/context-update`, and `/context-end` commands. All state-changing workflows
retain the shared deterministic proposal, exact-digest approval, stale-target
rejection, and receipt boundary.

Promotion evidence is bound to OpenCode 1.18.27 and includes deterministic
adapter tests plus the opt-in installed-client harness documented in
`adapters/opencode/README.md`. Hooks and native memory are not claimed. No
`opencode.json`, plugin, provider, MCP server, sharing setting, or permission
policy is installed. Model-route privacy remains an operator decision; free or
contributor routes are suitable only for public or synthetic context unless the
operator knowingly accepts their data terms.
