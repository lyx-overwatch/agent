'use client';

import type { ReactNode } from 'react';
import ConversationSidebar from './components/ConversationSidebar';
import { SkillhubChatProvider } from './components/skillhub-chat';
import { SkillhubUIProvider } from './components/skillhub-ui';

/** SkillHub 模块布局：共享侧栏 + 右侧内容（页面自渲染 main / 文件树） */
export default function SkillhubLayout({ children }: { children: ReactNode }) {
  return (
    <SkillhubUIProvider>
      <SkillhubChatProvider>
        <div className="flex h-full w-full overflow-hidden bg-white">
          <ConversationSidebar />
          {children}
        </div>
      </SkillhubChatProvider>
    </SkillhubUIProvider>
  );
}
