"""Shared configuration and append-only evidence helpers (Python 3.9+)."""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import yaml


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", value):
        raise ValueError("ID must contain 1..96 ASCII letters, digits, _ or -")
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def append_json(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        f.flush()


def write_json(path, record):
    Path(path).write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def load_config(path):
    path = Path(path).resolve()
    c = yaml.safe_load(path.read_text(encoding="utf-8"))
    for section, key in [("server", "storage"), ("sender", "manifest"), ("experiment", "results")]:
        c[section][key] = str((path.parent / c[section][key]).resolve())
    identifier(c["sender"]["device_id"])
    identifier(c["experiment"]["condition_id"])
    s = c["sender"]
    if s["connect_timeout_s"] <= 0 or s["event_deadline_s"] <= 0 or s["max_retries"] < 0:
        raise ValueError("timeouts must be positive; retries must be nonnegative")
    if c["experiment"]["trials"] < 1 or c["experiment"]["interval_s"] < 0:
        raise ValueError("invalid trials / interval")
    if not 1 <= len(s["image_ids"]) <= 32:
        raise ValueError("select 1..32 images")
    return c
