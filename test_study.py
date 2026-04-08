import sys
import io
import json
from maimemo_api import MaiMemoAPI
from config import MOMO_TOKEN, GEMINI_API_KEY

# 解决 Windows 控制台输出中文的乱码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# 你的墨墨背单词开放平台 Token (已移至 config.py)

def main():
    momo = MaiMemoAPI(MOMO_TOKEN)
    print("正在拉取今日待学习/待复习的单词...")
    
    # 刚才修改了 SDK，这里现在默认 limit 为 500 了
    res = momo.get_today_items()
    
    if res and res.get("success"):
        items = res.get("data", {}).get("today_items", [])
        
        print(f"\n[成功] 拉取完毕！今日共有 {len(items)} 个单词任务。\n")
        
        if items:
            print("单词列表预览 (最多展示拉取到的前 200 个)：")
            print(json.dumps(items[:200], indent=4, ensure_ascii=False))
        else:
            print("你的 today_items 列表为空。")

if __name__ == "__main__":
    main()
