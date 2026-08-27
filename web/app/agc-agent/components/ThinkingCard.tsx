'use client';

import { useState } from 'react';
import { ChevronRight, Lightbulb } from 'lucide-react';

interface Props {
  content: string;
  defaultOpen?: boolean;
}

/** 思考折叠卡（默认展开，icon lightbulb，文案固定「深度思考」） */
export default function ThinkingCard({ content, defaultOpen = true }: Props) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-600 transition-colors mt-2"
      >
        <Lightbulb className="w-3.5 h-3.5" />
        <span>深度思考</span>
        <ChevronRight
          className={`w-3 h-3 transition-transform ${open ? 'rotate-90' : ''}`}
        />
      </button>
      {open && (
        <div className="bg-gray-50 rounded-lg px-4 py-3 mt-2">
          <p className="text-xs text-gray-500 leading-relaxed">{content}</p>
        </div>
      )}
    </div>
  );
}
