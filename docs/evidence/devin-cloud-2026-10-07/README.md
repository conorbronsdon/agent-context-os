# Devin cloud session instruction and skill evidence

This run used the public synthetic fixture
[`conorbronsdon/contextos-devin-live-fixture`](https://github.com/conorbronsdon/contextos-devin-live-fixture)
at `3d58d8f`, not personal-context data. It followed the operator-assisted path
in [`ui_conformance.py`](../../../adapters/devin/ui_conformance.py): `prepare`
bound the manifest to clean source `baff676` and the fixture, an operator ran
the session, and `record` re-verified the fixture and pull-request inventory
before writing [ui-baff676.json](ui-baff676.json). The artifact stores hashes of
the session URL and environment description, not the URL itself.

## What happened

- The operator started one cloud session in the Devin web app (Agent mode,
  Normal, Ubuntu virtual environment, default security profile) with only the
  fixture repository selected, and sent the manifest's root prompt.
- Devin replied with exactly `CONTEXTOS_DEVIN_ROOT_7D6A41C9 3d58d8f`…, the
  root canary and the fixture commit, and no skill canary. The user-only skill
  did not fire implicitly.
- The web composer refused the explicit `@skills:` turn twice with "Message
  failed to send". The operator sent the identical text into the same session
  with Devin CLI `3000.11.3` (`devin --cloud -r <session> -p`, isolated `HOME`).
  Devin replied with exactly `CONTEXTOS_DEVIN_SKILL_49B28E73`. The web session
  then showed both turns, and its session menu reported two user messages.
- The fixture still had only `main` at `3d58d8f` and no pull requests. Review
  was not invoked. The operator archived the session.

## Scope

These controls are operator-attested with local verification of the fixture,
inventory, and exact response values. Devin did not expose a product build, so
`build_identity_inspectable` is false. The run shows root instruction discovery
and explicit-only skill invocation in a cloud session. It does not show cloud
lifecycle proposal/apply, so the session surface stays experimental. It does not
establish Devin CLI or Review behavior.
