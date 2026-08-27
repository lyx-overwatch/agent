'use client';

import { X } from 'lucide-react';
import type { Skill } from '../types';
import { badgeOf, formatAuthor } from '../lib/skill';

interface Props {
  skill: Skill | null;
  onClose: () => void;
}

/** 技能详情弹窗（发布者 / 技能名 / 详细描述） */
export default function SkillDetailModal({ skill, onClose }: Props) {
  if (!skill) return null;

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="absolute inset-0 flex items-center justify-center p-4">
        <div className="w-full max-w-lg bg-white rounded-xl shadow-xl p-6">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-3 min-w-0">
              <div
                className={`w-10 h-10 rounded-lg flex items-center justify-center text-base font-bold shrink-0 ${badgeOf(skill.color)}`}
              >
                {skill.initial}
              </div>
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-gray-900 truncate">
                  {skill.displayName}
                </h3>
                <div className="text-xs text-gray-400 mt-1">
                  发布者：<span>{formatAuthor(skill.author)}</span>
                </div>
              </div>
            </div>
            <button
              type="button"
              title="关闭"
              onClick={onClose}
              className="p-1 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors shrink-0"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="mt-5 pt-4 border-t border-gray-100">
            <div className="text-sm font-medium text-gray-900 mb-2">技能描述</div>
            <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-line">
              {skill.description}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
