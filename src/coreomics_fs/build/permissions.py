"""Ownership/permission enforcement for the canonical and view trees.

The goal is to stop lab users (who reach the tree as SMB clients) from deleting
canonical project directories while still letting them manage data *inside* their
own project. On POSIX the right to delete an entry is governed by write permission
on its *parent* directory, so we keep everything above the project level group
``r-x`` (no write) and make only the project ``<id>`` directory (and its ``share``
subdir) group-writable.

    canonical_root/<YYYY>/<MM>/      02755  group r-x   <- users CANNOT delete <id>
    canonical_root/<YYYY>/<MM>/<id>/ 03775  group rwx+t <- users write; sticky
        .submission/                 0755   group r-x   <- protected metadata
            submission.json          0644
        share/                       03775  group rwx+t <- users share data here
            README.md                0644   (owned by service user)
    views_root/ (+ .versions tree)   02755  group r-x   <- browse only, no delete

The setgid bit (``02xxx``) makes new subdirs/files inherit the lab group, so the
bulk of the tree stays correctly grouped without per-file ``chgrp``.

The sticky bit (``01xxx``) on the group-writable ``<id>`` and ``share`` dirs means
an entry can only be deleted/renamed by *its owner* (or the dir owner / root). So a
recursive ``rm -rf`` from a lab user can't sweep through and delete the ``share`` /
``.submission`` directories (owned by the service user) or another user's files —
only the user's *own* files. The build runs as the dir owner, so it is unaffected.

The whole feature is opt-in: with no ``[permissions] group`` configured,
``load_perm_policy`` returns ``None`` and callers do nothing.
"""
import grp
import os
import pwd
import stat
import sys

# Directory/file modes (see module docstring). Leading 0o2 = setgid, 0o3 = setgid+sticky.
PARENT_MODE = 0o2755    # canonical_root, <YYYY>, <MM>, views tree dirs
PROJECT_MODE = 0o3775   # the project <id> dir + share subdir (group-writable, sticky)
META_DIR_MODE = 0o755   # <id>/.submission (not group-writable)
META_FILE_MODE = 0o644  # <id>/.submission/submission.json


class PermPolicy:
    """Resolved ownership/permission policy. ``uid`` is -1 when no owner is
    configured (``os.chown`` leaves the owner unchanged); ``gid`` is always a
    real group id."""

    def __init__(self, gid, uid=-1):
        self.gid = gid
        self.uid = uid


def load_perm_policy(cfg):
    """Return a :class:`PermPolicy`, or ``None`` when enforcement is disabled.

    Enforcement is disabled when ``[permissions] group`` is blank/absent. If the
    group (or a configured owner) cannot be resolved, fail fast with a clear
    message rather than silently skipping protection."""
    group = (cfg.get("permissions", "group", fallback="") or "").strip()
    if not group:
        return None
    try:
        gid = grp.getgrnam(group).gr_gid
    except KeyError:
        sys.exit(f"[permissions] group {group!r} does not exist on this system")

    owner = (cfg.get("permissions", "owner", fallback="") or "").strip()
    uid = -1
    if owner:
        try:
            uid = pwd.getpwnam(owner).pw_uid
        except KeyError:
            sys.exit(f"[permissions] owner {owner!r} does not exist on this system")
    return PermPolicy(gid, uid)


def _apply(path, mode, policy, *, follow=True):
    """Idempotently set ``mode`` and group (and owner, if configured) on ``path``.

    Failures are logged and swallowed so a single un-chmod-able path (e.g. a file
    a lab user created and owns) never aborts the build."""
    try:
        os.chown(path, policy.uid, policy.gid, follow_symlinks=follow)
    except OSError as e:
        print(f"perm: chown failed for {path}: {e}")
    if mode is not None and follow:
        # Don't chmod symlinks — Linux ignores symlink mode bits and there's no
        # lchmod; the parent directory's mode governs deletion of the link.
        try:
            os.chmod(path, mode)
        except OSError as e:
            print(f"perm: chmod failed for {path}: {e}")


def enforce_project(dst, policy, canon_root):
    """Apply the canonical permission model to a single project directory.

    Sets the project ``<id>`` dir group-writable, its ``.submission`` metadata
    read-only to the group, and bumps every ancestor up to ``canon_root`` to the
    group-``r-x`` parent mode so the project can't be deleted from above. Cheap
    and idempotent — safe to call on every build."""
    dst = os.fspath(dst)
    _apply(dst, PROJECT_MODE, policy)

    sub = os.path.join(dst, ".submission")
    if os.path.isdir(sub):
        _apply(sub, META_DIR_MODE, policy)
        sj = os.path.join(sub, "submission.json")
        if os.path.isfile(sj):
            _apply(sj, META_FILE_MODE, policy)

    # Walk up <id> -> <MM> -> <YYYY> -> ... -> canon_root, locking each parent.
    canon_root = os.path.abspath(os.fspath(canon_root))
    parent = os.path.dirname(os.path.abspath(dst))
    while True:
        _apply(parent, PARENT_MODE, policy)
        if parent == canon_root:
            break
        up = os.path.dirname(parent)
        if up == parent:   # reached filesystem root without hitting canon_root
            break
        parent = up


def enforce_share(share_dir, policy):
    """Make a project's ``share`` subdirectory group-writable (``02775``).

    Lab users do their data sharing inside this dir, so it gets the same
    group-``rwx`` mode as the project root. The dir is created *after*
    ``enforce_project`` runs (by ``share_output_dir``), so this is applied
    separately once it exists. User content inside is left untouched."""
    _apply(os.fspath(share_dir), PROJECT_MODE, policy)


def enforce_tree(root, policy, *, project_dirs_writable=False, share_name=None):
    """Recursively apply the parent mode to every directory under ``root``.

    Used for the views tree and for the one-time ``--enforce-permissions``
    migration. Symlinks are chgrp'd (without following) but never chmod'd. When
    ``project_dirs_writable`` is set, a directory containing a ``.submission``
    child is treated as a canonical project dir and made group-writable, its
    ``.submission`` left read-only — so a full canonical-tree sweep reproduces
    exactly what ``enforce_project`` would do per project. A ``share_name`` child
    of a project dir is made group-writable and *not* recursed into, so existing
    user content keeps its modes."""
    root = os.fspath(root)
    if not os.path.isdir(root):
        return
    _apply(root, PARENT_MODE, policy)
    for dirpath, dirnames, filenames in os.walk(root):
        is_project = project_dirs_writable and ".submission" in dirnames
        if is_project:
            _apply(dirpath, PROJECT_MODE, policy)
        skip = []
        for d in dirnames:
            p = os.path.join(dirpath, d)
            if os.path.islink(p):
                _apply(p, None, policy, follow=False)
            elif is_project and d == ".submission":
                _apply(p, META_DIR_MODE, policy)
            elif is_project and share_name and d == share_name:
                _apply(p, PROJECT_MODE, policy)
                skip.append(d)   # don't re-mode user content inside share/
            else:
                _apply(p, PARENT_MODE, policy)
        for d in skip:
            dirnames.remove(d)
        for f in filenames:
            p = os.path.join(dirpath, f)
            if os.path.islink(p):
                _apply(p, None, policy, follow=False)
            elif f == "submission.json":
                _apply(p, META_FILE_MODE, policy)
            # other files keep their existing mode; only ensure group ownership
            else:
                _apply(p, None, policy)
