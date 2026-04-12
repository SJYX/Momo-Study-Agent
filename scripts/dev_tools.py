#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
开发工具脚本
提供代码质量检查、格式化等开发辅助功能
"""

import os
import subprocess
import sys
from pathlib import Path


def run_command(cmd: str, description: str) -> bool:
    """运行命令并返回是否成功"""
    print(f"\n{'='*60}")
    print(f"🔧 {description}")
    print(f"{'='*60}")
    print(f"命令: {cmd}\n")

    result = subprocess.run(cmd, shell=True)
    success = result.returncode == 0

    if success:
        print(f"✅ {description} - 成功")
    else:
        print(f"❌ {description} - 失败")

    return success


def format_code():
    """格式化代码"""
    commands = [
        ("python -m black core/ main.py config.py --line-length 120", "Black 代码格式化"),
        ("python -m isort core/ main.py config.py --profile black", "Import 排序"),
    ]

    results = []
    for cmd, desc in commands:
        results.append(run_command(cmd, desc))

    return all(results)


def lint_code():
    """代码质量检查"""
    commands = [
        (
            "python -m flake8 core/ main.py config.py --max-line-length 120 --ignore=E203,W503",
            "Flake8 代码检查",
        ),
        ("python -m mypy core/ main.py config.py --ignore-missing-imports", "MyPy 类型检查"),
    ]

    results = []
    for cmd, desc in commands:
        results.append(run_command(cmd, desc))

    return all(results)


def run_tests(with_coverage: bool = False):
    """运行测试"""
    if with_coverage:
        cmd = (
            "python -m pytest tests/ -v "
            "--cov=core --cov=config --cov=main "
            "--cov-report=html:htmlcov "
            "--cov-report=term-missing "
            "--cov-report=json:coverage.json"
        )
        desc = "运行测试并生成覆盖率报告"
    else:
        cmd = "python -m pytest tests/ -v"
        desc = "运行测试"

    return run_command(cmd, desc)


def clean_cache():
    """清理缓存和临时文件"""
    print(f"\n{'='*60}")
    print("🧹 清理缓存和临时文件")
    print(f"{'='*60}\n")

    patterns = [
        "**/__pycache__",
        "**/*.pyc",
        "**/*.pyo",
        "**/*.egg-info",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "htmlcov",
        ".coverage",
        "coverage.json",
    ]

    count = 0
    for pattern in patterns:
        for path in Path(".").glob(pattern):
            if path.is_file():
                path.unlink()
                count += 1
                print(f"  删除文件: {path}")
            elif path.is_dir():
                import shutil

                shutil.rmtree(path)
                count += 1
                print(f"  删除目录: {path}")

    print(f"\n✅ 清理完成，共删除 {count} 个项目")
    return True


def check_dependencies():
    """检查依赖项"""
    print(f"\n{'='*60}")
    print("📦 检查依赖项")
    print(f"{'='*60}\n")

    required_packages = {
        "requests": "requests",
        "google-genai": "google.genai",
        "python-dotenv": "dotenv",
        "pytest": "pytest",
        "json-repair": "json_repair",
        "libsql-client": "libsql",
    }

    dev_packages = {
        "black": "black",
        "isort": "isort",
        "flake8": "flake8",
        "mypy": "mypy",
        "pytest-cov": "pytest_cov",
    }

    all_installed = True

    print("生产依赖:")
    for package_name, import_name in required_packages.items():
        try:
            __import__(import_name)
            print(f"  ✅ {package_name}")
        except ImportError:
            print(f"  ❌ {package_name} (未安装)")
            all_installed = False

    print("\n开发依赖:")
    for package_name, import_name in dev_packages.items():
        try:
            __import__(import_name)
            print(f"  ✅ {package_name}")
        except ImportError:
            print(f"  ⚠️  {package_name} (未安装，运行 'pip install {package_name}' 安装)")

    return all_installed


def show_help():
    """显示帮助信息"""
    print("""
Momo Study Agent - 开发工具

用法: python scripts/dev_tools.py [命令]

可用命令:
  format          - 格式化代码 (black + isort)
  lint            - 代码质量检查 (flake8 + mypy)
  test            - 运行测试
  test-cov        - 运行测试并生成覆盖率报告
  clean           - 清理缓存和临时文件
  check-deps      - 检查依赖项
  ci              - 运行完整的 CI 流程 (clean + lint + test-cov)
  help            - 显示此帮助信息

示例:
  python scripts/dev_tools.py format
  python scripts/dev_tools.py ci
""")


def run_ci():
    """运行完整的 CI 流程"""
    steps = [
        (clean_cache, "清理缓存"),
        (check_dependencies, "检查依赖"),
        (lint_code, "代码质量检查"),
        (lambda: run_tests(with_coverage=True), "运行测试并生成覆盖率"),
    ]

    print(f"\n{'='*60}")
    print("🚀 开始 CI 流程")
    print(f"{'='*60}")

    for step_func, step_name in steps:
        if not step_func():
            print(f"\n❌ CI 失败: {step_name}")
            return False

    print(f"\n{'='*60}")
    print("✅ CI 流程全部通过！")
    print(f"{'='*60}")
    return True


def main():
    """主函数"""
    if len(sys.argv) < 2:
        show_help()
        return

    command = sys.argv[1].lower()

    commands = {
        "format": format_code,
        "lint": lint_code,
        "test": lambda: run_tests(with_coverage=False),
        "test-cov": lambda: run_tests(with_coverage=True),
        "clean": clean_cache,
        "check-deps": check_dependencies,
        "ci": run_ci,
        "help": show_help,
    }

    if command in commands:
        success = commands[command]()
        sys.exit(0 if success else 1)
    else:
        print(f"❌ 未知命令: {command}")
        show_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
