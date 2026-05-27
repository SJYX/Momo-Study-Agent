#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
sys.path.append('.')

from database.momo_words import save_ai_word_note
from database.schema import init_db
from config import TEST_DB_PATH
from core.litellm_client import LiteLLMClient

# 初始化 DB
init_db(TEST_DB_PATH)

# 测试客户端（不会真的调用，因为没有有效 key）
client = LiteLLMClient(model="gemini/gemini-2.0-flash", api_key="dummy_key")

# 模拟结果
mock_results = [
    {
        'spelling': 'test',
        'basic_meanings': '测试',
        'memory_aid': '助记',
        'raw_full_text': '模拟原始文本'
    }
]

# 保存
save_ai_word_note('123', mock_results[0], db_path=TEST_DB_PATH)

print('Test completed on TEST_DB_PATH: raw_full_text should be saved.')