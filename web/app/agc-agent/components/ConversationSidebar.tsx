'use client';

import { useEffect, useRef, useState } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
  ChevronUp,
  LogOut,
  MessageCircle,
  PanelLeftClose,
  PanelLeftOpen,
  Sparkles,
  Trash2,
} from 'lucide-react';
import classNames from 'classnames';
import s from '../skillhub.module.scss';
import { useSkillhubChat } from './skillhub-chat';
import { useSkillhubUI } from './skillhub-ui';
import Modal from '@/components/base/modal';

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
  const { conversations, conversationsLoading, deleteConversation, user } =
    useSkillhubChat();
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);

  // 点击用户菜单外部时收起
  useEffect(() => {
    if (!userMenuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [userMenuOpen]);

  const displayName = user?.email || user?.username || '用户';

  const isNavActive = (href: string) =>
    href === '/agc-agent' ? pathname === '/agc-agent' : pathname.startsWith(href);
  const isConvActive = (id: string) => pathname === `/agc-agent/${id}`;

  const handleCollapse = () => {
    setMobileOpen(false);
    setUserMenuOpen(false);
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
          'fixed lg:static inset-y-0 left-0 z-50 w-60 bg-white border-r border-gray-200 flex flex-col transition-[width,transform] duration-200',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
          'lg:translate-x-0',
          sidebarCollapsed ? 'lg:w-[52px]' : 'lg:w-60',
        )}
      >
        {/* 顶部：展开态 Logo + 收起；折叠态仅展开按钮 */}
        <div
          className={classNames(
            'h-12 flex items-center justify-between px-4',
            sidebarCollapsed && 'lg:justify-center lg:px-2',
          )}
        >
          <Link
            href="/agc-agent"
            className={classNames(
              'flex items-center hover:opacity-80 transition-opacity',
              sidebarCollapsed && 'lg:hidden',
            )}
          >
            <svg
              width="24"
              height="24"
              viewBox="0 0 20 20"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              className="pointer-events-none text-gray-900 shrink-0"
            >
              <path
                d="M17.3481 3.19781C17.9163 3.19781 18.3774 3.65892 18.3774 4.22711V13.1714C18.3773 13.5007 18.2292 13.8127 17.9741 14.0211L14.9419 16.4966C14.7461 16.6564 14.5012 16.7436 14.2485 16.7437H2.73975C2.17168 16.7437 1.71066 16.2834 1.71045 15.7154V7.03864C1.71045 6.70834 1.85946 6.39546 2.11572 6.18707L5.48877 3.44391C5.6844 3.28484 5.92902 3.19785 6.18115 3.19781H17.3481ZM6.69971 5.25055C6.57403 5.25049 6.45172 5.2936 6.354 5.37262L3.98779 7.28668C3.85899 7.39084 3.78371 7.54779 3.78369 7.71344V14.3384C3.78369 14.5278 3.93804 14.6812 4.12744 14.6812H5.82568V11.1197C5.82568 10.8167 6.07147 10.5709 6.37451 10.5709H7.67725C7.98028 10.5709 8.22607 10.8167 8.22607 11.1197V14.6812H9.46045V11.1197C9.46045 10.8168 9.70638 10.571 10.0093 10.5709H11.313C11.6159 10.571 11.8618 10.8167 11.8618 11.1197V14.6812H13.7065C13.8327 14.6812 13.9554 14.6378 14.0532 14.5582L16.1167 12.8795C16.2447 12.7753 16.3197 12.6187 16.3198 12.4537V5.59821C16.3198 5.409 16.1662 5.25572 15.9771 5.25543L6.69971 5.25055Z"
                fill="currentColor"
              />
            </svg>
          </Link>
          <button
            type="button"
            title="收起侧边栏"
            onClick={handleCollapse}
            className={classNames(
              'p-2 -mr-2 flex items-center justify-center hover:bg-gray-100 rounded-md transition-colors',
              sidebarCollapsed && 'lg:hidden',
            )}
          >
            <PanelLeftClose className="w-4 h-4 text-gray-600" />
          </button>
          <button
            type="button"
            title="展开侧边栏"
            onClick={() => setSidebarCollapsed(false)}
            className={classNames(
              'hidden p-2 hover:bg-gray-100 rounded-md transition-colors',
              sidebarCollapsed && 'lg:inline-flex',
            )}
          >
            <PanelLeftOpen className="w-4 h-4 text-gray-600" />
          </button>
        </div>

        {/* 导航（折叠时仅图标居中） */}
        <nav className={classNames('px-3 py-3 space-y-1', sidebarCollapsed && 'lg:px-1')}>
          {NAV.map((item) => {
            const active = isNavActive(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                title={item.label}
                className={classNames(
                  'flex items-center rounded-md text-sm font-medium transition-colors',
                  sidebarCollapsed
                    ? 'lg:justify-center lg:px-0 py-2'
                    : 'gap-3 px-3 py-2',
                  active
                    ? 'bg-gray-100 text-gray-900'
                    : 'text-gray-600 hover:bg-gray-50',
                )}
              >
                <Icon className="w-4 h-4 shrink-0" />
                <span className={classNames(sidebarCollapsed && 'lg:hidden')}>
                  {item.label}
                </span>
              </Link>
            );
          })}
        </nav>

        {/* 会话列表（折叠时隐藏） */}
        <div
          className={classNames(
            'flex-1 overflow-y-auto px-3 py-2 space-y-1',
            s.skillhubScroll,
            sidebarCollapsed && 'lg:hidden',
          )}
        >
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

        {/* 底部用户信息（折叠时仅头像，点击展开侧栏） */}
        <div ref={userMenuRef} className="relative border-t border-gray-200 mt-auto">
          {userMenuOpen && !sidebarCollapsed && (
            <div className="absolute bottom-full left-2 right-2 mb-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-10">
              <button
                type="button"
                onClick={() => {
                  setUserMenuOpen(false);
                  handleLogout();
                }}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors"
              >
                <LogOut className="w-4 h-4" />
                退出登录
              </button>
            </div>
          )}
          <button
            type="button"
            onClick={() => {
              if (sidebarCollapsed) {
                setSidebarCollapsed(false);
              } else {
                setUserMenuOpen((v) => !v);
              }
            }}
            className={classNames(
              'w-full flex items-center hover:bg-gray-50 transition-colors',
              sidebarCollapsed ? 'lg:justify-center lg:px-0 py-3' : 'gap-3 px-4 py-3',
            )}
          >
            <Image
              src="/avator.png"
              alt="用户头像"
              width={32}
              height={32}
              className="rounded-full shrink-0"
            />
            <span className={classNames('flex-1 min-w-0 text-left', sidebarCollapsed && 'lg:hidden')}>
              <span className="block text-sm text-gray-900 truncate">{displayName}</span>
            </span>
            <ChevronUp
              className={classNames(
                'w-4 h-4 text-gray-400 shrink-0',
                sidebarCollapsed && 'lg:hidden',
              )}
            />
          </button>
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
