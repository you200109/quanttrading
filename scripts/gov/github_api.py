"""GitHub API 访问层（REST，统一鉴权/重试/配额可见）

模块名必须是 github_api 而不是 http：scripts/gov 会被放进 sys.path[0]（
以 `python scripts/gov/metrics.py` 运行时就是），叫 http.py 会遮蔽标准库
http 包，导致 urllib.request 里的 `import http.client` 直接 ModuleNotFoundError。
设计要点（都是被 CI 教育出来的）：
1. **凭据缺失必须显式抛出** NoCredentials，由调用方决定跳过还是失败——
   不能像旧 `|| echo` 那样把"没配置"伪装成"没问题"；
2. **重试只对可恢复错误生效**：429 / 5xx / 网络异常才退避重试，其余 4xx
   直接失败（403 且配额耗尽时给出 x-ratelimit-reset 时刻，让调用方能报告
   "几点几分恢复"，而不是一句干巴巴的 403）；
3. **配额必须可读**：每次请求把 x-ratelimit-remaining 带回 meta，监控层据此
   决定是否提前收手，而不是撞到 403 才知道配额没了；
4. 单一注入点 `_urlopen` / `_SLEEP`：测试替换这两个即可完全离线且不等退避。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT = 20
DEFAULT_RETRIES = 3
MAX_BACKOFF = 8

USER_AGENT = "quanttrading-gov"


class NoCredentials(Exception):
    """没有 GITHUB_TOKEN / GH_TOKEN"""


class GitHubError(Exception):
    """API 返回不可恢复的错误"""

    def __init__(self, status: int, message: str, url: str = ""):
        super().__init__(f"HTTP {status} {url}: {message}")
        self.status = status
        self.url = url


def token_from_env(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    value = (env.get("GITHUB_TOKEN") or env.get("GH_TOKEN") or "").strip()
    if not value:
        raise NoCredentials("缺少 GITHUB_TOKEN / GH_TOKEN")
    return value


def _urlopen(req: urllib.request.Request, timeout: int):
    """唯一的网络出口。测试里替换这一个函数即可完全离线"""
    return urllib.request.urlopen(req, timeout=timeout)


_SLEEP = time.sleep


def _as_int(value: Any) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def request(path: str, params: dict | None = None, *, method: str = "GET",
            body: dict | None = None, token: str | None = None,
            timeout: int = DEFAULT_TIMEOUT, retries: int = DEFAULT_RETRIES,
            env: dict | None = None) -> tuple[Any, dict]:
    """发起一次 GitHub API 请求，返回 (payload, meta)

    meta = {"status", "rate_remaining", "rate_reset", "url"}
    """
    if token is None:
        token = token_from_env(env)

    url = path if path.startswith("http") else API_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})

    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        if attempt:
            _SLEEP(min(2 ** (attempt - 1), MAX_BACKOFF))
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with _urlopen(req, timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                meta = {
                    "status": resp.status,
                    "rate_remaining": _as_int(resp.headers.get("x-ratelimit-remaining")),
                    "rate_reset": _as_int(resp.headers.get("x-ratelimit-reset")),
                    "url": url,
                }
                payload = json.loads(raw) if raw.strip() else None
                return payload, meta
        except urllib.error.HTTPError as exc:
            status = exc.code
            retry_after = _as_int(exc.headers.get("retry-after")) if exc.headers else None
            try:
                snippet = exc.read().decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001 - body 读不出来不影响错误处理
                snippet = ""
            retryable = status == 429 or status >= 500
            if retryable and attempt < retries:
                last_error = exc
                if retry_after:
                    _SLEEP(min(retry_after, MAX_BACKOFF))
                continue
            if status == 403 and meta_rate_hint(exc):
                remaining, reset = meta_rate_hint(exc)  # type: ignore[misc]
                raise GitHubError(
                    status,
                    f"配额耗尽或拒绝访问（remaining={remaining}, reset={reset}）{snippet}",
                    url,
                ) from exc
            raise GitHubError(status, snippet or f"HTTP {status}", url) from exc
        except Exception as exc:  # noqa: BLE001 - 网络 layer 异常种类不可枚举
            last_error = exc
            if attempt < retries:
                continue
            raise GitHubError(0, f"网络请求失败: {exc}", url) from exc

    # 走到这里说明所有尝试都落在 retryable 分支却没返回（理论上不可达）
    raise GitHubError(0, f"重试后仍失败: {last_error}", url)


def meta_rate_hint(exc: urllib.error.HTTPError) -> tuple[int | None, int | None] | None:
    """403 时提取配额提示；非配额类 403 返回 None"""
    if exc.code != 403 or not exc.headers:
        return None
    remaining = _as_int(exc.headers.get("x-ratelimit-remaining"))
    reset = _as_int(exc.headers.get("x-ratelimit-reset"))
    if remaining == 0:
        return remaining, reset
    return None


def rate_limit(token: str | None = None, env: dict | None = None) -> dict:
    """查询当前令牌配额（core/search 两个桶）"""
    payload, _meta = request("/rate_limit", token=token, env=env)
    resources = (payload or {}).get("resources", {})
    out: dict[str, dict] = {}
    for bucket in ("core", "search"):
        item = resources.get(bucket) or {}
        out[bucket] = {
            "limit": item.get("limit"),
            "remaining": item.get("remaining"),
            "reset": item.get("reset"),
        }
    return out
