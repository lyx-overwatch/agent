'use client';

import { AlertCircle, AlertTriangle, Copy } from 'lucide-react';
import { toast } from 'sonner';
import copy from 'copy-to-clipboard';
import { Markdown } from '@/components/base/markdown';
import type { Message, MessageSegment } from '../types';
import AttachmentChip from './AttachmentChip';
import ThinkingCard from './ThinkingCard';
import ToolCard from './ToolCard';
import s from '../skillhub.module.scss';

function UserMessage({ message, anchorId }: { message: Message; anchorId?: string }) {
  const handleCopy = () => {
    copy(message.content ?? '');
    toast.success('复制成功');
  };

  return (
    <div id={anchorId} className={`group flex justify-end items-center gap-2 mb-6 ${s.messageEnter}`}>
      {message.content && (
        <button
          type="button"
          title="复制"
          onClick={handleCopy}
          className="opacity-0 group-hover:opacity-100 transition-opacity p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg shrink-0"
        >
          <Copy className="w-4 h-4" />
        </button>
      )}
      <div className="max-w-[80%] bg-gray-100 rounded-2xl rounded-tr-md px-4 py-3">
        {message.attachments && message.attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {message.attachments.map((att) => (
              <AttachmentChip key={att.id} attachment={att} />
            ))}
          </div>
        )}
        {message.content && (
          <p className="text-sm text-gray-800 whitespace-pre-wrap">{message.content}</p>
        )}
      </div>
    </div>
  );
}

function Segment({ segment }: { segment: MessageSegment }) {
  switch (segment.type) {
    case 'thinking':
      return <ThinkingCard content={segment.content} defaultOpen={segment.open} />;
    case 'text':
      return (
        <div className="mt-3">
          <Markdown content={segment.content} />
        </div>
      );
    case 'tool':
      return <ToolCard tool={segment.tool} />;
    case 'error':
      return (
        <div className="border border-red-100 bg-red-50/60 rounded-lg overflow-hidden">
          <div className="flex items-start gap-2 px-3 py-2">
            <AlertTriangle className="w-3.5 h-3.5 text-red-500 mt-0.5 flex-shrink-0" />
            <pre className="text-xs text-red-500 font-mono whitespace-pre-wrap m-0">
              {segment.message}
            </pre>
          </div>
        </div>
      );
    case 'cancelled':
      return (
        <div className="mt-2 flex items-center gap-2 text-xs text-amber-600 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
          <AlertCircle className="w-3.5 h-3.5" />
          生成被中断
        </div>
      );
    default:
      return null;
  }
}

function AssistantMessage({ message }: { message: Message }) {
  return (
    <div className={`mb-6 ${s.messageEnter}`}>
      {message.segments?.map((segment, index) => (
        <Segment key={index} segment={segment} />
      ))}
    </div>
  );
}

/** 消息气泡：用户（右对齐灰底）/ 助手（左对齐，无头像，交错段）；anchorId 用于问题锚点定位 */
export default function MessageBubble({ message, anchorId }: { message: Message; anchorId?: string }) {
  return message.role === 'user' ? (
    <UserMessage message={message} anchorId={anchorId} />
  ) : (
    <AssistantMessage message={message} />
  );
}
