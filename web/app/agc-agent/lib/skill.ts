// ⚠️ 占位文件（STUB）—— 明天从原项目拷贝真实源码后整体替换本文件。
// 以下为纯展示逻辑的最小可运行实现（语义易推断），真实配色/文案以原项目为准。

import type { SkillOrigin } from '../types';

const COLOR_KEYS = ['blue', 'pink', 'green', 'orange', 'purple', 'teal', 'indigo'] as const;

/** 技能名 → 头像底色语义名（稳定哈希） */
export function hashColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i += 1) {
    h = (h * 31 + name.charCodeAt(i)) >>> 0;
  }
  return COLOR_KEYS[h % COLOR_KEYS.length];
}

/** 技能展示名 → 头像缩写（取首字符，缺省回退 'S'） */
export function initialOf(name: string): string {
  const trimmed = name?.trim();
  if (!trimmed) return 'S';
  return trimmed[0].toUpperCase();
}

const BADGE_MAP: Record<string, string> = {
  blue: 'bg-blue-100 text-blue-700',
  pink: 'bg-pink-100 text-pink-700',
  green: 'bg-green-100 text-green-700',
  orange: 'bg-orange-100 text-orange-700',
  purple: 'bg-purple-100 text-purple-700',
  teal: 'bg-teal-100 text-teal-700',
  indigo: 'bg-indigo-100 text-indigo-700',
};

/** 头像底色语义名 → tailwind 样式类 */
export function badgeOf(color: string): string {
  return BADGE_MAP[color] ?? BADGE_MAP.blue;
}

/** 作者展示名（空值回退 SkillHub） */
export function formatAuthor(author: string): string {
  return author || 'SkillHub';
}

/** 技能来源 → 角标元数据（label + className） */
export function originMetaOf(
  origin: SkillOrigin | undefined,
): { label: string; className: string } {
  switch (origin) {
    case 'builtin':
      return { label: '内置', className: 'bg-gray-100 text-gray-600' };
    case 'mine':
      return { label: '我的', className: 'bg-blue-50 text-blue-600' };
    case 'added':
      return { label: '已添加', className: 'bg-green-50 text-green-600' };
    default:
      return { label: '未知', className: 'bg-gray-100 text-gray-500' };
  }
}
