---
name: framework-kb
description: 检索本机 DSH 框架知识库（铁律 AGENTS.md、persona 画像、全部 skill、meta-drift-log、HANDOFF），用 framework-kb/search_kb.py 按关键词+向量找回规则原文，供 agent 准确对齐框架约束。Use when 需要查「本机框架有哪些铁律/规则/skill/画像约定」或回答「按框架该怎么写/怎么做」。
---

# Framework KB（框架知识库检索）

把 DSH 框架内容（铁律 + 画像 + 全部 skill + 偏离日志 + 交接文档）做成本地可检索知识库，agent 用 `search_kb.py` 找回规则**原文**再回答，不靠记忆臆测框架规则。

## 运行

```powershell
$env:PYTHONPATH = "G:\CodexDS\DSH\INTRO\framework-kb\pylibs"
python "G:\CodexDS\DSH\INTRO\framework-kb\search_kb.py" "查询内容" --top 8
```

返回 JSON：每条 `{source, tag, section, text, score, keyword_hit, vector_hit}`，`source`/`section` 是出处，`text` 是原文片段。

## 接地回答契约（铁律，违反即失效）

1. **只答检索到的原文**：每个结论必须来自 `text` 片段，禁止凭训练记忆补框架规则。
2. **必引出处**：引用 `source`（如 `AGENTS.md`、`skill:xxx/SKILL.md`）+ `section`，让结论可追溯、可核对。
3. **规则必带条件**：铁律/约束往往有触发判据和边界（如「先申请后执行」「判重读版本差异」），照原文条件说，不脱条件断章。
4. **证据不足必承认缺口**：检索不到就明说「框架里没有这条」，不编一条像样的规则。
5. **禁止跨源/跨版本混用**：不同 skill 的同名项可能版本不同（v1/v2 规格），不把 A 源结论套到 B 源。

## 核验闭环

1. 先 `search_kb.py` 召回候选 → 2. 逐条读 `text` 核对是否真的支持结论 → 3. 命中则引用原文；不足则换关键词/换 `section` 再搜一次 → 4. 仍不足则承认缺口，不硬凑。

## 已知坑（框架里高频误用点，检索时优先覆盖）

- 铁律一「动手前先检索现成轮子」；判重必须读到版本/规格差异，不能同名判重。
- 铁律二「收尾反思」：先申请后执行，最终裁决在用户；决策询问用选项弹窗（`ask_user_question`），禁止文字问决策。
- 授权处理 ≠ 授权选具体方案：说「处理某问题」只授权动作，不授权选方案。
- 提示重启/改环境必须附日志完整路径（`startup-*.log` 等）。
- skill 用法细节易错（如继承对话名的用法）；accept 候选前必须先检索核实。

## 边界

- 只读检索，不改框架文件。知识库由 `build_kb.py` 重建。
- 检索结果是**原文证据**，不是裁决；框架规则的最终解释权在用户。
