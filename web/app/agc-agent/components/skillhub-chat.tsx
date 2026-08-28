'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { AlertError } from '../lib/alert';
import { skillhubApi, type AuthUser } from '../api/skillhub';
import { mapConversation, mapMessages, mapModel, mapWireEvent } from '../api/mappers';
import type { Attachment, Conversation, Message, Model } from '../types';
import { chatReducer, truncateTitle, type ChatState } from '../lib/chatReducer';
import { pyEventsourceFetch } from '../lib/pyEventsourceFetch';

const initialState: ChatState = { conversations: [], messages: {}, streaming: null };

export interface SendMessageOptions {
  /** 提供则继续该会话，否则新建会话（POST /conversations） */
  conversationId?: string;
  text: string;
  attachments: Attachment[];
  modelName?: string;
  /** 用户通过 @ 显式指定的技能（可选） */
  skillName?: string;
  thinkingEnabled: boolean;
}

async function resolveConversation(
  conversationId: string | undefined,
  files: File[],
): Promise<{ conversationId: string; fileMetadatas?: string }> {
  if (files.length > 0) {
    if (conversationId) {
      const res = await skillhubApi.appendFiles(conversationId, files);
      return { conversationId, fileMetadatas: JSON.stringify(res.files) };
    }
    const res = await skillhubApi.createConversation(files);
    return { conversationId: res.conversation_id, fileMetadatas: JSON.stringify(res.files) };
  }
  if (conversationId) {
    return { conversationId };
  }
  const res = await skillhubApi.createConversation();
  return { conversationId: res.conversation_id };
}

interface SkillhubChatContextValue {
  conversations: Conversation[];
  conversationsLoading: boolean;
  loadingMessagesId: string | null;
  messagesOf: (conversationId: string) => Message[];
  streaming: ChatState['streaming'];
  models: Model[];
  /** 当前选中的模型（跨页面共享，缺省回填首个模型） */
  modelName: string;
  setModelName: (name: string) => void;
  /** 深度思考开关（跨页面共享） */
  thinking: boolean;
  setThinking: (v: boolean) => void;
  /** 发送消息并启动 SSE 流，返回会话 id（新建或续用） */
  sendMessage: (opts: SendMessageOptions) => Promise<string>;
  stopGeneration: () => void;
  /** 删除会话：后端成功后才移除本地，返回是否成功 */
  deleteConversation: (conversationId: string) => Promise<boolean>;
  /** 打开会话时加载历史消息 */
  loadConversation: (conversationId: string) => void;
  /** 当前用户角色（verify 返回），skills 页据此显示「审核」入口 */
  role: string | null;
  /** 当前登录用户（verify 返回，含 email / username），侧边栏据此展示用户信息 */
  user: AuthUser | null;
}

const SkillhubChatContext = createContext<SkillhubChatContextValue | null>(null);

export function SkillhubChatProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(chatReducer, initialState);
  const [models, setModels] = useState<Model[]>([]);
  const [conversationsLoading, setConversationsLoading] = useState(true);
  const [loadingMessagesId, setLoadingMessagesId] = useState<string | null>(null);
  const [modelName, setModelName] = useState('');
  const [thinking, setThinking] = useState(true);
  const [role, setRole] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const streamingConvRef = useRef<string | null>(null);
  const pollingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const hasLoadedRef = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollingTimerRef.current) {
      clearInterval(pollingTimerRef.current);
      pollingTimerRef.current = null;
    }
  }, []);

  // loadConversations：拉会话列表 + 自停轮询挂钩点。
  // 存在 running/active 就每 3s 轮询 GET /conversations，全终态停表；瞬时网络错误静默忽略。
  const refreshConversations = useCallback(async () => {
    let list: Conversation[] = [];
    try {
      const { conversations } = await skillhubApi.listConversations();
      list = conversations.map(mapConversation);
      dispatch({ type: 'CONVERSATIONS_LOADED', conversations: list });
      hasLoadedRef.current = true;
    } catch (e) {
      // 首次加载失败弹提示；轮询中的瞬时网络错误静默忽略（见 progress 决策）
      if (!hasLoadedRef.current) AlertError('加载会话列表失败');
      return;
    } finally {
      setConversationsLoading(false);
    }

    const hasInFlight = list.some(
      (c) =>
        c.status === 'running' ||
        c.status === 'active' ||
        c.titlePending === true,
    );
    if (hasInFlight) {
      if (!pollingTimerRef.current) {
        pollingTimerRef.current = setInterval(() => {
          refreshConversations();
        }, 2000);
      }
    } else {
      stopPolling();
    }
  }, [stopPolling]);

  // 模型列表加载后回填默认模型（首个）
  useEffect(() => {
    if (!modelName && models[0]) setModelName(models[0].name);
  }, [models, modelName]);

  // 卸载时清理定时器
  useEffect(() => () => stopPolling(), [stopPolling]);

  // 启动时：verify（校验 + 自动注册）→ 拉会话列表 + 模型列表
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await skillhubApi.verify();
        if (!cancelled) {
          setRole(res.role);
          setUser({
            user_id: res.user_id,
            email: res.email,
            username: res.username,
            role: res.role,
          });
        }
      } catch (e) {
        console.warn('[skillhub] verify failed', e);
      }
      if (cancelled) return;
      refreshConversations();
      try {
        const { models } = await skillhubApi.getModels();
        if (!cancelled) setModels(models.map(mapModel));
      } catch (e) {
        console.warn('[skillhub] getModels failed', e);
        AlertError('加载模型列表失败');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshConversations]);

  const sendMessage = useCallback(
    async (opts: SendMessageOptions): Promise<string> => {
      const files = opts.attachments
        .map((a) => a.file)
        .filter((f): f is File => !!f);
      const { conversationId, fileMetadatas } = await resolveConversation(
        opts.conversationId,
        files,
      );

      const userMessage: Message = {
        id: `local-${Date.now()}-u`,
        role: 'user',
        content: opts.text,
        attachments: opts.attachments,
      };
      const assistantMessage: Message = {
        id: `local-${Date.now()}-a`,
        role: 'assistant',
        segments: [],
      };

      dispatch({
        type: 'SEND',
        conversationId,
        title: truncateTitle(opts.text),
        userMessage,
        assistantMessage,
        thinkingEnabled: opts.thinkingEnabled,
      });
      streamingConvRef.current = conversationId;

      const fd = new FormData();
      fd.append('message', opts.text);
      fd.append('conversation_id', conversationId);
      fd.append('thinking_enabled', String(opts.thinkingEnabled));
      if (opts.modelName) fd.append('model_name', opts.modelName);
      if (fileMetadatas) fd.append('file_metadatas', fileMetadatas);
      if (opts.skillName) fd.append('skill_name', opts.skillName);

      pyEventsourceFetch('/chat/stream', fd, {
        getAbortController: (c) => {
          abortRef.current = c;
        },
        onMessage: (data) => {
          const event = mapWireEvent(data);
          if (event) dispatch({ type: 'STREAM_EVENT', conversationId, event });
        },
        onClose: () => {
          abortRef.current = null;
          if (streamingConvRef.current === conversationId) {
            streamingConvRef.current = null;
          }
          refreshConversations();
        },
        onError: () => {
          abortRef.current = null;
          if (streamingConvRef.current !== conversationId) return; // 已本地停止
          streamingConvRef.current = null;
          dispatch({
            type: 'STREAM_EVENT',
            conversationId,
            event: { type: 'error', message: '网络连接中断，请重试。' },
          });
          dispatch({
            type: 'STREAM_EVENT',
            conversationId,
            event: { type: 'run_end', finish_reason: 'error' },
          });
          refreshConversations();
        },
      }).catch((e) => {
        console.warn('[skillhub] stream failed', e);
      });

      return conversationId;
    },
    [refreshConversations],
  );

  const stopGeneration = useCallback(() => {
    const conversationId = streamingConvRef.current;
    abortRef.current?.abort();
    abortRef.current = null;
    if (!conversationId) return;
    streamingConvRef.current = null;
    skillhubApi.stopStream(conversationId).catch(() => {});
    // 本地立即标记取消（后端后台任务随后落地 cancelled）
    dispatch({
      type: 'STREAM_EVENT',
      conversationId,
      event: { type: 'run_end', finish_reason: 'cancelled' },
    });
    refreshConversations();
  }, [refreshConversations]);

  const deleteConversation = useCallback(
    async (conversationId: string): Promise<boolean> => {
      try {
        await skillhubApi.deleteConversation(conversationId);
        dispatch({ type: 'DELETE_CONVERSATION', conversationId });
        return true;
      } catch (e) {
        console.warn('[skillhub] deleteConversation failed', e);
        AlertError('删除会话失败');
        return false;
      }
    },
    [],
  );

  const loadConversation = useCallback(async (conversationId: string) => {
    setLoadingMessagesId(conversationId);
    try {
      const { messages } = await skillhubApi.getMessages(conversationId);
      dispatch({
        type: 'MESSAGES_LOADED',
        conversationId,
        messages: mapMessages(messages),
      });
    } catch (e) {
      console.warn('[skillhub] getMessages failed', e);
      AlertError('加载消息失败');
    } finally {
      setLoadingMessagesId(null);
    }
  }, []);

  const messagesOf = useCallback(
    (conversationId: string) => state.messages[conversationId] ?? [],
    [state.messages],
  );

  const value = useMemo<SkillhubChatContextValue>(
    () => ({
      conversations: state.conversations,
      conversationsLoading,
      loadingMessagesId,
      messagesOf,
      streaming: state.streaming,
      models,
      modelName,
      setModelName,
      thinking,
      setThinking,
      sendMessage,
      stopGeneration,
      deleteConversation,
      loadConversation,
      role,
      user,
    }),
    [
      state.conversations,
      conversationsLoading,
      loadingMessagesId,
      state.streaming,
      state.messages,
      models,
      modelName,
      thinking,
      messagesOf,
      sendMessage,
      stopGeneration,
      deleteConversation,
      loadConversation,
      role,
      user,
    ],
  );

  return <SkillhubChatContext.Provider value={value}>{children}</SkillhubChatContext.Provider>;
}

export function useSkillhubChat(): SkillhubChatContextValue {
  const ctx = useContext(SkillhubChatContext);
  if (!ctx) {
    throw new Error('useSkillhubChat 必须在 SkillhubChatProvider 内使用');
  }
  return ctx;
}
