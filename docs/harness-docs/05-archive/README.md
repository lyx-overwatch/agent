# 历史分析文档（Archive）

> 本目录保存项目前期的分析文档，作为决策依据可追溯。
> 这些文档**不会被更新**，如有新分析应写到 `01-design/` 或 `02-plan/`。

## 文档列表

| 文档 | 创建于 | 说明 |
|------|--------|------|
| [`HARNESS_PACKAGE_ANALYSIS.md`](HARNESS_PACKAGE_ANALYSIS.md) | 2026-07-03 | `deerflow-harness` 包的结构化分析（16 个子目录 + 顶层文件） |
| [`HARNESS_BUSINESS_COUPLING.md`](HARNESS_BUSINESS_COUPLING.md) | 2026-07-03 | DeerFlow 业务耦合度分析（5 个耦合层面） |

## 这两份文档的作用

### HARNESS_PACKAGE_ANALYSIS.md
- 1341 行，~62KB
- 包含：每个子目录的目录树、核心职责、关键类/函数、依赖关系、抽离价值
- 是阶段 1-4 抽离工作的**参考依据**
- 提供了"哪些是 L3 通用"、"哪些是 L1 业务"的初步分类

### HARNESS_BUSINESS_COUPLING.md
- 详细分析了 5 个业务耦合层面：概念层、状态层、路径层、中间件层、工具层
- 包含：模块级耦合矩阵、目标目录结构、4 个关键问题
- 早期版本（已被 ADR-001 修正）

## 早期认知的演进

这两个文档代表了我们对"业务"理解的演进：

| 版本 | 认知 | 问题 |
|------|------|------|
| 早期 | 任何 DeerFlow 写过的代码都是业务 | 太宽，特性也被砍掉 |
| ADR-001 修正 | 业务 = 换成别的产品不会这样写的选择 | 正确的分层 |

ADR-001/ADR-002 修正后的 L1/L2/L3 定义见 [`01-design/sdk-boundary.md`](../01-design/sdk-boundary.md)。

## 引用方式

在新文档中引用历史分析时：

```markdown
> 详见历史分析 [`05-archive/HARNESS_PACKAGE_ANALYSIS.md`](HARNESS_PACKAGE_ANALYSIS.md) 第 X 节。
```

不要直接复制大段内容，而是引用 + 总结。
