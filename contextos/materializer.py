"""Digest-bound materialization proposals backed by verified offline bundles."""

from __future__ import annotations

import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from .bundle_schema import (
    BundleError,
    VerifiedBundle,
    create_initial_structural_plan,
    create_structural_plan,
    verify_bundle,
)
from .component_schema import portable_path_identity
from .installed_state import (
    InstalledStateError,
    validate_installed_state as validate_installed_state_document,
)
from .primitives import canonical_json, read_regular_file_snapshot, sha256_bytes
from .workspace_schema import (
    WorkspaceConfigError,
    analyze_legacy_workspace,
    render_workspace_config,
    strict_json_loads,
    validate_workspace_config,
)


MATERIALIZE_OPERATION = "component-materialize"
MATERIALIZE_INVARIANTS = [
    "exact-structural-plan-digest",
    "offline-bundle-source-revalidation",
    "component-ownership-closed",
    "seed-and-extensible-content-preserved",
    "exact-raw-file-hashes-and-modes",
    "second-pre-mutation-revalidation",
    "shared-journal-receipt-and-rollback",
]
INSTALLED_STATE_PATH = ".context-os/installed-bundle.json"
BUNDLE_SPEC_KEYS = {"lock", "source", "expected_sha256", "source_mode"}
MATERIALIZE_AUTHORIZATION_KEYS = {
    "policy",
    "mode",
    "plan",
    "candidate",
    "current",
    "workspace_config",
    "recovery_policy",
}
MATERIALIZE_CHANGE_KEYS = {
    "path",
    "action",
    "authorization",
    "before_raw_sha256",
    "before_mode",
    "after_raw_sha256",
    "after_mode",
    "after_text",
    "content_ref",
    "diff",
}
CHANGE_AUTHORIZATION_KEYS = {"kind", "owner", "policy"}
CONTENT_REF_KEYS = {"kind", "role", "path", "text"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _kernel():
    # Imported lazily so kernel.py can call validation helpers without a module cycle.
    from . import kernel

    return kernel


def _bundle_spec(bundle: VerifiedBundle) -> dict[str, str]:
    return {
        "lock": str(bundle.lock_path.absolute()),
        "source": str(bundle.root.absolute()),
        "expected_sha256": bundle.digest,
        "source_mode": bundle.source_mode,
    }


def _load_bundle_spec(
    value: Any, field: str, *, role: str, retain_paths: Sequence[str] = (),
) -> VerifiedBundle:
    if not isinstance(value, dict) or set(value) != BUNDLE_SPEC_KEYS:
        raise BundleError(f"{field}: invalid bundle input shape")
    for key in ("lock", "source", "expected_sha256", "source_mode"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise BundleError(f"{field}.{key}: must be a non-empty string")
    if not SHA256_RE.fullmatch(value["expected_sha256"]):
        raise BundleError(f"{field}.expected_sha256: must be a lowercase SHA-256 digest")
    if value["source_mode"] not in {"directory", "git-index"}:
        raise BundleError(f"{field}.source_mode: unsupported value")
    lock = Path(value["lock"])
    source = Path(value["source"])
    if not lock.is_absolute() or not source.is_absolute():
        raise BundleError(f"{field}: lock and source must be absolute local paths")
    return verify_bundle(
        lock,
        source,
        expected_sha256=value["expected_sha256"],
        source_mode=value["source_mode"],
        role=role,
        retain_paths=retain_paths,
    )


def _mode_for_write(path: Path, *, executable: bool) -> int:
    kernel = _kernel()
    if os.name == "nt":
        return stat.S_IMODE(path.stat().st_mode) if path.exists() else kernel.NEW_CONTENT_MODE
    return 0o755 if executable else 0o644


def _before(path: Path) -> tuple[str | None, int | None]:
    kernel = _kernel()
    digest = kernel.raw_file_digest(path)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    return digest, mode


def _target_path(root: Path, relative: str) -> Path:
    kernel = _kernel()
    if relative == INSTALLED_STATE_PATH:
        candidate = root / ".context-os" / "installed-bundle.json"
        kernel._guard_local_artifact_path(root, candidate)
        return candidate
    return kernel.safe_repo_path(root, relative)


def _workspace_config_relative(root: Path, path: Path) -> str:
    try:
        relative = path.absolute().resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError) as exc:
        raise BundleError("workspace_config_path: must remain inside target_root") from exc
    if relative != "contextos.workspace.json":
        raise BundleError(
            "workspace_config_path: must equal target_root/contextos.workspace.json"
        )
    return relative


def _inline_ref(text: str) -> dict[str, Any]:
    return {"kind": "inline", "role": None, "path": None, "text": text}


def _bundle_ref(path: str) -> dict[str, Any]:
    return {"kind": "bundle", "role": "candidate", "path": path, "text": None}


def _change(
    root: Path,
    *,
    relative: str,
    action: str,
    owner: str,
    policy: str,
    kind: str,
    after_hash: str | None,
    after_mode: int | None,
    content_ref: dict[str, Any] | None,
    reason: str,
) -> dict[str, Any]:
    kernel = _kernel()
    path = _target_path(root, relative)
    before_hash, before_mode = _before(path)
    return {
        "path": relative,
        "action": action,
        "authorization": {"kind": kind, "owner": owner, "policy": policy},
        "before_raw_sha256": before_hash,
        "before_mode": before_mode,
        "after_raw_sha256": after_hash,
        "after_mode": after_mode,
        "after_text": content_ref["text"] if content_ref is not None else None,
        "content_ref": content_ref,
        "diff": f"{action} {relative}: {reason}\n",
    }


def _installed_state(candidate: VerifiedBundle, plan: dict[str, Any]) -> str:
    value = {
        "schema_version": 1,
        "bundle": {
            "name": candidate.name,
            "version": candidate.version,
            "sha256": candidate.digest,
            "source_git_commit": candidate.lock["bundle"]["source_git_commit"],
        },
        "components": list(plan["desired_components"]),
        "plan_digest": plan["plan_digest"],
    }
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _validate_installed_state(
    root: Path, current: VerifiedBundle | None, plan: dict[str, Any]
) -> None:
    path = _target_path(root, INSTALLED_STATE_PATH)
    if not path.exists():
        return
    if current is None:
        raise BundleError("installed bundle state requires an explicit current bundle")
    try:
        raw, _metadata = read_regular_file_snapshot(
            path, subject="installed bundle state"
        )
        value = validate_installed_state_document(
            strict_json_loads(raw.decode("utf-8"), source=INSTALLED_STATE_PATH)
        )
    except (OSError, UnicodeError, WorkspaceConfigError, InstalledStateError) as exc:
        raise BundleError(str(exc)) from exc
    bundle = value.get("bundle")
    expected_bundle = {
        "name": current.name,
        "version": current.version,
        "sha256": current.digest,
        "source_git_commit": current.lock["bundle"]["source_git_commit"],
    }
    if bundle != expected_bundle:
        raise BundleError("installed bundle state contradicts the current bundle")
    if value.get("components") != plan["current_components"]:
        raise BundleError("installed bundle state contradicts current_components")


def _expected_changes(
    root: Path,
    *,
    candidate: VerifiedBundle,
    plan: dict[str, Any],
    workspace_config_relative: str,
) -> list[dict[str, Any]]:
    kernel = _kernel()
    changes: list[dict[str, Any]] = []
    for item in plan["actions"]:
        action = item["action"]
        if action not in {"add", "replace", "remove"}:
            continue
        relative = item["path"]
        record = candidate.records.get(relative)
        if action in {"add", "replace"}:
            generated_text = plan.get("generated_files", {}).get(relative)
            if record is None:
                raise BundleError(f"plan.{relative}: candidate record is missing")
            target = kernel.safe_repo_path(root, relative)
            after_hash = (
                sha256_bytes(generated_text.encode("utf-8"))
                if generated_text is not None
                else record["sha256_raw"]
            )
            changes.append(
                _change(
                    root,
                    relative=relative,
                    action="write",
                    owner=item["owner"],
                    policy=item["policy"],
                    kind="component",
                    after_hash=after_hash,
                    after_mode=_mode_for_write(
                        target,
                        executable=False if generated_text is not None else record["executable"],
                    ),
                    content_ref=(
                        _inline_ref(generated_text)
                        if generated_text is not None
                        else _bundle_ref(relative)
                    ),
                    reason=item["reason"],
                )
            )
        else:
            changes.append(
                _change(
                    root,
                    relative=relative,
                    action="delete",
                    owner=item["owner"],
                    policy=item["policy"],
                    kind="component",
                    after_hash=None,
                    after_mode=None,
                    content_ref=None,
                    reason=item["reason"],
                )
            )

    config_text = render_workspace_config(plan["intended_workspace"])
    config_path = kernel.safe_repo_path(root, workspace_config_relative)
    if kernel.raw_file_digest(config_path) != sha256_bytes(config_text.encode("utf-8")):
        changes.append(
            _change(
                root,
                relative=workspace_config_relative,
                action="write",
                owner="workspace-config",
                policy="managed",
                kind="workspace-config",
                after_hash=sha256_bytes(config_text.encode("utf-8")),
                after_mode=_mode_for_write(config_path, executable=False),
                content_ref=_inline_ref(config_text),
                reason="bind workspace identity to the candidate bundle",
            )
        )

    installed_text = _installed_state(candidate, plan)
    installed_path = _target_path(root, INSTALLED_STATE_PATH)
    changes.append(
        _change(
            root,
            relative=INSTALLED_STATE_PATH,
            action="write",
            owner="context-os",
            policy="local-managed",
            kind="installed-state",
            after_hash=sha256_bytes(installed_text.encode("utf-8")),
            after_mode=_mode_for_write(installed_path, executable=False),
            content_ref=_inline_ref(installed_text),
            reason="record the exact installed bundle and component closure",
        )
    )
    legacy_path = kernel.safe_repo_path(root, "workspace.yaml")
    if legacy_path.exists():
        try:
            legacy_bytes, _metadata = read_regular_file_snapshot(
                legacy_path, subject="legacy workspace configuration"
            )
            legacy = analyze_legacy_workspace(
                legacy_bytes.decode("utf-8-sig")
            )
        except (OSError, UnicodeError, WorkspaceConfigError) as exc:
            raise BundleError(str(exc)) from exc
        if legacy.issues:
            raise BundleError(
                "workspace.yaml cannot be retired losslessly: "
                + "; ".join(legacy.issues)
            )
        conflicts = [
            key
            for key, value in legacy.values.items()
            if plan["intended_workspace"]["paths"][key] != value
        ]
        if conflicts:
            raise BundleError(
                "workspace.yaml conflicts with intended paths: "
                + ", ".join(conflicts)
            )
        changes.append(
            _change(
                root,
                relative="workspace.yaml",
                action="delete",
                owner="legacy-workspace-config",
                policy="migration-only",
                kind="workspace-config",
                after_hash=None,
                after_mode=None,
                content_ref=None,
                reason="retire losslessly migrated legacy workspace configuration",
            )
        )
    return sorted(changes, key=lambda item: portable_path_identity(item["path"]))


def create_materialization_proposal(
    *,
    target_root: Path,
    workspace_config_path: Path,
    expected_config_sha256: str,
    candidate: VerifiedBundle,
    desired_components: Sequence[str],
    now: datetime,
    current: VerifiedBundle | None = None,
    current_components: Sequence[str] = (),
    intended_workspace: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    kernel = _kernel()
    root = target_root.absolute()
    plan = create_structural_plan(
        target_root=root,
        workspace_config_path=workspace_config_path,
        expected_config_sha256=expected_config_sha256,
        candidate=candidate,
        desired_components=desired_components,
        current=current,
        current_components=current_components,
        intended_workspace=intended_workspace,
    )
    _validate_installed_state(root, current, plan)
    config_relative = _workspace_config_relative(root, workspace_config_path)
    changes = _expected_changes(
        root,
        candidate=candidate,
        plan=plan,
        workspace_config_relative=config_relative,
    )
    recovery_policy = {
        change["path"]: {
            "action": change["action"],
            "owner": change["authorization"]["owner"],
            "policy": change["authorization"]["policy"],
        }
        for change in changes
    }
    authorization = {
        "policy": "component-materialization-v1",
        "mode": "upgrade",
        "plan": plan,
        "candidate": _bundle_spec(candidate),
        "current": _bundle_spec(current) if current is not None else None,
        "workspace_config": {
            "path": config_relative,
            "expected_sha256": expected_config_sha256,
            **(
                {"intended": intended_workspace}
                if intended_workspace is not None
                else {}
            ),
        },
        "recovery_policy": recovery_policy,
    }
    source_hashes = {
        str(candidate.lock_path.absolute()): sha256_bytes(candidate.lock_path.read_bytes()),
        str(kernel.safe_repo_path(root, config_relative)): expected_config_sha256,
    }
    if current is not None:
        source_hashes[str(current.lock_path.absolute())] = sha256_bytes(
            current.lock_path.read_bytes()
        )
    source_hashes = dict(sorted(source_hashes.items()))
    document: dict[str, Any] = {
        "schema_version": kernel.SCHEMA_VERSION,
        "workflow": kernel.AGENT_LIFECYCLE_WORKFLOW,
        "operation": MATERIALIZE_OPERATION,
        "created_at": now.isoformat(),
        "proposal_id": kernel.proposal_id(
            kernel.AGENT_LIFECYCLE_WORKFLOW, now, changes
        ),
        "changes": changes,
        "authorization": authorization,
        "source_hashes": source_hashes,
        "source_git_head": kernel.git_head(root),
        "invariants": list(MATERIALIZE_INVARIANTS),
    }
    document["proposal_digest"] = sha256_bytes(
        canonical_json(document).encode("utf-8")
    )
    path = root / ".context-os" / "proposals" / f"{document['proposal_id']}.json"
    kernel._write_exclusive_text(
        path, json.dumps(document, indent=2, ensure_ascii=False) + "\n", root=root
    )
    return path, document


def _create_composition_document(
    *,
    root: Path,
    workspace_config_path: Path,
    intended: dict[str, Any],
    config_digest: str,
    candidate: VerifiedBundle,
    desired_components: Sequence[str],
    now: datetime,
    input_path: Path | None,
) -> tuple[Path, dict[str, Any]]:
    kernel = _kernel()
    plan = create_initial_structural_plan(
        target_root=root,
        workspace_config=intended,
        candidate=candidate,
        desired_components=desired_components,
    )
    config_relative = _workspace_config_relative(root, workspace_config_path)
    if kernel.raw_file_digest(kernel.safe_repo_path(root, config_relative)) is not None:
        raise BundleError("workspace_config_path: clean composition target already exists")
    _validate_installed_state(root, None, plan)
    changes = _expected_changes(
        root,
        candidate=candidate,
        plan=plan,
        workspace_config_relative=config_relative,
    )
    recovery_policy = {
        change["path"]: {
            "action": change["action"],
            "owner": change["authorization"]["owner"],
            "policy": change["authorization"]["policy"],
        }
        for change in changes
    }
    workspace_authorization = {
        "path": config_relative,
        "expected_sha256": config_digest,
        "intended": intended,
    }
    source_hashes = {
        str(candidate.lock_path.absolute()): sha256_bytes(candidate.lock_path.read_bytes())
    }
    if input_path is not None:
        workspace_authorization["input_path"] = str(input_path)
        source_hashes[str(input_path)] = config_digest
    authorization = {
        "policy": "component-materialization-v1",
        "mode": "compose",
        "plan": plan,
        "candidate": _bundle_spec(candidate),
        "current": None,
        "workspace_config": workspace_authorization,
        "recovery_policy": recovery_policy,
    }
    document: dict[str, Any] = {
        "schema_version": kernel.SCHEMA_VERSION,
        "workflow": kernel.AGENT_LIFECYCLE_WORKFLOW,
        "operation": MATERIALIZE_OPERATION,
        "created_at": now.isoformat(),
        "proposal_id": kernel.proposal_id(
            kernel.AGENT_LIFECYCLE_WORKFLOW, now, changes
        ),
        "changes": changes,
        "authorization": authorization,
        "source_hashes": dict(sorted(source_hashes.items())),
        "source_git_head": kernel.git_head(root),
        "invariants": list(MATERIALIZE_INVARIANTS),
    }
    document["proposal_digest"] = sha256_bytes(
        canonical_json(document).encode("utf-8")
    )
    path = root / ".context-os" / "proposals" / f"{document['proposal_id']}.json"
    kernel._write_exclusive_text(
        path, json.dumps(document, indent=2, ensure_ascii=False) + "\n", root=root
    )
    return path, document


def create_guided_composition_proposal(
    *,
    target_root: Path,
    workspace_config: dict[str, Any],
    candidate: VerifiedBundle,
    desired_components: Sequence[str],
    now: datetime,
) -> tuple[Path, dict[str, Any]]:
    """Create one proposal from schema-v2 intent embedded in the digest-bound document."""
    root = target_root.absolute()
    try:
        intended = validate_workspace_config(
            workspace_config,
            known_runtime_ids=sorted(candidate.runtimes),
            known_component_ids=sorted(
                item["id"] for item in candidate.manifest["components"]
            ),
        )
    except WorkspaceConfigError as exc:
        raise BundleError(str(exc)) from exc
    config_digest = sha256_bytes(render_workspace_config(intended).encode("utf-8"))
    return _create_composition_document(
        root=root,
        workspace_config_path=root / "contextos.workspace.json",
        intended=intended,
        config_digest=config_digest,
        candidate=candidate,
        desired_components=desired_components,
        now=now,
        input_path=None,
    )


def create_composition_proposal(
    *,
    target_root: Path,
    workspace_config_path: Path,
    workspace_config_input_path: Path,
    expected_config_input_sha256: str,
    candidate: VerifiedBundle,
    desired_components: Sequence[str],
    now: datetime,
) -> tuple[Path, dict[str, Any]]:
    """Create a transaction proposal for a first install into a clean target."""
    kernel = _kernel()
    root = target_root.absolute()
    input_path = workspace_config_input_path.absolute()
    try:
        input_bytes, _metadata = read_regular_file_snapshot(
            input_path, subject="workspace configuration input"
        )
        input_digest = sha256_bytes(input_bytes)
        if input_digest != expected_config_input_sha256:
            raise BundleError("expected_config_input_sha256: workspace input is stale")
        input_value = strict_json_loads(
            input_bytes.decode("utf-8"), source=str(input_path)
        )
        intended = validate_workspace_config(
            input_value,
            known_runtime_ids=sorted(candidate.runtimes),
            known_component_ids=sorted(
                item["id"] for item in candidate.manifest["components"]
            ),
        )
    except (OSError, UnicodeError, WorkspaceConfigError) as exc:
        raise BundleError(str(exc)) from exc
    return _create_composition_document(
        root=root,
        workspace_config_path=workspace_config_path,
        intended=intended,
        config_digest=input_digest,
        candidate=candidate,
        desired_components=desired_components,
        now=now,
        input_path=input_path,
    )


def _materialization_context(
    root: Path, document: dict[str, Any], *, candidate_retain_paths: Sequence[str] = (),
) -> tuple[VerifiedBundle, VerifiedBundle | None, dict[str, Any], list[dict[str, Any]]]:
    authorization = document.get("authorization")
    if not isinstance(authorization, dict) or set(authorization) != MATERIALIZE_AUTHORIZATION_KEYS:
        raise BundleError("materialization authorization has an invalid shape")
    if authorization.get("policy") != "component-materialization-v1":
        raise BundleError("materialization authorization policy is invalid")
    mode = authorization.get("mode")
    if mode not in {"compose", "upgrade"}:
        raise BundleError("materialization authorization mode is invalid")
    candidate = _load_bundle_spec(
        authorization.get("candidate"), "authorization.candidate", role="candidate",
        retain_paths=candidate_retain_paths,
    )
    current_spec = authorization.get("current")
    current = (
        _load_bundle_spec(current_spec, "authorization.current", role="current")
        if current_spec is not None
        else None
    )
    plan = authorization.get("plan")
    if not isinstance(plan, dict) or not SHA256_RE.fullmatch(str(plan.get("plan_digest"))):
        raise BundleError("authorization.plan is invalid")
    config = authorization.get("workspace_config")
    if not isinstance(config, dict) or not isinstance(config.get("path"), str):
        raise BundleError("authorization.workspace_config is invalid")
    if config["path"] != "contextos.workspace.json":
        raise BundleError("materialization workspace config path is not canonical")
    if mode == "upgrade":
        if (
            set(config) not in (
                {"path", "expected_sha256"},
                {"path", "expected_sha256", "intended"},
            )
            or not SHA256_RE.fullmatch(str(config.get("expected_sha256")))
            or (
                "intended" in config
                and not isinstance(config.get("intended"), dict)
            )
        ):
            raise BundleError("authorization.workspace_config is invalid")
        recomputed = create_structural_plan(
            target_root=root,
            workspace_config_path=_kernel().safe_repo_path(root, config["path"]),
            expected_config_sha256=config["expected_sha256"],
            candidate=candidate,
            desired_components=plan.get("desired_components", []),
            current=current,
            current_components=plan.get("current_components", []),
            intended_workspace=config.get("intended"),
        )
    else:
        external_input = "input_path" in config
        if (
            set(config) not in (
                {"path", "expected_sha256", "intended"},
                {"path", "expected_sha256", "input_path", "intended"},
            )
            or not SHA256_RE.fullmatch(str(config.get("expected_sha256")))
            or not isinstance(config.get("intended"), dict)
            or (
                external_input
                and (
                    not isinstance(config.get("input_path"), str)
                    or not Path(config["input_path"]).is_absolute()
                )
            )
        ):
            raise BundleError("authorization.workspace_config is invalid")
        try:
            if external_input:
                input_path = Path(config["input_path"])
                input_bytes, _metadata = read_regular_file_snapshot(
                    input_path, subject="workspace configuration input"
                )
                if sha256_bytes(input_bytes) != config["expected_sha256"]:
                    raise BundleError("workspace configuration input became stale")
                input_value = strict_json_loads(
                    input_bytes.decode("utf-8"), source=str(input_path)
                )
            else:
                input_value = config["intended"]
            parsed = validate_workspace_config(
                input_value,
                known_runtime_ids=sorted(candidate.runtimes),
                known_component_ids=sorted(
                    item["id"] for item in candidate.manifest["components"]
                ),
            )
            if (
                not external_input
                and sha256_bytes(render_workspace_config(parsed).encode("utf-8"))
                != config["expected_sha256"]
            ):
                raise BundleError("embedded workspace configuration digest is invalid")
        except (OSError, UnicodeError, WorkspaceConfigError) as exc:
            raise BundleError(str(exc)) from exc
        if parsed != config["intended"]:
            raise BundleError("workspace configuration input no longer matches intent")
        recomputed = create_initial_structural_plan(
            target_root=root,
            workspace_config=parsed,
            candidate=candidate,
            desired_components=plan.get("desired_components", []),
        )
    if recomputed != plan:
        raise BundleError("materialization structural plan is stale or invalid")
    _validate_installed_state(root, current, recomputed)
    changes = _expected_changes(
        root,
        candidate=candidate,
        plan=recomputed,
        workspace_config_relative=config["path"],
    )
    return candidate, current, recomputed, changes


def _candidate_payload_paths(document: dict[str, Any]) -> tuple[str, ...]:
    """Return untrusted bundle references solely as bounded retention hints."""
    paths: set[str] = set()
    changes = document.get("changes")
    if not isinstance(changes, list):
        return ()
    for change in changes:
        if not isinstance(change, dict):
            continue
        reference = change.get("content_ref")
        if (
            change.get("action") == "write"
            and isinstance(reference, dict)
            and reference.get("kind") == "bundle"
            and reference.get("role") == "candidate"
            and isinstance(reference.get("path"), str)
        ):
            paths.add(reference["path"])
    return tuple(sorted(paths, key=portable_path_identity))


def _validate_materialization_document(
    root: Path, document: dict[str, Any], *, candidate_retain_paths: Sequence[str] = (),
) -> tuple[datetime, VerifiedBundle, list[dict[str, Any]]]:
    kernel = _kernel()
    required = {
        "schema_version", "workflow", "operation", "created_at", "proposal_id",
        "changes", "authorization", "source_hashes", "source_git_head",
        "invariants", "proposal_digest",
    }
    if set(document) != required or document.get("operation") != MATERIALIZE_OPERATION:
        raise BundleError("materialization proposal has an invalid top-level shape")
    if document.get("invariants") != MATERIALIZE_INVARIANTS:
        raise BundleError("materialization proposal invariants are invalid")
    created_at = kernel.parse_now(kernel.ensure_text(document.get("created_at"), "created_at"))
    candidate, _current, plan, expected_changes = _materialization_context(
        root, document, candidate_retain_paths=candidate_retain_paths
    )
    changes = document.get("changes")
    if changes != expected_changes:
        raise BundleError("materialization changes are stale or invalid")
    for index, change in enumerate(changes):
        if not isinstance(change, dict) or set(change) != MATERIALIZE_CHANGE_KEYS:
            raise BundleError(f"materialization changes[{index}] has an invalid shape")
        if set(change["authorization"]) != CHANGE_AUTHORIZATION_KEYS:
            raise BundleError(f"materialization authorization is invalid: {change['path']}")
        content_ref = change.get("content_ref")
        if content_ref is not None and (
            not isinstance(content_ref, dict) or set(content_ref) != CONTENT_REF_KEYS
        ):
            raise BundleError(f"materialization content reference is invalid: {change['path']}")
    expected_recovery = {
        change["path"]: {
            "action": change["action"],
            "owner": change["authorization"]["owner"],
            "policy": change["authorization"]["policy"],
        }
        for change in changes
    }
    if document["authorization"].get("recovery_policy") != expected_recovery:
        raise BundleError("materialization recovery policy is invalid")
    config = document["authorization"]["workspace_config"]
    expected_sources = {
        str(candidate.lock_path.absolute()): sha256_bytes(candidate.lock_path.read_bytes()),
    }
    if document["authorization"]["mode"] != "compose":
        expected_sources[
            str(_kernel().safe_repo_path(root, config["path"]))
        ] = config["expected_sha256"]
    elif "input_path" in config:
        expected_sources[config["input_path"]] = config["expected_sha256"]
    current_spec = document["authorization"].get("current")
    if current_spec is not None:
        expected_sources[current_spec["lock"]] = sha256_bytes(Path(current_spec["lock"]).read_bytes())
    if document.get("source_hashes") != dict(sorted(expected_sources.items())):
        raise BundleError("materialization source hashes are stale or invalid")
    return created_at, candidate, expected_changes


def validate_materialization_proposal_shape(
    root: Path, document: dict[str, Any]
) -> tuple[str, datetime]:
    created_at, _candidate, _changes = _validate_materialization_document(
        root, document
    )
    return MATERIALIZE_OPERATION, created_at


def validate_materialization_preflight(root: Path, document: dict[str, Any]) -> None:
    kernel = _kernel()
    if document.get("source_git_head") != kernel.git_head(root):
        raise BundleError("refusing stale materialization proposal; git HEAD changed")
    validate_materialization_proposal_shape(root, document)


def _payloads_from_verified_context(
    candidate: VerifiedBundle, changes: Sequence[dict[str, Any]],
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for change in changes:
        if change["action"] != "write":
            continue
        reference = change["content_ref"]
        if reference["kind"] == "inline":
            payload = reference["text"].encode("utf-8")
        else:
            relative = reference["path"]
            record = candidate.records.get(relative)
            if record is None:
                raise BundleError(f"candidate source record is missing: {relative}")
            payload = candidate.verified_bytes.get(relative)
            if payload is None:
                raise BundleError(f"candidate verified payload is missing: {relative}")
            if (
                len(payload) != record["size"]
                or sha256_bytes(payload) != record["sha256_raw"]
            ):
                raise BundleError(f"candidate verified payload is invalid: {relative}")
        if sha256_bytes(payload) != change["after_raw_sha256"]:
            raise BundleError(f"materialization payload hash is invalid: {change['path']}")
        payloads[change["path"]] = payload
    return payloads


def prepare_materialization_preflight(
    root: Path, document: dict[str, Any]
) -> tuple[datetime, dict[str, bytes]]:
    """Validate one apply boundary and retain only candidate write payloads."""
    kernel = _kernel()
    if document.get("source_git_head") != kernel.git_head(root):
        raise BundleError("refusing stale materialization proposal; git HEAD changed")
    retain_paths = _candidate_payload_paths(document)
    created_at, candidate, changes = _validate_materialization_document(
        root, document, candidate_retain_paths=retain_paths
    )
    return created_at, _payloads_from_verified_context(candidate, changes)
