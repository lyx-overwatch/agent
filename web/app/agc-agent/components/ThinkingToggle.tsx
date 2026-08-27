'use client';

import { Lock } from 'lucide-react';
import classNames from 'classnames';

interface Props {
  enabled: boolean;
  /** 锁定（模型强制开启，不可关闭） */
  locked?: boolean;
  onToggle: () => void;
}

/** 深度思考开关 */
export default function ThinkingToggle({ enabled, locked, onToggle }: Props) {
  return (
    <button
      type="button"
      title={locked ? '深度思考（锁定）' : '深度思考'}
      onClick={() => {
        if (!locked) onToggle();
      }}
      className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
    >
      <span
        className={classNames(
          'w-[34px] h-5 rounded-[10px] relative transition-colors flex-shrink-0',
          enabled ? 'bg-[#0072ff]' : 'bg-gray-300',
        )}
      >
        <span
          className={classNames(
            'absolute w-4 h-4 rounded-full bg-white top-[2px] left-[2px] transition-transform',
            enabled && 'translate-x-[14px]',
          )}
        />
      </span>
      <span>深度思考</span>
      {locked && <Lock className="w-3 h-3 text-gray-400" />}
    </button>
  );
}
