'use client';

import type { ReactNode } from 'react';
import { Menu, PanelLeftOpen } from 'lucide-react';
import { useSkillhubUI } from './skillhub-ui';

interface Props {
  title: string;
  /** 标题栏右侧内容（token meta / 文件树开关等） */
  right?: ReactNode;
}

/** 顶部标题栏（桌面：展开侧栏按钮 + 标题 + 右侧槽；移动：菜单 + 标题） */
export default function PageHeader({ title, right }: Props) {
  const { sidebarCollapsed, setSidebarCollapsed, setMobileOpen } =
    useSkillhubUI();

  return (
    <>
      {/* 桌面端 */}
      <div className="hidden lg:flex h-14 items-center justify-between px-6 bg-white flex-shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          {sidebarCollapsed && (
            <button
              type="button"
              title="展开侧边栏"
              onClick={() => setSidebarCollapsed(false)}
              className="p-2 -ml-2 hover:bg-gray-100 rounded-md flex-shrink-0"
            >
              <PanelLeftOpen className="w-4 h-4 text-gray-600" />
            </button>
          )}
          <h1 className="text-base font-semibold text-gray-900 truncate">
            {title}
          </h1>
        </div>
        {right}
      </div>

      {/* 移动端 */}
      <div className="lg:hidden h-12 flex items-center px-4 border-b border-gray-200 bg-white flex-shrink-0">
        <button
          type="button"
          onClick={() => setMobileOpen(true)}
          className="p-2 -ml-2 hover:bg-gray-100 rounded-md"
        >
          <Menu className="w-4 h-4 text-gray-600" />
        </button>
        <span className="ml-2 font-semibold text-sm text-gray-900 truncate">
          {title}
        </span>
      </div>
    </>
  );
}
