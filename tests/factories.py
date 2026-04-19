import uuid
from typing import Dict, Any, List

class DataFactory:
    """工业级测试数据工厂，统一生成业务对象。"""
    
    @staticmethod
    def create_word_record(voc_id: str = None, spelling: str = "apple") -> Dict[str, Any]:
        """创建一个典型的墨墨单词记录字典。"""
        uid = voc_id or f"v-{uuid.uuid4().hex[:8]}"
        return {
            "voc_id": uid,
            "voc_spelling": spelling,
            "short_term_familiarity": 1.5,
            "review_count": 5,
            "meanings": "n. 苹果"
        }

    @staticmethod
    def create_ai_response(spelling: str = "apple", score: int = 9) -> Dict[str, Any]:
        """创建模拟的 AI 响应结果。"""
        return {
            "score": score,
            "justification": "Test score",
            "refined_content": f"Memory aid for {spelling}",
            "tags": ["mnemonic", "test"]
        }

    @staticmethod
    def create_batch_results(words: List[str]) -> List[Dict[str, Any]]:
        """批量生成单词结果。"""
        return [DataFactory.create_word_record(spelling=w) for w in words]
