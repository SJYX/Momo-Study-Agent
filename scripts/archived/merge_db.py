import sqlite3
import os
import argparse
import shutil
import hashlib
from datetime import datetime
from typing import List, Tuple, Dict, Any

# 导入核心逻辑 (需要确保 python 路径能找到 core)
import sys
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.db_manager import _get_conn, _create_tables, get_momo_token_hash, get_config

def get_token_from_env_file(env_path: str) -> str:
    """从指定的 .env 文件中提取 MOMO_TOKEN"""
    if not os.path.exists(env_path):
        return None
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('MOMO_TOKEN='):
                return line.split('=')[1].strip().strip('"').strip("'")
    return None

def get_data_richness(row: sqlite3.Row) -> int:
    """计算一行数据的丰度 (非空字段数量)"""
    # 排除不需要计算的统计类字段
    exclude = ['voc_id', 'spelling', 'created_at', 'updated_at', 'raw_full_text']
    count = 0
    for key in row.keys():
        if key not in exclude and row[key] and str(row[row.keys().index(key)]).strip():
            count += 1
    return count

def backup_db(db_path: str):
    """备份数据库文件"""
    backup_path = f"{db_path}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
    shutil.copy2(db_path, backup_path)
    print(f"[*] 已备份: {db_path} -> {backup_path}")

def merge_databases(source_path: str, target_path: str, force: bool = False):
    """
    将 source 分支的数据合并到 target 主干。
    """
    print(f"[*] 准备合并: {source_path} -> {target_path}")
    
    # 1. 结构对齐
    for p in [source_path, target_path]:
        conn = _get_conn(p)
        _create_tables(conn.cursor())
        conn.commit()
        conn.close()

    # 2. 验证 Identity (Token)
    # 尝试寻找对应的 .env
    # 假设数据库名为 history_NAME.db, 对应 profiles/NAME.env
    def find_token_for_db(db_p):
        name = os.path.basename(db_p).replace('history_', '').replace('.db', '')
        env_p = os.path.join(BASE_DIR, 'data', 'profiles', f"{name}.env")
        return get_token_from_env_file(env_p)

    s_token = find_token_for_db(source_path)
    t_token = find_token_for_db(target_path)
    
    if s_token and t_token:
        s_hash = get_momo_token_hash(s_token)
        t_hash = get_momo_token_hash(t_token)
        if s_hash != t_hash:
            print(f"[!] 警告: 两个数据库的 MOMO_TOKEN 不匹配！")
            if not force:
                print("[!] 合并取消。如果你确定要合并不同账号的数据，请使用 --force 参数。")
                return
    else:
        print("[?] 无法通过 Profile 文件自动验证 Token。")
        if not force:
            print("[!] 为了安全，请手动确认。或使用 --force 跳过校检。")
            return

    # 3. 开始合并
    s_conn = _get_conn(source_path)
    s_conn.row_factory = sqlite3.Row
    t_conn = _get_conn(target_path)
    t_conn.row_factory = sqlite3.Row
    
    s_cur = s_conn.cursor()
    t_cur = t_conn.cursor()

    # --- Table: processed_words ---
    print("[*] 正在同步已处理单词列表...")
    s_cur.execute("SELECT * FROM processed_words")
    for row in s_cur.fetchall():
        t_cur.execute("INSERT OR IGNORE INTO processed_words (voc_id, spelling, processed_at) VALUES (?, ?, ?)", 
                      (row['voc_id'], row['spelling'], row['processed_at']))

    # --- Table: ai_batches ---
    print("[*] 正在同步 AI 批次记录...")
    s_cur.execute("SELECT * FROM ai_batches")
    for row in s_cur.fetchall():
        keys = row.keys()
        placeholders = ",".join(["?"] * len(keys))
        vals = [row[k] for k in keys]
        t_cur.execute(f"INSERT OR IGNORE INTO ai_batches ({','.join(keys)}) VALUES ({placeholders})", vals)

    # --- Table: ai_word_notes (Smart Dimension Merge) ---
    print("[*] 正在深度合并 AI 笔记表 (核心)...")
    s_cur.execute("SELECT * FROM ai_word_notes")
    s_notes = s_cur.fetchall()
    
    for s_row in s_notes:
        vid = s_row['voc_id']
        t_cur.execute("SELECT * FROM ai_word_notes WHERE voc_id = ?", (vid,))
        t_row = t_cur.fetchone()
        
        should_use_source = False
        if not t_row:
            should_use_source = True
        else:
            # 维度对比
            s_rich = get_data_richness(s_row)
            t_rich = get_data_richness(t_row)
            
            if s_rich > t_rich:
                should_use_source = True
                print(f"    [+] 发现词条 {s_row['spelling']} 在源库维度更高 ({s_rich} > {t_rich})，执行覆盖。")
            elif s_rich == t_rich:
                # 时间对比
                if s_row['updated_at'] > t_row['updated_at']:
                    should_use_source = True

        if should_use_source:
            keys = [k for k in s_row.keys() if k != 'updated_at'] # 让 target 触发 DEFAULT TIMESTAMP 或手动指定
            placeholders = ",".join(["?"] * len(keys))
            vals = [s_row[k] for k in keys]
            t_cur.execute(f"INSERT OR REPLACE INTO ai_word_notes ({','.join(keys)}) VALUES ({placeholders})", vals)

    # --- Table: word_progress_history ---
    print("[*] 正在合并学习进度流水 (基于时间线去重)...")
    s_cur.execute("SELECT * FROM word_progress_history")
    for row in s_cur.fetchall():
        # 这里为了防止完全重复的快照录入，检查一下
        t_cur.execute("""
            SELECT 1 FROM word_progress_history 
            WHERE voc_id = ? AND review_count = ? AND ABS(familiarity_short - ?) < 0.001
        """, (row['voc_id'], row['review_count'], row['familiarity_short']))
        if not t_cur.fetchone():
            t_cur.execute("""
                INSERT INTO word_progress_history 
                (voc_id, familiarity_short, familiarity_long, review_count, it_level, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (row['voc_id'], row['familiarity_short'], row['familiarity_long'], row['review_count'], row['it_level'], row['created_at']))

    t_conn.commit()
    s_conn.close()
    t_conn.close()
    print("[√] 合并成功！")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MoMo Study Agent 数据库智能合并工具")
    parser.add_argument("source", help="源数据库路径 (提供数据)")
    parser.add_argument("target", help="目标数据库路径 (接收数据并作为最终库)")
    parser.add_argument("--force", action="store_true", help="强制忽略 Token 校验")
    parser.add_argument("--no-backup", action="store_true", help="合并前不备份")

    args = parser.parse_args()

    # 路径处理
    s_path = os.path.abspath(args.source)
    t_path = os.path.abspath(args.target)

    if not os.path.exists(s_path):
        print(f"[!] 找不到源文件: {s_path}")
        exit(1)
    if not os.path.exists(t_path):
        print(f"[!] 找不到目标文件: {t_path}")
        exit(1)

    if not args.no_backup:
        backup_db(t_path)
    
    merge_databases(s_path, t_path, args.force)
