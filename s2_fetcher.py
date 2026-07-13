"""
Semantic Scholar 论文检索模块
通过多组关键词搜索论文，支持分页、去重、筛选和本地缓存。
"""

import time
import logging
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

# ── 返回字段 ─────────────────────────────────────────────────────
PAPER_FIELDS: str = (
    "paperId,title,abstract,year,authors,venue,citationCount,"
    "influentialCitationCount,externalIds,url,openAccessPdf,"
    "publicationDate,fieldsOfStudy,journal,tldr"
)


def _build_headers() -> dict[str, str]:
    """构建请求头，如果有 API Key 则附带。"""
    headers: dict[str, str] = {}
    if config.SEMANTIC_SCHOLAR_KEY:
        headers["x-api-key"] = config.SEMANTIC_SCHOLAR_KEY
    return headers


# 无 API Key 时的请求间隔（S2 对匿名用户限制约 100 req/5min 全局共享）
ANONYMOUS_DELAY: float = 3.5
MAX_RETRIES: int = 3


def _make_request(
    url: str,
    params: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any] | None:
    """
    封装 HTTP GET 请求，包含 429 自动退避重试机制。
    无 API Key 时使用更长的请求间隔。
    """
    delay: float = config.REQUEST_DELAY_SECONDS if config.SEMANTIC_SCHOLAR_KEY else ANONYMOUS_DELAY

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                # 指数退避：3s, 6s, 12s
                wait: float = delay * (2 ** (attempt - 1))
                logger.warning(
                    "429 速率限制，第 %d/%d 次重试，等待 %.1f 秒...", attempt, MAX_RETRIES, wait
                )
                time.sleep(wait)
                continue
            logger.error("HTTP 错误 (%s): %s", e.response.status_code, e.response.text[:500])
            return None
        except requests.exceptions.ConnectionError:
            logger.error("连接失败，请检查网络。")
            return None
        except requests.exceptions.Timeout:
            logger.error("请求超时。")
            return None
        except Exception as e:
            logger.error("未知错误: %s", e, exc_info=True)
            return None

    logger.error("已达到最大重试次数 (%d)，放弃请求。", MAX_RETRIES)
    return None


def search_papers_by_query(query: str) -> list[dict[str, Any]]:
    """
    使用单个关键词在 Semantic Scholar 搜索论文。
    自动分页直到满足 MAX_PAPERS_PER_QUERY 或结果耗尽。

    Args:
        query: 搜索关键词

    Returns:
        论文字典列表
    """
    all_papers: list[dict[str, Any]] = []
    offset: int = 0
    total: int = 0
    limit: int = min(100, config.MAX_PAPERS_PER_QUERY)  # API 单页上限 100

    headers = _build_headers()
    url = f"{config.S2_BASE_URL}/paper/search"

    while len(all_papers) < config.MAX_PAPERS_PER_QUERY:
        params: dict[str, Any] = {
            "query": query,
            "fields": PAPER_FIELDS,
            "limit": limit,
            "offset": offset,
            "year": config.YEAR_RANGE,
        }

        data = _make_request(url, params, headers)
        if data is None:
            logger.warning("查询 '%s' 在 offset=%d 时请求失败，跳过。", query, offset)
            break

        batch: list[dict[str, Any]] = data.get("data", [])
        if not batch:
            logger.info("查询 '%s' 无更多结果，共获取 %d 篇。", query, len(all_papers))
            break

        all_papers.extend(batch)
        total: int = data.get("total", 0)

        # 判断是否还有更多结果
        next_offset: int = data.get("next", offset + limit)
        if next_offset <= offset or len(all_papers) >= total:
            break

        offset = next_offset
        time.sleep(config.REQUEST_DELAY_SECONDS)

    logger.info("关键词 '%s' 获取 %d 篇论文 (总计 %d)。", query, len(all_papers), total)
    return all_papers[: config.MAX_PAPERS_PER_QUERY]


def get_recommended_papers(paper_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """
    获取与指定论文相关的推荐论文（需要 Semantic Scholar API Key）。

    Args:
        paper_id: S2 论文 ID
        limit: 返回数量上限

    Returns:
        推荐论文字典列表
    """
    if not config.SEMANTIC_SCHOLAR_KEY:
        logger.warning("未配置 SEMANTIC_SCHOLAR_KEY，无法使用推荐 API。")
        return []

    headers = _build_headers()
    url = f"https://api.semanticscholar.org/recommendations/v1/papers/{paper_id}/recommended"
    params = {"fields": PAPER_FIELDS, "limit": limit}

    data = _make_request(url, params, headers)
    if data is None:
        return []

    recommended: list[dict[str, Any]] = data.get("data", [])
    logger.info("论文 %s 获取 %d 篇推荐论文。", paper_id[:12], len(recommended))
    return recommended


def get_paper_details(paper_id: str) -> dict[str, Any] | None:
    """
    通过 S2 PaperId 或 DOI 获取单篇论文的详细信息。

    Args:
        paper_id: 论文标识符，如 S2 ID、DOI:10.xxx、ARXIV:xxxx.xxxxx

    Returns:
        论文详情字典
    """
    headers = _build_headers()
    url = f"{config.S2_BASE_URL}/paper/{paper_id}"
    params = {"fields": PAPER_FIELDS}

    return _make_request(url, params, headers)


def deduplicate_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    论文去重：优先以 DOI 去重，其次以 paperId 去重，最后以标题去重。
    保留每组重复论文中引用数最高的那篇。

    Args:
        papers: 论文列表

    Returns:
        去重后的论文列表
    """
    seen_doi: dict[str, dict[str, Any]] = {}
    seen_s2id: dict[str, dict[str, Any]] = {}
    seen_title: dict[str, dict[str, Any]] = {}

    for paper in papers:
        # 按 DOI 去重
        doi: str | None = (paper.get("externalIds") or {}).get("DOI")
        if doi:
            if doi in seen_doi:
                if paper.get("citationCount", 0) > seen_doi[doi].get("citationCount", 0):
                    seen_doi[doi] = paper
                continue
            seen_doi[doi] = paper

        # 按 S2 PaperId 去重
        s2_id: str = paper.get("paperId", "")
        if s2_id and s2_id in seen_s2id:
            continue
        if s2_id:
            seen_s2id[s2_id] = paper

        # 按标题去重
        title: str = (paper.get("title") or "").strip().lower()
        if title and title in seen_title:
            continue
        if title:
            seen_title[title] = paper

    # 合并：以 DOI 匹配的优先，然后 S2 ID，最后标题
    merged: list[dict[str, Any]] = []
    all_keys: set[str] = set()

    for paper in seen_doi.values():
        key = paper.get("paperId", id(paper))
        if key not in all_keys:
            merged.append(paper)
            all_keys.add(key)

    for paper in seen_s2id.values():
        key = paper.get("paperId", id(paper))
        if key not in all_keys:
            merged.append(paper)
            all_keys.add(key)

    for paper in seen_title.values():
        key = paper.get("paperId", id(paper))
        if key not in all_keys:
            merged.append(paper)
            all_keys.add(key)

    logger.info("去重前 %d 篇，去重后 %d 篇。", len(papers), len(merged))
    return merged


def filter_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    筛选论文：过滤无摘要、低于最低引用数的论文。

    Args:
        papers: 论文列表

    Returns:
        筛选后的论文列表
    """
    filtered: list[dict[str, Any]] = []
    for paper in papers:
        # 必须有摘要
        if not paper.get("abstract"):
            continue
        # 引用数过滤
        if paper.get("citationCount", 0) < config.MIN_CITATIONS:
            continue
        filtered.append(paper)

    logger.info("筛选前 %d 篇，筛选后 %d 篇。", len(papers), len(filtered))
    return filtered


def fetch_all_papers() -> list[dict[str, Any]]:
    """
    执行完整的论文检索流程：
    1. 逐个关键词搜索
    2. 对高引论文获取推荐论文
    3. 全量去重
    4. 筛选

    Returns:
        最终的论文列表
    """
    all_papers: list[dict[str, Any]] = []

    for query in config.SEARCH_QUERIES:
        logger.info("正在搜索关键词: %s", query)
        papers = search_papers_by_query(query)
        all_papers.extend(papers)
        time.sleep(config.REQUEST_DELAY_SECONDS)

    # 对引用数 Top 5 的论文获取推荐
    all_papers.sort(key=lambda p: p.get("citationCount", 0), reverse=True)
    top_papers = all_papers[:5]
    for paper in top_papers:
        paper_id: str = paper.get("paperId", "")
        if paper_id:
            recs = get_recommended_papers(paper_id, limit=10)
            all_papers.extend(recs)
            time.sleep(config.REQUEST_DELAY_SECONDS)

    # 去重 + 筛选
    all_papers = deduplicate_papers(all_papers)
    all_papers = filter_papers(all_papers)

    # 按引用数降序排列
    all_papers.sort(key=lambda p: p.get("citationCount", 0), reverse=True)

    logger.info("检索完成，共 %d 篇高质量论文。", len(all_papers))
    return all_papers
