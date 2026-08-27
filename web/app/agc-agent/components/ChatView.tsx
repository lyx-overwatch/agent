'use client';

import { useEffect, useMemo, useRef, type MutableRefObject } from 'react';
import { useContext } from 'use-context-selector';
import classNames from 'classnames';
import type { Message } from '../types';
import MessageBubble from './MessageBubble';
import ScrollArea from '@/components/ScrollArea';
import ScrollAreaContext from '@/components/ScrollArea/context';
import QuestionAnchor from './QuestionAnchor';
import s from '../skillhub.module.scss';

const SCROLL_CONTAINER_ID = 'skillhub-scroll-container';
const QUESTION_PREFIX = 'skillhub-question';
const QUESTION_ANCHOR_THRESHOLD = 3;

/** 桥接 ScrollAreaContext 的 disableAutoScroll / resetScrollTag：
 *  - disableAutoScroll：点击锚点跳转前禁用自动滚动，避免流式输出又把容器拽回底部
 *  - resetScrollTag：发送新问题后重新开启自动滚动并滚到底部
 */
function AutoScrollBridge({
  disableAutoScrollRef,
  resetScrollTagRef,
}: {
  disableAutoScrollRef: MutableRefObject<(() => void) | undefined>;
  resetScrollTagRef: MutableRefObject<(() => void) | undefined>;
}) {
  const { disableAutoScroll, resetScrollTag } = useContext(ScrollAreaContext);
  useEffect(() => {
    disableAutoScrollRef.current = disableAutoScroll;
    resetScrollTagRef.current = resetScrollTag;
  }, [disableAutoScroll, resetScrollTag, disableAutoScrollRef, resetScrollTagRef]);
  return null;
}

interface Props {
  messages: Message[];
  /** 历史消息加载中 */
  loading?: boolean;
}

/** 消息列表容器（ScrollArea observe + delayScroll：自动滚动到底部；含问题锚点快速定位） */
export default function ChatView({ messages, loading = false }: Props) {
  const disableAutoScrollRef = useRef<(() => void) | undefined>(undefined);
  const resetScrollTagRef = useRef<(() => void) | undefined>(undefined);

  // 最后一条用户消息的 id：发送新问题 / 加载历史时会变化，据此重置自动滚动并滚到底部
  const lastUserMessageId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'user') return messages[i].id;
    }
    return undefined;
  }, [messages]);

  const lastUserMessageIdRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (lastUserMessageIdRef.current === lastUserMessageId) return;
    lastUserMessageIdRef.current = lastUserMessageId;
    // 新问题已渲染到 DOM：重新开启自动滚动（用户此前手动上滚会被重置），并立即滚到底部
    resetScrollTagRef.current?.();
    const container = document.getElementById(SCROLL_CONTAINER_ID);
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
    }
  }, [lastUserMessageId]);

  // 提取「问题」（用户消息）及每条用户消息的锚点 id（按 messages 数组下标对齐）
  const { questions, anchorIds } = useMemo(() => {
    const qs: string[] = [];
    const ids: (string | undefined)[] = [];
    let q = 0;
    for (const m of messages) {
      if (m.role === 'user') {
        qs.push(m.content ?? '');
        ids.push(`${QUESTION_PREFIX}-${q++}`);
      } else {
        ids.push(undefined);
      }
    }
    return { questions: qs, anchorIds: ids };
  }, [messages]);

  const scrollToQuestion = (index: number) => {
    disableAutoScrollRef.current?.();
    const container = document.getElementById(SCROLL_CONTAINER_ID);
    const target = document.getElementById(`${QUESTION_PREFIX}-${index}`);
    if (container && target) {
      const top =
        target.getBoundingClientRect().top -
        container.getBoundingClientRect().top +
        container.scrollTop -
        12;
      container.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
    }
  };

  return (
    <div className="flex-1 min-h-0 relative">
      <ScrollArea
        id={SCROLL_CONTAINER_ID}
        observe
        delayScroll
        className={classNames('max-w-3xl mx-auto', s.hideScrollbar)}
      >
        <AutoScrollBridge
          disableAutoScrollRef={disableAutoScrollRef}
          resetScrollTagRef={resetScrollTagRef}
        />
        <div className="px-4 py-6">
          {loading ? (
            <p className="text-center text-gray-400 text-sm py-10">加载中…</p>
          ) : (
            messages.map((message, i) => (
              <MessageBubble key={message.id} message={message} anchorId={anchorIds[i]} />
            ))
          )}
        </div>
      </ScrollArea>

      {questions.length >= QUESTION_ANCHOR_THRESHOLD && (
        <QuestionAnchor
          questions={questions}
          onItemClick={scrollToQuestion}
          scrollContainerId={SCROLL_CONTAINER_ID}
          itemIdPrefix={QUESTION_PREFIX}
        />
      )}
    </div>
  );
}
