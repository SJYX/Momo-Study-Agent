import argparse
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.preflight import run_preflight


def _render_text(result: dict) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append(f"Preflight Report | user={result['username']}")
    lines.append("=" * 60)
    lines.append(f"profile: {result['profile_path']}")
    lines.append(f"force_cloud_mode: {result['force_cloud_mode']}")
    lines.append("-" * 60)

    for item in result["checks"]:
        icon = "OK" if item["ok"] else "XX"
        block = "[BLOCK]" if item["blocking"] else "[WARN]"
        flag = "" if item["ok"] else f" {block}"
        lines.append(f"{icon:<2} {item['name']}{flag}")
        lines.append(f"    - detail: {item['detail']}")
        if not item["ok"]:
            lines.append(f"    - fix: {item['fix_hint']}")

    lines.append("-" * 60)
    if result["ok"]:
        lines.append("RESULT: PASS (exit code 0)")
    else:
        lines.append("RESULT: FAIL (exit code 1)")
        lines.append("Blocking items:")
        for item in result["blocking_items"]:
            lines.append(f"  - {item['name']}: {item['fix_hint']}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run onboarding preflight checks")
    parser.add_argument("--user", dest="username", help="Target username")
    parser.add_argument(
        "--format",
        dest="fmt",
        choices=["text", "json"],
        default="text",
        help="Output format",
    )
    args = parser.parse_args()

    username = args.username or os.getenv("MOMO_USER") or "default"
    result = run_preflight(ROOT_DIR, username)

    if args.fmt == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_render_text(result))

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
