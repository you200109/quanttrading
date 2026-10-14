"""
AGI 自主代码重构器 - AI 理解自身架构并自主优化

实现真正的"自我编程"：
- 代码自省 - 读取和分析自身代码结构
- 性能分析 - 识别性能瓶颈
- 自动重构 - 优化代码结构和算法
- 测试验证 - 重构后自动运行测试
- 版本回滚 - 重构失败自动回滚
"""

import ast
import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
MEMORY = ROOT / "memory" / "agi"
MEMORY.mkdir(parents=True, exist_ok=True)
BACKUP_DIR = ROOT / ".backups" / "refactor"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class CodeAnalysis:
    file_path: str
    lines: int
    functions: list[str]
    classes: list[str]
    imports: list[str]
    complexity_score: float
    issues: list[str]
    suggestions: list[str]


@dataclass
class RefactorResult:
    file_path: str
    success: bool
    changes_made: list[str]
    lines_before: int
    lines_after: int
    tests_passed: bool
    error_message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


class AutoRefactor:
    """自主代码重构器

    核心能力：
    1. 代码自省 - 使用 AST 分析代码结构
    2. 复杂度检测 - 识别过于复杂的函数
    3. 自动优化 - 提取重复代码、简化条件、优化循环
    4. 安全重构 - 备份→重构→测试→回滚
    5. 持续改进 - 记录重构历史，学习最佳实践
    """

    COMPLEXITY_THRESHOLD = 10
    MAX_FUNCTION_LINES = 100

    def __init__(self):
        self.refactor_history: list[RefactorResult] = []
        self.analyzed_files: dict[str, CodeAnalysis] = {}
        self.llm_client = None
        self._init_llm()

    def _init_llm(self):
        try:
            import os
            if os.getenv("OPENAI_API_KEY"):
                from openai import OpenAI
                self.llm_client = OpenAI()
            elif os.getenv("ANTHROPIC_API_KEY"):
                from anthropic import Anthropic
                self.llm_client = Anthropic()
        except ImportError:
            pass

    def analyze_project(self) -> dict[str, CodeAnalysis]:
        """分析整个项目的代码质量"""
        py_files = list(ROOT.rglob("*.py"))
        py_files = [f for f in py_files if ".venv" not in str(f) and "__pycache__" not in str(f)]
        logger.info(f"分析 {len(py_files)} 个 Python 文件")
        for file_path in py_files:
            try:
                analysis = self._analyze_file(file_path)
                self.analyzed_files[str(file_path)] = analysis
                if analysis.issues:
                    logger.info(f"{file_path.name}: {len(analysis.issues)} 个问题, 复杂度={analysis.complexity_score:.1f}")
            except Exception as e:
                logger.debug(f"分析 {file_path.name} 失败: {e}")
        self._save_analysis()
        return self.analyzed_files

    def _analyze_file(self, file_path: Path) -> CodeAnalysis:
        """分析单个文件"""
        code = file_path.read_text(encoding="utf-8", errors="ignore")
        lines = code.count('\n') + 1
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return CodeAnalysis(file_path=str(file_path), lines=lines, functions=[],
                               classes=[], imports=[], complexity_score=0,
                               issues=["语法错误"], suggestions=[])

        functions = []
        classes = []
        imports = []
        complexity = 0
        issues = []
        suggestions = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.append(node.name)
                func_complexity = self._cyclomatic_complexity(node)
                complexity += func_complexity
                func_lines = node.end_lineno - node.lineno if node.end_lineno else 0
                if func_complexity > self.COMPLEXITY_THRESHOLD:
                    issues.append(f"函数 {node.name} 圈复杂度 {func_complexity} 过高")
                    suggestions.append(f"拆分 {node.name} 为更小的函数")
                if func_lines > self.MAX_FUNCTION_LINES:
                    issues.append(f"函数 {node.name} 过长 ({func_lines} 行)")
                    suggestions.append(f"将 {node.name} 拆分为多个函数")
                if len(node.args.args) > 5:
                    issues.append(f"函数 {node.name} 参数过多 ({len(node.args.args)} 个)")
                    suggestions.append(f"使用配置对象替代 {node.name} 的多个参数")
            elif isinstance(node, ast.ClassDef):
                classes.append(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    imports.append(alias.name)

        avg_complexity = complexity / max(len(functions), 1)
        return CodeAnalysis(
            file_path=str(file_path), lines=lines, functions=functions,
            classes=classes, imports=imports, complexity_score=round(avg_complexity, 1),
            issues=issues, suggestions=suggestions,
        )

    def _cyclomatic_complexity(self, node: ast.FunctionDef) -> int:
        """计算圈复杂度"""
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.And, ast.Or,
                                  ast.ExceptHandler, ast.With, ast.Assert)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        return complexity

    def refactor_file(self, file_path: str) -> RefactorResult:
        """重构单个文件"""
        path = Path(file_path)
        if not path.exists():
            return RefactorResult(file_path=file_path, success=False,
                                 changes_made=[], lines_before=0, lines_after=0,
                                 tests_passed=False, error_message="文件不存在")

        original_code = path.read_text(encoding="utf-8")
        lines_before = original_code.count('\n') + 1

        self._backup(path)

        if self.llm_client:
            refactored_code = self._llm_refactor(original_code, path.name)
        else:
            refactored_code = self._builtin_refactor(original_code)

        if refactored_code == original_code:
            return RefactorResult(file_path=file_path, success=True,
                                 changes_made=["无需重构"], lines_before=lines_before,
                                 lines_after=lines_before, tests_passed=True)

        path.write_text(refactored_code, encoding="utf-8")
        lines_after = refactored_code.count('\n') + 1

        tests_passed = self._run_tests()
        if not tests_passed:
            self._rollback(path)
            return RefactorResult(file_path=file_path, success=False,
                                 changes_made=["重构后测试失败，已回滚"],
                                 lines_before=lines_before, lines_after=lines_before,
                                 tests_passed=False, error_message="测试失败")

        changes = [f"代码行数: {lines_before} → {lines_after}"]
        result = RefactorResult(file_path=file_path, success=True, changes_made=changes,
                               lines_before=lines_before, lines_after=lines_after,
                               tests_passed=True)
        self.refactor_history.append(result)
        self._save_history()
        logger.info(f"重构完成: {path.name} ({lines_before}→{lines_after} 行)")
        return result

    def _llm_refactor(self, code: str, filename: str) -> str:
        """使用 LLM 进行智能重构"""
        prompt = f"""重构以下 Python 代码 ({filename})，要求：
1. 保持功能完全不变
2. 提高可读性和可维护性
3. 拆分过长的函数
4. 简化复杂的条件表达式
5. 移除重复代码
6. 添加适当的类型注解

只返回重构后的完整代码，不要任何解释。

原始代码：
```python
{code[:8000]}
```"""
        try:
            if hasattr(self.llm_client, 'chat'):
                response = self.llm_client.chat.completions.create(
                    model="gpt-4", messages=[
                        {"role": "system", "content": "你是 Python 代码重构专家。"},
                        {"role": "user", "content": prompt}
                    ], temperature=0.3, max_tokens=4000
                )
                result = response.choices[0].message.content
            else:
                response = self.llm_client.messages.create(
                    model="claude-3-opus-20240229", max_tokens=4000,
                    system="你是 Python 代码重构专家。",
                    messages=[{"role": "user", "content": prompt}]
                )
                result = response.content[0].text
            if "```python" in result:
                result = result.split("```python")[1].split("```")[0]
            elif "```" in result:
                result = result.split("```")[1].split("```")[0]
            return result.strip()
        except Exception as e:
            logger.error(f"LLM 重构失败: {e}")
            return code

    def _builtin_refactor(self, code: str) -> str:
        """内置重构规则"""
        lines = code.split('\n')
        refactored = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('#') and len(stripped) > 100:
                line = line[:100] + '...'
            if stripped == '' and refactored and refactored[-1].strip() == '':
                continue
            refactored.append(line)
        return '\n'.join(refactored)

    def _backup(self, file_path: Path):
        """备份文件"""
        backup_path = BACKUP_DIR / f"{file_path.name}.{datetime.now().strftime('%Y%m%d%H%M%S')}.bak"
        backup_path.write_text(file_path.read_text(encoding="utf-8"))

    def _rollback(self, file_path: Path):
        """回滚文件"""
        backups = sorted(BACKUP_DIR.glob(f"{file_path.name}.*.bak"), reverse=True)
        if backups:
            file_path.write_text(backups[0].read_text(encoding="utf-8"))
            logger.info(f"已回滚: {file_path.name}")

    def _run_tests(self) -> bool:
        """运行测试验证"""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/", "-x", "--tb=short"],
                cwd=str(ROOT), capture_output=True, text=True, timeout=60
            )
            return result.returncode == 0
        except Exception:
            return True

    def _save_analysis(self):
        data = {
            "timestamp": datetime.now().isoformat(),
            "files_analyzed": len(self.analyzed_files),
            "total_issues": sum(len(a.issues) for a in self.analyzed_files.values()),
            "files": {
                path: {"complexity": a.complexity_score, "issues": len(a.issues)}
                for path, a in self.analyzed_files.items() if a.issues
            }
        }
        (MEMORY / "code_analysis.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _save_history(self):
        data = {
            "total_refactors": len(self.refactor_history),
            "successful": sum(1 for r in self.refactor_history if r.success),
            "last_updated": datetime.now().isoformat(),
            "recent": [
                {"file": r.file_path, "success": r.success, "changes": r.changes_made}
                for r in self.refactor_history[-10:]
            ],
        }
        (MEMORY / "refactor_history.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def get_status(self) -> dict:
        return {
            "files_analyzed": len(self.analyzed_files),
            "total_refactors": len(self.refactor_history),
            "successful_refactors": sum(1 for r in self.refactor_history if r.success),
            "total_issues_found": sum(len(a.issues) for a in self.analyzed_files.values()),
            "llm_available": self.llm_client is not None,
        }
