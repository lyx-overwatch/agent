# 详细规格（Specs）

> 本目录包含每个 Protocol、每个阶段的**详细技术规格**。
> 与 `01-design/` 的设计文档不同，这里是更具体的实现规格。

## 状态

本目录目前只有占位 README，具体规格在对应阶段创建：

| 规格 | 状态 | 创建于 | 文件 |
|------|------|--------|------|
| PathProvider Protocol 详细规格 | ⏳ 阶段 1 | - | `path-provider.md` |
| MemorySchema Protocol 详细规格 | ⏳ 阶段 2 | - | `memory-schema.md` |
| SubagentRegistry Protocol 详细规格 | ⏳ 阶段 2 | - | `subagent-registry.md` |
| AuditRules Protocol 详细规格 | ⏳ 阶段 3 | - | `audit-rules.md` |
| SDK 公开 API 规格 | ⏳ 阶段 5 | - | `public-api.md` |
| **SDK 模块手册**（每个文件夹作用 + 怎么测） | ✅ 已完成 | 2026-07-06 | `module-tour.md` |

## 规格文档模板

每个规格文档应包含：

1. **背景**：为什么需要这个规格
2. **接口定义**：完整的 Protocol/类代码
3. **默认实现**：SDK 内置的"无业务"实现
4. **Preset 实现**：DeerFlow 风格的实现
5. **使用示例**：用户如何注入
6. **边界情况**：测试覆盖的边界
7. **迁移路径**：如何从现有硬编码迁移
8. **测试用例**：单元测试列表

## 创建时机

规格文档在对应**阶段开始时**创建：
- 阶段 1 开始 → 创建 `path-provider.md`
- 阶段 2 开始 → 创建 `memory-schema.md` 和 `subagent-registry.md`
- 阶段 3 开始 → 创建 `audit-rules.md`
- 阶段 5 开始 → 创建 `public-api.md`

## 区别于设计文档

| 类型 | 内容 | 何时更新 |
|------|------|----------|
| `01-design/` 设计文档 | 高层架构、边界定义、特性清单 | 阶段开始前 |
| `04-specs/` 详细规格 | 具体 Protocol 接口、默认实现、测试用例 | 阶段实现时 |
