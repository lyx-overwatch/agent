'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
  LogOut,
  MessageCircle,
  PanelLeftClose,
  Sparkles,
  Trash2,
} from 'lucide-react';
import classNames from 'classnames';
import s from '../skillhub.module.scss';
import { useSkillhubChat } from './skillhub-chat';
import { useSkillhubUI } from './skillhub-ui';
import Modal from '@/app/components/base/modal';

const NAV = [
  { href: '/agc-agent', label: '工作台', icon: MessageCircle },
  { href: '/agc-agent/skills', label: '技能', icon: Sparkles },
];

/** 会话侧栏：Logo + 收起 + 导航 + 会话列表（状态点 / hover 删除 / 空态） */
export default function ConversationSidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { sidebarCollapsed, setSidebarCollapsed, mobileOpen, setMobileOpen } =
    useSkillhubUI();
  const { conversations, conversationsLoading, deleteConversation } =
    useSkillhubChat();
  const [deleteId, setDeleteId] = useState<string | null>(null);

  const isNavActive = (href: string) =>
    href === '/agc-agent' ? pathname === '/agc-agent' : pathname.startsWith(href);
  const isConvActive = (id: string) => pathname === `/agc-agent/${id}`;

  const handleCollapse = () => {
    setMobileOpen(false);
    setSidebarCollapsed(true);
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    router.replace('/');
  };

  const handleDelete = (id: string) => {
    setDeleteId(id);
  };

  const confirmDelete = async () => {
    if (!deleteId) return;
    const id = deleteId;
    const isCurrent = pathname === `/agc-agent/${id}`;
    setDeleteId(null);
    // 后端删成功才跳走；失败则留在原页（本地会话未被移除）
    const ok = await deleteConversation(id);
    if (ok && isCurrent) router.push('/agc-agent');
  };

  return (
    <>
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside
        className={classNames(
          'fixed lg:static inset-y-0 left-0 z-50 w-60 bg-white border-r border-gray-200 flex flex-col transition-transform duration-200',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
          'lg:translate-x-0',
          sidebarCollapsed && 'lg:hidden',
        )}
      >
        {/* Logo + 退出 + 收起 */}
        <div className="h-12 flex items-center justify-between px-4">
          <Link
            href="/"
            className="flex items-center hover:opacity-80 transition-opacity"
          >
            <span className="text-base font-bold text-gray-900">Heyu Agent</span>
          </Link>
          <div className="flex items-center">
            <button
              type="button"
              title="退出登录"
              onClick={handleLogout}
              className="p-2 hover:bg-gray-100 rounded-md transition-colors"
            >
              <LogOut className="w-4 h-4 text-gray-600" />
            </button>
            <button
              type="button"
              title="收起侧边栏"
              onClick={handleCollapse}
              className="p-2 -mr-2 hover:bg-gray-100 rounded-md transition-colors"
            >
              <PanelLeftClose className="w-4 h-4 text-gray-600" />
            </button>
          </div>
        </div>

        {/* 导航 */}
        <nav className="px-3 py-3 space-y-1">
          {NAV.map((item) => {
            const active = isNavActive(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={classNames(
                  'flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors',
                  active
                    ? 'bg-gray-100 text-gray-900'
                    : 'text-gray-600 hover:bg-gray-50',
                )}
              >
                <Icon className="w-4 h-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* 会话列表 */}
        <div className={`flex-1 overflow-y-auto px-3 py-2 space-y-1 ${s.skillhubScroll}`}>
          <div className="text-xs text-gray-400 mb-2 px-3">最近会话</div>
          {conversations.map((c) => {
            const active = isConvActive(c.id);
            return (
              <Link
                key={c.id}
                href={`/agc-agent/${c.id}`}
                className={classNames(
                  'group flex items-center gap-2.5 px-3 py-1.5 rounded-lg transition-colors',
                  active ? 'bg-gray-100' : 'hover:bg-gray-50',
                )}
              >
                <span
                  className={classNames(
                    'flex-1 min-w-0 text-sm truncate',
                    active ? 'text-gray-900' : 'text-gray-700',
                  )}
                >
                  {c.title}
                </span>
                {c.status === 'running' && <span className={s.convPulseDot} />}
                <button
                  type="button"
                  title="删除会话"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    handleDelete(c.id);
                  }}
                  className="p-1 text-gray-400 hover:text-red-500 rounded opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </Link>
            );
          })}
          {conversationsLoading ? (
            <p className="px-3 py-2 text-xs text-gray-400">加载中…</p>
          ) : (
            conversations.length === 0 && (
              <p className="px-3 py-2 text-xs text-gray-400">暂无会话</p>
            )
          )}
        </div>
      </aside>

      <Modal
        title="删除该会话？"
        isShow={deleteId !== null}
        onClose={() => setDeleteId(null)}
        closable
      >
        <div className="pt-4">
          <div className="flex justify-between mt-4">
            <div
              onClick={() => setDeleteId(null)}
              className="cursor-pointer px-4 h-8 leading-8 border border-[#ecedef] text-[#17181e] hover:bg-[#ecedef] rounded-md"
            >
              取消
            </div>
            <div
              onClick={confirmDelete}
              className="cursor-pointer px-4 h-8 leading-8 text-white bg-[#f1010a] hover:bg-[#b02d31] rounded-md"
            >
              确定
            </div>
          </div>
        </div>
      </Modal>
    </>
  );
}
