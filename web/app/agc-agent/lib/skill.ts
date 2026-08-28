// 技能卡片展示辅助：头像配色 / 缩写 / 状态角标 / 来源标签（纯函数，供 SkillCard / SkillDetailModal / skills 页 / InputArea 复用）

import type { SkillOrigin } from '../types';

/** 技能来源标签：文案 + 角标配色（@ 菜单、技能列表等复用） */
export const SKILL_ORIGIN_META: Record<SkillOrigin, { label: string; className: string }> = {
  builtin: { label: '内置', className: 'bg-gray-100 text-gray-500' },
  mine: { label: '我的', className: 'bg-blue-50 text-blue-600' },
  added: { label: '已添加', className: 'bg-green-50 text-green-600' },
};

/** 取来源标签元信息（缺省回退「内置」） */
export function originMetaOf(origin?: SkillOrigin): { label: string; className: string } {
  return SKILL_ORIGIN_META[origin ?? 'builtin'];
}

export const COLOR_KEYS = [
  'blue',
  'pink',
  'green',
  'orange',
  'purple',
  'teal',
  'indigo',
] as const;

const COLOR_BADGE: Record<string, string> = {
  blue: 'bg-blue-100 text-blue-600',
  pink: 'bg-pink-100 text-pink-600',
  green: 'bg-green-100 text-green-600',
  orange: 'bg-orange-100 text-orange-600',
  purple: 'bg-purple-100 text-purple-600',
  teal: 'bg-teal-100 text-teal-600',
  indigo: 'bg-indigo-100 text-indigo-600',
};

/** 头像底色 class（按语义色名） */
export function badgeOf(color: string): string {
  return COLOR_BADGE[color] ?? COLOR_BADGE.blue;
}

/** 按技能名稳定哈希出一个语义色名 */
export function hashColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i += 1) {
    h = (h * 31 + name.charCodeAt(i)) >>> 0;
  }
  return COLOR_KEYS[h % COLOR_KEYS.length];
}

/** 头像缩写（取展示名首字符） */
export function initialOf(displayName: string): string {
  return (displayName.trim()[0] ?? 'S').toUpperCase();
}

/** 作者名展示：后端拿不到可读用户名，author_name 是 uid（长 hex），缩短为前 8 位避免卡片挤满一长串 */
export function formatAuthor(name: string): string {
  if (/^[0-9a-f-]{16,}$/i.test(name)) {
    return `${name.slice(0, 8)}…`;
  }
  return name;
}
