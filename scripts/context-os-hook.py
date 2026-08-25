#!/usr/bin/env python3
"""Stable hook entry point that works when the runtime starts below repo root."""

from __future__ import annotations

import json
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


def main() -> int:
    if len(sys.argv) not in (3, 4):
        print("usage: context-os-hook.py RUNTIME session-start|pre-write [SURFACE]", file=sys.stderr)
        return 2
    runtime, event = sys.argv[1:3]
    surface_id = sys.argv[3] if len(sys.argv) == 4 else None
    hook_output: str | None = "system-message"
    try:
        manifest = runtime_manifest(ROOT, runtime, check_paths=False)
        hook_output = runtime_surface(manifest, surface_id).get("hook_output")
        raw = sys.stdin.read().strip()
        payload = json.loads(raw) if raw else {}
        if not isinstance(payload, dict):
            raise ContextOSError("hook input must be an object")
        report = hook_report(ROOT, event, payload)
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
