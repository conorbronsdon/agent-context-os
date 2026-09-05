from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .continuity import briefing_report, history_report, render_briefing, render_history
from .attachment import AttachmentError, RootRoles, resolve_root_roles
from .bundle_schema import (
    BundleError,
    create_bundle_lock,
    create_structural_plan,
    verify_bundle,
)
from .kernel import (
    ContextOSError,
    PROJECT_OPERATIONS,
    agent_list_report,
    apply_proposal,
    create_agent_activation_proposal,
    create_proposal,
    create_project_attachment_proposal,
    create_workspace_migration_proposal,
    create_workspace_setup_proposal,
    discover_root,
    doctor,
    hook_report,
    install_runtime,
    migrate_legacy_runtime_state,
    parse_now,
    project_attachment_doctor,
    plan_workspace_migration,
    read_json,
    render_hook_payload,
    runtime_ids,
    runtime_manifest,
    runtime_surface,
    start_report,
    load_project_attachment,
    workspace_resolution_report,
)
from .coordination import (
    bootstrap_board,
    compact_board,
    create_claim,
    post_message,
    propose_promotion,
    release_claim,
    sync_board,
    validate_board,
)
from .materializer import (
    INSTALLED_STATE_PATH,
    MATERIALIZE_OPERATION,
    create_composition_proposal,
    create_guided_composition_proposal,
    create_materialization_proposal,
)
from .installed_state import InstalledStateError, validate_installed_state
from .primitives import read_regular_file_snapshot, sha256_bytes
from .workspace_composition import (
    WorkspaceCompositionError,
    desired_component_closure,
)
from .workspace_schema import (
    DEFAULT_PATHS,
    WORKSPACE_SCHEMA_VERSION,
    WorkspaceConfigError,
    analyze_legacy_workspace,
    load_workspace_config,
    parse_agent_selection,
    strict_json_loads,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="context-os", description="Deterministic Context OS lifecycle kernel")
    result.add_argument(
        "--root",
        type=Path,
        help=(
            "v0.12 discovery start for the nearest Context OS root "
            "(ContextRoot and nominal WorkingRoot; also KernelRoot for the "
            "full-template wrapper path)"
        ),
    )
    result.add_argument(
        "--kernel-root",
        type=Path,
        help="exact trusted product root (normally supplied by scripts/contextos.sh)",
    )
    result.add_argument(
        "--context-root",
        type=Path,
        help="exact attached ContextRoot; requires --working-root and --kernel-root",
    )
    result.add_argument(
        "--working-root",
        type=Path,
        help="exact attached application root; requires --context-root and --kernel-root",
    )
    result.add_argument("--version", action="version", version=__version__)
    commands = result.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="Read workspace continuity as structured data")
    start.add_argument("--now", help="ISO-8601 timestamp for deterministic runs")
    start.add_argument("--format", choices=("json", "markdown"), default="json")
    start.add_argument("--briefing", action="store_true", help="Include source-attributed excerpts in JSON (Markdown includes them automatically)")
    start.add_argument("--source", action="append", default=[], help="Explicit repository-relative Markdown task source (repeatable)")

    history = commands.add_parser("history", help="Read local context change receipts")
    history.add_argument("--format", choices=("json", "markdown"), default="markdown")
    history.add_argument("--limit", type=int, default=10)
    history.add_argument("--path", help="Filter by one repository-relative changed path")
    history.add_argument("--details", action="store_true", help="Include available proposal diffs after checking their digest binding")

    propose = commands.add_parser("propose", help="Create a reviewable lifecycle proposal")
    propose.add_argument("workflow", choices=("setup", "update", "end"))
    propose.add_argument("--input", type=Path, required=True, help="Reviewed JSON payload")
    propose.add_argument("--now", help="ISO-8601 timestamp for deterministic runs")

    apply = commands.add_parser("apply", help="Apply one exact host-confirmed proposal")
    apply.add_argument("proposal", type=Path)
    apply.add_argument("--confirm", required=True, help="Exact proposal digest printed by propose")
    apply.add_argument("--runtime", metavar="RUNTIME", required=True)

    install = commands.add_parser(
        "install", help="Record local onboarding for one runtime and print host setup steps"
    )
    install.add_argument("--runtime", metavar="RUNTIME", required=True)

    agent = commands.add_parser(
        "agent", help="Inspect or propose changes to tracked agent activation"
    )
    agent_commands = agent.add_subparsers(dest="agent_command", required=True)
    agent_commands.add_parser(
        "list", help="List registered runtimes and their tracked/local status"
    )
    for agent_command in ("add", "enable", "disable"):
        activation = agent_commands.add_parser(
            agent_command,
            help=(
                "Create an exact proposal to disable one tracked runtime"
                if agent_command == "disable"
                else "Create an exact proposal to enable one bundled runtime"
            ),
        )
        activation.add_argument("--runtime", metavar="RUNTIME", required=True)
        activation.add_argument(
            "--now", help="ISO-8601 timestamp for deterministic proposal IDs"
        )

    project = commands.add_parser(
        "project", help="Create or inspect an external-project attachment"
    )
    project_commands = project.add_subparsers(dest="project_command", required=True)
    attach = project_commands.add_parser(
        "attach", help="Propose an exact tracked identity and machine-local binding"
    )
    attach.add_argument("--id", dest="project_id", required=True)
    attach.add_argument("--now", help="ISO-8601 timestamp for deterministic proposal IDs")
    rebind = project_commands.add_parser(
        "rebind", help="Propose a new local path for an existing tracked project"
    )
    rebind.add_argument("--id", dest="project_id", required=True)
    rebind.add_argument("--now", help="ISO-8601 timestamp for deterministic proposal IDs")
    project_commands.add_parser("show", help="Validate and show the active attachment")

    diagnose = commands.add_parser(
        "doctor", help="Check workspace health with tracked agent-set awareness"
    )
    diagnose_selection = diagnose.add_mutually_exclusive_group()
    diagnose_selection.add_argument("--runtime", metavar="RUNTIME")
    diagnose_selection.add_argument(
        "--all", action="store_true", help="Strictly validate every shipped runtime"
    )

    workspace = commands.add_parser(
        "workspace", help="Inspect tracked workspace intent or preview migration"
    )
    workspace_commands = workspace.add_subparsers(
        dest="workspace_command", required=True
    )
    workspace_commands.add_parser(
        "show", help="Show effective tracked workspace configuration and precedence"
    )
    migrate = workspace_commands.add_parser(
        "migrate", help="Preview canonical tracked JSON without writing it"
    )
    selection = migrate.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--agents", action="append", help="Comma-separated runtime ids, or none for core-only"
    )
    selection.add_argument(
        "--agent",
        action="append",
        help="Deprecated singleton compatibility alias; use --agents",
    )
    propose_migration = workspace_commands.add_parser(
        "propose-migration",
        help="Create a digest-bound proposal to write JSON and retire legacy YAML",
    )
    proposal_selection = propose_migration.add_mutually_exclusive_group(required=True)
    proposal_selection.add_argument(
        "--agents", action="append", help="Comma-separated runtime ids, or none for core-only"
    )
    proposal_selection.add_argument(
        "--agent",
        action="append",
        help="Deprecated singleton compatibility alias; use --agents",
    )
    propose_migration.add_argument(
        "--now", help="ISO-8601 timestamp for deterministic proposal IDs"
    )
    propose_setup = workspace_commands.add_parser(
        "propose-setup",
        help="Create an additive digest-bound setup proposal for tracked agents",
    )
    setup_selection = propose_setup.add_mutually_exclusive_group(required=True)
    setup_selection.add_argument(
        "--agents", action="append", help="Comma-separated runtime ids, or none for core-only"
    )
    setup_selection.add_argument(
        "--agent",
        action="append",
        help="Deprecated singleton compatibility alias; use --agents",
    )
    propose_setup.add_argument(
        "--now", help="ISO-8601 timestamp for deterministic proposal IDs"
    )
    workspace_commands.add_parser(
        "migrate-local-runtime",
        help="Atomically copy legacy local runtime state into hosts.json",
    )
    for guided_name, guided_help in (
        ("init", "Propose a schema-v2 composition into a clean target"),
        ("update", "Propose runtime, profile, extras, or bundle changes"),
        ("reconcile", "Propose convergence to existing schema-v2 intent"),
    ):
        guided = workspace_commands.add_parser(guided_name, help=guided_help)
        guided.add_argument("--target", type=Path, required=True)
        guided.add_argument("--lock", type=Path, required=True)
        guided.add_argument("--source", type=Path, required=True)
        guided.add_argument("--expect-sha256", required=True)
        guided.add_argument(
            "--source-mode", choices=("git-index", "directory"), default="directory"
        )
        guided.add_argument("--now", help="ISO-8601 timestamp for deterministic proposal IDs")
        if guided_name in {"init", "update"}:
            guided.add_argument(
                "--agents", required=True,
                help="Comma-separated runtime ids, or none for core-only",
            )
            guided.add_argument(
                "--profile", choices=("selected", "full-template"), required=True
            )
            guided.add_argument(
                "--extras", default="none",
                help="Comma-separated optional component roots, or none",
            )
        if guided_name in {"update", "reconcile"}:
            guided.add_argument("--current-lock", type=Path)
            guided.add_argument("--current-source", type=Path)
            guided.add_argument("--expect-current-sha256")
            guided.add_argument(
                "--current-source-mode",
                choices=("git-index", "directory"),
                default="directory",
            )

    board = commands.add_parser(
        "board", help="Coordination board operations (contract: coordination/README.md)"
    )
    board_commands = board.add_subparsers(dest="board_command", required=True)
    board_bootstrap = board_commands.add_parser(
        "bootstrap", help="Create the coordination ref on the remote if absent"
    )
    board_bootstrap.add_argument("--now")
    board_post = board_commands.add_parser("post", help="Validate and publish one board message")
    board_post.add_argument("--runtime", required=True)
    board_post.add_argument("--from", dest="sender", required=True, help="runtime/role of the posting run")
    board_post.add_argument("--audience", required=True, help="all, an enumerated role, or runtime/run-id")
    board_post.add_argument("--kind", required=True, choices=["note", "alert", "query", "handoff"])
    board_post.add_argument("--re", dest="re_ref", help="commit:path reference, optional #sha256:<hex>")
    board_post.add_argument("--expires", help="UTC ISO expiry; defaults to now + 7 days")
    board_post.add_argument("--body", required=True, help="message body, or '-' to read stdin")
    board_post.add_argument("--now")
    board_claim = board_commands.add_parser("claim", help="Publish an advisory claim")
    board_claim.add_argument("--runtime", required=True)
    board_claim.add_argument("--task", required=True, help="stable reference: commit:path or a task id")
    board_claim.add_argument("--owner", required=True, help="runtime/run-id")
    board_claim.add_argument("--lease-expires", dest="lease_expires", help="UTC ISO; defaults to now + 7 days")
    board_claim.add_argument("--now")
    board_release = board_commands.add_parser(
        "release", help="Release a claim, optionally handing off atomically in the same commit"
    )
    board_release.add_argument("--runtime", required=True)
    board_release.add_argument("--claim", dest="claim_id", required=True)
    board_release.add_argument("--then-claim-task", dest="then_claim_task")
    board_release.add_argument("--then-claim-owner", dest="then_claim_owner")
    board_release.add_argument("--now")
    board_sync = board_commands.add_parser(
        "sync", help="Fetch and surface unexpired messages addressed to this run"
    )
    board_sync.add_argument("--runtime", required=True)
    board_sync.add_argument("--role", required=True)
    board_sync.add_argument("--run-id", dest="run_id", required=True)
    board_sync.add_argument("--cursor-file", dest="cursor_file", type=Path)
    board_sync.add_argument("--now")
    board_compact = board_commands.add_parser(
        "compact", help="Report expired messages and stale claims; --apply deletes expired messages"
    )
    board_compact.add_argument("--apply", action="store_true")
    board_compact.add_argument("--now")
    board_promote = board_commands.add_parser(
        "promote", help="Create a source-bound proposal for one live message"
    )
    board_promote.add_argument("--message", required=True, help="exact message id")
    board_promote.add_argument(
        "--target", required=True,
        help="explicit decisions.md or today's session path",
    )
    board_promote.add_argument(
        "--input", type=Path, required=True, help="reviewed promotion JSON payload"
    )
    board_promote.add_argument("--now")
    board_validate = board_commands.add_parser("validate", help="Validate the fetched coordination tree")
    board_validate.add_argument("--now")

    hook = commands.add_parser("hook", help="Run a normalized read-only lifecycle hook check")
    hook.add_argument("event", choices=("session-start", "pre-write"))
    hook.add_argument("--runtime", metavar="RUNTIME", required=True)
    hook.add_argument("--surface", metavar="SURFACE")

    bundle = commands.add_parser(
        "bundle", help="Generate, verify, or plan from immutable offline bundles"
    )
    bundle_commands = bundle.add_subparsers(dest="bundle_command", required=True)
    generate_bundle = bundle_commands.add_parser(
        "generate", help="Print a detached lock for one explicit local source"
    )
    generate_bundle.add_argument("--source", type=Path, required=True)
    generate_bundle.add_argument("--name", required=True)
    generate_bundle.add_argument("--bundle-version", required=True)
    check_bundle = bundle_commands.add_parser(
        "check", help="Verify a caller-pinned lock against local source bytes"
    )
    check_bundle.add_argument("--lock", type=Path, required=True)
    check_bundle.add_argument("--source", type=Path, required=True)
    check_bundle.add_argument("--expect-sha256", required=True)
    check_bundle.add_argument(
        "--source-mode", choices=("git-index", "directory"), default="directory"
    )
    plan_bundle = bundle_commands.add_parser(
        "plan", help="Print a deterministic read-only structural plan"
    )
    propose_bundle = bundle_commands.add_parser(
        "propose", help="Create a digest-bound materialization proposal"
    )
    compose_bundle = bundle_commands.add_parser(
        "compose", help="Create a first-install proposal for a clean target"
    )
    apply_bundle = bundle_commands.add_parser(
        "apply", help="Apply a materialization proposal to its explicit target"
    )
    apply_bundle.add_argument("--target", type=Path, required=True)
    apply_bundle.add_argument("--proposal", type=Path, required=True)
    apply_bundle.add_argument("--confirm", required=True)
    apply_bundle.add_argument("--runtime", default="generic")
    for command in (plan_bundle, propose_bundle, compose_bundle):
        command.add_argument("--lock", type=Path, required=True)
        command.add_argument("--source", type=Path, required=True)
        command.add_argument("--expect-sha256", required=True)
        command.add_argument(
            "--source-mode", choices=("git-index", "directory"), default="directory"
        )
        command.add_argument("--target", type=Path, required=True)
        command.add_argument("--workspace-config", type=Path, required=True)
        command.add_argument("--expect-config-sha256", required=True)
        command.add_argument("--components", required=True)
        command.add_argument("--current-lock", type=Path)
        command.add_argument("--current-source", type=Path)
        command.add_argument("--expect-current-sha256")
        command.add_argument(
            "--current-source-mode", choices=("git-index", "directory"),
            default="directory",
        )
        command.add_argument("--current-components")
    propose_bundle.add_argument("--now", help="ISO-8601 timestamp for deterministic proposal IDs")
    compose_bundle.add_argument("--workspace-config-input", type=Path, required=True)
    compose_bundle.add_argument("--now", help="ISO-8601 timestamp for deterministic proposal IDs")
    return result


def emit(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _resolve_cli_roles(args: argparse.Namespace) -> RootRoles:
    split_requested = args.context_root is not None or args.working_root is not None
    if args.root is not None and split_requested:
        raise ContextOSError("--root cannot be combined with split-root options")
    if split_requested:
        if args.kernel_root is None:
            raise ContextOSError(
                "split attachment requires --kernel-root, --context-root, and --working-root"
            )
        try:
            return resolve_root_roles(
                kernel_root=args.kernel_root,
                context_root=args.context_root,
                working_root=args.working_root,
            )
        except AttachmentError as exc:
            raise ContextOSError(str(exc)) from exc
    root = discover_root(args.root if args.root is not None else args.kernel_root)
    kernel = args.kernel_root.resolve() if args.kernel_root is not None else root
    try:
        return resolve_root_roles(kernel_root=kernel, legacy_root=root)
    except AttachmentError as exc:
        raise ContextOSError(str(exc)) from exc


def component_selection(raw: str, field: str) -> list[str]:
    values = [item.strip() for item in raw.split(",")]
    if not values or any(not item for item in values):
        raise BundleError(f"{field}: must be a comma-separated component list")
    return values


def _guided_extras(raw: str) -> list[str]:
    return [] if raw.strip() == "none" else component_selection(raw, "extras")


def _guided_report(
    target: Path, proposal_path: Path, proposal: dict[str, object]
) -> dict[str, object]:
    authorization = proposal["authorization"]
    assert isinstance(authorization, dict)
    plan = authorization["plan"]
    assert isinstance(plan, dict)
    return {
        "schema_version": 1,
        "proposal": proposal_path.relative_to(target).as_posix(),
        "proposal_id": proposal["proposal_id"],
        "proposal_digest": proposal["proposal_digest"],
        "plan_digest": plan["plan_digest"],
        "desired_components": plan["desired_components"],
        "current_components": plan["current_components"],
        "intended_workspace": plan["intended_workspace"],
        "changes": [
            {
                "action": change["action"],
                "path": change["path"],
                "owner": change["authorization"]["owner"],
                "policy": change["authorization"]["policy"],
                "summary": change["diff"].strip(),
            }
            for change in proposal["changes"]
        ],
        "writes": True,
        "applied": False,
        "next": (
            "review this single structural proposal, then run bundle apply with "
            "the exact proposal digest"
        ),
    }


def _load_guided_installed_state(target: Path) -> dict[str, object] | None:
    path = target / INSTALLED_STATE_PATH
    if not path.exists():
        return None
    try:
        raw, _metadata = read_regular_file_snapshot(
            path, subject="installed bundle state"
        )
        return validate_installed_state(
            strict_json_loads(raw.decode("utf-8"), source=INSTALLED_STATE_PATH)
        )
    except (OSError, UnicodeError, WorkspaceConfigError, InstalledStateError) as exc:
        raise BundleError(str(exc)) from exc


def _guided_workspace_main(args: argparse.Namespace) -> int:
    target = args.target.absolute().resolve()
    if not target.is_dir():
        raise BundleError("target must be an existing local directory")
    candidate = verify_bundle(
        args.lock,
        args.source,
        expected_sha256=args.expect_sha256,
        source_mode=args.source_mode,
        retain_paths=(),
    )
    component_ids = [item["id"] for item in candidate.manifest["components"]]
    if args.workspace_command == "init":
        agents = parse_agent_selection(
            args.agents, known_runtime_ids=sorted(candidate.runtimes)
        )
        assert agents is not None
        paths = dict(DEFAULT_PATHS)
        legacy_path = target / "workspace.yaml"
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
                    "workspace.yaml cannot be migrated losslessly: "
                    + "; ".join(legacy.issues)
                )
            paths.update(legacy.values)
        intended = {
            "schema_version": WORKSPACE_SCHEMA_VERSION,
            "agents": agents,
            "composition": {
                "profile": args.profile,
                "extras": _guided_extras(args.extras),
            },
            "paths": paths,
            "template": {
                "source": candidate.name,
                "version": candidate.version,
                "bundle_sha256": candidate.digest,
            },
        }
        desired = desired_component_closure(
            intended, candidate.manifest, candidate.runtimes
        )
        proposal_path, proposal = create_guided_composition_proposal(
            target_root=target,
            workspace_config=intended,
            candidate=candidate,
            desired_components=desired,
            now=parse_now(args.now),
        )
        emit(_guided_report(target, proposal_path, proposal))
        return 0

    config_path = target / "contextos.workspace.json"
    try:
        current_config, _canonical = load_workspace_config(
            config_path,
            root=target,
            known_runtime_ids=sorted(candidate.runtimes),
            known_component_ids=component_ids,
        )
    except WorkspaceConfigError as exc:
        raise BundleError(str(exc)) from exc
    legacy_v1 = current_config["schema_version"] != WORKSPACE_SCHEMA_VERSION
    if legacy_v1 and args.workspace_command == "reconcile":
        raise BundleError("schema v1 must be migrated with workspace update")
    if legacy_v1 and args.profile != "full-template":
        raise BundleError(
            "schema-v1 migration must first preserve the full-template profile"
        )
    installed = _load_guided_installed_state(target)
    current_values = (
        args.current_lock,
        args.current_source,
        args.expect_current_sha256,
    )
    if any(value is not None for value in current_values) and not all(
        value is not None for value in current_values
    ):
        raise BundleError(
            "current bundle inputs are all required together: --current-lock, "
            "--current-source, --expect-current-sha256"
        )
    current = None
    current_components: list[str] = []
    if installed is not None:
        current_components = list(installed["components"])
        installed_digest = installed["bundle"]["sha256"]
        if installed_digest == candidate.digest:
            current = candidate
        elif args.current_lock is not None:
            current = verify_bundle(
                args.current_lock,
                args.current_source,
                expected_sha256=args.expect_current_sha256,
                source_mode=args.current_source_mode,
                role="current",
                retain_paths=(),
            )
        else:
            raise BundleError(
                "installed bundle differs from the candidate; pinned current bundle inputs are required"
            )
    elif args.workspace_command == "update" and not legacy_v1:
        raise BundleError(
            "workspace update requires installed state; run workspace reconcile first"
        )

    if args.workspace_command == "reconcile":
        intended = current_config
        if intended["template"] != {
            "source": candidate.name,
            "version": candidate.version,
            "bundle_sha256": candidate.digest,
        }:
            raise BundleError("reconcile candidate does not match the tracked bundle pin")
    else:
        agents = parse_agent_selection(
            args.agents, known_runtime_ids=sorted(candidate.runtimes)
        )
        assert agents is not None
        intended = {
            **current_config,
            "schema_version": WORKSPACE_SCHEMA_VERSION,
            "agents": agents,
            "composition": {
                "profile": args.profile,
                "extras": _guided_extras(args.extras),
            },
            "template": {
                "source": candidate.name,
                "version": candidate.version,
                "bundle_sha256": candidate.digest,
            },
        }
        intended.pop("mode", None)
    desired = desired_component_closure(
        intended, candidate.manifest, candidate.runtimes
    )
    proposal_path, proposal = create_materialization_proposal(
        target_root=target,
        workspace_config_path=config_path,
        expected_config_sha256=sha256_bytes(config_path.read_bytes()),
        candidate=candidate,
        desired_components=desired,
        current=current,
        current_components=current_components,
        intended_workspace=intended,
        now=parse_now(args.now),
    )
    emit(_guided_report(target, proposal_path, proposal))
    return 0


def _bundle_main(args: argparse.Namespace) -> int:
    if args.bundle_command == "apply":
        root = args.target.absolute().resolve()
        proposal = args.proposal if args.proposal.is_absolute() else root / args.proposal
        if read_json(proposal).get("operation") != MATERIALIZE_OPERATION:
            raise BundleError("bundle apply accepts only materialization proposals")
        receipt_path, receipt = apply_proposal(
            root, proposal, args.confirm, args.runtime
        )
        validation = doctor(root)
        emit({
            "receipt": receipt_path.relative_to(root).as_posix(),
            **receipt,
            "validation": validation,
        })
        return 0
    if args.bundle_command == "generate":
        lock = create_bundle_lock(
            args.source,
            name=args.name,
            version=args.bundle_version,
            source_mode="git-index",
        )
        print(json.dumps(lock, indent=2, ensure_ascii=False))
        return 0
    candidate = verify_bundle(
        args.lock, args.source, expected_sha256=args.expect_sha256,
        source_mode=args.source_mode,
        retain_paths=(),
    )
    if args.bundle_command == "check":
        emit({
            "schema_version": candidate.lock["schema_version"],
            "bundle": {"name": candidate.name, "version": candidate.version},
            "bundle_sha256": candidate.digest,
            "source_git_commit": candidate.lock["bundle"]["source_git_commit"],
            "files": len(candidate.records),
            "source_mode": candidate.source_mode,
            "executable_modes_verified": candidate.mode_verified,
            "unlocked_files_ignored": True,
            "writes": False,
        })
        return 0
    current_values = (
        args.current_lock,
        args.current_source,
        args.expect_current_sha256,
        args.current_components,
    )
    if any(value is not None for value in current_values) and not all(
        value is not None for value in current_values
    ):
        raise BundleError(
            "current_bundle: --current-lock, --current-source, "
            "--expect-current-sha256, and --current-components are all required together"
        )
    current = None
    current_components: list[str] = []
    if args.current_lock is not None:
        current = verify_bundle(
            args.current_lock,
            args.current_source,
            expected_sha256=args.expect_current_sha256,
            source_mode=args.current_source_mode,
            role="current",
            retain_paths=(),
        )
        current_components = component_selection(
            args.current_components, "current_components"
        )
    desired_components = component_selection(args.components, "components")
    if args.bundle_command == "compose":
        if current is not None or current_components:
            raise BundleError("compose: current bundle inputs are not allowed")
        proposal_path, proposal = create_composition_proposal(
            target_root=args.target,
            workspace_config_path=args.workspace_config,
            workspace_config_input_path=args.workspace_config_input,
            expected_config_input_sha256=args.expect_config_sha256,
            candidate=candidate,
            desired_components=desired_components,
            now=parse_now(args.now),
        )
        emit({
            "proposal": proposal_path.relative_to(args.target.absolute()).as_posix(),
            "proposal_id": proposal["proposal_id"],
            "proposal_digest": proposal["proposal_digest"],
            "plan_digest": proposal["authorization"]["plan"]["plan_digest"],
            "source_mode": candidate.source_mode,
            "source_git_commit": candidate.lock["bundle"]["source_git_commit"],
            "changes": [
                {
                    "action": change["action"],
                    "path": change["path"],
                    "owner": change["authorization"]["owner"],
                    "policy": change["authorization"]["policy"],
                    "before_sha256_raw": change["before_raw_sha256"],
                    "after_sha256_raw": change["after_raw_sha256"],
                    "summary": change["diff"].strip(),
                }
                for change in proposal["changes"]
            ],
            "writes": True,
            "applied": False,
        })
        return 0
    if args.bundle_command == "propose":
        proposal_path, proposal = create_materialization_proposal(
            target_root=args.target,
            workspace_config_path=args.workspace_config,
            expected_config_sha256=args.expect_config_sha256,
            candidate=candidate,
            desired_components=desired_components,
            current=current,
            current_components=current_components,
            now=parse_now(args.now),
        )
        emit({
            "proposal": proposal_path.relative_to(args.target.absolute()).as_posix(),
            "proposal_id": proposal["proposal_id"],
            "proposal_digest": proposal["proposal_digest"],
            "plan_digest": proposal["authorization"]["plan"]["plan_digest"],
            "source_mode": candidate.source_mode,
            "source_git_commit": candidate.lock["bundle"]["source_git_commit"],
            "changes": [
                {
                    "action": change["action"],
                    "path": change["path"],
                    "owner": change["authorization"]["owner"],
                    "policy": change["authorization"]["policy"],
                    "before_sha256_raw": change["before_raw_sha256"],
                    "after_sha256_raw": change["after_raw_sha256"],
                    "summary": change["diff"].strip(),
                }
                for change in proposal["changes"]
            ],
            "writes": True,
            "applied": False,
        })
        return 0
    plan = create_structural_plan(
        target_root=args.target,
        workspace_config_path=args.workspace_config,
        expected_config_sha256=args.expect_config_sha256,
        candidate=candidate,
        desired_components=desired_components,
        current=current,
        current_components=current_components,
    )
    emit({**plan, "writes": False})
    return 0


def selected_workspace_agents(args: argparse.Namespace, root: Path) -> list[str]:
    selections = args.agents if args.agents is not None else args.agent
    if len(selections) != 1:
        raise ContextOSError("workspace migration selection may be specified only once")
    raw_selection = selections[0]
    if args.agent is not None and "," in raw_selection:
        raise ContextOSError(
            "--agent is a deprecated singleton alias and accepts exactly one runtime id"
        )
    selected_agents = parse_agent_selection(
        raw_selection, known_runtime_ids=runtime_ids(root)
    )
    if selected_agents is None:
        raise ContextOSError("workspace migration requires explicit agents")
    return selected_agents


def workspace_proposal_report(
    root: Path,
    path: Path | None,
    document: dict[str, object] | None,
    notices: list[str],
) -> dict[str, object]:
    if path is None or document is None:
        return {
            "schema_version": 1,
            "writes": False,
            "action": "noop",
            "proposal": None,
            "proposal_id": None,
            "proposal_digest": None,
            "changes": [],
            "notices": notices,
        }
    changes = document["changes"]
    source_hashes = document["source_hashes"]
    assert isinstance(changes, list)
    assert isinstance(source_hashes, dict)
    return {
        "schema_version": document["schema_version"],
        "writes": False,
        "action": "proposed",
        "workflow": document["workflow"],
        "operation": document["operation"],
        "proposal": path.relative_to(root).as_posix(),
        "proposal_id": document["proposal_id"],
        "proposal_digest": document["proposal_digest"],
        "changes": [
            {
                "action": item["action"],
                "path": item["path"],
                "owner": item["authorization"]["owner"],
                "policy": item["authorization"]["policy"],
                "before_sha256_raw": item["before_raw_sha256"],
                "after_sha256_raw": item["after_raw_sha256"],
                "diff": item["diff"],
            }
            for item in changes
        ],
        "authorization_inputs": [
            {"path": source, "sha256_raw": digest}
            for source, digest in source_hashes.items()
        ],
        "source_git_head": document["source_git_head"],
        "authorization": document["authorization"],
        "notices": notices,
    }


def _board_roles(root: Path) -> list[str] | None:
    roles_file = root / "state" / "roles.md"
    if not roles_file.exists():
        return None
    roles: list[str] = []
    for line in roles_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            roles.append(stripped[2:].strip().lower())
    return roles or None


def _print_report(text: str) -> None:
    # Redirected Windows terminals can use a legacy encoding. Preserve readable
    # output with explicit Unicode escapes instead of failing the whole report.
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(text.encode(encoding, errors="backslashreplace").decode(encoding))


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    hook_output: str | None = None
    try:
        if args.command == "bundle":
            return _bundle_main(args)
        if args.command == "workspace" and args.workspace_command in {
            "init", "update", "reconcile"
        }:
            return _guided_workspace_main(args)
        roles = _resolve_cli_roles(args)
        root = roles.context_root
        split_mode = args.context_root is not None or args.working_root is not None
        if split_mode and args.command not in {
            "start", "history", "propose", "apply", "hook", "project", "doctor"
        }:
            raise ContextOSError(
                f"{args.command} is not yet a split-root lifecycle surface"
            )
        if split_mode and args.command not in {"doctor", "apply"} and not (
            args.command == "project" and args.project_command in {"attach", "rebind"}
        ):
            load_project_attachment(roles)
        if args.command == "start":
            if args.briefing or args.source or args.format == "markdown":
                report = briefing_report(root, parse_now(args.now), sources=args.source, roles=roles if split_mode else None)
            else:
                report = start_report(root, parse_now(args.now), roles=roles if split_mode else None)
            _print_report(render_briefing(report)) if args.format == "markdown" else emit(report)
        elif args.command == "history":
            report = history_report(root, limit=args.limit, path=args.path, details=args.details)
            _print_report(render_history(report)) if args.format == "markdown" else emit(report)
        elif args.command == "propose":
            path, document = create_proposal(root, args.workflow, read_json(args.input), parse_now(args.now))
            emit({
                "proposal": path.relative_to(root).as_posix(),
                "proposal_id": document["proposal_id"],
                "proposal_digest": document["proposal_digest"],
                "changes": [{"path": item["path"], "diff": item["diff"]} for item in document["changes"]],
            })
        elif args.command == "apply":
            proposal = args.proposal if args.proposal.is_absolute() else root / args.proposal
            if split_mode and read_json(proposal).get("operation") not in PROJECT_OPERATIONS:
                load_project_attachment(roles)
            receipt_path, receipt = apply_proposal(
                root,
                proposal,
                args.confirm,
                args.runtime,
                roles=roles if split_mode else None,
            )
            emit({"receipt": receipt_path.relative_to(root).as_posix(), **receipt})
        elif args.command == "project":
            if not split_mode:
                raise ContextOSError(
                    "project attachment requires exact --kernel-root, --context-root, and --working-root"
                )
            if args.project_command in {"attach", "rebind"}:
                path, document = create_project_attachment_proposal(
                    roles,
                    args.project_id,
                    parse_now(args.now),
                    rebind=args.project_command == "rebind",
                )
                emit({
                    "proposal": path.relative_to(root).as_posix(),
                    "proposal_id": document["proposal_id"],
                    "proposal_digest": document["proposal_digest"],
                    "operation": document["operation"],
                    "changes": [
                        {"path": item["path"], "diff": item["diff"]}
                        for item in document["changes"]
                    ],
                    "working_root_access": "read-only",
                    "nonexclusive_claim": True,
                })
            else:
                manifest, binding = load_project_attachment(roles)
                emit({
                    "schema_version": 1,
                    "root_roles": {
                        "kernel_root": str(roles.kernel_root),
                        "context_root": str(roles.context_root),
                        "working_root": str(roles.working_root),
                    },
                    "project": manifest,
                    "binding": binding,
                    "working_root_access": "read-only",
                    "nonexclusive_claim": True,
                })
        elif args.command == "install":
            path, manifest = install_runtime(root, args.runtime)
            relative = path.relative_to(root).as_posix()
            emit({"host_state": relative, "runtime_file": relative, **manifest})
        elif args.command == "agent":
            if args.agent_command == "list":
                emit(agent_list_report(root))
            else:
                enabled = args.agent_command in {"add", "enable"}
                path, document = create_agent_activation_proposal(
                    root, args.runtime, enabled, parse_now(args.now)
                )
                notices = [
                    "agent add is an alias for agent enable"
                    if args.agent_command == "add"
                    else "agent disable changes tracked intent only; bundled files remain"
                    if not enabled
                    else "agent enable changes tracked intent only",
                ]
                emit(workspace_proposal_report(root, path, document, notices))
        elif args.command == "doctor":
            report = (
                project_attachment_doctor(
                    roles, args.runtime, all_runtimes=args.all
                )
                if split_mode
                else doctor(root, args.runtime, all_runtimes=args.all)
            )
            emit(report)
            return 1 if report["status"] == "fail" else 0
        elif args.command == "workspace":
            if args.workspace_command == "show":
                emit(workspace_resolution_report(root))
            elif args.workspace_command == "migrate":
                selected_agents = selected_workspace_agents(args, root)
                report = plan_workspace_migration(root, selected_agents)
                if args.agent is not None:
                    report["notices"].append(
                        "--agent is a deprecated singleton compatibility alias; use --agents"
                    )
                emit(report)
            elif args.workspace_command == "propose-migration":
                selected_agents = selected_workspace_agents(args, root)
                path, document = create_workspace_migration_proposal(
                    root, selected_agents, parse_now(args.now)
                )
                notices = []
                if args.agent is not None:
                    notices.append(
                        "--agent is a deprecated singleton compatibility alias; use --agents"
                    )
                emit(workspace_proposal_report(root, path, document, notices))
            elif args.workspace_command == "propose-setup":
                selected_agents = selected_workspace_agents(args, root)
                path, document = create_workspace_setup_proposal(
                    root, selected_agents, parse_now(args.now)
                )
                notices = [
                    "setup selection is additive and never removes configured agents"
                ]
                if args.agent is not None:
                    notices.append(
                        "--agent is a deprecated singleton compatibility alias; use --agents"
                    )
                emit(workspace_proposal_report(root, path, document, notices))
            elif args.workspace_command == "migrate-local-runtime":
                path, state, changed, migrated_runtime = migrate_legacy_runtime_state(root)
                emit({
                    "host_state": path.relative_to(root).as_posix(),
                    "changed": changed,
                    "migrated_runtime": migrated_runtime,
                    "legacy_runtime_retained": False,
                    **state,
                })
        elif args.command == "board":
            now = parse_now(getattr(args, "now", None))
            if args.board_command == "bootstrap":
                emit(bootstrap_board(root, now=now))
            elif args.board_command == "post":
                body = sys.stdin.read() if args.body == "-" else args.body
                emit(post_message(
                    root, sender=args.sender, audience=args.audience, kind=args.kind,
                    body=body, re_ref=args.re_ref, expires=args.expires,
                    runtime=args.runtime, now=now,
                ))
            elif args.board_command == "claim":
                emit(create_claim(
                    root, task=args.task, owner=args.owner,
                    lease_expires=args.lease_expires, runtime=args.runtime, now=now,
                ))
            elif args.board_command == "release":
                then_claim = None
                if args.then_claim_task or args.then_claim_owner:
                    if not (args.then_claim_task and args.then_claim_owner):
                        raise ContextOSError(
                            "--then-claim-task and --then-claim-owner are required together"
                        )
                    then_claim = {"task": args.then_claim_task, "owner": args.then_claim_owner}
                emit(release_claim(
                    root, claim_id=args.claim_id, then_claim=then_claim,
                    runtime=args.runtime, now=now,
                ))
            elif args.board_command == "sync":
                cursor = args.cursor_file or (
                    root / ".context-os" / "coordination" / f"cursor-{args.runtime}.json"
                )
                emit(sync_board(
                    root, runtime=args.runtime, role=args.role, run_id=args.run_id,
                    cursor_file=cursor, roles=_board_roles(root), now=now,
                ))
            elif args.board_command == "compact":
                emit(compact_board(root, apply=args.apply, now=now))
            elif args.board_command == "promote":
                path, document = propose_promotion(
                    root,
                    message_id=args.message,
                    target=args.target,
                    payload=read_json(args.input),
                    now=now,
                )
                emit({
                    "proposal": path.relative_to(root).as_posix(),
                    "proposal_id": document["proposal_id"],
                    "proposal_digest": document["proposal_digest"],
                    "source": document["source"],
                    "changes": [
                        {"path": item["path"], "diff": item["diff"]}
                        for item in document["changes"]
                    ],
                })
            elif args.board_command == "validate":
                emit(validate_board(root, roles=_board_roles(root), now=now))
        elif args.command == "hook":
            product_root = roles.kernel_root if split_mode else root
            hook_manifest = runtime_manifest(product_root, args.runtime, check_paths=False)
            surface_outputs = {
                surface.get("hook_output")
                for surface in hook_manifest["surfaces"].values()
            }
            if len(surface_outputs) == 1:
                hook_output = next(iter(surface_outputs))
            hook_output = runtime_surface(hook_manifest, args.surface).get("hook_output")
            raw = sys.stdin.read().strip()
            payload = json.loads(raw) if raw else {}
            if not isinstance(payload, dict):
                raise ContextOSError("hook input must be a JSON object")
            report = hook_report(
                root, args.event, payload, roles=roles if split_mode else None
            )
            messages = [item["message"] for item in report["findings"]]
            rendered = render_hook_payload(hook_output, messages)
            if rendered is not None:
                emit(rendered)
        return 0
    except (
        ContextOSError,
        BundleError,
        WorkspaceConfigError,
        WorkspaceCompositionError,
        AttachmentError,
        json.JSONDecodeError,
        OSError,
        UnicodeError,
    ) as exc:
        if getattr(args, "command", None) == "hook":
            message = f"Context OS advisory hook could not run: {exc}"
            # If no validated descriptor established a host protocol, silence
            # is safer than emitting another runtime's incompatible envelope.
            rendered = render_hook_payload(hook_output, [message])
            if rendered is not None:
                emit(rendered)
            return 0
        print(f"context-os: {exc}", file=sys.stderr)
        return 2
