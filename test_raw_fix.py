#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
sys.path.append('.')

from core.db_manager import init_db, save_ai_word_note
from core.gemini_client import GeminiClient

# 初始化 DB
init_db()

# 测试 Gemini 客户端
client = GeminiClient('dummy_key')  # 不会真的调用，因为没有 key

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
save_ai_word_note('123', mock_results[0])

print('Test completed: raw_full_text should be saved.')