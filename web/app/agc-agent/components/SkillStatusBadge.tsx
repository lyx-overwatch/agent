import type { SkillReviewStatus } from '../types';

const STATUS_TEXT: Record<SkillReviewStatus, string> = {
  draft: '草稿',
  pending: '待审核',
  approved: '已通过',
  rejected: '已拒绝',
};

// 配色对齐 phase2 设计稿（public/phase2/pages/market.html）
const STATUS_CLASS: Record<SkillReviewStatus, string> = {
  draft: 'bg-gray-100 text-gray-500',
  pending: 'bg-amber-50 text-amber-600',
  approved: 'bg-emerald-50 text-emerald-600',
  rejected: 'bg-red-50 text-red-600',
};

/** 技能状态角标（草稿 / 待审核 / 已通过 / 已拒绝） */
export default function SkillStatusBadge({ status }: { status: SkillReviewStatus }) {
  return (
    <span
      className={`shrink-0 px-2 py-0.5 rounded-full text-[11px] font-medium ${STATUS_CLASS[status]}`}
    >
      {STATUS_TEXT[status]}
    </span>
  );
}
