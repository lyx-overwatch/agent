'use client';

import { useState } from 'react';
import {
  ChevronRight,
  ChevronsRight,
  Download,
  Folder,
  FolderOpen,
  Maximize2,
  Minimize2,
} from 'lucide-react';
import classNames from 'classnames';
import type { FileNode } from '../types';
import { FileTypeIcon } from './icons';
import s from '../skillhub.module.scss';

const MIN_PANEL_WIDTH = 240;
const MAX_PANEL_WIDTH = 720;
const DEFAULT_PANEL_WIDTH = 288;

interface Props {
  tree: FileNode[];
  hasFiles?: boolean;
  /** 文件树加载中 */
  loading?: boolean;
  collapsed?: boolean;
  fullscreen?: boolean;
  onPreview?: (node: FileNode) => void;
  onDownload?: (node: FileNode) => void;
  onDownloadDir?: (node: FileNode) => void;
  onCollapse?: () => void;
  onToggleFullscreen?: () => void;
}

function TreeNode({
  node,
  depth,
  onPreview,
  onDownload,
  onDownloadDir,
}: {
  node: FileNode;
  depth: number;
  onPreview?: (node: FileNode) => void;
  onDownload?: (node: FileNode) => void;
  onDownloadDir?: (node: FileNode) => void;
}) {
  const [open, setOpen] = useState(true);

  if (node.type === 'dir') {
    return (
      <div>
        <div
          className="group flex items-center gap-1.5 px-2 py-1.5 cursor-pointer hover:bg-gray-100 rounded-md"
          onClick={() => setOpen((v) => !v)}
        >
          <ChevronRight
            className={classNames(
              'text-gray-400 flex-shrink-0 transition-transform',
              depth === 0 ? 'w-3.5 h-3.5' : 'w-3 h-3',
              open && 'rotate-90',
            )}
          />
          <Folder
            className={classNames(
              'text-gray-500 flex-shrink-0',
              depth === 0 ? 'w-4 h-4' : 'w-3.5 h-3.5',
            )}
          />
          <span
            className={classNames(
              'text-gray-600 truncate',
              depth === 0 ? 'text-sm font-medium' : 'text-xs',
            )}
          >
            {node.name}
          </span>
          <button
            type="button"
            title="下载目录"
            className="p-1 text-gray-300 hover:text-[#0072ff] rounded opacity-0 group-hover:opacity-100 ml-auto flex-shrink-0"
            onClick={(e) => {
              e.stopPropagation();
              onDownloadDir?.(node);
            }}
          >
            <Download className="w-3 h-3" />
          </button>
        </div>
        {open && node.children && (
          <div className="pl-5 space-y-0.5">
            {node.children.map((child, i) => (
              <TreeNode key={i} node={child} depth={depth + 1} onPreview={onPreview} onDownload={onDownload} onDownloadDir={onDownloadDir} />
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className="group flex items-center gap-1.5 px-2 py-1.5 cursor-pointer hover:bg-gray-100 rounded-md"
      onClick={() => onPreview?.(node)}
    >
      <span className="w-6 h-6 rounded-md bg-gray-100 flex items-center justify-center flex-shrink-0">
        <FileTypeIcon name={node.name} className="text-sm" />
      </span>
      <span className="text-xs text-gray-700 truncate">{node.name}</span>
      <button
        type="button"
        title="下载"
        className="p-1 text-gray-300 hover:text-[#0072ff] rounded opacity-0 group-hover:opacity-100 ml-auto flex-shrink-0"
        onClick={(e) => {
          e.stopPropagation();
          onDownload?.(node);
        }}
      >
        <Download className="w-3 h-3" />
      </button>
    </div>
  );
}

/** 右侧文件树（outputs / workspace / uploads 三根目录，含空态 / 折叠 / 全屏） */
export default function FileTreePanel({
  tree,
  hasFiles = true,
  loading = false,
  collapsed = false,
  fullscreen = false,
  onPreview,
  onDownload,
  onDownloadDir,
  onCollapse,
  onToggleFullscreen,
}: Props) {
  const [width, setWidth] = useState(DEFAULT_PANEL_WIDTH);
  const [dragging, setDragging] = useState(false);

  const startDrag = (e: React.MouseEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(true);
    const startX = e.clientX;
    const startWidth = width;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    const onMove = (ev: MouseEvent) => {
      const next = Math.min(MAX_PANEL_WIDTH, Math.max(MIN_PANEL_WIDTH, startWidth + (startX - ev.clientX)));
      setWidth(next);
    };
    const onUp = () => {
      setDragging(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  if (collapsed) return null;

  return (
    <aside
      className={classNames(
        'border-l border-gray-200 bg-white flex-col flex-shrink-0 relative',
        fullscreen ? 'flex flex-1' : 'hidden xl:flex',
      )}
      style={fullscreen ? undefined : { width }}
    >
      {!fullscreen && (
        <div
          onMouseDown={startDrag}
          className={classNames(
            'absolute top-0 bottom-0 -left-0.5 w-1 cursor-col-resize transition-colors z-10',
            dragging ? 'bg-[#0072ff]' : 'hover:bg-[#0072ff]',
          )}
        />
      )}
      <div className="h-12 flex items-center justify-between px-5 bg-white flex-shrink-0">
        <div className="flex items-center gap-2">
          <FolderOpen className="w-4 h-4 text-gray-600" />
          <span className="text-sm font-semibold text-gray-900">文件</span>
        </div>
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            title={fullscreen ? '收缩' : '展开'}
            onClick={onToggleFullscreen}
            className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
          >
            {fullscreen ? (
              <Minimize2 className="w-4 h-4" />
            ) : (
              <Maximize2 className="w-4 h-4" />
            )}
          </button>
          <button
            type="button"
            title="折叠"
            onClick={onCollapse}
            className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <ChevronsRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex-1 flex flex-col items-center justify-center text-center px-6">
          <p className="text-xs text-gray-400">加载中…</p>
        </div>
      ) : hasFiles ? (
        <div className={`flex-1 overflow-y-auto px-3 py-2 space-y-1 ${s.skillhubScroll}`}>
          {tree.map((node, i) => (
            <TreeNode key={i} node={node} depth={0} onPreview={onPreview} onDownload={onDownload} onDownloadDir={onDownloadDir} />
          ))}
        </div>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center text-center px-6">
          <div className="w-12 h-12 rounded-full bg-gray-100 flex items-center justify-center mb-3">
            <Folder className="w-5 h-5 text-gray-300" />
          </div>
          <p className="text-xs text-gray-400">暂无文件</p>
          <p className="text-[11px] text-gray-300 mt-1">该会话未生成任何文件</p>
        </div>
      )}
    </aside>
  );
}
