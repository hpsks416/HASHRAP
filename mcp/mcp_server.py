"""ChipManualDesk 检索 MCP server：把本机芯片手册检索暴露成 agent 可全权驱动的 MCP 工具。

依赖：pip install mcp
启动：python mcp\mcp_server.py        # MCP 在 http://127.0.0.1:8000/mcp
连接：claude mcp add --transport http chip-manual-rag http://127.0.0.1:8000/mcp

本服务只封装检索（status/search/read/page），不入库；入库走 ChipManualDesk 桌面端。
数据根走环境变量 CHIPRAG_DATA（同 query.ps1 约定）；python/backend 可用 --python/--backend 或
环境变量 CHIPRAG_PYTHON / CHIPRAG_BACKEND 覆盖。本机需先 Install.cmd 完成并索引手册才有真实结果。

注意：mcp.run() 的 transport 参数随 mcp SDK 版本略有差异（streamable-http / http / stdio）。
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("chip-manual-rag")

BACKEND = Path(os.environ.get(
    "CHIPRAG_BACKEND",
    Path(__file__).resolve().parents[1] / "ChipManualDesk-1.0.2" / "backend",
))
PYTHON = os.environ.get("CHIPRAG_PYTHON", sys.executable)


def _run(*args: str) -> str:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [PYTHON, "-m", "chiprag.cli", *args],
        cwd=str(BACKEND), env=env, capture_output=True, text=True, encoding="utf-8",
    )
    if proc.returncode != 0:
        return json.dumps({"error": (proc.stderr or "").strip() or f"exit {proc.returncode}"},
                          ensure_ascii=False)
    return proc.stdout


@mcp.tool()
def status(docid: str = "") -> str:
    """列出知识库里的手册（或指定 docid 的单条）：型号/版本/状态/页数/索引进度。先调用它确认正确手册与修订版。"""
    return _run("status", *([docid] if docid else []))


@mcp.tool()
def search(query: str, chip: str = "", revision: str = "", docid: str = "",
           top: int = 8, english_query: str = "", lexical_only: bool = False,
           rerank: bool = False) -> str:
    """混合检索（FTS5+向量+RRF）。chip/revision/docid 过滤；中文问题给 english_query 以启用英文重排。返回带出处（章节/页码/源PDF）的片段。"""
    args = ["search", query, "--top", str(top)]
    if chip:
        args += ["--chip", chip]
    if revision:
        args += ["--revision", revision]
    if docid:
        args += ["--docid", docid]
    if english_query:
        args += ["--english-query", english_query]
    if lexical_only:
        args += ["--lexical-only"]
    if not rerank:
        args += ["--no-rerank"]
    return _run(*args)


@mcp.tool()
def read(chunk_id: str, section: bool = False, offset: int = 0, limit: int = 20) -> str:
    """读取某片段全文，或（section=True）读同章节片段列表。用于命中后扩上下文、跟续表。"""
    args = ["read", chunk_id, "--offset", str(offset), "--limit", str(limit)]
    if section:
        args += ["--section"]
    return _run(*args)


@mcp.tool()
def page(docid: str, page: int, bbox: str = "") -> str:
    """把原 PDF 指定页渲染成本地图片，供核验数值/位域/图表。bbox 用 'x0,y0,x1,y1'（0-1000 归一化坐标，可选）。"""
    args = ["page", docid, str(page)]
    if bbox:
        parts = bbox.split(",")
        if len(parts) != 4:
            return json.dumps({"error": "bbox must be 'x0,y0,x1,y1'"}, ensure_ascii=False)
        args += ["--bbox", *parts]
    return _run(*args)


def _load_skill() -> str:
    return (Path(__file__).resolve().parent / "SKILL.md").read_text(encoding="utf-8")


@mcp.resource("tool://skill")
def skill() -> str:
    """工具说明书（写作规则 + 官方示例）。agent 应先 read_resource("tool://skill") 再开始调用工具。"""
    return _load_skill()


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8000)
