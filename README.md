# HASHRAP — 芯片手册 RAG 知识库

本机芯片手册检索知识库（RAG）：PDF 经 MinerU 解析 → 分块 → FTS5 + 向量混合召回 → RRF 融合 → 原页核验，按芯片/修订版查寄存器、时序、引脚与电气参数，附 PDF 原页出处。

## 结构

- `ChipManualDesk-1.0.2/` — 桌面应用 + 后端（`chiprag`，本地 MinerU + SQLite 混合检索）
- `eval/` — 检索层 Eval 框架（黄金集 + 确定性评测脚本）
- `mcp/` — MCP server（把检索暴露成 agent 可驱动的 status/search/read/page）
- `skill/` — `chip-manual-rag` skill（供 Codex / Claude Code 使用）
- `llms.txt` — agent 发现入口
- `芯片手册知识库-技术原理详解.md` — 技术原理（含本次整合变更）

## 快速开始

1. `ChipManualDesk-1.0.2\Install.cmd`（联网下载运行环境与模型）
2. 解析 PDF 入库 → 用 `status` / `search` 检索
3. Eval：`python eval\run_eval.py --self-test`
4. MCP：`python mcp\mcp_server.py`

## 相关仓库

- [framework-kb](https://github.com/hpsks416/framework-kb) — DSH 框架内容的知识库（FTS5 + 向量 + RRF 检索 + 接地契约 + MCP），用本项目的 RAG 方法建成

## License

MIT
