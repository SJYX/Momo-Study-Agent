# -*- coding: utf-8 -*-
"""
检查墨墨 API 状态和初始化情况
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
os.environ['MOMO_USER'] = 'DDY'  # 强制指定用户为 DDY

from config import MOMO_TOKEN, ACTIVE_USER
from core.maimemo_api import MaiMemoAPI
import json

def main():
    print("=" * 60)
    print("墨墨 API 状态检查工具")
    print("=" * 60)
    print(f"当前用户: {ACTIVE_USER}")
    print()

    # 创建 API 客户端
    momo = MaiMemoAPI(MOMO_TOKEN)

    # 1. 检查学习进度
    print("1. 检查学习进度 (get_study_progress)")
    print("-" * 60)
    progress_result = momo.get_study_progress()

    if not progress_result:
        print("❌ API 返回空响应")
    else:
        print(f"API 响应状态: {'成功' if progress_result.get('success') else '失败'}")
        if progress_result.get("success"):
            data = progress_result.get("data", {})
            print(f"今日已学单词数: {data.get('today_studied', 0)}")
            print(f"今日待复习单词数: {data.get('today_review', 0)}")
            print(f"总学习进度: {data.get('total_progress', 0)}%")
        else:
            errors = progress_result.get("errors", [])
            if errors:
                for error in errors:
                    print(f"错误: {error.get('code', 'N/A')}: {error.get('msg', 'N/A')}")
    print()

    # 2. 检查今日待复习列表
    print("2. 检查今日待复习列表 (get_today_items)")
    print("-" * 60)
    today_result = momo.get_today_items(limit=500)

    if not today_result:
        print("❌ API 返回空响应")
    else:
        print(f"API 响应状态: {'成功' if today_result.get('success') else '失败'}")
        if today_result.get("success"):
            data = today_result.get("data", {})
            today_items = data.get("today_items", [])
            print(f"今日待复习单词数量: {len(today_items)}")

            if today_items:
                print("\n前 3 个单词:")
                for i, word in enumerate(today_items[:3], 1):
                    print(f"  {i}. {word.get('voc_spelling', 'N/A')} (ID: {word.get('voc_id', 'N/A')[:20]}...)")
                    print(f"     是否新学: {word.get('is_new', 'N/A')}")
                    print(f"     是否完成: {word.get('is_finished', 'N/A')}")
            else:
                print("\n⚠️  今日没有待复习的单词")
                print("    可能原因:")
                print("    1. 今日已完成所有复习任务")
                print("    2. 当日未打开 App 进行初始化")
                print("    3. 未开启自动同步功能")
        else:
            errors = today_result.get("errors", [])
            if errors:
                for error in errors:
                    print(f"错误: {error.get('code', 'N/A')}: {error.get('msg', 'N/A')}")
    print()

    # 3. 检查未来学习计划
    print("3. 检查未来 7 天学习计划 (query_study_records)")
    print("-" * 60)
    from datetime import datetime, timedelta
    start_dt = datetime.now()
    end_dt = start_dt + timedelta(days=7)

    future_result = momo.query_study_records(
        start_dt.strftime("%Y-%m-%dT00:00:00.000Z"),
        end_dt.strftime("%Y-%m-%dT23:59:59.000Z")
    )

    if not future_result:
        print("❌ API 返回空响应")
    else:
        print(f"API 响应状态: {'成功' if future_result.get('success') else '失败'}")
        if future_result.get("success"):
            data = future_result.get("data", {})
            records = data.get("records", [])
            print(f"未来 7 天学习计划单词数量: {len(records)}")

            if records:
                print("\n前 3 个计划单词:")
                for i, record in enumerate(records[:3], 1):
                    print(f"  {i}. {record.get('voc_spelling', 'N/A')} (ID: {record.get('voc_id', 'N/A')[:20]}...)")
                    print(f"     下次学习日期: {record.get('next_study_date', 'N/A')}")
                    print(f"     学习次数: {record.get('study_count', 'N/A')}")
        else:
            errors = future_result.get("errors", [])
            if errors:
                for error in errors:
                    print(f"错误: {error.get('code', 'N/A')}: {error.get('msg', 'N/A')}")
    print()

    # 4. 总结和建议
    print("=" * 60)
    print("总结和建议")
    print("=" * 60)

    today_empty = today_result and today_result.get("success") and len(today_result.get("data", {}).get("today_items", [])) == 0
    future_has_data = future_result and future_result.get("success") and len(future_result.get("data", {}).get("records", [])) > 0

    if today_empty:
        print("⚠️  今日待复习列表为空")
        if future_has_data:
            print("✅ 未来学习计划有数据")
            print("\n建议:")
            print("1. 打开墨墨背单词 App")
            print("2. 浏览一下今日学习任务")
            print("3. 等待几分钟让数据同步")
            print("4. 重新运行程序")
            print("\n或者选择 [未来计划] 模式处理未来几天的单词")
        else:
            print("❌ 未来学习计划也为空")
            print("\n可能原因:")
            print("1. API Token 可能已过期")
            print("2. 账号可能没有学习计划")
            print("3. 网络连接问题")
    else:
        print("✅ 今日待复习列表有数据")
        print("可以正常处理今日任务")

if __name__ == "__main__":
    main()
