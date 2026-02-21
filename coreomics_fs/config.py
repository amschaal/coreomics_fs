import configparser
import os
from pathlib import Path


def load_config():
    # ----------------------------------------------------------------------
    # Load configuration
    # ----------------------------------------------------------------------
    cfg_path = Path(__file__).parent / "config.ini"
    CONFIG_PATH = os.getenv('CONFIG_PATH', cfg_path)
    if not CONFIG_PATH.is_file():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    # with CONFIG_PATH.open() as f:
    #     cfg = yaml.safe_load(f)

    config_path = Path(CONFIG_PATH)
    cfg = configparser.ConfigParser()
    cfg.read(config_path)
    return cfg