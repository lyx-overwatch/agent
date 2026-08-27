'use client';

import s from '../skillhub.module.scss';

interface Props {
  label?: string;
  visible?: boolean;
}

/** 生成状态条（常驻，文案由 progress phase 驱动） */
export default function GenStatusBar({ label = '执行工具中…', visible = true }: Props) {
  if (!visible) return null;
  return (
    <div className="text-[13px] text-gray-500 bg-white">
      <div className="max-w-3xl mx-auto px-4 flex items-center gap-2 pt-2 pb-0">
        <span className={s.genSpinner} />
        <span>{label}</span>
      </div>
    </div>
  );
}
