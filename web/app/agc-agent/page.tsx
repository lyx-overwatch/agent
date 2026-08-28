'use client';

import { Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import InputArea from './components/InputArea';
import MobileSidebarToggle from './components/MobileSidebarToggle';
import { useSkillhubChat } from './components/skillhub-chat';

/** 工作台（默认欢迎页，无「新对话」按钮；发消息即新建会话并跳转详情页） */
export default function SkillhubPage() {
  return (
    <Suspense fallback={null}>
      <SkillhubPageInner />
    </Suspense>
  );
}

function SkillhubPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { models } = useSkillhubChat();
  // 技能页「创建」跳转带入的预填提示词 + @ 指定技能
  const initialText = searchParams.get('prompt') ?? undefined;
  const initialSkillName = searchParams.get('skill') ?? undefined;

  return (
    <main className="flex-1 flex flex-col min-w-0 relative bg-white">
      <MobileSidebarToggle />
      <div className="absolute inset-0 flex items-center justify-center px-4">
        <div className="relative w-full max-w-2xl">
          <h1 className="absolute bottom-full left-0 right-0 mb-10 text-center text-2xl font-bold text-gray-900">
            Heyu Agent，让工作更简单
          </h1>
          <InputArea
            models={models}
            placeholder="今天和agent聊点什么，@ 指定技能"
            initialText={initialText}
            initialSkillName={initialSkillName}
            onAfterSend={(id) => router.push(`/agc-agent/${id}`)}
          />
        </div>
      </div>
    </main>
  );
}
