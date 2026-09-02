#!/usr/bin/env python3
"""Build and verify deterministic, full-closure Context OS release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contextos.bundle_schema import (  # noqa: E402
    BundleError,
    create_bundle_lock,
    load_bundle_lock,
    verify_bundle,
)
from contextos.component_schema import portable_path_identity  # noqa: E402
from contextos.primitives import git_environment  # noqa: E402


GENERATOR_VERSION = 1
EXAMPLE_BUNDLE_SHA256 = "0" * 64
TEMPLATE_NAME = "agent-context-os-template"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CHECKSUM_RE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9._-]+)$")


class ReleaseArtifactError(ValueError):
    """Raised when release identity or artifact bytes fail closed."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _git(root: Path, *arguments: str) -> bytes:
    try:
        return subprocess.run(
            ["git", *arguments], cwd=root, check=True, capture_output=True,
            env=git_environment(),
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", b"")
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace").strip()
        raise ReleaseArtifactError(
            "git " + " ".join(arguments) + " failed" + (f": {detail}" if detail else "")
        ) from exc


def _require_clean_repository(root: Path, expected_commit: str) -> int:
    if not COMMIT_RE.fullmatch(expected_commit):
        raise ReleaseArtifactError("commit must be one exact lowercase 40-hex Git commit")
    actual = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    if actual != expected_commit:
        raise ReleaseArtifactError(f"HEAD is {actual}, expected {expected_commit}")
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise ReleaseArtifactError("release source must have a completely clean worktree and index")
    if _git(root, "ls-files", "--stage").count(b"\n") == 0:
        raise ReleaseArtifactError("release source Git index is empty")
    submodules = _git(root, "ls-files", "--stage").splitlines()
    if any(line.startswith(b"160000 ") for line in submodules):
        raise ReleaseArtifactError("release source must not contain Git submodules")
    epoch_text = _git(root, "show", "-s", "--format=%ct", "HEAD").decode("ascii").strip()
    try:
        epoch = int(epoch_text)
    except ValueError as exc:
        raise ReleaseArtifactError("source commit timestamp is not an integer") from exc
    if epoch < 0:
        raise ReleaseArtifactError("source commit timestamp must not be negative")
    return epoch


def _require_release_identity(root: Path, version: str, tag: str) -> None:
    if not VERSION_RE.fullmatch(version):
        raise ReleaseArtifactError("version must be an exact X.Y.Z release version")
    if tag != f"v{version}":
        raise ReleaseArtifactError(f"tag must equal v{version}")
    init_text = (root / "contextos/__init__.py").read_text(encoding="utf-8")
    schema_text = (root / "contextos/workspace_schema.py").read_text(encoding="utf-8")
    init_match = re.search(r'^__version__\s*=\s*"([^"]+)"\s*$', init_text, re.MULTILINE)
    schema_match = re.search(
        r'^DEFAULT_TEMPLATE_VERSION\s*=\s*"([^"]+)"\s*$', schema_text, re.MULTILINE
    )
    source_match = re.search(
        r'^DEFAULT_TEMPLATE_SOURCE\s*=\s*"([^"]+)"\s*$', schema_text, re.MULTILINE
    )
    if init_match is None or init_match.group(1) != version:
        raise ReleaseArtifactError("contextos.__version__ does not match the release version")
    if schema_match is None or schema_match.group(1) != version:
        raise ReleaseArtifactError("DEFAULT_TEMPLATE_VERSION does not match the release version")
    if source_match is None or source_match.group(1) != TEMPLATE_NAME:
        raise ReleaseArtifactError("DEFAULT_TEMPLATE_SOURCE does not match the release template")
    workspace = json.loads((root / "workspace/example.json").read_text(encoding="utf-8"))
    if workspace.get("template") != {
        "version": version,
        "source": TEMPLATE_NAME,
        "bundle_sha256": EXAMPLE_BUNDLE_SHA256,
    }:
        raise ReleaseArtifactError("workspace/example.json template identity does not match")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## \[{re.escape(version)}\] [—-] \d{{4}}-\d{{2}}-\d{{2}}\b", changelog, re.MULTILINE):
        raise ReleaseArtifactError("CHANGELOG.md lacks a dated release block for the version")


def artifact_names(version: str) -> dict[str, str]:
    stem = f"{TEMPLATE_NAME}-v{version}"
    return {
        "archive": f"{stem}.tar",
        "lock": f"{stem}.bundle.lock.json",
        "provenance": f"{stem}.provenance.json",
        "instructions": f"{stem}.OFFLINE-VERIFY.md",
        "checksums": "SHA256SUMS",
    }


def _archive_bytes(prefix: str, source_epoch: int, files: Sequence[dict[str, Any]], payloads: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for record in files:
            relative = record["path"]
            info = tarfile.TarInfo(f"{prefix}/{relative}")
            info.size = len(payloads[relative])
            info.mode = 0o755 if record["executable"] else 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = source_epoch
            info.type = tarfile.REGTYPE
            archive.addfile(info, io.BytesIO(payloads[relative]))
    return stream.getvalue()


def _offline_instructions(version: str, tag: str, commit: str, names: dict[str, str], bundle_digest: str) -> bytes:
    return f"""# Offline verification for Context OS v{version}

Canonical artifact: `{names['archive']}`. GitHub's automatically generated
source archives are not the release artifact.

Publisher identity: tag `{tag}`, commit `{commit}`.

1. Create one empty verification directory, obtain all five release assets in
   that directory through an authenticated or otherwise trusted GitHub channel,
   and make it the current directory. Keep the assets together throughout these
   steps. The co-located files prove consistency, not publisher identity.
2. Check the four payload digests listed in `{names['checksums']}` using
   `sha256sum -c {names['checksums']}` (or an equivalent SHA-256 tool).
3. Extract `{names['archive']}` directly in the current verification directory;
   do not select a separate extraction destination. The archive creates one root
   named `{TEMPLATE_NAME}-v{version}` beside the five assets.
4. Change into that extracted root and verify the detached lock without network
   access:

```bash
python -m contextos bundle check \\
  --lock ../{names['lock']} \\
  --source . \\
  --source-mode directory \\
  --expect-sha256 {bundle_digest}
```

The report must name version `{version}`, commit `{commit}`, directory source
mode, `unlocked_files_ignored: true`, and `writes: false`. Linux must report
`executable_modes_verified: true`. Windows reports `false` because Windows
directory sources do not expose portable POSIX executable bits; this is an
explicit platform limitation, not a skipped check.
""".encode("utf-8")


def build_artifacts(source: Path, output_dir: Path, *, version: str, tag: str, commit: str) -> dict[str, Any]:
    source = source.absolute().resolve()
    output_dir = output_dir.absolute()
    if output_dir.exists():
        raise ReleaseArtifactError(f"output directory already exists: {output_dir}")
    source_epoch = _require_clean_repository(source, commit)
    _require_release_identity(source, version, tag)
    names = artifact_names(version)
    staging = Path(tempfile.mkdtemp(prefix="contextos-release-", dir=output_dir.parent))
    try:
        lock = create_bundle_lock(source, name=TEMPLATE_NAME, version=version, source_mode="git-index")
        if lock["bundle"]["source_git_commit"] != commit:
            raise ReleaseArtifactError("bundle lock source commit does not match")
        lock_bytes = _json_bytes(lock)
        lock_path = staging / names["lock"]
        lock_path.write_bytes(lock_bytes)
        verified = verify_bundle(
            lock_path, source, expected_sha256=lock["bundle_sha256"],
            source_mode="git-index", retain_paths=None,
        )
        prefix = f"{TEMPLATE_NAME}-v{version}"
        archive_bytes = _archive_bytes(prefix, source_epoch, lock["bundle"]["files"], verified.verified_bytes)
        archive_path = staging / names["archive"]
        archive_path.write_bytes(archive_bytes)
        instructions = _offline_instructions(version, tag, commit, names, lock["bundle_sha256"])
        instructions_path = staging / names["instructions"]
        instructions_path.write_bytes(instructions)
        runtime_evidence = []
        records = {record["path"]: record for record in lock["bundle"]["files"]}
        for path in sorted(
            (path for path in verified.verified_bytes if path.startswith("runtimes/")
             and path.endswith(".json") and path != "runtimes/schema.json"),
            key=portable_path_identity,
        ):
            descriptor = json.loads(verified.verified_bytes[path].decode("utf-8"))
            runtime_evidence.append({
                "path": path,
                "sha256_raw": records[path]["sha256_raw"],
                "runtime": descriptor["runtime"],
                "support_tier": descriptor["support_tier"],
                "support_summary": descriptor["support_summary"],
                "tested_versions": descriptor["evidence"]["tested_versions"],
            })
        provenance = {
            "schema_version": 1,
            "release": {
                "repository": "https://github.com/conorbronsdon/agent-context-os",
                "tag": tag,
                "commit": commit,
            },
            "template": {"name": TEMPLATE_NAME, "version": version},
            "source": {
                "mode": "git-index",
                "commit_epoch": source_epoch,
                "generator": "scripts/release-artifacts.py",
                "generator_version": GENERATOR_VERSION,
                "generation_platform": "linux",
            },
            "archive": {
                "filename": names["archive"],
                "media_type": "application/x-tar",
                "root": prefix,
                "file_count": len(lock["bundle"]["files"]),
                "sha256": _sha256_bytes(archive_bytes),
            },
            "bundle_lock": {
                "filename": names["lock"],
                "sha256": _sha256_bytes(lock_bytes),
                "bundle_sha256": lock["bundle_sha256"],
            },
            "verification_instructions": {
                "filename": names["instructions"],
                "sha256": _sha256_bytes(instructions),
            },
            "runtime_evidence": runtime_evidence,
        }
        provenance_bytes = _json_bytes(provenance)
        (staging / names["provenance"]).write_bytes(provenance_bytes)
        checksummed = [names[key] for key in ("archive", "lock", "provenance", "instructions")]
        checksum_text = "".join(
            f"{_sha256_file(staging / filename)}  {filename}\n" for filename in checksummed
        )
        (staging / names["checksums"]).write_text(checksum_text, encoding="ascii", newline="\n")
        staging.replace(output_dir)
        return provenance
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseArtifactError(f"invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseArtifactError(f"{path.name} must contain a JSON object")
    return value


def _parse_checksums(path: Path, expected_names: Sequence[str]) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ReleaseArtifactError(f"cannot read {path.name}: {exc}") from exc
    if len(lines) != len(expected_names):
        raise ReleaseArtifactError("SHA256SUMS has an unexpected number of entries")
    result: dict[str, str] = {}
    for line in lines:
        match = CHECKSUM_RE.fullmatch(line)
        if match is None or match.group(2) in result:
            raise ReleaseArtifactError("SHA256SUMS is malformed or contains duplicates")
        result[match.group(2)] = match.group(1)
    if list(result) != list(expected_names):
        raise ReleaseArtifactError("SHA256SUMS filenames or order do not match the release contract")
    return result


def verify_artifacts(artifacts: Path, extract_to: Path, *, version: str, tag: str, commit: str) -> dict[str, Any]:
    artifacts = artifacts.absolute().resolve()
    extract_to = extract_to.absolute()
    if not artifacts.is_dir():
        raise ReleaseArtifactError("artifacts must be an existing directory")
    if extract_to.exists():
        raise ReleaseArtifactError("extract destination must not already exist")
    if not VERSION_RE.fullmatch(version) or not COMMIT_RE.fullmatch(commit) or tag != f"v{version}":
        raise ReleaseArtifactError("expected release identity is malformed")
    names = artifact_names(version)
    expected_set = set(names.values())
    actual_set = {item.name for item in artifacts.iterdir() if item.is_file()}
    if actual_set != expected_set or any(not item.is_file() for item in artifacts.iterdir()):
        raise ReleaseArtifactError("release artifact set does not exactly match the contract")
    checksummed = [names[key] for key in ("archive", "lock", "provenance", "instructions")]
    checksums = _parse_checksums(artifacts / names["checksums"], checksummed)
    for filename, expected_digest in checksums.items():
        if _sha256_file(artifacts / filename) != expected_digest:
            raise ReleaseArtifactError(f"SHA-256 mismatch for {filename}")
    provenance = _load_json(artifacts / names["provenance"])
    if set(provenance) != {
        "schema_version", "release", "template", "source", "archive",
        "bundle_lock", "verification_instructions", "runtime_evidence",
    } or provenance.get("schema_version") != 1:
        raise ReleaseArtifactError("provenance schema or top-level fields do not match")
    if provenance.get("release") != {
        "repository": "https://github.com/conorbronsdon/agent-context-os",
        "tag": tag,
        "commit": commit,
    }:
        raise ReleaseArtifactError("provenance release identity does not match")
    if provenance.get("template") != {"name": TEMPLATE_NAME, "version": version}:
        raise ReleaseArtifactError("provenance template identity does not match")
    source = provenance.get("source")
    if not isinstance(source, dict) or set(source) != {
        "mode", "commit_epoch", "generator", "generator_version", "generation_platform"
    } or source.get("mode") != "git-index" or source.get("generation_platform") != "linux":
        raise ReleaseArtifactError("provenance source contract does not match")
    if source.get("generator") != "scripts/release-artifacts.py" or source.get("generator_version") != GENERATOR_VERSION:
        raise ReleaseArtifactError("provenance generator identity does not match")
    if type(source.get("commit_epoch")) is not int or source["commit_epoch"] < 0:
        raise ReleaseArtifactError("provenance commit epoch is invalid")
    if not isinstance(provenance.get("runtime_evidence"), list):
        raise ReleaseArtifactError("provenance runtime evidence must be an array")
    lock_path = artifacts / names["lock"]
    lock = load_bundle_lock(lock_path)
    if lock["bundle"]["name"] != TEMPLATE_NAME or lock["bundle"]["version"] != version or lock["bundle"]["source_git_commit"] != commit:
        raise ReleaseArtifactError("bundle lock identity does not match")
    lock_provenance = provenance.get("bundle_lock")
    if lock_provenance != {
        "filename": names["lock"],
        "sha256": checksums[names["lock"]],
        "bundle_sha256": lock["bundle_sha256"],
    }:
        raise ReleaseArtifactError("provenance bundle-lock binding does not match")
    instructions_provenance = provenance.get("verification_instructions")
    if instructions_provenance != {
        "filename": names["instructions"],
        "sha256": checksums[names["instructions"]],
    }:
        raise ReleaseArtifactError("provenance instructions binding does not match")
    expected_instructions = _offline_instructions(
        version, tag, commit, names, lock["bundle_sha256"]
    )
    if (artifacts / names["instructions"]).read_bytes() != expected_instructions:
        raise ReleaseArtifactError("offline verification instructions do not match the release identity")
    prefix = f"{TEMPLATE_NAME}-v{version}"
    archive_provenance = provenance.get("archive")
    if archive_provenance != {
        "filename": names["archive"],
        "media_type": "application/x-tar",
        "root": prefix,
        "file_count": len(lock["bundle"]["files"]),
        "sha256": checksums[names["archive"]],
    }:
        raise ReleaseArtifactError("provenance archive binding does not match")
    expected_members = [f"{prefix}/{item['path']}" for item in lock["bundle"]["files"]]
    extract_root = extract_to / prefix
    extract_to.mkdir(parents=True)
    runtime_evidence: list[dict[str, Any]] = []
    try:
        with tarfile.open(artifacts / names["archive"], mode="r:") as archive:
            members = archive.getmembers()
            if [member.name for member in members] != expected_members:
                raise ReleaseArtifactError("archive members or portable order do not match the lock")
            for member, record in zip(members, lock["bundle"]["files"]):
                if not member.isfile() or member.linkname or member.uid != 0 or member.gid != 0:
                    raise ReleaseArtifactError(f"unsafe archive member metadata: {member.name}")
                if member.uname or member.gname or member.mtime != source["commit_epoch"]:
                    raise ReleaseArtifactError(f"non-deterministic archive metadata: {member.name}")
                expected_mode = 0o755 if record["executable"] else 0o644
                if member.mode != expected_mode or member.size != record["size"]:
                    raise ReleaseArtifactError(f"archive mode or size mismatch: {member.name}")
                relative = PurePosixPath(record["path"])
                destination = extract_root.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                payload = archive.extractfile(member)
                if payload is None:
                    raise ReleaseArtifactError(f"archive payload unavailable: {member.name}")
                data = payload.read()
                if _sha256_bytes(data) != record["sha256_raw"]:
                    raise ReleaseArtifactError(f"archive payload mismatch: {member.name}")
                if record["path"].startswith("runtimes/") and record["path"].endswith(".json") and record["path"] != "runtimes/schema.json":
                    descriptor = json.loads(data.decode("utf-8"))
                    runtime_evidence.append({
                        "path": record["path"],
                        "sha256_raw": record["sha256_raw"],
                        "runtime": descriptor["runtime"],
                        "support_tier": descriptor["support_tier"],
                        "support_summary": descriptor["support_summary"],
                        "tested_versions": descriptor["evidence"]["tested_versions"],
                    })
                destination.write_bytes(data)
                if os.name != "nt":
                    destination.chmod(expected_mode)
        if provenance["runtime_evidence"] != runtime_evidence:
            raise ReleaseArtifactError("provenance runtime evidence does not match locked descriptors")
        verified = verify_bundle(
            lock_path, extract_root, expected_sha256=lock["bundle_sha256"],
            source_mode="directory", retain_paths=(),
        )
        return {
            "schema_version": 1,
            "tag": tag,
            "commit": commit,
            "version": version,
            "bundle_sha256": verified.digest,
            "archive_sha256": checksums[names["archive"]],
            "files": len(verified.records),
            "source_mode": verified.source_mode,
            "executable_modes_verified": verified.mode_verified,
            "unlocked_files_ignored": True,
            "writes": False,
        }
    except Exception:
        shutil.rmtree(extract_to, ignore_errors=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--source", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--artifacts", type=Path, required=True)
    verify.add_argument("--extract-to", type=Path, required=True)
    for command in (build, verify):
        command.add_argument("--version", required=True)
        command.add_argument("--tag", required=True)
        command.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            if not sys.platform.startswith("linux"):
                raise ReleaseArtifactError("canonical release generation is Linux-only")
            result = build_artifacts(
                args.source, args.output_dir, version=args.version,
                tag=args.tag, commit=args.commit,
            )
        else:
            result = verify_artifacts(
                args.artifacts, args.extract_to, version=args.version,
                tag=args.tag, commit=args.commit,
            )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ReleaseArtifactError, BundleError, OSError, UnicodeError, json.JSONDecodeError, tarfile.TarError) as exc:
        print(f"release artifacts: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
