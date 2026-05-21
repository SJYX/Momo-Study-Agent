"""
core/weak_word_filter.py: 易错词筛选与多维度弱词评估。
"""
# -*- coding: utf-8 -*-
"""
薄弱词筛选优化系统

提供多维度的薄弱词评分和筛选策略
"""

import json
import time
from datetime import datetime
from typing import List, Dict, Tuple
import config as _config
from database.connection import _get_read_conn
from database.word_repo import query_weak_words


class WeakWordFilter:
    def __init__(self, logger=None):
        if logger:
            self.logger = logger
        else:
            from core.logger import get_logger
            self.logger = get_logger()
        
        # 缓存用户统计信息，TTL 为 60 秒
        self._user_stats_cache: Dict = None
        self._user_stats_cache_ttl: float = 0.0  # 缓存过期时间戳

    @staticmethod
    def _as_number(value, default=0.0):
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def calculate_weak_score(self, word: Dict) -> float:
        """计算单词的薄弱分数（0-100，越高越薄弱）

        评分维度：
        1. 熟悉度 (0-40分)：熟悉度越低，分数越高
        2. 学习次数 (0-20分)：学习次数越少，分数越高
        3. 错误率 (0-20分)：错误率越高，分数越高
        4. 时间因素 (0-10分)：上次学习越久，分数越高
        5. 迭代级别 (0-10分)：迭代级别越高，分数越高
        """
        score = 0

        # 1. 熟悉度权重 (0-40分)
        familiarity = self._as_number(word.get('familiarity_short'), 0.0)
        if familiarity < 3.0:
            score += (3.0 - familiarity) * 13.33  # 3.0以下每0.1增加1.33分

        # 2. 复习次数权重 (0-20分)
        review_count = int(self._as_number(word.get('review_count'), 0))
        if review_count < 5:
            score += 20
        elif review_count < 10:
            score += 15
        elif review_count < 20:
            score += 10
        elif review_count < 30:
            score += 5

        # 3. 时间权重 (0-10分) - 使用 created_at 字段
        created_at = word.get('created_at', '')
        if created_at:
            try:
                # 处理不同的日期格式
                if created_at.endswith('Z'):
                    created_at = created_at.replace('Z', '+00:00')
                created_date = datetime.fromisoformat(created_at)
                days_since = (datetime.now() - created_date).days

                if days_since > 30:
                    score += 10
                elif days_since > 14:
                    score += 7
                elif days_since > 7:
                    score += 4
            except Exception as e:
                self.logger.warning(f"解析日期失败: {created_at}, 错误: {e}")

        # 4. 迭代级别权重 (0-10分)
        it_level = int(self._as_number(word.get('it_level'), 0))
        score += min(it_level * 2, 10)  # 迭代级别越高，分数越高

        return min(score, 100)

    def get_dynamic_threshold(self, user_stats: Dict = None) -> float:
        """根据用户学习情况动态调整阈值

        Args:
            user_stats: 用户统计信息
                - avg_familiarity: 平均熟悉度
                - study_frequency: 学习频率 ('high', 'normal', 'low')
                - total_words: 总单词数
        """
        if user_stats is None:
            user_stats = self._get_user_stats()

        avg_familiarity = user_stats.get('avg_familiarity', 2.5)
        study_frequency = user_stats.get('study_frequency', 'normal')

        base_threshold = 3.0

        if study_frequency == 'high':
            # 高频学习用户：阈值更高，筛选更严格
            return base_threshold + 0.5
        elif study_frequency == 'low':
            # 低频学习用户：阈值更低，筛选更宽松
            return base_threshold - 0.5
        else:
            # 根据平均熟悉度微调
            if avg_familiarity < 2.0:
                return base_threshold - 0.3
            elif avg_familiarity > 3.5:
                return base_threshold + 0.3
            else:
                return base_threshold

    def _get_user_stats(self) -> Dict:
        """获取用户统计信息，60秒内使用缓存避免重复查询"""
        current_time = time.time()
        
        # 检查缓存是否有效（未过期）
        if self._user_stats_cache is not None and current_time < self._user_stats_cache_ttl:
            return self._user_stats_cache
        
        # 缓存已过期或不存在，执行查询
        from database.backends import get_active_backend
        conn = _get_read_conn(_config.DB_PATH)
        with get_active_backend().op_lock_for(conn):
            cur = conn.cursor()
            try:
                # 获取平均熟悉度
                cur.execute("""
                    SELECT AVG(familiarity_short) as avg_fam
                    FROM (
                        SELECT familiarity_short
                        FROM word_progress_history
                        GROUP BY voc_id
                        HAVING MAX(created_at)
                    )
                """)
                avg_fam = cur.fetchone()[0] or 2.5

                # 获取平均复习次数
                cur.execute("SELECT AVG(review_count) FROM (SELECT review_count FROM word_progress_history GROUP BY voc_id HAVING MAX(created_at))")
                avg_reviews = cur.fetchone()[0] or 0

                # 获取总单词数
                cur.execute("SELECT COUNT(DISTINCT voc_id) FROM word_progress_history")
                total_words = cur.fetchone()[0] or 0
            finally:
                cur.close()
        if get_active_backend().should_close(conn):
            conn.close()

        # 估算学习频率 (简易实现)
        study_frequency = "normal"
        if avg_reviews > 20:
            study_frequency = "high"
        elif avg_reviews < 5:
            study_frequency = "low"

        result = {
            'avg_familiarity': avg_fam,
            'total_words': total_words,
            'study_frequency': study_frequency,
            'avg_review_count': avg_reviews
        }
        
        # 缓存结果，设置 60 秒的 TTL
        self._user_stats_cache = result
        self._user_stats_cache_ttl = current_time + 60.0
        
        return result

    def get_weak_words_by_score(self, min_score: float = 50.0, limit: int = 100) -> List[Dict]:
        """根据薄弱分数获取单词列表

        Args:
            min_score: 最低薄弱分数
            limit: 最大返回数量
        """
        user_stats = self._get_user_stats()
        avg_reviews = user_stats.get('avg_review_count', 0)
        min_review_threshold = 1 if avg_reviews < 5 else 3

        scored_words = []
        rows = query_weak_words(min_score=0.0, limit=5000, db_path=_config.DB_PATH)
        for word in rows:
            if 'created_at' not in word and word.get('updated_at'):
                word = dict(word)
                word['created_at'] = word.get('updated_at')
            if int(self._as_number(word.get('review_count'), 0)) < min_review_threshold:
                continue
            score = self.calculate_weak_score(word)
            if score >= min_score:
                word['weak_score'] = score
                scored_words.append(word)

        # 按分数排序并限制数量
        scored_words.sort(key=lambda x: x['weak_score'], reverse=True)
        return scored_words[:limit]

    def get_weak_words_by_category(self, threshold: float = 3.0) -> Dict[str, List[Dict]]:
        """按类别获取薄弱单词

        Returns:
            {
                'urgent': List[Dict],  # 紧急薄弱词
                'normal': List[Dict],  # 一般薄弱词
                'potential': List[Dict]  # 潜在薄弱词
            }
        """
        rows = query_weak_words(min_score=0.0, limit=5000, db_path=_config.DB_PATH)

        urgent_words = []
        normal_words = []
        potential_words = []

        user_stats = self._get_user_stats()
        avg_reviews = user_stats.get('avg_review_count', 0)
        min_review_threshold = 1 if avg_reviews < 5 else 3

        for word in rows:
            if 'created_at' not in word and word.get('updated_at'):
                word = dict(word)
                word['created_at'] = word.get('updated_at')
            familiarity = self._as_number(word.get('familiarity_short'), 0.0)
            review_count = int(self._as_number(word.get('review_count'), 0))

            # 复习次数门槛
            if review_count < min_review_threshold:
                continue

            # 紧急薄弱词：熟悉度极低
            if familiarity < threshold * 0.7:
                urgent_words.append(word)
            # 一般薄弱词：熟悉度低于阈值
            elif familiarity < threshold:
                normal_words.append(word)
            # 潜在薄弱词：复习次数少但熟悉度不高
            elif review_count < 10 and familiarity < threshold * 1.2:
                potential_words.append(word)

        return {
            'urgent': urgent_words,
            'normal': normal_words,
            'potential': potential_words
        }

    def _deduplicate_words(self, words: List[Dict]) -> List[Dict]:
        """去重处理"""
        unique_words = {}
        for word in words:
            voc_id = word['voc_id']
            if voc_id not in unique_words:
                unique_words[voc_id] = word
        return list(unique_words.values())


# 使用示例
if __name__ == "__main__":
    filter = WeakWordFilter()

    # 1. 获取用户统计信息
    user_stats = filter._get_user_stats()
    print(f"用户统计: {user_stats}")

    # 2. 获取动态阈值
    threshold = filter.get_dynamic_threshold(user_stats)
    print(f"动态阈值: {threshold}")

    # 3. 按分数获取薄弱词
    weak_words = filter.get_weak_words_by_score(min_score=50.0, limit=10)
    print(f"薄弱词数量: {len(weak_words)}")

    # 4. 按类别获取薄弱词
    categorized = filter.get_weak_words_by_category(threshold)
    print(f"紧急薄弱词: {len(categorized['urgent'])}")
    print(f"一般薄弱词: {len(categorized['normal'])}")
    print(f"潜在薄弱词: {len(categorized['potential'])}")
