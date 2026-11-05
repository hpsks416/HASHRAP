# HASHRAP — 框架知识库转化方法（RAG 管线）

把原始文档（框架规则 / 手册 / 任意文本）转成可检索知识库的**转化方法**：解析 → 分块 → FTS5 关键词索引 + 向量化 → RRF 混合召回 → 跨编码器精排，附原文出处。

转化产物（如 DSH 框架知识库）放在 [agent-deployed](https://github.com/hpsks416/agent-deployed) 仓库；本仓库只放转化方法本身。

## 结构

- `build_kb.py` — 收集文档 → 分块 → FTS5 + 向量化 → `*.sqlite3`
- `search_kb.py` — 检索（FTS5 BM25 + 向量余弦 + RRF + bge-reranker 精排；`--lexical-only --no-rerank` 关闭模型）
- `test_kb.py` — 召回效果测试（top-k 命中预期 source）
- `eval/` — 检索层 Eval 框架（黄金集 + 确定性评测脚本）
- `mcp/` — MCP server（把检索暴露成 agent 可驱动的接口）
- `llms.txt` — agent 发现入口
- `examples/chip-manual/` — 一个完整用例：芯片手册 RAG（桌面应用 ChipManualDesk + skill），演示本管线的落地用法

## 快速开始

```powershell
# 构建（首次；需 pylibs 依赖 + 嵌入模型，见 agent-deployed 的构建说明）
$env:PYTHONPATH = "$PWD\pylibs"
python build_kb.py

# 检索（纯关键词，不加载模型）
python search_kb.py "判重读版本差异" --lexical-only --no-rerank
```

## 相关仓库

- [agent-deployed](https://github.com/hpsks416/agent-deployed) — 经本管线转化好的 DSH 框架知识库（含检索 skill 与接地回答契约）

## License

MIT
