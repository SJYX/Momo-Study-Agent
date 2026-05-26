"""同步自愈机制：修复卡住的 sync_status 记录

当本地记录长时间处于 sync_status=0 但云端实际已有数据时，
说明同步成功但状态更新失败。自愈机制检查云端数据并修复状态。
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def get_stuck_records(
    older_than_hours: int,
    limit: int,
    db_path: str,
    session: Any
) -> List[Dict[str, Any]]:
    """查询卡住的同步记录

    Args:
        older_than_hours: 超过多少小时视为卡住
        limit: 最多返回多少条记录
        db_path: 数据库路径（用于日志）
        session: libsql 会话对象

    Returns:
        卡住的记录列表，每条包含 id, voc_id, created_at
    """
    threshold = datetime.now() - timedelta(hours=older_than_hours)
    threshold_str = threshold.isoformat()

    query = """
        SELECT id, voc_id, created_at
        FROM ai_word_notes
        WHERE sync_status = 0
          AND created_at < ?
        ORDER BY created_at ASC
        LIMIT ?
    """

    cursor = session.execute(query, (threshold_str, limit))
    rows = cursor.fetchall()

    # 转换为字典列表
    records = []
    for row in rows:
        # 支持字典和元组两种格式
        if isinstance(row, dict):
            records.append({
                "id": row["id"],
                "voc_id": row["voc_id"],
                "created_at": row["created_at"]
            })
        else:
            records.append({
                "id": row[0],
                "voc_id": row[1],
                "created_at": row[2]
            })

    return records


def heal_stuck_sync_status(
    momo_api: Any,
    max_records: int = 50,
    db_path: str = None,
    session: Any = None
) -> int:
    """修复卡住的 sync_status 记录

    检查云端是否有数据，如果有则更新 sync_status=1。

    Args:
        momo_api: MaimemoAPI 实例
        max_records: 最多处理多少条记录
        db_path: 数据库路径
        session: libsql 会话对象（如果为 None 则创建新连接）

    Returns:
        修复的记录数量
    """
    # 如果没有提供 session，创建新连接
    if session is None:
        from database.connection import _get_main_write_conn_singleton
        if db_path is None:
            from config import _config
            db_path = _config.DB_PATH
        session = _get_main_write_conn_singleton(db_path)

    # 查询卡住的记录（超过 1 小时）
    stuck_records = get_stuck_records(
        older_than_hours=1,
        limit=max_records,
        db_path=db_path,
        session=session
    )

    if not stuck_records:
        logger.debug("自愈检查：没有发现卡住的记录")
        return 0

    logger.info(f"自愈检查：发现 {len(stuck_records)} 条卡住的记录，开始检查云端数据")

    healed_count = 0

    for record in stuck_records:
        voc_id = record["voc_id"]
        record_id = record["id"]

        try:
            # 检查云端是否有数据
            cloud_data = momo_api.list_interpretations(voc_id)

            if cloud_data and cloud_data.get("data"):
                # 云端有数据，说明同步成功但状态更新失败
                logger.info(f"自愈：记录 {record_id} (voc_id={voc_id}) 云端有数据，修复 sync_status")

                # 更新 sync_status
                update_query = """
                    UPDATE ai_word_notes
                    SET sync_status = 1
                    WHERE id = ?
                """
                session.execute(update_query, (record_id,))
                healed_count += 1
            else:
                # 云端无数据，说明确实未同步，跳过
                logger.debug(f"自愈：记录 {record_id} (voc_id={voc_id}) 云端无数据，跳过")

        except Exception as e:
            logger.warning(f"自愈：检查记录 {record_id} 时出错: {e}")
            continue

    if healed_count > 0:
        # 提交更改
        session.commit()
        logger.info(f"自愈完成：修复了 {healed_count} 条记录")

    return healed_count
