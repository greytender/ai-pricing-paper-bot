"""
Semantic Scholar 论文检索模块
双通道检索：近期论文(2025+) + 经典高引文献（不限年份）
顶刊/顶会白名单过滤，确保只保留高质量文献。
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
    "publicationDate,fieldsOfStudy,journal,tldr,publicationVenue"
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


def search_papers_by_query(
    query: str,
    year_range: str = "",
    max_papers: int | None = None,
) -> list[dict[str, Any]]:
    """
    使用单个关键词在 Semantic Scholar 搜索论文。
    自动分页直到满足上限或结果耗尽。

    Args:
        query: 搜索关键词
        year_range: 年份过滤，如 "2025-2026"，空字符串表示不限
        max_papers: 本组最大论文数（默认使用全局配置）

    Returns:
        论文字典列表
    """
    cap: int = max_papers if max_papers is not None else config.MAX_PAPERS_PER_QUERY
    all_papers: list[dict[str, Any]] = []
    offset: int = 0
    total: int = 0
    limit: int = min(100, cap)  # API 单页上限 100

    headers = _build_headers()
    url = f"{config.S2_BASE_URL}/paper/search"

    while len(all_papers) < cap:
        params: dict[str, Any] = {
            "query": query,
            "fields": PAPER_FIELDS,
            "limit": limit,
            "offset": offset,
        }
        if year_range:
            params["year"] = year_range

        data = _make_request(url, params, headers)
        if data is None:
            logger.warning("查询 '%s' 在 offset=%d 时请求失败，跳过。", query, offset)
            break

        batch: list[dict[str, Any]] = data.get("data", [])
        if not batch:
            logger.info("查询 '%s' 无更多结果，共获取 %d 篇。", query, len(all_papers))
            break

        all_papers.extend(batch)
        total = data.get("total", 0)

        # 判断是否还有更多结果
        next_offset: int = data.get("next", offset + limit)
        if next_offset <= offset or len(all_papers) >= total:
            break

        offset = next_offset
        time.sleep(config.REQUEST_DELAY_SECONDS)

    logger.info("关键词 '%s' 获取 %d 篇论文 (总计 %d)。", query, len(all_papers), total)
    return all_papers[:cap]


def get_recommended_papers(paper_id: str, limit: int = 10) -> list[dict[str, Any]]:
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


def _extract_venue_name(paper: dict[str, Any]) -> str:
    """
    从论文数据中提取所有可能的 venue 名称，统一小写返回。
    """
    # 优先级: publicationVenue.name > journal.name > venue
    pub_venue: dict[str, Any] = paper.get("publicationVenue") or {}
    if pub_venue.get("name"):
        return pub_venue["name"].strip().lower()

    journal_info: dict[str, Any] = paper.get("journal") or {}
    if journal_info.get("name"):
        return journal_info["name"].strip().lower()

    venue: str = paper.get("venue") or ""
    if venue:
        return venue.strip().lower()

    return ""


def is_top_venue(paper: dict[str, Any]) -> bool:
    """
    判断论文是否发表于顶刊/顶会。
    匹配逻辑：论文的 venue/journal 名称是否包含白名单中的关键词。

    Args:
        paper: 论文字典

    Returns:
        是否为顶刊/顶会论文
    """
    venue_name: str = _extract_venue_name(paper)
    if not venue_name:
        return False

    for top_name in config.TOP_VENUES:
        if top_name in venue_name:
            return True

    return False


def filter_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    筛选论文，必须满足全部基础条件 + 至少一条质量条件：

    基础条件：
    - 必须有摘要
    - 必须有可下载的 PDF（openAccessPdf.url 存在）

    质量条件（满足任一）：
    1. 来自顶刊/顶会白名单
    2. 有影响力引用数 >= 10（influentialCitationCount）
    3. 经典文献且引用数 >= MIN_CITATIONS_CLASSIC

    Args:
        papers: 论文列表

    Returns:
        筛选后的论文列表
    """
    filtered: list[dict[str, Any]] = []
    top_venue_count: int = 0
    influential_count: int = 0
    high_cite_count: int = 0
    no_pdf_count: int = 0

    for paper in papers:
        # 基础条件：必须有摘要
        if not paper.get("abstract"):
            continue

        # 基础条件：必须有可下载的 PDF
        oa_pdf: dict[str, str] = paper.get("openAccessPdf") or {}
        if not oa_pdf.get("url"):
            no_pdf_count += 1
            continue

        # 质量判断 1: 顶刊/顶会
        if is_top_venue(paper):
            top_venue_count += 1
            filtered.append(paper)
            continue

        # 质量判断 2: 有影响力引用数
        influential: int = paper.get("influentialCitationCount", 0)
        if influential >= 10:
            influential_count += 1
            filtered.append(paper)
            continue

        # 质量判断 3: 高引用（经典文献通道）
        citations: int = paper.get("citationCount", 0)
        if citations >= config.MIN_CITATIONS_CLASSIC:
            high_cite_count += 1
            filtered.append(paper)
            continue

    logger.info(
        "论文筛选结果: 无PDF=%d, 顶刊/顶会=%d, 有影响力引用>=10=%d, 高引用>=%d=%d, 总通过=%d (总输入=%d)",
        no_pdf_count, top_venue_count, influential_count, config.MIN_CITATIONS_CLASSIC,
        high_cite_count, len(filtered), len(papers),
    )
    return filtered


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


def fetch_all_papers() -> list[dict[str, Any]]:
    """
    执行完整的论文检索流程（双通道，精要模式）：
    通道 A — 近期论文（2025+）：精简关键词，宽泛检索
    通道 B — 经典文献（不限年份）：更少关键词 + 高引用过滤 + 顶刊筛选

    合并 → 去重 → 质量筛选 → 推荐扩展 → 最终去重 → 截取 Top N

    Returns:
        最终的论文列表（最多 MAX_FINAL_PAPERS 篇）
    """
    all_papers: list[dict[str, Any]] = []

    # ── 通道 A: 近期论文 (2025+) ──────────────────────────────────
    logger.info("=" * 50)
    logger.info("通道 A: 近期论文检索 (年份: %s)", config.YEAR_RANGE_RECENT)
    logger.info("=" * 50)
    recent_count: int = 0
    for query in config.SEARCH_QUERIES_RECENT:
        if recent_count >= config.MAX_TOTAL_RECENT:
            break
        logger.info("搜索关键词: %s", query)
        papers = search_papers_by_query(
            query,
            year_range=config.YEAR_RANGE_RECENT,
            max_papers=min(config.MAX_PAPERS_PER_QUERY, config.MAX_TOTAL_RECENT - recent_count),
        )
        all_papers.extend(papers)
        recent_count += len(papers)
        time.sleep(config.REQUEST_DELAY_SECONDS)

    # ── 通道 B: 经典高引文献 ─────────────────────────────────────
    logger.info("=" * 50)
    logger.info("通道 B: 经典文献检索 (不限年份)")
    logger.info("=" * 50)
    classic_count: int = 0
    for query in config.SEARCH_QUERIES_CLASSIC:
        if classic_count >= config.MAX_TOTAL_CLASSIC:
            break
        logger.info("搜索关键词: %s", query)
        papers = search_papers_by_query(
            query,
            year_range=config.YEAR_RANGE_CLASSIC,
            max_papers=min(15, config.MAX_TOTAL_CLASSIC - classic_count),
        )
        all_papers.extend(papers)
        classic_count += len(papers)
        time.sleep(config.REQUEST_DELAY_SECONDS)

    # ── 第一次去重 + 质量筛选 ────────────────────────────────────
    logger.info("全量去重中...")
    all_papers = deduplicate_papers(all_papers)

    logger.info("顶刊/质量筛选中...")
    all_papers = filter_papers(all_papers)

    # ── 对 Top 3 高引论文获取推荐 ───────────────────────────────
    logger.info("扩展推荐论文...")
    all_papers.sort(key=lambda p: p.get("citationCount", 0), reverse=True)
    top_papers = all_papers[:3]
    for paper in top_papers:
        paper_id: str = paper.get("paperId", "")
        if paper_id:
            recs = get_recommended_papers(paper_id, limit=5)
            all_papers.extend(recs)
            time.sleep(config.REQUEST_DELAY_SECONDS)

    # ── 最终去重 + 筛选 + 截取 Top N ─────────────────────────────
    all_papers = deduplicate_papers(all_papers)
    all_papers = filter_papers(all_papers)

    # 按引用数降序排列，截取 Top N
    all_papers.sort(key=lambda p: p.get("citationCount", 0), reverse=True)
    all_papers = all_papers[: config.MAX_FINAL_PAPERS]

    # 标注来源通道
    for paper in all_papers:
        year: int = paper.get("year", 0)
        if year >= 2025:
            paper["_channel"] = "recent"
        else:
            paper["_channel"] = "classic"

    logger.info("=" * 50)
    logger.info("检索完成！共 %d 篇高质量论文（精要模式，上限 %d）",
                len(all_papers), config.MAX_FINAL_PAPERS)
    if all_papers:
        recent = sum(1 for p in all_papers if p.get("_channel") == "recent")
        classic = sum(1 for p in all_papers if p.get("_channel") == "classic")
        logger.info("  近期 (2025+): %d 篇, 经典: %d 篇", recent, classic)
    logger.info("=" * 50)
    return all_papers
