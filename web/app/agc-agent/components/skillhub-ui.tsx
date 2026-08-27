'use client';

import { createContext, useContext, useState, type ReactNode } from 'react';

interface SkillhubUIState {
  /** 桌面端侧栏是否收起 */
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (v: boolean) => void;
  /** 移动端抽屉是否展开 */
  mobileOpen: boolean;
  setMobileOpen: (v: boolean) => void;
}

const SkillhubUIContext = createContext<SkillhubUIState | null>(null);

export function SkillhubUIProvider({ children }: { children: ReactNode }) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <SkillhubUIContext.Provider
      value={{ sidebarCollapsed, setSidebarCollapsed, mobileOpen, setMobileOpen }}
    >
      {children}
    </SkillhubUIContext.Provider>
  );
}

export function useSkillhubUI() {
  const ctx = useContext(SkillhubUIContext);
  if (!ctx) {
    throw new Error('useSkillhubUI 必须在 SkillhubUIProvider 内使用');
  }
  return ctx;
}
