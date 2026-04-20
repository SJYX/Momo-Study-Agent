"""
Phase 0 快速验证脚本 - 仅测试本地模式可用性
如果本地模式通过，则表示 libsql 在 Windows 上可用
"""
import os
import sys
import tempfile
import subprocess

def run_test():
    print("=" * 60)
    print("  libsql Embedded Replicas - Windows 快速验证")
    print("=" * 60)
    print()
    
    print("[Test 1] 检查 libsql 导入...")
    try:
        import libsql
        print("✅ libsql 导入成功")
    except ImportError as e:
        print(f"❌ libsql 导入失败: {e}")
        return False
    
    print("\n[Test 2] 创建本地 Embedded Replica 文件...")
    local_db = os.path.join(tempfile.gettempdir(), "er_test_quick.db")
    try:
        # 创建最简单的数据库
        conn = libsql.connect(local_db)
        conn.execute("CREATE TABLE IF NOT EXISTS test (id INTEGER, data TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'hello')")
        conn.commit()
        
        # 验证读取
        row = conn.execute("SELECT data FROM test WHERE id = 1").fetchone()
        assert row[0] == 'hello'
        conn.close()
        
        print(f"✅ 本地读写验证成功")
        print(f"   数据库文件: {local_db}")
    except Exception as e:
        print(f"❌ 本地模式失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # 清理
        for ext in ("", "-wal", "-shm"):
            try:
                os.remove(local_db + ext)
            except:
                pass
    
    print("\n[Test 3] 检查 Turso 凭据配置...")
    url = os.getenv('TURSO_DB_URL', '').strip()
    token = os.getenv('TURSO_AUTH_TOKEN', '').strip()
    
    if not url or not token:
        print("⏭️  Turso 凭据未配置（正常）")
        print("   可在纯本地模式下使用 libsql.connect('db.db')")
        print("\n" + "=" * 60)
        print("✅ Phase 0 验证完成：Windows 本地模式正常工作")
        print("   可进入 Phase 1: 连接层迁移")
        print("=" * 60)
        return True
    
    print(f"✅ 检测到 Turso 凭据")
    print(f"   URL: {url[:50]}...")
    print(f"   Token: {token[:20]}...")
    
    print("\n[Test 4] 测试 Embedded Replica 连接（30秒超时）...")
    er_db = os.path.join(tempfile.gettempdir(), "er_test_hybrid.db")
    
    try:
        # 使用 signal 实现超时（仅限 Unix，Windows 需要线程）
        import threading
        result_holder = [False, None]
        
        def connect_er():
            try:
                conn = libsql.connect(er_db, sync_url=url, auth_token=token)
                conn.sync()
                result_holder[0] = True
                result_holder[1] = None
                conn.close()
            except Exception as e:
                result_holder[0] = False
                result_holder[1] = str(e)
        
        thread = threading.Thread(target=connect_er, daemon=True)
        thread.start()
        thread.join(timeout=30)
        
        if thread.is_alive():
            print("⏱️  Embedded Replica 连接超时（30秒）")
            print("   可能原因：网络延迟或 Turso 服务响应慢")
        elif result_holder[0]:
            print("✅ Embedded Replica 连接和 sync() 成功")
        else:
            print(f"❌ Embedded Replica 连接失败: {result_holder[1]}")
            return False
            
    except Exception as e:
        print(f"⚠️  Embedded Replica 测试异常: {e}")
    finally:
        # 清理
        for ext in ("", "-wal", "-shm"):
            try:
                os.remove(er_db + ext)
            except:
                pass
    
    print("\n" + "=" * 60)
    print("✅ Phase 0 验证完成")
    print("   Windows libsql 本地模式正常")
    print("   可进入 Phase 1: 连接层迁移")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
