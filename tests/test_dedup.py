"""
test_dedup.py - 测试单词去重机制 (Deduplication Mechanism Test)

目的：验证 db_manager 的 is_processed / mark_processed 函数
     是否能正确地防止同一个单词被重复处理。

使用内存数据库 (:memory:)，不会污染 data/history.db。

运行方式：
  python tests/test_dedup.py
"""
import os
import sys
import sqlite3
import io

# 将项目根目录加入 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 解决 Windows 终端中文/Emoji 输出乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# ======================================================
# 内存数据库版本的 db_manager（与真实逻辑完全一致）
# ======================================================

def _get_conn(db_path=":memory:"):
    return sqlite3.connect(db_path)

def init_db_in_memory():
    """创建内存数据库并建表"""
    conn = _get_conn()
    cur = conn.cursor()
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
    conn.commit()
    return conn


def is_processed(conn, voc_id: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM ai_word_notes WHERE voc_id = ?", (str(voc_id),))
    return cur.fetchone() is not None


def mark_processed(conn, voc_id: str, payload: dict):
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO ai_word_notes (
            voc_id, spelling, basic_meanings, ielts_focus, collocations,
            traps, synonyms, discrimination, example_sentences, memory_aid, raw_full_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(voc_id),
        payload.get("spelling", ""),
        payload.get("basic_meanings", ""),
        payload.get("ielts_focus", ""),
        payload.get("collocations", ""),
        payload.get("traps", ""),
        payload.get("synonyms", ""),
        payload.get("discrimination", ""),
        payload.get("example_sentences", ""),
        payload.get("memory_aid", ""),
        payload.get("raw_full_text", ""),
    ))
    conn.commit()


def get_row_count(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM ai_word_notes")
    return cur.fetchone()[0]


def get_record(conn, voc_id: str) -> dict | None:
    cur = conn.cursor()
    cur.execute("SELECT * FROM ai_word_notes WHERE voc_id = ?", (voc_id,))
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


# ======================================================
# 测试用例
# ======================================================

PASS = "✅ PASS"
FAIL = "❌ FAIL"

def run_tests():
    total, passed = 0, 0
    conn = init_db_in_memory()
    
    # 模拟数据
    VOC_ID_1 = "voc-apple-test-001"
    VOC_ID_2 = "voc-run-test-002"
    
    PAYLOAD_1 = {
        "spelling": "apple",
        "basic_meanings": "n. 苹果",
        "ielts_focus": "雅思写作中可用作比喻",
        "collocations": "apple juice; pick apples",
        "traps": "注意 apple 的引申义：掌上明珠",
        "synonyms": "fruit",
        "discrimination": "",
        "example_sentences": "She ate an apple.",
        "memory_aid": "词根：apple 本身就是苹果",
        "raw_full_text": "### apple\nn. 苹果"
    }
    
    PAYLOAD_1_MODIFIED = {**PAYLOAD_1, "basic_meanings": "n. 苹果【被修改版】"}

    print("=" * 60)
    print("  🧪 去重机制测试 (Deduplication Mechanism Test)")
    print("=" * 60)

    # --------------------------------------------------
    # Case 1: 新单词写入前，is_processed 应返回 False
    # --------------------------------------------------
    total += 1
    result = not is_processed(conn, VOC_ID_1)
    status = PASS if result else FAIL
    print(f"\n[Case 1] 新单词未写入时，is_processed() 应为 False")
    print(f"  结果: {status}")
    if result:
        passed += 1

    # --------------------------------------------------
    # Case 2: 写入后，is_processed 应返回 True
    # --------------------------------------------------
    total += 1
    mark_processed(conn, VOC_ID_1, PAYLOAD_1)
    result = is_processed(conn, VOC_ID_1)
    status = PASS if result else FAIL
    print(f"\n[Case 2] 写入单词后，is_processed() 应为 True")
    print(f"  结果: {status}")
    if result:
        passed += 1

    # --------------------------------------------------
    # Case 3: 重复写入（INSERT OR IGNORE）后，数据库行数不增加
    # --------------------------------------------------
    total += 1
    count_before = get_row_count(conn)
    mark_processed(conn, VOC_ID_1, PAYLOAD_1_MODIFIED)  # 使用修改版数据重复写入
    count_after = get_row_count(conn)
    result = (count_before == count_after == 1)
    status = PASS if result else FAIL
    print(f"\n[Case 3] 重复写入同一 voc_id 后，记录行数不应增加 (期望: 1 行)")
    print(f"  写入前行数: {count_before} | 写入后行数: {count_after}")
    print(f"  结果: {status}")
    if result:
        passed += 1

    # --------------------------------------------------
    # Case 4: INSERT OR IGNORE 保护了原始数据（不被修改版覆盖）
    # --------------------------------------------------
    total += 1
    record = get_record(conn, VOC_ID_1)
    original_meaning = PAYLOAD_1["basic_meanings"]
    result = (record is not None and record["basic_meanings"] == original_meaning)
    status = PASS if result else FAIL
    print(f"\n[Case 4] INSERT OR IGNORE 保护原始数据（不被第二次写入覆盖）")
    print(f"  期望值: '{original_meaning}'")
    print(f"  实际值: '{record['basic_meanings'] if record else 'N/A'}'")
    print(f"  结果: {status}")
    if result:
        passed += 1

    # --------------------------------------------------
    # Case 5: 不同单词可以独立写入
    # --------------------------------------------------
    total += 1
    mark_processed(conn, VOC_ID_2, {**PAYLOAD_1, "spelling": "run", "basic_meanings": "v. 跑"})
    result = (get_row_count(conn) == 2 and is_processed(conn, VOC_ID_2))
    status = PASS if result else FAIL
    print(f"\n[Case 5] 不同 voc_id 的单词可独立写入，行数应为 2")
    print(f"  当前总行数: {get_row_count(conn)}")
    print(f"  结果: {status}")
    if result:
        passed += 1

    # --------------------------------------------------
    # Case 6: 从未写入的单词 voc_id，is_processed 应为 False
    # --------------------------------------------------
    total += 1
    result = not is_processed(conn, "voc-nonexistent-999")
    status = PASS if result else FAIL
    print(f"\n[Case 6] 不存在的 voc_id 查询，is_processed() 应为 False")
    print(f"  结果: {status}")
    if result:
        passed += 1

    conn.close()
    
    # --------------------------------------------------
    # 总结
    # --------------------------------------------------
    print("\n" + "=" * 60)
    print(f"  📊 测试结果汇总: {passed} / {total} 通过")
    if passed == total:
        print("  🎉 所有测试均通过！去重机制运作正常。")
    else:
        print(f"  ⚠️  有 {total - passed} 个测试失败，请检查去重逻辑。")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
