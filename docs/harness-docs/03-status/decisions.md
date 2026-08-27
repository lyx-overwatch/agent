# 决策日志（ADR - Architecture Decision Records）

> 记录项目关键决策。每个决策包含背景、决定、影响。
> 格式参考 [Michael Nygard 的 ADR 模板](https://github.com/joelparkerhenderson/architecture-decision-record)。

## 索引

| 编号 | 标题 | 日期 | 状态 |
|------|------|------|------|
| [ADR-001](#adr-001-sdk-定位为-feature-rich--brand-neutral) | SDK 定位为 "feature-rich + brand-neutral" | 2026-07-03 | 已确认 |
| [ADR-002](#adr-002-l1l2l3-三层重定义) | L1/L2/L3 三层重定义 | 2026-07-03 | 已确认 |
| [ADR-003](#adr-003-阶段-1-优先做-pathprovider-抽象) | 阶段 1 优先做 PathProvider 抽象 | 2026-07-03 | 已确认 |
| [ADR-004](#adr-004-抽离期间不动-backend-现有代码) | 抽离期间不动 `backend/` 现有代码 | 2026-07-03 | 已确认 |
| [ADR-005](#adr-005-新建-sdk-extraction-目录不在-backend-内) | 新建 `sdk-extraction/` 目录，不在 `backend/` 内 | 2026-07-03 | 已确认 |
| [ADR-006](#adr-006-sdk-输出为-sdk-extractionagent-目录) | SDK 输出为 `sdk-extraction/harness/` 目录 | 2026-07-03 | 已确认 |
| [ADR-007](#adr-007-sdk-采用扁平布局无-src-嵌套) | SDK 采用扁平布局（无 `src/` 嵌套） | 2026-07-03 | 已撤回（被 ADR-008 取代） |
| [ADR-008](#adr-008-sdk-包名为-agent-sdk-包目录为-agent_sdk) | SDK 包名为 `agent-sdk`，包目录为 `harness/agent_sdk/` | 2026-07-03 | 已确认（被 ADR-009 部分覆盖） |
| [ADR-009](#adr-009-sdk-物理目录从-agent-重命名为-harness) | SDK 物理目录从 `agent/` 重命名为 `harness/` | 2026-07-03 | 已确认 |
| [ADR-010](#adr-010-抽离策略-重新实现-不是-代码搬运) | 抽离策略 = 重新实现（Re-implementation），不是代码搬运（Code Mover） | 2026-07-06 | 已确认 |
| [ADR-011](#adr-011-错误消息与工具描述-brand-neutral-化) | 错误消息与工具描述 brand-neutral 化（剥离 DeerFlow 业务文案） | 2026-07-07 | 已确认 |

---

## ADR-001: SDK 定位为 "feature-rich + brand-neutral"

**日期**: 2026-07-03
**状态**: 已确认

### 背景

最初我们提议把 SDK 削成"最小 agent + opt-in 特性"——但实际上 DeerFlow 的特性（任务规划、长期记忆、多 agent、文件管理、沙箱、审计、Skills、MCP）都是必要的。如果 SDK 只是个空壳，用户自己用 LangGraph 写就行，没必要用 SDK。

我们也犯过一个相反错误：把"特性"当成"业务耦合"砍掉，导致 SDK 没有实用价值。

### 决定

SDK 保留所有 agent 特性（**feature-rich**），但所有 DeerFlow 业务选择（**brand-neutral**）通过 Protocol/参数注入。

### 影响

- 抽离工作量从 8-10 周降到 5-6 周
- SDK 体积更大但更实用
- 用户可以选择启用哪些特性（通过 `RuntimeFeatures`）
- 业务选择通过 preset 注入，避免硬编码

### 关键修正

- ❌ **错误**：把"特性"当"业务"砍掉（如把 `ThreadDataMiddleware` 移到 preset）
- ✅ **正确**：保留特性（如 `ThreadDataMiddleware`），但业务耦合（如 `/mnt/user-data` 路径）通过 Protocol 注入

---

## ADR-002: L1/L2/L3 三层重定义

**日期**: 2026-07-03
**状态**: 已确认

### 背景

最初的 L1/L2/L3 分类混淆了"特性"和"业务选择"：

| 错误分类 | 正确分类 |
|----------|----------|
| `ThreadDataMiddleware` = L1 业务 | `ThreadDataMiddleware` = L2 特性（per-thread workspace 概念通用） |
| `MemoryMiddleware` = L1 业务 | `MemoryMiddleware` = L2 特性（长期记忆概念通用） |
| `SandboxAuditMiddleware` = L1 业务 | `SandboxAuditMiddleware` = L2 特性（命令审计概念通用） |

### 决定

重新定义 L1/L2/L3：

- **L1 业务耦合**：路径前缀、数据模型字段、工具名、prompt 文案
  - 例：`/mnt/user-data`、`workContext`、`ask_clarification`、`"You are an open-source super agent"`
  - 抽离方式：通过 Protocol/参数注入

- **L2 特性 + 可配置业务**：特性逻辑保留，业务选择可注入
  - 例：`ThreadDataMiddleware` + `PathProvider`、`MemoryMiddleware` + `MemorySchema`
  - 抽离方式：特性在 SDK，业务通过 Protocol 注入

- **L3 纯通用**：任何 agent runtime 都需要
  - 例：5 个通用 middleware、Sandbox ABC、MemoryStorage ABC
  - 抽离方式：直接抽到 SDK

### 影响

所有"特性"都在 SDK 保留。所有"业务耦合"都通过 Protocol 注入。SDK 不是一个空壳，而是一个**功能完整**的 agent runtime。

---

## ADR-003: 阶段 1 优先做 PathProvider 抽象

**日期**: 2026-07-03
**状态**: 已确认

### 背景

`/mnt/user-data` 硬编码在 9+ 个文件里，是耦合最广的硬编码：
- `sandbox/tools.py`（1582 行）
- `config/paths.py`
- `uploads/manager.py`
- `ThreadDataMiddleware`
- `UploadsMiddleware`
- `present_file_tool`
- `view_image_tool`
- `invoke_acp_agent_tool`
- `sandbox/middleware.py`

解开 PathProvider 抽象能为后续所有抽离提供参考模式（业务耦合 → Protocol 注入）。

### 决定

阶段 1（2 周）优先做 `PathProvider` 抽象，作为 SDK 第一个 Protocol。

### 风险

- **高**：`sandbox/tools.py` 1582 行迁移可能引入 bug
- **中**：路径边界情况（symlink、相对路径、UNC 路径）
- **中**：DeerFlow 回归测试可能不充分

### 应对

- 保持原逻辑不变，只替换路径来源
- 分小批迁移
- 单元测试覆盖所有边界情况
- 阶段开始前先跑基线测试

---

## ADR-004: 抽离期间不动 `backend/` 现有代码

**日期**: 2026-07-03
**状态**: 已确认

### 背景

抽离是结构性工作，应该与 DeerFlow 应用解耦，避免破坏现有功能。DeerFlow 是一个正在运行的应用，抽离过程中任何代码修改都可能导致回归。

### 决定

抽离期间 `backend/` 任何现有代码**完全不动**。所有工作只在 `sdk-extraction/` 内新增。

### 例外情况

只有在以下情况才能修改 `backend/`：
1. SDK 发布后 DeerFlow 应用迁移使用 SDK（这是另一阶段，不在抽离 PR 范围）
2. 抽离过程中发现现有代码 bug，可**最小化**修复（需在 PR 描述中说明）

### 影响

- 抽离工作可分阶段进行，每阶段结束 DeerFlow 都正常工作
- 抽离完成后，DeerFlow 通过 preset 保持原行为
- 旧代码与新 SDK 可共存

### 验证

- `sdk-extraction/harness/` 是独立可发布的 Python 包
- DeerFlow 应用保持原样运行
- SDK 通过 preset 与 DeerFlow 解耦

---

## ADR-005: 新建 `sdk-extraction/` 目录，不在 `backend/` 内

**日期**: 2026-07-03
**状态**: 已确认

### 背景

抽离工作涉及大量新文件（规划文档、SDK 代码、测试）。如果放在 `backend/` 内会与 DeerFlow 应用代码混在一起，造成混淆。

### 决定

新建顶层目录 `sdk-extraction/`（在项目根，与 `backend/`、`frontend/` 平级）。

```
D:\registry\source\deer-flow\
├── backend/                # DeerFlow 应用
├── frontend/               # DeerFlow 前端
├── sdk-extraction/         # SDK 抽离（新）
│   ├── docs/              # 规划文档
│   └── agent/             # SDK 输出
└── ...
```

### 优势

- 与 `backend/` 物理隔离，避免混淆
- 抽离完成后，`sdk-extraction/harness/` 可独立 `pip install`
- 文档与代码分离，结构清晰

### 未来选项

- 抽离完成后，可将 `sdk-extraction/harness/` 移到独立仓库（如 `github.com/.../agent-sdk`）
- 但目前保持 monorepo 便于管理

---

## ADR-006: SDK 输出为 `sdk-extraction/harness/` 目录

**日期**: 2026-07-03
**状态**: 已确认

### 背景

抽离完成后，SDK 应该是一个独立的 Python 包，可 `pip install` 到任何项目。

### 决定

SDK 物理输出位置为 `sdk-extraction/harness/`：

```
sdk-extraction/harness/
├── README.md              # SDK 文档
├── pyproject.toml         # 包配置
├── CHANGELOG.md           # 变更日志
├── agent_sdk/             # SDK 包代码（扁平布局）
│   ├── __init__.py
│   ├── runtime/
│   ├── paths/
│   ├── features/
│   └── ...
└── tests/                 # 单元测试
```

最终结构是扁平布局的 Python 包，可：
- `pip install -e sdk-extraction/harness/`（开发模式）
- `pip install sdk-extraction/harness/`（生产模式）
- 抽离完成后可独立发布

### 影响

- SDK 包采用**扁平布局**（无 `src/` 嵌套），import 路径直接对应包名
- 包名：`agent-sdk`（PyPI 名）
- import 路径：`agent_sdk`（包内）
- DeerFlow 应用通过 `from agent_sdk import create_agent` 使用 SDK

### 为什么不用 src/ 布局

- 减少一层目录嵌套
- 抽离阶段代码还不稳定，避免 `src/` 布局的"防本地导入"机制带来的认知负担
- 后期如需切换到 `src/` 布局，路径调整成本低

### Preset 位置

`agent_sdk.presets.deerflow` 在 SDK 包**内部**（不是独立包），方便 DeerFlow 用户一行 import。

---

## ADR-007: SDK 采用扁平布局（无 `src/` 嵌套）

**日期**: 2026-07-03
**状态**: 已撤回（被 ADR-008 取代）

### 背景

最初采用标准 `src/` 布局（`agent/src/deerflow/`），但这样 SDK 包多了一层目录嵌套，路径不直观。所以改成扁平布局 `agent/deerflow/`，但包名仍是 `deerflow`。

### 后续修正

见 ADR-008。包目录依然是扁平的 `agent/agent_sdk/`，但包名改为 `agent-sdk`（避免 DeerFlow 品牌），import 路径从 `from deerflow import ...` 变为 `from agent_sdk import ...`。

---

## ADR-008: SDK 包名为 `agent-sdk`，包目录为 `agent_sdk/`

**日期**: 2026-07-03
**状态**: 已确认

### 背景

之前的命名沿用 DeerFlow 品牌（包名 `deerflow-sdk`、包目录 `deerflow/`），但既然 SDK 是 brand-neutral 的（ADR-001），就应该用更中性的名字。

最初我们尝试过 `agent/src/__init__.py`（让 `src/` 本身做包名），但这会让 `from src import ...` 看起来像 `src/` 关键字布局而非普通包名，容易引起混淆。

也试过 `agent/src/agent_sdk/`（标准 `src/` 布局 + 命名包），但因为包目录已经叫 `agent`，再套一层 `src/` 是多余的嵌套。

### 决定

- **PyPI 包名**：`agent-sdk`（连字符）
- **包目录**：`agent/agent_sdk/`（扁平布局，无 `src/` 嵌套）
- **import 路径**：`from agent_sdk import ...`（用下划线，Python 标识符合法）

```
sdk-extraction/harness/
├── README.md
├── pyproject.toml
├── CHANGELOG.md
└── agent_sdk/         # 实际的 Python 包（扁平布局）
    ├── __init__.py
    ├── runtime/
    ├── paths/
    └── ...
└── tests/
```

`pyproject.toml`：
- `name = "agent-sdk"`（PyPI 名）
- `packages = ["agent_sdk"]`（Hatch 构建目标）

### 影响

- 避免 DeerFlow 品牌绑定，SDK 真正 brand-neutral
- 扁平布局，无多余嵌套
- import 路径从 `from deerflow import ...` 变为 `from agent_sdk import ...`
- 所有 doc 文档和 import 示例已同步更新

### 用法对比

```python
# 抽离前（deerflow-sdk）
from deerflow import create_agent

# 抽离后（agent-sdk）
from agent_sdk import create_agent
from agent_sdk.presets.deerflow import DeerFlowAgent
```

### 关于命名

- PyPI 用 `agent-sdk`（连字符，PyPI 允许）
- Python import 用 `agent_sdk`（下划线，Python 标识符要求）
- 这是 Python 生态的标准做法（如 `pip install pydantic-settings` → `import pydantic_settings`）

---

## ADR-009: SDK 物理目录从 `agent/` 重命名为 `harness/`

**日期**: 2026-07-03
**状态**: 已确认

### 背景

之前 SDK 物理目录叫 `sdk-extraction/agent/`，但这与 DeerFlow 项目的命名风格不一致：
- DeerFlow 现有结构是 `backend/packages/harness/deerflow/`（harness 是包名，deerflow 是其中的 SDK）
- 我们抽离的目标是 `harness/deerflow` 中的 SDK 部分
- 因此抽离产物应该放在 `sdk-extraction/harness/` 下（harness 是包名，agent_sdk 是其中的 SDK）

### 决定

物理目录：`sdk-extraction/agent/` → `sdk-extraction/harness/`

```
sdk-extraction/
├── docs/
└── harness/                  # ← SDK 物理目录（PyPI 包：agent-sdk）
    ├── README.md
    ├── pyproject.toml
    ├── CHANGELOG.md
    └── agent_sdk/            # ← 实际 import 的包
        └── __init__.py
```

注意：
- **包名（PyPI）不变**：`agent-sdk`
- **import 路径不变**：`from agent_sdk import ...`
- **只改物理目录名**：`agent/` → `harness/`

### 影响

- 命名风格与 DeerFlow 现有结构对齐（`harness/deerflow` → `harness/agent_sdk`）
- 所有 doc 文档的路径引用已同步更新（`sdk-extraction/agent/` → `sdk-extraction/harness/`）
- pyproject.toml 中的 `packages = ["agent_sdk"]` 不变（因为是相对路径）
- ADR-008 状态保留，但物理目录路径已更新

### 命名层次

| 层级 | 名字 | 解释 |
|------|------|------|
| 物理包目录 | `sdk-extraction/harness/` | 抽离项目的根 |
| Python 包名（import） | `agent_sdk` | 实际 import 的包 |
| PyPI 包名 | `agent-sdk` | pip install 的名字 |

三层独立，互不耦合。

---

## ADR-010: 抽离策略 = 重新实现（Re-implementation），不是代码搬运（Code Mover）

**日期**: 2026-07-06
**状态**: 已确认

### 背景

阶段 1-4 的原始计划文档普遍使用"**修改** `backend/sandbox/tools.py`"、"**迁移** `tools/builtins/*.py` 到 `presets/deerflow/tools/`"等措辞。系统审计发现这与 ADR-004（抽离期间完全不动 `backend/`）**严重冲突**：

- 阶段 1：6 处冲突
- 阶段 2：5 处冲突
- 阶段 3：6 处冲突
- 阶段 4：12 处冲突
- 阶段 5：2 处冲突
- `feature-inventory.md`：1 处语义冲突

冲突根源：计划文档作者把"抽离"误解为"逐步替换 backend/ 中的代码"（Code Mover 思路），而架构文档作者理解的"抽离"是"在 SDK 内部镜像实现"（Re-implementation 思路）。

### 决定

**抽离策略 = 重新实现（Re-implementation）**，**禁止代码搬运（Code Mover）**。

#### 禁止项

1. ❌ 禁止 `git mv`、`cp` 等方式把 `backend/` 文件搬到 `sdk-extraction/`
2. ❌ 禁止 `from backend.* import ...`、`from app.* import ...`、`from deerflow.* import ...` 在 SDK 任何模块中
3. ❌ 禁止复制粘贴 `backend/` 现有文件作为 SDK 源文件
4. ❌ 禁止修改 `backend/` 任何现有文件（包括测试代码、fixture、`conftest.py`）
5. ❌ 禁止为修复 `backend/tests/` 失败而修改 `backend/tests/`

#### 允许项

1. ✅ SDK 内部可以 Read `backend/` 文件作为**行为参考**
2. ✅ SDK 内部可以使用**离线录制的 golden fixture**（来自 `backend/` 真实输出的快照，**不引用** `backend.*`）作为字节级对比对象
3. ✅ Golden fixture 放在 `sdk-extraction/harness/tests/fixtures/`
4. ✅ 可以跑 `backend/tests/` 做基线回归（**只跑不改**）
5. ✅ 抽离 PR 完成后，DeerFlow 应用切换到 preset 的迁移属于**后续应用迁移 PR**

#### SDK 内部每个文件都是新写的

- 行为可以**与 `backend/` 字节级一致**（通过 golden fixture 验证）
- 实现可以是**任何形式**（不要求与 `backend/` 字面相同）
- 默认 prompt 是**无 DeerFlow 业务假设的最小通用文案**（与 `backend/` 业务文案**完全分离**）

### 影响

- 阶段 1-5 的所有"修改/迁移 backend/ 文件"措辞统一改为"在 sdk-extraction/ 内重新实现"
- 阶段 4 "DeerFlow Preset 抽离"重新定义为"在 sdk-extraction/ 内新建 DeerFlow Preset"
- 阶段 5 "DeerFlow 应用切换"任务移到 `00-vision/post-extraction-roadmap.md`（后续应用迁移 PR）
- 所有阶段计划文档的"成功标准"加上"**`backend/` 全程未触碰**"硬性要求

### 抽离 PR 边界

**抽离 PR 范围**：
1. 在 `sdk-extraction/harness/` 内新建 Python 包 `agent-sdk`
2. 包含 4 个 Protocol + 5 个通用 middleware + SDK 特性 + DeerFlow preset
3. SDK 内部 100% 测试通过
4. `backend/tests/` 跑通基线（**不修改**）

**不在抽离 PR 范围**（后续应用迁移 PR）：
1. 修改 `backend/` 让 DeerFlow 应用 import `agent_sdk.presets.deerflow`
2. 删除 `backend/packages/harness/deerflow/` 中已被 SDK 替代的代码
3. 更新 `langgraph.json` / `config.yaml` 让 DeerFlow 使用新 SDK 入口
4. 真正的"`DeerFlowClient` → `DeerFlowAgent`"切换
5. 端到端"DeerFlow 应用通过 preset 使用 SDK"测试

### 验证

- 所有 `sdk-extraction/harness/agent_sdk/` 模块**没有** import `backend.*`、`app.*`、`deerflow.*`
- 所有 golden fixture 字节级匹配
- `backend/tests/` 基线回归通过（仅跑，不修改）
- 抽离 PR 完成后 `git diff backend/` 输出为空

---

## ADR-011: 错误消息与工具描述 brand-neutral 化（剥离 DeerFlow 业务文案）

**日期**: 2026-07-07
**状态**: 已确认

### 背景

- ADR-001 定位 SDK 为 "feature-rich + brand-neutral"
- ADR-010 重新实现策略规定 SDK 不耦合 DeerFlow 全局 config
- 阶段 5.7 adversarial 体检（`docs/03-status/changelog.md` 2026-07-07 session）发现：
  - `LOCAL_HOST_BASH_DISABLED_MESSAGE` 含 "AioSandboxProvider"（DeerFlow 私有沙箱名）+ "sandbox.allow_host_bash"（DeerFlow config key）
  - `LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE` 同样含品牌名
  - bash 工具 docstring 提到 `/mnt/user-data/workspace/.venv`（DeerFlow 约定路径 + 约定目录名）

这些文案由 5.7 阶段从 backend verbatim 复制过来（brief 写"verbatim 保留以保持 LLM 提示一致"），但与 brand-neutral 目标直接冲突。

### 决定

1. **错误消息 brand-neutral 化**：
   - 新增 `LOCAL_BASH_DISABLED_MESSAGE_FALLBACK`（默认 brand-neutral 文案）
   - `LOCAL_HOST_BASH_DISABLED_MESSAGE` / `LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE` 保留为 backward-compat alias（指向新 fallback，docstring 标注 deprecated）
   - `HostBashPolicy` 协议增加 `disabled_message: str` property
   - `DefaultHostBashPolicy.disabled_message` 返回 brand-neutral fallback
   - `ConfigurableHostBashPolicy(disabled_message=...)` 允许产品注入品牌特定文案

2. **工具 description 模板化**：
   - bash 等工具的 docstring 用占位符（如 `{python_venv_hint}`）
   - `SandboxToolsConfig.python_venv_hint` 字段提供默认值（`<virtual_path_prefix>/workspace/.venv`）
   - 阶段 4 DeerFlow preset 注入具体值（`/mnt/user-data/workspace/.venv`）
   - 注：f-string 在函数体里**不识别为 docstring**（Python 3.12 语言限制），所以用 `__doc__` 后置赋值 + `@tool(parse_docstring=True)` 装饰

### 影响

- 阶段 4 DeerFlow preset 需提供：
  - `python_venv_hint: str = "/mnt/user-data/workspace/.venv"`
  - 自定义 `HostBashPolicy.disabled_message`（提及 DeerFlow 私有沙箱名 + config key）
- 工具 description 在 LLM 视角下变得"neutral"（不依赖 DeerFlow 约定），可移植到其他产品
- backend tools.py 的 verbatim 字节级等价目标**局部放弃**（错误消息 + 工具 description 改用 brand-neutral 变体）
- `LOCAL_HOST_BASH_DISABLED_MESSAGE` 等常量保留为 alias，避免破坏已有 import
- 工具 description 的稳定性：开头短语"Host bash execution is disabled" 保持稳定（LLM 可能 key off ），具体 product 名 / config key 抽到 preset 层

### 验证

- `tests/sandbox/test_security.py` 6 个新/修改用例覆盖：
  - 默认 deny message 是 brand-neutral（不含 `AioSandboxProvider` / `allow_host_bash`）
  - `ConfigurableHostBashPolicy(disabled_message=...)` 接受 override
  - backward-compat alias 与 fallback 字符串相等
  - Protocol runtime checkable 仍能识别含 `disabled_message` property 的 stub
- `tests/sandbox/test_tools.py` 1 个新用例：
  - `python_venv_hint` 默认值是 brand-neutral placeholder
  - `make_sandbox_tools` 构造时把 hint 嵌入 bash 工具的 `description` 属性

### 与 ADR-001 / ADR-010 的关系

- ADR-001: SDK 定位 brand-neutral → ADR-011 是这条原则在用户可见文案层的落地
- ADR-010: 不复制粘贴 backend 文件 → ADR-011 是"verbatim 复制" 策略的局部修正（错误消息 + 工具 description 这两类用户可见文案要 brand-neutral 化，其余代码可继续 verbatim）
