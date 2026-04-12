# -*- coding: utf-8 -*-
"""
文档质量检查脚本

检查文档中的常见问题：
1. 尾随空格
2. 缺少换行
3. 格式不一致
"""

import os
import re
import sys
import io

def check_trailing_spaces(file_path):
    """检查尾随空格"""
    issues = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f, 1):
            if line.rstrip() != line.rstrip('\n'):
                issues.append(f"Line {i}: Trailing spaces")
    return issues

def check_multiple_blank_lines(file_path):
    """检查多余空行"""
    issues = []
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        # 检查连续3个或更多空行
        if re.search(r'\n{4,}', content):
            issues.append("Found multiple consecutive blank lines (3+)")
    return issues

def check_markdown_headers(file_path):
    """检查 Markdown 标题格式"""
    issues = []
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        in_code_block = False

        for i, line in enumerate(lines, 1):
            # 跳过代码块
            if line.strip().startswith('```'):
                in_code_block = not in_code_block
                continue

            if in_code_block:
                continue

            # 检查一级标题后是否有空行
            if line.startswith('# ') and not line.startswith('##'):
                if i < len(lines) and lines[i].strip() != '':
                    issues.append(f"Line {i}: Missing blank line after H1 header")
    return issues

def check_file_encoding(file_path):
    """检查文件编码"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            f.read()
        return []
    except UnicodeDecodeError:
        return ["File encoding is not UTF-8"]

def main():
    # 设置标准输出为 UTF-8
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    docs_dir = os.path.join(os.path.dirname(__file__), '..', 'docs')
    if not os.path.exists(docs_dir):
        print(f"Docs directory not found: {docs_dir}")
        return

    total_issues = 0
    markdown_files = []

    # 收集所有 Markdown 文件
    for root, dirs, files in os.walk(docs_dir):
        for file in files:
            if file.endswith('.md'):
                markdown_files.append(os.path.join(root, file))

    print(f"检查 {len(markdown_files)} 个 Markdown 文件...\n")

    for file_path in sorted(markdown_files):
        relative_path = os.path.relpath(file_path, docs_dir)
        issues = []

        issues.extend(check_trailing_spaces(file_path))
        issues.extend(check_multiple_blank_lines(file_path))
        issues.extend(check_markdown_headers(file_path))
        issues.extend(check_file_encoding(file_path))

        if issues:
            print(f"📄 {relative_path}")
            for issue in issues:
                print(f"   ⚠️  {issue}")
            total_issues += len(issues)
            print()

    if total_issues == 0:
        print("✅ 所有文档质量检查通过！")
    else:
        print(f"❌ 发现 {total_issues} 个问题")

if __name__ == "__main__":
    main()
