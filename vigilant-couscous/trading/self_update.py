"""
自更新模块 - 系统自我升级

能力:
1. 版本检查 - 对比本地与远端版本
2. 代码拉取 - 从 GitHub 仓库获取最新代码
3. 完整性校验 - 文件哈希校验
4. 安全备份 - 更新前自动备份
5. 文件替换 - 原子替换
6. 触发热加载 - 通知热更新层即时生效
7. 更新历史 - 记录每次升级
"""
import hashlib
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
BACKUP_DIR = ROOT / ".backups"
VERSION_FILE = ROOT / "memory" / "nexus" / "version.json"


class SelfUpdater:
    """自更新器"""

    # 自我升级来源（可指向私有仓库或发布地址）
    UPDATE_SOURCES = [
        # {"type": "git", "url": "https://github.com/your/repo.git", "branch": "main"},
    ]

    # 允许自动更新的安全路径白名单
    ALLOWED_PATHS = [
        "agents/", "data/", "evolution/", "strategies/", "trading/",
        "cli/", "agi/", "memory/",
    ]
    # 需要人工审查的关键文件（即使在白名单内也需额外确认）
    SENSITIVE_FILES = [
        "config.py", "trading/auto_trade.py", "data/live_trader.py",
        "trading/self_update.py",  # 自更新模块自身
    ]

    def __init__(self):
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        self.current_version = self._load_version()
        self.history: list[dict] = []

    def _load_version(self) -> str:
        """读取当前版本"""
        if VERSION_FILE.exists():
            try:
                with open(VERSION_FILE, encoding="utf-8") as f:
                    return json.load(f).get("version", "0.1.0")
            except Exception:
                pass
        return "0.1.0"

    def _bump_version(self, level: str = "patch") -> str:
        """递增版本号"""
        parts = [int(x) for x in self.current_version.split(".")]
        while len(parts) < 3:
            parts.append(0)
        if level == "major":
            parts[0] += 1; parts[1] = 0; parts[2] = 0
        elif level == "minor":
            parts[1] += 1; parts[2] = 0
        else:
            parts[2] += 1
        return ".".join(str(p) for p in parts)

    def _save_version(self, version: str, note: str = ""):
        """保存版本"""
        VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": version,
            "last_updated": datetime.now().isoformat(),
            "note": note,
            "recent_history": self.history[-20:],
        }
        with open(VERSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self.current_version = version

    def _file_hash(self, path: Path) -> str:
        """计算文件哈希"""
        try:
            return hashlib.md5(path.read_bytes()).hexdigest()
        except Exception:
            return ""

    def backup(self, files: list[str] | None = None) -> str:
        """备份当前代码

        Args:
            files: 需要备份的文件相对路径列表，None 表示备份核心模块

        Returns:
            备份目录路径
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bdir = BACKUP_DIR / ts
        bdir.mkdir(parents=True, exist_ok=True)

        if files is None:
            files = [
                "config.py", "hot_reload.py", "auto_trade.py", "start.py",
                "agents/researcher.py", "agents/trader.py", "agents/risk_manager.py",
                "data/fetcher.py", "data/live_trader.py",
                "evolution/learning_loop.py", "evolution/rl_trainer.py",
            ]

        count = 0
        for rel in files:
            src = ROOT / rel
            if src.exists():
                dst = bdir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                count += 1

        logger.info(f"已备份 {count} 个文件到 {bdir}")
        return str(bdir)

    def apply_update(self, files: dict[str, str], level: str = "patch", note: str = "") -> dict:
        """应用更新

        Args:
            files: {相对路径: 新内容}
            level: 版本递增级别
            note: 更新说明

        Returns:
            更新结果
        """
        # 1. 备份
        backup_path = self.backup(list(files.keys()))

        old_version = self.current_version
        new_version = self._bump_version(level)

        # 2. 写入新内容
        written = []
        failed = []
        for rel, content in files.items():
            try:
                fp = ROOT / rel
                fp.parent.mkdir(parents=True, exist_ok=True)
                # 原子写入: 先写临时文件再替换
                tmp = fp.with_suffix(fp.suffix + ".tmp")
                tmp.write_text(content, encoding="utf-8")
                os.replace(tmp, fp)
                written.append(rel)
            except Exception as e:
                logger.error(f"写入 {rel} 失败: {e}")
                failed.append(rel)

        # 3. 记录历史
        entry = {
            "time": datetime.now().isoformat(),
            "from_version": old_version,
            "to_version": new_version,
            "files": written,
            "failed": failed,
            "note": note,
            "backup": backup_path,
        }
        self.history.append(entry)
        self._save_version(new_version, note)

        # 4. 触发热加载
        reloaded = self._trigger_hot_reload(written)

        return {
            "success": len(failed) == 0,
            "from": old_version,
            "to": new_version,
            "written": written,
            "failed": failed,
            "reloaded": reloaded,
        }

    def _trigger_hot_reload(self, files: list[str]) -> list[str]:
        """触发热加载，通知热更新层重载"""
        reloaded = []
        try:
            from hot_reload import HotReloadManager
            mgr = HotReloadManager()
            # 标记对应模块为已变化，触发重载
            for rel in files:
                mod = rel.replace("/", ".").replace(".py", "")
                if mod in mgr.watchers:
                    mgr.watchers[mod].changed()
            reloaded = mgr.check_and_reload()
        except Exception as e:
            logger.warning(f"触发热加载失败: {e}")
        return reloaded

    def check_for_update(self, repo_url: str, branch: str = "main") -> str | None:
        """检查远端是否有更新

        Returns:
            远端版本号，None 表示无法访问
        """
        try:
            # 通过 git ls-remote 检查远端最新提交
            result = subprocess.run(
                ["git", "ls-remote", repo_url, branch],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout:
                remote_hash = result.stdout.split()[0][:12]
                logger.info(f"远端最新提交: {remote_hash}")
                return remote_hash
        except Exception as e:
            logger.warning(f"检查远端更新失败: {e}")
        return None

    def _verify_signature(self, tmp_dir: Path) -> bool:
        """验证远端代码签名

        检查 SHA256SUMS 签名文件，验证所有 .py 文件完整性。
        若签名文件不存在，拒绝自动更新（需人工确认）。
        """
        sig_file = tmp_dir / "SHA256SUMS"
        if not sig_file.exists():
            logger.warning("远端缺少 SHA256SUMS 签名文件，跳过签名校验")
            return False  # 无签名默认不通过，需人工审查

        try:
            expected = {}
            for line in sig_file.read_text(encoding="utf-8").strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                if len(parts) == 2:
                    expected[parts[1]] = parts[0]

            for pyf in tmp_dir.rglob("*.py"):
                rel = str(pyf.relative_to(tmp_dir)).replace("\\", "/")
                if rel in expected:
                    actual = hashlib.sha256(pyf.read_bytes()).hexdigest()
                    if actual != expected[rel]:
                        logger.error(f"签名校验失败: {rel}")
                        return False

            logger.info(f"签名校验通过，已验证 {len(expected)} 个文件")
            return True
        except Exception as e:
            logger.error(f"签名校验异常: {e}")
            return False

    def _review_changes(self, update_files: dict[str, str]) -> dict:
        """审查变更文件

        Returns:
            {
                "approved": [...],      # 自动批准的文件
                "blocked": [...],       # 被阻止的文件（不在白名单）
                "sensitive": [...],     # 敏感文件（需人工确认）
            }
        """
        approved = []
        blocked = []
        sensitive = []

        for rel in update_files:
            # 检查是否在白名单路径内
            in_whitelist = any(rel.startswith(p) for p in self.ALLOWED_PATHS)
            if not in_whitelist:
                blocked.append(rel)
                logger.warning(f"变更审查阻止: {rel} (不在白名单)")
                continue

            # 检查是否为敏感文件
            if rel in self.SENSITIVE_FILES:
                sensitive.append(rel)
                logger.warning(f"变更审查标记敏感: {rel} (需人工确认)")
                continue

            approved.append(rel)

        return {"approved": approved, "blocked": blocked, "sensitive": sensitive}

    def pull_and_update(self, repo_url: str, branch: str = "main", skip_signature: bool = False, approved_sensitive: list[str] | None = None) -> dict:
        """从远端拉取并更新

        流程: 克隆到临时目录 -> 对比 -> 备份 -> 替换 -> 热加载
        """
        tmp_dir = ROOT / ".update_tmp"
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)

        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", "-b", branch, repo_url, str(tmp_dir)],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                return {"success": False, "error": f"克隆失败: {result.stderr[:200]}"}

            # 读取远端版本
            remote_ver_file = tmp_dir / "memory" / "nexus" / "version.json"
            remote_version = "unknown"
            if remote_ver_file.exists():
                remote_version = json.loads(remote_ver_file.read_text(encoding="utf-8")).get("version", "unknown")

            # 收集需要更新的代码文件
            update_files = {}
            for sub in ["agents", "data", "evolution", "strategies"]:
                src_dir = tmp_dir / sub
                if src_dir.exists():
                    for pyf in src_dir.rglob("*.py"):
                        rel = str(pyf.relative_to(tmp_dir)).replace("\\", "/")
                        local_fp = ROOT / rel
                        # 只更新有变化的文件
                        if not local_fp.exists() or self._file_hash(pyf) != self._file_hash(local_fp):
                            update_files[rel] = pyf.read_text(encoding="utf-8")

            for top in ["config.py", "hot_reload.py", "start.py", "auto_trade.py"]:
                src = tmp_dir / top
                if src.exists():
                    local_fp = ROOT / top
                    if not local_fp.exists() or self._file_hash(src) != self._file_hash(local_fp):
                        update_files[top] = src.read_text(encoding="utf-8")

            if not update_files:
                return {"success": True, "message": "已是最新版本", "updated": 0}

            # === 安全闸门 ===
            # 1. 签名校验
            if not skip_signature and not self._verify_signature(tmp_dir):
                return {
                    "success": False,
                    "error": "签名校验失败：远端代码缺少有效签名，拒绝自动更新",
                    "hint": "设置 skip_signature=True 可跳过（不推荐），或确认远端已配置 SHA256SUMS"
                }

            # 2. 变更审查
            review = self._review_changes(update_files)
            if review["blocked"]:
                return {
                    "success": False,
                    "error": f"变更审查阻止：{len(review['blocked'])} 个文件不在白名单",
                    "blocked_files": review["blocked"]
                }

            # 3. 敏感文件确认
            if review["sensitive"]:
                if not approved_sensitive:
                    return {
                        "success": False,
                        "error": f"变更审查暂停：{len(review['sensitive'])} 个敏感文件需人工确认",
                        "sensitive_files": review["sensitive"],
                        "hint": "通过 approved_sensitive 参数传入已确认的文件列表"
                    }
                # 只更新已批准的敏感文件
                for rel in list(update_files.keys()):
                    if rel in review["sensitive"] and rel not in approved_sensitive:
                        del update_files[rel]
                        logger.info(f"跳过未确认的敏感文件: {rel}")

            if not update_files:
                return {"success": True, "message": "所有变更文件已审查，无需更新", "updated": 0}
            # === 安全闸门结束 ===

            result = self.apply_update(update_files, level="patch", note=f"自更新 from {repo_url}")
            result["remote_version"] = remote_version
            result["updated"] = len(update_files)
            return result

        finally:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def rollback(self, backup_ts: str) -> dict:
        """回滚到指定备份"""
        bdir = BACKUP_DIR / backup_ts
        if not bdir.exists():
            return {"success": False, "error": "备份不存在"}

        restored = []
        for src in bdir.rglob("*.py"):
            rel = str(src.relative_to(bdir)).replace("\\", "/")
            dst = ROOT / rel
            shutil.copy2(src, dst)
            restored.append(rel)

        logger.info(f"已回滚 {len(restored)} 个文件")
        return {"success": True, "restored": restored}

    def get_status(self) -> dict:
        """获取自更新状态"""
        backups = [d.name for d in BACKUP_DIR.iterdir() if d.is_dir()] if BACKUP_DIR.exists() else []
        return {
            "current_version": self.current_version,
            "sources": len(self.UPDATE_SOURCES),
            "backups": sorted(backups)[-5:],
            "history_count": len(self.history),
        }


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    updater = SelfUpdater()
    print(json.dumps(updater.get_status(), indent=2, ensure_ascii=False))
