---
name: rag
description: 把一组文本语料（框架规则 / 文档 / 代码库等）建成本地可检索 RAG 知识库——分块 + FTS5 关键词 + 向量化 + RRF 混合检索，配「接地回答契约」检索接口。Use when 需要把本地框架/文档内容做成 agent 可检索的知识库，或回答「怎么建 RAG 知识库」「向量化+排序怎么做」。
---

# RAG（把语料建成可检索知识库）

把一组 Markdown/文本语料（如 DSH 框架的 `AGENTS.md` / `persona.md` / 全部 `SKILL.md`）建成本地可检索知识库，让 agent 按**原文**检索而非靠记忆。

## 复用轮子（铁律一，不重造）

- 关键词排序：SQLite FTS5（BM25，stdlib）。
- 向量：`fastembed`（onnxruntime 后端，多语言 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`）。
- 混合融合：RRF（Reciprocal Rank Fusion，`1/(60+rank)`）。
- 现成模板：`G:\CodexDS\DSH\INTRO\framework-kb\` 下的 `build_kb.py` / `search_kb.py` / `mcp_server.py`，复制改语料路径即可。

## 流程

1. **收集语料**：列出 Markdown/文本文件清单（如框架核心文档 + 全部 SKILL.md）。
2. **分块**：按标题（`#`~`###`）分段，段内按长度切（约 900 字符 + 100 重叠），保留 section 元数据。
3. **索引**：FTS5 关键词（英文/数字 token + 中文相邻双字 bigram）+ 向量化（归一化 float32 存 BLOB）。
4. **检索**：FTS5 BM25 + 向量余弦 → RRF 融合 → top-k，返回带 `source`/`section` 的原文。
5. **接地契约**：配检索 skill——只答证据、必引出处、数值带条件、证据不足承认缺口、禁跨源/跨版本混用。

## 已知坑（本机实测，避免重踩）

- Store Python 只读 site-packages + pip 的 urllib3 会挂 + schannel 报 `SEC_E_NO_CREDENTIALS` → 用 `uv pip install --target <dir> --python 3.11`（uv 的 rustls 绕开三坑）。
- PyPI 走清华镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple`；HF 模型走 `HF_ENDPOINT=https://hf-mirror.com`。
- MCP：用 `mcp<2`（2.x 把 FastMCP 改名为 MCPServer）；pywin32 用 `--target` 装后要补 `sys.path`（`win32`、`win32/lib`、`pywin32_system32` 三个路径）。
- 大二进制/缓存/库目录（`.venv`/`pylibs`/`models`/`*.sqlite3`/`.uv-cache`）必须 `.gitignore` 排除。

## 参考实现

`G:\CodexDS\DSH\INTRO\framework-kb\`：
- `build_kb.py`（构建）、`search_kb.py`（检索）、`mcp_server.py`（MCP 暴露 `search` + `tool://skill`）
- `SKILL.md`（接地回答契约 + 核验闭环 + 已知坑）、`grounded-rag-template.md`（通用「有据可依」模板）

## 边界

- 本 skill 只描述「如何建 RAG 知识库」；具体某次建库用 `build_kb.py` 执行，检索用 `search_kb.py` 或 MCP。
- 建库不改变框架原文；知识库是框架内容的**索引快照**，框架更新后需 `build_kb.py` 重建。
