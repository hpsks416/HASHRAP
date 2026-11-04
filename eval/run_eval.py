#!/usr/bin/env python3
"""ChipManualDesk 检索层 Eval（确定性、本地、零 LLM judge）。

只测「检索层」：
  * recall@k           - 期望的寄存器/术语标记是否出现在 top-k 结果并集中
  * section locality   - 命中是否落在期望章节（提供了 expected_section 时）
  * page citation      - 命中是否落在期望 PDF 页（提供了 expected_page 时）
  * version-constraint - 结果是否混入禁止标记（错误芯片/系列）
  * filter sanity      - 所有返回 chunk 是否匹配请求的 chip + revision

生成层幻觉（宿主 AI 是否编造答案）不在此测量：它依赖宿主模型，超出本地确定性脚本范围，
需宿主 AI + judge 单独评估。

真实模式（需已安装 ChipManualDesk + 已索引的手册）：
    python run_eval.py --python <venv-python> --data <ChipManualLibrary> --golden golden.json

自检模式（只验证评分逻辑，无需后端）：
    python run_eval.py --self-test
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _text(r: dict) -> str:
    return (r.get("text", "") or "") + "\n" + " / ".join(r.get("section", []) or [])


def _present(term: str, haystack: str) -> bool:
    # 大小写不敏感的子串匹配。子串可能过度匹配（如 PA0 命中 PA01）；
    # 起步集里术语足够具体，可接受，未来可升级为整词/token 匹配。
    return term.lower() in haystack.lower()


def score_case(case: dict, results: list[dict]) -> dict:
    """对单个黄金用例打分。纯函数，可独立测试。"""
    checks = case.get("checks", {}) or {}
    must_contain = checks.get("must_contain", [])
    must_not_contain = checks.get("must_not_contain", [])
    expected_section = checks.get("expected_section")
    expected_page = checks.get("expected_page")
    expected_revision = str(case.get("revision", "")).strip() if case.get("revision") else None
    expected_chip = (case.get("chip") or "").upper().strip() or None

    union = "\n".join(_text(r) for r in results)

    term_hits = {t: _present(t, union) for t in must_contain}
    recall = (sum(term_hits.values()) / len(must_contain)) if must_contain else None
    forbidden = [t for t in must_not_contain if _present(t, union)]

    section_ok = None
    if expected_section:
        section_ok = any(
            _present(expected_section, " / ".join(r.get("section", []) or []))
            for r in results
        )

    page_ok = None
    if expected_page is not None:
        page_ok = any(r.get("page") == expected_page for r in results)

    rev_mismatch = [
        r for r in results
        if expected_revision and str(r.get("revision")) != expected_revision
    ]
    chip_mismatch = [
        r for r in results
        if expected_chip and (r.get("chip") or "").upper() != expected_chip
    ]

    passed: list[str] = []
    failed: list[str] = []
    if must_contain:
        (passed if all(term_hits.values()) else failed).append("must_contain")
    if must_not_contain:
        (passed if not forbidden else failed).append("must_not_contain")
    if section_ok is not None:
        (passed if section_ok else failed).append("expected_section")
    if page_ok is not None:
        (passed if page_ok else failed).append("expected_page")
    (passed if not rev_mismatch else failed).append("revision_filter")
    (passed if not chip_mismatch else failed).append("chip_filter")

    out = {
        "id": case.get("id"),
        "category": case.get("category"),
        "recall": recall,
        "term_hits": term_hits,
        "forbidden_hits": forbidden,
        "section_ok": section_ok,
        "page_ok": page_ok,
        "n_results": len(results),
        "passed": passed,
        "failed": failed,
    }
    out["ok"] = not failed
    return out


def run_search(python: str, backend: Path, data: Path, case: dict, top: int, rerank: bool) -> dict:
    cmd = [
        python, "-m", "chiprag.cli", "search", case["query"],
        "--chip", case["chip"], "--revision", str(case.get("revision", "")),
        "--top", str(top),
    ]
    if case.get("english_query"):
        cmd += ["--english-query", case["english_query"]]
    if not rerank:
        cmd += ["--no-rerank"]
    env = dict(os.environ)
    env["CHIPRAG_DATA"] = str(data)
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(cmd, cwd=str(backend), env=env, capture_output=True,
                          text=True, encoding="utf-8")
    if proc.returncode != 0:
        return {"_error": (proc.stderr or "").strip() or f"exit {proc.returncode}"}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"_error": "non-JSON stdout: " + proc.stdout[:200]}


def aggregate(scored: list[dict]) -> dict:
    cats: dict[str, list[dict]] = {}
    for s in scored:
        cats.setdefault(s["category"] or "uncategorized", []).append(s)
    per_cat = {}
    for cat, items in cats.items():
        recalls = [i["recall"] for i in items if i["recall"] is not None]
        per_cat[cat] = {
            "n": len(items),
            "pass_rate": sum(1 for i in items if i["ok"]) / len(items),
            "avg_recall": (sum(recalls) / len(recalls)) if recalls else None,
        }
    ok = sum(1 for s in scored if s["ok"])
    recalls = [s["recall"] for s in scored if s["recall"] is not None]
    return {
        "n_cases": len(scored),
        "overall_pass_rate": (ok / len(scored)) if scored else None,
        "avg_recall": (sum(recalls) / len(recalls)) if recalls else None,
        "per_category": per_cat,
    }


def _pct(x):
    return "—" if x is None else f"{x * 100:.1f}%"


def render_markdown(scored, agg, golden_path, rerank: bool) -> str:
    lines = ["# ChipManualDesk 检索层 Eval 报告", ""]
    lines.append(f"- 黄金集：`{golden_path}`；重排：{'开' if rerank else '关（--no-rerank，混合召回基线）'}")
    lines.append(f"- 用例数：{agg['n_cases']}；总通过率：{_pct(agg['overall_pass_rate'])}；平均 recall：{_pct(agg['avg_recall'])}")
    lines.append("")
    lines.append("> 本报告只测**检索层**（召回/定位/引用/版本约束/过滤），不测生成层幻觉。")
    lines.append("> 总通过率是跨类别平均值——分域看才最有指导意义。")
    lines.append("")
    lines.append("## 分域结果")
    lines.append("| 类别 | 用例数 | 通过率 | 平均 recall |")
    lines.append("|---|---|---|---|")
    for cat, m in agg["per_category"].items():
        lines.append(f"| {cat} | {m['n']} | {_pct(m['pass_rate'])} | {_pct(m['avg_recall'])} |")
    lines.append("")
    lines.append("## 逐用例")
    lines.append("| id | 类别 | 结果 | recall | 命中数 | 通过项 | 失败项 |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in scored:
        lines.append(
            f"| {s['id']} | {s['category']} | {'PASS' if s['ok'] else 'FAIL'} "
            f"| {_pct(s['recall'])} | {s['n_results']} "
            f"| {', '.join(s['passed']) or '—'} | {', '.join(s['failed']) or '—'} |"
        )
    return "\n".join(lines) + "\n"


def self_test() -> int:
    synthetic = {
        "id": "t1", "category": "register_config", "chip": "STM32H743", "revision": "9",
        "checks": {"must_contain": ["ADC", "CKMODE"], "must_not_contain": ["STM32F1"],
                   "expected_section": "ADC"},
    }
    good = [{"text": "ADC clock CKMODE prescaler", "section": ["ADC"], "page": 1,
             "chip": "STM32H743", "revision": "9"}]
    bad = [{"text": "ADC clock STM32F1 prescaler", "section": ["GPIO"], "page": 1,
            "chip": "STM32F103", "revision": "9"}]
    s1 = score_case(synthetic, good)
    s2 = score_case(synthetic, bad)
    assert s1["ok"] is True, s1
    assert s2["ok"] is False, s2
    assert s2["term_hits"]["CKMODE"] is False, s2
    assert s2["forbidden_hits"] == ["STM32F1"], s2
    print("self-test PASS（评分逻辑正确）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ChipManualDesk 检索层 Eval")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--golden", default="golden.json")
    ap.add_argument("--python", default=None, help="venv 的 python.exe（默认 sys.executable）")
    ap.add_argument("--backend", default=None, help="backend 目录（含 chiprag/）")
    ap.add_argument("--data", default=None, help="CHIPRAG_DATA 知识库根目录（真实模式必填）")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--rerank", action="store_true", help="开启英文重排（需英文改写 + reranker 模型）")
    ap.add_argument("--report", default="report.md")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    python = args.python or sys.executable
    backend = Path(args.backend).resolve() if args.backend else (
        Path(__file__).resolve().parents[1] / "ChipManualDesk-1.0.2" / "backend")
    if args.data is None:
        print("--data（ChipManualLibrary 根目录）在真实模式下必填", file=sys.stderr)
        return 2
    data = Path(args.data).resolve()

    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    cases = golden["cases"]

    scored = []
    for case in cases:
        raw = run_search(python, backend, data, case, args.top, args.rerank)
        if "_error" in raw:
            scored.append({"id": case.get("id"), "category": case.get("category"),
                           "recall": None, "term_hits": {}, "forbidden_hits": [],
                           "section_ok": None, "page_ok": None, "n_results": 0,
                           "passed": [], "failed": [f"runner_error: {raw['_error']}"],
                           "ok": False})
            print(f"[error] {case.get('id')}: {raw['_error']}", file=sys.stderr)
            continue
        s = score_case(case, raw.get("results", []))
        scored.append(s)
        print(f"[{'PASS' if s['ok'] else 'FAIL'}] {s['id']} recall={_pct(s['recall'])} n={s['n_results']}")

    agg = aggregate(scored)
    Path(args.report).write_text(render_markdown(scored, agg, args.golden, args.rerank),
                                 encoding="utf-8")
    print(f"\n报告已写入 {args.report}")
    print(f"总通过率={_pct(agg['overall_pass_rate'])} 平均 recall={_pct(agg['avg_recall'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
