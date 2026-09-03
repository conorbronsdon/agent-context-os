#!/usr/bin/env python3
"""Stable hook entry point that works when the runtime starts below repo root."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contextos.kernel import (  # noqa: E402
    ContextOSError,
    hook_report,
    runtime_hook_payload,
    runtime_manifest,
    runtime_surface,
)
from contextos.attachment import AttachmentError, resolve_root_roles  # noqa: E402


def main() -> int:
    if len(sys.argv) not in (3, 4):
        print("usage: context-os-hook.py RUNTIME session-start|pre-write [SURFACE]", file=sys.stderr)
        return 2
    runtime, event = sys.argv[1:3]
    surface_id = sys.argv[3] if len(sys.argv) == 4 else None
    hook_output: str | None = "system-message"
    try:
        context_value = os.environ.get("CONTEXTOS_CONTEXT_ROOT")
        working_value = os.environ.get("CONTEXTOS_WORKING_ROOT")
        if (context_value is None) != (working_value is None):
            raise ContextOSError(
                "CONTEXTOS_CONTEXT_ROOT and CONTEXTOS_WORKING_ROOT must be set together"
            )
        roles = None
        context_root = ROOT
        if context_value is not None and working_value is not None:
            try:
                roles = resolve_root_roles(
                    kernel_root=ROOT,
                    context_root=Path(context_value),
                    working_root=Path(working_value),
                )
            except AttachmentError as exc:
                raise ContextOSError(str(exc)) from exc
            context_root = roles.context_root
        manifest = runtime_manifest(ROOT, runtime, check_paths=False)
        hook_output = runtime_surface(manifest, surface_id).get("hook_output")
        raw = sys.stdin.read().strip()
        payload = json.loads(raw) if raw else {}
        if not isinstance(payload, dict):
            raise ContextOSError("hook input must be an object")
        report = hook_report(context_root, event, payload, roles=roles)
        messages = [item["message"] for item in report["findings"]]
        rendered = runtime_hook_payload(manifest, messages, surface_id)
        if rendered is not None:
            print(json.dumps(rendered))
        return 0
    except (ContextOSError, json.JSONDecodeError, OSError, UnicodeError) as exc:
        # These hooks are advisory. Surface malformed input instead of silently
        # passing, but do not create a second mutation-enforcement path.
        message = f"Context OS advisory hook could not run: {exc}"
        if hook_output is None:
            return 0
        if hook_output == "system-message":
            print(json.dumps({"systemMessage": message}))
        else:
            print(json.dumps({"action": "allow", "message": message}))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
