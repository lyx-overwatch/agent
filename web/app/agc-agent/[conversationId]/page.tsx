'use client';

import { use, useCallback, useEffect, useRef, useState } from 'react';
import { PanelRight } from 'lucide-react';
import ChatView from '../components/ChatView';
import FilePreviewModal from '../components/FilePreviewModal';
import FileTreePanel from '../components/FileTreePanel';
import GenStatusBar from '../components/GenStatusBar';
import InputArea from '../components/InputArea';
import PageHeader from '../components/PageHeader';
import { useSkillhubChat } from '../components/skillhub-chat';
import { skillhubApi } from '../api/skillhub';
import { mapFileTree } from '../api/mappers';
import { downloadDirectory, downloadFile } from '../lib/files';
import type { ConversationStatus, FileNode } from '../types';

/** 生成中的会话状态（断线后轮询补齐正文的判定依据） */
const IN_FLIGHT_STATUSES: ConversationStatus[] = ['pending', 'active', 'running'];
/** 终态 —— 本轮已停止，正文/工具记录已落库 */
const TERMINAL_STATUSES: ConversationStatus[] = ['completed', 'error', 'cancelled', 'step_limit'];

/** 会话详情页（承载完整 Agent 对话：侧栏 + 对话流 + 文件树 + 预览） */
export default function ConversationDetailPage({
  params,
}: {
  params: Promise<{ conversationId: string }>;
}) {
  const { conversationId } = use(params);
  const { conversations, messagesOf, streaming, models, loadingMessagesId, loadConversation } =
    useSkillhubChat();
  const [fileCollapsed, setFileCollapsed] = useState(false);
  const [fileFullscreen, setFileFullscreen] = useState(false);
  const [preview, setPreview] = useState<FileNode | null>(null);
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [fileTreeLoading, setFileTreeLoading] = useState(true);

  const conv = conversations.find((c) => c.id === conversationId);
  const title = conv?.title ?? '对话';
  const tokens = conv?.tokens;
  const cacheRate = conv?.cacheRate;
  const messages = messagesOf(conversationId);
  const isStreaming = streaming?.conversationId === conversationId;
  const convStatus = conv?.status;
  // 断线后仍在生成：本地无 SSE 流（刷新 / 跨 layout 切走），但后端状态仍是 running。
  const generatingOffline = !isStreaming && (convStatus ? IN_FLIGHT_STATUSES.includes(convStatus) : false);

  // 打开会话时加载历史（流式中 / 已有内存消息时跳过，避免覆盖在途内容）。
  // conv 为空（会话已被删除）时不再拉取，否则删除会清空 messages 触发本条 effect 重跑 → 请求已删会话 404。
  useEffect(() => {
    if (isStreaming || messages.length > 0) return;
    if (!conv) return;
    loadConversation(conversationId);
  }, [conversationId, isStreaming, messages.length, loadConversation, conv]);

  // 断线后（刷新 / 切到其他 layout）本会话没有活跃 SSE 流，正文要等回合结束才落库。
  // 轮询把状态从「生成中」翻成终态时，自动重拉一次历史补齐正文。
  // prevStreaming 用于排除 SSE 正常结束的场景（此时内存里已有完整内容，无需重拉）。
  const refillPrevStatusRef = useRef<ConversationStatus | undefined>(convStatus);
  const refillPrevStreamingRef = useRef(isStreaming);
  useEffect(() => {
    const prevStatus = refillPrevStatusRef.current;
    const prevStreaming = refillPrevStreamingRef.current;
    refillPrevStatusRef.current = convStatus;
    refillPrevStreamingRef.current = isStreaming;

    if (prevStreaming) return;
    if (!prevStatus || !convStatus) return;
    if (IN_FLIGHT_STATUSES.includes(prevStatus) && TERMINAL_STATUSES.includes(convStatus)) {
      loadConversation(conversationId);
    }
  }, [convStatus, isStreaming, loadConversation, conversationId]);

  const loadFileTree = useCallback(async () => {
    setFileTreeLoading(true);
    try {
      const { roots } = await skillhubApi.getFileTree(conversationId);
      setFileTree(mapFileTree(roots));
    } catch (e) {
      console.warn('[skillhub] getFileTree failed', e);
    } finally {
      setFileTreeLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    loadFileTree();
  }, [loadFileTree]);

  // 流结束后刷新文件树（本轮可能生成了新文件）
  const prevStreamingRef = useRef(isStreaming);
  useEffect(() => {
    if (prevStreamingRef.current && !isStreaming) loadFileTree();
    prevStreamingRef.current = isStreaming;
  }, [isStreaming, loadFileTree]);

  const hasFiles = fileTree.some((r) => (r.children?.length ?? 0) > 0);

  const shortMeta = cacheRate ? `${tokens} · ${cacheRate}` : tokens;
  const fullMeta = cacheRate
    ? `${tokens} tokens · 缓存命中率 ${cacheRate}`
    : `${tokens} tokens`;

  const handleToggleFullscreen = () => {
    setFileFullscreen((v) => !v);
    setFileCollapsed(false);
  };

  const handleCollapse = () => {
    setFileCollapsed(true);
    setFileFullscreen(false);
  };

  const handleDownload = (node: FileNode) => {
    if (node.virtualPath) downloadFile(conversationId, node.virtualPath);
  };

  const handleDownloadDir = (node: FileNode) => {
    if (node.virtualPath) downloadDirectory(conversationId, node.virtualPath);
  };

  return (
    <>
      {!fileFullscreen && (
        <main className="flex-1 flex flex-col min-w-0 relative bg-white">
          <PageHeader
            title={title}
            right={
              <div className="flex items-center gap-2 flex-shrink-0">
                {tokens && (
                  <span
                    className="text-[13px] font-medium text-gray-600 cursor-help"
                    title={fullMeta}
                  >
                    {shortMeta}
                  </span>
                )}
                {fileCollapsed && (
                  <button
                    type="button"
                    title="展开文件树"
                    onClick={() => setFileCollapsed(false)}
                    className="p-2 -mr-1 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                  >
                    <PanelRight className="w-4 h-4" />
                  </button>
                )}
              </div>
            }
          />

          <ChatView
            messages={messages}
            loading={loadingMessagesId === conversationId && messages.length === 0}
          />
          <GenStatusBar label={streaming?.label ?? '正在生成…'} visible={isStreaming || generatingOffline} />

          <div className="bg-white flex-shrink-0">
            <div className="max-w-3xl mx-auto px-4 pt-1 pb-4">
              <InputArea
                key={conversationId}
                models={models}
                conversationId={conversationId}
                placeholder="输入消息，@ 指定技能 (Enter 发送, Shift+Enter 换行)"
              />
            </div>
          </div>
        </main>
      )}

      <FileTreePanel
        tree={fileTree}
        hasFiles={hasFiles}
        loading={fileTreeLoading}
        collapsed={fileCollapsed}
        fullscreen={fileFullscreen}
        onPreview={setPreview}
        onDownload={handleDownload}
        onDownloadDir={handleDownloadDir}
        onCollapse={handleCollapse}
        onToggleFullscreen={handleToggleFullscreen}
      />

      <FilePreviewModal
        file={preview}
        conversationId={conversationId}
        onClose={() => setPreview(null)}
      />
    </>
  );
}
