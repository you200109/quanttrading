"""gov-memory 分支搬运（scripts/gov/memory_branch.py）集成测试

直接对临时真实仓库运行——不 mock git，验证 restore/persist 在真实 git 行为下
的语义：首次运行建孤儿内容、无变化跳过（不产生空提交）、变更与删除传播、
整体替换工作区、分支无知识库目录等。
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.gov import memory_branch  # noqa: E402

KB = "memory/knowledge"
IDENT = ["-c", "user.name=test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false"]


def git(*args, cwd):
    cp = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                        text=True, encoding="utf-8", errors="replace")
    assert cp.returncode == 0, f"git {args} 失败：{cp.stderr}"
    return cp.stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """工作副本 + 本地裸仓库 origin（main 已推送，工作副本无知识库目录）"""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main",
                    str(origin)], check=True, capture_output=True)
    work = tmp_path / "work"
    work.mkdir()
    git("init", "--initial-branch=main", cwd=work)
    (work / "app.py").write_text("print('hi')\n", encoding="utf-8")
    git(*IDENT, "add", "-A", cwd=work)
    git(*IDENT, "commit", "-m", "init", cwd=work)
    git("remote", "add", "origin", origin.as_posix(), cwd=work)
    git(*IDENT, "push", "-u", "origin", "main", cwd=work)
    return work


def _write_kb(work: Path, files: dict) -> None:
    for name, payload in files.items():
        path = work / KB / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def _branch_files(repo: Path, tmp_path: Path) -> list:
    bare = tmp_path / "origin.git"
    out = git("--git-dir", str(bare), "ls-tree", "-r", "--name-only", "gov-memory",
              cwd=tmp_path)
    return [line for line in out.splitlines() if line.strip()]


def _branch_show(repo: Path, tmp_path: Path, path: str) -> str:
    bare = tmp_path / "origin.git"
    return git("--git-dir", str(bare), "show", f"gov-memory:{path}", cwd=tmp_path)


def test_persist_first_run_creates_branch_with_only_kb(repo, tmp_path):
    _write_kb(repo, {"state/prev_shortlist.json": {"date": "2026-10-15"},
                     "projects/a__b.json": {"name": "a/b"}})
    result = memory_branch.persist(repo, kb_rel=KB, message="snap 1")
    assert result["action"] == "pushed"
    names = _branch_files(repo, tmp_path)
    assert f"{KB}/state/prev_shortlist.json" in names
    assert f"{KB}/projects/a__b.json" in names
    # 分支只有知识库，没有代码（孤儿内容，不是 main 快照）
    assert all(name.startswith(f"{KB}/") for name in names)
    bare = tmp_path / "origin.git"
    author = git("--git-dir", str(bare), "log", "-1", "--format=%an", "gov-memory",
                 cwd=tmp_path).strip()
    assert author == "github-actions[bot]"


def test_persist_unchanged_does_not_create_empty_commit(repo):
    _write_kb(repo, {"a.json": {"v": 1}})
    first = memory_branch.persist(repo, kb_rel=KB, message="snap 1")
    second = memory_branch.persist(repo, kb_rel=KB, message="snap 2")
    assert first["action"] == "pushed"
    assert second["action"] == "unchanged"
    assert second["commit"] == first["commit"]


def test_persist_change_and_deletion_propagate(repo, tmp_path):
    _write_kb(repo, {"a.json": {"v": 1}, "b.json": {"v": 1}})
    memory_branch.persist(repo, kb_rel=KB, message="snap 1")
    (repo / KB / "b.json").unlink()
    (repo / KB / "a.json").write_text(json.dumps({"v": 2}) + "\n", encoding="utf-8")
    result = memory_branch.persist(repo, kb_rel=KB, message="snap 2")
    assert result["action"] == "pushed"
    names = _branch_files(repo, tmp_path)
    assert f"{KB}/a.json" in names
    assert f"{KB}/b.json" not in names
    assert json.loads(_branch_show(repo, tmp_path, f"{KB}/a.json"))["v"] == 2


def test_persist_keeps_existing_branch_history_fast_forward(repo, tmp_path):
    _write_kb(repo, {"a.json": {"v": 1}})
    first = memory_branch.persist(repo, kb_rel=KB, message="snap 1")
    (repo / KB / "a.json").write_text(json.dumps({"v": 2}) + "\n", encoding="utf-8")
    second = memory_branch.persist(repo, kb_rel=KB, message="snap 2")
    assert second["action"] == "pushed"
    bare = tmp_path / "origin.git"
    parent = git("--git-dir", str(bare), "log", "-1", "--format=%P", "gov-memory",
                 cwd=tmp_path).strip()
    assert parent == first["commit"]


def test_restore_absent_branch_is_not_an_error(repo):
    result = memory_branch.restore(repo, kb_rel=KB)
    assert result["action"] == "absent"


def test_restore_branch_without_kb_dir(repo):
    # gov-memory 指向 main（无知识库目录）→ 按首次运行处理
    git(*IDENT, "push", "origin", "main:gov-memory", cwd=repo)
    result = memory_branch.restore(repo, kb_rel=KB)
    assert result["action"] == "no-kb"


def test_restore_roundtrip_and_whole_dir_replacement(repo):
    _write_kb(repo, {"state/x.json": {"n": 1}})
    memory_branch.persist(repo, kb_rel=KB, message="snap 1")
    # 模拟 CI 新检出：工作区清空 + 混入一个游离文件，restore 应整体替换
    shutil.rmtree(repo / KB)
    (repo / KB).mkdir(parents=True)
    (repo / KB / "stray.json").write_text("{}\n", encoding="utf-8")
    result = memory_branch.restore(repo, kb_rel=KB)
    assert result["action"] == "restored"
    assert result["files"] == 1
    restored = json.loads((repo / KB / "state" / "x.json").read_text(encoding="utf-8"))
    assert restored == {"n": 1}
    assert not (repo / KB / "stray.json").exists()


def test_persist_skipped_without_kb_dir(repo):
    result = memory_branch.persist(repo, kb_rel=KB, message="snap")
    assert result["action"] == "skipped"
