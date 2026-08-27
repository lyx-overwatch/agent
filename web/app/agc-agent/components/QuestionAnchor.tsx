'use client';

import React, { useEffect, useRef, useState } from 'react';

/** tick 最大显示数量（超过则窗口化，跟随 activeIndex） */
const QUESTION_ANCHOR_MAX_TICKS = 20;

interface QuestionAnchorProps {
  /** 问题文本列表（用户消息） */
  questions: string[];
  /** 点击 tick / 面板项回调（参数为问题序号） */
  onItemClick: (index: number) => void;
  /** 滚动容器 id */
  scrollContainerId: string;
  /** 问题元素 id 前缀（`${itemIdPrefix}-${index}`） */
  itemIdPrefix: string;
}

/** 问题锚点：消息区右侧窄竖条，hover 展开问题列表，滚动时高亮当前问题（对齐 aigc-main QuestionAnchor） */
function QuestionAnchor({
  questions,
  onItemClick,
  scrollContainerId,
  itemIdPrefix,
}: QuestionAnchorProps) {
  const [hovered, setHovered] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const enter = () => {
    clearTimeout(timerRef.current);
    setHovered(true);
  };

  const leave = () => {
    timerRef.current = setTimeout(() => setHovered(false), 120);
  };

  useEffect(() => {
    const container = document.getElementById(scrollContainerId);
    if (!container) return;

    const computeActive = () => {
      const containerRect = container.getBoundingClientRect();
      let active = 0;
      let minVisibleTop = Infinity;
      let lastAbove = 0;

      for (let i = 0; i < questions.length; i++) {
        const el = document.getElementById(`${itemIdPrefix}-${i}`);
        if (el) {
          const relativeTop = el.getBoundingClientRect().top - containerRect.top;
          if (relativeTop >= 0) {
            if (relativeTop < minVisibleTop) {
              minVisibleTop = relativeTop;
              active = i;
            }
          } else {
            lastAbove = i;
          }
        }
      }

      // 没有标题在视口内（全在上方），取最后一个在视口上方的
      if (minVisibleTop === Infinity) {
        active = lastAbove;
      }
      setActiveIndex(active);
    };

    container.addEventListener('scroll', computeActive, { passive: true });
    computeActive();

    return () => {
      container.removeEventListener('scroll', computeActive);
    };
  }, [scrollContainerId, itemIdPrefix, questions.length]);

  const total = questions.length;
  const windowSize = QUESTION_ANCHOR_MAX_TICKS;
  let startIndex = 0;
  if (total > windowSize) {
    startIndex = Math.max(0, activeIndex - windowSize + 1);
    startIndex = Math.min(startIndex, total - windowSize);
  }
  const tickCount = Math.min(total, windowSize);
  const ticks = Array.from({ length: tickCount }, (_, i) => startIndex + i);

  return (
    <div className="absolute right-5 top-0 bottom-0 w-5 z-10">
      <div
        className="w-5 flex flex-col items-center justify-center gap-2 absolute right-0 top-1/2 -translate-y-1/2"
        onMouseEnter={enter}
        onMouseLeave={leave}
      >
        {ticks.map((qi) => (
          <button
            key={qi}
            type="button"
            aria-label={`定位到第 ${qi + 1} 个问题`}
            onClick={() => onItemClick(qi)}
            className={`p-0 border-0 outline-none w-[18px] h-[2px] rounded-[1px] flex-shrink-0 cursor-pointer ${
              qi === activeIndex ? 'bg-black' : 'bg-[#8f8f8f]'
            }`}
          />
        ))}
      </div>

      {hovered && (
        <div
          className="absolute right-5 top-1/2 -translate-y-1/2 w-60 max-h-[364px] bg-white rounded-lg shadow-lg border border-gray-200 overflow-hidden flex flex-col"
          onMouseEnter={enter}
          onMouseLeave={leave}
        >
          <div className="overflow-y-auto py-2">
            {questions.map((content, index) => (
              <div
                key={index}
                onClick={() => onItemClick(index)}
                title={content}
                className={`px-3 py-2 text-[13px] text-gray-800 cursor-pointer whitespace-nowrap overflow-hidden text-ellipsis transition-colors ${
                  index === activeIndex ? 'bg-gray-100' : 'hover:bg-gray-50'
                }`}
              >
                {content}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default React.memo(QuestionAnchor);
