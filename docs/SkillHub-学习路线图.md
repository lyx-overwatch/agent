# SkillHub 学习路线图

> 基于 DeerFlow 项目，从 React 前端开发者视角，逐步掌握 Python 后端并落地 SkillHub 平台。

---

## 个人背景

- **前端**：React / Next.js / TypeScript 熟练
- **Python**：自学 2 个月，能阅读代码
- **目标**：通过 DeerFlow 项目提升后端水平，完成 SkillHub 平台

---

## 第一阶段：前端切入建立全局视角（第 1-2 天）

**先看熟悉的，建立对整体的感性认知。**

### 1.1 跑起来（半天）

```bash
make setup    # 配置向导
make dev      # 启动所有服务
# 访问 http://localhost:2026
```

### 1.2 从 Next.js 前端入手

```
frontend/src/
├── app/          # App Router 页面——你有经验，直接看
├── components/   # UI 组件——和 SkillHub 方案里的前端设计对照看
├── hooks/        # 关键是看 SSE 流式处理和 API 调用方式
└── lib/api.ts    # 前端怎么调后端 API 的
```

### 1.3 用浏览器 DevTools 追踪一个完整请求

打开浏览器 → 发一条消息 → 在 Network 面板看：

- 请求发到了哪个 API？（`/api/langgraph/threads/...`）
- 响应是什么格式？（SSE 流式）
- 直观看到前后端怎么通信的

> **关键认知**：你的 SkillHub 前端本质上就是在 DeerFlow 现有前端基础上，把"通用对话界面"改造成"Skill 市场 + Skill 执行界面"。实现方案第 8.2 节已经规划好了页面结构，你直接能上手写。

---

## 第二阶段：API 层——Python 后端第一站（第 3-5 天）

**FastAPI 路由是你 React 背景最容易理解的 Python 后端入口——它本质就是 "API Route Handler"。**

### 2.1 核心阅读顺序

| 优先级 | 文件 | 为什么重要 |
|--------|------|-----------|
| ⭐⭐⭐ | `backend/app/gateway/app.py` | FastAPI 应用入口，看路由怎么注册的 |
| ⭐⭐⭐ | `backend/app/gateway/routers/skills.py` | **Skill Hub 最直接的参考**——Skill 列表、安装、删除 API |
| ⭐⭐⭐ | `backend/app/gateway/routers/threads.py` | 对话线程 CRUD，Skill 执行流程的核心 |
| ⭐⭐ | `backend/app/gateway/routers/thread_runs.py` | 运行管理，流式响应 |
| ⭐⭐ | `backend/app/gateway/routers/uploads.py` | 文件上传——Skill 执行时需要 |
| ⭐ | `backend/app/gateway/auth_middleware.py` | 认证中间件——你的方案里有外部认证对接 |

### 2.2 前端 → 后端概念映射

```python
# 你熟悉的 Next.js API Route：
// app/api/skills/route.ts
export async function GET(request: Request) {
  const skills = await getSkills()
  return Response.json(skills)
}

# DeerFlow 的 Python 等价写法（在 routers/skills.py 里）：
@router.get("/skills")
async def list_skills(user_id: str = Depends(get_user_id)):
    skills = await skill_manager.list_all()
    return {"skills": skills}
```

**模式一样**：路由装饰器 → 依赖注入 → 业务逻辑 → 返回 JSON。

### 2.3 Hands-on 练习

在 `routers/skills.py` 里加一个新接口试试手：

```python
@router.get("/skills/market")
async def list_market_skills(
    category: str = None,
    sort: str = "hot",
    page: int = 1,
    limit: int = 20,
):
    """Skill 市场列表——你的 SkillHub 首页数据源"""
    ...
```

---

## 第三阶段：Skills 系统——SkillHub 的核心（第 6-8 天）

**这是你实现 SkillHub 最重要的模块。DeerFlow 已经有一套完整的 Skill 系统，你的工作是扩展它。**

### 3.1 阅读顺序

```
backend/packages/harness/deerflow/skills/
├── types.py          # ① 先看：Skill 的数据结构定义
├── parser.py         # ② SKILL.md 怎么解析成 Skill 对象
├── loader.py         # ③ Skill 怎么从磁盘加载到内存
├── manager.py        # ④ Skill 的增删改查管理
├── installer.py      # ⑤ .skill 文件怎么安装
├── validation.py     # ⑥ Skill 内容的安全校验
└── security_scanner.py # ⑦ 安全检查（可以后看）
```

### 3.2 对照实现方案的扩展点

| 方案中的概念 | DeerFlow 现有代码 | 需要做的工作 |
|-------------|-----------------|-------------|
| Skill 元数据（display_name, description, tags） | `types.py` 里只有基础字段 | **扩展 `Skill` 类型，加上分类、标签、评分** |
| SKILL.md 解析 | `parser.py` 已实现 | **扩展 frontmatter 支持新字段** |
| Skill 市场列表 | `routers/skills.py` 只有基础 CRUD | **加上分页、搜索、排序、筛选** |
| Skill 安装 | `installer.py` 已有 | **对接创建/发布流程** |
| 评分/收藏 | 不存在 | **新建数据表 + API** |
| 使用记录 | 不存在 | **新建数据表 + API** |

---

## 第四阶段：Agent 运行时——理解 Skill 怎么被执行（第 9-11 天）

**这部分是 Python 后端能力的核心提升。理解 Agent 怎么跑起来的。**

### 4.1 核心阅读顺序

```
# ① 先看这个：理解整体流程
backend/packages/harness/deerflow/runtime/runs/manager.py
  → RunManager 怎么创建运行、管理生命周期

# ② Agent 怎么构建的
backend/packages/harness/deerflow/agents/lead_agent/agent.py
  → make_lead_agent() 函数

# ③ 中间件链——Agent 的"洋葱模型"
backend/packages/harness/deerflow/agents/middlewares/
  → 18 个中间件，先看懂前 5 个：
     thread_data_middleware.py    # 线程隔离
     sandbox_audit_middleware.py  # 沙箱审计
     memory_middleware.py         # 记忆注入
     subagent_limit_middleware.py # 子代理限制
     loop_detection_middleware.py # 循环检测

# ④ 技能工具——Skill 怎么被 Agent 调用
backend/packages/harness/deerflow/tools/skill_manage_tool.py
  → Skill 作为工具被 Agent 调用的桥梁
```

### 4.2 前端概念 → Agent 概念

| 你熟悉的前端概念 | Python/Agent 对应 |
|----------------|------------------|
| Next.js Middleware（middleware.ts） | LangGraph AgentMiddleware |
| Redux / Zustand state | ThreadState（线程状态） |
| API Route Handler | FastAPI Router |
| EventSource / SSE | StreamBridge（流式桥接） |
| React Context | RunnableConfig / context |
| 组件嵌套（Composition） | 中间件链（Middleware Chain） |

---

## 第五阶段：动手实现 SkillHub MVP（第 12-20 天）

**开始写代码。按这个顺序，从最擅长的前端开始。**

### Sprint 1: 前端 Skill 市场（3 天）

参考实现方案 `8.2 核心页面` + `8.3 关键组件示例`：

- `SkillCard` / `SkillGrid` / `SearchBox` / `CategoryFilter`
- 可以直接复用 DeerFlow 现有的前端组件风格

### Sprint 2: Skill 执行界面（3 天）

改造 DeerFlow 的对话界面为 Skill 专用执行界面：

- `ChatInterface` + `StreamingText` + `OutputViewer`
- 关键是 SSE 流式处理 hook（方案 8.3 已有代码骨架）

### Sprint 3: 后端 API 扩展（3 天）

在 `routers/skills.py` 基础上加：

- 市场列表（分页 + 搜索 + 排序）
- Skill 创建 / 发布
- 执行记录查询

### Sprint 4: 数据库（1 天）

方案第 3.2 节已经设计好了表结构：

```sql
-- 核心表
skills              # Skill 元数据（分类、标签、评分、状态）
skill_categories    # 分类
skill_usage_records # 使用记录
user_favorite_skills # 用户收藏
skill_ratings       # 评分
```

直接执行建表即可。

---

## 学习策略

### Python 后端重点关注的三个特性

DeerFlow 大量使用，而且和你熟悉的 TypeScript 很像：

1. **类型注解**：`def foo(x: str) -> int:` —— 和 TypeScript 的类型标注几乎一样
2. **async/await**：Python 的异步，和 JS 的 Promise 用法几乎一样
3. **Pydantic 模型**：`class Skill(BaseModel)` —— 等价于 TypeScript 的 `interface` + Zod 校验

### 高效的代码阅读方法

- **不要从头啃 Python 教程**——在代码里学，遇到不懂的语法查
- **跟着调用链读**：从 FastAPI router → service → manager → 底层实现，一条线追下去
- **不要试图看完所有代码再动手**——看完 API 层（第二阶段）就开始写，边写边深入

---

## 时间总览

```
Week 1  ████████ 前端切入 → 跑起来 → 追踪请求 → 理解整体
Week 2  ████████ FastAPI 路由 → Skills Router → 手写一个 API
Week 3  ████████ Skills 系统源码 → 对照方案 → 设计扩展点
Week 4  ████████ Agent 运行时 → 中间件链 → 理解执行流程
Week 5-6 ████████ 动手实现 MVP → 前端市场+执行 → 后端 API 扩展
```

---

## 关键文件速查

| 类别 | 文件路径 |
|------|---------|
| 项目入口 | `CLAUDE.md` |
| 后端架构 | `backend/CLAUDE.md` |
| FastAPI 应用 | `backend/app/gateway/app.py` |
| Skills 路由 | `backend/app/gateway/routers/skills.py` |
| Threads 路由 | `backend/app/gateway/routers/threads.py` |
| Skill 类型定义 | `backend/packages/harness/deerflow/skills/types.py` |
| Skill 解析器 | `backend/packages/harness/deerflow/skills/parser.py` |
| Skill 管理器 | `backend/packages/harness/deerflow/skills/manager.py` |
| Lead Agent | `backend/packages/harness/deerflow/agents/lead_agent/agent.py` |
| RunManager | `backend/packages/harness/deerflow/runtime/runs/manager.py` |
| 中间件目录 | `backend/packages/harness/deerflow/agents/middlewares/` |
| SkillHub 方案 | `SkillHub-实现方案.md` |
| 项目介绍 | `项目介绍.md` |