"""
全局配置模块 —— 所有密钥和环境变量统一从此处读取，禁止硬编码。
优先从 .env 文件加载，其次从系统环境变量读取。
"""

import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# 项目根目录
PROJECT_ROOT: Path = Path(__file__).resolve().parent

# 加载 .env 文件（如果存在）
_env_path: Path = PROJECT_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

# ── Semantic Scholar ──────────────────────────────────────────────
SEMANTIC_SCHOLAR_KEY: str | None = os.getenv("SEMANTIC_SCHOLAR_KEY")
S2_BASE_URL: str = "https://api.semanticscholar.org/graph/v1"

# ── Zotero ────────────────────────────────────────────────────────
ZOTERO_API_KEY: str | None = os.getenv("ZOTERO_API_KEY")
ZOTERO_USER_ID: str | None = os.getenv("ZOTERO_USER_ID")
ZOTERO_COLLECTION_KEY: str | None = os.getenv("ZOTERO_COLLECTION_KEY")
ZOTERO_COLLECTION_NAME: str = os.getenv("ZOTERO_COLLECTION_NAME", "AI Pricing - Game Theory")
ZOTERO_BASE_URL: str = "https://api.zotero.org"

# ── 年份范围（自动取当前年份） ────────────────────────────────────
_CURRENT_YEAR: int = datetime.now().year

# 近期论文检索范围
YEAR_RANGE_RECENT: str = f"2025-{_CURRENT_YEAR}"
# 经典文献检索范围（不限年份）
YEAR_RANGE_CLASSIC: str = ""  # 空字符串表示不限制年份

# ── 爬取策略 ────────────────────────────────────────────────────
# 近期顶刊关键词（2025+）
SEARCH_QUERIES_RECENT: list[str] = [
    "AI product pricing game theory",
    "algorithmic pricing competition reinforcement learning",
    "data-driven pricing strategic interaction",
    "machine learning pricing oligopoly",
    "dynamic pricing multi-agent reinforcement learning",
    "AI pricing mechanism design",
    "algorithmic collusion pricing",
    "LLM pricing strategy",
    "computational pricing strategy AI",
]

# 经典文献关键词（不限年份，后续用引用数+顶刊双重过滤）
SEARCH_QUERIES_CLASSIC: list[str] = [
    "algorithmic game theory pricing",
    "dynamic pricing competition",
    "price competition reinforcement learning",
    "algorithmic pricing strategy",
]

# ── 顶刊/顶会白名单 ─────────────────────────────────────────────
# 匹配 venue、journal.name、publicationVenue.name（不区分大小写）
TOP_VENUES: set[str] = {
    # Economics / Management 顶刊
    "american economic review",
    "aer",
    "econometrica",
    "quarterly journal of economics",
    "qje",
    "review of economic studies",
    "restud",
    "journal of political economy",
    "review of economic perspectives",
    "management science",
    "operations research",
    "marketing science",
    "journal of economic theory",
    "games and economic behavior",
    "the economic journal",
    "rand journal of economics",
    "journal of finance",
    "journal of financial economics",
    "review of financial studies",
    "manufacturing & service operations management",
    "msom",
    "production and operations management",
    "pom",
    "information systems research",
    "mis quarterly",
    "journal of marketing research",
    "journal of marketing",
    "journal of consumer research",
    "informs journal on computing",
    "mathematics of operations research",
    "naval research logistics",
    "economic theory",
    "journal of the european economic association",
    # CS/AI 顶会
    "neurips",
    "nips",
    "advances in neural information",
    "icml",
    "international conference on machine learning",
    "iclr",
    "international conference on learning representations",
    "aaai",
    "ijcai",
    "international joint conference on artificial intelligence",
    "aamas",
    "acm ec",
    "acm conference on economics and computation",
    "www",
    "international world wide web",
    "kdd",
    "sigkdd",
    "icis",
    # CS/AI 顶刊
    "journal of machine learning research",
    "jmlr",
    "machine learning",
    "artificial intelligence",
    "journal of artificial intelligence research",
    "ieee transactions on pattern analysis",
    "ieee transactions on neural networks",
    "journal of the acm",
    "acm transactions on",
    "ieee transactions on computers",
    "acm computing surveys",
}

# 筛选参数
MAX_PAPERS_PER_QUERY: int = 20  # 每组关键词最多抓取论文数
MAX_TOTAL_RECENT: int = 30  # 近期通道总上限（去重+筛选前）
MAX_TOTAL_CLASSIC: int = 20  # 经典通道总上限（去重+筛选前）
MAX_FINAL_PAPERS: int = 10  # 最终入库上限（按引用数排序取 Top N）
MIN_CITATIONS_RECENT: int = 0  # 近期论文不限引用数
MIN_CITATIONS_CLASSIC: int = 50  # 经典文献至少 50 引用
REQUEST_DELAY_SECONDS: float = 1.1  # 请求间隔，遵守速率限制

# ── 数据存储 ──────────────────────────────────────────────────────
DATA_DIR: Path = PROJECT_ROOT / "data"
PAPER_CACHE_FILE: Path = DATA_DIR / "paper_cache.json"

# 确保 data 目录存在
DATA_DIR.mkdir(exist_ok=True)
