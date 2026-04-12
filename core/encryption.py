# -*- coding: utf-8 -*-
"""
Fernet 对称加密工具模块

用于加密存储敏感数据（API Key、Token 等）。
"""

import os
from cryptography.fernet import Fernet

# 从环境变量读取加密密钥，如果不存在则生成警告
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')

if not ENCRYPTION_KEY:
    import warnings
    warnings.warn(
        "ENCRYPTION_KEY 环境变量未设置。敏感数据加密功能将不可用。"
        "请在 .env 或系统环境中设置 ENCRYPTION_KEY (32 字节 Base64 编码)。",
        RuntimeWarning
    )


def generate_key() -> str:
    """
    生成新的 Fernet 密钥（32 字节 Base64 编码）。
    用于首次初始化或密钥轮转。
    
    返回：Base64 编码的密钥字符串
    """
    key = Fernet.generate_key()
    return key.decode('utf-8')


def encrypt_field(value: str) -> str:
    """
    加密单个字段值。
    
    参数：
        value: 待加密的明文字符串
        
    返回：
        Base64 编码的密文字符串
        
    异常：
        RuntimeError: 如果 ENCRYPTION_KEY 未配置
        InvalidToken: 如果加密失败
    """
    if not ENCRYPTION_KEY:
        raise RuntimeError(
            "ENCRYPTION_KEY 未配置。请在环境变量中设置加密密钥。"
        )
    
    cipher = Fernet(ENCRYPTION_KEY.encode('utf-8'))
    encrypted = cipher.encrypt(value.encode('utf-8'))
    return encrypted.decode('utf-8')


def decrypt_field(encrypted_value: str) -> str:
    """
    解密单个字段值。
    
    参数：
        encrypted_value: Base64 编码的密文字符串
        
    返回：
        解密后的明文字符串
        
    异常：
        RuntimeError: 如果 ENCRYPTION_KEY 未配置
        InvalidToken: 如果解密失败或数据损坏
    """
    if not ENCRYPTION_KEY:
        raise RuntimeError(
            "ENCRYPTION_KEY 未配置。请在环境变量中设置加密密钥。"
        )
    
    cipher = Fernet(ENCRYPTION_KEY.encode('utf-8'))
    decrypted = cipher.decrypt(encrypted_value.encode('utf-8'))
    return decrypted.decode('utf-8')


def encrypt_dict(data: dict, keys_to_encrypt: list) -> dict:
    """
    加密字典中的指定键值对。
    
    参数：
        data: 原始字典
        keys_to_encrypt: 需要加密的键列表
        
    返回：
        修改后的字典（加密特定字段）
    """
    result = data.copy()
    for key in keys_to_encrypt:
        if key in result and result[key]:
            result[key] = encrypt_field(result[key])
    return result


def decrypt_dict(data: dict, keys_to_decrypt: list) -> dict:
    """
    解密字典中的指定键值对。
    
    参数：
        data: 包含密文的字典
        keys_to_decrypt: 需要解密的键列表
        
    返回：
        修改后的字典（解密特定字段）
    """
    result = data.copy()
    for key in keys_to_decrypt:
        if key in result and result[key]:
            result[key] = decrypt_field(result[key])
    return result
