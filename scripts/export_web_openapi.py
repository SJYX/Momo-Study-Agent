"""
导出 Web 后端 OpenAPI 到 JSON 文件，供前端类型自动生成使用。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.backend.app import create_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Export web backend OpenAPI schema")
    parser.add_argument(
        "--output",
        default="web/frontend/src/api/openapi.json",
        help="OpenAPI output path",
    )
    args = parser.parse_args()

    app = create_app()
    schema = app.openapi()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OpenAPI exported: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
