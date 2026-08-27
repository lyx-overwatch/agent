'use client';

import { Check, Info, Plus, Send, Trash2, X } from 'lucide-react';
import type { Skill } from '../types';
import { badgeOf, formatAuthor } from '../lib/skill';
import SkillStatusBadge from './SkillStatusBadge';
import s from '../skillhub.module.scss';

type Variant = 'marketplace' | 'mine' | 'added' | 'review' | 'builtin';

interface Props {
  skill: Skill;
  variant: Variant;
  /** 点击卡片（操作按钮除外）打开详情 */
  onClick?: (skill: Skill) => void;
  // 各变体操作回调
  onAdd?: (skill: Skill) => void;
  onRemove?: (skill: Skill) => void;
  onPublish?: (skill: Skill) => void;
  onDelete?: (skill: Skill) => void;
  onShowNote?: (skill: Skill) => void;
  onApprove?: (skill: Skill) => void;
  onReject?: (skill: Skill) => void;
}

const BTN =
  'shrink-0 p-1.5 rounded-lg text-gray-400 transition-colors';
const BTN_GRAY = `${BTN} hover:text-gray-900 hover:bg-gray-100`;
const BTN_RED = `${BTN} hover:text-red-600 hover:bg-red-50`;
const ICON = 'w-3.5 h-3.5';

/** 单个操作按钮（阻止冒泡，避免触发卡片详情） */
function ActionBtn({
  title,
  className,
  onClick,
  children,
}: {
  title: string;
  className: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={className}
    >
      {children}
    </button>
  );
}

/** 技能卡片：标题 + 描述（2 行截断）+ 头像/作者 + 状态角标，操作按钮随变体切换 */
export default function SkillCard({
  skill,
  variant,
  onClick,
  onAdd,
  onRemove,
  onPublish,
  onDelete,
  onShowNote,
  onApprove,
  onReject,
}: Props) {
  const renderActions = () => {
    switch (variant) {
      case 'marketplace':
        return skill.added ? (
          <ActionBtn
            title="移除"
            className={BTN_RED}
            onClick={() => onRemove?.(skill)}
          >
            <X className={ICON} />
          </ActionBtn>
        ) : (
          <ActionBtn
            title="添加"
            className={BTN_GRAY}
            onClick={() => onAdd?.(skill)}
          >
            <Plus className={ICON} />
          </ActionBtn>
        );
      case 'added':
        return (
          <ActionBtn
            title="移除"
            className={BTN_RED}
            onClick={() => onRemove?.(skill)}
          >
            <X className={ICON} />
          </ActionBtn>
        );
      case 'review':
        return (
          <div className="flex items-center gap-0.5 shrink-0">
            <ActionBtn
              title="通过"
              className={`${BTN} text-emerald-600 hover:bg-emerald-50`}
              onClick={() => onApprove?.(skill)}
            >
              <Check className={ICON} />
            </ActionBtn>
            <ActionBtn
              title="驳回"
              className={BTN_RED}
              onClick={() => onReject?.(skill)}
            >
              <X className={ICON} />
            </ActionBtn>
          </div>
        );
      case 'mine':
        return (
          <div className="flex items-center gap-0.5 shrink-0">
            {(skill.reviewStatus === 'draft' ||
              skill.reviewStatus === 'rejected') && (
              <ActionBtn
                title={skill.reviewStatus === 'draft' ? '发布' : '重新提交'}
                className={BTN_GRAY}
                onClick={() => onPublish?.(skill)}
              >
                <Send className={ICON} />
              </ActionBtn>
            )}
            <ActionBtn
              title="删除"
              className={BTN_RED}
              onClick={() => onDelete?.(skill)}
            >
              <Trash2 className={ICON} />
            </ActionBtn>
          </div>
        );
      case 'builtin':
      default:
        return null;
    }
  };

  const showStatus = variant === 'mine' || variant === 'review';

  return (
    <div
      onClick={() => onClick?.(skill)}
      className="px-4 py-3 bg-white rounded-xl border border-gray-200 hover:border-gray-300 hover:shadow-md transition-all duration-200 flex flex-col cursor-pointer"
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold text-sm text-gray-900 truncate min-w-0">
          {skill.displayName}
        </h3>
        {renderActions()}
      </div>

      <p className={`text-xs text-gray-500 mt-3 leading-relaxed min-h-[3.25em] ${s.lineClamp2}`}>
        {skill.description}
      </p>

      <div className="flex items-center justify-between gap-2 mt-4">
        <div className="flex items-center gap-2 min-w-0">
          <div
            className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${badgeOf(skill.color)}`}
          >
            {skill.initial}
          </div>
          <span className="text-xs text-gray-400 truncate">{formatAuthor(skill.author)}</span>
        </div>

        {showStatus && skill.reviewStatus && (
          <div className="flex items-center gap-1.5 shrink-0">
            <SkillStatusBadge status={skill.reviewStatus} />
            {variant === 'mine' &&
              skill.reviewStatus === 'rejected' &&
              skill.reviewNote && (
                <ActionBtn
                  title="查看驳回原因"
                  className={`${BTN} text-amber-500 hover:bg-amber-50`}
                  onClick={() => onShowNote?.(skill)}
                >
                  <Info className={ICON} />
                </ActionBtn>
              )}
          </div>
        )}
      </div>
    </div>
  );
}
