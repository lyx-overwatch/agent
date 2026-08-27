// ⚠️ 占位文件（STUB）—— 明天从原项目拷贝真实源码后整体替换本文件。
// 此处仅保证「类型签名 + 导出名」与所有调用点对齐，让项目能通过编译。
// 核心的 SSE 流式 segment 追加状态机尚未实现（见 STREAM_EVENT 分支的 TODO）。

import type { Conversation, Message, StreamEvent } from '../types';

/** 流式进行中的会话状态（供 InputArea 停止按钮 + GenStatusBar 文案使用） */
export interface StreamingState {
  conversationId: string;
  label: string;
}

export interface ChatState {
  conversations: Conversation[];
  messages: Record<string, Message[]>;
  streaming: StreamingState | null;
}

export type ChatAction =
  | { type: 'CONVERSATIONS_LOADED'; conversations: Conversation[] }
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
  | { type: 'MESSAGES_LOADED'; conversationId: string; messages: Message[] };

export const initialState: ChatState = {
  conversations: [],
  messages: {},
  streaming: null,
};

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'CONVERSATIONS_LOADED':
      return { ...state, conversations: action.conversations };

    case 'SEND': {
      const { conversationId, title, userMessage, assistantMessage } = action;
      const existing = state.messages[conversationId] ?? [];
      const isNew = !state.conversations.some((c) => c.id === conversationId);
      const conversations = isNew
        ? [{ id: conversationId, title, status: 'running' as const }, ...state.conversations]
        : state.conversations;
      return {
        ...state,
        conversations,
        messages: {
          ...state.messages,
          [conversationId]: [...existing, userMessage, assistantMessage],
        },
        streaming: { conversationId, label: '正在生成…' },
      };
    }

    case 'STREAM_EVENT': {
      // TODO(占位): 真实实现需按 event.type 追加/更新最后一个 assistant 消息的
      // segments（token → text、reasoning → thinking、tool_start/tool_end → tool、
      // error → error、title_update → 更新标题），并维护 streaming.label / 置空。
      const { conversationId, event } = action;
      let streaming = state.streaming;
      if (event.type === 'tool_start') {
        streaming = { conversationId, label: `正在执行 ${event.name ?? event.tool}…` };
      } else if (event.type === 'run_end') {
        streaming = null;
      }
      return { ...state, streaming };
    }

    case 'DELETE_CONVERSATION': {
      const conversations = state.conversations.filter(
        (c) => c.id !== action.conversationId,
      );
      const messages = { ...state.messages };
      delete messages[action.conversationId];
      return { ...state, conversations, messages };
    }

    case 'MESSAGES_LOADED':
      return {
        ...state,
        messages: { ...state.messages, [action.conversationId]: action.messages },
      };

    default:
      return state;
  }
}

/** 把用户输入压缩为会话标题（去换行、截断）。 */
export function truncateTitle(text: string): string {
  const normalized = text.replace(/\s+/g, ' ').trim();
  return normalized.length > 30 ? `${normalized.slice(0, 30)}…` : normalized;
}

/** 秒数 → 中文耗时文案（如 2分10秒）。 */
export function fmtElapsed(seconds: number): string {
  if (seconds < 1) return '不到1秒';
  if (seconds < 60) return `${Math.round(seconds)}秒`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (seconds < 3600) return s > 0 ? `${m}分${s}秒` : `${m}分钟`;
  const h = Math.floor(seconds / 3600);
  const rm = Math.floor((seconds % 3600) / 60);
  return `${h}小时${rm}分`;
}
