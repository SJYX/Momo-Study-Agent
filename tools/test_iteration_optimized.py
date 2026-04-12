# -*- coding: utf-8 -*-
"""
测试优化后的薄弱词助记功能
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

# 强制指定用户
os.environ['MOMO_USER'] = 'DDY'

from config import MOMO_TOKEN, ACTIVE_USER, AI_PROVIDER
from core.maimemo_api import MaiMemoAPI
from core.iteration_manager import IterationManager
from core.logger import setup_logger
import json

def main():
    print("=" * 60)
    print("优化后薄弱词助记功能测试")
    print("=" * 60)
    print(f"当前用户: {ACTIVE_USER}")
    print(f"AI 提供商: {AI_PROVIDER}")
    print()

    # 创建 API 客户端
    momo = MaiMemoAPI(MOMO_TOKEN)

    # 创建日志器
    logger = setup_logger(ACTIVE_USER)

    # 创建迭代管理器
    from core.mimo_client import MimoClient
    from config import MIMO_API_KEY
    ai_client = MimoClient(MIMO_API_KEY)

    im = IterationManager(ai_client, momo, logger)

    # 1. 测试新的筛选系统
    print("1. 测试新的筛选系统 (WeakWordFilter)")
    print("-" * 60)

    from core.weak_word_filter import WeakWordFilter
    filter = WeakWordFilter(logger)

    # 获取用户统计信息
    user_stats = filter._get_user_stats()
    print(f"用户统计: {user_stats}")

    # 获取动态阈值
    dynamic_threshold = filter.get_dynamic_threshold(user_stats)
    print(f"动态阈值: {dynamic_threshold}")

    # 按分数获取薄弱词
    weak_words_by_score = filter.get_weak_words_by_score(min_score=50.0, limit=10)
    print(f"按分数找到 {len(weak_words_by_score)} 个薄弱单词")

    if weak_words_by_score:
        print("\n前 3 个薄弱单词 (按分数):")
        for i, word in enumerate(weak_words_by_score[:3], 1):
            print(f"  {i}. {word.get('spelling', 'N/A')} (ID: {word.get('voc_id', 'N/A')[:20]}...)")
            print(f"     薄弱分数: {word.get('weak_score', 'N/A'):.1f}")
            print(f"     熟悉度: {word.get('familiarity_short', 'N/A')}")
            print(f"     学习次数: {word.get('study_count', 'N/A')}")
    else:
        print("没有找到薄弱单词")

    # 按类别获取薄弱词
    categorized = filter.get_weak_words_by_category(dynamic_threshold)
    print(f"\n按类别找到:")
    print(f"  紧急薄弱词: {len(categorized['urgent'])}")
    print(f"  一般薄弱词: {len(categorized['normal'])}")
    print(f"  潜在薄弱词: {len(categorized['potential'])}")
    print()

    # 2. 测试迭代功能
    print("2. 测试迭代功能 (run_iteration)")
    print("-" * 60)
    print("开始执行智能迭代...")
    print()

    try:
        im.run_iteration()
        print("✅ 迭代完成")
    except Exception as e:
        print(f"❌ 迭代失败: {e}")
    print()

    # 3. 检查 API 限制状态
    print("3. 检查 API 限制状态")
    print("-" * 60)
    if hasattr(momo, 'creation_limit_reached'):
        print(f"创建释义限制状态: {momo.creation_limit_reached}")
    else:
        print("未设置创建释义限制状态")
    print()

    print("=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    main()
