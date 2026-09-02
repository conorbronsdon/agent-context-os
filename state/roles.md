# Fleet roles

Enumerated roles for the coordination board (`coordination/README.md`). A
board message's `audience` must be `all`, one of these roles, or a specific
`runtime/run-id`. Keep this list short and edit it deliberately — validation
warns on audiences that match no role here, which is what catches typos before
they silently drop a message.

- generalist

Add roles as your fleet differentiates (for example: researcher, builder,
publisher, maintainer). One role per line, lowercase, hyphenated.
