"""
python -m web 统一入口：默认走 scripts/start_web.py。
"""
from __future__ import annotations

import runpy
from pathlib import Path


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "start_web.py"
    runpy.run_path(str(script_path), run_name="__main__")


if __name__ == "__main__":
    main()
