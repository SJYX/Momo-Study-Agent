import sys
import os
import json

# 注入根目录以正确导入模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.mimo_client import MimoClient
from core.db_manager import save_test_word_note, log_test_run, is_processed, mark_processed, TEST_DB_PATH

def test_pipeline():
    print("=== Mimo Pipeline Validation Test ===")
    print(f"Target DB: {TEST_DB_PATH}")

    # 1. 准备测试单词
    test_words = ["run"]
    words_to_process = test_words
    
    # 2. 实例化 Mimo 客户端
    client = MimoClient()
    print(f"\n[AI] Sending words to Mimo Model ({client.model_name}): {words_to_process}")
    
    try:
        # 请求助记生成
        results = client.generate_mnemonics(words_to_process)
        print(f"\n[AI] Generated Results ({len(results)} items):")
        print(json.dumps(results, indent=2, ensure_ascii=False))
        
        # 3. 结果写出到分离的测试数据库
        if not results:
            print("\n[-] AI returned empty or failed to parse.")
        
        success_count = 0
        for item in results:
            # 在真实的由于没有从墨墨侧拉取，所以我们伪造一个 voc_id
            spell = item.get("spelling", "unknown")
            voc_id = f"mock_{spell}"
            
            print(f"  -> Saving note for: {spell} (ID: {voc_id}) to TEST DB")
            # 写入笔记体
            save_test_word_note(voc_id, item)
            # 写入状态表以防未来重复查
            mark_processed(voc_id, spell, db_path=TEST_DB_PATH)
            
            success_count += 1
            
        # 4. 录入运行日志表 
        log_payload = {
            "results": results,
            "token_usage": getattr(client, "last_usage", {})
        }
        
        log_id = log_test_run(
            total_count=len(test_words),
            sample_count=len(words_to_process),
            words_sampled=words_to_process,
            ai_calls=1,
            success_parsed=success_count,
            is_dry_run=True, # 不推送到墨墨，所以是 dry_run
            ai_results=log_payload
        )
        print(f"\n[SUCCESS] Pipeline complete! Test log saved with ID -> {log_id}")

    except Exception as e:
        print(f"\n[FAILED] Error occurred: {e}")
        # 记录失败日志
        log_test_run(
            total_count=len(test_words),
            sample_count=len(words_to_process),
            words_sampled=words_to_process,
            ai_calls=1,
            success_parsed=0,
            is_dry_run=True,
            error_msg=str(e)
        )

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf8')
    test_pipeline()
