#!/usr/bin/env python3
"""Validate the local memory binding and /dream proposal artifacts.

The slash commands are prose, so the safety-critical filesystem checks live
here.  This helper intentionally accepts only a small, explicit proposal
surface: no path separators in memory filenames, no symlinked binding/artifact
components, no remotes or unrelated changes in the memory git repository,
reserved control files for structural actions, no proposal collisions, and no
empty evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any


TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$")
MEMORY_FILE = re.compile(r"^(?:MEMORY|ARCHIVE|[a-z][A-Za-z0-9_-]*)\.md$")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
COMMON_FIELDS = {"id", "action", "reasoning", "evidence", "confidence"}
ALLOWED_ACTIONS = {"modify", "archive", "merge", "split", "add", "flag"}
ALLOWED_CONFIDENCE = {"high", "medium", "low", "flag"}
SHIPPED_CURATORS = {"rot", "merge", "split", "lint"}
CURATOR_ACTIONS = {
    "rot": {"modify", "archive", "flag"},
    "merge": {"merge", "flag"},
    "split": {"split", "flag"},
    "lint": {"modify", "archive", "flag"},
}
CONTROL_FILES = {"MEMORY.md", "ARCHIVE.md"}
ALLOWED_TOP_LEVEL = {"curator", "ran_at", "inputs_summary", "proposals", "skipped"}
REQUIRED_TOP_LEVEL = {"curator", "ran_at", "proposals"}
ACTION_FIELDS = {
    "modify": {"target", "current_excerpt", "proposed_excerpt", "check"},
    "archive": {"target", "current_excerpt", "proposed_excerpt", "archive_reason", "check"},
    "merge": {
        "targets",
        "survivor",
        "merged_body",
        "index_changes",
        "archive_tombstones",
        "net_index_lines",
    },
    "split": {"target", "original_index_line", "result_files"},
    "add": {"target", "proposed_content", "index_line", "check"},
    "flag": {"target", "concern", "current_excerpt", "proposed_excerpt", "check"},
}
REQUIRED_ACTION_FIELDS = {
    "modify": {"target", "current_excerpt", "proposed_excerpt"},
    "archive": {"target", "archive_reason"},
    "merge": {
        "targets",
        "survivor",
        "merged_body",
        "index_changes",
        "archive_tombstones",
        "net_index_lines",
    },
    "split": {"target", "original_index_line", "result_files"},
    "add": {"target", "proposed_content", "index_line"},
    "flag": {"target", "concern"},
}


class ValidationError(ValueError):
    """A user-facing validation failure."""


def run_git(args: list[str], *, cwd: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ValidationError(f"git {' '.join(args)} failed: {detail}") from exc
    return completed.stdout.strip()


def run_git_paths(args: list[str], *, cwd: Path) -> set[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return {
            item.decode("utf-8")
            for item in completed.stdout.split(b"\0")
            if item
        }
    except (subprocess.CalledProcessError, UnicodeError) as exc:
        detail = getattr(exc, "stderr", b"")
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        raise ValidationError(f"cannot inspect memory git changes: {str(detail).strip()}") from exc


def repository_identity(repo: Path) -> str:
    common_dir = run_git(
        ["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=repo
    )
    resolved = Path(common_dir).resolve(strict=True)
    return str(resolved)


def same_directory(recorded: str, identity: str) -> bool:
    """Do two recorded paths name the same directory?

    Compared as paths rather than as strings, because the marker file and this
    check are written by different tools that spell the same directory
    differently:

      git rev-parse   C:/Users/me/repo/.git      (forward slashes, even on Windows)
      Python resolve  C:\\Users\\me\\repo\\.git     (backslashes)
      docs/auto-memory.md's `realpath` under Git Bash → /c/Users/me/repo/.git

    All three name one directory. On POSIX they are byte-identical, which is why
    a literal `!=` held up everywhere CI runs and failed only on Windows -- where
    it rejected every correctly-configured binding, taking out 31 tests and, more
    importantly, the feature itself for any Windows user who followed the setup
    doc exactly.

    This does NOT loosen the check. It still demands the same directory; it just
    stops treating a separator convention as a different repository. Comparison is
    on fully resolved paths, so `..`, symlinks, and 8.3 short names all normalize
    before the equality, and a marker naming any other directory is still
    rejected. Unresolvable input (a path that does not exist, e.g. the classic
    stale marker pointing at a deleted checkout) fails closed.
    """
    if recorded == identity:
        return True
    try:
        if CONTROL.search(recorded) or CONTROL.search(identity):
            return False
        left = Path(native_path(recorded))
        right = Path(native_path(identity))
        reject_nonlocal_root(left, "memory repository marker")
        return same_file(left.resolve(strict=True), right.resolve(strict=True))
    except (OSError, ValueError, ValidationError):
        # Nonexistent, malformed, or not addressable on this platform -- e.g. the
        # MSYS-style /c/... form under a native Python. Fail closed: an identity
        # we cannot resolve is not an identity we can vouch for.
        return False


def head_identity(memory_dir: Path) -> str:
    completed = subprocess.run(
        ["git", "symbolic-ref", "-q", "HEAD"],
        cwd=memory_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode == 1:
        return "DETACHED"
    if completed.returncode != 0:
        raise ValidationError("cannot inspect the memory repository HEAD identity")
    value = completed.stdout.strip()
    if not value.startswith("refs/heads/"):
        raise ValidationError("memory HEAD must be detached or name a canonical local branch")
    checked = subprocess.run(
        ["git", "check-ref-format", value],
        cwd=memory_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if checked.returncode != 0:
        raise ValidationError("memory HEAD names an invalid local branch")
    return value


def read_single_line(path: Path, label: str) -> str:
    if path.is_symlink():
        raise ValidationError(f"{label} must not be a symlink: {path}")
    if not path.is_file():
        raise ValidationError(f"{label} must be a regular file: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValidationError(f"cannot read {label}: {exc}") from exc
    lines = text.splitlines()
    if len(lines) != 1 or not lines[0].strip() or text != f"{lines[0]}\n":
        raise ValidationError(f"{label} must contain exactly one non-empty line")
    return lines[0]


def require_regular_file(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ValidationError(f"{label} must not be a symlink: {path}")
    if not path.is_file():
        raise ValidationError(f"{label} must be a regular file: {path}")


DOTS = {".", ".."}


def reject_traversal(raw: str, label: str) -> None:
    """Reject '.'/'..' in a slash-form path BEFORE any translation sees it.

    cygpath collapses traversal silently, so `/tmp/../tmp/memory` reached
    require_canonical_directory already normalized and sailed through the
    "must be canonical with no '..'" check that the drive-letter branch
    correctly rejects. Two spellings of the same forbidden input, two different
    verdicts, on the same platform. Checked on the raw string so the answer no
    longer depends on which translation branch runs.
    """
    for part in raw.replace("\\", "/").split("/"):
        if part in DOTS:
            raise ValidationError(f"{label} must be canonical with no '.' or '..': {raw}")


def reject_nonlocal_root(path: Path, label: str) -> None:
    """Reject UNC shares and Win32 device paths.

    Two reasons, one of them new. The binding is documented as a PRIVATE
    directory, and a share is not private. More sharply: same_directory now
    RESOLVES the recorded value, and resolving `//attacker/share/...` makes
    Windows open an SMB connection to a host named in an attacker-controlled
    file -- a credential-disclosure and hang risk the old literal string compare
    did not have. The ten-second guard on cygpath does not cover filesystem
    resolution, which has no timeout at all.

    Device paths (\\\\?\\, \\\\.\\) are rejected in the same breath: they bypass
    normalization, so a canonical check on one means very little.

    This is a deliberate tightening -- UNC memory directories were accepted
    before. Reverse it by dropping this call if a network store is ever wanted,
    but do it knowing the resolution happens on unvalidated input.
    """
    text = str(path)
    if text.startswith("\\\\") or text.startswith("//"):
        raise ValidationError(
            f"{label} must be a local path; UNC and device paths are not accepted: {path}"
        )


def find_cygpath() -> str | None:
    """Locate cygpath, falling back to the Git installation that ships it.

    It lives in `Git\\usr\\bin` while git.exe is in `Git\\mingw64\\bin` or
    `Git\\cmd` -- different directories -- so a PATH carrying git does not imply
    one carrying cygpath. Without this the documented `/tmp/...` form silently
    stops translating and gets rejected as non-absolute, on a machine where Git
    for Windows is installed and everything looks fine.
    """
    found = shutil.which("cygpath")
    if found:
        return found
    git = shutil.which("git")
    if not git:
        return None
    for parent in Path(git).resolve().parents:
        candidate = parent / "usr" / "bin" / "cygpath.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def same_file(a: Path, b: Path) -> bool:
    """Compare filesystem identity, not path spelling.

    Path.__eq__ is case-INSENSITIVE on Windows, so `C:\\cs\\Repo\\.git` and
    `C:\\cs\\repo\\.git` compared equal -- two genuinely different repositories
    on a directory with case sensitivity enabled, and the marker is the whole
    binding. The pre-existing literal string compare happened to be
    case-sensitive; switching to Path comparison quietly gave that away.

    os.path.samefile compares device and inode (the file index on Windows), so
    it answers the question actually being asked. Requires both to exist, which
    is correct here: an identity that cannot be stat'd is not one to vouch for.
    """
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def replace_control_file(path: Path, text: str, label: str) -> None:
    """Write a control file without ever following what is already there.

    `path.write_text()` follows a symlink. That turned `bind --force` into an
    arbitrary-file-overwrite: point `.context-os/memory-directory` at any file,
    run bind --force, and its contents are replaced -- verified against a file
    holding unrelated content. A BROKEN symlink was worse, because Path.exists()
    is false for one, so even the non-force path skipped its check and created a
    file wherever the link pointed.

    Writing a temp sibling and os.replace()ing it swaps the directory ENTRY, so
    an existing symlink is replaced rather than traversed. The lexists check
    still refuses up front, so this is belt and braces on the operation that
    actually caused the damage.
    """
    if os.path.lexists(path) and (path.is_symlink() or not path.is_file()):
        raise ValidationError(
            f"{label} must be a regular file, not a symlink or special file: {path}"
        )
    tmp = path.with_name(path.name + ".tmp-bind")
    if os.path.lexists(tmp):
        raise ValidationError(f"stale temporary file in the way: {tmp}")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if os.path.lexists(tmp):
            tmp.unlink()


MSYS_DRIVE = re.compile(r"^/(?:cygdrive/)?([A-Za-z])/(.*)$")


def native_path(raw: str) -> str:
    """Rewrite a Unix-shell path into the form this interpreter can address.

    docs/auto-memory.md builds both recorded paths in bash. On Windows that bash
    is Git Bash, whose absolute paths are MSYS-style — `/c/Users/me/memory`, or
    `/cygdrive/c/...` under Cygwin. Native Python reads those as drive-less and
    rejects them at the `is_absolute()` gate, so the documented setup produced a
    binding the validator refused: "must be absolute". Same directory, different
    shell's spelling.

    This is a spelling change only, applied before validation, never instead of
    it. The translated path still has to be absolute, non-symlinked, canonical,
    existing, and a directory — and for the marker, still has to name the same
    repository. Nothing here can turn a rejected path into an accepted one; it
    can only let a correctly-spelled-for-bash path reach the checks at all.

    No-op on POSIX, where `/c/anything` is a real path and must stay one.
    """
    if os.name != "nt" or not raw.startswith("/"):
        return raw
    reject_traversal(raw, "recorded path")
    match = MSYS_DRIVE.match(raw)
    if match:
        drive, rest = match.groups()
        return str(Path(f"{drive.upper()}:/{rest}"))
    # A POSIX-absolute path with no drive letter (/tmp/..., /usr/...) is a mount
    # only the shell knows about. cygpath ships with Git for Windows and is the
    # authority on those; if it is missing or fails, hand back the original so
    # the caller's own checks reject it rather than guessing a translation.
    cygpath = find_cygpath()
    if not cygpath:
        return raw
    try:
        converted = subprocess.run(
            [cygpath, "-w", raw], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return raw
    if converted.returncode != 0:
        return raw
    return converted.stdout.strip() or raw


def require_canonical_directory(raw: str, label: str) -> Path:
    if CONTROL.search(raw):
        raise ValidationError(f"{label} contains a control character")
    reject_traversal(raw, label)
    raw = native_path(raw)
    path = Path(raw)
    if not path.is_absolute():
        raise ValidationError(f"{label} must be absolute")
    reject_nonlocal_root(path, label)
    if path.is_symlink():
        raise ValidationError(f"{label} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValidationError(f"{label} must resolve to an existing directory: {exc}") from exc
    if str(path) != str(resolved):
        raise ValidationError(f"{label} must be canonical with no '..' or symlinks")
    if not resolved.is_dir():
        raise ValidationError(f"{label} must be an existing directory")
    return resolved


def ensure_inside(base: Path, child: Path, label: str) -> Path:
    resolved_child = child.resolve(strict=False)
    try:
        os.path.commonpath([str(base), str(resolved_child)])
    except ValueError as exc:
        raise ValidationError(f"{label} escapes memory directory") from exc
    if os.path.commonpath([str(base), str(resolved_child)]) != str(base):
        raise ValidationError(f"{label} escapes memory directory")
    return resolved_child


def ensure_no_symlink_components(path: Path, stop_at: Path, label: str) -> None:
    current = stop_at
    for part in path.relative_to(stop_at).parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValidationError(f"{label} contains a symlink component: {current}")


def changed_memory_paths(memory_dir: Path) -> set[str]:
    return set().union(
        run_git_paths(["diff", "--no-renames", "--name-only", "-z"], cwd=memory_dir),
        run_git_paths(
            ["diff", "--cached", "--no-renames", "--name-only", "-z"],
            cwd=memory_dir,
        ),
        run_git_paths(
            ["ls-files", "--others", "--exclude-standard", "-z"], cwd=memory_dir
        ),
    )


MOUNTINFO = Path("/proc/self/mountinfo")

# mountinfo octal-escapes exactly these four characters in the root and
# mount-point fields, which is what makes a plain whitespace split safe.
_MOUNTINFO_ESCAPES = {"040": " ", "011": "\t", "012": "\n", "134": "\\"}


def _unescape_mountinfo(field: str) -> str:
    """Decode one field, in a single left-to-right pass.

    The pass matters. A directory literally named `\\040` is emitted as
    `\\134040`; decoding once yields a backslash followed by "040", which is
    right. A decoder that applies replacements repeatedly (or str.replace in a
    loop) turns that same input into a space and silently names a different
    directory.
    """
    out = []
    i = 0
    while i < len(field):
        if field[i] == "\\" and field[i + 1:i + 4] in _MOUNTINFO_ESCAPES:
            out.append(_MOUNTINFO_ESCAPES[field[i + 1:i + 4]])
            i += 4
        else:
            out.append(field[i])
            i += 1
    return "".join(out)


def read_mountinfo(source: Path = MOUNTINFO) -> list[tuple[str, str, str]]:
    """Parse /proc/self/mountinfo into (device, root, mount_point) triples.

    Split first, decode the two path fields individually afterwards -- never the
    other way round. Unescaping the whole line before splitting would turn a
    `\\040` inside a directory name into a field separator and a `\\012` into a
    record boundary, which is a parsing bypass rather than a cosmetic bug.

    Read with surrogateescape, not errors="replace": Linux pathnames are byte
    strings, so a non-UTF-8 directory name is legal. Replacing those bytes with
    U+FFFD would make two different paths compare equal, and collapsing several
    distinct names onto one string is exactly the shape of a bypass.

    Returns [] when the file is absent or unreadable (Windows, macOS, a
    container with a restricted /proc). Callers treat that as "cannot tell",
    never as "nothing is mounted".
    """
    try:
        text = source.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError:
        return []
    entries = []
    for line in text.splitlines():
        fields = line.split(" ")
        if len(fields) < 5:
            continue
        entries.append(
            (fields[2], _unescape_mountinfo(fields[3]), _unescape_mountinfo(fields[4]))
        )
    return entries


def _is_at_or_under(path: PurePosixPath, root: PurePosixPath) -> bool:
    """Component-wise containment. `/repo` must not swallow `/repository`."""
    return path == root or root in path.parents


def filesystem_location(path: Path, entries: list[tuple[str, str, str]]):
    """Map a visible path to the (device, path-within-that-filesystem) it names.

    This is what sees through a bind mount. `resolve()` cannot: a bind alias is
    not a symlink, so a store sitting inside the repository can be published at
    an outside path and pass a purely lexical containment check. Reproduced.

    The mount whose mount point is the longest component-prefix wins; among
    equal-length matches the last listed wins, which is how a stacked mount
    behaves on current kernels. NOTE that line order is an implementation
    property, not the documented rule -- the documented way to identify the
    visible mount among several at one point is the parent-ID graph. Adversarial
    stacking can therefore mis-select. That is an accepted limit: someone able
    to stack mounts can also unshare a namespace, which defeats any check based
    on a recorded pathname. This guards against accidents, not attackers.

    `root` is the source's path within its own filesystem -- `/` for an ordinary
    mount, the source directory for a bind. Chained binds need no iteration: the
    kernel already reports the ORIGINAL filesystem path for a bind of a bind
    (verified by mounting one, not assumed).

    Returns None when nothing matches.
    """
    target = PurePosixPath(path.as_posix())
    best = None
    best_depth = -1
    for device, root, mount_point in entries:
        mp = PurePosixPath(mount_point)
        if not _is_at_or_under(target, mp):
            continue
        depth = len(mp.parts)
        if depth >= best_depth:            # >= so a later equal-depth mount wins
            best_depth = depth
            best = (device, root, mp)
    if best is None:
        return None
    device, root, mp = best
    relative = target.relative_to(mp)
    if str(relative) == ".":
        return device, PurePosixPath(root)
    return device, PurePosixPath(root) / relative


def repository_regions(roots, entries):
    """Every (device, filesystem-path) region reachable at or beneath the repo.

    A repository is not one region. If a separate filesystem is mounted inside
    it -- `/repo/vendor` on another device, common in containers and dev setups
    -- then a store on THAT device, aliased to an outside path, is visibly under
    the repository while sharing no device with the worktree root. Comparing
    against the worktree's own region alone accepts it.

    So collect the region for each root plus the region of every mount whose
    mount point falls at or beneath a root. O(mounts), not O(files).
    """
    regions = []
    for root in roots:
        root_posix = PurePosixPath(Path(root).as_posix())
        here = filesystem_location(Path(root), entries)
        if here is not None:
            regions.append(here)
        for device, mroot, mount_point in entries:
            if _is_at_or_under(PurePosixPath(mount_point), root_posix):
                regions.append((device, PurePosixPath(mroot)))
    return regions


def shares_underlying_location(inner: Path, outer: Path, entries=None) -> bool:
    """Is `inner` physically at or under `outer`, seeing through bind mounts?

    False when it cannot be determined -- no mountinfo, or the path is not
    covered by any mount entry. Deliberate: this runs ALONGSIDE the lexical
    containment check, never instead of it, so an inconclusive answer leaves the
    existing guarantee exactly where it was. Failing closed would reject every
    store on every platform without /proc, and rejecting a working setup is the
    failure users actually hit. Rejection happens only on positive evidence.

    Known limits, none of which this pretends to cover: a mount namespace the
    helper cannot see, an overlayfs backing directory reached through its upper
    layer (different device identity from the overlay path), and a mount created
    after the check. statx(STATX_MNT_ID)/statmount would narrow the first and
    last, but neither is exposed by the Python standard library.
    """
    entries = read_mountinfo() if entries is None else entries
    if not entries:
        return False
    here = filesystem_location(inner, entries)
    if here is None:
        return False
    device, fs_path = here
    for region_device, region_path in repository_regions([outer], entries):
        if device == region_device and _is_at_or_under(fs_path, region_path):
            return True
    return False


def require_outside_repository(memory_dir: Path, repo: Path, identity: str) -> None:
    """Refuse a memory directory that lives inside the repository.

    docs/auto-memory.md step 1 says "a private absolute directory OUTSIDE this
    repository", and until now nothing enforced it: a memory dir nested in the
    working tree passed every check, because it is its own git top-level and so
    satisfied the one test that came close.

    Nesting it is the failure this whole binding exists to prevent. Private
    memory inside a shared checkout is one `git add -A` away from being staged
    as a gitlink, one `rm -rf .git` away from being committed wholesale, and it
    travels with any archive of the repo. The repo here is shared with other
    people, so "it is only local" is not a property that holds.

    Checks the working tree and the git common directory separately: a linked
    worktree's toplevel is not under its common dir, so testing one does not
    cover the other.
    """
    try:
        worktree = Path(run_git(["rev-parse", "--show-toplevel"], cwd=repo)).resolve(strict=True)
    except (ValidationError, OSError):
        worktree = repo

    for root, what in ((worktree, "working tree"), (Path(identity), "git directory")):
        try:
            inside = memory_dir == root or memory_dir.is_relative_to(root)
        except (OSError, ValueError):
            inside = False
        # A bind mount publishes one directory at a second path. The alias is not
        # a symlink, so resolve() cannot see through it and the check above reads
        # "outside" for a store sitting in the repository. Reproduced, then fixed
        # by asking the kernel where each path actually lives.
        if not inside:
            inside = shares_underlying_location(memory_dir, root)
            if inside:
                what = f"{what} (reached through a bind mount)"
        if inside:
            raise ValidationError(
                f"memory directory must live outside this repository; it is inside the {what} "
                f"({memory_dir}). Move it to a private path outside {root} and update "
                ".context-os/memory-directory."
            )


def validate_memory_binding(repo: Path, *, require_clean: bool = False) -> dict[str, str]:
    repo = repo.resolve(strict=True)
    identity = repository_identity(repo)
    binding = repo / ".context-os" / "memory-directory"
    memory_dir = require_canonical_directory(
        read_single_line(binding, ".context-os/memory-directory"),
        ".context-os/memory-directory",
    )

    require_outside_repository(memory_dir, repo, identity)

    marker = memory_dir / ".context-os-repository"
    marker_value = read_single_line(marker, "memory repository marker")
    if not same_directory(marker_value, identity):
        raise ValidationError(
            "memory repository marker does not match this repository identity"
        )
    require_regular_file(memory_dir / "MEMORY.md", "memory index")

    memory_top = Path(
        run_git(["rev-parse", "--show-toplevel"], cwd=memory_dir)
    ).resolve(strict=True)
    if memory_top != memory_dir:
        raise ValidationError("memory directory must be its own git top-level")
    if run_git(["remote"], cwd=memory_dir):
        raise ValidationError("memory git repository must not have remotes")
    if require_clean:
        dirty = changed_memory_paths(memory_dir)
        if dirty:
            raise ValidationError(
                "memory git repository must be clean; review or snapshot these paths first: "
                + ", ".join(sorted(dirty))
            )
    return {"memory_dir": str(memory_dir), "repository_identity": identity}


def safe_memory_filename(
    value: Any,
    *,
    memory_dir: Path,
    label: str,
    require_existing: bool = False,
    require_absent: bool = False,
) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{label} must be a non-empty string")
    if CONTROL.search(value) or "/" in value or "\\" in value:
        raise ValidationError(f"{label} must be a plain memory filename")
    if value in {".", ".."} or value.startswith(".") or ".." in Path(value).parts:
        raise ValidationError(f"{label} must not be hidden or relative")
    if not MEMORY_FILE.fullmatch(value):
        raise ValidationError(f"{label} must be a safe .md memory filename")
    candidate = memory_dir / value
    if candidate.is_symlink():
        raise ValidationError(f"{label} must not point at a symlink")
    if require_existing:
        if not candidate.is_file():
            raise ValidationError(f"{label} must be an existing memory file")
    if require_absent and candidate.exists():
        raise ValidationError(f"{label} must not already exist")
    target = ensure_inside(memory_dir, candidate, label)
    if target.exists() and target.is_symlink():
        raise ValidationError(f"{label} must not point at a symlink")
    return value


def safe_detail_filename(
    value: Any,
    *,
    memory_dir: Path,
    label: str,
    require_existing: bool = False,
    require_absent: bool = False,
) -> str:
    if isinstance(value, str) and value in CONTROL_FILES:
        raise ValidationError(f"{label} must be a detail file, not a memory control file")
    filename = safe_memory_filename(
        value,
        memory_dir=memory_dir,
        label=label,
        require_existing=require_existing,
        require_absent=require_absent,
    )
    return filename


def safe_relative_change(value: Any, *, memory_dir: Path, label: str) -> str:
    if not isinstance(value, str) or not value or CONTROL.search(value):
        raise ValidationError(f"{label} must be a non-empty path without control characters")
    path = Path(value)
    if (
        path.is_absolute()
        or "\\" in value
        or value != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValidationError(f"{label} must be a canonical relative path")
    candidate = memory_dir / path
    ensure_inside(memory_dir, candidate, label)
    ensure_no_symlink_components(candidate, memory_dir, label)
    return path.as_posix()


def require_allowed_changes(memory_dir: Path, allowed: set[str]) -> set[str]:
    changed = changed_memory_paths(memory_dir)
    unexpected = changed - allowed
    if unexpected:
        raise ValidationError(
            "memory git has changes outside the reviewed allowlist: "
            + ", ".join(sorted(unexpected))
        )
    return changed


def require_no_unstaged_changes(memory_dir: Path) -> None:
    completed = subprocess.run(
        ["git", "diff", "--quiet", "--exit-code"],
        cwd=memory_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode == 1:
        raise ValidationError("memory git has unstaged changes after reviewed staging")
    if completed.returncode != 0:
        raise ValidationError("cannot compare the memory worktree with its index")
    untracked = run_git_paths(
        ["ls-files", "--others", "--exclude-standard", "-z"], cwd=memory_dir
    )
    if untracked:
        raise ValidationError(
            "memory git has untracked paths after final review: "
            + ", ".join(sorted(untracked))
        )


def staged_entry(memory_dir: Path, relative: str) -> tuple[str, bytes] | None:
    completed = subprocess.run(
        ["git", "ls-files", "--stage", "-z", "--", relative],
        cwd=memory_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise ValidationError(f"cannot inspect staged path: {relative}")
    entries = [entry for entry in completed.stdout.split(b"\0") if entry]
    candidate = memory_dir / relative
    if not entries:
        if candidate.exists():
            raise ValidationError(f"reviewed path is not staged: {relative}")
        return None
    if len(entries) != 1:
        raise ValidationError(f"reviewed path has unresolved index stages: {relative}")
    metadata, separator, encoded_path = entries[0].partition(b"\t")
    fields = metadata.split()
    try:
        decoded_path = encoded_path.decode("utf-8")
    except UnicodeError as exc:
        raise ValidationError(f"staged path is not UTF-8: {relative}") from exc
    if not separator or len(fields) != 3 or fields[2] != b"0" or decoded_path != relative:
        raise ValidationError(f"malformed staged entry for reviewed path: {relative}")
    blob = subprocess.run(
        ["git", "cat-file", "blob", fields[1].decode("ascii")],
        cwd=memory_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if blob.returncode != 0:
        raise ValidationError(f"cannot read staged blob for reviewed path: {relative}")
    return fields[0].decode("ascii"), blob.stdout


def tree_entry(memory_dir: Path, tree_sha: str, relative: str) -> tuple[str, bytes] | None:
    completed = subprocess.run(
        ["git", "ls-tree", "-z", tree_sha, "--", relative],
        cwd=memory_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise ValidationError(f"cannot inspect approved tree path: {relative}")
    entries = [entry for entry in completed.stdout.split(b"\0") if entry]
    if not entries:
        return None
    if len(entries) != 1:
        raise ValidationError(f"approved tree path is ambiguous: {relative}")
    metadata, separator, encoded_path = entries[0].partition(b"\t")
    fields = metadata.split()
    try:
        decoded_path = encoded_path.decode("utf-8")
    except UnicodeError as exc:
        raise ValidationError(f"approved tree path is not UTF-8: {relative}") from exc
    if (
        not separator
        or len(fields) != 3
        or fields[1] != b"blob"
        or decoded_path != relative
    ):
        raise ValidationError(f"malformed approved tree entry for path: {relative}")
    blob = subprocess.run(
        ["git", "cat-file", "blob", fields[2].decode("ascii")],
        cwd=memory_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if blob.returncode != 0:
        raise ValidationError(f"cannot read approved tree blob for path: {relative}")
    return fields[0].decode("ascii"), blob.stdout


def change_digest(
    memory_dir: Path,
    paths: set[str],
    *,
    source: str,
    tree_sha: str | None = None,
) -> str:
    digest = hashlib.sha256()
    digest.update(b"context-os-dream-change-v1\0")
    for relative in sorted(paths):
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        if source == "index":
            entry = staged_entry(memory_dir, relative)
        elif source == "tree":
            if tree_sha is None:
                raise ValidationError("approved tree digest requires a tree SHA")
            entry = tree_entry(memory_dir, tree_sha, relative)
        elif source == "worktree":
            candidate = memory_dir / relative
            if candidate.is_symlink() or (candidate.exists() and not candidate.is_file()):
                raise ValidationError(f"reviewed path must be a regular file or deletion: {relative}")
            try:
                entry = (
                    ("100755" if candidate.stat().st_mode & 0o111 else "100644"),
                    candidate.read_bytes(),
                ) if candidate.exists() else None
            except OSError as exc:
                raise ValidationError(f"cannot read reviewed path {relative}: {exc}") from exc
        else:  # pragma: no cover - internal callers use constants.
            raise ValidationError(f"unknown digest source: {source}")
        if entry is None:
            digest.update(b"D")
        else:
            mode, content = entry
            digest.update(b"F")
            digest.update(mode.encode("ascii"))
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
    return digest.hexdigest()


def require_object_sha(value: str, label: str) -> str:
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value):
        raise ValidationError(f"{label} must be a lowercase Git object SHA")
    return value


def tree_changed_paths(memory_dir: Path, base_head: str, tree_sha: str) -> set[str]:
    return run_git_paths(
        [
            "diff-tree",
            "--no-commit-id",
            "-r",
            "--no-renames",
            "--name-only",
            "-z",
            base_head,
            tree_sha,
        ],
        cwd=memory_dir,
    )


def valid_timestamp(value: str) -> bool:
    if not TIMESTAMP.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H-%M-%SZ")
    except ValueError:
        return False
    return True


def dreams_root(memory_dir: Path) -> Path:
    candidate = memory_dir / ".dreams"
    if candidate.is_symlink():
        raise ValidationError("dreams root contains a symlink component")
    root = ensure_inside(memory_dir, candidate, "dreams root")
    ensure_no_symlink_components(root, memory_dir, "dreams root")
    return root


def resolve_artifact(memory_dir: Path, ts: str, *, for_create: bool) -> tuple[str, Path]:
    root = dreams_root(memory_dir)
    if ts == "latest":
        if for_create:
            raise ValidationError("latest cannot be used when creating an artifact")
        if not root.is_dir():
            raise ValidationError("no .dreams directory exists")
        candidates = [
            child.name
            for child in root.iterdir()
            if child.is_dir() and not child.is_symlink() and valid_timestamp(child.name)
        ]
        if not candidates:
            raise ValidationError("no valid dream artifacts exist")
        ts = sorted(candidates)[-1]
    elif not valid_timestamp(ts):
        raise ValidationError("dream timestamp must match YYYY-MM-DDTHH-MM-SSZ")

    path = ensure_inside(memory_dir, root / ts, "dream artifact")
    ensure_no_symlink_components(path, memory_dir, "dream artifact")
    if for_create:
        if path.exists():
            raise ValidationError(f"dream artifact already exists: {ts}")
        return ts, path

    if path.is_symlink() or not path.is_dir():
        raise ValidationError(f"dream artifact must be an existing directory: {ts}")
    require_regular_file(path / "proposals.json", "proposals.json")
    require_regular_file(path / "REPORT.md", "REPORT.md")
    return ts, path


def validate_common(proposal: dict[str, Any], index: int) -> str:
    missing = COMMON_FIELDS - set(proposal)
    if missing:
        raise ValidationError(f"proposal {index}: missing fields {sorted(missing)}")
    action = proposal["action"]
    if not isinstance(action, str) or action not in ALLOWED_ACTIONS:
        raise ValidationError(f"proposal {index}: unknown action {action!r}")
    missing = REQUIRED_ACTION_FIELDS[action] - set(proposal)
    if missing:
        raise ValidationError(f"proposal {index}: missing {action} fields {sorted(missing)}")
    allowed = COMMON_FIELDS | ACTION_FIELDS[action]
    extra = set(proposal) - allowed
    if extra:
        raise ValidationError(f"proposal {index}: unknown fields {sorted(extra)}")
    for field in ("id", "reasoning"):
        if not isinstance(proposal[field], str) or not proposal[field].strip():
            raise ValidationError(f"proposal {index}: {field} must be non-empty")
    if CONTROL.search(proposal["id"]):
        raise ValidationError(f"proposal {index}: id must be a single safe line")
    evidence = proposal["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ValidationError(f"proposal {index}: evidence must be a non-empty array")
    if any(not isinstance(item, str) or not item.strip() for item in evidence):
        raise ValidationError(f"proposal {index}: every evidence item must be non-empty")
    confidence = proposal["confidence"]
    if not isinstance(confidence, str) or confidence not in ALLOWED_CONFIDENCE:
        raise ValidationError(f"proposal {index}: unsupported confidence {confidence!r}")
    return action


def require_string_fields(
    proposal: dict[str, Any],
    index: int,
    fields: set[str],
    *,
    allow_empty: set[str] | None = None,
) -> None:
    allow_empty = allow_empty or set()
    for field in fields:
        if field in proposal and not isinstance(proposal[field], str):
            raise ValidationError(f"proposal {index}: {field} must be a string")
        if field in proposal and field not in allow_empty and not proposal[field].strip():
            raise ValidationError(f"proposal {index}: {field} must be a non-empty string")


def require_single_line_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or CONTROL.search(value):
        raise ValidationError(f"{label} must be a non-empty single-line string")
    return value


def require_iso_date(value: str, label: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValidationError(f"{label} must match YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValidationError(f"{label} is not a valid calendar date") from exc
    return value


def validate_proposal(proposal: Any, index: int, *, memory_dir: Path) -> None:
    if not isinstance(proposal, dict):
        raise ValidationError(f"proposal {index}: must be an object")
    action = validate_common(proposal, index)

    if action in {"modify", "flag"}:
        safe_memory_filename(
            proposal["target"],
            memory_dir=memory_dir,
            label=f"proposal {index} target",
            require_existing=True,
        )
    if action == "archive":
        safe_detail_filename(
            proposal["target"],
            memory_dir=memory_dir,
            label=f"proposal {index} target",
            require_existing=True,
        )
    if action == "split":
        original_target = safe_detail_filename(
            proposal["target"],
            memory_dir=memory_dir,
            label=f"proposal {index} target",
            require_existing=True,
        )
    else:
        original_target = None
    if action == "add":
        safe_detail_filename(
            proposal["target"],
            memory_dir=memory_dir,
            label=f"proposal {index} target",
            require_absent=True,
        )
    if action == "merge":
        targets = proposal["targets"]
        if not isinstance(targets, list) or len(targets) < 2:
            raise ValidationError(f"proposal {index}: merge targets must contain 2+ files")
        normalized_targets = []
        for target_index, target in enumerate(targets):
            normalized_targets.append(
                safe_detail_filename(
                    target,
                    memory_dir=memory_dir,
                    label=f"proposal {index} targets[{target_index}]",
                    require_existing=True,
                )
            )
        if len(set(normalized_targets)) != len(normalized_targets):
            raise ValidationError(f"proposal {index}: merge targets must be unique")
        survivor = safe_detail_filename(
            proposal["survivor"],
            memory_dir=memory_dir,
            label=f"proposal {index} survivor",
            require_existing=proposal["survivor"] in normalized_targets,
            require_absent=proposal["survivor"] not in normalized_targets,
        )
        index_changes = proposal.get("index_changes")
        if not isinstance(index_changes, dict):
            raise ValidationError(f"proposal {index}: index_changes must be an object")
        if set(index_changes) != {"remove", "add"}:
            raise ValidationError(f"proposal {index}: index_changes fields must be remove and add")
        if (
            not isinstance(index_changes["remove"], list)
            or not index_changes["remove"]
            or any(
                not isinstance(item, str) or not item.strip() or CONTROL.search(item)
                for item in index_changes["remove"]
            )
            or not isinstance(index_changes["add"], str)
            or not index_changes["add"].strip()
            or CONTROL.search(index_changes["add"])
        ):
            raise ValidationError(f"proposal {index}: index_changes must contain string remove[] and add")
        if len(set(index_changes["remove"])) != len(index_changes["remove"]):
            raise ValidationError(f"proposal {index}: index_changes.remove must be unique")
        tombstones = proposal.get("archive_tombstones")
        if not isinstance(tombstones, list) or not tombstones:
            raise ValidationError(f"proposal {index}: archive_tombstones must be an array")
        if any(
            not isinstance(item, str) or not item.strip() or CONTROL.search(item)
            for item in tombstones
        ):
            raise ValidationError(f"proposal {index}: archive_tombstones must be non-empty strings")
        expected_tombstones = len(normalized_targets) - int(survivor in normalized_targets)
        if len(tombstones) != expected_tombstones:
            raise ValidationError(
                f"proposal {index}: archive_tombstones must contain one row per absorbed target"
            )
        if type(proposal.get("net_index_lines")) is not int:
            raise ValidationError(f"proposal {index}: net_index_lines must be an integer")
        if proposal["net_index_lines"] != 1 - len(index_changes["remove"]):
            raise ValidationError(
                f"proposal {index}: net_index_lines must match the proposed index changes"
            )
        require_string_fields(proposal, index, {"merged_body"})
    elif action == "split":
        results = proposal["result_files"]
        if not isinstance(results, list) or len(results) < 2:
            raise ValidationError(f"proposal {index}: result_files must contain 2+ files")
        result_names = []
        for result_index, result in enumerate(results):
            if not isinstance(result, dict):
                raise ValidationError(
                    f"proposal {index}: result_files[{result_index}] must be an object"
                )
            expected = {"name", "purpose", "index_line", "body"}
            if set(result) != expected:
                raise ValidationError(
                    f"proposal {index}: result_files[{result_index}] fields must be {sorted(expected)}"
                )
            result_names.append(
                safe_detail_filename(
                    result["name"],
                    memory_dir=memory_dir,
                    label=f"proposal {index} result_files[{result_index}].name",
                    require_existing=result["name"] == original_target,
                    require_absent=result["name"] != original_target,
                )
            )
            for field in ("purpose", "index_line", "body"):
                if not isinstance(result[field], str) or not result[field].strip():
                    raise ValidationError(
                        f"proposal {index}: result_files[{result_index}].{field} must be non-empty"
                    )
            require_single_line_string(
                result["index_line"],
                f"proposal {index} result_files[{result_index}].index_line",
            )
        if len(set(result_names)) != len(result_names):
            raise ValidationError(f"proposal {index}: result file names must be unique")
        require_string_fields(proposal, index, {"original_index_line"})
        require_single_line_string(
            proposal["original_index_line"], f"proposal {index} original_index_line"
        )
    elif action == "modify":
        require_string_fields(
            proposal,
            index,
            {"current_excerpt", "proposed_excerpt", "check"},
            allow_empty={"proposed_excerpt"},
        )
    else:
        require_string_fields(
            proposal,
            index,
            {
                "current_excerpt",
                "proposed_excerpt",
                "archive_reason",
                "proposed_content",
                "index_line",
                "concern",
                "check",
            },
            allow_empty={"proposed_excerpt"},
        )
        if action == "archive":
            require_single_line_string(
                proposal["archive_reason"], f"proposal {index} archive_reason"
            )
        if action == "add":
            require_single_line_string(
                proposal["index_line"], f"proposal {index} index_line"
            )


def proposal_mutation_claims(proposal: dict[str, Any]) -> set[str]:
    action = proposal["action"]
    if action in {"modify", "archive", "add"}:
        return {proposal["target"]}
    if action == "merge":
        return set(proposal["targets"]) | {proposal["survivor"]}
    if action == "split":
        return {proposal["target"]} | {
            result["name"] for result in proposal["result_files"]
        }
    return set()


def validate_proposals(
    path: Path, *, memory_dir: Path, artifact_timestamp: str
) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot parse proposals.json: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError("proposals.json must be a top-level object")
    missing = REQUIRED_TOP_LEVEL - set(data)
    if missing:
        raise ValidationError(f"proposals.json is missing fields {sorted(missing)}")
    extra = set(data) - ALLOWED_TOP_LEVEL
    if extra:
        raise ValidationError(f"proposals.json has unknown top-level fields {sorted(extra)}")
    if not isinstance(data["curator"], str) or data["curator"] not in SHIPPED_CURATORS:
        raise ValidationError("proposals.json curator must name a shipped curator")
    if not isinstance(data["ran_at"], str):
        raise ValidationError("proposals.json ran_at must be a UTC timestamp string")
    try:
        ran_at = datetime.strptime(data["ran_at"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValidationError("proposals.json ran_at must match YYYY-MM-DDTHH:MM:SSZ") from exc
    artifact_time = datetime.strptime(artifact_timestamp, "%Y-%m-%dT%H-%M-%SZ")
    if ran_at != artifact_time:
        raise ValidationError("proposals.json ran_at must match its artifact directory timestamp")
    if "inputs_summary" in data and not isinstance(data["inputs_summary"], dict):
        raise ValidationError("proposals.json inputs_summary must be an object")
    if "skipped" in data and not isinstance(data["skipped"], list):
        raise ValidationError("proposals.json skipped must be an array")
    proposals = data.get("proposals")
    if not isinstance(proposals, list):
        raise ValidationError("proposals.json must contain a proposals array")
    ids: set[str] = set()
    mutation_claims: set[str] = set()
    curator = data["curator"]
    for index, proposal in enumerate(proposals):
        validate_proposal(proposal, index, memory_dir=memory_dir)
        if proposal["action"] not in CURATOR_ACTIONS[curator]:
            raise ValidationError(
                f"proposal {index}: action {proposal['action']!r} is not allowed for curator {curator!r}"
            )
        if proposal["id"] in ids:
            raise ValidationError(f"proposal {index}: duplicate proposal id {proposal['id']!r}")
        ids.add(proposal["id"])

        claims = proposal_mutation_claims(proposal)
        overlap = claims & mutation_claims
        mutation_claims |= claims
        if overlap:
            raise ValidationError(
                f"proposal {index}: mutation target collides with another proposal: {sorted(overlap)}"
            )
    return len(proposals)


def first_markdown_table_cells(line: str, count: int) -> list[str] | None:
    if not line.startswith("|") or count < 1:
        return None
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line[1:]:
        if character == "|" and not escaped:
            cells.append("".join(current).strip())
            current = []
            if len(cells) == count:
                return cells
            continue
        current.append(character)
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
    return None


def visible_markdown_lines(lines: list[str]) -> list[str]:
    visible_lines: list[str] = []
    in_comment = False
    fence_character: str | None = None
    fence_length = 0
    for original in lines:
        if fence_character is not None:
            closing_fence = re.fullmatch(
                rf"\s{{0,3}}{re.escape(fence_character)}{{{fence_length},}}\s*",
                original,
            )
            if closing_fence:
                fence_character = None
                fence_length = 0
            continue

        line = original
        visible = ""
        cursor = 0
        while cursor < len(line):
            if in_comment:
                closing = line.find("-->", cursor)
                if closing < 0:
                    cursor = len(line)
                    break
                in_comment = False
                cursor = closing + 3
                continue
            opening = line.find("<!--", cursor)
            if opening < 0:
                visible += line[cursor:]
                break
            visible += line[cursor:opening]
            in_comment = True
            cursor = opening + 4

        opening_fence = re.fullmatch(
            r"\s{0,3}(?:(`{3,})([^`]*)|(~{3,})(.*))", visible
        )
        if opening_fence:
            marker = opening_fence.group(1) or opening_fence.group(3)
            fence_character = marker[0]
            fence_length = len(marker)
            continue
        visible_lines.append(visible)
    if in_comment:
        raise ValidationError("archive index contains an unterminated HTML comment")
    if fence_character is not None:
        raise ValidationError("archive index contains an unterminated fenced block")
    return visible_lines


def archive_rows(archive_index: Path, target: str) -> list[str]:
    require_regular_file(archive_index, "archive index")
    try:
        lines = visible_markdown_lines(
            archive_index.read_text(encoding="utf-8").splitlines()
        )
    except (OSError, UnicodeError) as exc:
        raise ValidationError(f"cannot read archive index: {exc}") from exc
    header = re.compile(r"^\|\s*Date\s*\|\s*Memory\s*\|\s*Reason\s*\|\s*$")
    separator = re.compile(r"^\|\s*:?-{3,}:?\s*\|\s*:?-{3,}:?\s*\|\s*:?-{3,}:?\s*\|\s*$")
    headers = [index for index, line in enumerate(lines) if header.fullmatch(line)]
    if len(headers) != 1:
        raise ValidationError("archive index must contain exactly one canonical archive table")
    header_index = headers[0]
    if header_index + 1 >= len(lines) or not separator.fullmatch(lines[header_index + 1]):
        raise ValidationError("archive index table must have a canonical separator row")

    target_link = f"archive/{target}"
    link_pattern = re.compile(r"^\[[^\]\r\n]+\]\(([^)\r\n]+)\)$")
    dates = []
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            break
        cells = first_markdown_table_cells(line, 2)
        if cells is None:
            raise ValidationError("archive index table contains a malformed row")
        date_cell, memory_cell = cells
        link = link_pattern.fullmatch(memory_cell)
        if link and link.group(1) == target_link:
            dates.append(require_iso_date(date_cell, "archive index row date"))
        elif target_link in memory_cell:
            raise ValidationError("archive index has a malformed row for target")
    return dates


def archived_stamps(path: Path) -> list[str]:
    if not path.exists():
        return []
    require_regular_file(path, "archive target")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValidationError(f"cannot read archive target: {exc}") from exc
    if not lines or lines[0] != "---":
        raise ValidationError("archive target must begin with YAML frontmatter")
    try:
        closing = lines.index("---", 1)
    except ValueError as exc:
        raise ValidationError("archive target has unterminated YAML frontmatter") from exc

    stamps = []
    for line in lines[1:closing]:
        if (
            re.match(r'''^\s*(?:archived|["']archived["'])\s*:''', line)
            and not line.startswith("archived:")
        ):
            raise ValidationError("archive target has a malformed archived field")
        if line.startswith("archived:"):
            value = line.partition(":")[2].strip()
            stamps.append(require_iso_date(value, "archive target archived date"))
    return stamps


def cmd_archive_state(args: argparse.Namespace) -> dict[str, Any]:
    binding = validate_memory_binding(Path.cwd(), require_clean=False)
    memory_dir = Path(binding["memory_dir"])
    require_iso_date(args.today, "--today")
    target = safe_detail_filename(
        args.target,
        memory_dir=memory_dir,
        label="archive target",
    )
    root = memory_dir / target
    destination = memory_dir / "archive" / target
    ensure_inside(memory_dir, destination, "archive destination")
    ensure_no_symlink_components(destination, memory_dir, "archive destination")
    if root.is_symlink() or destination.is_symlink():
        raise ValidationError("archive target and destination must not be symlinks")
    root_exists = root.is_file()
    destination_exists = destination.is_file()
    if root.exists() and not root_exists:
        raise ValidationError("archive root target must be a regular file")
    if destination.exists() and not destination_exists:
        raise ValidationError("archive destination must be a regular file")

    rows = archive_rows(memory_dir / "ARCHIVE.md", target)
    if len(rows) > 1:
        raise ValidationError("archive index contains duplicate rows for target")
    if root_exists and destination_exists:
        raise ValidationError("archive target exists at both root and destination")
    if not root_exists and not destination_exists:
        raise ValidationError("archive target exists at neither root nor destination")
    if destination_exists:
        if len(rows) != 1:
            raise ValidationError("archive destination requires exactly one archive row")
        stamps = archived_stamps(destination)
        if stamps != rows:
            raise ValidationError("completed archive stamp must match its single row date")
        return {
            **binding,
            "target": target,
            "status": "complete",
            "archive_date": rows[0],
            "append_row": False,
            "insert_stamp": False,
        }

    archive_date = rows[0] if rows else args.today
    stamps = archived_stamps(root)
    if len(stamps) > 1:
        raise ValidationError("archive target contains duplicate archived stamps")
    if stamps and stamps[0] != archive_date:
        raise ValidationError("archive target stamp does not match the required archive date")
    return {
        **binding,
        "target": target,
        "status": "resume" if rows else "fresh",
        "archive_date": archive_date,
        "append_row": not rows,
        "insert_stamp": not stamps,
    }


def cmd_resolve(_: argparse.Namespace) -> dict[str, Any]:
    return validate_memory_binding(Path.cwd(), require_clean=True)


def cmd_artifact(args: argparse.Namespace) -> dict[str, Any]:
    binding = validate_memory_binding(
        Path.cwd(), require_clean=not args.for_commit
    )
    memory_dir = Path(binding["memory_dir"])
    ts, path = resolve_artifact(memory_dir, args.timestamp, for_create=args.for_create)
    result: dict[str, Any] = {**binding, "timestamp": ts, "dream_dir": str(path)}
    if not args.for_create:
        result["proposal_count"] = validate_proposals(
            path / "proposals.json", memory_dir=memory_dir, artifact_timestamp=ts
        )
    if args.for_commit:
        require_regular_file(path / "inputs.json", "inputs.json")
        artifact_paths = {
            f".dreams/{ts}/inputs.json",
            f".dreams/{ts}/proposals.json",
            f".dreams/{ts}/REPORT.md",
        }
        changed = require_allowed_changes(memory_dir, artifact_paths)
        if changed != artifact_paths:
            raise ValidationError(
                "new dream artifact must change exactly inputs.json, proposals.json, and REPORT.md"
            )
        result["changed_paths"] = sorted(changed)
    return result


def cmd_changes(args: argparse.Namespace) -> dict[str, Any]:
    binding = validate_memory_binding(Path.cwd(), require_clean=False)
    memory_dir = Path(binding["memory_dir"])
    allowed = {
        safe_relative_change(
            value, memory_dir=memory_dir, label=f"allow[{index}]"
        )
        for index, value in enumerate(args.allow)
    }
    if not allowed:
        raise ValidationError("changes requires at least one reviewed --allow path")
    changed = require_allowed_changes(memory_dir, allowed)
    if not changed:
        raise ValidationError("memory git has no reviewed changes to commit")
    omitted = allowed - changed
    if omitted:
        raise ValidationError(
            "reviewed allowlist includes paths that did not change: "
            + ", ".join(sorted(omitted))
        )
    if args.staged:
        if not args.expect_digest:
            raise ValidationError("--staged requires the reviewed --expect-digest")
        require_no_unstaged_changes(memory_dir)
    elif args.expect_digest:
        raise ValidationError("--expect-digest is valid only with --staged")
    digest = change_digest(
        memory_dir,
        changed,
        source="index" if args.staged else "worktree",
    )
    if args.expect_digest:
        if not re.fullmatch(r"[0-9a-f]{64}", args.expect_digest):
            raise ValidationError("--expect-digest must be a lowercase SHA-256 digest")
        if digest != args.expect_digest:
            raise ValidationError(
                "staged bytes do not match the reviewed change digest; inspect and re-approve the final diff"
            )
    result = {
        **binding,
        "changed_paths": sorted(changed),
        "allowed_paths": sorted(allowed),
        "change_digest": digest,
        "source": "index" if args.staged else "worktree",
    }
    if args.staged:
        tree_sha = run_git(["write-tree"], cwd=memory_dir)
        tree_digest = change_digest(
            memory_dir,
            changed,
            source="tree",
            tree_sha=tree_sha,
        )
        if tree_digest != digest:
            raise ValidationError("captured tree does not match the validated index")
        result["tree_sha"] = tree_sha
        reviewed_ref = head_identity(memory_dir)
        if reviewed_ref == "DETACHED":
            raise ValidationError(
                "memory apply requires HEAD to name a local branch; leave detached HEAD before final review"
            )
        result["base_head"] = run_git(["rev-parse", "HEAD"], cwd=memory_dir)
        if head_identity(memory_dir) != reviewed_ref:
            raise ValidationError("memory HEAD identity changed while capturing the tree")
        result["head_ref"] = reviewed_ref
    return result


def cmd_commit(args: argparse.Namespace) -> dict[str, Any]:
    binding = validate_memory_binding(Path.cwd(), require_clean=False)
    memory_dir = Path(binding["memory_dir"])
    tree_sha = require_object_sha(args.tree, "--tree")
    base_head = require_object_sha(args.base_head, "--base-head")
    if not args.head_ref.startswith("refs/heads/"):
        raise ValidationError("--head-ref must name the reviewed local branch")
    checked_ref = subprocess.run(
        ["git", "check-ref-format", args.head_ref],
        cwd=memory_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if checked_ref.returncode != 0:
        raise ValidationError("--head-ref must name a valid local branch")
    if run_git(["cat-file", "-t", tree_sha], cwd=memory_dir) != "tree":
        raise ValidationError("--tree must identify a Git tree object")
    if head_identity(memory_dir) != args.head_ref:
        raise ValidationError("memory HEAD identity changed after final review")
    if run_git(["rev-parse", "HEAD"], cwd=memory_dir) != base_head:
        raise ValidationError("memory HEAD changed after final review")
    if not re.fullmatch(r"[0-9a-f]{64}", args.expect_digest):
        raise ValidationError("--expect-digest must be a lowercase SHA-256 digest")
    if not isinstance(args.message, str) or not args.message.strip() or CONTROL.search(args.message):
        raise ValidationError("--message must be a non-empty single line")

    allowed = {
        safe_relative_change(value, memory_dir=memory_dir, label=f"allow[{index}]")
        for index, value in enumerate(args.allow)
    }
    if not allowed:
        raise ValidationError("commit requires at least one reviewed --allow path")
    changed = tree_changed_paths(memory_dir, base_head, tree_sha)
    unexpected = changed - allowed
    omitted = allowed - changed
    if unexpected:
        raise ValidationError(
            "approved tree changes paths outside the reviewed allowlist: "
            + ", ".join(sorted(unexpected))
        )
    if omitted:
        raise ValidationError(
            "reviewed allowlist includes paths absent from the approved tree diff: "
            + ", ".join(sorted(omitted))
        )
    resurrected = sorted(
        relative
        for relative in changed
        if tree_entry(memory_dir, tree_sha, relative) is None
        and os.path.lexists(memory_dir / relative)
    )
    if resurrected:
        raise ValidationError(
            "reviewed deleted paths reappeared after final review: "
            + ", ".join(resurrected)
        )
    digest = change_digest(
        memory_dir,
        changed,
        source="tree",
        tree_sha=tree_sha,
    )
    if digest != args.expect_digest:
        raise ValidationError("approved tree bytes do not match the reviewed digest")

    require_no_unstaged_changes(memory_dir)
    if run_git(["write-tree"], cwd=memory_dir) != tree_sha:
        raise ValidationError("memory index changed after final tree review")

    new_commit = run_git(
        ["commit-tree", tree_sha, "-p", base_head, "-m", args.message],
        cwd=memory_dir,
    )
    if head_identity(memory_dir) != args.head_ref:
        raise ValidationError("memory HEAD identity changed while creating the commit")
    if run_git(["rev-parse", "HEAD"], cwd=memory_dir) != base_head:
        raise ValidationError("memory HEAD changed while creating the commit")
    resurrected = sorted(
        relative
        for relative in changed
        if tree_entry(memory_dir, tree_sha, relative) is None
        and os.path.lexists(memory_dir / relative)
    )
    if resurrected:
        raise ValidationError(
            "reviewed deleted paths reappeared while creating the commit: "
            + ", ".join(resurrected)
        )
    require_no_unstaged_changes(memory_dir)
    if run_git(["write-tree"], cwd=memory_dir) != tree_sha:
        raise ValidationError("memory index changed while creating the commit")
    run_git(["update-ref", args.head_ref, new_commit, base_head], cwd=memory_dir)
    return {
        **binding,
        "commit_sha": new_commit,
        "tree_sha": tree_sha,
        "base_head": base_head,
        "head_ref": args.head_ref,
        "change_digest": digest,
        "changed_paths": sorted(changed),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("resolve", help="validate and print the memory binding")

    bind = subcommands.add_parser(
        "bind", help="write the memory binding for this repository, then validate it"
    )
    bind.add_argument(
        "--memory-dir",
        required=True,
        help="absolute path to a private memory directory outside this repository",
    )
    bind.add_argument(
        "--force",
        action="store_true",
        help="repoint an existing binding, or claim a store bound to another repository",
    )

    artifact = subcommands.add_parser("artifact", help="validate or allocate a dream artifact")
    artifact.add_argument("timestamp", help="YYYY-MM-DDTHH-MM-SSZ or latest")
    artifact.add_argument(
        "--for-create",
        action="store_true",
        help="validate a new timestamp path without requiring files to exist",
    )
    artifact.add_argument(
        "--for-commit",
        action="store_true",
        help="validate a newly written artifact and reject unrelated memory changes",
    )

    changes = subcommands.add_parser(
        "changes", help="reject memory changes outside an exact reviewed allowlist"
    )
    changes.add_argument(
        "--allow", action="append", default=[], help="reviewed memory-relative path"
    )
    changes.add_argument(
        "--staged",
        action="store_true",
        help="hash the staged blobs and require no unstaged changes",
    )
    changes.add_argument(
        "--expect-digest",
        help="reviewed worktree digest that the staged blobs must match",
    )

    commit = subcommands.add_parser(
        "commit", help="commit one explicitly approved immutable tree"
    )
    commit.add_argument("--tree", required=True, help="approved Git tree SHA")
    commit.add_argument("--base-head", required=True, help="HEAD reviewed with the tree")
    commit.add_argument(
        "--head-ref", required=True, help="reviewed local branch ref"
    )
    commit.add_argument(
        "--expect-digest", required=True, help="approved change-content digest"
    )
    commit.add_argument(
        "--allow", action="append", default=[], help="reviewed memory-relative path"
    )
    commit.add_argument("--message", required=True, help="single-line commit message")

    archive = subcommands.add_parser(
        "archive-state", help="classify an archive target before applying it"
    )
    archive.add_argument("target", help="plain detail filename")
    archive.add_argument("--today", required=True, help="current date as YYYY-MM-DD")
    return parser


def cmd_bind(args: argparse.Namespace) -> dict[str, str]:
    """Write both halves of the binding, then prove the result validates.

    The two recorded files were written by hand, in a shell, from a doc -- while
    being read by this script, in Python. Nothing kept the two spellings in
    agreement, and both Windows bugs fixed alongside this came from exactly that
    split. Writing both files here, in the same code that reads them, removes
    the disagreement by construction.

    STRICTLY PREFLIGHTED. Every refusal runs before anything is created or
    written, because the first version did not and that was the bug: a bind that
    failed validation had already created a git repo, an archive/ and a
    MEMORY.md, and had already overwritten the previous binding -- destroying a
    working configuration while exiting non-zero. Nothing below the PREFLIGHT
    marker may raise for a reason that could have been known above it.

    Deliberately conservative about existing state: it creates the directory,
    archive/, a git repo and MEMORY.md only when ABSENT, never resetting one
    already there, and refuses to repoint a binding or claim a store bound
    elsewhere unless --force. A memory store is the one thing here with no
    upstream copy.

    --force relaxes exactly one thing: the semantic "this points somewhere else"
    refusal. It has never been a reason to skip a SAFETY check, and used to skip
    the symlink check by accident, because those checks lived inside the same
    read_single_line call that read the value being compared.
    """
    repo = Path.cwd().resolve(strict=True)
    identity = repository_identity(repo)

    raw = args.memory_dir
    if CONTROL.search(raw):
        raise ValidationError("--memory-dir contains a control character")
    reject_traversal(raw, "--memory-dir")
    target = Path(native_path(raw))
    if not target.is_absolute():
        raise ValidationError(f"--memory-dir must be absolute: {raw}")
    reject_nonlocal_root(target, "--memory-dir")

    # resolve(strict=False), not abspath: abspath is purely lexical, so a
    # symlinked or junctioned PARENT stayed unresolved and the containment check
    # below ran against a path that pointed somewhere else entirely. Verified:
    # `--memory-dir /outside/link-to-repo/inside` built a whole memory store
    # INSIDE the repository, which is the exact thing require_outside_repository
    # exists to prevent.
    target = target.resolve(strict=False)
    if target.is_symlink():
        raise ValidationError(f"--memory-dir must not be a symlink: {target}")
    if os.path.lexists(target) and not target.is_dir():
        raise ValidationError(f"--memory-dir exists and is not a directory: {target}")

    require_outside_repository(target, repo, identity)

    binding = repo / ".context-os" / "memory-directory"
    marker = target / ".context-os-repository"

    # Safety checks on both control paths, regardless of --force.
    for control, label in ((binding, ".context-os/memory-directory"),
                           (marker, "memory repository marker")):
        if os.path.lexists(control) and (control.is_symlink() or not control.is_file()):
            raise ValidationError(
                f"{label} must be a regular file, not a symlink or special file: {control}"
            )
    if binding.parent.is_symlink():
        raise ValidationError(f".context-os must not be a symlink: {binding.parent}")

    # Semantic refusals -- the only thing --force is allowed to relax.
    if not args.force:
        if binding.is_file():
            current = read_single_line(binding, ".context-os/memory-directory")
            if not same_directory(current, str(target)):
                raise ValidationError(
                    f".context-os/memory-directory already points at {current}. "
                    "Re-run with --force to repoint it, after confirming the existing "
                    "memory store is somewhere you can still reach."
                )
        if marker.is_file():
            existing = read_single_line(marker, "memory repository marker")
            if not same_directory(existing, identity):
                raise ValidationError(
                    f"{target} is already bound to a different repository ({existing}). "
                    "Re-run with --force only if you mean to hand this memory store to "
                    "this repository."
                )

    # A store that already exists must satisfy the rules the validator will apply
    # anyway. Checking here keeps a doomed bind from writing the repo's binding
    # file first and reporting the failure second.
    if (target / ".git").exists() and run_git(["remote"], cwd=target):
        raise ValidationError(
            f"{target} is a git repository with remotes; a memory store must have none"
        )

    # ---- PREFLIGHT COMPLETE. Everything below creates or writes. ----

    created = []
    for directory in (target, target / "archive"):
        if not directory.exists():
            directory.mkdir(parents=True)
            created.append(str(directory))

    if not (target / ".git").exists():
        run_git(["init", "-q"], cwd=target)
        # Pin line endings on the store we just made. Git for Windows sets
        # core.autocrlf=true at SYSTEM level, and the review flow digests
        # worktree bytes and compares them against the staged blob -- so an
        # inherited autocrlf rewrites the bytes between those two reads and
        # every approved change is rejected as tampered. The test fixtures
        # pinned this and thereby HID it: the suite passed while the real
        # Windows workflow was broken for anyone whose store bind created.
        run_git(["config", "core.autocrlf", "false"], cwd=target)
        run_git(["config", "core.eol", "lf"], cwd=target)
        created.append(str(target / ".git"))

    index = target / "MEMORY.md"
    if not index.exists():
        index.write_text("# Memory\n", encoding="utf-8")
        created.append(str(index))

    binding.parent.mkdir(parents=True, exist_ok=True)
    # Newline-terminated single line: read_single_line rejects anything else.
    # Written via replace_control_file so an existing symlink is REPLACED rather
    # than followed.
    replace_control_file(binding, f"{target}\n", ".context-os/memory-directory")
    replace_control_file(marker, f"{identity}\n", "memory repository marker")

    # Prove it. A bind that reports success without the validator agreeing is
    # the failure this command exists to prevent, so run the real check rather
    # than trusting that we wrote the right bytes. require_clean stays off: the
    # marker we just wrote is legitimately uncommitted.
    result = validate_memory_binding(repo, require_clean=False)
    result["created"] = ", ".join(created) if created else "nothing (all present)"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "resolve":
            result = cmd_resolve(args)
        elif args.command == "bind":
            result = cmd_bind(args)
        elif args.command == "artifact":
            if args.for_create and args.for_commit:
                raise ValidationError("--for-create and --for-commit are mutually exclusive")
            result = cmd_artifact(args)
        elif args.command == "changes":
            result = cmd_changes(args)
        elif args.command == "commit":
            result = cmd_commit(args)
        elif args.command == "archive-state":
            result = cmd_archive_state(args)
        else:  # pragma: no cover - argparse prevents this.
            parser.error("unknown command")
    except ValidationError as exc:
        print(f"validate-memory: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
