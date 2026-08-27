// 图标统一映射：工具卡 lucide 图标 + 文件类型 FontAwesome 彩色图标（对齐 phase1 HTML）
import type { ComponentType } from 'react';
import { config } from '@fortawesome/fontawesome-svg-core';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faFile,
  faFileCode,
  faFileCsv,
  faFileExcel,
  faFileImage,
  faFileLines,
  faFilePdf,
  faFilePowerpoint,
  faFileWord,
  type IconDefinition,
} from '@fortawesome/free-solid-svg-icons';
import {
  BookOpen,
  Bot,
  FilePlus,
  FileText,
  Filter,
  Folder,
  Globe,
  Image,
  Link,
  Replace,
  Search,
  Terminal,
} from 'lucide-react';

// 关闭 FontAwesome 运行时自动注入 CSS：避免 SSR 后 icon 先按默认大尺寸渲染、水合后再缩小（FOUC）。
// 尺寸改由 FileTypeIcon 内联 height:1em 控制。
config.autoAddCss = false;

export type ToolIconKey =
  | 'file-text'
  | 'terminal'
  | 'folder'
  | 'filter'
  | 'search'
  | 'file-plus'
  | 'replace'
  | 'book-open'
  | 'globe'
  | 'link'
  | 'image'
  | 'bot';

const toolIconMap: Record<ToolIconKey, ComponentType<{ className?: string }>> = {
  'file-text': FileText,
  terminal: Terminal,
  folder: Folder,
  filter: Filter,
  search: Search,
  'file-plus': FilePlus,
  replace: Replace,
  'book-open': BookOpen,
  globe: Globe,
  link: Link,
  image: Image,
  bot: Bot,
};

/** 工具卡图标（lucide） */
export function ToolIcon({
  icon,
  className,
}: {
  icon: string;
  className?: string;
}) {
  const Cmp = toolIconMap[icon as ToolIconKey] ?? FileText;
  return <Cmp className={className} />;
}

/** 按文件名扩展名取 FontAwesome 彩色文件图标 */
export function fileTypeIconOf(
  name: string,
): { icon: IconDefinition; colorClass: string } {
  const ext = name.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'ppt':
    case 'pptx':
      return { icon: faFilePowerpoint, colorClass: 'text-orange-600' };
    case 'pdf':
      return { icon: faFilePdf, colorClass: 'text-red-600' };
    case 'xls':
    case 'xlsx':
      return { icon: faFileExcel, colorClass: 'text-green-600' };
    case 'doc':
    case 'docx':
      return { icon: faFileWord, colorClass: 'text-blue-600' };
    case 'png':
    case 'jpg':
    case 'jpeg':
    case 'gif':
    case 'webp':
      return { icon: faFileImage, colorClass: 'text-purple-500' };
    case 'csv':
      return { icon: faFileCsv, colorClass: 'text-green-600' };
    case 'md':
      return { icon: faFileLines, colorClass: 'text-gray-500' };
    case 'json':
      return { icon: faFileCode, colorClass: 'text-amber-500' };
    case 'py':
    case 'js':
    case 'ts':
    case 'tsx':
    case 'jsx':
      return { icon: faFileCode, colorClass: 'text-gray-500' };
    default:
      return { icon: faFile, colorClass: 'text-gray-500' };
  }
}

/** 文件类型彩色图标（FontAwesome） */
export function FileTypeIcon({
  name,
  className,
}: {
  name: string;
  className?: string;
}) {
  const { icon, colorClass } = fileTypeIconOf(name);
  return (
    <FontAwesomeIcon
      icon={icon}
      className={`${colorClass} ${className ?? ''}`}
      style={{ display: 'inline-block', height: '1em', verticalAlign: '-0.125em' }}
    />
  );
}
