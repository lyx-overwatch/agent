'use client';

import type { ReactNode } from 'react';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import ConversationSidebar from './components/ConversationSidebar';
import { SkillhubChatProvider } from './components/skillhub-chat';
import { SkillhubUIProvider } from './components/skillhub-ui';

/** 工作台布局：共享侧栏 + 右侧内容（登录/注册页在根路由 /，由根 page 渲染） */
export default function SkillhubLayout({ children }: { children: ReactNode }) {
  const router = useRouter();

  // 客户端最小守卫：无 token 则跳登录页（根路由）
  useEffect(() => {
    if (!localStorage.getItem('token')) router.replace('/');
  }, [router]);

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
