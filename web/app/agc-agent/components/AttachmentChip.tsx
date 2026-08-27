'use client';

import { X } from 'lucide-react';
import type { Attachment } from '../types';
import { FileTypeIcon } from './icons';

interface Props {
  attachment: Attachment;
  onRemove?: (id: string) => void;
}

/** 附件 chip（用户消息内只读 / 输入区可移除） */
export default function AttachmentChip({ attachment, onRemove }: Props) {
  return (
    <span className="inline-flex items-center gap-1.5 px-2 py-1 border border-gray-200 rounded-lg bg-white text-xs text-gray-700">
      <FileTypeIcon name={attachment.name} className="text-xs" />
      <span className="max-w-[180px] truncate">{attachment.name}</span>
      {onRemove && (
        <button
          type="button"
          title="移除附件"
          onClick={() => onRemove(attachment.id)}
          className="-mr-0.5 w-4 h-4 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-200 transition-colors inline-flex items-center justify-center"
        >
          <X className="w-3 h-3" />
        </button>
      )}
    </span>
  );
}
