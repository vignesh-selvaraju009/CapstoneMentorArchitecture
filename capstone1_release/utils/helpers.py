"""Shared, dependency-light helper functions used across modules.

Provides:
- ``get_logger``: consistent logging setup (console + rotating file under ``logs/``).
- Safe JSON/YAML read/write helpers reused by the parser, knowledge base, validator,
  generators, and storage modules.

No UI code lives here.
"""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import yaml

from config import settings

_CONFIGURED_LOGGERS: set[str] = set()


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger that logs to console and to ``logs/<root>.log``.

    Safe to call multiple times with the same ``name``; handlers are only attached once.
    """
    logger = logging.getLogger(name)
    if name in _CONFIGURED_LOGGERS:
        return logger

    logger.setLevel(settings.log_level)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = settings.logs_dir / "app.log"
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    _CONFIGURED_LOGGERS.add(name)
    return logger


_logger = get_logger(__name__)


def read_json(path: str | Path, default: Any = None) -> Any:
    """Read a JSON file, returning ``default`` if the file does not exist.

    Raises ``ValueError`` if the file exists but contains invalid JSON.
    """
    file_path = Path(path)
    if not file_path.exists():
        _logger.debug("read_json: %s does not exist, returning default", file_path)
        return default
    try:
        with file_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        _logger.error("read_json: invalid JSON in %s: %s", file_path, exc)
        raise ValueError(f"Invalid JSON in {file_path}: {exc}") from exc


def write_json(path: str | Path, data: Any, indent: int = 2) -> None:
    """Write ``data`` as JSON to ``path``, creating parent directories as needed."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=indent, ensure_ascii=False)
        handle.write("\n")
    _logger.debug("write_json: wrote %s", file_path)


def read_yaml(path: str | Path, default: Any = None) -> Any:
    """Read a YAML (or JSON, which is valid YAML) file, returning ``default`` if missing."""
    file_path = Path(path)
    if not file_path.exists():
        _logger.debug("read_yaml: %s does not exist, returning default", file_path)
        return default
    try:
        with file_path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        _logger.error("read_yaml: invalid YAML in %s: %s", file_path, exc)
        raise ValueError(f"Invalid YAML in {file_path}: {exc}") from exc


def safe_filename(text: str, max_length: int = 100) -> str:
    """Convert arbitrary text into a filesystem-safe, lowercase, underscore-separated name."""
    keep = [c if c.isalnum() else "_" for c in text.strip().lower()]
    collapsed = "".join(keep)
    while "__" in collapsed:
        collapsed = collapsed.replace("__", "_")
    return collapsed.strip("_")[:max_length] or "unnamed"
