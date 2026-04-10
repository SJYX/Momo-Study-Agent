# -*- coding: utf-8 -*-
import sqlite3, os, json, re, hashlib, shutil, time
from datetime import datetime
from typing import Optional, Dict, Tuple, List, Any
from config import DB_PATH, TEST_DB_PATH, DATA_DIR

TURSO_DB_URL = os.getenv('TURSO_DB_URL')
TURSO_AUTH_TOKEN = os.getenv('TURSO_AUTH_TOKEN')
TURSO_TEST_DB_URL = os.getenv('TURSO_TEST_DB_URL')
TURSO_TEST_AUTH_TOKEN = os.getenv('TURSO_TEST_AUTH_TOKEN')

try:
    import libsql
    HAS_LIBSQL = True
except ImportError:
    HAS_LIBSQL = False
# 导入日志系统
try:
    from .logger import ContextLogger, log_performance, get_logger
    import logging
except ImportError:
    # 如果导入失败，提供简单的替代
    class ContextLogger:
        def __init__(self, logger): self.logger = logger
        def info(self, *args, **kwargs): pass
        def error(self, *args, **kwargs): pass
        def debug(self, *args, **kwargs): pass
    
    def log_performance(logger_func):
        def decorator(func):
            return func
        return decorator
    def get_logger():
        import logging
        return ContextLogger(logging.getLogger(__name__))

def _debug_log(msg, start_time=None):
    elapsed = f' | 耗时: {int((time.time() - start_time)*1000)}ms' if start_time else ''
    get_logger().debug(f"[DB] {msg}{elapsed}", module="db_manager")

def clean_for_maimemo(text: str) -> str:
    if text is None: return ''
    text = re.sub(r'^#{1,6}\s+', '', str(text), flags=re.MULTILINE)
    text = re.sub(r'^[\-\*]\s+', '• ', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\*(.+?)\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'`(.+?)`', r'\1', text)
    return text.strip()

def _get_local_conn(db_path: str = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def _get_conn(db_path: str) -> Any:
    target_abs = os.path.abspath(db_path)
    main_abs = os.path.abspath(DB_PATH)
    is_test = 'test_' in os.path.basename(db_path)
    url = TURSO_TEST_DB_URL if is_test else TURSO_DB_URL
    token = TURSO_TEST_AUTH_TOKEN if is_test else TURSO_AUTH_TOKEN
    
    if (target_abs == main_abs or is_test) and url and token and HAS_LIBSQL:
        # 增加轻量级重试逻辑
        for attempt in range(3):
            try:
                return libsql.connect(url, auth_token=token)
            except Exception as e:
                if attempt == 2: raise e
                _debug_log(f'连接云端失败，正在重试 ({attempt+1}/3)...')
                time.sleep(1)
    return _get_local_conn(db_path)

def _create_tables(cur):
    cur.execute('CREATE TABLE IF NOT EXISTS processed_words (voc_id TEXT PRIMARY KEY, spelling TEXT, processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cur.execute('CREATE TABLE IF NOT EXISTS ai_word_notes (voc_id TEXT PRIMARY KEY, spelling TEXT, basic_meanings TEXT, ielts_focus TEXT, collocations TEXT, traps TEXT, synonyms TEXT, discrimination TEXT, example_sentences TEXT, memory_aid TEXT, word_ratings TEXT, raw_full_text TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, batch_id TEXT, original_meanings TEXT, maimemo_context TEXT, it_level INTEGER DEFAULT 0, it_history TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cur.execute('CREATE TABLE IF NOT EXISTS word_progress_history (id INTEGER PRIMARY KEY AUTOINCREMENT, voc_id TEXT, familiarity_short REAL, familiarity_long REAL, review_count INTEGER, it_level INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    # 添加联合唯一约束，避免历史记录冗余同步
    try: cur.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_progress_unique ON word_progress_history (voc_id, created_at, review_count)')
    except: pass
    cur.execute('CREATE TABLE IF NOT EXISTS ai_batches (batch_id TEXT PRIMARY KEY, request_id TEXT, ai_provider TEXT, model_name TEXT, prompt_version TEXT, batch_size INTEGER, total_latency_ms INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, finish_reason TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cur.execute('CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cur.execute('CREATE TABLE IF NOT EXISTS test_run_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, total_count INTEGER, sample_count INTEGER, sample_words TEXT, ai_calls INTEGER, success_parsed INTEGER, is_dry_run BOOLEAN, error_msg TEXT, ai_results_json TEXT)')
    for t, c, d in [
        ('ai_word_notes', 'it_level',          'INTEGER DEFAULT 0'),
        ('ai_word_notes', 'it_history',         'TEXT'),
        ('ai_word_notes', 'prompt_tokens',      'INTEGER DEFAULT 0'),
        ('ai_word_notes', 'completion_tokens',  'INTEGER DEFAULT 0'),
        ('ai_word_notes', 'total_tokens',       'INTEGER DEFAULT 0'),
        ('ai_word_notes', 'batch_id',           'TEXT'),
        ('ai_word_notes', 'original_meanings',  'TEXT'),
        ('ai_word_notes', 'maimemo_context',    'TEXT'),
        ('ai_word_notes', 'raw_full_text',      'TEXT'),
        ('ai_word_notes', 'word_ratings',       'TEXT'),
        ('ai_word_notes', 'updated_at',         'TIMESTAMP'),
        ('processed_words', 'updated_at',      'TIMESTAMP'),
    ]:
        try:
            cur.execute(f'ALTER TABLE {t} ADD COLUMN {c} {d}')
            _debug_log(f"  列添加成功: {t}.{c}")
        except Exception as e:
            if "duplicate column name" not in str(e).lower():
                _debug_log(f"  列添加失败: {t}.{c} -> {e}")
    
    # 手动为旧数据补齐时间戳，确保同步逻辑能正常运行
    try:
        cur.execute("UPDATE ai_word_notes SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
        cur.execute("UPDATE processed_words SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
    except: pass

def init_db(db_path: str = None):
    """初始化数据库，确保本地和云端 schema 一致。"""
    path = db_path or DB_PATH
    
    # 1. 首先确保本地数据库 schema 是最新的
    try:
        lc = _get_local_conn(path)
        lcur = lc.cursor()
        _create_tables(lcur)
        lc.commit()
        lc.close()
        _debug_log("本地数据库初始化/迁移完成")
    except Exception as e:
        _debug_log(f"本地数据库初始化失败: {e}")

    # 2. 如果配置了云端，尝试初始化云端
    if HAS_LIBSQL and TURSO_DB_URL and TURSO_AUTH_TOKEN:
        try:
            cc = libsql.connect(TURSO_DB_URL, auth_token=TURSO_AUTH_TOKEN)
            ccur = cc.cursor()
            _create_tables(ccur)
            cc.commit()
            cc.close()
            _debug_log("云端数据库存储初始化/迁移完成")
        except Exception as e:
            _debug_log(f"云端数据库初始化失败 (可能网络不通): {e}")

@log_performance(lambda: ContextLogger(logging.getLogger(__name__)))
def get_processed_ids_in_batch(voc_ids: list, db_path: str = None) -> set:
    if not voc_ids: return set()
    s = time.time()
    c = _get_conn(db_path or DB_PATH); cur = c.cursor()
    vs = [str(v) for v in voc_ids]; ph = ','.join(['?']*len(vs))
    cur.execute(f'SELECT voc_id FROM processed_words WHERE voc_id IN ({ph})', vs)
    res = {str(r[0] if isinstance(r, (tuple,list)) else r['voc_id']) for r in cur.fetchall()}
    c.close(); _debug_log(f'批量查询 ({len(voc_ids)} 词)', s)
    return res

def is_processed(voc_id: str, db_path: str = None) -> bool:
    c = _get_conn(db_path or DB_PATH); cur = c.cursor(); cur.execute('SELECT 1 FROM processed_words WHERE voc_id = ?', (str(voc_id),))
    res = cur.fetchone() is not None; c.close(); return res

def mark_processed(voc_id: str, spelling: str, db_path: str = None, conn: Any = None):
    """支持连接复用的标记处理函数"""
    def _do_sql(cn):
        cur = cn.cursor()
        cur.execute('INSERT OR REPLACE INTO processed_words (voc_id, spelling, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)', (str(voc_id), spelling))
        if not conn: cn.commit(); cn.close()

    if conn:
        _do_sql(conn)
    else:
        path = db_path or DB_PATH
        # 优先写入云端
        try:
            cloud_conn = _get_conn(path)
            if str(cloud_conn).startswith('<libsql.'):  # 云端连接
                _do_sql(cloud_conn)
                # 同步到本地缓存
                try:
                    _do_sql(_get_local_conn(path))
                except:
                    pass
            else:
                # 本地连接，写入本地
                _do_sql(cloud_conn)
        except:
            # 云端失败，写入本地
            _do_sql(_get_local_conn(path))

def log_progress_snapshots(words: List[dict], db_path: str = None):
    if not words: return 0
    s_all = time.time()
    c = _get_conn(db_path or DB_PATH); cur = c.cursor()
    vids = [str(w['voc_id']) for w in words]; ph = ','.join(['?']*len(vids))
    cur.execute(f'SELECT voc_id, it_level FROM ai_word_notes WHERE voc_id IN ({ph})', vids)
    itm = {str(r[0]): r[1] for r in cur.fetchall()}
    cur.execute(f'SELECT voc_id, familiarity_short, review_count FROM word_progress_history WHERE voc_id IN ({ph}) ORDER BY created_at DESC', vids)
    lh = {}
    for r in cur.fetchall():
        v = str(r[0]); 
        if v not in lh: lh[v] = (r[1], r[2])
    ins = []
    for w in words:
        v = str(w['voc_id']); nf = w.get('short_term_familiarity', 0) or w.get('voc_familiarity', 0); nr = w.get('review_count', 0); l = lh.get(v)
        if not l or abs(l[0]-float(nf))>0.01 or l[1]!=int(nr):
            ins.append((v, nf, w.get('long_term_familiarity',0), nr, itm.get(v,0)))
    if ins:
        cur.executemany('INSERT INTO word_progress_history (voc_id, familiarity_short, familiarity_long, review_count, it_level) VALUES (?, ?, ?, ?, ?)', ins)
        c.commit()
    c.close(); _debug_log(f'进度同步 ({len(ins)} 条)', s_all)
    return len(ins)

@log_performance(lambda: ContextLogger(logging.getLogger(__name__)))
def save_ai_word_note(voc_id: str, payload: dict, db_path: str = None, metadata: dict = None, conn: Any = None):
    """支持连接复用的笔记保存函数"""
    s = payload.get('spelling', '')
    # raw_full_text 应为该词条自身原始 AI 输出的 JSON 字符串（由客户端设置）；
    # fallback 时序列化整个 payload（去掉 raw_full_text 自身，避免循环）以保留完整信息
    _raw_candidate = {k: v for k, v in payload.items() if k != 'raw_full_text'}
    t = payload.get('raw_full_text') or json.dumps(_raw_candidate, ensure_ascii=False)
    m_ctx = json.dumps(metadata.get('maimemo_context', {}), ensure_ascii=False) if metadata and metadata.get('maimemo_context') else None
    def _c(f): return clean_for_maimemo(payload.get(f, ''))
    args = (str(voc_id), s, _c('basic_meanings'), _c('ielts_focus'), _c('collocations'), _c('traps'), _c('synonyms'), _c('discrimination'), _c('example_sentences'), _c('memory_aid'), _c('word_ratings'), t, payload.get('prompt_tokens', 0), payload.get('completion_tokens', 0), payload.get('total_tokens', 0), metadata.get('batch_id') if metadata else None, metadata.get('original_meanings') if metadata else None, m_ctx, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    sql = 'INSERT OR REPLACE INTO ai_word_notes (voc_id, spelling, basic_meanings, ielts_focus, collocations, traps, synonyms, discrimination, example_sentences, memory_aid, word_ratings, raw_full_text, prompt_tokens, completion_tokens, total_tokens, batch_id, original_meanings, maimemo_context, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
    
    def _do_sql(cn):
        cur = cn.cursor(); cur.execute(sql, args)
        if not conn: cn.commit(); cn.close()

    if conn:
        _do_sql(conn)
    else:
        path = db_path or DB_PATH
        # 优先写入云端
        try:
            cloud_conn = _get_conn(path)
            if str(cloud_conn).startswith('<libsql.'):  # 云端连接
                _do_sql(cloud_conn)
                # 同步到本地缓存
                try:
                    _do_sql(_get_local_conn(path))
                except:
                    pass
            else:
                # 本地连接，写入本地
                _do_sql(cloud_conn)
        except:
            # 云端失败，写入本地
            _do_sql(_get_local_conn(path))

def get_word_note(voc_id: str, db_path: str = None) -> Optional[dict]:
    c = _get_conn(db_path or DB_PATH); cur = c.cursor(); cur.execute('SELECT * FROM ai_word_notes WHERE voc_id = ?', (str(voc_id),)); r = cur.fetchone(); c.close(); return _row_to_dict(cur, r) if r else None

def find_word_in_community(voc_id: str) -> Optional[Tuple[dict, str]]:
    cdb = os.path.basename(DB_PATH); dr = os.path.dirname(DB_PATH)
    dfs = sorted([f for f in os.listdir(dr) if f.startswith('history_') and f.endswith('.db')], key=lambda x: os.path.getmtime(os.path.join(dr, x)), reverse=True)
    for df in dfs:
        if df == cdb: continue
        try:
            c = _get_local_conn(os.path.join(dr, df)); cur = c.cursor(); cur.execute('SELECT * FROM ai_word_notes WHERE voc_id = ?', (str(voc_id),))
            r = cur.fetchone(); c.close()
            if r: return dict(r), df
        except: continue
    return None

def save_ai_batch(batch_data: dict, db_path: str = None):
    c = _get_conn(db_path or DB_PATH); cur = c.cursor(); cur.execute('INSERT OR REPLACE INTO ai_batches (batch_id, request_id, ai_provider, model_name, prompt_version, batch_size, total_latency_ms, prompt_tokens, completion_tokens, total_tokens, finish_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (batch_data.get('batch_id'), batch_data.get('request_id'), batch_data.get('ai_provider'), batch_data.get('model_name'), batch_data.get('prompt_version'), batch_data.get('batch_size', 1), batch_data.get('total_latency_ms', 0), batch_data.get('prompt_tokens', 0), batch_data.get('completion_tokens', 0), batch_data.get('total_tokens', 0), batch_data.get('finish_reason'))); c.commit(); c.close()

def get_file_hash(file_path):
    if not os.path.exists(file_path): return '00000000'
    with open(file_path, 'rb') as f: return hashlib.md5(f.read()).hexdigest()[:8]

def archive_prompt_file(source_path, prompt_hash, prompt_type='main'):
    ad = os.path.join(DATA_DIR, 'prompts'); os.makedirs(ad, exist_ok=True); tp = os.path.join(ad, f'prompt_{prompt_type}_{prompt_hash}.md')
    if not os.path.exists(tp): shutil.copy2(source_path, tp)

def get_latest_progress(voc_id, db_path=None):
    c = _get_conn(db_path or DB_PATH); cur = c.cursor(); cur.execute('SELECT familiarity_short, review_count FROM word_progress_history WHERE voc_id = ? ORDER BY created_at DESC LIMIT 1', (str(voc_id),)); r = cur.fetchone(); c.close(); return _row_to_dict(cur, r) if r else None

def set_config(k,v,db=None): c = _get_conn(db or DB_PATH); cur = c.cursor(); cur.execute('INSERT OR REPLACE INTO system_config (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)', (k, v)); c.commit(); c.close()
def get_config(k,db=None): c = _get_conn(db or DB_PATH); cur = c.cursor(); cur.execute('SELECT value FROM system_config WHERE key = ?', (k,)); r = cur.fetchone(); c.close(); return r[0] if r else None
def log_progress_snapshots_bulk(w): return log_progress_snapshots(w)
def save_test_word_note(v, p): save_ai_word_note(v, p, db_path=TEST_DB_PATH)
def log_test_run(t, s, w, a, sp, d=True, e="", res=None):
    c = _get_conn(TEST_DB_PATH); cur = c.cursor(); aj = json.dumps(res, ensure_ascii=False) if res else ""; cur.execute('INSERT INTO test_run_logs (total_count, sample_count, sample_words, ai_calls, success_parsed, is_dry_run, error_msg, ai_results_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (t, s, ",".join(w), a, sp, d, e, aj)); c.commit(); rid = cur.lastrowid; c.close(); return rid

@log_performance(lambda: ContextLogger(logging.getLogger(__name__)))
def sync_databases(db_path: str = None, dry_run: bool = False) -> Dict[str, int]:
    """
    双向同步云端和本地数据库，确保数据一致性。
    支持 dry_run 模式，仅返回需要上传和下载的记录数。
    返回格式: {'upload': X, 'download': Y}
    """
    path = db_path or DB_PATH
    stats = {'upload': 0, 'download': 0}
    if not TURSO_DB_URL or not TURSO_AUTH_TOKEN or not HAS_LIBSQL:
        if not dry_run: _debug_log("云端未配置，跳过同步")
        return stats
    
    sync_start = time.time()
    if not dry_run: _debug_log("开始数据库同步...")
    
    try:
        # 获取连接
        cloud_conn = libsql.connect(TURSO_DB_URL, auth_token=TURSO_AUTH_TOKEN)
        local_conn = _get_local_conn(path)
        
        # 注意：libsql 不支持 sqlite3.Row row_factory，选择器内部会用 cursor.description 手动转 dict
        local_conn.row_factory = sqlite3.Row  # 本地 sqlite3 支持
        
        cloud_cur = cloud_conn.cursor()
        local_cur = local_conn.cursor()
        
        # 同步 ai_word_notes
        u, d = _sync_table(cloud_conn, local_conn, 'ai_word_notes', 'voc_id', dry_run)
        stats['upload'] += u; stats['download'] += d
        
        # 同步 processed_words
        u, d = _sync_table(cloud_conn, local_conn, 'processed_words', 'voc_id', dry_run)
        stats['upload'] += u; stats['download'] += d
        
        # 同步 word_progress_history (需要特殊处理，因为有 id 自增)
        u, d = _sync_progress_history(cloud_conn, local_conn, dry_run)
        stats['upload'] += u; stats['download'] += d
        
        # 同步 ai_batches
        u, d = _sync_table(cloud_conn, local_conn, 'ai_batches', 'batch_id', dry_run)
        stats['upload'] += u; stats['download'] += d
        
        # 同步 system_config
        u, d = _sync_table(cloud_conn, local_conn, 'system_config', 'key', dry_run)
        stats['upload'] += u; stats['download'] += d
        # 同步 system_config
        # ... (配置表通常极小，直接同步即可，或者通过 dry_run 略过统计，为简单起见同样计入 stats)
        
        if not dry_run:
            cloud_conn.commit()
            local_conn.commit()
        
        cloud_conn.close()
        local_conn.close()
        
        total_time = int((time.time() - sync_start) * 1000)
        if not dry_run: _debug_log(f"数据库同步完成 | 总耗时: {total_time}ms")
        return stats
        
    except Exception as e:
        _debug_log(f"数据库同步失败: {e}")
        return stats

def _row_to_dict(cursor, row) -> dict:
    """将任意 row 对象（sqlite3.Row 或 libsql tuple）安全转换为 dict。"""
    if isinstance(row, dict):
        return row
    try:
        # sqlite3.Row: keys() 方法
        return dict(zip(row.keys(), tuple(row)))
    except AttributeError:
        # libsql 返回 tuple，用 cursor.description 获取列名
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))

def _sync_table(cloud_conn, local_conn, table_name: str, primary_key: str, dry_run: bool = False):
    """同步单个表，云端优先，本地独有数据上传"""
    cloud_cur = cloud_conn.cursor()
    local_cur = local_conn.cursor()
    
    # 获取云端数据（libsql 返回 tuple，用 _row_to_dict 统一处理）
    cloud_cur.execute(f'SELECT * FROM {table_name}')
    cloud_rows = cloud_cur.fetchall()
    cloud_data = {_row_to_dict(cloud_cur, r)[primary_key]: _row_to_dict(cloud_cur, r) for r in cloud_rows}
    cloud_count = len(cloud_data)
    
    # 获取本地数据（sqlite3.Row 已设置 row_factory，_row_to_dict 同样兼容）
    local_cur.execute(f'SELECT * FROM {table_name}')
    local_rows = local_cur.fetchall()
    local_data = {_row_to_dict(local_cur, r)[primary_key]: _row_to_dict(local_cur, r) for r in local_rows}
    local_count = len(local_data)
    
    if not dry_run: _debug_log(f"  {table_name}: 云端 {cloud_count} 条, 本地 {local_count} 条")
    
    upload_count = 0
    download_count = 0
    
    # 统一时间戳格式以支持可靠比较
    def _clean_ts(ts):
        if not ts: return ""
        # 移除毫秒部分以统一格式
        return str(ts).split('.')[0].replace('T', ' ')

    # 收集待同步的数据
    to_upload = []
    to_download = []

    # 更新云端：本地有但云端没有，或本地更新
    for key, local_row in local_data.items():
        l_ts = _clean_ts(local_row.get('updated_at'))
        c_row = cloud_data.get(key)
        
        if not c_row or l_ts > _clean_ts(c_row.get('updated_at')):
            to_upload.append(local_row)
    
    # 更新本地：云端有但本地没有，或云端更新
    for key, cloud_row in cloud_data.items():
        c_ts = _clean_ts(cloud_row.get('updated_at'))
        l_row = local_data.get(key)
        
        if not l_row or c_ts > _clean_ts(l_row.get('updated_at')):
            to_download.append(cloud_row)

    # 批量提交函数
    def _execute_batch(conn, cur, data, action_name):
        if not data: return 0
        if dry_run: return len(data)
        
        count = 0
        # 批量处理逻辑
        cols = ', '.join(data[0].keys())
        vals = ', '.join(['?'] * len(data[0]))
        sql = f'INSERT OR REPLACE INTO {table_name} ({cols}) VALUES ({vals})'
        
        # 将 data 转换为 tuple 列表以供 executemany 使用
        params = [tuple(r.values()) for r in data]
        
        # 分块执行（Chunking），每 100 条提交一次
        CHUNK_SIZE = 100
        for i in range(0, len(params), CHUNK_SIZE):
            chunk = params[i:i + CHUNK_SIZE]
            try:
                cur.executemany(sql, chunk)
                conn.commit()
                count += len(chunk)
                if len(params) > CHUNK_SIZE:
                    _debug_log(f"  {table_name} {action_name} 进度: {count}/{len(params)}")
            except Exception as e:
                _debug_log(f"  {table_name} {action_name} 批量执行失败: {e}")
        return count

    upload_count = _execute_batch(cloud_conn, cloud_cur, to_upload, "上传")
    download_count = _execute_batch(local_conn, local_cur, to_download, "下载")
    
    if (upload_count > 0 or download_count > 0) and not dry_run:
        _debug_log(f"  {table_name} 同步完成: 上传 {upload_count} 条, 下载 {download_count} 条")
    return len(to_upload), len(to_download)

def _sync_progress_history(cloud_conn, local_conn, dry_run=False):
    """特殊处理 word_progress_history，因为有自增 id"""
    cloud_cur = cloud_conn.cursor()
    local_cur = local_conn.cursor()
    
    # 获取云端数据，按 voc_id 分组取最新
    cloud_cur.execute('SELECT voc_id, MAX(created_at) as latest FROM word_progress_history GROUP BY voc_id')
    cloud_latest = {_row_to_dict(cloud_cur, r)['voc_id']: _row_to_dict(cloud_cur, r)['latest'] for r in cloud_cur.fetchall()}
    
    # 获取本地数据，按 voc_id 分组取最新
    local_cur.execute('SELECT voc_id, MAX(created_at) as latest FROM word_progress_history GROUP BY voc_id')
    local_latest = {_row_to_dict(local_cur, r)['voc_id']: _row_to_dict(local_cur, r)['latest'] for r in local_cur.fetchall()}
    
    to_upload = []
    to_download = []
    
    # 上传本地新数据到云端
    for voc_id, local_time in local_latest.items():
        if voc_id not in cloud_latest or local_time > cloud_latest[voc_id]:
            local_cur.execute('SELECT * FROM word_progress_history WHERE voc_id = ? AND created_at = ?', (voc_id, local_time))
            for row in local_cur.fetchall():
                d = _row_to_dict(local_cur, row)
                to_upload.append({k: v for k, v in d.items() if k != 'id'})
    
    # 下载云端新数据到本地
    for voc_id, cloud_time in cloud_latest.items():
        if voc_id not in local_latest or cloud_time > local_latest[voc_id]:
            cloud_cur.execute('SELECT * FROM word_progress_history WHERE voc_id = ? AND created_at = ?', (voc_id, cloud_time))
            for row in cloud_cur.fetchall():
                d = _row_to_dict(cloud_cur, row)
                to_download.append({k: v for k, v in d.items() if k != 'id'})

    def _batch_history(conn, cur, data, name):
        if not data: return 0
        if dry_run: return len(data)
        cols = ', '.join(data[0].keys()); vals = ', '.join(['?'] * len(data[0]))
        params = [tuple(r.values()) for r in data]
        try:
            # 使用 INSERT OR IGNORE 以配合唯一约束 idx_progress_unique
            cur.executemany(f'INSERT OR IGNORE INTO word_progress_history ({cols}) VALUES ({vals})', params)
            conn.commit()
            if not dry_run: _debug_log(f"  word_progress_history {name} 完成: {len(data)} 条")
        except Exception as e:
            if not dry_run: _debug_log(f"  word_progress_history {name} 失败: {e}")
        return len(data)

    u = _batch_history(cloud_conn, cloud_cur, to_upload, "上传")
    d = _batch_history(local_conn, local_cur, to_download, "下载")
    return (u, d)
