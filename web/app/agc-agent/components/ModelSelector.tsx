'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Lock } from 'lucide-react';
import classNames from 'classnames';
import type { Model } from '../types';

interface Props {
  models: Model[];
  value: string;
  onChange: (name: string) => void;
  /** 深度思考开关状态（移入菜单内展示） */
  thinkingEnabled: boolean;
  /** 锁定（模型强制开启深度思考，不可关闭） */
  thinkingLocked: boolean;
  onToggleThinking: () => void;
}

/** 模型下拉（展示 display_name，值为模型键 name；菜单内含深度思考开关） */
export default function ModelSelector({ models, value, onChange, thinkingEnabled, thinkingLocked, onToggleThinking }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, []);

  const current = models.find((m) => m.name === value);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-gray-700 bg-gray-50 hover:bg-gray-100 rounded-lg transition-colors"
      >
        <span>{current?.displayName ?? value}</span>
        <ChevronDown className="w-3 h-3 text-gray-400" />
      </button>
      {open && (
        <div className="absolute z-50 bg-white border border-gray-200 rounded-xl shadow-[0_10px_30px_rgba(0,0,0,0.1)] p-1.5 bottom-full left-0 mb-2 w-60">
          <p className="px-3 py-2 text-xs text-gray-400 border-b border-gray-100">
            选择模型
          </p>
          <div className="py-1">
            {models.map((m) => (
              <button
                key={m.name}
                type="button"
                onClick={() => {
                  onChange(m.name);
                  setOpen(false);
                }}
                className="w-full flex items-center px-3 py-2 rounded-md hover:bg-gray-50 text-left"
              >
                <span className="text-xs text-gray-700">{m.displayName ?? m.name}</span>
              </button>
            ))}
          </div>
          <div className="border-t border-gray-100 mt-1 pt-1">
            <button
              type="button"
              disabled={thinkingLocked}
              onClick={onToggleThinking}
              title={thinkingLocked ? '深度思考（锁定）' : '深度思考'}
              className="w-full flex items-center justify-between px-3 py-2 rounded-md hover:bg-gray-50 disabled:cursor-not-allowed"
            >
              <span className="flex items-center gap-1.5 text-xs text-gray-700">
                深度思考
                {thinkingLocked && <Lock className="w-3 h-3 text-gray-400" />}
              </span>
              <span
                className={classNames(
                  'w-[34px] h-5 rounded-[10px] relative transition-colors flex-shrink-0',
                  thinkingEnabled ? 'bg-[#0072ff]' : 'bg-gray-300',
                )}
              >
                <span
                  className={classNames(
                    'absolute w-4 h-4 rounded-full bg-white top-[2px] left-[2px] transition-transform',
                    thinkingEnabled && 'translate-x-[14px]',
                  )}
                />
              </span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
