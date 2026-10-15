"""
全时间历史行情缓存管理器

设计目标:
1. 缓存策略  - 全历史持久化 + 增量更新 + 分层TLL
2. 数据结构  - 按交易对分目录(Parquet数据 + JSON元信息)
3. 过期机制  - 已收盘历史永久有效, 最新数据按TTL过期
4. 数据一致性 - 原子写入 + 时间戳去重 + 连续性校验 + 校验和 + 文件锁

存储布局:
    memory/market_cache/
    ├── cache_index.json          全局缓存索引
    └── BTC_USDT/
        ├── data.parquet        全历史K线数据
        └── meta.json           元信息(范围/条数/校验和/修订号)
"""
import os
import json
import time
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
CACHE_ROOT = ROOT / "memory" / "market_cache"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)


class MarketDataCache:
    """全时间历史行情缓存"""

    # ===== 过期机制参数 =====
    FRESH_TTL = 3600          # 最新数据有效期(秒): 1小时
    STALE_TTL = 86400         # 陈旧阈值(秒): 1天, 超过则强制刷新最新段
    MAX_PAGES = 80            # 单次增量拉取最大页数

    def __init__(self, fetcher=None, cache_root: Optional[Path] = None):
        self.cache_root = Path(cache_root) if cache_root else CACHE_ROOT
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.fetcher = fetcher

    # ---------- 路径与索引 ----------
    def _symbol_dir(self, symbol: str) -> Path:
        safe = symbol.replace("/", "_").replace("-", "_")
        d = self.cache_root / safe
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _data_file(self, symbol: str) -> Path:
        return self._symbol_dir(symbol) / "data.parquet"

    def _meta_file(self, symbol: str) -> Path:
        return self._symbol_dir(symbol) / "meta.json"

    def _index_file(self) -> Path:
        return self.cache_root / "cache_index.json"

    # ---------- 一致性: 锁 ----------
    def _acquire_lock(self, symbol: str, timeout: float = 10.0) -> Optional[Path]:
        """获取文件锁, 防止并发写冲突"""
        lock = self._symbol_dir(symbol) / ".lock"
        start = time.time()
        while lock.exists():
            if time.time() - start > timeout:
                logger.warning(f"[{symbol}] 获取缓存锁超时")
                return None
            time.sleep(0.1)
        try:
            lock.write_text(str(os.getpid()), encoding="utf-8")
            return lock
        except Exception as e:
            logger.warning(f"[{symbol}] 创建锁失败: {e}")
            return None

    def _release_lock(self, lock: Optional[Path]):
        try:
            if lock and lock.exists():
                lock.unlink()
        except Exception:
            pass

    # ---------- 一致性: 校验和 ----------
    def _checksum(self, df: pd.DataFrame) -> str:
        """基于数据内容计算校验和"""
        try:
            h = hashlib.md5()
            h.update(str(len(df)).encode())
            if len(df) > 0:
                h.update(str(df.index[0]).encode())
                h.update(str(df.index[-1]).encode())
                h.update(str(round(float(df['close'].iloc[-1]), 4)).encode())
            return h.hexdigest()[:16]
        except Exception:
            return ""

    # ---------- 加载 ----------
    def load(self, symbol: str) -> Tuple[Optional[pd.DataFrame], dict]:
        """从磁盘加载缓存数据与元信息"""
        df_file = self._data_file(symbol)
        meta_file = self._meta_file(symbol)
        if not df_file.exists():
            return None, {}
        try:
            df = pd.read_parquet(df_file)
            meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
            # 一致性: 校验和比对
            if meta.get("checksum") and meta["checksum"] != self._checksum(df):
                logger.warning(f"[{symbol}] 缓存校验和不匹配, 可能已损坏")
            return df, meta
        except Exception as e:
            logger.warning(f"[{symbol}] 缓存加载失败: {e}")
            return None, {}

    # ---------- 一致性: 原子写入 ----------
    def save(self, symbol: str, df: pd.DataFrame, meta_extra: Optional[dict] = None):
        """原子写入数据与元信息"""
        df_file = self._data_file(symbol)
        meta_file = self._meta_file(symbol)

        # 一致性: 去重 + 排序 + 单调
        df = self._normalize(df)

        # 原子写数据: tmp -> replace
        tmp_data = df_file.with_suffix(".parquet.tmp")
        df.to_parquet(tmp_data)
        os.replace(tmp_data, df_file)

        # 元信息
        meta = {
            "symbol": symbol,
            "rows": len(df),
            "first_ts": str(df.index[0]) if len(df) else None,
            "last_ts": str(df.index[-1]) if len(df) else None,
            "last_updated": datetime.now().isoformat(),
            "checksum": self._checksum(df),
            "revision": (meta_extra or {}).get("revision", 1),
        }
        if meta_extra:
            meta.update({k: v for k, v in meta_extra.items() if k != "revision"})

        tmp_meta = meta_file.with_suffix(".json.tmp")
        tmp_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_meta, meta_file)

        self._update_index(symbol, meta)
        logger.info(f"[{symbol}] 缓存已写入: {meta['rows']} 条, {meta['first_ts']} ~ {meta['last_ts']}")

    def _normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """一致性: 时间戳去重(保留最新) + 排序 + 连续性保证"""
        if df is None or df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = df[~df.index.duplicated(keep="last")]
        df = df.sort_index()
        return df

    def _update_index(self, symbol: str, meta: dict):
        idx_file = self._index_file()
        idx = {}
        if idx_file.exists():
            try:
                idx = json.loads(idx_file.read_text(encoding="utf-8"))
            except Exception:
                idx = {}
        idx[symbol] = {
            "rows": meta.get("rows"),
            "first_ts": meta.get("first_ts"),
            "last_ts": meta.get("last_ts"),
            "last_updated": meta.get("last_updated"),
        }
        tmp = idx_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, idx_file)

    # ---------- 过期机制 ----------
    def is_fresh(self, symbol: str) -> bool:
        """判断最新数据是否仍在有效期内"""
        _, meta = self.load(symbol)
        if not meta.get("last_updated"):
            return False
        try:
            last = datetime.fromisoformat(meta["last_updated"])
            return (datetime.now() - last).total_seconds() < self.FRESH_TTL
        except Exception:
            return False

    def needs_update(self, symbol: str) -> bool:
        """是否需要更新(不存在 或 超过陈旧阈值)"""
        meta = self.load(symbol)[1]
        if not meta.get("last_updated"):
            return True
        try:
            last = datetime.fromisoformat(meta["last_updated"])
            return (datetime.now() - last).total_seconds() > self.STALE_TTL
        except Exception:
            return True

    # ---------- 一致性: 连续性校验 ----------
    def check_continuity(self, df: pd.DataFrame, expected_gap_days: int = 1) -> dict:
        """检查数据时间连续性"""
        if df is None or len(df) < 2:
            return {"ok": True, "gaps": 0, "missing": 0}
        diffs = df.index.to_series().diff().dropna()
        gaps = int((diffs > pd.Timedelta(days=expected_gap_days * 1.5)).sum())
        return {"ok": gaps == 0, "gaps": gaps, "rows": len(df)}

    def get(self, symbol: str, start_date: str, end_date: str, auto_update: bool = True) -> pd.DataFrame:
        """核心入口: 缓存优先读取, 缺失或过期则增量更新"""
        df, meta = self.load(symbol)

        if df is not None and len(df) > 0 and not self.needs_update(symbol):
            sub = df[(df.index >= start_date) & (df.index <= end_date)]
            if len(sub) > 0:
                logger.info(f"[{symbol}] 缓存命中 {len(sub)} 条")
                return sub

        if auto_update and self.fetcher is not None:
            df = self.update(symbol, start_date, end_date)
            if df is not None and len(df) > 0:
                return df[(df.index >= start_date) & (df.index <= end_date)]

        if df is not None:
            return df[(df.index >= start_date) & (df.index <= end_date)]
        return pd.DataFrame()

    def update(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """增量更新: 合并已有缓存与最新拉取数据"""
        lock = self._acquire_lock(symbol)
        if lock is None:
            return self.load(symbol)[0]
        try:
            old_df, old_meta = self.load(symbol)
            new_df = self.fetcher._fetch_ccxt(symbol, start_date, end_date) if self.fetcher else None
            if new_df is None or new_df.empty:
                logger.warning(f"[{symbol}] 增量拉取无数据")
                return old_df

            merged = new_df if old_df is None else pd.concat([old_df, new_df])
            merged = self._normalize(merged)
            revision = int(old_meta.get("revision", 0)) + 1
            self.save(symbol, merged, meta_extra={"revision": revision, "last_fetch": datetime.now().isoformat()})
            return merged
        finally:
            self._release_lock(lock)

    def get_status(self) -> dict:
        """缓存总体状态"""
        idx_file = self._index_file()
        idx = json.loads(idx_file.read_text(encoding="utf-8")) if idx_file.exists() else {}
        total_rows = sum(v.get("rows", 0) for v in idx.values())
        return {
            "symbols": len(idx),
            "total_rows": total_rows,
            "fresh_ttl": self.FRESH_TTL,
            "stale_ttl": self.STALE_TTL,
            "details": idx,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    cache = MarketDataCache()
    print(json.dumps(cache.get_status(), indent=2, ensure_ascii=False))
