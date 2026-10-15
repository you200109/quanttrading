"""
agi/eternal_evolver 真实系统状态度量测试（P3b）

覆盖 2026-10-16 P3b 重构：
- _system_state：全部指标来自真实文件（策略库/内化/语义记忆/归档/发现数）
- _measure_improvement：加权归一化增量；无增量 = 0；确定性（无随机）
- _evolve_strategy：委托 LearningEngine.integrate_params（stub，禁网）
- _evolve_risk：审计修复缺失止损/止盈的库条目（真实写回）
- _evolve_cognition：委托 MemorySystem.consolidate（stub）
- _evolve_generic：目标去重 + 归档已完成目标
- _random_mutation：适用度静态化（同类型突变适用度相同）
- _last_system_state：持久化 + _self_assess 跨周期增长
- 回归防护：random.uniform 假度量已彻底移除（调用即失败）
"""
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def isolated_evolver(tmp_path, monkeypatch):
    """把 eternal_evolver 的所有持久化目标隔离到 tmp_path"""
    from agi import eternal_evolver as ee
    mem = tmp_path / "memory" / "agi"
    mem.mkdir(parents=True)
    monkeypatch.setattr(ee, "MEMORY", mem)
    monkeypatch.setattr(ee, "ETERNAL_LOG", mem / "eternal_evolution.jsonl")
    monkeypatch.setattr(ee, "STRATEGY_LIB", tmp_path / "nexus" / "gh_strategy_library.json")
    monkeypatch.setattr(ee, "ITERATIONS_DIR", tmp_path / "iterations")
    monkeypatch.setattr(ee, "SEMANTIC_FILE", mem / "memory_system.json")
    monkeypatch.setattr(ee, "GOAL_ARCHIVE", mem / "goal_archive.json")
    evolver = ee.EternalEvolver()
    # 注意：方法内部引用的是模块级常量；此处把 patched 后的路径镜像到实例上，
    # 仅供测试代码便利引用（不代表方法通过 self 访问）
    for attr in ("MEMORY", "ETERNAL_LOG", "STRATEGY_LIB", "ITERATIONS_DIR",
                 "SEMANTIC_FILE", "GOAL_ARCHIVE"):
        setattr(evolver, attr, getattr(ee, attr))
    return evolver


def _write_lib(evolver, strategies):
    evolver.STRATEGY_LIB.parent.mkdir(parents=True, exist_ok=True)
    evolver.STRATEGY_LIB.write_text(
        json.dumps({"strategies": strategies}), encoding="utf-8")


def _make_goal(domain="strategy_creation"):
    from agi.eternal_evolver import EvolutionGoal
    return EvolutionGoal(id="g1", description="测试目标", domain=domain,
                         novelty_score=0.8, difficulty=0.5, potential_impact=0.7)


class TestSystemState:
    def test_all_metrics_from_real_files(self, isolated_evolver):
        ev = isolated_evolver
        _write_lib(ev, [
            {"name": "a", "stop_loss": 0.05, "take_profit": 0.15, "backtest_passed": True},
            {"name": "b", "stop_loss": 0.05},                       # 缺 take_profit
            {"name": "c", "backtest_passed": True},                 # 缺风控参数
        ])
        ev.ITERATIONS_DIR.mkdir(parents=True)
        (ev.ITERATIONS_DIR / "internalized_x.json").write_text("{}")
        (ev.ITERATIONS_DIR / "internalized_y.json").write_text("{}")
        ev.SEMANTIC_FILE.write_text(json.dumps({"semantic_count": 4}))
        ev.GOAL_ARCHIVE.write_text(json.dumps({"goals": [{"id": "z"}]}))
        ev.discoveries_count = 6

        state = ev._system_state()
        assert state == {
            "library_size": 3, "risk_covered": 1, "passed_strategies": 2,
            "internalized": 2, "semantic_memory": 4,
            "archived_goals": 1, "discoveries": 6,
        }

    def test_empty_state_is_zeros(self, isolated_evolver):
        state = isolated_evolver._system_state()
        assert state["library_size"] == 0
        assert state["passed_strategies"] == 0
        assert state["internalized"] == 0


class TestMeasureImprovement:
    def test_no_change_is_zero(self, isolated_evolver):
        ev = isolated_evolver
        state = ev._system_state()
        assert ev._measure_improvement(state, dict(state), "strategy_creation") == 0.0

    def test_weighted_growth(self, isolated_evolver):
        ev = isolated_evolver
        before = ev._system_state()
        after = dict(before)
        after["library_size"] = before["library_size"] + 3   # 满额归一化
        imp = ev._measure_improvement(before, after, "strategy_creation")
        # library_size 权重 0.35 × min(1, 3/3) = 0.35
        assert imp == pytest.approx(0.35)

    def test_regression_not_counted(self, isolated_evolver):
        ev = isolated_evolver
        before = ev._system_state()
        after = dict(before)
        after["library_size"] = before["library_size"] - 5
        assert ev._measure_improvement(before, after, "strategy_creation") == 0.0

    def test_deterministic_no_random(self, isolated_evolver):
        ev = isolated_evolver
        before = ev._system_state()
        after = dict(before)
        after["passed_strategies"] = before["passed_strategies"] + 2
        first = ev._measure_improvement(before, after, "risk_management")
        second = ev._measure_improvement(before, after, "risk_management")
        assert first == second  # 无随机成分


class TestEvolveActions:
    def test_strategy_delegates_to_integrate_params(self, isolated_evolver, monkeypatch):
        ev = isolated_evolver
        _write_lib(ev, [])
        calls = []

        class FakeLE:
            def __init__(self, token=""):
                pass

            def integrate_params(self):
                calls.append(1)
                _write_lib(ev, [{"name": "learned_x", "stop_loss": 0.05, "take_profit": 0.15}])
                return 1

        fake_mod = types.ModuleType("strategy.learning_engine")
        fake_mod.LearningEngine = FakeLE
        monkeypatch.setitem(sys.modules, "strategy.learning_engine", fake_mod)

        before = ev._system_state()
        ev._evolve_strategy(_make_goal("strategy_creation"))
        after = ev._system_state()

        assert calls == [1]
        assert after["library_size"] == before["library_size"] + 1
        assert after["risk_covered"] == before["risk_covered"] + 1
        imp = ev._measure_improvement(before, after, "strategy_creation")
        # library 0.35×1/3 + risk 0.15×1/3（_measure_improvement 输出保留 6 位）
        assert imp == round(0.35 / 3 + 0.15 / 3, 6)

    def test_risk_repairs_missing_params(self, isolated_evolver):
        ev = isolated_evolver
        _write_lib(ev, [
            {"name": "no_sl"},                      # 两个都缺
            {"name": "no_tp", "stop_loss": 0.04},   # 缺 take_profit
            {"name": "full", "stop_loss": 0.05, "take_profit": 0.15},
        ])
        before = ev._system_state()
        assert before["risk_covered"] == 1
        ev._evolve_risk(_make_goal("risk_management"))
        after = ev._system_state()
        assert after["risk_covered"] == 3  # 两条被修复
        imp = ev._measure_improvement(before, after, "risk_management")
        # risk_covered 0.45×2/3 + library 0 + passed 0 = 0.3
        assert imp == pytest.approx(0.3)

    def test_risk_repair_persisted_to_file(self, isolated_evolver):
        ev = isolated_evolver
        _write_lib(ev, [{"name": "x"}])
        ev._evolve_risk(_make_goal("risk_management"))
        lib = json.loads(ev.STRATEGY_LIB.read_text(encoding="utf-8"))
        assert lib["strategies"][0]["stop_loss"] == 0.05
        assert lib["strategies"][0]["take_profit"] == 0.15
        assert "last_risk_audit" in lib

    def test_cognition_delegates_to_consolidate(self, isolated_evolver, monkeypatch):
        ev = isolated_evolver
        consolidated = []

        class FakeMS:
            def __init__(self):
                pass

            def consolidate(self):
                consolidated.append(1)
                ev.SEMANTIC_FILE.write_text(json.dumps({"semantic_count": 5}))

        monkeypatch.setattr("agi.memory_system.MemorySystem", FakeMS)
        before = ev._system_state()
        ev._evolve_cognition(_make_goal("cognitive_architecture"))
        after = ev._system_state()

        assert consolidated == [1]
        assert after["semantic_memory"] == 5
        imp = ev._measure_improvement(before, after, "cognitive_architecture")
        # semantic 0.40×5/3(封顶1) = 0.40
        assert imp == pytest.approx(0.40)

    def test_generic_dedupes_and_archives(self, isolated_evolver):
        from agi.eternal_evolver import EvolutionGoal
        ev = isolated_evolver
        done = EvolutionGoal(id="d1", description="已完成", domain="risk_management",
                             novelty_score=0.5, difficulty=0.5, potential_impact=0.5)
        done.status = "completed"
        dup1 = EvolutionGoal(id="p1", description="重复", domain="market_analysis",
                             novelty_score=0.5, difficulty=0.5, potential_impact=0.5)
        dup2 = EvolutionGoal(id="p2", description="重复", domain="market_analysis",
                             novelty_score=0.5, difficulty=0.5, potential_impact=0.5)
        ev.goals = [done, dup1, dup2]
        ev._evolve_generic(_make_goal("market_analysis"))
        assert len(ev.goals) == 2  # 去掉一个重复
        archive = json.loads(ev.GOAL_ARCHIVE.read_text(encoding="utf-8"))
        assert [g["id"] for g in archive["goals"]] == ["d1"]

    def test_generic_archive_idempotent(self, isolated_evolver):
        from agi.eternal_evolver import EvolutionGoal
        ev = isolated_evolver
        done = EvolutionGoal(id="d1", description="x", domain="market_analysis",
                             novelty_score=0.5, difficulty=0.5, potential_impact=0.5)
        done.status = "completed"
        ev.goals = [done]
        ev._evolve_generic(_make_goal())
        ev._evolve_generic(_make_goal())
        archive = json.loads(ev.GOAL_ARCHIVE.read_text(encoding="utf-8"))
        assert len(archive["goals"]) == 1  # 不重复归档


class TestMutationApplicability:
    def test_static_per_type(self, isolated_evolver):
        ev = isolated_evolver
        seen = {}
        for _ in range(30):
            inv = ev._random_mutation()
            seen.setdefault(inv.concept, inv.applicability)
            # 同类型突变适用度必须一致（静态映射）
            assert seen[inv.concept] == inv.applicability
            assert 0.3 <= inv.applicability <= 0.8
        # 至少覆盖 2 种突变类型才算有效采样
        assert len(seen) >= 2

    def test_matches_mapping(self, isolated_evolver):
        ev = isolated_evolver
        for _ in range(50):
            inv = ev._random_mutation()
            mutation_type = inv.concept.removeprefix("突变: ")
            assert inv.applicability == ev.MUTATION_APPLICABILITY[mutation_type]


class TestSelfAssessAndPersistence:
    def test_last_system_state_persisted_across_cycles(self, isolated_evolver):
        ev = isolated_evolver
        _write_lib(ev, [{"name": "a", "stop_loss": 0.05, "take_profit": 0.15,
                         "backtest_passed": True}])
        ev._save()
        reloaded = type(ev)()
        assert reloaded._last_system_state is not None
        assert reloaded._last_system_state["library_size"] == 1
        assert reloaded._last_system_state["passed_strategies"] == 1

    def test_self_assess_reports_system_growth(self, isolated_evolver):
        ev = isolated_evolver
        _write_lib(ev, [])
        ev._save()  # 基线：空库
        ev._last_system_state = ev._system_state()
        _write_lib(ev, [{"name": "a", "stop_loss": 0.05, "take_profit": 0.15}])
        # 直接构造一条记录驱动 _self_assess 非初始化分支
        from agi.eternal_evolver import EvolutionRecord
        ev.records.append(EvolutionRecord(
            id="r1", goal_id="g1", action="evolve_strategy_creation",
            before_state={}, after_state={}, improvement=0.05,
            novel_discovery=False, lessons=[]))
        assessment = ev._self_assess()
        assert assessment["system_growth"]["library_size"] == 1
        assert assessment["system_growth"]["risk_covered"] == 1

    def test_self_assess_no_baseline_no_growth(self, isolated_evolver):
        from agi.eternal_evolver import EvolutionRecord
        ev = isolated_evolver
        ev._last_system_state = None
        ev.records.append(EvolutionRecord(
            id="r1", goal_id="g1", action="x", before_state={}, after_state={},
            improvement=0.05, novel_discovery=False, lessons=[]))
        assessment = ev._self_assess()
        assert assessment["system_growth"] == {}


class TestNoFakeMetrics:
    def test_random_uniform_never_called(self, isolated_evolver, monkeypatch):
        """回归防护：random.uniform 假度量已彻底移除"""
        from agi import eternal_evolver as ee

        def _fail(*args, **kwargs):
            raise AssertionError("random.uniform 假度量已被移除")

        monkeypatch.setattr(ee.random, "uniform", _fail)
        ev = isolated_evolver
        _write_lib(ev, [{"name": "no_sl"}])
        ev.goals = [_make_goal("strategy_creation"), _make_goal("risk_management")]
        # 完整跑一轮（含目标选择/进化/突变/跨域/自评/巩固/保存）
        result = ev.eternal_cycle()
        assert result["cycle"] == 1
        assert result["assessment"]["status"] in ("improving", "stable", "declining")

    def test_improvement_reflects_real_action(self, isolated_evolver):
        """端到端：风控目标在缺失参数库上必须产生可解释的真实改进度"""
        ev = isolated_evolver
        _write_lib(ev, [{"name": "no_sl"}, {"name": "no_tp", "stop_loss": 0.04}])
        goal = _make_goal("risk_management")
        result = ev._evolve_towards_goal(goal)
        assert result["improvement"] == pytest.approx(0.3)  # 0.45 × 2/3
        assert ev.records[-1].improvement == pytest.approx(0.3)
        assert ev.records[-1].action == "evolve_risk_management"
