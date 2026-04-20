#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试模型切换功能
"""

import sys
import os

# 路径修正
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from config import AI_PROVIDER, GEMINI_API_KEY, MIMO_API_KEY
from compat.gemini_client import GeminiClient
from mimo_client import MimoClient

def test_gemini_client():
    """测试 Gemini 客户端"""
    print("====== 测试 Gemini 客户端 ======")
    if not GEMINI_API_KEY:
        print("  [跳过] 未配置 GEMINI_API_KEY")
        return False

    try:
        client = GeminiClient(GEMINI_API_KEY)
        print(f"  [Info] 模型: {client.model_name}")

        # 简单测试
        test_words = ["apple"]
        result = client.generate_mnemonics(test_words)

        if result and len(result) > 0:
            print(f"  ✅ Gemini 测试成功，返回 {len(result)} 个结果")
            print(f"  单词: {result[0].get('spelling', 'N/A')}")
            return True
        else:
            print(f"  ❌ Gemini 测试失败，返回空结果")
            return False
    except Exception as e:
        print(f"  ❌ Gemini 测试异常: {e}")
        return False


def test_mimo_client():
    """测试 Mimo 客户端"""
    print("\n====== 测试 Mimo 客户端 ======")
    if not MIMO_API_KEY:
        print("  [跳过] 未配置 MIMO_API_KEY")
        return False

    try:
        client = MimoClient(MIMO_API_KEY)
        print(f"  [Info] 模型: {client.model_name}")

        # 简单测试
        test_words = ["apple"]
        result = client.generate_mnemonics(test_words)

        if result and len(result) > 0:
            print(f"  ✅ Mimo 测试成功，返回 {len(result)} 个结果")
            print(f"  单词: {result[0].get('spelling', 'N/A')}")
            return True
        else:
            print(f"  ❌ Mimo 测试失败，返回空结果")
            return False
    except Exception as e:
        print(f"  ❌ Mimo 测试异常: {e}")
        return False


def test_provider_selection():
    """测试提供商会根据配置自动选择"""
    print("\n====== 测试提供商会根据配置自动选择 ======")
    print(f"  当前 AI_PROVIDER 配置: {AI_PROVIDER}")

    if AI_PROVIDER == "mimo":
        print("  [Info] 配置为使用 Mimo")
        if MIMO_API_KEY:
            print("  ✅ Mimo API Key 已配置")
        else:
            print("  ❌ Mimo API Key 未配置")
    else:
        print("  [Info] 配置为使用 Gemini")
        if GEMINI_API_KEY:
            print("  ✅ Gemini API Key 已配置")
        else:
            print("  ❌ Gemini API Key 未配置")


if __name__ == "__main__":
    # 终端编码修正
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    print("🚀 开始测试模型切换功能\n")

    test_provider_selection()

    # 测试两个客户端
    gemini_success = test_gemini_client()
    mimo_success = test_mimo_client()

    print("\n====== 测试总结 ======")
    print(f"Gemini 客户端: {'✅ 通过' if gemini_success else '❌ 失败/跳过'}")
    print(f"Mimo 客户端: {'✅ 通过' if mimo_success else '❌ 失败/跳过'}")

    if AI_PROVIDER == "mimo" and not mimo_success:
        print("\n⚠️  警告: 当前配置使用 Mimo，但 Mimo 测试失败")
    elif AI_PROVIDER != "mimo" and not gemini_success:
        print("\n⚠️  警告: 当前配置使用 Gemini，但 Gemini 测试失败")