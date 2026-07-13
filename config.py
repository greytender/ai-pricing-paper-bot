"""
全局配置模块 —— 所有密钥和环境变量统一从此处读取，禁止硬编码。
优先从 .env 文件加载，其次从系统环境变量读取。
"""

import os
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

# ── 爬取策略 ────────────────────────────────────────────────────
# 多组关键词覆盖研究主题的各个维度
SEARCH_QUERIES: list[str] = [
    "AI product pricing game theory",
    "data-driven pricing strategic interaction",
    "algorithmic pricing competition AI",
    "machine learning pricing oligopoly",
    "dynamic pricing reinforcement learning competition",
    "AI pricing mechanism design",
    "data-driven strategic pricing",
    "artificial intelligence pricing game",
    "algorithmic game theory pricing",
    "computational pricing strategy",
]

# 筛选参数
YEAR_RANGE: str = "2018-2026"
MAX_PAPERS_PER_QUERY: int = 100  # 每组关键词最多抓取论文数
MIN_CITATIONS: int = 0  # 最低引用数（0 表示不过滤）
REQUEST_DELAY_SECONDS: float = 1.1  # 请求间隔，遵守速率限制

# ── 数据存储 ──────────────────────────────────────────────────────
DATA_DIR: Path = PROJECT_ROOT / "data"
PAPER_CACHE_FILE: Path = DATA_DIR / "paper_cache.json"

# 确保 data 目录存在
DATA_DIR.mkdir(exist_ok=True)
