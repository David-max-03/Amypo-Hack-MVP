"""Regenerate openapi.yaml from the FastAPI app, so the spec never drifts from the code.

Usage (from the repo root):  .venv/bin/python scripts/export_openapi.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.main import app  # noqa: E402

HEADER = (
    "# Generated from the FastAPI app (backend/app/main.py) - do not edit by hand.\n"
    "# Regenerate: .venv/bin/python scripts/export_openapi.py\n"
)


def main() -> None:
    out = ROOT / "openapi.yaml"
    spec = app.openapi()
    with out.open("w") as f:
        f.write(HEADER)
        yaml.safe_dump(spec, f, sort_keys=False, allow_unicode=True)
    print(f"wrote {out.relative_to(ROOT)} ({len(spec['paths'])} paths)")


if __name__ == "__main__":
    main()
