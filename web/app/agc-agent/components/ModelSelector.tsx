'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import type { Model } from '../types';

interface Props {
  models: Model[];
  value: string;
  onChange: (name: string) => void;
}

/** 模型下拉（展示 display_name，值为模型键 name） */
export default function ModelSelector({ models, value, onChange }: Props) {
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
                <span className="text-sm text-gray-700">{m.displayName ?? m.name}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
