#!/usr/bin/env python3
"""Stable hook entry point that works when the runtime starts below repo root."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contextos.kernel import ContextOSError, hook_report  # noqa: E402


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"claude", "codex", "hermes"}:
        print("usage: context-os-hook.py claude|codex|hermes session-start|pre-write", file=sys.stderr)
        return 2
    runtime, event = sys.argv[1:]
    try:
        raw = sys.stdin.read().strip()
        payload = json.loads(raw) if raw else {}
        if not isinstance(payload, dict):
            raise ContextOSError("hook input must be an object")
        report = hook_report(ROOT, event, payload)
        messages = [item["message"] for item in report["findings"]]
        if runtime in {"claude", "codex"}:
            if messages:
                print(json.dumps({"systemMessage": "\n".join(messages)}))
        else:
            print(json.dumps({"action": "allow", "message": "\n".join(messages)}))
        return 0
    except (ContextOSError, json.JSONDecodeError) as exc:
        # These hooks are advisory. Surface malformed input instead of silently
        # passing, but do not create a second mutation-enforcement path.
        message = f"Context OS advisory hook could not run: {exc}"
        if runtime in {"claude", "codex"}:
            print(json.dumps({"systemMessage": message}))
        else:
            print(json.dumps({"action": "allow", "message": message}))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
