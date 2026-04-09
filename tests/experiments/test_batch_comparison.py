# -*- coding: utf-8 -*-
"""
tests/test_batch_comparison.py

对比实验：将 'run', 'subject', 'minute' 混合在 10 词批次和 20 词批次中，
观察 Gemini 在处理大吞吐量时，对关键词多义性、雅思考点、记忆法的分析深度是否下降。

⚠️  只读模式，不写入墨墨，也不写入正式数据库 history.db。
"""

import sys
import io
import os
import time
import json

# ── 路径修正 ──────────────────────────────────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from dotenv import load_dotenv
from mimo_client import MimoClient
from db_manager import log_test_run

# ── 终端编码 ──────────────────────────────────────────────────────────────────
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

load_dotenv(os.path.join(ROOT_DIR, ".env"))

# ── 测试数据 ──────────────────────────────────────────────────────────────────
TARGET_WORDS = ["run", "subject", "minute"]

# 候选干扰词（从墨墨拉取的今日真实待学词）
FILLER_WORDS = [
    "terminate", "accurate", "sufficiency", "confront", "ensure", 
    "specialist", "compete", "circumstance", "revenge", "pedestrian", 
    "subordinate", "consolidate", "signify", "co-ordinate", "spark", 
    "emerge", "inflation", "startle", "breach", "submerge", "enterprise"
]

# 组装 10 词列表: 3 核心 + 7 干扰
WORDS_10 = TARGET_WORDS + FILLER_WORDS[:7]
# 组装 20 词列表: 3 核心 + 17 干扰
WORDS_20 = TARGET_WORDS + FILLER_WORDS[:17]

def hr(char="─", width=80):
    return char * width

def analyze_diff(res_10, res_20):
    """对比三类核心词在两个批次中的差异。"""
    print("\n" + hr("═"))
    print("  📊  深度对比分析报告 (10词 vs 20词)")
    print(hr("═"))
    
    dict_10 = {item["spelling"].lower(): item for item in res_10}
    dict_20 = {item["spelling"].lower(): item for item in res_20}
    
    for word in TARGET_WORDS:
        item_10 = dict_10.get(word)
        item_20 = dict_20.get(word)
        
        print(f"\n🔍 单词: 【{word.upper()}】")
        print(hr("-"))
        
        if not item_10 or not item_20:
            print("  ❌ 数据缺失，无法对比。")
            continue
            
        # 1. 核心释义长度对比
        len_10 = len(item_10.get('basic_meanings', ''))
        len_20 = len(item_20.get('basic_meanings', ''))
        print(f"  📖 释义详细度 (字符数): 10词版({len_10}) vs 20词版({len_20})")
        
        # 2. 考点深度对比
        focus_10 = item_10.get('ielts_focus', '')
        focus_20 = item_20.get('ielts_focus', '')
        print(f"  🎯 雅思考点点位: {focus_10.count('-')} vs {focus_20.count('-')}")
        
        # 3. 记忆法丰富度
        mem_10 = item_10.get('memory_aid', '')
        mem_20 = item_20.get('memory_aid', '')
        print(f"  🧠 记忆法流派数: {mem_10.count('记忆法')} vs {mem_20.count('记忆法')}")
        
        # 4. 文本变化摘要
        if focus_10 == focus_20:
            print("  ✅ [结论] 雅思考点完全一致，无缩水。")
        else:
            print("  ⚠️  [结论] 内容存在微调或语义压缩。")

def main():
    mimo = MimoClient()
    
    print(f"\n🚀 [Batch 1] 开始请求 10 个单词 (含重点词) using {mimo.model_name}...")
    t1_start = time.time()
    results_10 = mimo.generate_mnemonics(WORDS_10)
    t1_end = time.time()
    print(f"   ✅ 完成，耗时: {t1_end - t1_start:.1f}s")

    # 频率限制保护
    WAIT_SEC = 20
    print(f"\n⏳ 休息 {WAIT_SEC} 秒以保护 API 频率限制...")
    time.sleep(WAIT_SEC)

    print(f"\n🚀 [Batch 2] 开始请求 20 个单词 (含相同重点词 + 更多干扰)...")
    t2_start = time.time()
    results_20 = mimo.generate_mnemonics(WORDS_20)
    t2_end = time.time()
    print(f"   ✅ 完成，耗时: {t2_end - t2_start:.1f}s")
    
    if not results_10 or not results_20:
        print("[错误] 某一批次解析失败，终止对比。")
        return

    # 对比分析
    analyze_diff(results_10, results_20)
    
    # 打印 20 词版中的 'run' 给用户看深度
    run_info = next((i for i in results_20 if i['spelling'].lower() == 'run'), {})
    print("\n" + hr("═"))
    print("  👀  查看 20 词批次中 'RUN' 的具体输出深度：")
    print(hr("-"))
    print(json.dumps(run_info, indent=2, ensure_ascii=False))
    
    # 记录日志
    log_test_run(0, 10, WORDS_10, 1, len(results_10), True, error_msg="Batch Comparison Test (10)", ai_results=results_10)
    log_test_run(0, 20, WORDS_20, 1, len(results_20), True, error_msg="Batch Comparison Test (20)", ai_results=results_20)

if __name__ == "__main__":
    main()
