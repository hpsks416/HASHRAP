#!/usr/bin/env python3
"""framework-kb 召回效果测试：跑一组框架规则查询，检查 top-k 是否命中预期 source。"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "pylibs"))
from search_kb import search

TESTS = [
    # (查询, 预期 source 关键词, 说明)
    ("判重要不要读版本差异", "AGENTS.md", "铁律一·判重读版本差异"),
    ("先申请后执行", "AGENTS.md", "铁律二·先申请后执行"),
    ("调用skill前要做什么", "AGENTS.md", "铁律三·强制加载知识库"),
    ("装Python包用pip还是uv", "rag", "rag skill·已知坑(Store Python/schannel)"),
    ("推送GitHub用什么代理", "persona.md", "画像·环境约定(代理7897)"),
    ("用户决策偏好", "persona.md", "画像·决策偏好(选项弹窗)"),
    ("Gitee创建仓库public字段注意什么", "acp-studio", "强制效果·摘要无但全文有的细节"),
    ("windows-node-spawn-cli和cross-spawn什么关系", "AGENTS.md", "铁律一·冲突处理(复用标准轮子)"),
]


def main():
    top = 5
    hit = 0
    for q, expected, note in TESTS:
        r = search(q, top=top)
        results = r.get("results", [])
        sources = [x["source"] for x in results]
        ok = any(expected.lower() in s.lower() for s in sources)
        hit += int(ok)
        top1 = results[0] if results else {}
        src = Path(top1.get("source", "")).name
        sec = top1.get("section", "")
        print(f"[{'HIT' if ok else 'MISS'}] {q}")
        print(f"    预期={expected} | top1={src} | {sec}")
    print(f"\n=== 召回命中 {hit}/{len(TESTS)} ===")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
