# Skill Hub 平台实现方案

基于 DeerFlow 构建企业级 Skill Hub 平台的完整技术方案。

---

## 1. 方案概述

### 1.1 目标
构建一个 Skill Hub 平台，支持：
- 用户在平台内使用内置 Skill 完成写作、PPT、PDF 生成等任务
- 用户可创建、发布、分享自己的 Skill
- 完整的 Skill 市场（分类、搜索、评分、排行）
- 用户历史记录、使用统计、计费统计

### 1.2 核心决策
**使用 DeerFlow 作为 Skill Hub 的后端基础**：
- DeerFlow 已提供完整的 Agent 执行、沙箱、记忆、子代理能力
- 自带 FastAPI 网关、数据库支持（SQLite/Postgres）
- 前端为 Next.js，可复用或参考

**与主平台的集成方式**：
- DeerFlow 作为独立服务部署
- 通过 API 与主平台 Java 后端对接（用户认证、权限）
- Skill Hub 业务数据存储在 DeerFlow 数据库或主平台数据库

---

## 2. 系统架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                           用户浏览器                                  │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
              ▼                   ▼                   ▼
┌─────────────────────┐ ┌─────────────────┐ ┌─────────────────────┐
│   主平台前端         │ │  Skill Hub 前端  │ │   主平台管理后台     │
│   (原有系统)         │ │   (Next.js)     │ │   (原有系统)         │
└─────────┬───────────┘ └────────┬────────┘ └─────────┬───────────┘
          │                      │                    │
          └──────────────────────┼────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      主平台 Java 后端                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  用户认证中心  │  │  权限控制     │  │  Skill Hub 业务接口   │   │
│  │  - 登录/注册   │  │  - 角色权限   │  │  - 市场列表           │   │
│  │  - JWT 颁发   │  │  - 资源权限   │  │  - 使用记录查询       │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└───────────────────────────────────┬─────────────────────────────┘
                                    │ 内网调用
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DeerFlow (Python)                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  Gateway API │  │  LangGraph   │  │    Skill 系统         │   │
│  │  (FastAPI)   │  │   运行时      │  │  - 内置 Skill         │   │
│  │              │  │              │  │  - 自定义 Skill       │   │
│  │ /api/models  │  │  Lead Agent  │  │  - Skill 安装/管理    │   │
│  │ /api/skills  │  │  - 工具调用   │  │                      │   │
│  │ /api/threads │  │  - 子代理     │  │                      │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└───────────────────────────────────┬─────────────────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
              ▼                     ▼                     ▼
┌─────────────────────┐ ┌─────────────────┐ ┌─────────────────────┐
│   PostgreSQL        │ │   文件存储       │ │   Docker 沙箱        │
│  (DeerFlow DB)      │ │   (本地/OSS)    │ │   (代码执行)         │
│  - Runs             │ │  - 上传文件      │ │                     │
│  - Threads          │ │  - 生成工件      │ │                     │
│  - Skill 元数据      │ │  - Skill 文件    │ │                     │
└─────────────────────┘ └─────────────────┘ └─────────────────────┘
```

### 2.2 服务职责划分

| 服务 | 职责 | 技术栈 |
|------|------|--------|
| **主平台 Java 后端** | 用户认证、权限、基础用户信息 | Java + Spring Boot |
| **Skill Hub 前端** | Skill 市场界面、任务执行界面、用户中心 | Next.js + React |
| **DeerFlow** | Agent 执行、沙箱、Skill 管理、运行记录 | Python + FastAPI + LangGraph |
| **PostgreSQL** | 业务数据（可共用或独立） | PostgreSQL 14+ |

---

## 3. 数据模型设计

### 3.1 DeerFlow 原生表（复用）

DeerFlow 已提供以下表，可直接使用：

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `runs` | 运行记录 | run_id, thread_id, user_id, status, model_name, token 统计 |
| `threads_meta` | 线程元数据 | thread_id, user_id, display_name, status |
| `run_events` | 运行事件流 | 详细执行步骤，用于回放 |

**注意**：DeerFlow 的 `user_id` 是字符串，存储主平台的用户ID。

### 3.2 Skill Hub 扩展表

需要在 DeerFlow 数据库或主平台数据库新增：

#### skills（Skill 元数据表）
```sql
CREATE TABLE skills (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(128) UNIQUE NOT NULL,           -- 唯一标识（如 slide-creation）
    display_name VARCHAR(256) NOT NULL,          -- 显示名称
    description TEXT,                            -- 描述
    
    -- 分类与标签
    category_id VARCHAR(36),                     -- 外键：skill_categories
    tags JSON,                                   -- ["办公", "演示"]
    
    -- 作者信息
    author_id VARCHAR(64) NOT NULL,              -- 主平台用户ID
    author_name VARCHAR(128),                    -- 作者显示名
    
    -- 状态与权限
    is_official BOOLEAN DEFAULT FALSE,           -- 是否官方
    is_public BOOLEAN DEFAULT TRUE,              -- 是否公开
    is_enabled BOOLEAN DEFAULT TRUE,             -- 是否启用
    review_status VARCHAR(20) DEFAULT 'pending', -- pending | approved | rejected
    
    -- 存储位置
    storage_type VARCHAR(20) DEFAULT 'builtin',  -- builtin | custom | uploaded
    file_path VARCHAR(512),                      -- SKILL.md 路径
    
    -- 统计
    download_count INT DEFAULT 0,
    usage_count INT DEFAULT 0,
    rating_sum INT DEFAULT 0,                    -- 总评分
    rating_count INT DEFAULT 0,                  -- 评分人数
    
    -- 版本
    version VARCHAR(32) DEFAULT '1.0.0',
    changelog TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_category (category_id),
    INDEX idx_author (author_id),
    INDEX idx_status (review_status, is_enabled),
    INDEX idx_hot (usage_count DESC),
    FULLTEXT INDEX ft_name_desc (display_name, description)
);
```

#### skill_categories（分类表）
```sql
CREATE TABLE skill_categories (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(64) UNIQUE NOT NULL,
    icon VARCHAR(64),              -- 图标名称
    sort_order INT DEFAULT 0,
    is_enabled BOOLEAN DEFAULT TRUE
);
```

#### skill_usage_records（Skill 使用记录）
```sql
CREATE TABLE skill_usage_records (
    id VARCHAR(36) PRIMARY KEY,
    
    -- 用户与 Skill
    user_id VARCHAR(64) NOT NULL,
    skill_id VARCHAR(36) NOT NULL,
    
    -- 关联 DeerFlow 运行
    deerflow_thread_id VARCHAR(64),
    deerflow_run_id VARCHAR(64),
    
    -- 输入输出摘要
    input_summary VARCHAR(500),
    output_summary VARCHAR(500),
    output_file_urls JSON,         -- ["https://oss.com/xxx.ppt"]
    
    -- 执行状态
    status VARCHAR(20),            -- running | success | error | timeout
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    
    -- 资源消耗
    input_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    total_tokens INT DEFAULT 0,
    
    -- 错误信息
    error_message TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_user (user_id, created_at DESC),
    INDEX idx_skill (skill_id, created_at DESC),
    INDEX idx_status (status)
);
```

#### user_favorite_skills（用户收藏）
```sql
CREATE TABLE user_favorite_skills (
    user_id VARCHAR(64),
    skill_id VARCHAR(36),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, skill_id)
);
```

#### skill_ratings（评分表）
```sql
CREATE TABLE skill_ratings (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(64),
    skill_id VARCHAR(36),
    rating INT CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, skill_id)
);
```

---

## 4. API 设计

### 4.1 Skill 市场 API

```yaml
# Skill 分类与列表
GET  /api/skill-hub/categories              # 获取分类列表
GET  /api/skill-hub/skills                  # 获取 Skill 列表（支持筛选、分页、搜索）
GET  /api/skill-hub/skills/:id              # 获取 Skill 详情
GET  /api/skill-hub/skills/:id/download     # 下载 Skill 文件（.skill 格式）

# 用户交互
POST /api/skill-hub/skills/:id/favorite     # 收藏 Skill
DELETE /api/skill-hub/skills/:id/favorite   # 取消收藏
POST /api/skill-hub/skills/:id/rating       # 评分

# 用户中心
GET  /api/skill-hub/users/:userId/skills    # 获取用户创建的 Skill
GET  /api/skill-hub/users/:userId/history   # 获取用户使用记录
GET  /api/skill-hub/users/:userId/favorites # 获取用户收藏
```

**搜索参数示例**：
```
GET /api/skill-hub/skills?
    category=office&           # 分类筛选
    tag=ppt&                   # 标签筛选
    sort=hot&                  # 排序：hot | new | rating
    q=写作&                    # 关键词搜索
    page=1&limit=20            # 分页
```

### 4.2 Skill 执行 API

```yaml
# 任务执行（复用 DeerFlow API，包装一层）
POST /api/skill-hub/execute                 # 启动 Skill 执行
Request:
{
    "skillId": "slide-creation",
    "input": "帮我做一个关于AI趋势的PPT",
    "modelName": "gpt-4",                  # 可选，默认使用配置
    "files": ["uploaded-file-id"]          # 可选，上传的文件ID
}

Response:
{
    "executionId": "exec-xxx",
    "threadId": "thread-xxx",
    "runId": "run-xxx",
    "status": "running",
    "streamUrl": "/api/skill-hub/execute/exec-xxx/stream"
}

# 流式获取结果
GET /api/skill-hub/execute/:id/stream       # SSE 流式输出

# 查询执行状态
GET /api/skill-hub/execute/:id

# 取消执行
POST /api/skill-hub/execute/:id/cancel

# 获取生成的文件
GET /api/skill-hub/files/:fileId/download
```

### 4.3 Skill 管理 API（创作者）

```yaml
# Skill 创建
POST /api/skill-hub/skills
Content-Type: multipart/form-data
{
    "name": "my-skill",
    "displayName": "我的技能",
    "description": "...",
    "categoryId": "cat-xxx",
    "tags": ["标签1", "标签2"],
    "content": "# Skill 内容\n你是专业的...",  // SKILL.md 内容
    "icon": [文件],
    "examples": ["示例1", "示例2"]
}

# Skill 更新
PUT /api/skill-hub/skills/:id

# Skill 版本发布
POST /api/skill-hub/skills/:id/versions
{
    "version": "1.1.0",
    "changelog": "修复了xxx问题",
    "content": "..."
}

# 删除 Skill
DELETE /api/skill-hub/skills/:id
```

---

## 5. Skill 创建与管理流程

### 5.1 Skill 文件格式

DeerFlow 原生使用 `SKILL.md`，Skill Hub 扩展为：

```
skill-name/
├── SKILL.md              # 核心定义（DeerFlow 兼容）
├── icon.png              # 图标（可选）
├── examples/             # 示例文件（可选）
│   ├── example1.md
│   └── example2.md
└── manifest.json         # 扩展元数据（Skill Hub 特有）
```

**SKILL.md 示例**：
```markdown
---
name: slide-creation
display_name: PPT 演示文稿生成
description: 根据主题自动生成专业的 PowerPoint 演示文稿
version: 1.0.0
author:官方团队
license: MIT
allowed_tools: [read_file, write_file, bash, web_search]
category: office
tags: [ppt, 演示, 办公]
---

# PPT 演示文稿生成

你是专业的PPT制作专家。请遵循以下流程：

## 工作流程

1. **分析需求**
   - 理解用户想要的主题、页数、风格
   - 确认目标受众

2. **大纲设计**
   - 设计清晰的章节结构
   - 每页的主要内容要点

3. **内容生成**
   - 使用搜索工具收集信息（如需）
   - 撰写简洁有力的文案

4. **视觉设计**
   - 使用 python-pptx 生成 PPTX 文件
   - 保存到 /mnt/user-data/outputs/

5. **交付**
   - 向用户展示生成的文件
   - 提供下载链接

## 输出要求

- 文件格式：PPTX
- 默认页数：10-15页
- 风格：商务专业
```

**manifest.json**：
```json
{
  "id": "slide-creation",
  "categoryId": "cat-office",
  "examples": [
    {
      "title": "生成AI趋势报告PPT",
      "input": "帮我做一个关于2024年AI发展趋势的PPT，10页左右"
    }
  ],
  "recommendedModels": ["gpt-4", "claude-3-opus"],
  "estimatedTime": "2-3分钟",
  "outputTypes": ["pptx"]
}
```

### 5.2 Skill 创建流程

```
用户在前端填写表单
       │
       ▼
┌──────────────┐
│ 1. 表单校验   │
│ - 名称唯一性  │
│ - 必填字段   │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ 2. 生成文件   │
│ - SKILL.md   │
│ - manifest.json
│ - 打包为 .skill
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ 3. 存储      │
│ - 文件→存储  │
│ - 元数据→DB  │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ 4. 安装到    │
│    DeerFlow  │
│ - 调用 install API
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ 5. 审核/发布 │
│ - 官方审核（如需）
│ - 上架市场   │
└──────────────┘
```

---

## 6. 用户认证与权限

### 6.1 认证流程

```
用户登录主平台
       │
       ▼
主平台颁发 JWT
       │
       ▼
用户访问 Skill Hub
       │
       ▼
Skill Hub 前端携带 JWT
       │
       ▼
请求到达 DeerFlow
       │
       ▼
DeerFlow 转发/调用
主平台验证 JWT
       │
       ▼
验证通过，获取 userId
继续执行请求
```

### 6.2 DeerFlow 认证配置

```yaml
# config.yaml
auth:
  enabled: true
  mode: external                              # 外部认证模式
  external_auth_url: http://main-platform/api/auth/verify
  service_token: $DEERFLOW_SERVICE_TOKEN      # 服务间调用密钥
```

### 6.3 API 调用时的用户传递

**方式一：Header 传递**
```http
POST /api/langgraph/threads
X-User-Id: user-123-from-main-platform
X-Service-Token: secret-token
```

**方式二：JWT 中包含**
```http
Authorization: Bearer <JWT-from-main-platform>
# JWT payload 包含: { "sub": "user-123", "source": "main-platform" }
```

---

## 7. 部署方案

### 7.1 开发环境

```bash
# 1. 启动 DeerFlow
cd deer-flow
make setup      # 配置模型
make dev        # 启动所有服务（2026端口）

# 2. 启动 Skill Hub 前端（开发模式）
cd skill-hub-frontend
pnpm install
pnpm dev        # 3000端口
```

### 7.2 生产环境（Docker Compose）

```yaml
# docker-compose.yml
version: '3.8'

services:
  # DeerFlow 核心服务
  deerflow-gateway:
    image: deerflow/gateway:latest
    environment:
      - DATABASE_URL=postgresql://postgres:pass@db:5432/deerflow
      - AUTH_MODE=external
      - EXTERNAL_AUTH_URL=http://main-platform:8080/api/auth/verify
    ports:
      - "8001:8001"
    volumes:
      - ./skills:/app/skills
      - ./user-data:/app/.deer-flow
    networks:
      - skillhub-network

  deerflow-langgraph:
    image: deerflow/langgraph:latest
    environment:
      - DATABASE_URL=postgresql://postgres:pass@db:5432/deerflow
    ports:
      - "2024:2024"
    networks:
      - skillhub-network

  # Nginx 统一入口
  nginx:
    image: nginx:alpine
    ports:
      - "2026:2026"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - deerflow-gateway
      - deerflow-langgraph
    networks:
      - skillhub-network

  # PostgreSQL 数据库
  db:
    image: postgres:15
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=pass
      - POSTGRES_DB=deerflow
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - skillhub-network

  # Skill Hub 前端（SSG 静态部署）
  skillhub-frontend:
    image: skillhub/frontend:latest
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_BASE_URL=http://deerflow-gateway:8001
    networks:
      - skillhub-network

volumes:
  postgres-data:

networks:
  skillhub-network:
    driver: bridge
```

### 7.3 高可用部署

```
                    ┌─────────────┐
                    │   负载均衡   │
                    │  (Nginx/SLB)│
                    └──────┬──────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           ▼               ▼               ▼
    ┌────────────┐  ┌────────────┐  ┌────────────┐
    │DeerFlow 1  │  │DeerFlow 2  │  │DeerFlow 3  │
    └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
          │               │               │
          └───────────────┼───────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │    PostgreSQL 主从    │
              │    (读写分离)          │
              └───────────────────────┘
```

---

## 8. 前端架构

### 8.1 技术栈
- **框架**: Next.js 16 + React 19
- **语言**: TypeScript 5.8
- **样式**: Tailwind CSS 4
- **状态管理**: TanStack Query (React Query) + Zustand
- **UI 组件**: Radix UI + Shadcn/ui
- **包管理**: pnpm

### 8.2 核心页面

```
src/
├── app/                              # Next.js App Router
│   ├── page.tsx                      # Skill 市场首页
│   ├── skills/
│   │   ├── [id]/
│   │   │   └── page.tsx              # Skill 详情页
│   │   └── [id]/execute/
│   │       └── page.tsx              # Skill 执行页（对话界面）
│   ├── categories/
│   │   └── [id]/
│   │       └── page.tsx              # 分类列表页
│   ├── workspace/
│   │   └── page.tsx                  # 用户工作台（历史记录）
│   ├── create/
│   │   └── page.tsx                  # 创建 Skill
│   └── api/                          # API Routes（可选）
│
├── components/
│   ├── skill-market/                 # Skill 市场组件
│   │   ├── SkillCard.tsx
│   │   ├── SkillGrid.tsx
│   │   ├── CategoryFilter.tsx
│   │   └── SearchBox.tsx
│   ├── skill-execution/              # 执行界面组件
│   │   ├── ChatInterface.tsx         # 对话界面
│   │   ├── FileUploader.tsx          # 文件上传
│   │   ├── OutputViewer.tsx          # 结果展示
│   │   └── StreamingText.tsx         # 流式文本
│   ├── skill-editor/                 # Skill 编辑器
│   │   ├── SkillForm.tsx
│   │   ├── MarkdownEditor.tsx
│   │   └── IconUploader.tsx
│   └── ui/                           # 基础 UI 组件
│
├── hooks/
│   ├── useSkillExecution.ts          # Skill 执行逻辑
│   ├── useStreaming.ts               # SSE 流式处理
│   └── useAuth.ts                    # 认证相关
│
├── lib/
│   ├── api.ts                        # API 客户端
│   ├── utils.ts                      # 工具函数
│   └── constants.ts                  # 常量定义
│
└── types/
    ├── skill.ts                      # Skill 类型定义
    ├── execution.ts                  # 执行相关类型
    └── api.ts                        # API 响应类型
```

### 8.3 关键组件示例

**Skill 卡片组件**：
```tsx
// components/skill-market/SkillCard.tsx
interface SkillCardProps {
  skill: Skill;
  onExecute: (skill: Skill) => void;
  onFavorite: (skill: Skill) => void;
}

export function SkillCard({ skill, onExecute, onFavorite }: SkillCardProps) {
  return (
    <div className="rounded-lg border p-4 hover:shadow-lg transition-shadow">
      <div className="flex items-start gap-4">
        <img src={skill.iconUrl} alt={skill.displayName} className="w-12 h-12 rounded" />
        <div className="flex-1">
          <h3 className="font-semibold">{skill.displayName}</h3>
          <p className="text-sm text-gray-600 line-clamp-2">{skill.description}</p>
          <div className="flex items-center gap-4 mt-2 text-xs text-gray-500">
            <span>⭐ {skill.ratingAvg.toFixed(1)}</span>
            <span>📥 {skill.usageCount} 次使用</span>
            <span>👤 {skill.authorName}</span>
          </div>
        </div>
      </div>
      <div className="flex gap-2 mt-4">
        <Button onClick={() => onExecute(skill)}>立即使用</Button>
        <Button variant="ghost" onClick={() => onFavorite(skill)}>
          <Heart className={skill.isFavorited ? "fill-red-500" : ""} />
        </Button>
      </div>
    </div>
  );
}
```

**Skill 执行 Hook**：
```tsx
// hooks/useSkillExecution.ts
export function useSkillExecution() {
  const [isExecuting, setIsExecuting] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  
  const execute = async (skillId: string, input: string, files?: File[]) => {
    setIsExecuting(true);
    
    // 1. 上传文件（如有）
    const fileIds = files ? await uploadFiles(files) : [];
    
    // 2. 启动执行
    const { threadId, runId, streamUrl } = await api.post('/skill-hub/execute', {
      skillId,
      input,
      fileIds
    });
    
    // 3. 建立 SSE 连接
    const eventSource = new EventSource(streamUrl);
    
    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type === 'message') {
        setMessages(prev => [...prev, data.message]);
      } else if (data.type === 'artifact') {
        // 收到生成的文件
        handleNewArtifact(data.artifact);
      } else if (data.type === 'end') {
        eventSource.close();
        setIsExecuting(false);
      }
    };
    
    return { threadId, runId };
  };
  
  return { execute, isExecuting, messages };
}
```

---

## 9. 关键实现细节

### 9.1 文件处理流程

```
用户上传文件
       │
       ▼
前端上传到 DeerFlow
POST /api/threads/{id}/uploads
       │
       ▼
DeerFlow 自动转换
(PDF/PPT/Excel → Markdown)
       │
       ▼
文件存入沙箱
/mnt/user-data/uploads/
       │
       ▼
AI 处理时引用
通过虚拟路径访问
       │
       ▼
生成输出文件
/mnt/user-data/outputs/
       │
       ▼
Java 后端获取文件
GET /api/threads/{id}/artifacts
       │
       ▼
转存到 OSS
返回永久 URL 给用户
```

### 9.2 计费统计实现

```sql
-- 按用户统计 Token 消耗
SELECT 
    user_id,
    DATE(created_at) as date,
    SUM(input_tokens) as input_tokens,
    SUM(output_tokens) as output_tokens,
    SUM(total_tokens) as total_tokens,
    COUNT(*) as execution_count
FROM skill_usage_records
WHERE created_at >= '2024-01-01'
GROUP BY user_id, DATE(created_at);

-- 按 Skill 统计热度
SELECT 
    s.id,
    s.display_name,
    COUNT(r.id) as usage_count,
    AVG(r.rating) as avg_rating
FROM skills s
LEFT JOIN skill_usage_records r ON s.id = r.skill_id
WHERE r.created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
GROUP BY s.id
ORDER BY usage_count DESC;
```

### 9.3 性能优化

| 优化点 | 方案 |
|--------|------|
| Skill 列表加载 | Redis 缓存热门 Skill，分页加载 |
| 搜索 | Elasticsearch 全文检索 |
| 文件存储 | 大文件存对象存储（OSS/S3），小文件本地 |
| 沙箱执行 | 连接池复用，异步执行 |
| 流式响应 | SSE 长连接，前端虚拟列表 |

---

## 10. 实施路线图

### Phase 1: MVP（4-6 周）

**目标**：完成基础 Skill Hub，支持内置 Skill 使用

- [ ] Week 1-2: 部署 DeerFlow，配置模型
- [ ] Week 2-3: 实现 Skill 市场前端（列表、详情）
- [ ] Week 3-4: 实现 Skill 执行流程（对话界面、流式输出）
- [ ] Week 4-5: 用户认证对接（与主平台）
- [ ] Week 5-6: 使用记录存储，基础历史页面

### Phase 2: 创作者生态（4-6 周）

**目标**：支持用户创建、发布 Skill

- [ ] Skill 创建表单与编辑器
- [ ] 文件上传与 .skill 打包
- [ ] Skill 审核流程
- [ ] 用户中心（我的 Skill、使用统计）

### Phase 3: 市场运营（4 周）

**目标**：完善 Skill 市场功能

- [ ] 评分评论系统
- [ ] 收藏功能
- [ ] 分类与标签管理
- [ ] 热门排行、推荐算法

### Phase 4: 企业级（持续）

- [ ] 计费与配额系统
- [ ] 组织架构与权限
- [ ] 审计日志
- [ ] 多租户支持

---

## 11. 风险与应对

| 风险 | 影响 | 应对措施 |
|------|------|----------|
| DeerFlow 升级不兼容 | 高 | Fork 后维护，或锁定版本 |
| LLM API 不稳定 | 高 | 配置多模型 fallback |
| 沙箱安全问题 | 高 | 使用 Docker 沙箱，限制资源 |
| 大文件处理慢 | 中 | 异步处理，进度反馈 |
| Token 消耗过高 | 中 | 配额限制，使用提醒 |

---

## 12. 参考资料

- DeerFlow 官方文档：https://deerflow.tech
- DeerFlow GitHub：https://github.com/bytedance/deer-flow
- LangGraph 文档：https://langchain-ai.github.io/langgraph/
- 本地方案文档：
  - `CLAUDE.md` - 项目整体指引
  - `backend/CLAUDE.md` - 后端详细架构
  - `frontend/CLAUDE.md` - 前端详细架构

---

**文档版本**: v1.0
**最后更新**: 2026-04-29
