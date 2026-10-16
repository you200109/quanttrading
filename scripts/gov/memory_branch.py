"""gov-memory 分支的知识库搬运（P6f 编排的组成部分）

main 有分支保护（要求走 PR；enforce_admins=false 只豁免管理员），Actions 的
GITHUB_TOKEN 不是管理员，直推 main 会被拒；GITHUB_TOKEN 造的 PR 又不触发 CI
（递归抑制）——所以知识库回写改走**不受保护的专用分支**（gov-memory），
零新增密钥、零手工操作。main 保持干净，代码与记忆分家。

契约：
- restore()：远端分支存在且包含知识库目录时，用其内容整体替换工作区的该目录；
  分支不存在 / 分支上还没有该目录 → 原样返回（首次运行是正常状态，不是失败）。
- persist()：以分支 tip（首次运行时为空树）为基线，**只取工作区知识库目录**
  构建提交并推送；树无变化则不产生空提交。

边界纪律：
- 一切 git 调用经 _git() 单点进出；tests/test_gov_memory_branch.py 直接对临时
  真实仓库运行本模块，不靠 mock 猜 git 行为；
- restore 失败时调用方**必须放弃 persist**——否则会把未恢复的工作区覆盖掉分支
  上的记忆（run.py 已按此约束接线，勿绕过）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

BRANCH = "gov-memory"
GIT_TIMEOUT = 120  # 秒；单条 git 命令上限（fetch/push 为网络操作）


class GitError(RuntimeError):
    """git 命令以非预期退出码结束（含远端不可达、非 fast-forward 等）"""


def _git(args: list[str], *, cwd: Path, env: dict | None = None,
         check: bool = True) -> subprocess.CompletedProcess:
    merged = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})}
    cp = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT, env=merged)
    if check and cp.returncode != 0:
        tail = ((cp.stderr or "") + (cp.stdout or "")).strip()[-500:]
        raise GitError(f"git {' '.join(args[:3])} 失败（退出码 {cp.returncode}）：{tail}")
    return cp


def _branch_exists(root: Path, branch: str) -> bool:
    """ls-remote 探测远端分支：0=存在，2=不存在（--exit-code 约定），其余按错误处理"""
    cp = _git(["ls-remote", "--exit-code", "--heads", "origin", branch],
              cwd=root, check=False)
    if cp.returncode == 0:
        return True
    if cp.returncode == 2:
        return False
    tail = ((cp.stderr or "") + (cp.stdout or "")).strip()[-500:]
    raise GitError(f"git ls-remote 失败（退出码 {cp.returncode}）：{tail}")


def restore(root: Path, *, kb_rel: str, branch: str = BRANCH) -> dict:
    """把 gov-memory 分支上的知识库恢复到工作区。

    kb_rel：相对仓库根的 POSIX 路径（如 vigilant-couscous/memory/knowledge）。
    返回 action：absent（无分支）/ no-kb（分支无该目录）/ restored。
    """
    if not _branch_exists(root, branch):
        return {"action": "absent", "branch": branch}
    _git(["fetch", "--depth=1", "origin", branch], cwd=root)
    listed = _git(["ls-tree", "-r", "--name-only", "FETCH_HEAD", "--", kb_rel],
                  cwd=root).stdout.splitlines()
    files = [line for line in listed if line.strip()]
    if not files:
        return {"action": "no-kb", "branch": branch}
    local = root / kb_rel
    if local.exists():
        shutil.rmtree(local)
    _git(["checkout", "FETCH_HEAD", "--", kb_rel], cwd=root)
    return {"action": "restored", "branch": branch, "files": len(files)}


def persist(root: Path, *, kb_rel: str, message: str, branch: str = BRANCH) -> dict:
    """把工作区知识库目录快照推送到 gov-memory 分支。

    返回 action：skipped（工作区没有该目录）/ unchanged（与分支现状一致）/
    pushed（新提交已推送，附 commit）。
    """
    kb_abs = root / kb_rel
    if not kb_abs.is_dir():
        return {"action": "skipped", "reason": f"工作区没有 {kb_rel} 目录"}
    base = None
    if _branch_exists(root, branch):
        _git(["fetch", "--depth=1", "origin", branch], cwd=root)
        base = _git(["rev-parse", "FETCH_HEAD"], cwd=root).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="gov-memory-") as tmp:
        # 临时索引：只构建"分支 tip + 本次知识库改动"的树，绝不触碰 main 的索引
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if base:
            _git(["read-tree", base], cwd=root, env=env)
        else:
            _git(["read-tree", "--empty"], cwd=root, env=env)
        _git(["add", "-A", "--", kb_rel], cwd=root, env=env)
        tree = _git(["write-tree"], cwd=root, env=env).stdout.strip()
        if base:
            base_tree = _git(["rev-parse", f"{base}^{{tree}}"], cwd=root).stdout.strip()
            if tree == base_tree:
                return {"action": "unchanged", "branch": branch, "commit": base}
        identity = ["-c", "user.name=github-actions[bot]",
                    "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com"]
        if base:
            commit = _git([*identity, "commit-tree", tree, "-p", base, "-m", message],
                          cwd=root).stdout.strip()
        else:
            commit = _git([*identity, "commit-tree", tree, "-m", message],
                          cwd=root).stdout.strip()
    _git(["push", "origin", f"{commit}:refs/heads/{branch}"], cwd=root)
    return {"action": "pushed", "branch": branch, "commit": commit}
