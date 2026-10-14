"""
AGI 零样本泛化系统 - 新市场自适应

实现无需训练即可适应新环境：
- 市场状态类比：将新市场映射到已知状态
- 特征对齐：自动对齐不同市场的特征空间
- 快速适应：少量样本快速微调
- 异常检测：识别全新市场模式
- 置信度校准：新环境下的不确定性估计
"""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
MEMORY = ROOT / "memory" / "agi"
MEMORY.mkdir(parents=True, exist_ok=True)


@dataclass
class MarketProfile:
    symbol: str
    volatility: float
    trend_strength: float
    volume_profile: str
    regime: str
    feature_vector: np.ndarray
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AdaptationResult:
    source_market: str
    target_market: str
    similarity: float
    adapted_params: dict[str, float]
    confidence: float
    warnings: list[str]
    timestamp: datetime = field(default_factory=datetime.now)


class ZeroShotAdapter:
    """零样本泛化系统

    核心能力：
    1. 市场类比 - 找到最相似的历史市场状态
    2. 特征对齐 - 自动对齐不同市场的特征分布
    3. 快速适应 - 少量样本在线微调
    4. 异常检测 - 识别全新未知模式
    5. 置信度校准 - 新环境下的不确定性量化
    """

    SIMILARITY_THRESHOLD = 0.6
    ADAPTATION_WINDOW = 50
    MIN_SAMPLES_FOR_ADAPT = 20

    def __init__(self):
        self.known_markets: dict[str, list[MarketProfile]] = defaultdict(list)
        self.adaptation_history: list[AdaptationResult] = []
        self.anomaly_thresholds: dict[str, float] = {}
        self.confidence_calibration: dict[str, float] = {}

    def adapt_to_new_market(self, target_symbol: str, target_data: dict,
                           source_symbols: list[str] = None) -> AdaptationResult:
        """零样本适应新市场"""
        target_profile = self._extract_profile(target_symbol, target_data)

        source_symbols = source_symbols or list(self.known_markets.keys())
        if not source_symbols:
            return AdaptationResult(
                source_market="unknown", target_market=target_symbol,
                similarity=0, adapted_params={}, confidence=0.1,
                warnings=["无已知市场可参考，使用默认参数"],
            )

        best_match = None
        best_similarity = 0
        for source_symbol in source_symbols:
            for profile in self.known_markets.get(source_symbol, []):
                similarity = self._cosine_similarity(target_profile.feature_vector, profile.feature_vector)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = profile

        if best_match is None or best_similarity < self.SIMILARITY_THRESHOLD:
            warnings = [f"最相似市场 {best_match.symbol if best_match else 'N/A'} 相似度仅 {best_similarity:.2f}"]
            return AdaptationResult(
                source_market=best_match.symbol if best_match else "unknown",
                target_market=target_symbol, similarity=best_similarity,
                adapted_params=self._default_params(target_profile),
                confidence=best_similarity * 0.5, warnings=warnings,
            )

        adapted_params = self._transfer_params(best_match, target_profile, best_similarity)
        confidence = best_similarity * 0.8 + 0.2 * (1 if best_match.regime == target_profile.regime else 0.5)

        result = AdaptationResult(
            source_market=best_match.symbol, target_market=target_symbol,
            similarity=best_similarity, adapted_params=adapted_params,
            confidence=confidence, warnings=[],
        )
        self.adaptation_history.append(result)
        self._save()
        logger.info(f"零样本适应: {target_symbol} ← {best_match.symbol} (相似度: {best_similarity:.2f})")
        return result

    def register_market(self, symbol: str, data: dict):
        """注册已知市场"""
        profile = self._extract_profile(symbol, data)
        self.known_markets[symbol].append(profile)

        if len(self.known_markets[symbol]) > 100:
            self.known_markets[symbol] = self.known_markets[symbol][-50:]

    def detect_anomaly(self, symbol: str, data: dict) -> dict:
        """检测异常市场模式"""
        profile = self._extract_profile(symbol, data)

        if symbol not in self.known_markets or not self.known_markets[symbol]:
            return {"is_anomaly": True, "reason": "新市场，无历史数据", "confidence": 0.3}

        historical_vectors = np.array([p.feature_vector for p in self.known_markets[symbol][-20:]])
        mean_vector = np.mean(historical_vectors, axis=0)
        std_vector = np.std(historical_vectors, axis=0) + 1e-8

        z_scores = np.abs((profile.feature_vector - mean_vector) / std_vector)
        max_z = np.max(z_scores)
        anomaly_features = [f"特征{i}" for i, z in enumerate(z_scores) if z > 3]

        is_anomaly = max_z > 3 or len(anomaly_features) > 2

        return {
            "is_anomaly": is_anomaly,
            "max_z_score": float(max_z),
            "anomaly_features": anomaly_features,
            "confidence": min(0.9, max_z / 5),
            "recommendation": "建议观望，等待市场恢复正常" if is_anomaly else "市场状态正常",
        }

    def quick_adapt(self, symbol: str, recent_data: dict,
                   n_samples: int = None) -> dict[str, float]:
        """快速适应 - 少量样本在线微调"""
        n_samples = n_samples or min(self.ADAPTATION_WINDOW, len(recent_data.get('close', [])))

        if n_samples < self.MIN_SAMPLES_FOR_ADAPT:
            return {"status": "insufficient_data", "needed": self.MIN_SAMPLES_FOR_ADAPT}

        close = recent_data.get('close', [])[-n_samples:]
        returns = np.diff(close) / close[:-1]

        adapted = {
            "volatility": float(np.std(returns) * np.sqrt(252)),
            "trend": float(np.mean(returns) * 252),
            "max_drawdown_estimate": float(np.min(np.cumprod(1 + returns)) - 1),
            "optimal_stop_loss": float(np.std(returns) * 2),
            "optimal_position_size": float(0.2 / max(1, np.std(returns) * 50)),
        }

        return {"status": "adapted", "params": adapted, "n_samples": n_samples}

    def calibrate_confidence(self, predictions: list[float],
                            actuals: list[float]) -> dict:
        """置信度校准"""
        if len(predictions) < 10:
            return {"status": "insufficient_data"}

        errors = np.abs(np.array(predictions) - np.array(actuals))
        mean_error = np.mean(errors)

        calibration_factor = 1.0 / (1.0 + mean_error)
        self.confidence_calibration["global"] = calibration_factor

        return {
            "mean_error": float(mean_error),
            "calibration_factor": float(calibration_factor),
            "calibrated_confidence": f"原始置信度 × {calibration_factor:.2f}",
        }

    def _extract_profile(self, symbol: str, data: dict) -> MarketProfile:
        """提取市场特征"""
        close = data.get('close', [])
        volume = data.get('volume', [])

        if len(close) < 20:
            return MarketProfile(symbol=symbol, volatility=0, trend_strength=0,
                                volume_profile="unknown", regime="unknown",
                                feature_vector=np.zeros(16))

        returns = np.diff(close[-50:]) / close[-51:-1] if len(close) >= 51 else np.diff(close) / close[:-1]
        volatility = float(np.std(returns) * np.sqrt(252))
        trend_strength = float(np.mean(returns) * 252)

        vol_ma = np.mean(volume[-20:]) if len(volume) >= 20 else 1
        vol_current = volume[-1] if len(volume) > 0 else 1
        if vol_current > vol_ma * 2:
            volume_profile = "high"
        elif vol_current < vol_ma * 0.5:
            volume_profile = "low"
        else:
            volume_profile = "normal"

        if trend_strength > 0.3:
            regime = "bull"
        elif trend_strength < -0.3:
            regime = "bear"
        elif volatility > 0.5:
            regime = "volatile"
        else:
            regime = "sideways"

        feature_vector = np.zeros(16)
        feature_vector[0] = volatility
        feature_vector[1] = trend_strength
        feature_vector[2] = 1 if volume_profile == "high" else (0 if volume_profile == "normal" else -1)
        feature_vector[3] = float(np.mean(close[-5:]) / np.mean(close[-20:]) - 1) if len(close) >= 20 else 0
        feature_vector[4] = float(np.max(close[-20:]) / np.min(close[-20:]) - 1) if len(close) >= 20 else 0
        feature_vector[5] = float(np.corrcoef(volume[-20:], close[-20:])[0, 1]) if len(volume) >= 20 else 0
        feature_vector[6] = float(sum(1 for r in returns[-20:] if r > 0) / max(len(returns[-20:]), 1))
        feature_vector[7] = float(np.sum(returns[-5:]) / (abs(np.sum(returns[-20:])) + 1e-8))

        return MarketProfile(
            symbol=symbol, volatility=volatility, trend_strength=trend_strength,
            volume_profile=volume_profile, regime=regime, feature_vector=feature_vector,
        )

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def _transfer_params(self, source: MarketProfile, target: MarketProfile,
                        similarity: float) -> dict[str, float]:
        """迁移参数"""
        vol_ratio = target.volatility / max(source.volatility, 0.01)
        return {
            "stop_loss": round(0.05 * vol_ratio * similarity, 4),
            "take_profit": round(0.15 * vol_ratio * similarity, 4),
            "position_size": round(0.2 / max(vol_ratio, 0.5) * similarity, 4),
            "confidence_multiplier": round(similarity, 2),
        }

    def _default_params(self, profile: MarketProfile) -> dict[str, float]:
        return {
            "stop_loss": 0.03, "take_profit": 0.10,
            "position_size": 0.1, "confidence_multiplier": 0.3,
        }

    def _save(self):
        data = {
            "known_markets": len(self.known_markets),
            "total_adaptations": len(self.adaptation_history),
            "recent_adaptations": [
                {"target": a.target_market, "source": a.source_market,
                 "similarity": a.similarity, "confidence": a.confidence}
                for a in self.adaptation_history[-10:]
            ],
            "last_updated": datetime.now().isoformat(),
        }
        (MEMORY / "zero_shot_adapter.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def get_status(self) -> dict:
        return {
            "known_markets": len(self.known_markets),
            "total_adaptations": len(self.adaptation_history),
            "avg_similarity": np.mean([a.similarity for a in self.adaptation_history]) if self.adaptation_history else 0,
            "calibration": self.confidence_calibration.get("global", 1.0),
        }
