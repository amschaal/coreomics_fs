#!/usr/bin/env python3
# winlnk.py — writer for Windows Shell Link (.lnk) shortcut files, backed by pylnk3.
#
# The build host is Linux/Samba and the shortcut *targets* (a UNC \\server\share
# path, or a Z:\ mapped-drive path) don't exist on it, so we build the shortcut
# in memory rather than stat'ing the target.
#
# Why pylnk3 and not a hand-rolled encoder: Windows Explorer reads a shortcut's
# target from its binary LinkTargetIDList (a shell "PIDL") or an expand-string —
# NOT from a bare relative/working path. A minimal hand-written .lnk therefore
# opens with an *empty* target. pylnk3 emits the full, Explorer-resolvable
# structure. It is an *optional* dependency (only needed when [paths]
# windows_views_root is set), imported lazily here so the rest of coreomics-fs
# stays dependency-light. Install on the build host with: pip install pylnk3
# (or: pip install 'coreomics-fs[windows]').


def _require_pylnk3():
    try:
        import pylnk3
    except ImportError as e:  # pragma: no cover - exercised only without the dep
        raise SystemExit(
            "[paths] windows_views_root is configured but the 'pylnk3' package "
            "is not installed on the build host. Install it with:\n"
            "    pip install pylnk3\n"
            "(or: pip install 'coreomics-fs[windows]')"
        ) from e
    return pylnk3


def write_unc_lnk(lnk_path, unc_target: str) -> None:
    """Write a folder shortcut to a UNC path.

    ``unc_target`` is the full ``\\\\server\\share\\...`` path. pylnk3's
    ``for_file`` handles UNC targets without touching the local filesystem: it
    builds a remote ``LinkInfo`` plus an environment expand-string that Explorer
    resolves to the share path."""
    pylnk3 = _require_pylnk3()
    # Passing lnk_name makes for_file save to that path itself.
    pylnk3.for_file(unc_target, lnk_name=str(lnk_path))


def write_drive_lnk(lnk_path, drive_target: str) -> None:
    """Write a folder shortcut to a mapped-drive path (e.g. ``Z:\\a\\b\\c``).

    Built directly as a ``My Computer -> Drive -> folder...`` LinkTargetIDList.
    We force every path segment to ``TYPE_FOLDER`` — ``for_file`` would mislabel
    the final segment as a *file* because the target doesn't exist on the Linux
    build host, which yields a file shortcut instead of a folder one."""
    pylnk3 = _require_pylnk3()
    lnk = pylnk3.create(str(lnk_path))
    lnk.link_flags.IsUnicode = True
    lnk.link_info = None
    levels = list(pylnk3.path_levels(drive_target))   # ['Z:\\', 'Z:\\a', ...]
    items = [pylnk3.RootEntry(pylnk3.ROOT_MY_COMPUTER), pylnk3.DriveEntry(levels[0])]
    for level in levels[1:]:
        items.append(_folder_segment(pylnk3, level))
    lnk.shell_item_id_list = pylnk3.LinkTargetIDList()
    lnk.shell_item_id_list.items = items
    lnk.save()


def _folder_segment(pylnk3, level):
    """A PathSegmentEntry for ``level`` forced to TYPE_FOLDER.

    pylnk3's ``create_for_path`` signature differs across versions — newer takes
    ``(path, entry_type)``, older takes ``(path)`` and infers the type from
    ``os.path.isdir`` (which is False for a Windows target path on the Linux
    build host, so it would wrongly pick TYPE_FILE). We set ``.type`` explicitly
    after creation to be correct on every version."""
    try:
        seg = pylnk3.PathSegmentEntry.create_for_path(level, pylnk3.TYPE_FOLDER)
    except TypeError:
        seg = pylnk3.PathSegmentEntry.create_for_path(level)
    seg.type = pylnk3.TYPE_FOLDER
    return seg
