'use client';

import { useEffect, useState } from 'react';
import { message } from 'antd';
import Modal from '@/app/components/base/modal';
import SkillTextArea from './SkillTextArea';
import type { Skill } from '../types';

interface Props {
  skill: Skill | null;
  onClose: () => void;
  /** 提交驳回原因（作者可见） */
  onSubmit: (reason: string) => Promise<void>;
}

/** 驳回原因弹窗（项目封装 Modal + antd 输入框） */
export default function RejectSkillModal({ skill, onClose, onSubmit }: Props) {
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (skill) setReason('');
  }, [skill]);

  const handleSubmit = async () => {
    const r = reason.trim();
    if (!r) {
      message.warning('驳回原因不能为空');
      return;
    }
    setSubmitting(true);
    try {
      await onSubmit(r);
      onClose();
    } catch (e) {
      console.warn('[skillhub] reviewSkill reject failed', e);
      message.error('驳回失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal title="驳回技能" isShow={!!skill} onClose={onClose} closable>
      <div className="pt-4">
        <p className="text-sm text-gray-500">
          驳回「{skill?.displayName}」，原因将展示给作者：
        </p>
        <SkillTextArea
          value={reason}
          onChange={setReason}
          rows={4}
          maxLength={1000}
          showCount
          placeholder="请输入驳回原因"
          className="mt-3"
        />
        <div className="flex justify-end gap-2 mt-4">
          <div
            onClick={onClose}
            className="cursor-pointer px-4 h-8 leading-8 border border-[#ecedef] text-[#17181e] hover:bg-[#ecedef] rounded-md"
          >
            取消
          </div>
          <div
            onClick={handleSubmit}
            className={`cursor-pointer px-4 h-8 leading-8 text-white rounded-md ${
              submitting || !reason.trim()
                ? 'bg-[#f0a3a6] cursor-not-allowed'
                : 'bg-[#f1010a] hover:bg-[#b02d31]'
            }`}
          >
            {submitting ? '提交中…' : '驳回'}
          </div>
        </div>
      </div>
    </Modal>
  );
}
