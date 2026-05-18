"""
测试 sync_manager 中的队列 task_done() 计数修复与防饥饿策略

验证：
1. 找到高优先级任务时，计数准确平衡。
2. 找不到高优先级任务时，当前任务 p0 不会被重复入队。
3. 确保没有任何场景发生 queue.join() 死锁。
"""

import unittest
from unittest.mock import MagicMock
import queue
from core.sync_manager import SyncManager
from core.sync_priority import Priority

class TestQueueTaskDoneLogic(unittest.TestCase):
    """验证队列计数逻辑修复与死锁消除"""

    def setUp(self):
        # 初始化带 mock 的 SyncManager
        self.logger = MagicMock()
        self.momo_api = MagicMock()
        self.on_mark_processed = MagicMock()
        self.sm = SyncManager(self.logger, self.momo_api, self.on_mark_processed)
        # 强制设置连续 P1 计数以触发防饥饿
        self.sm._consecutive_p1_count = 5

    def tearDown(self):
        self.sm.shutdown()

    def test_starvation_policy_finds_high_priority(self):
        """
        验证：触发防饥饿且找到了高优先级任务。
        预期：
        - p0 (P1) 及其他取出的候选 P1 都被正确放回队列，不会造成计数泄漏。
        - 返回选中的高优先级任务。
        """
        # p0 是第一个取出来的任务，触发检查
        p0 = (int(Priority.P1), 1, {"spell": "apple"})
        
        # 队列中剩下的任务：几个 P1 和一个 P2
        self.sm.sync_queue.put((int(Priority.P1), 2, {"spell": "banana"}))
        self.sm.sync_queue.put((int(Priority.P1), 3, {"spell": "cat"}))
        self.sm.sync_queue.put((int(Priority.P2), 4, {"spell": "dog"}))
        
        initial_unfinished = self.sm.sync_queue.unfinished_tasks
        
        # 执行调度
        chosen = self.sm._apply_starvation_policy(p0)
        
        # 结果断言
        self.assertEqual(chosen[2]["spell"], "dog", "应该返回更高优先级的 dog")
        self.assertEqual(self.sm._consecutive_p1_count, 0, "计数器应该被重置")
        
        # 最核心验证： unfinished_tasks 的数量应该保持绝对平衡。
        # 原来有 3 个任务 (put了3次，没经过 get+task_done消费)，此时 unfinished 应该是 3。
        # 加上一开始的 p0 其实已经被 get 出来了，所以 p0 本身不包含在 initial 里面。
        # 在 apply 之后，p0 被 put 回去了，banana 和 cat 被取出来又 put 回去了，dog 被取出去了（将交给外层）。
        # 队列中此时剩下的是：apple, banana, cat (3 个任务)。
        # 而 unfinished_tasks 必须依然是最初的 initial_unfinished。
        self.assertEqual(self.sm.sync_queue.unfinished_tasks, initial_unfinished)
        
        # 注释掉外层消费模拟，因为 p0 没有 put 进去
        # self.sm.sync_queue.task_done()
        
        # 验证队列里残留的任务确实能被全部正常消费
        while not self.sm.sync_queue.empty():
            _ = self.sm.sync_queue.get_nowait()
            self.sm.sync_queue.task_done()
            
        self.assertEqual(self.sm.sync_queue.unfinished_tasks, 0, "队列全部消费后必须毫无泄漏")

    def test_starvation_policy_no_high_priority(self):
        """
        验证：触发防饥饿但队列里全都是 P1 任务。
        预期：
        - p0 被直接返回继续执行。
        - p0 绝对没有被放回队列中产生重复执行 Bug。
        - 其他取出的 P1 被正确放回，计数精准。
        """
        p0 = (int(Priority.P1), 1, {"spell": "apple"})
        
        # 队列中剩下的全都是 P1
        self.sm.sync_queue.put((int(Priority.P1), 2, {"spell": "banana"}))
        self.sm.sync_queue.put((int(Priority.P1), 3, {"spell": "cat"}))
        
        initial_unfinished = self.sm.sync_queue.unfinished_tasks
        
        # 执行调度
        chosen = self.sm._apply_starvation_policy(p0)
        
        # 结果断言
        self.assertEqual(chosen[2]["spell"], "apple", "没有高优先级时应该原样返回 p0")
        self.assertEqual(self.sm._consecutive_p1_count, 6, "防饥饿计数应累加")
        
        # 最核心验证： p0 绝对不能存在于队列里。
        # apple 已经被选出，队列里应该只剩下 banana 和 cat。
        # 因此此时unfinished_tasks 应等于 2（刚进去的banana和cat，它们是被取出后又放回并 task_done 平衡过的）。
        # 因为我们自己模拟的 p0 没有经过队列所以它不算在 initial_unfinished。
        self.assertEqual(self.sm.sync_queue.unfinished_tasks, initial_unfinished)
        
        # 取出队列剩下的检查，确保没有 apple
        leftovers = []
        while not self.sm.sync_queue.empty():
            leftovers.append(self.sm.sync_queue.get_nowait()[2]["spell"])
            self.sm.sync_queue.task_done()
            
        self.assertNotIn("apple", leftovers, "致命 Bug：p0 被错误地放回了队列导致重复执行")
        self.assertEqual(leftovers, ["banana", "cat"])
        
        # 注释掉外层消费模拟，因为 p0 没有 put 进去
        # self.sm.sync_queue.task_done()

if __name__ == "__main__":
    unittest.main()
