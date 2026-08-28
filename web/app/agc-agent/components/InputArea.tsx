'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertError } from '../lib/alert';
import { ArrowUp, Loader2, Paperclip, Square, X } from 'lucide-react';
import classNames from 'classnames';
import type { Attachment, Model } from '../types';
import { extToFileType } from '../api/mappers';
import { skillhubApi, type ApiAvailableSkillItem } from '../api/skillhub';
import { originMetaOf } from '../lib/skill';
import AttachmentChip from './AttachmentChip';
import ModelSelector from './ModelSelector';
import { useSkillhubChat } from './skillhub-chat';

// @ 关键词字符：英文/数字/下划线/连字符 + 中日韩汉字（U+4E00–U+9FFF），支持「@中文」匹配
const AT_QUERY_RE = /@([A-Za-z0-9_一-鿿-]*)$/;
// @ 前一个字符若为英文标识符（字母/数字/下划线/连字符）视为邮箱/标识符，不触发；中文等其余字符前可正常 @
const AT_EMAIL_RE = /[\w-]/;

interface Props {
  models: Model[];
  /** 继续该会话（缺省则新建会话） */
  conversationId?: string;
  placeholder?: string;
  /** 新建会话后回调（工作台用于跳转详情页） */
  onAfterSend?: (conversationId: string) => void;
  /** 初始预填文本（工作台「创建技能」跳转带入） */
  initialText?: string;
  /** 初始 @ 指定技能（工作台「创建技能」跳转带入，如 skill-creator） */
  initialSkillName?: string;
}

/** 输入区：附件 chips + 文本域 + 模型下拉 + 深度思考开关 + 发送/停止 */
export default function InputArea({ models, conversationId, placeholder, onAfterSend, initialText, initialSkillName }: Props) {
  const { streaming, sendMessage, stopGeneration, modelName, setModelName, thinking, setThinking } = useSkillhubChat();
  const [text, setText] = useState(initialText ?? '');
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  // @ 指定技能：已选技能 + 候选列表 + 下拉/过滤状态
  const [skillName, setSkillName] = useState<string | null>(initialSkillName ?? null);
  const [skills, setSkills] = useState<ApiAvailableSkillItem[]>([]);
  const [showSkillMenu, setShowSkillMenu] = useState(false);
  const [skillQuery, setSkillQuery] = useState('');
  const [highlightIndex, setHighlightIndex] = useState(0);
  // 发送中锁：sendMessage 卡住时（resolveConversation / SSE 迟迟不返回），
  // 防止持续 Enter 反复触发 sendMessage → 后端批量创建重复会话。
  // ref 用于同步判重（避免 state 闭包滞后导致连按穿透），state 用于按钮禁用态。
  const [sending, setSending] = useState(false);
  const sendingRef = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // @ 菜单里当前高亮项的 DOM 引用（键盘导航时用于自动滚动）
  const highlightedRef = useRef<HTMLButtonElement | null>(null);

  // 仅当前会话在流式时展示停止按钮：工作台（无 conversationId）永不展示停止，
  // 详情页只在流式会话等于本页会话时展示，避免回到工作台仍残留停止按钮。
  const isStreaming = !!conversationId && streaming?.conversationId === conversationId;
  const currentModel = models.find((m) => m.name === modelName);
  const thinkingLocked = !!currentModel?.locked;
  const hasContent = text.trim().length > 0 || attachments.length > 0;

  // 懒加载技能列表（仅用于 @ 菜单），失败静默：菜单不展示即可
  useEffect(() => {
    let cancelled = false;
    skillhubApi
      .getAvailable()
      .then((list) => {
        if (!cancelled) setSkills(Array.isArray(list) ? list : []);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // 键盘移动高亮时，让高亮项自动滚入可见区域（block:'nearest' 已可见则不动）
  useEffect(() => {
    highlightedRef.current?.scrollIntoView({ block: 'nearest' });
  }, [highlightIndex]);

  // 匹配优先级：名称前缀 > 名称/展示名包含 > 描述包含。这样「@UI」会优先命中名称相关技能，
  // 而描述里恰好含关键词的技能（如描述里带「UI」的 mcp）只作为兜底排到后面，不再突兀置顶。
  const filteredSkills = useMemo(() => {
    if (!skillQuery) return skills;
    const q = skillQuery.toLowerCase();
    const rank = (s: ApiAvailableSkillItem): number => {
      const name = s.name.toLowerCase();
      const display = (s.display_name ?? '').toLowerCase();
      if (name.startsWith(q) || display.startsWith(q)) return 0;
      if (name.includes(q) || display.includes(q)) return 1;
      if (s.description.toLowerCase().includes(q)) return 2;
      return 3;
    };
    return skills
      .map((s) => ({ s, r: rank(s) }))
      .filter((x) => x.r < 3)
      .sort((a, b) => a.r - b.r)
      .map((x) => x.s);
  }, [skills, skillQuery]);

  const resize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  };

  // 挂载时若带初始预填文本，调整一次 textarea 高度
  useEffect(() => {
    resize();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleModelChange = (name: string) => {
    setModelName(name);
    const m = models.find((x) => x.name === name);
    if (m?.locked) setThinking(true);
  };

  /** 选中某个技能：写入 skillName，并删掉 textarea 里正在输入的「@关键词」 */
  const pickSkill = (name: string | undefined) => {
    if (!name) return;
    setSkillName(name);
    setShowSkillMenu(false);
    setSkillQuery('');
    const el = textareaRef.current;
    const cursor = el?.selectionStart ?? text.length;
    const before = text.slice(0, cursor).replace(AT_QUERY_RE, '');
    const after = text.slice(cursor);
    setText(before + after);
    requestAnimationFrame(() => {
      if (el) {
        el.focus();
        el.setSelectionRange(before.length, before.length);
      }
      resize();
    });
  };

  const handleToggleStream = async () => {
    if (isStreaming) {
      stopGeneration();
      return;
    }
    if (sendingRef.current) return;
    if (!hasContent) return;
    sendingRef.current = true;
    setSending(true);
    try {
      const id = await sendMessage({
        conversationId,
        text: text.trim(),
        attachments,
        modelName,
        skillName: skillName ?? undefined,
        thinkingEnabled: thinking,
      });
      setText('');
      setAttachments([]);
      setSkillName(null);
      requestAnimationFrame(resize);
      onAfterSend?.(id);
    } catch (e) {
      console.warn('[skillhub] sendMessage failed', e);
      AlertError('发送失败，请重试');
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // @ 菜单打开时，方向键/回车/Esc 优先交给菜单
    if (showSkillMenu && filteredSkills.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setHighlightIndex((i) => (i + 1) % filteredSkills.length);
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setHighlightIndex((i) => (i - 1 + filteredSkills.length) % filteredSkills.length);
        return;
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        pickSkill(filteredSkills[highlightIndex]?.name);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setShowSkillMenu(false);
        return;
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleToggleStream();
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (files.length === 0) return;
    setAttachments((prev) => [
      ...prev,
      ...files.map((f, i) => ({
        id: `att-${Date.now()}-${i}`,
        name: f.name,
        fileType: extToFileType(f.name.split('.').pop() ?? ''),
        file: f,
      })),
    ]);
    e.target.value = '';
  };

  const removeAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  return (
    <div className="relative rounded-2xl border border-gray-200 bg-white transition-all focus-within:border-gray-300 focus-within:shadow-[0_4px_24px_rgba(0,0,0,0.06)]">
      {(attachments.length > 0 || skillName) && (
        <div className="flex flex-wrap items-center gap-1.5 px-4 pt-3">
          {attachments.map((a) => (
            <AttachmentChip key={a.id} attachment={a} onRemove={removeAttachment} />
          ))}
          {skillName && (
            <span className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-blue-50 text-blue-600 text-xs font-medium">
              @{skillName}
              <button
                type="button"
                onClick={() => setSkillName(null)}
                aria-label="移除技能"
                className="text-blue-400 hover:text-blue-600"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          )}
        </div>
      )}

      <textarea
        ref={textareaRef}
        rows={3}
        value={text}
        placeholder={placeholder ?? '输入消息，@ 指定技能'}
        onChange={(e) => {
          const value = e.target.value;
          setText(value);
          resize();
          // 光标前若处于「@关键词」输入中，弹出技能菜单
          const cursor = e.target.selectionStart ?? value.length;
          const before = value.slice(0, cursor);
          // 反向规则：@ 前是「字母/数字/下划线/连字符」视为邮箱/标识符，不触发；
          // 其余（中文、标点、行首、空白后）都能直接 @ 触发。
          const match = before.match(AT_QUERY_RE);
          const atIndex = match?.index ?? -1;
          const prev = atIndex > 0 ? before[atIndex - 1] : undefined;
          const isEmailLike = prev !== undefined && AT_EMAIL_RE.test(prev);
          if (match && !isEmailLike) {
            setSkillQuery(match[1]);
            setHighlightIndex(0);
            setShowSkillMenu(true);
          } else {
            setShowSkillMenu(false);
            setSkillQuery('');
          }
        }}
        onKeyDown={handleKeyDown}
        onBlur={() => setShowSkillMenu(false)}
        className="w-full px-5 pt-4 pb-2 text-[14px] text-gray-800 placeholder-gray-400 outline-none resize-none bg-transparent"
      />

      {showSkillMenu && filteredSkills.length > 0 && (
        <div className="absolute left-4 right-4 bottom-14 z-20 max-h-56 overflow-y-auto rounded-xl border border-gray-200 bg-white shadow-[0_8px_30px_rgba(0,0,0,0.10)]">
          {filteredSkills.map((s, i) => {
            const displayName = s.display_name || s.name;
            const origin = originMetaOf(s.origin);
            return (
              <button
                key={s.name}
                type="button"
                ref={i === highlightIndex ? highlightedRef : undefined}
                onMouseDown={(e) => {
                  // 阻止 blur，保持 textarea 光标，pickSkill 才能定位并删掉「@关键词」
                  e.preventDefault();
                  pickSkill(s.name);
                }}
                onMouseEnter={() => setHighlightIndex(i)}
                className={classNames(
                  'flex w-full items-center gap-2 px-3 py-2 text-left',
                  i === highlightIndex ? 'bg-blue-50' : 'bg-white',
                )}
              >
                <span className="shrink-0 text-xs font-semibold text-blue-600">@{displayName}</span>
                <span className={classNames('shrink-0 rounded px-1 py-0.5 text-[10px]', origin.className)}>
                  {origin.label}
                </span>
                <span className="min-w-0 flex-1 truncate text-xs text-gray-500">{s.description}</span>
              </button>
            );
          })}
        </div>
      )}

      <div className="flex items-center justify-between px-3 pb-2">
        <div className="flex items-center gap-1.5">
          <ModelSelector
            models={models}
            value={modelName}
            onChange={handleModelChange}
            thinkingEnabled={thinking}
            thinkingLocked={thinkingLocked}
            onToggleThinking={() => setThinking(!thinking)}
          />
          <label
            title="上传附件"
            className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors cursor-pointer"
          >
            <Paperclip className="w-4 h-4" />
            <input
              type="file"
              multiple
              className="hidden"
              onChange={handleFileChange}
            />
          </label>
        </div>

        <button
          type="button"
          disabled={sending || (!isStreaming && !hasContent)}
          onClick={handleToggleStream}
          className={classNames(
            'w-8 h-8 rounded-full flex items-center justify-center text-white transition-colors disabled:bg-gray-200 disabled:cursor-not-allowed',
            isStreaming ? 'bg-black hover:bg-neutral-800' : 'bg-[#0072ff] hover:bg-[#0056cc]',
          )}
        >
          {isStreaming ? (
            <Square className="w-3.5 h-3.5 fill-current" />
          ) : sending ? (
            <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
          ) : (
            <ArrowUp className="w-4 h-4" />
          )}
        </button>
      </div>
    </div>
  );
}
