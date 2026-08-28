'use client';

import { PanelLeftOpen } from 'lucide-react';
import { useSkillhubUI } from './skillhub-ui';

/** 移动端浮动侧栏开关：工作台 / 技能页无 header 页面复用，桌面端隐藏。
 *  视觉与 PageHeader 左侧图标一致（p-2 / rounded-md / hover:bg-gray-100 / w-4 h-4），
 *  top-2 left-2 对齐 header 图标距左上角 8px 的间距。 */
export default function MobileSidebarToggle() {
  const { setMobileOpen } = useSkillhubUI();

  return (
    <button
      type="button"
      aria-label="打开侧边栏"
      onClick={() => setMobileOpen(true)}
      className="fixed top-2 left-2 z-30 lg:hidden p-2 hover:bg-gray-100 rounded-md"
    >
      <PanelLeftOpen className="w-4 h-4 text-gray-600" />
    </button>
  );
}
