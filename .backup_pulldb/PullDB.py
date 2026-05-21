import os
import sys
import turso.sync

# 1. 配置你的远程 Turso 凭证
# 建议通过环境变量读取，或者直接替换为你的字符串
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "libsql://history-asher-ashershi.aws-ap-northeast-1.turso.io")
# 修改这一行，强制清空可能存在的尾部换行或空格
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3NzkzMjU3MTQsImlkIjoiMDE5ZDlhNjMtZmUwMS03OTAyLWFhZmEtNGNiNjg3YjBiMGY2IiwicmlkIjoiYTZhMmY4YzAtZjAwMC00YWIzLWIzOGUtY2RhZWM5YjU3M2JmIn0.ghiO9KEa-hyykYfDg0Oo94fUIoxoVWRBiJaY_d2cST7jQLO2cYhUDzLhqrH7pobNWEqCvIQLVN98zg0ugqFOCA").strip()

# 本地数据库文件路径（如果文件不存在，pyturso 会自动创建它）
LOCAL_DB_PATH = "local_replica.db"

def pull_database():
    print(f"正在连接远程数据库并初始化本地文件: {LOCAL_DB_PATH}...")
    
    try:
        # 2. 建立同步连接
        # 注意：默认情况下，如果本地文件为空，pyturso 在 connect 时就会自动从云端进行完整拉取（Bootstrap）
        conn = turso.sync.connect(
            LOCAL_DB_PATH,
            remote_url=TURSO_DATABASE_URL,
            auth_token=TURSO_AUTH_TOKEN
        )
        
        # 3. 显式调用 pull() 确保拉取最新变更
        # pull() 会返回一个布尔值：如果有新的远程变更被应用到本地，则返回 True
        print("正在检查并拉取远程最新变更...")
        has_changes = conn.pull()
        
        if has_changes:
            print("成功！已从云端同步了新的数据到本地。")
        else:
            print("本地已是最新状态，未检测到新的远程变更。")
            
        # 4. 验证：打印本地解密/同步后的表结构或数据
        print("\n--- 本地数据库中的表列表 ---")
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        if tables:
            for table in tables:
                print(f"表名: {table[0]}")
        else:
            print("未找到任何表（可能远程库本身就是空的）。")
            
        # 5. 关闭连接
        conn.close()
        print("\n同步完成，连接已关闭。")
        
    except Exception as e:
        print(f"同步过程中发生错误: {e}", file=sys.stderr)

if __name__ == "__main__":
    # 执行前确保安装了最新版 pyturso: pip install pyturso
    pull_database()