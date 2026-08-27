'use client';

import { useEffect, useState } from 'react';
import { Download, ExternalLink, FileText, X } from 'lucide-react';
import type { FileNode } from '../types';
import { pyFetchBlob } from '../lib/pyNetwork';
import { downloadFile, openFileInBrowser } from '../lib/files';
import { fmtBytes } from '../api/mappers';
import { FileTypeIcon } from './icons';

type Kind = 'image' | 'text' | 'html' | 'pdf' | 'placeholder';

/** 可在新标签页用浏览器原生渲染的类型（text 是源码、placeholder 不可预览，不在此列） */
const OPENABLE_KINDS: Kind[] = ['image', 'pdf', 'html'];

interface LoadState {
  status: 'loading' | 'ready' | 'error';
  kind: Kind;
  text?: string;
  url?: string;
}

const TEXT_EXTS = [
  'py', 'js', 'ts', 'tsx', 'jsx', 'json', 'md', 'csv', 'txt', 'log',
  'yaml', 'yml', 'css', 'sh', 'sql',
];

function kindOf(file: FileNode): Kind {
  const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
  if (file.fileType === 'img' || ['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext)) {
    return 'image';
  }
  if (ext === 'pdf') return 'pdf';
  if (ext === 'html' || ext === 'htm') return 'html';
  if (TEXT_EXTS.includes(ext)) return 'text';
  return 'placeholder';
}

interface Props {
  file: FileNode | null;
  conversationId: string;
  onClose: () => void;
}

/** 文件预览弹窗（图片 / 文本 / 代码 / HTML / PDF / 占位），内容经 /files/{id} 带 auth 抓取 */
export default function FilePreviewModal({ file, conversationId, onClose }: Props) {
  const [state, setState] = useState<LoadState>({ status: 'loading', kind: 'placeholder' });

  useEffect(() => {
    if (!file || !file.virtualPath) {
      setState({ status: 'ready', kind: 'placeholder' });
      return;
    }
    const kind = kindOf(file);
    if (kind === 'placeholder') {
      setState({ status: 'ready', kind });
      return;
    }

    let cancelled = false;
    let objectUrl: string | null = null;
    setState({ status: 'loading', kind });

    pyFetchBlob(
      `/chat/files/${conversationId}?path=${encodeURIComponent(file.virtualPath)}`,
    )
      .then(async (blob) => {
        if (cancelled) return;
        if (kind === 'text' || kind === 'html') {
          setState({ status: 'ready', kind, text: await blob.text() });
        } else {
          objectUrl = URL.createObjectURL(blob);
          setState({ status: 'ready', kind, url: objectUrl });
        }
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'error', kind });
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [file, conversationId]);

  if (!file) return null;

  const meta = fmtBytes(file.size);
  const canDownload = !!file.virtualPath;

  return (
    <div
      className="fixed inset-0 z-[100] bg-black/60 flex items-center justify-center p-5"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl max-w-[900px] w-full max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-4 border-b border-gray-100">
          <div className="flex items-center gap-3 min-w-0">
            <span className="w-6 h-6 rounded-md bg-gray-100 flex items-center justify-center flex-shrink-0">
              <FileTypeIcon name={file.name} className="text-sm" />
            </span>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-gray-900 truncate">{file.name}</h3>
              <p className="text-xs text-gray-500 mt-0.5">{meta}</p>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {OPENABLE_KINDS.includes(state.kind) && (
              <button
                type="button"
                disabled={!canDownload}
                onClick={() => canDownload && openFileInBrowser(conversationId, file.virtualPath!)}
                className="inline-flex items-center gap-1.5 text-gray-700 border border-gray-200 hover:bg-gray-50 text-sm px-4 py-2 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <ExternalLink className="w-4 h-4" />
                在浏览器打开
              </button>
            )}
            <button
              type="button"
              disabled={!canDownload}
              onClick={() => canDownload && downloadFile(conversationId, file.virtualPath!)}
              className="inline-flex items-center gap-1.5 text-gray-700 border border-gray-200 hover:bg-gray-50 text-sm px-4 py-2 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Download className="w-4 h-4" />
              下载
            </button>
            <button
              type="button"
              onClick={onClose}
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
            >
              <X className="w-5 h-5 text-gray-500" />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-auto p-5 bg-gray-100">
          {state.status === 'loading' && (
            <div className="text-center py-16 text-gray-400 text-sm">加载中…</div>
          )}
          {state.status === 'error' && (
            <div className="text-center py-16 text-gray-400">
              <FileText className="w-12 h-12 mx-auto mb-3" />
              <p className="text-sm">加载失败，请重试</p>
            </div>
          )}
          {state.status === 'ready' && state.kind === 'image' && state.url && (
            <img src={state.url} alt={file.name} className="max-w-full rounded-lg mx-auto block" />
          )}
          {state.status === 'ready' && state.kind === 'text' && (
            <pre className="m-0 bg-white border border-gray-200 rounded-lg p-4 text-[13px] font-mono whitespace-pre-wrap text-gray-800">
              {state.text}
            </pre>
          )}
          {state.status === 'ready' && state.kind === 'html' && (
            <iframe
              title={file.name}
              srcDoc={state.text ?? ''}
              // 生成物 HTML 不可信：sandbox 用 opaque origin + 只放行脚本/表单/弹窗，
              // 绝不加 allow-same-origin（否则可逃逸沙箱、读到宿主页 token）。
              sandbox="allow-scripts allow-forms allow-modals allow-popups"
              referrerPolicy="no-referrer"
              className="w-full h-[70vh] rounded-lg border-0 bg-white"
            />
          )}
          {state.status === 'ready' && state.kind === 'pdf' && state.url && (
            <iframe src={state.url} title={file.name} className="w-full h-[70vh] rounded-lg border-0 bg-white" />
          )}
          {state.status === 'ready' && state.kind === 'placeholder' && (
            <div className="text-center py-16 text-gray-400">
              <FileText className="w-12 h-12 mx-auto mb-3" />
              <p className="text-sm">该文件类型暂不支持预览</p>
              <p className="text-xs mt-1">可直接下载后查看</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
