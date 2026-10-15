"""P3a 回归测试：数据契约路径断言（防读写分裂复发）

背景：learning_engine.py 与 unified_evolve.py 曾用 Path(__file__).parent
（指向 strategy/）推导 NEXUS，导致 memory/nexus 契约文件读写分裂到
strategy/memory/nexus。2026-10-16 P3a 修复为 parent.parent 并迁移数据。
本测试锁定修复后的路径契约。
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VC_ROOT = REPO_ROOT / 'vigilant-couscous'
CONTRACT_NEXUS = (VC_ROOT / 'memory' / 'nexus').resolve()

sys.path.insert(0, str(VC_ROOT))
sys.path.insert(0, str(REPO_ROOT))


def test_learning_engine_nexus_points_to_contract_location():
    from strategy.learning_engine import NEXUS
    assert NEXUS.resolve() == CONTRACT_NEXUS, (
        f'LearningEngine.NEXUS={NEXUS} 偏离契约位置 {CONTRACT_NEXUS}')


def test_unified_evolve_nexus_points_to_contract_location():
    from strategy import unified_evolve
    assert unified_evolve.NEXUS.resolve() == CONTRACT_NEXUS, (
        f'unified_evolve.NEXUS={unified_evolve.NEXUS} 偏离契约位置 {CONTRACT_NEXUS}')


def test_learning_engine_persists_under_nexus(tmp_path, monkeypatch):
    """LearningEngine 持久化必须落在 NEXUS 常量所指目录（monkeypatch 隔离）"""
    from strategy import learning_engine
    monkeypatch.setattr(learning_engine, 'NEXUS', tmp_path)
    engine = learning_engine.LearningEngine(token='')
    engine._save()
    assert (tmp_path / 'learning_history.json').exists()
    assert (tmp_path / 'discovery_history.json').exists()


def test_no_strategy_memory_directory():
    """错位置产物目录不得复活"""
    assert not (VC_ROOT / 'strategy' / 'memory').exists(), (
        'strategy/memory/ 再现——ROOT 路径 bug 可能复发')
