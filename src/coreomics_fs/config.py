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