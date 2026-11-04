# ChipManualDesk 检索层 Eval

这是给 ChipManualDesk 补的「系统性检索召回率评测」框架（对应技术原理文档第 21 节自认的缺口）。**只测检索层，不测生成层幻觉**。

## 测什么

| 检查项 | 含义 | 判定 |
|---|---|---|
| `must_contain` | 期望寄存器/术语应被召回 | 任一 top-k 结果文本并集含全部术语即过（recall@k） |
| `must_not_contain` | 禁止标记（错误系列/版本）不应出现 | top-k 全无即过（precision / 防混） |
| `expected_section` | 命中应落在期望章节 | 任一结果章节路径含片段即过 |
| `expected_page` | 命中应落在期望页码 | 任一结果 `page` 相等即过（引用精度） |
| `revision_filter` / `chip_filter` | 过滤生效 | 所有结果 revision/chip 匹配请求 |

报告按「类别」分域（register_config / timing / pin_mux / param_table / version_diff / precision / honest_gap），**不只看总平均**——跨类别平均最无指导意义。

## 前置条件

- 已安装 ChipManualDesk（`Install.cmd` 完成，含模型）。
- 已索引至少一本手册（状态 `ready`），如 RM0433 Rev 9。

## 运行

```powershell
# 1) 先自检评分逻辑（无需后端，任何 Python 3 都可）
python run_eval.py --self-test

# 2) 真实跑（混合召回基线，不重排）
python run_eval.py `
  --python 'C:\Users\<你>\AppData\Local\ChipManualDesk\runtime\venv\Scripts\python.exe' `
  --backend 'C:\Users\<你>\...\ChipManualDesk\backend' `
  --data 'C:\Users\<你>\Documents\ChipManualLibrary' `
  --golden golden.json --report report.md

# 3) 开重排跑（需英文改写 + reranker 模型）
python run_eval.py --python ... --data ... --rerank
```

`--python` 缺省用当前 `sys.executable`；`--backend` 缺省自动定位到 `RAP/ChipManualDesk-1.0.2/backend`。

## 怎么扩充黄金集

按 `golden.json` 的 `cases` 结构追加。三原则：

1. **术语必须是真实文本**：先手动 `search` 一次，看寄存器名在解析结果里怎么呈现（`fADC` 可能渲染成 `f ADC`），再填 `must_contain`。
2. **页码后补**：`expected_page` 先留 `null`，对照原手册核实页码后填入，就能自动校验页码级引用精度。
3. **来自真实工作**：优先用裁判系统历史 bug、容易配错的寄存器、版本差异坑题，而非我这份起步集。

## 边界（诚实声明）

- 这是**检索层** eval：召回/定位/引用/版本约束/过滤。宿主 AI 是否编造答案（生成层幻觉）不在此测，需宿主 AI + judge。
- 子串匹配会过度匹配（如 `PA0` 命中 `PA01`）；起步集术语足够具体，可接受，后续可换整词匹配。
- 本框架在本仓库内**尚未对真实索引跑过**（本机无 ChipManualLibrary 与模型），`--self-test` 已自证评分逻辑正确；真实数字需在你的安装机上跑。
