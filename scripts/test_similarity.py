"""
临时测试脚本：从本地 DB 取一个已同步的单词，查云端释义，用 _classify_interpretation_list 做置信度比对。

用法: python scripts/test_similarity.py --user <username>
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from database.momo_words import get_word_note
from core.maimemo_api import MaiMemoAPI


def main():
    parser = argparse.ArgumentParser(description="测试释义近似匹配置信度")
    parser.add_argument("--user", required=True, help="用户名")
    parser.add_argument("--voc-id", help="指定 voc_id（可选，默认取第一个已同步的单词）")
    parser.add_argument("--threshold", type=float, default=0.95, help="相似度阈值（默认 0.95）")
    args = parser.parse_args()

    # 加载 profile
    config.switch_user(args.user)

    if not config.MOMO_TOKEN:
        print("❌ MOMO_TOKEN 未配置")
        sys.exit(1)

    db_path = config.DB_PATH
    momo = MaiMemoAPI(config.MOMO_TOKEN)

    # 查找已同步的单词
    if args.voc_id:
        note = get_word_note(args.voc_id, db_path=db_path)
        if not note:
            print(f"❌ voc_id={args.voc_id} 本地无笔记")
            sys.exit(1)
    else:
        # 从 DB 中取一个 sync_status=1 的单词
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT voc_id, spelling, basic_meanings, sync_status "
            "FROM ai_word_notes WHERE sync_status = 1 LIMIT 1"
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            print("❌ 本地没有已同步的单词（sync_status=1）")
            sys.exit(1)
        note = dict(row)

    voc_id = note.get("voc_id")
    spelling = note.get("spelling", "?")
    basic_meanings = note.get("basic_meanings", "")

    print(f"=== 选取单词 ===")
    print(f"  spelling:       {spelling}")
    print(f"  voc_id:         {voc_id}")
    print(f"  basic_meanings: {basic_meanings[:100]}{'...' if len(basic_meanings) > 100 else ''}")
    print(f"  sync_status:    {note.get('sync_status')}")
    print()

    # 查云端释义
    print(f"=== 查询云端释义 ===")
    res = momo.list_interpretations(voc_id)
    if not res or not res.get("success"):
        print("❌ 查询云端释义失败")
        sys.exit(1)

    items = res.get("data", {}).get("interpretations", [])
    print(f"  云端释义数量: {len(items)}")
    for i, item in enumerate(items):
        text = momo._extract_interpretation_text(item)
        print(f"  [{i}] {text[:120]}{'...' if len(text) > 120 else ''}")
    print()

    if not items:
        print("⚠️ 云端无释义，无法比对")
        return

    # 用 _classify_interpretation_list 做比对
    print(f"=== 置信度比对（阈值={args.threshold}）===")
    result = momo._classify_interpretation_list(res, basic_meanings, similarity_threshold=args.threshold)

    print(f"  sync_status:        {result['sync_status']}")
    print(f"  reason:             {result['reason']}")
    print(f"  match_confidence:   {result['match_confidence']}")
    print(f"  matched_text:       {str(result.get('matched_text', ''))[:120]}")
    print(f"  has_remote:         {result['has_remote_interpretation']}")
    print()

    # 额外展示逐条相似度
    print(f"=== 逐条相似度详情 ===")
    normalized_expected = momo._normalize_interpretation_text(basic_meanings)
    print(f"  本地归一化文本: {normalized_expected[:100]}{'...' if len(normalized_expected) > 100 else ''}")
    print()
    for i, item in enumerate(items):
        text = momo._extract_interpretation_text(item)
        normalized_text = momo._normalize_interpretation_text(text)
        exact = normalized_text == normalized_expected
        ratio = momo._similarity(normalized_text, normalized_expected)
        tag = "✅ EXACT" if exact else ("🟢 PASS" if ratio >= args.threshold else "🔴 MISS")
        print(f"  [{i}] ratio={ratio:.4f}  {tag}  {text[:80]}{'...' if len(text) > 80 else ''}")


if __name__ == "__main__":
    main()
