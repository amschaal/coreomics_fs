import configparser
import os
import sys
from pathlib import Path

# The override notice prints at most once per process (load_config runs a few
# times) so a locked key doesn't spam stderr.
_OVERRIDE_NOTIFIED = False


def _override_path():
    """The admin override file, or None.

    Layered on top of the base config so deployer-locked keys (e.g. the canonical
    and views directories) win over whatever a user put in their own config.
    Lives at ``<package_dir>/config.override.ini`` — admin-owned in a shared
    install — or wherever ``$CONFIG_OVERRIDE_PATH`` points (tests/admin)."""
    if env := os.getenv('CONFIG_OVERRIDE_PATH'):
        p = Path(env)
        return p if p.is_file() else None
    p = Path(__file__).parent / "config.override.ini"
    return p if p.is_file() else None


def _apply_override(cfg, opath):
    """Layer the override onto ``cfg`` per-key, noting any value it changes.

    Uses ``raw=True`` throughout so ``%``-interpolation can't choke on
    ``date_format``'s ``%%Y_%%m_%%d`` and so change-detection is a literal
    string compare."""
    global _OVERRIDE_NOTIFIED
    ov = configparser.ConfigParser()
    ov.read(opath)
    notices = []
    for section in ov.sections():
        for key, new in ov.items(section, raw=True):
            old = cfg.get(section, key, raw=True, fallback=None)
            if old is not None and old != new:
                notices.append(f"  [{section}] {key}: {old!r} -> {new!r}")
    cfg.read(opath)   # apply the merge (overwrite existing keys, add new ones)
    if notices and not _OVERRIDE_NOTIFIED:
        print(f"note: {opath} overrides these configured values:\n"
              + "\n".join(notices), file=sys.stderr)
        _OVERRIDE_NOTIFIED = True


def load_config():
    candidates = []
    if env := os.getenv('CONFIG_PATH'):
        candidates.append(Path(env))
    candidates.append(Path.home() / ".config" / "coreomics" / "config.ini")
    candidates.append(Path(__file__).parent / "config.ini")

    cfg = None
    for path in candidates:
        if path.is_file():
            cfg = configparser.ConfigParser()
            cfg.read(path)
            break
    if cfg is None:
        searched = "\n  ".join(str(p) for p in candidates)
        raise FileNotFoundError(f"Config file not found. Searched:\n  {searched}")

    # Layer the admin override on top of the base config, if present.
    opath = _override_path()
    if opath:
        _apply_override(cfg, opath)
    return cfg


def get_share_subdirectory(cfg=None):
    """Return the validated ``[paths] share_subdirectory`` name, or None if unset.

    Returns None when the key is blank/absent. Raises ValueError if it is set but
    is not a proper single-component subdirectory name (absolute, contains a path
    separator, or is ``.``/``..``)."""
    if cfg is None:
        cfg = load_config()
    name = (cfg.get("paths", "share_subdirectory", fallback="") or "").strip()
    if not name:
        return None
    seps = [s for s in (os.sep, os.altsep, "/", "\\") if s]
    if (name in (".", "..") or os.path.isabs(name)
            or any(s in name for s in seps) or Path(name).name != name):
        raise ValueError(
            f"Invalid [paths] share_subdirectory {name!r}: must be a single "
            "subdirectory name (not absolute, no path separators, not '.' or '..')."
        )
    return name


def share_output_dir(canonical_dir, cfg=None, create=False):
    """Directory to write a project's README into / link as a share.

    Returns ``<canonical_dir>/<share_subdirectory>`` when that key is configured,
    otherwise ``canonical_dir`` unchanged. Creates the subdirectory when
    ``create=True``."""
    if cfg is None:
        cfg = load_config()
    base = Path(canonical_dir)
    name = get_share_subdirectory(cfg)
    if not name:
        return base
    out = base / name
    if create:
        out.mkdir(parents=True, exist_ok=True)
    return out