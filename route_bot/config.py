"""Read local .env values without exposing secrets in logs or shell history."""

import os
import re
from pathlib import Path


KEY = re.compile(r"[A-Z][A-Z0-9_]*\Z")


def load_local_env(filename=None):
    path = Path(filename) if filename else Path(__file__).resolve().parent.parent / ".env"
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not KEY.fullmatch(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)
