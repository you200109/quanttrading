"""
GitHub 定时检索器 - 按小时搜索欧易相关工具、项目与代码库

功能：
1. 每小时自动搜索 GitHub 上与 OKX/加密货币交易相关的项目
2. 分析代码质量、活跃度和与当前项目的相关性
3. 产出对比报告，判断是否需要升级或迭代
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('github_scanner.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class GitHubScanner:
    """GitHub 定时检索器"""

    # 搜索关键词组（每轮随机选取，覆盖不同维度）
    SEARCH_QUERIES = [
        "okx trading bot python",
        "crypto quantitative trading",
        "okx api websocket market data",
        "crypto backtesting framework",
        "okx grid trading strategy",
        "crypto arbitrage bot",
        "technical indicators trading system",
        "reinforcement learning crypto trading",
        "okx market maker",
        "crypto portfolio optimization",
    ]

    def __init__(self, token: str | None = None, output_dir: str = "gh_repos"):
        self.token = token or os.getenv("GITHUB_TOKEN", "")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "SelfEvolve-Trading-Scanner/1.0"
        })
        if self.token:
            self.session.headers["Authorization"] = f"token {self.token}"

    def search(self, query: str, per_page: int = 10) -> list[dict]:
        """搜索 GitHub 仓库"""
        url = "https://api.github.com/search/repositories"
        params = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": per_page
        }
        try:
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("items", [])
            elif resp.status_code == 403:
                logger.warning("GitHub API 速率限制，等待重试...")
                time.sleep(60)
                return []
            else:
                logger.error(f"搜索失败: {resp.status_code} {resp.text[:200]}")
                return []
        except Exception as e:
            logger.error(f"搜索异常: {e}")
            return []

    def analyze_repo(self, repo: dict) -> dict:
        """分析单个仓库"""
        return {
            "full_name": repo.get("full_name"),
            "stars": repo.get("stargazers_count", 0),
            "forks": repo.get("forks_count", 0),
            "language": repo.get("language"),
            "description": repo.get("description", ""),
            "url": repo.get("html_url"),
            "updated_at": repo.get("updated_at"),
            "created_at": repo.get("created_at"),
            "topics": repo.get("topics", []),
            "open_issues": repo.get("open_issues_count", 0),
            "score": self._calc_score(repo),
        }

    def _calc_score(self, repo: dict) -> float:
        """计算仓库相关性评分"""
        score = 0.0
        stars = repo.get("stargazers_count", 0)
        if stars > 1000:
            score += 3.0
        elif stars > 100:
            score += 2.0
        elif stars > 10:
            score += 1.0

        desc = (repo.get("description") or "").lower()
        keywords = ["okx", "crypto", "trading", "quant", "strategy", "backtest"]
        score += sum(0.5 for k in keywords if k in desc)

        topics = repo.get("topics", [])
        score += sum(0.3 for t in topics if any(k in t for k in keywords))

        return round(score, 2)

    def compare_with_project(self, repos: list[dict]) -> dict:
        """与当前项目对比，判断是否需要升级"""
        report = {
            "scan_time": datetime.now().isoformat(),
            "total_found": len(repos),
            "high_priority": [],
            "worth_investigating": [],
            "recommendations": []
        }

        for repo in repos:
            if repo["score"] >= 3.0:
                report["high_priority"].append(repo)
                report["recommendations"].append(
                    f"[高优先级] {repo['full_name']} (⭐{repo['stars']}) - {repo['description'][:100]}"
                )
            elif repo["score"] >= 1.5:
                report["worth_investigating"].append(repo)

        if not report["recommendations"]:
            report["recommendations"].append("本轮未发现需要立即关注的项目")

        return report

    def run_once(self) -> dict:
        """执行一轮检索"""
        import random
        query = random.choice(self.SEARCH_QUERIES)
        logger.info(f"检索关键词: {query}")

        repos_raw = self.search(query, per_page=10)
        repos = [self.analyze_repo(r) for r in repos_raw]
        repos.sort(key=lambda x: x["score"], reverse=True)

        report = self.compare_with_project(repos)

        # 保存报告
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = self.output_dir / f"scan_{timestamp}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"报告已保存: {report_file}")
        for rec in report["recommendations"]:
            logger.info(f"  {rec}")

        return report

    def run_loop(self, interval_seconds: int = 3600):
        """循环运行，每隔指定秒数执行一轮"""
        logger.info(f"GitHub 定时检索器已启动，间隔 {interval_seconds} 秒")
        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.error(f"本轮检索异常: {e}")
            logger.info(f"等待 {interval_seconds} 秒后执行下一轮...")
            time.sleep(interval_seconds)


if __name__ == "__main__":
    scanner = GitHubScanner()
    scanner.run_once()
