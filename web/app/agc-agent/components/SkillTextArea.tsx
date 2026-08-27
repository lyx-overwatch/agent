'use client';

interface SkillTextAreaProps {
  value: string;
  onChange: (value: string) => void;
  /** 默认两行高度 */
  rows?: number;
  maxLength?: number;
  /** 是否在右下角显示字数统计（value.length / maxLength） */
  showCount?: boolean;
  placeholder?: string;
  className?: string;
}

/** 自定义 textarea（原生实现），与技能页原生输入框的 border / focus 样式保持一致 */
export default function SkillTextArea({
  value,
  onChange,
  rows = 2,
  maxLength,
  showCount = false,
  placeholder,
  className = '',
}: SkillTextAreaProps) {
  return (
    <div className={className}>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={rows}
        maxLength={maxLength}
        placeholder={placeholder}
        className="block w-full px-3 py-2 rounded-lg border border-gray-200 text-sm outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-100 transition-all resize-none"
      />
      {showCount && (
        <div className="text-right text-xs text-gray-400 mt-1">
          {value.length}
          {maxLength ? ` / ${maxLength}` : ''}
        </div>
      )}
    </div>
  );
}
