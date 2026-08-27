// SkillHub 领域类型定义（U1 阶段：纯 UI，数据来自 mock.ts）

/** 会话状态：与后端 runs.status 对齐（含 active / step_limit） */
export type ConversationStatus =
  | 'pending'
  | 'active'
  | 'running'
  | 'completed'
  | 'cancelled'
  | 'error'
  | 'step_limit';

/** 会话（侧栏列表项） */
export interface Conversation {
  id: string;
  title: string;
  status: ConversationStatus;
  /** token 用量（展示用字符串，如 "12.4K"） */
  tokens?: string;
  /** 缓存命中率（如 "45%"） */
  cacheRate?: string;
  /** 是否已生成文件（决定文件树是否展示空态） */
  hasFiles?: boolean;
  /** AI 标题是否仍在后台异步生成中（后端 title_pending） */
  titlePending?: boolean;
}

/** 附件 chip */
export interface Attachment {
  id: string;
  name: string;
  /** 文件类型键，用于图标着色 */
  fileType: FileTypeKey;
  /** 待上传的原始文件对象（本地选择后） */
  file?: File;
}

/** 文件类型键（与设计稿 file-type-* 对应） */
export type FileTypeKey =
  | 'pptx'
  | 'pdf'
  | 'docx'
  | 'xlsx'
  | 'csv'
  | 'img'
  | 'code'
  | 'md'
  | 'zip'
  | 'other';

/** 模型 */
export interface Model {
  /** 模型键（config.yaml 的 name，作为 chat/stream 的 model_name） */
  name: string;
  /** 展示名（/models 的 display_name） */
  displayName?: string;
  /** 是否强制开启深度思考（锁定不可关，= thinking_locked） */
  locked?: boolean;
  /** 是否支持深度思考 */
  supportsThinking?: boolean;
}

/** 工具调用卡 */
export interface ToolCall {
  /** run_id，用于流式匹配（U1 仅作 key） */
  id: string;
  /** 展示名，如「读取文件」 */
  name: string;
  /** 工具名，如 read_file */
  tool: string;
  /** 图标键 */
  icon: string;
  /** 输入（JSON/文本） */
  input: string;
  /** 输出 */
  output?: string;
  /** 耗时文案，如「耗时 2分10秒」（子代理卡片） */
  elapsed?: string;
  /** 是否为子代理变体（task） */
  isSubagent?: boolean;
  /** 运行态（pending） */
  status?: 'running' | 'done';
  /** 工具执行错误（tool_end.error） */
  error?: string;
}

/** 消息段：助手消息内部为交错结构（思考 / 文本 / 工具 / 错误 / 取消） */
export type MessageSegment =
  | { type: 'thinking'; content: string; open?: boolean }
  | { type: 'text'; content: string }
  | { type: 'tool'; tool: ToolCall }
  | { type: 'error'; message: string }
  | { type: 'cancelled' };

/** 消息 */
export interface Message {
  id: string;
  role: 'user' | 'assistant';
  /** 用户消息的纯文本 */
  content?: string;
  /** 用户消息的附件 */
  attachments?: Attachment[];
  /** 助手消息的交错段 */
  segments?: MessageSegment[];
}

/** 文件树节点 */
export interface FileNode {
  name: string;
  type: 'dir' | 'file';
  fileType?: FileTypeKey;
  children?: FileNode[];
  /** 虚拟路径（/mnt/user-data/outputs/...），预览/下载用 */
  virtualPath?: string;
  /** 是否可预览（后端 /files/tree 的 previewable） */
  previewable?: boolean;
  /** 文件大小（字节） */
  size?: number;
}

/** 技能审核状态（自定义技能） */
export type SkillReviewStatus = 'draft' | 'pending' | 'approved' | 'rejected';

/** 技能来源（/skills/available 的 origin） */
export type SkillOrigin = 'builtin' | 'mine' | 'added';

/** 技能（技能广场 / 我的技能 / 官方内置 / 审核） */
export interface Skill {
  /** 技能名（全局唯一，= 接口 name） */
  id: string;
  name: string;
  /** 展示名（缺省回退 name） */
  displayName: string;
  description: string;
  /** 作者显示名（内置技能为「内置」） */
  author: string;
  /** 头像底色（tailwind 语义名，如 blue/pink/green/orange/purple/teal/indigo） */
  color: string;
  /** 头像缩写 */
  initial: string;
  /** 审核状态（自定义技能才有；内置为 null） */
  reviewStatus: SkillReviewStatus | null;
  /** 驳回原因（rejected 时非空） */
  reviewNote?: string | null;
  /** 版本（自定义技能） */
  version?: string | null;
  /** 是否已添加（广场卡片） */
  added?: boolean;
  /** 来源（/available 用） */
  origin?: SkillOrigin;
}

/** SSE 流式事件（对齐 docs/api/index.md 事件枚举 + 后端新增 title_update） */
export type StreamEvent =
  | { type: 'run_start'; conversation_id?: string; thread_id?: string }
  | { type: 'thinking_start' }
  | { type: 'thinking_end' }
  | { type: 'token'; content: string }
  | { type: 'reasoning'; content: string }
  | {
      type: 'tool_start';
      tool: string;
      name?: string;
      icon?: string;
      input?: string;
      run_id?: string;
      is_subagent?: boolean;
      description?: string;
    }
  | {
      type: 'tool_end';
      tool?: string;
      output?: string;
      run_id?: string;
      is_subagent?: boolean;
      elapsed_seconds?: number;
      error?: string;
    }
  | { type: 'sandbox_provisioning'; tool?: string; run_id?: string }
  | {
      type: 'progress';
      phase: 'thinking' | 'tool' | 'provisioning';
      elapsed_seconds?: number;
      run_id?: string;
    }
  | { type: 'subagent_progress'; run_id?: string; elapsed_seconds?: number }
  | { type: 'error'; message: string; recoverable?: boolean }
  | { type: 'run_end'; finish_reason: 'stop' | 'cancelled' | 'error' }
  | { type: 'title_update'; title: string }
  | { type: '[DONE]' };
