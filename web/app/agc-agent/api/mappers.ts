// API(snake_case) → 领域类型(camelCase) + SSE wire(OpenAI-compatible) → StreamEvent。
// 后端 SSE 格式：type 顶层 + 负载在 choices[0].delta + finish_reason 在 choices[0].finish_reason。

import { fmtElapsed } from '../lib/chatReducer';
import type {
  Attachment,
  Conversation,
  ConversationStatus,
  FileNode,
  FileTypeKey,
  Message,
  MessageSegment,
  Model,
  StreamEvent,
  ToolCall,
} from '../types';
import type {
  ApiConversation,
  ApiFileTreeNode,
  ApiMessage,
  ApiModel,
} from './skillhub';

// ── 工具名 → 展示名 + 图标键 ──────────────────────────────────────────────
interface ToolMeta {
  name: string;
  icon: string;
}

const TOOL_META: Record<string, ToolMeta> = {
  read_file: { name: '读取文件', icon: 'file-text' },
  bash: { name: '执行 Bash', icon: 'terminal' },
  ls: { name: '列出目录', icon: 'folder' },
  glob: { name: '匹配文件', icon: 'filter' },
  grep: { name: '搜索文本', icon: 'search' },
  write_file: { name: '写文件', icon: 'file-plus' },
  str_replace: { name: '替换文本', icon: 'replace' },
  read_skill: { name: '读取技能', icon: 'book-open' },
  web_search: { name: '网页搜索', icon: 'globe' },
  zhipu_web_search: { name: '网页搜索', icon: 'globe' },
  web_fetch: { name: '网页抓取', icon: 'link' },
  view_image: { name: '图像理解', icon: 'image' },
  task: { name: '委派子代理', icon: 'bot' },
};

function toolMeta(toolName: string): ToolMeta {
  return TOOL_META[toolName] ?? { name: toolName, icon: 'file-text' };
}

// ── 数值格式化 ───────────────────────────────────────────────────────────
function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return `${n}`;
}

// ── 状态归一化 ───────────────────────────────────────────────────────────
const STATUS_MAP: Record<string, ConversationStatus> = {
  pending: 'pending',
  active: 'active',
  running: 'running',
  completed: 'completed',
  cancelled: 'cancelled',
  error: 'error',
  step_limit: 'step_limit',
};

function normalizeStatus(status: string): ConversationStatus {
  return STATUS_MAP[status] ?? 'completed';
}

// ── API → 领域 ───────────────────────────────────────────────────────────
export function mapModel(api: ApiModel): Model {
  return {
    name: api.name,
    displayName: api.display_name,
    locked: api.thinking_locked,
    supportsThinking: api.supports_thinking,
  };
}

export function mapConversation(api: ApiConversation): Conversation {
  const cacheRate =
    api.total_tokens > 0
      ? `${Math.round((api.cache_read / api.total_tokens) * 100)}%`
      : undefined;
  return {
    id: api.conversation_id,
    title: api.title ?? '未命名会话',
    status: normalizeStatus(api.status),
    tokens: api.total_tokens ? fmtTokens(api.total_tokens) : undefined,
    cacheRate,
    hasFiles: true,
    titlePending: api.title_pending,
  };
}

export function extToFileType(ext: string): FileTypeKey {
  const e = ext.replace('.', '').toLowerCase();
  switch (e) {
    case 'ppt':
    case 'pptx':
      return 'pptx';
    case 'pdf':
      return 'pdf';
    case 'doc':
    case 'docx':
      return 'docx';
    case 'xls':
    case 'xlsx':
      return 'xlsx';
    case 'csv':
      return 'csv';
    case 'png':
    case 'jpg':
    case 'jpeg':
    case 'gif':
    case 'webp':
      return 'img';
    case 'md':
      return 'md';
    case 'py':
    case 'js':
    case 'ts':
    case 'tsx':
    case 'jsx':
    case 'json':
      return 'code';
    case 'zip':
    case 'gz':
    case 'tar':
      return 'zip';
    default:
      return 'other';
  }
}

function parseAttachments(fileMetadata: string | null): Attachment[] {
  if (!fileMetadata) return [];
  try {
    const arr = JSON.parse(fileMetadata);
    if (!Array.isArray(arr)) return [];
    return arr.map((f: { filename?: string; extension?: string }, i: number) => ({
      id: `att-${i}-${f.filename ?? ''}`,
      name: f.filename ?? '文件',
      fileType: extToFileType(f.extension ?? ''),
    }));
  } catch {
    return [];
  }
}

function assistantSegment(m: ApiMessage): MessageSegment | null {
  switch (m.event_type) {
    case 'reasoning':
      return { type: 'thinking', content: m.content, open: true };
    case 'message':
      return { type: 'text', content: m.content };
    case 'error':
    case 'step_limit':
      return { type: 'error', message: m.content };
    default:
      return null;
  }
}

function toolSegment(m: ApiMessage): MessageSegment {
  const meta = toolMeta(m.tool_name ?? '');
  const isSubagent = m.is_subagent === true || m.tool_name === 'task';
  const tool: ToolCall = {
    id: m.id,
    name: isSubagent ? `委派子代理：${m.description || '任务'}` : meta.name,
    tool: m.tool_name ?? 'unknown',
    icon: meta.icon,
    input: m.tool_input ?? '',
    output: m.tool_output ?? '',
    isSubagent,
    status: 'done',
  };
  if (m.duration_ms) {
    tool.elapsed = `耗时 ${fmtElapsed(m.duration_ms / 1000)}`;
  }
  return { type: 'tool', tool };
}

/** 把扁平的 messages 表重建为交错 Message 列表（每个 user 行开启一个新回合） */
export function mapMessages(api: ApiMessage[]): Message[] {
  const messages: Message[] = [];
  let current: Message | null = null;

  for (const m of api) {
    if (m.role === 'user') {
      current = null;
      messages.push({
        id: m.id,
        role: 'user',
        content: m.content,
        attachments: parseAttachments(m.file_metadata),
      });
      continue;
    }

    if (!current) {
      current = { id: m.id, role: 'assistant', segments: [] };
      messages.push(current);
    }

    const segment =
      m.role === 'tool' ? toolSegment(m) : assistantSegment(m);
    if (segment) current.segments!.push(segment);
  }

  return messages;
}

// ── 文件树 ───────────────────────────────────────────────────────────────
export function fmtBytes(bytes: number | null | undefined): string {
  if (bytes == null) return '—';
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

function mapFileNode(node: ApiFileTreeNode): FileNode {
  const isDir = node.type === 'directory';
  return {
    name: node.label ?? node.name,
    type: isDir ? 'dir' : 'file',
    fileType: isDir ? undefined : extToFileType(node.extension ?? ''),
    children: node.children ? node.children.map(mapFileNode) : undefined,
    virtualPath: node.virtual_path,
    previewable: node.previewable,
    size: node.size ?? undefined,
  };
}

export function mapFileTree(roots: ApiFileTreeNode[]): FileNode[] {
  return roots.map(mapFileNode);
}

// ── SSE wire → StreamEvent ───────────────────────────────────────────────
export function mapWireEvent(data: unknown): StreamEvent | null {
  if (!data || typeof data !== 'object') return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const d = data as any;
  const type = d.type;
  if (typeof type !== 'string') return null;
  const delta = d.choices?.[0]?.delta ?? {};
  const finishReason = d.choices?.[0]?.finish_reason;

  switch (type) {
    case 'run_start':
      return {
        type: 'run_start',
        conversation_id: delta.conversation_id,
        thread_id: delta.thread_id,
      };
    case 'thinking_start':
      return { type: 'thinking_start' };
    case 'thinking_end':
      return { type: 'thinking_end' };
    case 'token':
      return { type: 'token', content: delta.content ?? '' };
    case 'reasoning':
      return { type: 'reasoning', content: delta.content ?? '' };
    case 'tool_start': {
      const tool = delta.tool ?? 'unknown';
      const meta = toolMeta(tool);
      const isSubagent = delta.is_subagent === true;
      return {
        type: 'tool_start',
        tool,
        name: isSubagent
          ? `委派子代理：${delta.description || '任务'}`
          : meta.name,
        icon: meta.icon,
        input: delta.input ?? '',
        run_id: delta.run_id,
        is_subagent: isSubagent,
        description: delta.description,
      };
    }
    case 'tool_end':
      return {
        type: 'tool_end',
        tool: delta.tool ?? 'unknown',
        output: delta.output ?? '',
        run_id: delta.run_id,
        is_subagent: delta.is_subagent,
        error: delta.error,
      };
    case 'subagent_progress':
      return {
        type: 'subagent_progress',
        run_id: delta.run_id,
        elapsed_seconds: delta.elapsed_seconds,
      };
    case 'llm_retry':
      return {
        type: 'llm_retry',
        attempt: delta.attempt,
        max_attempts: delta.max_attempts,
        wait_ms: delta.wait_ms,
        reason: delta.reason,
        message: delta.message,
      };
    case 'progress':
      return {
        type: 'progress',
        phase: delta.phase ?? 'thinking',
        run_id: delta.run_id,
      };
    case 'error':
      return {
        type: 'error',
        message: delta.message ?? '未知错误',
        recoverable: delta.recoverable,
      };
    case 'title_update':
      return { type: 'title_update', title: delta.title ?? '' };
    case 'run_end':
      return { type: 'run_end', finish_reason: finishReason ?? 'stop' };
    default:
      return null;
  }
}
