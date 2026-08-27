'use client';

import { useState } from 'react';
import { message } from 'antd';
import { FileArchive, X } from 'lucide-react';
import SkillTextArea from './SkillTextArea';

interface Props {
  open: boolean;
  onClose: () => void;
  /** 上传成功后由父组件刷新列表并提示 */
  onUpload: (file: File, displayName: string, description: string) => Promise<void>;
}

/** 上传技能弹窗（.zip / .skill / .md → 草稿） */
export default function UploadSkillModal({ open, onClose, onUpload }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [displayName, setDisplayName] = useState('');
  const [description, setDescription] = useState('');
  const [uploading, setUploading] = useState(false);

  if (!open) return null;

  const reset = () => {
    setFile(null);
    setDisplayName('');
    setDescription('');
  };

  const handleUpload = async () => {
    if (!file) {
      message.warning('请先选择 .zip / .skill / .md 文件');
      return;
    }
    setUploading(true);
    try {
      await onUpload(file, displayName.trim(), description.trim());
      reset();
      onClose();
    } catch (e) {
      console.warn('[skillhub] uploadSkill failed', e);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="absolute inset-0 flex items-center justify-center p-4">
        <div className="w-full max-w-md bg-white rounded-xl shadow-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-base font-semibold text-gray-900">上传新技能</h3>
            <button
              type="button"
              title="关闭"
              onClick={onClose}
              className="p-1 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <label className="flex items-center gap-2 px-3 h-10 rounded-lg border border-dashed border-gray-300 text-sm text-gray-500 cursor-pointer hover:border-gray-400 hover:bg-gray-50 transition-colors">
            <FileArchive className="w-4 h-4 text-gray-400 shrink-0" />
            <span className="truncate">
              {file ? file.name : '选择 .zip / .skill / .md 文件'}
            </span>
            <input
              type="file"
              accept=".zip,.skill,.md"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>

          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="展示名（可选，默认取 name）"
            className="w-full h-10 px-3 mt-3 rounded-lg border border-gray-200 text-sm outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-100 transition-all"
          />
          <SkillTextArea
            value={description}
            onChange={setDescription}
            rows={2}
            maxLength={1024}
            placeholder="技能描述（可选，默认取 description）"
            className="mt-3"
          />

          <p className="text-xs text-gray-400 mt-3">
            支持 .zip 压缩包、.skill 技能包（zip 或 Markdown 均可）、或 .md 单文件。一个 zip 归档只能包含一个技能，多个技能请分开打包。上传后保存为「草稿」，可发布后经审核进入广场。
          </p>

          <div className="flex justify-end gap-2 mt-5">
            <button
              type="button"
              onClick={onClose}
              className="h-9 px-4 rounded-lg border border-gray-200 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
            >
              取消
            </button>
            <button
              type="button"
              disabled={uploading}
              onClick={handleUpload}
              className="h-9 px-4 rounded-lg bg-gray-900 text-white text-sm font-medium hover:bg-gray-800 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {uploading ? '上传中…' : '上传'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
