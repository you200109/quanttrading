"""端到端验证 get_nexus_file 路由函数（真实代码路径）"""
import asyncio
import os
import sys

REPO = "C:/Users/Administrator/WorkBuddy/ww/quanttrading"
sys.path.insert(0, REPO)

from backend.api.vc_routes import get_nexus_file  # noqa: E402


async def main():
    cases = [
        ("version.json", "合法文件"),
        ("evolution_state.json", "合法文件"),
        ("../.env", "路径遍历"),
        ("../../backend/.env", "深层遍历"),
        ("/etc/passwd", "绝对路径"),
        (".hidden", "点文件"),
        ("nonexistent.json", "不存在文件"),
    ]
    fails = 0
    for name, desc in cases:
        r = await get_nexus_file(name)
        code = r["code"]
        if name in ("version.json", "evolution_state.json"):
            ok = code == 0
        else:
            ok = code == 1
        if not ok:
            fails += 1
        print(f"{'PASS' if ok else 'FAIL'}  {desc:10s} {name!r:28s} -> code={code} {r.get('msg', '')[:30]}")
    print(f"\n{len(cases) - fails}/{len(cases)} passed")
    return 1 if fails else 0


sys.exit(asyncio.run(main()))
