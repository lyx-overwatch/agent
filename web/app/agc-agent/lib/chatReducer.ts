// SkillHub 流式状态机（debug-agent.html sendStream 的 React 翻译）。
// 纯 reducer：把 SSE StreamEvent 序列转换成会话/消息/状态条状态。
// - 交错渲染：text / reasoning / tool 段按到达顺序追加到在途助手消息
// - pendingCards：tool_start 建 pending 卡、tool_end 按 run_id 匹配替换
// - detached 守卫：只有「当前流式会话」的事件才驱动状态条/清流，后台流只写自己的消息
import type {
  Attachment,
  Conversation,
  ConversationStatus,
  Message,
  MessageSegment,
  StreamEvent,
} from '../types';

export interface StreamingState {
  conversationId: string;
  label: string;
  thinkingEnabled: boolean;
}

export interface ChatState {
  conversations: Conversation[];
  messages: Record<string, Message[]>;
  streaming: StreamingState | null;
}

export type ChatAction =
  | {
      type: 'SEND';
      conversationId: string;
      title: string;
      userMessage: Message;
      assistantMessage: Message;
      thinkingEnabled: boolean;
    }
  | { type: 'STREAM_EVENT'; conversationId: string; event: StreamEvent }
  | { type: 'DELETE_CONVERSATION'; conversationId: string }
  | { type: 'CONVERSATIONS_LOADED'; conversations: Conversation[] }
  | { type: 'MESSAGES_LOADED'; conversationId: string; messages: Message[] };

/** 会话占位标题：截断用户首条消息 */
export function truncateTitle(t: string): string {
  const s = t.trim();
  return s.length > 20 ? `${s.slice(0, 20)}…` : s;
}

/** 秒 → 「X分Y秒」/「Y秒」 */
export function fmtElapsed(secs: number): string {
  const s = Math.floor(secs || 0);
  const mins = Math.floor(s / 60);
  const sec = s % 60;
  return mins > 0 ? `${mins}分${sec}秒` : `${sec}秒`;
}

const EMPTY_SEGMENTS: MessageSegment[] = [];

function replaceLastMessage(list: Message[], message: Message): Message[] {
  if (list.length === 0) return [message];
  const next = list.slice();
  next[next.length - 1] = message;
  return next;
}

/** 把一个 SSE 事件施加到在途助手消息上，返回新消息（不改状态条/会话状态） */
function applyEventToMessage(message: Message, event: StreamEvent): Message {
  const segs = message.segments ?? EMPTY_SEGMENTS;

  switch (event.type) {
    case 'token': {
      const last = segs[segs.length - 1];
      if (last && last.type === 'text') {
        const next = segs.slice();
        next[next.length - 1] = { ...last, content: last.content + event.content };
        return { ...message, segments: next };
      }
      return { ...message, segments: [...segs, { type: 'text', content: event.content }] };
    }

    case 'reasoning': {
      const last = segs[segs.length - 1];
      if (last && last.type === 'thinking') {
        // 兼容 delta 与全量两种模式：新内容以前缀开始 → 全量替换，否则累加
        const content = event.content.startsWith(last.content)
          ? event.content
          : last.content + event.content;
        const next = segs.slice();
        next[next.length - 1] = { ...last, content };
        return { ...message, segments: next };
      }
      return {
        ...message,
        segments: [...segs, { type: 'thinking', content: event.content, open: true }],
      };
    }

    case 'tool_start': {
      const runId = event.run_id || event.tool;
      return {
        ...message,
        segments: [
          ...segs,
          {
            type: 'tool',
            tool: {
              id: runId,
              name: event.name || event.tool,
              tool: event.tool,
              icon: event.icon || 'file-text',
              input: event.input || '',
              isSubagent: event.is_subagent,
              status: 'running' as const,
            },
          },
        ],
      };
    }

    case 'tool_end': {
      const runId = event.run_id || event.tool || 'unknown';
      const idx = segs.findIndex(
        (s) => s.type === 'tool' && s.tool.id === runId && s.tool.status === 'running',
      );
      const elapsed =
        event.elapsed_seconds != null ? `耗时 ${fmtElapsed(event.elapsed_seconds)}` : undefined;

      if (idx >= 0) {
        const seg = segs[idx];
        if (seg.type === 'tool') {
          const next = segs.slice();
          next[idx] = {
            type: 'tool',
            tool: {
              ...seg.tool,
              output: event.output ?? '',
              error: event.error,
              elapsed,
              status: 'done' as const,
            },
          };
          return { ...message, segments: next };
        }
      }

      // 孤儿 tool_end（无对应 pending）→ 单独建一张完成卡
      if (event.output || event.error) {
        return {
          ...message,
          segments: [
            ...segs,
            {
              type: 'tool',
              tool: {
                id: runId,
                name: event.tool || '未知工具',
                tool: event.tool || 'unknown',
                icon: 'file-text',
                input: '',
                output: event.output ?? '',
                error: event.error,
                elapsed,
                status: 'done' as const,
              },
            },
          ],
        };
      }
      return message;
    }

    case 'error': {
      return { ...message, segments: [...segs, { type: 'error', message: event.message }] };
    }

    case 'run_end': {
      if (event.finish_reason === 'cancelled') {
        return { ...message, segments: [...segs, { type: 'cancelled' }] };
      }
      return message;
    }

    default:
      return message;
  }
}

/** 状态条文案（返回 null 表示不改变当前文案） */
function labelFor(event: StreamEvent, thinkingEnabled: boolean): string | null {
  switch (event.type) {
    case 'run_start':
      return '正在生成…';
    case 'thinking_start':
    case 'tool_end':
      return thinkingEnabled ? '思考中…' : '生成中…';
    case 'token':
      return '生成中…';
    case 'reasoning':
      return thinkingEnabled ? '思考中…' : '生成中…';
    case 'sandbox_provisioning':
      return '环境准备中…';
    case 'progress':
      if (event.phase === 'provisioning') return '环境准备中…';
      if (event.phase === 'thinking') return thinkingEnabled ? '思考中…' : '生成中…';
      return '执行工具中…';
    case 'tool_start':
      return event.is_subagent ? '委派子代理中…' : '执行工具中…';
    case 'subagent_progress':
      return event.elapsed_seconds != null
        ? `委派子代理中… (${fmtElapsed(event.elapsed_seconds)})`
        : '委派子代理中…';
    default:
      return null;
  }
}

function handleSend(state: ChatState, action: Extract<ChatAction, { type: 'SEND' }>): ChatState {
  const exists = state.conversations.some((c) => c.id === action.conversationId);
  const conversations = exists
    ? state.conversations.map((c) =>
        c.id === action.conversationId ? { ...c, status: 'running' as ConversationStatus } : c,
      )
    : [
        {
          id: action.conversationId,
          title: action.title,
          status: 'running' as ConversationStatus,
          hasFiles: false,
        },
        ...state.conversations,
      ];

  const list = state.messages[action.conversationId] ?? [];
  const messages = {
    ...state.messages,
    [action.conversationId]: [...list, action.userMessage, action.assistantMessage],
  };

  return {
    conversations,
    messages,
    streaming: {
      conversationId: action.conversationId,
      label: '正在生成…',
      thinkingEnabled: action.thinkingEnabled,
    },
  };
}

function handleStreamEvent(
  state: ChatState,
  action: Extract<ChatAction, { type: 'STREAM_EVENT' }>,
): ChatState {
  const { conversationId, event } = action;
  const isCurrent = state.streaming?.conversationId === conversationId;

  // 1. 消息段更新（后台流也继续写自己的会话消息）
  let messages = state.messages;
  const list = state.messages[conversationId];
  if (list && list.length > 0) {
    const last = list[list.length - 1];
    if (last.role === 'assistant') {
      messages = {
        ...state.messages,
        [conversationId]: replaceLastMessage(list, applyEventToMessage(last, event)),
      };
    }
  }

  // 2. 标题 / 会话状态 / 状态条
  let conversations = state.conversations;
  let streaming = state.streaming;

  if (event.type === 'title_update') {
    conversations = conversations.map((c) =>
      c.id === conversationId ? { ...c, title: event.title } : c,
    );
  }

  if (event.type === 'run_end') {
    const status: ConversationStatus =
      event.finish_reason === 'cancelled'
        ? 'cancelled'
        : event.finish_reason === 'error'
          ? 'error'
          : 'completed';
    conversations = conversations.map((c) => (c.id === conversationId ? { ...c, status } : c));
    if (isCurrent) streaming = null;
  } else if (isCurrent && streaming) {
    const label = labelFor(event, streaming.thinkingEnabled);
    if (label) streaming = { ...streaming, label };
  }

  return { conversations, messages, streaming };
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'SEND':
      return handleSend(state, action);
    case 'STREAM_EVENT':
      return handleStreamEvent(state, action);
    case 'DELETE_CONVERSATION': {
      const messages = { ...state.messages };
      delete messages[action.conversationId];
      return {
        ...state,
        conversations: state.conversations.filter((c) => c.id !== action.conversationId),
        messages,
      };
    }
    case 'CONVERSATIONS_LOADED':
      return { ...state, conversations: action.conversations };
    case 'MESSAGES_LOADED':
      return {
        ...state,
        messages: { ...state.messages, [action.conversationId]: action.messages },
      };
  }
}
