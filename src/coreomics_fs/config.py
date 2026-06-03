import configparser
import os
from pathlib import Path


def load_config():
    candidates = []
    if env := os.getenv('CONFIG_PATH'):
        candidates.append(Path(env))
    candidates.append(Path.home() / ".config" / "coreomics" / "config.ini")
    candidates.append(Path(__file__).parent / "config.ini")

    for path in candidates:
        if path.is_file():
            cfg = configparser.ConfigParser()
            cfg.read(path)
            return cfg

    searched = "\n  ".join(str(p) for p in candidates)
    raise FileNotFoundError(f"Config file not found. Searched:\n  {searched}")


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