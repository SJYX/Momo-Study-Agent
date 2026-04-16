# -*- coding: utf-8 -*-
"""Prompt 迭代优化开发工具 (CLI + 菜单集成入口)

用法 (CLI):
    python scripts/prompt_dev_tool.py init
    python scripts/prompt_dev_tool.py evaluate
    python scripts/prompt_dev_tool.py optimize [--freeze-threshold 9.0]
    python scripts/prompt_dev_tool.py loop --rounds N
    python scripts/prompt_dev_tool.py history
    python scripts/prompt_dev_tool.py accept
    python scripts/prompt_dev_tool.py rollback <version_hash>

也可以通过 main.py 菜单选项 5 进入交互式操作。
"""
import sys
import os
import json
import time
import re
import shutil
import argparse
import hashlib

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    PROMPT_FILE, PROMPT_DEV_FILE, PROMPT_DEV_DIR,
    AUDITOR_PROMPT_FILE, OPTIMIZER_PROMPT_FILE,
    BENCHMARK_DIR, PROMPT_ITERATION_DB, PROMPT_HISTORY_DIR,
    AI_PROVIDER, GEMINI_API_KEY, MIMO_API_KEY,
)
from core.prompt_iteration_db import (
    init_iteration_db, compute_version_hash, save_prompt_version,
    save_evaluation_round, save_module_scores, save_optimization_action,
    get_latest_round_number, get_module_score_trends, get_all_rounds_summary,
    get_prompt_version_content, save_generation_cache, get_generation_cache,
)

# ── 模块注册表 ──
MODULE_REGISTRY = [
    {"id": "meanings",       "field": "basic_meanings",    "weight": 0.15},
    {"id": "ielts_depth",    "field": "ielts_focus",       "weight": 0.15},
    {"id": "collocations",   "field": "collocations",      "weight": 0.10},
    {"id": "traps",          "field": "traps",             "weight": 0.10},
    {"id": "synonyms",       "field": "synonyms",          "weight": 0.10},
    {"id": "discrimination", "field": "discrimination",    "weight": 0.05},
    {"id": "sentences",      "field": "example_sentences", "weight": 0.15},
    {"id": "memory",         "field": "memory_aid",        "weight": 0.10},
    {"id": "ratings",        "field": "word_ratings",      "weight": 0.05},
    {"id": "format",         "field": "format",            "weight": 0.05},
]
MODULE_FIELDS = [m["field"] for m in MODULE_REGISTRY]

DEFAULT_FREEZE_THRESHOLD = 9.0


# ══════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════

def _load_benchmark_words() -> list:
    """加载 Benchmark 测试词列表。"""
    path = os.path.join(BENCHMARK_DIR, "custom_test_set.json")
    if not os.path.exists(path):
        print(f"❌ 测试词文件不存在: {path}")
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    words = data.get("words", [])
    if len(words) < 10:
        print(f"⚠️  测试词数量偏少 ({len(words)} 个)，建议至少 10 个以获得可靠评估。")
    return words


def _load_dev_prompt() -> str:
    """加载开发版 Prompt。"""
    if not os.path.exists(PROMPT_DEV_FILE):
        print(f"❌ 开发版 Prompt 不存在: {PROMPT_DEV_FILE}")
        print("   请先运行 'init' 命令将生产 Prompt 拷贝到开发目录。")
        return ""
    with open(PROMPT_DEV_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()


def _save_dev_prompt(content: str):
    """保存开发版 Prompt。"""
    os.makedirs(os.path.dirname(PROMPT_DEV_FILE), exist_ok=True)
    with open(PROMPT_DEV_FILE, "w", encoding="utf-8") as f:
        f.write(content)


def _get_ai_client(use_auditor_model: bool = False):
    """获取 AI 客户端实例。

    Args:
        use_auditor_model: True 时尝试使用审计专用的强模型。
    """
    auditor_key = os.getenv("AUDITOR_API_KEY", "").strip()
    auditor_model = os.getenv("AUDITOR_MODEL", "").strip()

    if use_auditor_model and auditor_key and auditor_model:
        # 使用审计专用强模型
        from core.gemini_client import GeminiClient
        return GeminiClient(auditor_key, model_name=auditor_model), auditor_model
    elif AI_PROVIDER == "mimo":
        from core.mimo_client import MimoClient
        from config import MIMO_MODEL
        return MimoClient(MIMO_API_KEY), MIMO_MODEL
    else:
        from core.gemini_client import GeminiClient
        from config import GEMINI_MODEL
        return GeminiClient(GEMINI_API_KEY), GEMINI_MODEL


def _compute_module_status(round_scores: dict, freeze_threshold: float) -> dict:
    """计算每个模块的平均分和冻结状态。

    Args:
        round_scores: {"basic_meanings": [9, 8, 9], "memory_aid": [5, 6, 4], ...}
        freeze_threshold: 冻结阈值

    Returns:
        {"basic_meanings": {"avg": 8.67, "status": "frozen"}, ...}
    """
    status = {}
    for module_name, scores in round_scores.items():
        if not scores:
            continue
        avg = sum(scores) / len(scores)
        status[module_name] = {
            "avg": round(avg, 2),
            "status": "frozen" if avg >= freeze_threshold else "needs_improvement"
        }
    return status


def _print_module_radar(module_status: dict):
    """在终端打印模块评分雷达图（文本版）。"""
    print("\n" + "═" * 50)
    print("📊 模块评分雷达图")
    print("═" * 50)

    for field in MODULE_FIELDS:
        info = module_status.get(field, {"avg": 0, "status": "unknown"})
        avg = info["avg"]
        status = info["status"]

        # 生成条形图
        bar_len = int(avg * 3)
        bar = "█" * bar_len + "░" * (30 - bar_len)

        # 状态标记
        if status == "frozen":
            marker = "🔒"
        elif avg >= 8:
            marker = "✅"
        elif avg >= 6:
            marker = "⚠️ "
        else:
            marker = "❌"

        name_padded = f"{field:22s}"
        print(f"  {marker} {name_padded} [{bar}] {avg:.1f}/10")

    # 计算加权平均
    total_weight = 0
    weighted_sum = 0
    for m in MODULE_REGISTRY:
        info = module_status.get(m["field"], {})
        if "avg" in info:
            weighted_sum += info["avg"] * m["weight"]
            total_weight += m["weight"]

    if total_weight > 0:
        weighted_avg = weighted_sum / total_weight
        print(f"\n  📈 加权平均分: {weighted_avg:.2f}/10")
    print("═" * 50)


# ══════════════════════════════════════════════════
# 核心命令
# ══════════════════════════════════════════════════

def cmd_init():
    """将生产 Prompt 拷贝到开发目录。"""
    init_iteration_db()

    if not os.path.exists(PROMPT_FILE):
        print(f"❌ 生产 Prompt 不存在: {PROMPT_FILE}")
        return False

    shutil.copy2(PROMPT_FILE, PROMPT_DEV_FILE)
    print(f"✅ 已将生产 Prompt 拷贝到开发目录:")
    print(f"   {PROMPT_FILE} → {PROMPT_DEV_FILE}")

    # 保存初始版本到数据库
    with open(PROMPT_DEV_FILE, "r", encoding="utf-8") as f:
        content = f.read().strip()
    version_hash = save_prompt_version(content, source="init")
    print(f"   版本哈希: {version_hash}")
    print(f"   数据库已初始化: {PROMPT_ITERATION_DB}")
    return True


def cmd_evaluate(freeze_threshold: float = DEFAULT_FREEZE_THRESHOLD) -> dict:
    """运行 Benchmark 评估。返回模块状态字典。"""
    init_iteration_db()
    words = _load_benchmark_words()
    if not words:
        return {}

    dev_prompt = _load_dev_prompt()
    if not dev_prompt:
        return {}

    version_hash = compute_version_hash(dev_prompt)
    save_prompt_version(dev_prompt, source="manual")

    # Step 1: 用当前 dev prompt 生成测试输出
    version_hash = compute_version_hash(dev_prompt)
    
    all_outputs = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    
    # 尝试加载缓存
    cached_data = get_generation_cache(version_hash)
    if cached_data and cached_data.get("test_words") == words:
        batch_size = cached_data.get("batch_size", 5)
        print(f"\n♻️  发现当前版本 ({version_hash}) 已存在生成缓存 (Batch: {batch_size})，跳过生成环节...")
        all_outputs = cached_data["outputs"]
    else:
        print(f"\n🔄 正在使用 dev prompt 生成 {len(words)} 个测试词的输出...")
        gen_client, gen_model = _get_ai_client(use_auditor_model=False)

        # 分批生成（复用 generate_mnemonics 接口）
        gen_client_with_dev = gen_client.__class__.__new__(gen_client.__class__)
        gen_client_with_dev.__dict__.update(gen_client.__dict__)
        gen_client_with_dev.prompt_file = PROMPT_DEV_FILE

        batch_size = 5
        for i in range(0, len(words), batch_size):
            batch = words[i:i + batch_size]
            print(f"  生成中... [{i + 1}-{min(i + batch_size, len(words))}/{len(words)}]")
            results, metadata = gen_client_with_dev.generate_mnemonics(batch)
            all_outputs.extend(results)
            total_prompt_tokens += metadata.get("prompt_tokens", 0)
            total_completion_tokens += metadata.get("completion_tokens", 0)

        if not all_outputs:
            print("❌ 未生成任何有效输出，评估终止。")
            return {}
            
        # 保存到缓存
        save_generation_cache(version_hash, words, all_outputs, gen_model, batch_size)
        print(f"✅ 已生成 {len(all_outputs)} 个词的分析结果并存入缓存 (Batch: {batch_size})")
    
    if not all_outputs:
        return {}

    # Step 2: 用审计器评分
    from core.logger import get_logger, log_performance
    logger = get_logger()
    
    auditor_client, auditor_model = _get_ai_client(use_auditor_model=True)
    print(f"\n🔍 正在分批审计评分 (模型: {auditor_model})...")

    with open(AUDITOR_PROMPT_FILE, "r", encoding="utf-8") as f:
        auditor_instruction = f.read().strip()

    scores_list = []
    total_audit_prompt_tokens = 0
    total_audit_completion_tokens = 0
    
    # 采用分批审计策略 (每批 5 个词)，防止超长文本导致模型超时
    audit_batch_size = 5
    for i in range(0, len(all_outputs), audit_batch_size):
        batch_outputs = all_outputs[i:i + audit_batch_size]
        # 优先尝试从提示词定义的 spelling 字段或通用字段提取显示
        batch_words = [o.get("spelling") or o.get("word") or o.get("word_en") or "unknown" for o in batch_outputs]
        print(f"  审计中... [{i + 1}-{min(i + audit_batch_size, len(all_outputs))}/{len(all_outputs)}] {', '.join(batch_words)}")
        
        outputs_json = json.dumps(batch_outputs, ensure_ascii=False, indent=2)
        audit_prompt = f"请评估以下 {len(batch_outputs)} 个 AI 生成的词汇分析结果：\n\n{outputs_json}"
        
        start_time = time.time()
        try:
            raw_response, audit_metadata = auditor_client.generate_with_instruction(
                audit_prompt, instruction=auditor_instruction
            )
            duration = time.time() - start_time
            
            if not raw_response:
                error_info = audit_metadata.get("error") or audit_metadata.get("finish_reason") or "空响应"
                print(f"  ⚠️  本批次审计失败: {error_info}")
                continue

            # 解析本批次结果
            text = raw_response.strip()
            if text.startswith("```json"): text = text[7:]
            elif text.startswith("```"): text = text[3:]
            if text.endswith("```"): text = text[:-3]
            
            try:
                import json_repair
                batch_scores = json_repair.loads(text.strip())
            except:
                batch_scores = json.loads(text.strip())
            
            if isinstance(batch_scores, list):
                scores_list.extend(batch_scores)
            
            # 统计审计 tokens
            total_audit_prompt_tokens += audit_metadata.get("prompt_tokens", 0)
            total_audit_completion_tokens += audit_metadata.get("completion_tokens", 0)

            logger.info(
                "收单分批审计响应",
                module="prompt_dev_tool",
                function="cmd_evaluate",
                duration=duration,
                batch_size=len(batch_outputs)
            )
        except Exception as e:
            print(f"  ❌ 本批次审计异常: {e}")
            continue

    if not scores_list:
        print("❌ 审计器未返回任何有效结果，无法计算分数。")
        return {}

    # Step 3: 汇总分数并保存到数据库
    round_scores = {}  # {"basic_meanings": [9, 8, ...], ...}
    for s in scores_list:
        field = s.get("field", "")
        if field not in round_scores:
            round_scores[field] = []
        round_scores[field].append(s.get("score", 0))

    # 计算加权平均
    total_weight = 0
    weighted_sum = 0
    for m in MODULE_REGISTRY:
        scores = round_scores.get(m["field"], [])
        if scores:
            avg = sum(scores) / len(scores)
            weighted_sum += avg * m["weight"]
            total_weight += m["weight"]
    avg_score = weighted_sum / total_weight if total_weight > 0 else 0

    # 保存到数据库
    # 汇总总 Token (生成 + 审计)
    final_prompt_tokens = total_prompt_tokens + total_audit_prompt_tokens
    final_completion_tokens = total_completion_tokens + total_audit_completion_tokens

    round_id = save_evaluation_round(
        version_hash=version_hash,
        ai_provider=AI_PROVIDER,
        model_name=auditor_model,
        test_words=words,
        avg_score=round(avg_score, 2),
        prompt_tokens=final_prompt_tokens,
        completion_tokens=final_completion_tokens,
        gen_batch_size=batch_size,
        audit_batch_size=audit_batch_size
    )
    save_module_scores(round_id, scores_list)

    print(f"\n✅ 评估完成 (Round #{round_id}, 版本 {version_hash})")
    print(f"   审计模型: {auditor_model}")
    print(f"   测试词数: {len(words)}")
    print(f"   Token 消耗: prompt={final_prompt_tokens}, completion={final_completion_tokens}")

    # 打印雷达图
    module_status = _compute_module_status(round_scores, freeze_threshold)
    _print_module_radar(module_status)

    # 显示低分模块的详细反馈
    low_score_items = [s for s in scores_list if s.get("score", 10) < freeze_threshold]
    if low_score_items:
        print(f"\n⚠️  低分模块详情 (< {freeze_threshold}):")
        for item in sorted(low_score_items, key=lambda x: x.get("score", 0)):
            print(f"  [{item.get('field')}] {item.get('word')}: "
                  f"{item.get('score')}/10 — {item.get('feedback', '')}")
            if item.get("fix"):
                print(f"    💡 建议: {item.get('fix')}")
    else:
        print(f"\n🎉 所有模块均达到 {freeze_threshold} 分以上！可以执行 accept 上线。")

    return {
        "round_id": round_id,
        "module_status": module_status,
        "scores_list": scores_list,
        "avg_score": avg_score,
        "version_hash": version_hash,
    }


def cmd_optimize(freeze_threshold: float = DEFAULT_FREEZE_THRESHOLD, force_re_eval: bool = False) -> bool:
    """自动优化低分模块（冻结高分模块）。"""
    init_iteration_db()
    dev_prompt = _load_dev_prompt()
    if not dev_prompt: return False
    version_hash = compute_version_hash(dev_prompt)

    eval_result = None

    # 优先尝试复用数据库中当前版本的最新评估结果
    if not force_re_eval:
        from core.prompt_iteration_db import _get_iteration_conn
        conn = _get_iteration_conn()
        cur = conn.cursor()
        cur.execute('''
            SELECT id, version_hash, avg_score FROM evaluation_rounds 
            WHERE version_hash = ? ORDER BY round_number DESC LIMIT 1
        ''', (version_hash,))
        row = cur.fetchone()
        conn.close()

        if row:
            round_id = row[0]
            print(f"\n♻️  发现当前版本 ({version_hash}) 已有评估记录 (Round #{round_id})，正在复用...")
            
            # 重新加载模块状态
            module_scores_data = [] # 模拟 scores_list
            conn = _get_iteration_conn()
            cur = conn.cursor()
            cur.execute("SELECT module_name, score, feedback, fix_suggestion, test_word FROM module_scores WHERE round_id = ?", (round_id,))
            round_scores = {}
            for r in cur.fetchall():
                field, score, feedback, fix, word = r
                if field not in round_scores: round_scores[field] = []
                round_scores[field].append(score)
                module_scores_data.append({"field": field, "score": score, "feedback": feedback, "fix": fix, "word": word})
            conn.close()
            
            eval_result = {
                "round_id": round_id,
                "module_status": _compute_module_status(round_scores, freeze_threshold),
                "scores_list": module_scores_data,
                "version_hash": version_hash
            }

    # 如果没有可复用的结果或强制重测，则运行评估
    if not eval_result:
        print("\n🔍 未找到近期评估记录或强制要求重测，正在启动全流程评估...")
        eval_result = cmd_evaluate(freeze_threshold)
        if not eval_result:
            print("❌ 评估失败，无法继续优化。")
            return False

    module_status = eval_result["module_status"]
    scores_list = eval_result["scores_list"]
    round_id = eval_result["round_id"]

    # 判断哪些模块需要优化
    frozen_modules = [f for f, info in module_status.items() if info["status"] == "frozen"]
    target_modules = [f for f, info in module_status.items() if info["status"] == "needs_improvement"]

    if not target_modules:
        print(f"\n🎉 检查完成：所有模块评分均已达到阈值 {freeze_threshold}，无需优化！")
        return True

    print(f"\n🔒 冻结模块 ({len(frozen_modules)}): {', '.join(frozen_modules) or '无'}")
    print(f"🔧 待优化模块 ({len(target_modules)}): {', '.join(target_modules)}")

    print(f"\n🔒 冻结模块 ({len(frozen_modules)}): {', '.join(frozen_modules) or '无'}")
    print(f"🔧 待优化模块 ({len(target_modules)}): {', '.join(target_modules)}")

    # 构建低分反馈
    low_score_feedback = []
    for s in scores_list:
        if s.get("field") in target_modules and s.get("score", 10) < freeze_threshold:
            low_score_feedback.append(
                f"- [{s.get('field')}] {s.get('word')}: {s.get('score')}/10 | "
                f"问题: {s.get('feedback', '')} | 建议: {s.get('fix', '')}"
            )

    # 加载优化器提示词和当前 dev prompt
    dev_prompt = _load_dev_prompt()
    if not dev_prompt:
        return False

    with open(OPTIMIZER_PROMPT_FILE, "r", encoding="utf-8") as f:
        optimizer_instruction = f.read().strip()

    # 构建优化请求
    optimize_prompt = f"""以下是当前的 System Prompt：

{dev_prompt}

---

本轮审计发现以下模块需要改进：
{chr(10).join(low_score_feedback)}

以下模块已达标，**严禁修改**对应的 Prompt Section：
{', '.join(frozen_modules) if frozen_modules else '无（所有模块均需改进）'}

请仅修改需要改进的模块对应的 Prompt Section，保持其余部分完全不变。
输出完整的修改后 Prompt 文本。"""

    print(f"\n🔄 正在调用优化器...")
    opt_client, opt_model = _get_ai_client(use_auditor_model=False)
    raw_response, _ = opt_client.generate_with_instruction(
        optimize_prompt, instruction=optimizer_instruction
    )

    if not raw_response:
        print("❌ 优化器未返回有效结果。")
        return False

    # 解析优化结果（分离 prompt 和 reasoning）
    new_prompt = raw_response.strip()
    optimizer_reasoning = ""
    if "---REASONING---" in new_prompt:
        parts = new_prompt.split("---REASONING---", 1)
        new_prompt = parts[0].strip()
        optimizer_reasoning = parts[1].strip()

    # 保存新版本
    new_hash = save_prompt_version(new_prompt, parent_hash=version_hash, source="optimizer")
    _save_dev_prompt(new_prompt)

    # 保存优化决策
    save_optimization_action(
        round_id=round_id,
        target_modules=target_modules,
        frozen_modules=frozen_modules,
        input_version_hash=version_hash,
        output_version_hash=new_hash,
        optimizer_reasoning=optimizer_reasoning,
    )

    print(f"\n" + "✨" + "─" * 48)
    print(f"✅ 优化完成！")
    print(f"   旧版本 ID: {version_hash}")
    print(f"   新版本 ID: {new_hash}")
    print(f"   优化模块:  {', '.join(target_modules)}")
    print(f"   冻结模块:  {', '.join(frozen_modules)}")
    print("─" * 50)

    if optimizer_reasoning:
        print(f"\n📝 优化决策背后的思考:")
        try:
            import json_repair
            reasoning_data = json_repair.loads(optimizer_reasoning)
        except:
            try:
                reasoning_data = json.loads(optimizer_reasoning)
            except:
                reasoning_data = None

        if isinstance(reasoning_data, dict) and "changes" in reasoning_data:
            for idx, change in enumerate(reasoning_data["changes"], 1):
                section = change.get("section", "未知")
                what = change.get("what_changed", "未说明")
                why = change.get("why", "未说明")
                print(f"  {idx}. 【{section}】")
                print(f"     🔧 改动: {what}")
                print(f"     🎯 原因: {why}")
            
            preserved = reasoning_data.get("sections_preserved", [])
            if preserved:
                print(f"\n  🛡️  已完整保留的原生模块: {', '.join(preserved)}")
        else:
            # 备选方案：由于 JSON 解析失败，尝试格式化原始文本
            print(f"   {optimizer_reasoning}")
    
    print("─" * 50 + "\n")

    return True


def cmd_loop(rounds: int = 5, freeze_threshold: float = DEFAULT_FREEZE_THRESHOLD):
    """全自动迭代循环（含收敛检测）。"""
    print(f"\n🔄 开始自动迭代循环 (最多 {rounds} 轮, 冻结阈值 {freeze_threshold})")
    print("=" * 50)

    prev_avg = None
    convergence_count = 0
    CONVERGENCE_THRESHOLD = 0.3
    MAX_CONVERGENCE_ROUNDS = 2

    for i in range(1, rounds + 1):
        print(f"\n{'─' * 50}")
        print(f"🔁 第 {i}/{rounds} 轮")
        print(f"{'─' * 50}")

        eval_result = cmd_evaluate(freeze_threshold)
        if not eval_result:
            print("❌ 评估失败，终止循环。")
            break

        current_avg = eval_result["avg_score"]
        module_status = eval_result["module_status"]

        # 收敛检测
        if prev_avg is not None:
            delta = abs(current_avg - prev_avg)
            if delta < CONVERGENCE_THRESHOLD:
                convergence_count += 1
                print(f"   📉 分数变化: {delta:.2f} (< {CONVERGENCE_THRESHOLD}), "
                      f"收敛计数: {convergence_count}/{MAX_CONVERGENCE_ROUNDS}")
            else:
                convergence_count = 0

            if convergence_count >= MAX_CONVERGENCE_ROUNDS:
                print(f"\n🏁 连续 {MAX_CONVERGENCE_ROUNDS} 轮分数变化 < {CONVERGENCE_THRESHOLD}，"
                      f"已达收敛，自动停止。")
                break

        # 检查是否所有模块都达标
        all_frozen = all(
            info.get("status") == "frozen"
            for info in module_status.values()
        )
        if all_frozen:
            print(f"\n🎉 所有模块均达到 {freeze_threshold} 分以上！自动停止。")
            break

        # 执行优化
        target_modules = [
            f for f, info in module_status.items()
            if info.get("status") == "needs_improvement"
        ]
        if not target_modules:
            print("\n🎉 无需优化的模块，停止循环。")
            break

        cmd_optimize(freeze_threshold)
        prev_avg = current_avg

    print(f"\n{'═' * 50}")
    print(f"🏁 迭代循环结束，共执行 {min(i, rounds)} 轮")
    print(f"{'═' * 50}")


def cmd_history():
    """查看迭代历史趋势。"""
    init_iteration_db()
    rounds = get_all_rounds_summary()
    if not rounds:
        print("📭 暂无评估历史记录。")
        return

    print("\n" + "═" * 60)
    print("📊 评估历史")
    print("═" * 60)
    print(f"  {'轮次':>4s}  {'版本':>12s}  {'平均分':>6s}  {'模型':>16s}  {'时间'}")
    print("  " + "─" * 55)

    for r in rounds:
        print(f"  #{r['round']:>3d}  {r['version_hash']:>12s}  "
              f"{r['avg_score']:>5.2f}  {(r['model_name'] or 'N/A'):>16s}  "
              f"{(r['created_at'] or '')[:19]}")

    # 显示模块趋势
    trends = get_module_score_trends()
    if trends:
        print(f"\n📈 模块分数趋势 (最近):")
        current_round = None
        for t in trends[-30:]:  # 最近 30 条
            if t["round"] != current_round:
                current_round = t["round"]
                print(f"\n  Round #{current_round}:")
            print(f"    {t['module']:22s} → {t['avg_score']:.1f}")

    print("═" * 60)


def cmd_accept():
    """将开发版 Prompt 同步到生产环境（含安全检查）。"""
    dev_prompt = _load_dev_prompt()
    if not dev_prompt:
        return False

    # 1. Dry Run 安全检查
    print("\n🔍 执行 Dry Run 安全检查...")
    gen_client, gen_model = _get_ai_client(use_auditor_model=False)

    # 创建一个临时客户端使用 dev prompt
    test_client = gen_client.__class__.__new__(gen_client.__class__)
    test_client.__dict__.update(gen_client.__dict__)
    test_client.prompt_file = PROMPT_DEV_FILE

    results, metadata = test_client.generate_mnemonics(["test"])
    if not results:
        print("❌ Dry Run 失败: 新 Prompt 无法生成有效 JSON 输出。")
        print("   拒绝上线。请检查 dev prompt 是否破坏了 JSON 结构。")
        return False

    print("✅ Dry Run 通过: JSON 输出格式正常。")

    # 2. 备份当前生产版本
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        old_content = f.read().strip()
    old_hash = hashlib.sha256(old_content.encode()).hexdigest()[:8]
    backup_path = os.path.join(PROMPT_HISTORY_DIR, f"gem_prompt_{old_hash}.md")
    shutil.copy2(PROMPT_FILE, backup_path)
    print(f"📦 已备份旧版本: {backup_path}")

    # 3. 覆盖生产版本
    shutil.copy2(PROMPT_DEV_FILE, PROMPT_FILE)
    new_hash = hashlib.sha256(dev_prompt.encode()).hexdigest()[:8]
    print(f"✅ 已将开发版 Prompt 上线到生产环境!")
    print(f"   旧版本: {old_hash}")
    print(f"   新版本: {new_hash}")

    # 4. 追加 CHANGELOG
    try:
        changelog_path = os.path.join(
            os.path.dirname(os.path.dirname(PROMPT_FILE)), "CHANGELOG.md"
        )
        if os.path.exists(changelog_path):
            from core.db_manager import get_timestamp_with_tz
            entry = (
                f"\n### {get_timestamp_with_tz()[:10]}\n"
                f"- [Prompt] `gem_prompt.md` 更新至版本 `{new_hash}`"
                f" (原版本 `{old_hash}` 已备份至 `docs/prompts/history/`)\n"
            )
            with open(changelog_path, "a", encoding="utf-8") as f:
                f.write(entry)
            print(f"📝 已追加 CHANGELOG 记录。")
    except Exception as e:
        print(f"⚠️  CHANGELOG 追加失败: {e}")

    return True


def cmd_diff(hash1: str = None, hash2: str = None):
    """对比两个版本的 Prompt 差异。
    若不传参数，默认对比 [生产版] vs [当前开发版]。
    """
    import difflib
    
    content1 = ""
    label1 = ""
    content2 = ""
    label2 = ""

    if not hash1:
        # 默认：对比生产版 vs 开发版
        if not os.path.exists(PROMPT_FILE):
            print(f"❌ 生产版 Prompt 不存在: {PROMPT_FILE}")
            return
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            content1 = f.read().splitlines()
        label1 = "PROD (gem_prompt.md)"
        
        dev_content = _load_dev_prompt()
        if not dev_content: return
        content2 = dev_content.splitlines()
        label2 = "DEV (gem_prompt_iteration.md)"
    else:
        # 对比两个哈希版本
        content1_raw = get_prompt_version_content(hash1)
        if not content1_raw:
            print(f"❌ 未找到版本 {hash1}")
            return
        content1 = content1_raw.splitlines()
        label1 = f"Version {hash1}"
        
        if hash2:
            content2_raw = get_prompt_version_content(hash2)
            if not content2_raw:
                print(f"❌ 未找到版本 {hash2}")
                return
            content2 = content2_raw.splitlines()
            label2 = f"Version {hash2}"
        else:
            dev_content = _load_dev_prompt()
            content2 = dev_content.splitlines()
            label2 = "DEV (Current)"

    diff = difflib.unified_diff(content1, content2, fromfile=label1, tofile=label2, lineterm="")
    
    has_diff = False
    print("\n" + "🔍" + "─" * 48)
    for line in diff:
        has_diff = True
        if line.startswith('+'):
            print(f"\033[32m{line}\033[0m") # 绿色
        elif line.startswith('-'):
            print(f"\033[31m{line}\033[0m") # 红色
        elif line.startswith('^'):
            print(f"\033[36m{line}\033[0m") # 青色
        else:
            print(line)
    
    if not has_diff:
        print("✅ 两个版本完全一致，没有差异。")
    print("─" * 50 + "\n")


def cmd_rollback(version_hash: str):
    """回滚到指定历史版本。"""
    # 从数据库查找
    content = get_prompt_version_content(version_hash)

    if not content:
        # 尝试从 history 目录查找
        for filename in os.listdir(PROMPT_HISTORY_DIR):
            if version_hash in filename:
                path = os.path.join(PROMPT_HISTORY_DIR, filename)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                break

    if not content:
        print(f"❌ 未找到版本 {version_hash} 的 Prompt 内容。")
        return False

    # 覆盖生产版本
    with open(PROMPT_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ 已回滚 gem_prompt.md 至版本 {version_hash}")
    return True


def cmd_reset():
    """彻底重置当前用户的迭代数据库数据。"""
    confirm = input("⚠️  确定要清空所有迭代历史、评分和缓存吗？(y/N): ").strip().lower()
    if confirm != 'y':
        print("取消重置。")
        return
        
    from config import PROMPT_ITERATION_DB
    from core.prompt_iteration_db import init_iteration_db
    if os.path.exists(PROMPT_ITERATION_DB):
        os.remove(PROMPT_ITERATION_DB)
        print(f"✅ 已删除本地数据库: {PROMPT_ITERATION_DB}")
    
    init_iteration_db()
    print("✨ 已重新初始化空的迭代数据库。")


def cmd_clear_eval(version_hash: str = None):
    """清除指定版本（默认为当前版本）的审计评分记录，以便重新评分。"""
    if not version_hash:
        dev_prompt = _load_dev_prompt()
        if not dev_prompt: return
        version_hash = compute_version_hash(dev_prompt)
    
    from core.prompt_iteration_db import _get_iteration_conn
    conn = _get_iteration_conn()
    try:
        cur = conn.cursor()
        # 1. 获取要删除的 round_id
        cur.execute("SELECT id FROM evaluation_rounds WHERE version_hash = ?", (version_hash,))
        round_ids = [row[0] for row in cur.fetchall()]
        
        if not round_ids:
            print(f"ℹ️  未发现版本 {version_hash} 的评分记录，无需清理。")
            return

        # 2. 删除模块分数和轮次记录
        for rid in round_ids:
            cur.execute("DELETE FROM module_scores WHERE round_id = ?", (rid,))
        cur.execute("DELETE FROM evaluation_rounds WHERE version_hash = ?", (version_hash,))
        
        conn.commit()
        print(f"✅ 已成功清除版本 {version_hash} 的 {len(round_ids)} 条审计评分记录。")
        print("💡 下次运行 optimize 时将强制重新审计，但会复用单词笔记缓存。")
    finally:
        conn.close()


# ══════════════════════════════════════════════════
# 菜单集成入口（由 main.py 调用）
# ══════════════════════════════════════════════════

def run_interactive_menu():
    """Prompt 实验室交互式子菜单。"""
    while True:
        print("\n" + "═" * 35)
        print("🔬 Prompt 实验室")
        print("═" * 35)
        print("  1. [初始化] 将生产 Prompt 拷贝到开发环境")
        print("  2. [评估] 运行 Benchmark 跑分")
        print("  3. [优化] 自动改写低分模块 (冻结高分)")
        print("  4. [自动循环] 连续迭代 N 轮 (含收敛检测)")
        print("  5. [历史趋势] 查看模块分数变化")
        print("  6. [上线] 同步到生产环境 (含安全检查)")
        print("  7. [回滚] 恢复到指定历史版本")
        print("  8. [差异] 对比生产版与当前开发版的不同")
        print("  9. [重置] 清空所有迭代数据 (慎用)")
        print("  10. [清理评分] 仅删除当前版本的审计结果")
        print("  0. ← 返回主菜单")
        print("-" * 35)

        try:
            choice = input("请输入选项序号: ").strip()
        except (KeyboardInterrupt, EOFError):
            raise KeyboardInterrupt

        if choice == "0":
            break
        elif choice == "1":
            cmd_init()
        elif choice == "2":
            cmd_evaluate()
        elif choice == "3":
            cmd_optimize()
        elif choice == "4":
            try:
                rounds_input = input("请输入迭代轮数 (默认 5): ").strip()
                rounds = int(rounds_input) if rounds_input else 5
                cmd_loop(rounds=rounds)
            except ValueError:
                print("❌ 请输入有效的正整数。")
        elif choice == "5":
            cmd_history()
        elif choice == "6":
            confirm = input("⚠️  确认将开发版 Prompt 上线到生产环境？(Y/N): ").strip().lower()
            if confirm == "y":
                cmd_accept()
            else:
                print("已取消。")
        elif choice == "7":
            vh = input("请输入要回滚到的版本哈希: ").strip()
            if vh:
                cmd_rollback(vh)
        elif choice == "8":
            cmd_diff()
        elif choice == "9":
            cmd_reset()
        elif choice == "10":
            cmd_clear_eval()
        else:
            print("❌ 无效选项。")


# ══════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Prompt 迭代优化开发工具")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    subparsers.add_parser("init", help="初始化：将生产 Prompt 拷贝到开发目录")

    eval_parser = subparsers.add_parser("evaluate", help="评估：运行 Benchmark 跑分")
    eval_parser.add_argument("--freeze-threshold", type=float, default=DEFAULT_FREEZE_THRESHOLD,
                             help=f"冻结阈值 (默认 {DEFAULT_FREEZE_THRESHOLD})")
    eval_parser.add_argument("--force", action="store_true", help="强制从零生成（忽略中间缓存）")

    opt_parser = subparsers.add_parser("optimize", help="优化：自动改写低分模块")
    opt_parser.add_argument("--freeze-threshold", type=float, default=DEFAULT_FREEZE_THRESHOLD,
                            help=f"冻结阈值 (默认 {DEFAULT_FREEZE_THRESHOLD})")
    opt_parser.add_argument("--force", action="store_true", help="强制重新评估（忽略已有评分记录）")

    loop_parser = subparsers.add_parser("loop", help="自动循环：连续迭代 N 轮")
    loop_parser.add_argument("--rounds", type=int, default=5, help="迭代轮数 (默认 5)")
    loop_parser.add_argument("--freeze-threshold", type=float, default=DEFAULT_FREEZE_THRESHOLD,
                             help=f"冻结阈值 (默认 {DEFAULT_FREEZE_THRESHOLD})")

    subparsers.add_parser("history", help="查看迭代历史趋势")
    subparsers.add_parser("accept", help="上线：同步到生产环境")
    subparsers.add_parser("diff", help="对比差异 (默认对比生产版 vs 开发版)")
    subparsers.add_parser("reset", help="重置迭代数据库 (清空所有历史数据)")
    subparsers.add_parser("clear-eval", help="仅清除当前版本的评分记录 (保留生成缓存)")

    rollback_parser = subparsers.add_parser("rollback", help="回滚到指定版本")
    rollback_parser.add_argument("version_hash", help="版本哈希")

    subparsers.add_parser("menu", help="进入交互式菜单")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "init":
        cmd_init()
    elif args.command == "evaluate":
        cmd_evaluate(args.freeze_threshold, force_re_gen=args.force)
    elif args.command == "optimize":
        cmd_optimize(args.freeze_threshold, force_re_eval=args.force)
    elif args.command == "loop":
        cmd_loop(rounds=args.rounds, freeze_threshold=args.freeze_threshold)
    elif args.command == "history":
        cmd_history()
    elif args.command == "accept":
        cmd_accept()
    elif args.command == "diff":
        cmd_diff()
    elif args.command == "rollback":
        cmd_rollback(args.version_hash)
    elif args.command == "reset":
        cmd_reset()
    elif args.command == "clear-eval":
        cmd_clear_eval()
    elif args.command == "menu":
        run_interactive_menu()


if __name__ == "__main__":
    main()
