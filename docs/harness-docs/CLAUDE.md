# Project: DeerFlow SDK 抽离

> **这是引导文件**。任何新 session 打开此目录工作时，**第一步读这个文件**，**第二步读 `03-status/progress.md`**，知道当前状态。

## 项目一句话

把 `backend/packages/harness/deerflow`（**框架+应用混合**）抽离成 **feature-rich + brand-neutral** 的通用 Python SDK。

## 关键约束（必须严格遵守）

1. **SDK 是 feature-rich 的**：任务规划、长期记忆、多 agent 协同、文件管理、沙箱、安全审计、Skills、MCP 全部保留
2. **SDK 是 brand-neutral 的**：所有 DeerFlow 业务选择（路径名、字段名、工具名、prompt 文案）必须可注入
3. **不修改 `backend/` 任何现有代码** —— 我们只往 `sdk-extraction/` 里新增
4. 抽离后 `/sdk-extraction/harness/` 是一个完整的、可独立 `pip install` 的 SDK

## 文档结构

```
sdk-extraction/
├── docs/                          # ← 你在这里
│   ├── CLAUDE.md                  # 本文件（每次新会话必读）
│   ├── README.md                  # 项目说明
│   ├── 00-vision/                 # WHY - 为什么
│   ├── 01-design/                 # WHAT - 怎么设计
│   ├── 02-plan/                   # HOW - 怎么分步
│   ├── 03-status/                 # NOW - 当前状态
│   ├── 04-specs/                  # DETAIL - 详细规格
│   └── 05-archive/                # 历史文档
└── harness/                       # SDK 输出（最终是完整 Python 包）
    ├── README.md
    ├── pyproject.toml
    └── agent_sdk/             # 包代码（扁平布局，import 路径：from agent_sdk import ...）
```

## 文档阅读顺序

1. `00-vision/goals.md` - 项目目标
2. `00-vision/scope.md` - 范围
3. `01-design/architecture.md` - 总体架构
4. `01-design/sdk-boundary.md` - L1/L2/L3 定义
5. `01-design/feature-inventory.md` - SDK 特性清单
6. `02-plan/phases.md` - 阶段划分
7. `03-status/progress.md` - 当前进度
8. `03-status/decisions.md` - 决策日志

## 关键历史文档

- `05-archive/HARNESS_PACKAGE_ANALYSIS.md` - 16 个子目录的结构化分析
- `05-archive/HARNESS_BUSINESS_COUPLING.md` - 业务耦合度分析（5 个耦合层面）

## 工作流程

1. **开工前**：
   - 读 `03-status/progress.md` 知道当前阶段
   - 读 `03-status/decisions.md` 知道历史决策
2. **工作中**：
   - 用 TaskCreate/TaskUpdate 跟踪活跃任务
   - 严格不修改 `backend/` 任何代码
3. **收工时**：
   - 更新 `03-status/progress.md` 标记完成项
   - 如有新决策，在 `03-status/decisions.md` 加 ADR
   - 关键变更记录到 `03-status/changelog.md`

## 关键决策（截至 2026-07-03）

| 编号 | 标题 | 状态 |
|------|------|------|
| ADR-001 | SDK 定位为 "feature-rich + brand-neutral" | ✅ 已确认 |
| ADR-002 | L1/L2/L3 三层定义 | ✅ 已确认 |
| ADR-003 | 阶段 1 优先做 PathProvider 抽象 | ✅ 已确认 |
| ADR-004 | 抽离期间不动 `backend/` 现有代码 | ✅ 已确认 |
| ADR-005 | 新建 `sdk-extraction/` 目录，不在 `backend/` 内 | ✅ 已确认 |
| ADR-006 | SDK 输出为 `sdk-extraction/harness/` 目录 | ✅ 已确认 |
| ADR-007 | SDK 采用扁平布局（无 `src/` 嵌套） | ❌ 已撤回（被 ADR-008 取代） |
| ADR-008 | SDK 包名为 `agent-sdk`，包目录为 `harness/agent_sdk/` | ✅ 已确认 |
| ADR-009 | SDK 物理目录从 `agent/` 重命名为 `harness/` | ✅ 已确认 |

详见 `03-status/decisions.md`。

## SDK 输出位置

`sdk-extraction/harness/` —— 最终是完整的 Python 包。

## 联系/反馈

- 当前负责人：（开发者）
- 项目状态：见 `03-status/progress.md`
- 下次开会前必读：`03-status/blockers.md`
