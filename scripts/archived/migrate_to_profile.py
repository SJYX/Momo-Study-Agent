import sys
import io
import os
import shutil

# 强制 UTF-8 编码避免 Windows 终端乱码
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# 注入根目录
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data")
PROFILES_DIR = os.path.join(DATA_DIR, "profiles")

def migrate(target_username):
    print(f"🚀 [Migration] 正在将现有数据迁移至用户: {target_username}")

    # 1. 确保目录存在
    os.makedirs(PROFILES_DIR, exist_ok=True)

    # 2. 迁移环境配置文件
    env_src = os.path.join(ROOT_DIR, ".env")
    env_dest = os.path.join(PROFILES_DIR, f"{target_username}.env")

    if os.path.exists(env_src):
        shutil.copy2(env_src, env_dest)
        print(f"  ✅ 配置文件已迁移: .env -> data/profiles/{target_username}.env")
    else:
        print(f"  ⚠️ 未找到根目录下 .env 文件，跳过配置迁移。")

    # 3. 迁移数据库文件
    db_src = os.path.join(DATA_DIR, "history.db")
    db_dest = os.path.join(DATA_DIR, f"history_{target_username}.db")

    if os.path.exists(db_src):
        shutil.copy2(db_src, db_dest)
        print(f"  ✅ 数据库已迁移: data/history.db -> data/history_{target_username}.db")
    else:
        print(f"  ⚠️ 未找到 data/history.db，跳过数据库迁移。")

    print(f"\n✨ [Finish] 迁移完成！您现在可以使用用户 '{target_username}' 启动程序了。")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        username = sys.argv[1]
    else:
        username = input("请输入迁移目标用户名 (例如 Asher): ").strip()
    
    if not username:
        print("❌ 错误: 用户名不能为空")
        sys.exit(1)
        
    migrate(username)
