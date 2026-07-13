"""
主入口 —— 数据驱动的 AI 产品定价博弈论文自动爬取系统

流程：
    1. Semantic Scholar API 多关键词检索论文
    2. 本地缓存去重（增量更新）
    3. 上传增量论文到 Zotero 指定 Collection
"""

import logging
import sys
from datetime import datetime

import cache
import config
import s2_fetcher
import zotero_client

# ── 日志配置 ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.DATA_DIR / "fetch.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")


def main() -> None:
    """执行完整的论文爬取和入库流程。"""
    start_time: datetime = datetime.now()
    logger.info("=" * 60)
    logger.info("论文爬取系统启动")
    logger.info("研究方向: 数据驱动的 AI 产品定价博弈")
    logger.info("=" * 60)

    # ── Step 1: 从 Semantic Scholar 检索论文 ────────────────────────
    logger.info("[Step 1/3] 正在从 Semantic Scholar 检索论文...")
    all_papers = s2_fetcher.fetch_all_papers()

    if not all_papers:
        logger.warning("未检索到任何论文，请检查关键词或网络连接。")
        return

    logger.info("检索到 %d 篇论文（去重+筛选后）。", len(all_papers))

    # ── Step 2: 本地缓存去重（增量更新） ───────────────────────────
    logger.info("[Step 2/3] 正在与本地缓存对比，计算增量...")
    incremental_papers = cache.merge_with_cache(all_papers)

    if not incremental_papers:
        logger.info("没有新增论文，本次无需更新 Zotero。")
        return

    logger.info("发现 %d 篇新增论文，准备入库。", len(incremental_papers))

    # 打印新增论文摘要
    logger.info("── 新增论文列表 ──")
    for i, paper in enumerate(incremental_papers, 1):
        title: str = paper.get("title", "Untitled")
        year: int = paper.get("year", 0)
        citations: int = paper.get("citationCount", 0)
        doi: str = (paper.get("externalIds") or {}).get("DOI", "N/A")
        logger.info("  %d. [%d] %s (引用: %d, DOI: %s)", i, year, title[:80], citations, doi)

    # ── Step 3: 上传到 Zotero ─────────────────────────────────────
    logger.info("[Step 3/3] 正在将论文上传到 Zotero...")
    try:
        stats = zotero_client.batch_upload_to_zotero(incremental_papers)
    except ValueError as e:
        logger.error("Zotero 配置错误: %s", e)
        logger.info("提示: 请在 .env 文件中设置 ZOTERO_API_KEY 和 ZOTERO_USER_ID")
        logger.info("      Zotero API Key 申请: https://www.zotero.org/settings/keys/new")
        stats = {"success": 0, "skipped": len(incremental_papers), "failed": 0}

    # ── 汇总报告 ──────────────────────────────────────────────────
    elapsed: float = (datetime.now() - start_time).total_seconds()
    logger.info("=" * 60)
    logger.info("任务完成！耗时 %.1f 秒", elapsed)
    logger.info("总计检索: %d 篇", len(all_papers))
    logger.info("新增论文: %d 篇", len(incremental_papers))
    logger.info("Zotero 入库: 成功=%d, 跳过=%d, 失败=%d",
                stats["success"], stats["skipped"], stats["failed"])
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
