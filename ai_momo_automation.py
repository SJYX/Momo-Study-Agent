import sys
import io
import time
import json
import os
import google.generativeai as genai
from maimemo_api import MaiMemoAPI

# 解决终端中文的输出乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

from config import MOMO_TOKEN, GEMINI_API_KEY

# ==================== 配置区 ====================
# (密钥已移至 config.py 文件内，并受 .gitignore 保护不上传至 GitHub)

# 【安全开关】是否使用试运行模式？
# 如果为 True，脚本只会请求大模型生成内容打印在屏幕上给你看，但【绝不会】向墨墨的服务器写入数据。
# 确认生成效果满意后，将这里改为 False 即可正式打通系统。
DRY_RUN = True

# 是否仅处理新词？
# 如果为 True，只对今天的新词(is_new=True)生成并注入记忆法，老词复习就会被跳过，防止加了一堆重复笔记。
# 如果为 False，则对今日的所有 120 词进行批量生成。
ONLY_PROCESS_NEW = False

# 你刚才选择的 方案 B：外部文件 Prompt 模板路径
PROMPT_FILE = "gem_prompt.txt"
# ================================================

def load_system_instruction() -> str:
    """载入外部的系统提示词(定制化Gem设定)"""
    if not os.path.exists(PROMPT_FILE):
        return "你是一个高效的单词助记助手，请用简短有趣的谐音或者词根给下面的单词一句话建立联系。"
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()

def chunk_list(lst, chunk_size):
    """固定大小对单词列表切堆(即咱们商量的按量发送)"""
    for i in range(0, len(lst), chunk_size):
        yield lst[i:i + chunk_size]

def get_ai_mnemonics(words_batch, custom_gem):
    """连线 Gemini 获取记忆法字典"""
    # 让 AI 绝对遵守格式，以便我们能够程序化解析并逐个击破
    prompt = f"""
    我给你 {len(words_batch)} 个英语单词。请按系统设定为每个词生成一句绝妙助记法。
    请严格以 JSON 数组格式原样返回，包含 spelling 和 mnemonic 两项，不要有其余任何解释文字：
    [
        {{"spelling": "单词1", "mnemonic": "助记1"}},
        {{"spelling": "单词2", "mnemonic": "助记2"}}
    ]

    待处理单词列表: {", ".join(words_batch)}
    """
    
    try:
        response = custom_gem.generate_content(prompt)
        text = response.text.strip()
        
        # 清洗由于大模型天性自带的 markdown json 外壳标记
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
            
        result_json = json.loads(text.strip())
        return result_json
    except Exception as e:
        print(f"  [AI请求异常/数据不规范]: {e}")
        print(f"  [被舍弃的错误返回文为]:\n{response.text if 'response' in locals() else 'None'}")
        return []

def main():
    print("====== 🚀 启动全自动背单词黑科技流 ======")
    
    # 1. 组装专属于你的 AI 脑袋
    genai.configure(api_key=GEMINI_API_KEY)
    gem_rules = load_system_instruction()
    print(f"[*] 成功加载本地 {PROMPT_FILE} 人格设定 (共 {len(gem_rules)} 字)")
    
    # 指派模型
    custom_gem = genai.GenerativeModel(
        model_name="gemini-1.5-flash", # 这里调用兼顾速度和能力的极速版本模型
        system_instruction=gem_rules
    )
    
    # 2. 从墨墨拉取咱们的 120 个兵
    momo = MaiMemoAPI(MOMO_TOKEN)
    res = momo.get_today_items()
    if not res or not res.get("success"):
        print("[错误] 墨墨背单词接口数据抓取挫败，请检查网络！")
        return
        
    all_items = res.get("data", {}).get("today_items", [])
    print(f"[*] 解析到 {len(all_items)} 个原始单词数据结构。")
    
    word_dict = {}
    for item in all_items:
        spelling = item.get("voc_spelling")
        if ONLY_PROCESS_NEW and not item.get("is_new", False):
            continue
        word_dict[spelling] = item.get("voc_id")
        
    target_words = list(word_dict.keys())
    print(f"[*] 经过过滤器筛选去重，本次将送往工厂组装的实词共 {len(target_words)} 个！\n")
    
    if not target_words:
        print("所有单词都由于规则被砍飞了，无需工作。")
        return
        
    # 3. 按批次大炼钢铁
    BATCH_SIZE = 15 # 每次并发要求大模型吐15个词的答案，降低请求次数
    batches = list(chunk_list(target_words, BATCH_SIZE))
    
    for idx, batch in enumerate(batches):
        print(f"---> 开始向 AI 发送第 {idx+1}/{len(batches)} 批次请求库卡 (约包含 {len(batch)} 词)...")
        
        ai_results = get_ai_mnemonics(batch, custom_gem)
        
        if not ai_results:
            print("[警告] 本批次生成由于意外全军覆没或解析错位，跳过后续操作。")
            continue
            
        for ai_item in ai_results:
            w_spell = ai_item.get("spelling", "")
            mnemonic = ai_item.get("mnemonic", "")
            w_id = word_dict.get(w_spell)
            
            # 有且有值时，才执行落库
            if w_id and mnemonic:
                print(f"  > [AI 妙语] {w_spell}: {mnemonic}")
                
                # ==== 真实的写入步骤 ====
                if not DRY_RUN:
                    time.sleep(0.5) 
                    # 将这句助记作为 `AI专供助记` 分类创建进单次的笔记薄中
                    success = momo.create_note(w_id, "AI专供", mnemonic)
                    if success:
                        print("    ┗[入库同步] -> 绿灯！墨墨端已可见")
                    else:
                        print("    ┗[入库同步] -> 红灯阻截/存在异常")
        
        # Gemini 基础频控护卫：两批之间暂停，防止把人家压死封卡禁号
        if idx < len(batches) - 1:
            time.sleep(4)

    print("\n====== 全线任务打卡结束 ======")
    if DRY_RUN:
        print("\n当前系统工作在安全模拟/Dry Run模式。")
        print("您看到的妙语没有真实写入到您的手机上墨墨账号里。")
        print("修改脚本中 DRY_RUN = False 即可大开杀戒真实写入！")

if __name__ == "__main__":
    main()
