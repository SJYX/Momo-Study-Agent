# -*- coding: utf-8 -*-
"""
Phase 0: Turso Embedded Replicas 验证脚本
验证 libsql 包在 Windows 上的 Embedded Replica 功能。
"""
import os
import sys
import tempfile

# 加载 .env 配置
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
try:
    from dotenv import load_dotenv
    # 先加载根 .env
    load_dotenv(os.path.join(PROJECT_ROOT, '.env'))
    # 再加载 profile env（覆盖根配置，获取 TURSO_DB_URL 等）
    profiles_dir = os.path.join(PROJECT_ROOT, 'data', 'profiles')
    if os.path.isdir(profiles_dir):
        for f in sorted(os.listdir(profiles_dir)):
            if f.endswith('.env'):
                load_dotenv(os.path.join(profiles_dir, f), override=True)
except ImportError:
    pass


def test_basic_import():
    """测试 1: libsql 包导入"""
    try:
        import libsql
        print(f"✅ [1/6] libsql 导入成功, 版本信息: {getattr(libsql, '__version__', 'unknown')}")
        return True
    except ImportError as e:
        print(f"❌ [1/6] libsql 导入失败: {e}")
        return False


def test_local_only():
    """测试 2: 纯本地 SQLite 模式"""
    import libsql
    local_path = os.path.join(tempfile.gettempdir(), "er_test_local.db")
    try:
        conn = libsql.connect(local_path)
        conn.execute("CREATE TABLE IF NOT EXISTS test_table (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT OR REPLACE INTO test_table (id, name) VALUES (1, 'hello')")
        conn.commit()
        row = conn.execute("SELECT name FROM test_table WHERE id = 1").fetchone()
        assert row[0] == 'hello', f"Expected 'hello', got {row[0]}"
        conn.close()
        print(f"✅ [2/6] 纯本地模式正常工作")
        return True
    except Exception as e:
        print(f"❌ [2/6] 纯本地模式失败: {e}")
        return False
    finally:
        for ext in ("", "-wal", "-shm"):
            try:
                os.remove(local_path + ext)
            except:
                pass


def test_embedded_replica_connect():
    """测试 3: Embedded Replica 连接创建"""
    import libsql
    url = os.getenv('TURSO_DB_URL', '').strip()
    token = os.getenv('TURSO_AUTH_TOKEN', '').strip()

    if not url or not token:
        print("⏭️  [3/6] 跳过: TURSO_DB_URL / TURSO_AUTH_TOKEN 未配置")
        return None

    local_path = os.path.join(tempfile.gettempdir(), "er_test_replica.db")
    try:
        conn = libsql.connect(local_path, sync_url=url, auth_token=token)
        print(f"✅ [3/6] Embedded Replica 连接创建成功: {local_path} ↔ {url[:50]}...")
        return conn, local_path
    except Exception as e:
        print(f"❌ [3/6] Embedded Replica 连接失败: {e}")
        return False


def test_sync(conn):
    """测试 4: conn.sync() 同步"""
    try:
        result = conn.sync()
        print(f"✅ [4/6] sync() 成功, 返回值: {result}")
        return True
    except Exception as e:
        print(f"❌ [4/6] sync() 失败: {e}")
        return False


def test_local_read(conn):
    """测试 5: 同步后本地读取"""
    try:
        # 尝试读取已有的表
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t[0] for t in tables]
        print(f"✅ [5/6] 本地读取成功, 发现 {len(table_names)} 张表: {', '.join(table_names[:5])}{'...' if len(table_names) > 5 else ''}")

        # 尝试计数
        for tbl in ['processed_words', 'ai_word_notes']:
            if tbl in table_names:
                count = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                print(f"   📊 {tbl}: {count} 条记录")
        return True
    except Exception as e:
        print(f"❌ [5/6] 本地读取失败: {e}")
        return False


def test_write_roundtrip(conn):
    """测试 6: 写入 → 远程转发 → 读回验证"""
    try:
        conn.execute(
            "INSERT OR REPLACE INTO system_config (key, value, updated_at) VALUES (?, ?, datetime('now'))",
            ("_er_verify_test", "embedded_replica_ok")
        )
        conn.commit()

        row = conn.execute(
            "SELECT value FROM system_config WHERE key = ?", ("_er_verify_test",)
        ).fetchone()
        assert row is not None, "写入后读回为空"
        assert row[0] == "embedded_replica_ok", f"读回值不匹配: {row[0]}"

        # 清理
        conn.execute("DELETE FROM system_config WHERE key = '_er_verify_test'")
        conn.commit()

        print(f"✅ [6/6] 写入→远程转发→读回验证通过")
        return True
    except Exception as e:
        print(f"❌ [6/6] 写入验证失败: {e}")
        return False


def main():
    print("=" * 60)
    print("  Turso Embedded Replicas - Windows 验证")
    print("=" * 60)
    print()

    results = []

    # Test 1: Import
    results.append(test_basic_import())
    if not results[-1]:
        print("\n💀 libsql 无法导入，终止验证。")
        return False

    # Test 2: Local-only
    results.append(test_local_only())

    # Test 3-6: Embedded Replica (requires cloud credentials)
    er_result = test_embedded_replica_connect()
    if er_result is None:
        print("\n⚠️  云端凭据未配置，仅验证了本地模式。")
        print("   请设置 TURSO_DB_URL 和 TURSO_AUTH_TOKEN 后重试。")
        return all(r for r in results if r is not None)
    elif er_result is False:
        results.append(False)
    else:
        conn, local_path = er_result
        results.append(True)
        results.append(test_sync(conn))
        results.append(test_local_read(conn))
        results.append(test_write_roundtrip(conn))

        conn.close()
        for ext in ("", "-wal", "-shm"):
            try:
                os.remove(local_path + ext)
            except:
                pass

    print()
    passed = sum(1 for r in results if r is True)
    failed = sum(1 for r in results if r is False)
    total = len(results)
    print("=" * 60)
    if failed == 0:
        print(f"  🎉 全部通过! ({passed}/{total})")
        print("  可以进入 Phase 1: 连接层迁移")
    else:
        print(f"  ⚠️  {failed} 项失败 ({passed}/{total} 通过)")
        print("  请解决失败项后再进行迁移")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
