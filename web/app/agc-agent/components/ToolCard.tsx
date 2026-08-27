'use client';

import { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import classNames from 'classnames';
import type { ToolCall } from '../types';
import { ToolIcon } from './icons';
import s from '../skillhub.module.scss';

interface Props {
  tool: ToolCall;
  defaultOpen?: boolean;
}

/** 工具调用卡（含子代理 task 变体，输入/输出/耗时） */
export default function ToolCard({ tool, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const subagent = !!tool.isSubagent;

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={classNames(
          'w-full flex items-center gap-2 px-3 py-2 rounded-lg border bg-white transition-colors text-left',
          subagent
            ? 'border-[#cce5ff] hover:border-[#99ccff]'
            : 'border-gray-200 hover:border-gray-300',
        )}
      >
        <span className="w-6 h-6 rounded-md bg-gray-100 flex items-center justify-center flex-shrink-0">
          <ToolIcon icon={tool.icon} className="w-3.5 h-3.5 text-gray-500" />
        </span>
        <span className="text-sm font-medium text-gray-800 flex-1 truncate">
          {tool.name}
        </span>
        <span
          className={classNames(
            'text-[10px] px-1.5 py-0.5 rounded flex-shrink-0',
            subagent ? 'bg-[#cce5ff] text-[#0072ff]' : 'bg-gray-100 text-gray-500',
          )}
        >
          {tool.tool}
        </span>
        {tool.elapsed && (
          <span className="text-[11px] text-gray-400 flex-shrink-0">
            {tool.elapsed}
          </span>
        )}
        <ChevronRight
          className={classNames(
            'w-3.5 h-3.5 text-gray-400 flex-shrink-0 transition-transform',
            open && 'rotate-90',
          )}
        />
      </button>
      {open && (
        <div className="mt-1.5 border border-gray-200 rounded-lg overflow-hidden">
          <div className="px-3 py-2 border-b border-gray-100">
            <p className="text-[11px] font-medium text-gray-400 mb-1">输入</p>
            <pre className="text-xs text-gray-700 font-mono whitespace-pre-wrap m-0">
              {tool.input}
            </pre>
          </div>
          {tool.status === 'running' ? (
            <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 text-xs text-gray-400">
              <span className={s.genSpinner} />
              {tool.isSubagent ? '子代理执行中…' : '等待结果…'}
            </div>
          ) : (
            <>
              {tool.error && (
                <div className="px-3 py-2 border-b border-red-100 bg-red-50/50">
                  <p className="text-[11px] font-medium text-red-400 mb-1">错误</p>
                  <pre className="text-xs text-red-500 font-mono whitespace-pre-wrap m-0">
                    {tool.error}
                  </pre>
                </div>
              )}
              {tool.output && (
                <div className="px-3 py-2 bg-gray-50">
                  <p className="text-[11px] font-medium text-gray-400 mb-1">输出</p>
                  <pre className="text-xs text-gray-600 font-mono whitespace-pre-wrap m-0">
                    {tool.output}
                  </pre>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
