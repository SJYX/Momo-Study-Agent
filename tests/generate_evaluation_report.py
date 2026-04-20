import sys
import os
import json
import time

# 修正工作目录以正确加载上层依赖
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from core.mimo_client import MimoClient

import io

def main():
    # 终端编码修正，防止打印 Emoji 翻车
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
        
    test_words = ["get", "set", "minute", "run"]
    client = MimoClient()

    output_file = os.path.join(ROOT_DIR, "docs", "prompt_evaluation_sample.md")
    
    # 建立 Markdown 骨架
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("# 词汇提示词逆向评估样本 (Prompt Evaluation Sample)\n\n")
        f.write("> 评估目的：检查系统设定的 Prompt 是否让模型输出了过度简略或逻辑重复的废话。主要观察这四个极难发散的高频多义词表现。\n\n")
        f.write(f"**测试模型**: `{client.model_name}`\n")
        f.write(f"**测试词汇**: {', '.join(test_words)}\n")
        f.write("---\n\n")

    print("🚀 正在为您利用单点查询模式拉取终极评估词汇...")

    for word in test_words:
        print(f"⏳ 正在请求极端多义词: {word.upper()} ...")
        # 严格遵守 1个单元 长度度查询
        results = client.generate_mnemonics([word])
        if not results:
            print(f"❌ '{word}' 获取失败或解析错误。")
            continue
            
        data = results[0]
        
        # 格式化并追加到 Markdown
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"## 【{data.get('spelling', word).upper()}】\n\n")
            f.write(f"**📝 Basic Meanings (基本释义):**\n{data.get('basic_meanings', '')}\n\n")
            f.write(f"**🎯 IELTS Focus (雅思考点):**\n{data.get('ielts_focus', '')}\n\n")
            f.write(f"**🔗 Collocations (核心搭配):**\n{data.get('collocations', '')}\n\n")
            f.write(f"**⚠️ Traps (避坑陷阱):**\n{data.get('traps', '')}\n\n")
            f.write(f"**🔄 Synonyms (同义替换):**\n{data.get('synonyms', '')}\n\n")
            f.write(f"**⚖️ Discrimination (词义辨析):**\n{data.get('discrimination', '')}\n\n")
            f.write(f"**📚 Example Sentences (场景例句):**\n{data.get('example_sentences', '')}\n\n")
            f.write(f"**🧠 Memory Aid (超级助记法):**\n{data.get('memory_aid', '')}\n\n")
            f.write(f"**⭐ Word Ratings (单词价值评级):**\n{data.get('word_ratings', '')}\n\n")
            f.write("---\n\n")
            
        print(f"  ✅ '{word}' 已解构并写入评估报告。")
        # 短暂休眠避免请求撞车
        time.sleep(1)

    print(f"\n🎉 评估样本生成完成！去其他文档审阅吧，文件路径:\n📄 -> {output_file}")

if __name__ == "__main__":
    main()
