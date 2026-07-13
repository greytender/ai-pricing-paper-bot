"""
本地缓存模块
持久化已爬取的论文数据到 JSON 文件，避免重复请求 API。
"""

import json
import logging
from typing import Any

import config

logger = logging.getLogger(__name__)


def load_cache() -> dict[str, Any]:
    """
    从本地 JSON 文件加载论文缓存。

    Returns:
        缓存字典，包含 "papers" 列表和 "doi_set" 集合
    """
    if not config.PAPER_CACHE_FILE.exists():
        logger.info("缓存文件不存在，将创建新缓存。")
        return {"papers": [], "doi_set": []}

    try:
        with open(config.PAPER_CACHE_FILE, "r", encoding="utf-8") as f:
            cache: dict[str, Any] = json.load(f)
        logger.info("加载缓存: %d 篇论文。", len(cache.get("papers", [])))
        return cache
    except (json.JSONDecodeError, IOError) as e:
        logger.error("缓存文件损坏，重新创建: %s", e)
        return {"papers": [], "doi_set": []}


def save_cache(cache: dict[str, Any]) -> None:
    """
    将缓存写入本地 JSON 文件。

    Args:
        cache: 缓存字典
    """
    try:
        with open(config.PAPER_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        logger.info("缓存已保存: %d 篇论文。", len(cache.get("papers", [])))
    except IOError as e:
        logger.error("保存缓存失败: %s", e)


def merge_with_cache(new_papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    将新论文与本地缓存合并，返回增量（仅新增的）论文列表。

    Args:
        new_papers: 新爬取的论文列表

    Returns:
        缓存中不存在的论文列表（增量部分）
    """
    cache = load_cache()
    cached_dois: set[str] = set(cache.get("doi_set", []))
    cached_titles: set[str] = set(cache.get("title_set", []))

    incremental: list[dict[str, Any]] = []

    for paper in new_papers:
        doi: str = (paper.get("externalIds") or {}).get("DOI", "")
        title: str = (paper.get("title") or "").strip().lower()

        # 通过 DOI 或标题判断是否已缓存
        if doi and doi in cached_dois:
            continue
        if title and title in cached_titles:
            continue

        incremental.append(paper)

        # 更新缓存索引
        if doi:
            cached_dois.add(doi)
        if title:
            cached_titles.add(title)

    # 将增量论文追加到缓存
    cache["papers"].extend(incremental)
    cache["doi_set"] = list(cached_dois)
    cache["title_set"] = list(cached_titles)
    save_cache(cache)

    logger.info(
        "增量合并: 新增 %d 篇，缓存总量 %d 篇。",
        len(incremental), len(cache["papers"]),
    )
    return incremental
