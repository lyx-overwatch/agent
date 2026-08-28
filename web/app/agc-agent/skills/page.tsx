'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { Plus, Upload } from 'lucide-react';
import { AlertError } from '../lib/alert';
import Modal from '@/components/base/modal';
import {
  skillhubApi,
  type ApiBuiltinSkillItem,
  type ApiSkillItem,
} from '../api/skillhub';
import { useSkillhubChat } from '../components/skillhub-chat';
import SkillCard from '../components/SkillCard';
import UploadSkillModal from '../components/UploadSkillModal';
import SkillDetailModal from '../components/SkillDetailModal';
import RejectSkillModal from '../components/RejectSkillModal';
import MobileSidebarToggle from '../components/MobileSidebarToggle';
import { hashColor, initialOf } from '../lib/skill';
import type { Skill, SkillReviewStatus } from '../types';
import s from '../skillhub.module.scss';

type Tab = 'market' | 'mine' | 'review';

/** 二次确认弹窗的目标操作（移除 / 删除） */
type ConfirmAction = { kind: 'remove' | 'delete'; skill: Skill } | null;

const CREATE_PROMPT =
  '帮我创建一个新技能。请先询问我想实现的功能和使用场景，再按 SKILL.md 规范帮我生成技能定义。';

/** 系统内置的技能创建 skill：点击「创建」时连同提示词一起 @ 指定 */
const SKILL_CREATOR = 'skill-creator';

/** /mine、/marketplace、/pending 条目 → 领域 Skill（own：我的创建，作者显示「我」） */
function mapSkillItem(api: ApiSkillItem, own = false): Skill {
  const displayName = api.display_name || api.name;
  return {
    id: api.name,
    name: api.name,
    displayName,
    description: api.description,
    author: own ? '我' : api.author_name || 'Heyu Agent',
    color: hashColor(api.name),
    initial: initialOf(displayName),
    reviewStatus: (api.review_status as SkillReviewStatus) ?? null,
    reviewNote: api.review_note,
    version: api.version,
    added: api.added,
  };
}

/** /builtin 条目 → 领域 Skill */
function mapBuiltin(api: ApiBuiltinSkillItem): Skill {
  return {
    id: api.name,
    name: api.name,
    displayName: api.name,
    description: api.description,
    author: '内置',
    color: hashColor(api.name),
    initial: initialOf(api.name),
    reviewStatus: null,
  };
}

/** 网格容器：空态统一为「暂无技能」 */
function Grid({ empty, children }: { empty: boolean; children: React.ReactNode }) {
  if (empty) {
    return <p className="text-xs text-gray-400 py-8 text-center">暂无技能</p>;
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {children}
    </div>
  );
}

/** 技能页（phase2：市场 / 个人 / 审核 三 tab） */
export default function SkillsPage() {
  const router = useRouter();
  const { role } = useSkillhubChat();
  const isAdmin = role === 'admin';

  const [tab, setTab] = useState<Tab>('market');

  const [marketplace, setMarketplace] = useState<Skill[]>([]);
  const [mine, setMine] = useState<Skill[]>([]);
  const [builtin, setBuiltin] = useState<Skill[]>([]);
  const [pending, setPending] = useState<Skill[]>([]);

  const [marketLoading, setMarketLoading] = useState(true);
  const [marketError, setMarketError] = useState(false);
  const [mineLoading, setMineLoading] = useState(true);
  const [mineError, setMineError] = useState(false);
  const [pendingLoading, setPendingLoading] = useState(false);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [detailSkill, setDetailSkill] = useState<Skill | null>(null);
  const [rejectSkill, setRejectSkill] = useState<Skill | null>(null);
  const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null);
  const [confirmSubmitting, setConfirmSubmitting] = useState(false);
  const [noteSkill, setNoteSkill] = useState<Skill | null>(null);

  const loadMarketplace = useCallback(async () => {
    setMarketLoading(true);
    setMarketError(false);
    try {
      const list = await skillhubApi.getMarketplace();
      setMarketplace(list.map((i) => mapSkillItem(i)));
    } catch (e) {
      console.warn('[skillhub] getMarketplace failed', e);
      setMarketError(true);
      AlertError('加载市场失败');
    } finally {
      setMarketLoading(false);
    }
  }, []);

  const loadMine = useCallback(async () => {
    setMineLoading(true);
    setMineError(false);
    try {
      const [mineList, builtinList] = await Promise.all([
        skillhubApi.getMine(),
        skillhubApi.getBuiltin(),
      ]);
      setMine(mineList.map((i) => mapSkillItem(i, true)));
      setBuiltin(builtinList.map(mapBuiltin));
    } catch (e) {
      console.warn('[skillhub] load mine failed', e);
      setMineError(true);
      AlertError('加载个人失败');
    } finally {
      setMineLoading(false);
    }
  }, []);

  const loadPending = useCallback(async () => {
    setPendingLoading(true);
    try {
      const list = await skillhubApi.getPending();
      setPending(list.map((i) => mapSkillItem(i)));
    } catch (e) {
      // 非管理员 403 等：审核 tab 仅 admin 可见，静默忽略
      console.warn('[skillhub] getPending failed', e);
    } finally {
      setPendingLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMarketplace();
    loadMine();
  }, [loadMarketplace, loadMine]);

  useEffect(() => {
    if (isAdmin) loadPending();
  }, [isAdmin, loadPending]);

  // 切换 tab 时重新拉取对应数据，保证发布/审核等操作后切 tab 能拿到最新
  const handleTabChange = (next: Tab) => {
    if (next === tab) return;
    setTab(next);
    if (next === 'market') loadMarketplace();
    else if (next === 'mine') loadMine();
    else if (next === 'review') loadPending();
  };

  // ── 操作 ──────────────────────────────────────────────
  const handleAdd = async (skill: Skill) => {
    try {
      await skillhubApi.addSkill(skill.name);
      toast.success('已添加');
      loadMarketplace();
    } catch (e) {
      console.warn('[skillhub] addSkill failed', e);
      AlertError('添加失败');
    }
  };

  const handleRemove = (skill: Skill) => {
    setConfirmAction({ kind: 'remove', skill });
  };

  const handlePublish = async (skill: Skill) => {
    try {
      await skillhubApi.publishSkill(skill.name);
      toast.success('已提交审核');
      loadMine();
    } catch (e) {
      console.warn('[skillhub] publishSkill failed', e);
      AlertError('发布失败');
    }
  };

  const handleDelete = (skill: Skill) => {
    setConfirmAction({ kind: 'delete', skill });
  };

  const closeConfirm = () => {
    if (confirmSubmitting) return;
    setConfirmAction(null);
  };

  const handleConfirmAction = async () => {
    if (!confirmAction || confirmSubmitting) return;
    setConfirmSubmitting(true);
    try {
      if (confirmAction.kind === 'remove') {
        await skillhubApi.removeAddedSkill(confirmAction.skill.name);
        toast.success('已移除');
        loadMarketplace();
      } else {
        await skillhubApi.deleteSkill(confirmAction.skill.name);
        toast.success('已删除');
        loadMine();
        loadMarketplace();
      }
      setConfirmAction(null);
    } catch (e) {
      console.warn('[skillhub] confirm action failed', e);
      AlertError(confirmAction.kind === 'remove' ? '移除失败' : '删除失败');
    } finally {
      setConfirmSubmitting(false);
    }
  };

  const handleShowNote = (skill: Skill) => {
    setNoteSkill(skill);
  };

  const handleApprove = async (skill: Skill) => {
    try {
      await skillhubApi.reviewSkill(skill.name, 'approve');
      toast.success('已通过');
      loadPending();
      loadMarketplace();
    } catch (e) {
      console.warn('[skillhub] review approve failed', e);
      AlertError('操作失败');
    }
  };

  const handleRejectSubmit = async (reason: string) => {
    if (!rejectSkill) return;
    await skillhubApi.reviewSkill(rejectSkill.name, 'reject', reason);
    toast.success('已驳回');
    loadPending();
  };

  const handleUpload = async (
    file: File,
    displayName: string,
    description: string,
  ) => {
    const res = await skillhubApi.uploadSkill(
      file,
      displayName || undefined,
      description || undefined,
    );
    toast.success(`已上传「${res.display_name}」为草稿，可到「个人」发布`);
    loadMine();
  };

  const handleCreate = () => {
    router.push(
      `/agc-agent?prompt=${encodeURIComponent(CREATE_PROMPT)}&skill=${SKILL_CREATOR}`,
    );
  };

  // 广场 + 我的添加共用 marketplace 数据（added 字段区分）
  const addedSkills = marketplace.filter((sk) => sk.added);

  const tabBtn = (active: boolean) =>
    `px-4 h-9 text-sm font-medium rounded-lg border transition-colors ${
      active
        ? 'text-white bg-gray-900 border-gray-900 hover:bg-gray-900'
        : 'border-gray-200 text-gray-900 bg-white hover:bg-gray-50'
    }`;

  return (
    <main className="flex-1 flex flex-col min-w-0 relative bg-white">
      <MobileSidebarToggle />
      <div className={`flex-1 overflow-y-auto ${s.skillhubScroll}`}>
        <div className="max-w-7xl mx-auto px-4 pt-2 pb-6 lg:pt-6">
          {/* Tab 栏 */}
          <div className="flex items-center gap-2 justify-center lg:justify-start">
            <button type="button" className={tabBtn(tab === 'market')} onClick={() => handleTabChange('market')}>
              市场
            </button>
            <button type="button" className={tabBtn(tab === 'mine')} onClick={() => handleTabChange('mine')}>
              个人
            </button>
            {isAdmin && (
              <button type="button" className={tabBtn(tab === 'review')} onClick={() => handleTabChange('review')}>
                审核
              </button>
            )}
          </div>

          {/* 市场 */}
          {tab === 'market' && (
            <div className="mt-5">
              {marketLoading && marketplace.length === 0 ? (
                <p className="text-xs text-gray-400 py-16 text-center">加载中…</p>
              ) : marketError ? (
                <div className="flex flex-col items-center justify-center text-center py-16 gap-3">
                  <p className="text-xs text-gray-400">市场加载失败</p>
                  <button
                    type="button"
                    onClick={loadMarketplace}
                    className="px-4 h-8 leading-8 text-sm border border-gray-200 text-gray-700 hover:bg-gray-50 rounded-md"
                  >
                    重试
                  </button>
                </div>
              ) : (
                <Grid empty={marketplace.length === 0}>
                  {marketplace.map((sk) => (
                    <SkillCard
                      key={sk.id}
                      skill={sk}
                      variant="marketplace"
                      onClick={setDetailSkill}
                      onAdd={handleAdd}
                      onRemove={handleRemove}
                    />
                  ))}
                </Grid>
              )}
            </div>
          )}

          {/* 个人 */}
          {tab === 'mine' && (
            <div className="mt-5">
              {/* 我的创建 */}
              <div className="flex items-center justify-between mt-2 mb-4">
                <span className="text-sm font-semibold text-gray-900">我的创建</span>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={handleCreate}
                    className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium hover:bg-gray-800 transition-colors"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    创建
                  </button>
                  <button
                    type="button"
                    onClick={() => setUploadOpen(true)}
                    className="h-8 px-3 inline-flex items-center gap-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium hover:bg-gray-800 transition-colors"
                  >
                    <Upload className="w-3.5 h-3.5" />
                    上传
                  </button>
                </div>
              </div>

              {mineLoading && mine.length === 0 && builtin.length === 0 ? (
                <p className="text-xs text-gray-400 py-8 text-center">加载中…</p>
              ) : mineError ? (
                <div className="flex flex-col items-center justify-center text-center py-8 gap-3">
                  <p className="text-xs text-gray-400">个人加载失败</p>
                  <button
                    type="button"
                    onClick={loadMine}
                    className="px-4 h-8 leading-8 text-sm border border-gray-200 text-gray-700 hover:bg-gray-50 rounded-md"
                  >
                    重试
                  </button>
                </div>
              ) : (
                <Grid empty={mine.length === 0}>
                  {mine.map((sk) => (
                    <SkillCard
                      key={sk.id}
                      skill={sk}
                      variant="mine"
                      onClick={setDetailSkill}
                      onPublish={handlePublish}
                      onDelete={handleDelete}
                      onShowNote={handleShowNote}
                    />
                  ))}
                </Grid>
              )}

              {/* 我的添加 */}
              <div className="flex items-center gap-2 mt-8 mb-4">
                <span className="text-sm font-semibold text-gray-900">我的添加</span>
              </div>
              <Grid empty={addedSkills.length === 0}>
                {addedSkills.map((sk) => (
                  <SkillCard
                    key={sk.id}
                    skill={sk}
                    variant="added"
                    onClick={setDetailSkill}
                    onRemove={handleRemove}
                  />
                ))}
              </Grid>

              {/* 官方内置 */}
              <div className="flex items-center gap-2 mt-8 mb-4">
                <span className="text-sm font-semibold text-gray-900">官方内置</span>
              </div>
              <Grid empty={builtin.length === 0}>
                {builtin.map((sk) => (
                  <SkillCard
                    key={sk.id}
                    skill={sk}
                    variant="builtin"
                    onClick={setDetailSkill}
                  />
                ))}
              </Grid>
            </div>
          )}

          {/* 审核 */}
          {tab === 'review' && (
            <div className="mt-5">
              {pendingLoading && pending.length === 0 ? (
                <p className="text-xs text-gray-400 py-16 text-center">加载中…</p>
              ) : (
                <Grid empty={pending.length === 0}>
                  {pending.map((sk) => (
                    <SkillCard
                      key={sk.id}
                      skill={sk}
                      variant="review"
                      onClick={setDetailSkill}
                      onApprove={handleApprove}
                      onReject={setRejectSkill}
                    />
                  ))}
                </Grid>
              )}
            </div>
          )}
        </div>
      </div>

      <UploadSkillModal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUpload={handleUpload}
      />
      <SkillDetailModal skill={detailSkill} onClose={() => setDetailSkill(null)} />
      <Modal
        title={confirmAction?.kind === 'remove' ? '移除' : '删除技能'}
        isShow={!!confirmAction}
        onClose={closeConfirm}
        closable
      >
        <div className="pt-4">
          {confirmAction?.kind === 'remove' ? (
            <p className="text-sm text-gray-500">确定要移除该技能吗？</p>
          ) : (
            <div className="text-sm text-gray-500">
              <p>技能文件将从存储中永久删除，且不可恢复。</p>
              <p className="mt-2">已发布技能也会被删除，所有用户将无法使用。</p>
            </div>
          )}
          <div className="flex justify-between mt-4">
            <div
              onClick={closeConfirm}
              className="cursor-pointer px-4 h-8 leading-8 border border-[#ecedef] text-[#17181e] hover:bg-[#ecedef] rounded-md"
            >
              取消
            </div>
            <div
              onClick={handleConfirmAction}
              className="cursor-pointer px-4 h-8 leading-8 text-white bg-[#f1010a] hover:bg-[#b02d31] rounded-md"
            >
              确定
            </div>
          </div>
        </div>
      </Modal>

      <Modal
        title="驳回原因"
        isShow={!!noteSkill}
        onClose={() => setNoteSkill(null)}
        closable
      >
        <div className="pt-4">
          <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-line">
            {noteSkill?.reviewNote || '无'}
          </p>
          <div className="flex justify-end mt-4">
            <div
              onClick={() => setNoteSkill(null)}
              className="cursor-pointer px-4 h-8 leading-8 border border-[#ecedef] text-[#17181e] hover:bg-[#ecedef] rounded-md"
            >
              关闭
            </div>
          </div>
        </div>
      </Modal>
      <RejectSkillModal
        skill={rejectSkill}
        onClose={() => setRejectSkill(null)}
        onSubmit={handleRejectSubmit}
      />
    </main>
  );
}
