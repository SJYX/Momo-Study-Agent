# -*- coding: utf-8 -*-
"""
tests/test_sample_run.py

测试脚本：从今日待学单词中随机抽取 N 个，一次性批量发给 Gemini，
将 AI 分析结果按正式字段结构写入测试专用数据库（data/test.db），
并在 test_run_logs 表记录本次运行摘要。

⚠️  只读墨墨数据，绝对不写入墨墨，也不写入正式库 data/history.db。
"""

import sys
import io
import os
import random

# ── 路径修正 ──────────────────────────────────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from dotenv import load_dotenv
from compat.maimemo_api import MaiMemoAPI
from compat.gemini_client import GeminiClient
from config import TEST_DB_PATH
from database.momo_words import log_test_run, save_test_word_note
from database.schema import init_db


def init_test_db():
    init_db(TEST_DB_PATH)

# ── 解决 Windows 终端中文乱码 ──────────────────────────────────────────────────
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# ── 配置 ───────────────────────────────────────────────────────────────────────
load_dotenv(os.path.join(ROOT_DIR, ".env"))
MOMO_TOKEN     = os.getenv("MOMO_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

SAMPLE_SIZE = 20   # 从今日待学单词中随机抽取的数量


# ── 工具函数 ───────────────────────────────────────────────────────────────────
def hr(char="─", width=70):
    return char * width


def print_word_card(idx: int, item: dict):
    """在终端美观地打印单个单词的 AI 分析卡片。"""
    spell = item.get("spelling", "???")
    print(f"\n{hr('═')}")
    print(f"  [{idx:02d}]  {spell.upper()}")
    print(hr("─"))

    sections = [
        ("📖 核心释义 & 搭配", "basic_meanings"),
        ("🎯 雅思考点",         "ielts_focus"),
        ("🔗 高频搭配",         "collocations"),
        ("⚠️  易错陷阱",        "traps"),
        ("📈 写作同义词升级",   "synonyms"),
        ("🔍 词义辨析",         "discrimination"),
        ("💬 例句",             "example_sentences"),
        ("🧠 记忆法",           "memory_aid"),
    ]
    for label, key in sections:
        content = item.get(key, "").strip()
        if content:
            print(f"\n{label}")
            for line in content.splitlines():
                print(f"    {line}")


# ── 主流程 ─────────────────────────────────────────────────────────────────────
def main():
    print(hr("═"))
    print("  🔬  墨墨单词 · Gemini 批量测试")
    print(f"  📂  测试数据库: {os.path.relpath(TEST_DB_PATH, ROOT_DIR)}")
    print(hr("═"))

    if not MOMO_TOKEN or not GEMINI_API_KEY:
        print("[错误] 未找到 MOMO_TOKEN 或 GEMINI_API_KEY，请检查 .env 文件！")
        return

    # ── 初始化测试库 ──────────────────────────────────────────────────────────
    init_test_db()

    # ── Step 1: 从墨墨拉取今日待学单词 ────────────────────────────────────────
    print("\n[Step 1] 正在从墨墨 API 获取今日待学单词...")
    momo = MaiMemoAPI(MOMO_TOKEN)
    res  = momo.get_today_items(limit=500)

    if not res or not res.get("success"):
        msg = "墨墨接口请求失败，请检查网络与 Token！"
        print(f"[错误] {msg}")
        log_test_run(0, 0, [], 0, 0, False, error_msg=msg)
        return

    all_items   = res.get("data", {}).get("today_items", [])
    total_today = len(all_items)
    print(f"    ✅ 共拉取到 {total_today} 个待学/待复习单词。")

    if not all_items:
        print("[提示] 今日没有待学单词，任务结束。")
        log_test_run(0, 0, [], 0, 0, True)
        return

    # ── Step 2: 随机抽取样本，建立 spelling→voc_id 映射 ──────────────────────
    sample_size = min(SAMPLE_SIZE, total_today)
    sampled     = random.sample(all_items, sample_size)
    word_dict   = {item["voc_spelling"]: item["voc_id"] for item in sampled}
    word_list   = list(word_dict.keys())

    print(f"\n[Step 2] 随机抽取了 {len(word_list)} 个单词：")
    print("    " + "  |  ".join(word_list))

    # ── Step 3: 一次性批量调用 Gemini ─────────────────────────────────────────
    print(f"\n[Step 3] 正在向 Gemini 发送批量请求（共 {len(word_list)} 词，1 次调用）...")
    gem_client  = GeminiClient(GEMINI_API_KEY)
    ai_results  = gem_client.generate_mnemonics(word_list)
    ai_returned = len(ai_results)

    if not ai_results:
        msg = "Gemini 返回结果为空或解析失败。"
        print(f"[错误] {msg}")
        log_test_run(
            total_today, sample_size, word_list,
            ai_call_count=1, words_returned=0,
            success=False, error_msg=msg,
        )
        return

    print(f"    ✅ Gemini 成功返回 {ai_returned} 个单词的分析结果。")

    # ── Step 4: 打印结果 ───────────────────────────────────────────────────────
    print(f"\n[Step 4] 详细分析结果如下（共 {ai_returned} 词）：")
    for idx, item in enumerate(ai_results, start=1):
        print_word_card(idx, item)

    # ── Step 5: 按字段结构写入测试库 ai_word_notes ────────────────────────────
    print(f"\n[Step 5] 正在将 {ai_returned} 条结果写入测试库 ai_word_notes...")
    saved_count = 0
    for item in ai_results:
        spell  = item.get("spelling", "").strip()
        voc_id = word_dict.get(spell)
        if not spell:
            print(f"    ⚠️  跳过无 spelling 的记录: {item}")
            continue
        # 无 voc_id 时用 spelling 代替（测试环境允许）
        key = str(voc_id) if voc_id else f"TEST_{spell}"
        save_test_word_note(key, item)
        saved_count += 1
        print(f"    ✅ [{saved_count:02d}] {spell}  (voc_id={key})")

    # ── Step 6: 写入运行日志 ───────────────────────────────────────────────────
    row_id = log_test_run(
        total_today    = total_today,
        sample_size    = sample_size,
        words_sampled  = word_list,
        ai_call_count  = 1,
        words_returned = ai_returned,
        success        = True,
        ai_results     = ai_results,
    )

    # ── 汇总统计 ──────────────────────────────────────────────────────────────
    print(f"\n{hr('═')}")
    print(f"  📊 测试完成汇总：")
    print(f"     - 今日单词总数       : {total_today}")
    print(f"     - 本次抽样数量       : {sample_size}")
    print(f"     - Gemini 调用次数    : 1  ✅（节省了约 {max(sample_size-1,0)} 次独立调用）")
    print(f"     - 成功解析单词数     : {ai_returned}")
    print(f"     - 写入墨墨           : ❌ 0 条（只读测试模式）")
    print(f"     - 写入 history.db    : ❌ 0 条（隔离保护）")
    print(f"     - 写入 test.db / ai_word_notes : ✅ {saved_count} 条")
    print(f"     - 写入 test.db / test_run_logs : ✅ 1 条（row id = {row_id}）")
    print(hr("═"))
    print("  ⚠️  提示：如需真实写入，请使用 main.py 并关闭 DRY_RUN 开关。")
    print(hr("═"))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[中止] 用户手动退出。")
    except Exception as e:
        import traceback
        print(f"\n[崩溃] 发生了未预期的异常：{e}")
        traceback.print_exc()
