# 阶段 6：测试 + 发布（1-2 周）

> 补齐已知缺口、SDK 独立发布验证、CHANGELOG、发布脚本。
>
> **注意**：原阶段 6（端到端集成）已被阶段 4+5 吸收，原阶段 7 重编号为阶段 6。

## 目标

- SDK 单元测试 100% 通过
- DeerFlow 应用通过 preset 回归测试 100% 通过
- 干净环境 `pip install` 成功
- 文档完整

## 任务清单

### 6.1 写 SDK 单元测试（2 天）

**测试结构**：`sdk-extraction/harness/tests/`

```
tests/
├── runtime/
│   ├── test_create_agent.py        # create_agent 入口测试
│   ├── test_features.py            # RuntimeFeatures 测试
│   └── test_middlewares.py         # 5 个通用 middleware 测试
├── paths/
│   ├── test_provider.py
│   ├── test_resolver.py
│   ├── test_default.py
│   └── test_deerflow.py
├── memory/
│   ├── test_schema.py
│   ├── test_updater.py
│   └── test_storage.py
├── subagents/
│   ├── test_registry.py
│   ├── test_definition.py
│   └── test_executor.py
├── tools/
│   ├── test_factory.py
│   ├── test_naming.py
│   └── test_search.py
├── sandbox/
│   ├── test_base.py
│   ├── test_provider.py
│   └── test_search.py
├── skills/
│   ├── test_parser.py
│   ├── test_loader.py
│   └── test_installer.py
├── mcp/
│   ├── test_client.py
│   └── test_oauth.py
├── guardrails/
│   └── test_provider.py
├── reflection/
│   └── test_resolvers.py
├── tracing/
│   └── test_factory.py
└── utils/
    ├── test_file_conversion.py
    ├── test_network.py
    └── test_readability.py
```

**覆盖率目标**：核心模块 > 80%

### 6.2 写集成测试（1 天）

**测试位置**：`sdk-extraction/harness/tests/integration/`

**测试用例**：

1. **最小 SDK 用法**
   ```python
   def test_minimal_agent():
       from agent_sdk import create_agent
       from langchain_openai import ChatOpenAI
       agent = create_agent(
           model=ChatOpenAI(model="gpt-4o"),
           system_prompt="You are helpful.",
       )
       result = agent.invoke({"messages": [("user", "Hello")]})
       assert "messages" in result
   ```

2. **特性启用**
   ```python
   def test_features_toggle():
       agent = create_agent(
           model=...,
           features=RuntimeFeatures(memory=True, todo=True, subagent=True),
       )
       # 验证 middleware 正确装配
   ```

3. **自定义协议**
   ```python
   def test_custom_path_provider():
       class MyPathProvider:
           def get_workspace_dir(self, thread_id): ...
       agent = create_agent(
           model=...,
           path_provider=MyPathProvider(),
       )
   ```

4. **DeerFlow preset 行为一致**
   ```python
   def test_deerflow_preset_compatibility():
       from agent_sdk.presets.deerflow import DeerFlowAgent
       client = DeerFlowAgent()
       result = client.chat("Hello", thread_id="t1")
       # 验证与 backend/client.py 原版行为一致（golden fixture 对比）
   ```

   **绝对禁止**：
   - ❌ 测试代码 `from backend.* import ...` 或 `from deerflow.* import ...`
   - ❌ 测试代码引用 `backend.client.DeerFlowClient` 进行运行时对比
   - ❌ 测试代码引用 `backend.tests.*` 的 fixture

   **对比方法**：与 SDK 内部的 golden fixture（`sdk-extraction/harness/tests/fixtures/presets/deerflow/`，离线录制自 `backend/client.py` 真实输出）字节级对比。

### 6.3 写 SDK 完整 README（半天）

**文件**：`sdk-extraction/harness/README.md`

**内容**：
- SDK 简介
- 核心特性
- 安装方式
- 快速开始（最小用法）
- 进阶用法（特性启用、自定义协议）
- DeerFlow preset 用法
- API 文档（自动生成）
- 贡献指南

### 6.4 写 API 文档（1 天）

**工具**：使用 `sphinx` 或 `mkdocs` 自动生成

**内容**：
- 公开 API（`create_agent` / `RuntimeFeatures` / 各 Protocol）
- 私有 API（标记 `@internal`）
- 类型注解文档
- 使用示例

**输出**：`sdk-extraction/harness/docs/api/`

### 6.5 干净环境测试（半天）

**任务**：
1. 创建新 Python 虚拟环境
2. `pip install -e sdk-extraction/harness/`
3. 运行所有单元测试
4. 运行最小用法测试
5. 验证成功

### 6.6 DeerFlow 回归测试（半天）

**任务**：
1. 仅**运行** `backend/tests/` 全部测试
2. 验证 100% 通过
3. 记录任何 behavior change 到 `CHANGELOG.md`

**绝对禁止**：
- ❌ **修改** `backend/tests/` 中任何测试代码、fixture 或 `conftest.py`
- ❌ 修改 `backend/` 任何源代码以让测试通过
- ❌ 如果测试失败，**修复** `backend/tests/`

**处理流程**：
1. 如发现 `backend/tests/` 失败：先确认 `backend/` 是否被改过（理论上不应被改，因为抽离 PR 不动 `backend/`）
2. 如确认 `backend/` 未被改，则 SDK 行为可能与 `backend/` 存在差异
3. 把差异记录到 `sdk-extraction/docs/03-status/blockers.md`
4. **不修复** `backend/tests/`，**不修改** `backend/`

### 6.7 写 CHANGELOG（半天）

**文件**：`sdk-extraction/harness/CHANGELOG.md`

**内容**：
- 0.1.0 版本说明
- 抽离的模块列表
- 公开 API
- 已知限制
- 升级指南（从 DeerFlow 直接使用到 SDK + preset）

### 6.8 发布脚本（半天）

**任务**：
- `pyproject.toml` 完善（依赖、extras、classifiers）
- `MANIFEST.in`（包含必要文件）
- CI/CD 配置（可选）

### 6.9 最终评审（半天）

**评审清单**：
- [ ] 所有 ADR 已记录
- [ ] 所有阶段完成标准已满足
- [ ] 文档完整
- [ ] 测试覆盖率达标
- [ ] DeerFlow 行为完全一致
- [ ] SDK 可独立发布

## 风险

| 风险 | 等级 | 应对 |
|------|------|------|
| 测试覆盖率不达标 | 中 | 优先核心模块；接受 80% 阈值 |
| DeerFlow 行为有微小差异 | 中 | 记录所有差异；评估是否可接受 |
| 干净环境测试失败（依赖问题） | 低 | 提前测试；锁定依赖版本 |
| 文档不完整 | 低 | 提前规划；分批完成 |

## 依赖

- 阶段 1-4 全部完成

## 产出

- `sdk-extraction/harness/tests/` 完整测试套件
- `sdk-extraction/harness/README.md` 完整
- `sdk-extraction/harness/CHANGELOG.md` 0.1.0
- `sdk-extraction/harness/docs/api/` API 文档
- `sdk-extraction/harness/MANIFEST.in`
- 干净环境测试通过

## 完成标准

- [ ] 6.1-6.9 全部完成
- [ ] SDK 单元测试 100% 通过
- [ ] 集成测试 100% 通过
- [ ] DeerFlow 回归测试 100% 通过
- [ ] 干净环境 `pip install` 成功
- [ ] 文档完整
- [ ] 可发布状态
