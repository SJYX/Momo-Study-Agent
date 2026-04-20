# -*- coding: utf-8 -*-
"""
测试墨墨 API 的 get_today_items 接口
查看今天待复习单词列表的原始数据结构
"""

import sys
import io
import os

# 强制 UTF-8 编码
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import os
os.environ['MOMO_USER'] = 'Asher'  # 强制指定用户为 DDY

from config import MOMO_TOKEN, ACTIVE_USER
from core.maimemo_api import MaiMemoAPI
import json

def main():
    print("=" * 60)
    print("墨墨 API - 今日待复习单词列表测试")
    print("=" * 60)
    print(f"当前用户: {ACTIVE_USER}")
    print()

    # 创建 API 客户端
    momo = MaiMemoAPI(MOMO_TOKEN)

    # 获取今日待复习列表
    print("正在获取今日待复习单词列表...")
    result = momo.get_today_items(limit=500)

    if not result:
        print("❌ API 返回空响应")
        return

    print(f"API 响应状态: {'成功' if result.get('success') else '失败'}")
    print()

    # 打印完整的 JSON 响应
    print("完整 API 响应 (get_today_items):")
    print("-" * 60)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("-" * 60)
    print()

    # 提取并分析数据
    if result.get("success"):
        data = result.get("data", {})
        today_items = data.get("today_items", [])

        print(f"今日待复习单词数量: {len(today_items)}")
        print()

        if today_items:
            print("第一个单词的详细信息:")
            print("-" * 60)
            first_word = today_items[0]
            print(json.dumps(first_word, indent=2, ensure_ascii=False))
            print("-" * 60)
            print()

            # 显示关键字段
            print("关键字段说明:")
            print("- voc_id: 单词 ID")
            print("- voc_spelling: 单词拼写")
            print("- voc_meanings: 单词释义")
            print("- review_count: 复习次数")
            print("- short_term_familiarity: 短期熟悉度")
            print()

            # 显示前 5 个单词的概览
            print("前 5 个单词概览:")
            print("-" * 60)
            for i, word in enumerate(today_items[:5], 1):
                print(f"{i}. {word.get('voc_spelling', 'N/A')} (ID: {word.get('voc_id', 'N/A')})")
                print(f"   释义: {word.get('voc_meanings', 'N/A')[:50]}...")
                print(f"   复习次数: {word.get('review_count', 'N/A')}")
                print(f"   熟悉度: {word.get('short_term_familiarity', 'N/A')}")
                print()
        else:
            print("今日没有待复习的单词")
    else:
        errors = result.get("errors", [])
        if errors:
            print("API 错误:")
            for error in errors:
                print(f"  - {error.get('code', 'N/A')}: {error.get('msg', 'N/A')}")

    # 测试未来几天的学习计划
    print("\n" + "=" * 60)
    print("测试未来 7 天学习计划 API")
    print("=" * 60)

    from datetime import datetime, timedelta
    start_dt = datetime.now()
    end_dt = start_dt + timedelta(days=7)

    print(f"查询日期范围: {start_dt.strftime('%Y-%m-%d')} 至 {end_dt.strftime('%Y-%m-%d')}")

    future_result = momo.query_study_records(
        start_dt.strftime("%Y-%m-%dT00:00:00.000Z"),
        end_dt.strftime("%Y-%m-%dT23:59:59.000Z")
    )

    if not future_result:
        print("❌ API 返回空响应")
        return

    print(f"API 响应状态: {'成功' if future_result.get('success') else '失败'}")
    print()

    # 打印完整的 JSON 响应
    print("完整 API 响应 (query_study_records):")
    print("-" * 60)
    print(json.dumps(future_result, indent=2, ensure_ascii=False))
    print("-" * 60)
    print()

    # 提取并分析数据
    if future_result.get("success"):
        future_data = future_result.get("data", {})
        records = future_data.get("records", [])

        print(f"未来 7 天学习计划单词数量: {len(records)}")
        print()

        if records:
            print("第一个计划单词的详细信息:")
            print("-" * 60)
            first_record = records[0]
            print(json.dumps(first_record, indent=2, ensure_ascii=False))
            print("-" * 60)
            print()

            # 显示关键字段
            print("关键字段说明:")
            print("- voc_id: 单词 ID")
            print("- voc_spelling: 单词拼写")
            print("- next_study_date: 下次学习日期")
            print("- familiarity: 熟悉度")
            print()

            # 显示前 5 个计划单词的概览
            print("前 5 个计划单词概览:")
            print("-" * 60)
            for i, record in enumerate(records[:5], 1):
                print(f"{i}. {record.get('voc_spelling', 'N/A')} (ID: {record.get('voc_id', 'N/A')})")
                print(f"   下次学习日期: {record.get('next_study_date', 'N/A')}")
                print(f"   熟悉度: {record.get('familiarity', 'N/A')}")
                print()
        else:
            print("未来 7 天没有学习计划")
    else:
        errors = future_result.get("errors", [])
        if errors:
            print("API 错误:")
            for error in errors:
                print(f"  - {error.get('code', 'N/A')}: {error.get('msg', 'N/A')}")

if __name__ == "__main__":
    main()
