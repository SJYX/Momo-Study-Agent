"""
test_skip_ai.py - 测试去重与 AI 调用隔离机制

核心问题：当单词已存在于数据库中时，是否真的跳过了 Gemini AI 的调用？

这里使用 unittest.mock.MagicMock 来模拟 GeminiClient，
以便在不真实调用 API 的情况下，观察函数是否被触发。

运行方式：
  python tests/test_skip_ai.py
"""
import os
import sys
import io
import sqlite3
from unittest.mock import MagicMock, patch

# 将项目根目录加入 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 解决 Windows 终端中文/Emoji 输出乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# ======================================================
# 用内存数据库替换真实 DB，模拟真实的 is_processed 和 mark_processed
# ======================================================

_mem_conn = sqlite3.connect(":memory:")

def _setup_mem_db():
    cur = _mem_conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_word_notes (
            voc_id TEXT PRIMARY KEY,
            spelling TEXT,
            basic_meanings TEXT,
            ielts_focus TEXT,
            collocations TEXT,
            traps TEXT,
            synonyms TEXT,
            discrimination TEXT,
            example_sentences TEXT,
            memory_aid TEXT,
            raw_full_text TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    _mem_conn.commit()

def _is_processed_mem(voc_id: str) -> bool:
    cur = _mem_conn.cursor()
    cur.execute("SELECT 1 FROM ai_word_notes WHERE voc_id = ?", (str(voc_id),))
    return cur.fetchone() is not None

def _mark_processed_mem(voc_id: str, payload: dict):
    cur = _mem_conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO ai_word_notes (voc_id, spelling, basic_meanings,
        ielts_focus, collocations, traps, synonyms, discrimination,
        example_sentences, memory_aid, raw_full_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(voc_id), payload.get("spelling",""), payload.get("basic_meanings",""),
        payload.get("ielts_focus",""), payload.get("collocations",""),
        payload.get("traps",""), payload.get("synonyms",""),
        payload.get("discrimination",""), payload.get("example_sentences",""),
        payload.get("memory_aid",""), payload.get("raw_full_text",""),
    ))
    _mem_conn.commit()

# ======================================================
# 核心逻辑（从 main.py 提取，用于单元测试）
# ======================================================

def filter_words_for_ai(all_items: list, is_processed_fn) -> dict:
    """
    模拟 main.py 中的去重过滤循环。
    返回值: {spelling: voc_id} 的字典，仅包含未处理过的单词。
    """
    word_dict = {}
    for item in all_items:
        spelling = item.get("voc_spelling")
        voc_id = item.get("voc_id")
        if is_processed_fn(voc_id):
            continue
        word_dict[spelling] = voc_id
    return word_dict


PASS = "✅ PASS"
FAIL = "❌ FAIL"

def run_tests():
    _setup_mem_db()
    total, passed = 0, 0

    print("=" * 60)
    print("  🧪 AI 调用隔离测试 (AI Call Isolation Test)")
    print("=" * 60)

    # 模拟的"今日单词"列表
    ALL_ITEMS = [
        {"voc_id": "voc-apple-001", "voc_spelling": "apple", "is_new": False},
        {"voc_id": "voc-run-002",   "voc_spelling": "run",   "is_new": False},
        {"voc_id": "voc-test-003",  "voc_spelling": "test",  "is_new": True},
    ]

    # --------------------------------------------------
    # Case 1: 数据库为空时，所有单词都应进入 AI 处理队列
    # --------------------------------------------------
    total += 1
    word_dict = filter_words_for_ai(ALL_ITEMS, _is_processed_mem)
    result = (len(word_dict) == 3 and "apple" in word_dict)
    status = PASS if result else FAIL
    print(f"\n[Case 1] 数据库为空时，3 个单词全部应进入 AI 队列")
    print(f"  进入队列的单词: {list(word_dict.keys())}")
    print(f"  结果: {status}")
    if result:
        passed += 1

    # --------------------------------------------------
    # Case 2: 预先写入 "apple"，再次过滤后 apple 不应出现在 AI 队列
    # --------------------------------------------------
    total += 1
    _mark_processed_mem("voc-apple-001", {"spelling": "apple", "basic_meanings": "n. 苹果"})
    word_dict = filter_words_for_ai(ALL_ITEMS, _is_processed_mem)
    result = ("apple" not in word_dict and "run" in word_dict and "test" in word_dict)
    status = PASS if result else FAIL
    print(f"\n[Case 2] 'apple' 已入库，过滤后不应出现在 AI 队列中")
    print(f"  进入队列的单词: {list(word_dict.keys())}")
    print(f"  结果: {status}")
    if result:
        passed += 1

    # --------------------------------------------------
    # Case 3: Mock GeminiClient，验证 apple 已在库时，generate_mnemonics 不接收 apple
    # --------------------------------------------------
    total += 1
    mock_gemini = MagicMock()
    mock_gemini.generate_mnemonics.return_value = []

    word_dict = filter_words_for_ai(ALL_ITEMS, _is_processed_mem)
    target_words = list(word_dict.keys())

    if target_words:
        mock_gemini.generate_mnemonics(target_words)

    # 检查调用参数中不包含 apple
    if mock_gemini.generate_mnemonics.called:
        call_args = mock_gemini.generate_mnemonics.call_args[0][0]
        result = ("apple" not in call_args)
        print(f"\n[Case 3] Gemini 被调用时，'apple' 不应出现在参数列表中")
        print(f"  实际传入参数: {call_args}")
    else:
        result = False
        print(f"\n[Case 3] Gemini 本次未被调用（所有词都已在库）")

    status = PASS if result else FAIL
    print(f"  结果: {status}")
    if result:
        passed += 1

    # --------------------------------------------------
    # Case 4: 所有单词都已入库时，generate_mnemonics 根本不应被调用
    # --------------------------------------------------
    total += 1
    _mark_processed_mem("voc-run-002",  {"spelling": "run",  "basic_meanings": "v. 跑"})
    _mark_processed_mem("voc-test-003", {"spelling": "test", "basic_meanings": "v. 测试"})

    mock_gemini2 = MagicMock()
    word_dict = filter_words_for_ai(ALL_ITEMS, _is_processed_mem)
    target_words = list(word_dict.keys())

    if target_words:
        mock_gemini2.generate_mnemonics(target_words)
    
    result = (not mock_gemini2.generate_mnemonics.called and len(target_words) == 0)
    status = PASS if result else FAIL
    print(f"\n[Case 4] 所有单词已入库时，generate_mnemonics 不应被调用")
    print(f"  AI 队列大小: {len(target_words)} | Gemini 是否被触发: {mock_gemini2.generate_mnemonics.called}")
    print(f"  结果: {status}")
    if result:
        passed += 1

    # --------------------------------------------------
    # 总结
    # --------------------------------------------------
    print("\n" + "=" * 60)
    print(f"  📊 测试结果汇总: {passed} / {total} 通过")
    if passed == total:
        print("  🎉 所有测试均通过！AI 调用隔离机制配合去重逻辑运作正常。")
    else:
        print(f"  ⚠️  有 {total - passed} 个测试失败，请检查过滤逻辑。")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
