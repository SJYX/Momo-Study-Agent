# -*- coding: utf-8 -*-
import sys
import io
import requests
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# ================= 配置区域 =================
# 从被保护的 config.py 里自动读取
from config import MOMO_TOKEN
ACCESS_TOKEN = MOMO_TOKEN

# 墨墨开放 API 的基础 URL
BASE_URL = "https://open.maimemo.com/open/api/v1"

# 请求头配置
HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}
# ============================================

def get_voc_id(spelling: str) -> str:
    """
    第一步：通过单词的拼写，查询它在墨墨词库中的核心 ID (voc_id)
    """
    url = f"{BASE_URL}/vocabulary"
    
    # 频控策略：10秒20次。脚本中可以适当增加 sleep 防风控
    time.sleep(0.5) 
    
    response = requests.get(url, headers=HEADERS, params={"spelling": spelling})
    
    if response.status_code == 200:
        data = response.json()
        voc_data = data.get("data", {}).get("voc")
        if voc_data:
            voc_id = voc_data["id"]
            print(f"[成功] 找到单词 '{spelling}' 的 voc_id: {voc_id}")
            return voc_id
        else:
            print(f"[失败] 墨墨词库中未找到单词 '{spelling}'")
            return None
    else:
        print(f"[错误] 请求词库报错: {response.text}")
        return None

def create_or_update_interpretation(voc_id: str, new_meaning: str, tags: list = None):
    """
    第二步：使用 voc_id 为单词创建自定义释义
    （官方开放API的设定是：给单词添加"自己的释义"）
    """
    if tags is None:
        tags = []
        
    url = f"{BASE_URL}/interpretations"
    payload = {
        "interpretation": {
            "voc_id": voc_id,
            "interpretation": new_meaning,
            "tags": tags,
            "status": "PUBLISHED"  # 状态：发布
        }
    }
    
    time.sleep(0.5)
    response = requests.post(url, headers=HEADERS, json=payload)
    
    if response.status_code == 200:
        print(f"[成功] 释义已更新！内容: {new_meaning}")
        return response.json()
    else:
        print(f"[错误] 创建释义报错: {response.text}")
        print("提示：如果该生词你已经创建过释义，需要走 Update 接口而不是 Create 接口。")
        return None

# ================= 测试运行 =================
if __name__ == "__main__":
    if len(ACCESS_TOKEN) < 10:
        print("请先在代码配置区填写你的 ACCESS_TOKEN ！")
    else:
        target_word = "apple"
        custom_meaning = "n. 苹果（这是通过开放API写入的自定义释义！）"
        
        # 1. 获取单词 ID
        vid = get_voc_id(target_word)
        
        if vid:
            # 2. 更新或新建该单词的释义
            create_or_update_interpretation(vid, custom_meaning)
