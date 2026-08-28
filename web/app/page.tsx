'use client';

import { type FormEvent, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { message } from 'antd';
import { Eye, EyeOff, Lock, Mail, Sparkles } from 'lucide-react';
import { skillhubApi } from './agc-agent/api/skillhub';

type Mode = 'login' | 'register';

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** 登录 / 注册页（根路由）：成功签发 token 后跳工作台，风格对齐 ui-pages（#0072ff 主色 + 白卡片） */
export default function Home() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);

  // 已登录则直接进工作台
  useEffect(() => {
    if (localStorage.getItem('token')) router.replace('/agc-agent');
  }, [router]);

  const switchMode = (next: Mode) => {
    setMode(next);
    setPassword('');
    setConfirm('');
  };

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (loading) return;

    const trimmed = email.trim().toLowerCase();
    if (!EMAIL_RE.test(trimmed)) {
      message.error('请输入正确的邮箱地址');
      return;
    }
    if (mode === 'register' && password.length < 8) {
      message.error('密码至少 8 位');
      return;
    }
    if (mode === 'register' && password !== confirm) {
      message.error('两次输入的密码不一致');
      return;
    }

    setLoading(true);
    try {
      const res =
        mode === 'login'
          ? await skillhubApi.login(trimmed, password)
          : await skillhubApi.register(trimmed, password);
      localStorage.setItem('token', res.access_token);
      router.replace('/agc-agent');
    } catch (err) {
      message.error(err instanceof Error ? err.message : '操作失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  const inputClass =
    'w-full pl-9 pr-3 py-2 text-sm border border-gray-300 rounded-lg ' +
    'focus:outline-none focus:ring-2 focus:ring-[#0072ff]/30 focus:border-[#0072ff] transition-colors';

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md">
        {/* Logo + 标题 */}
        <div className="flex flex-col items-center mb-6">
          <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-[#0072ff] mb-3">
            <Sparkles className="w-6 h-6 text-white" />
          </div>
          <h1 className="text-xl font-bold text-gray-900">Heyu Agent</h1>
          <p className="text-sm text-gray-500 mt-1">AI Agent 平台</p>
        </div>

        <div className="bg-white rounded-2xl border border-gray-200 shadow-xl p-6">
          {/* 登录 / 注册切换 */}
          <div className="flex rounded-lg bg-gray-100 p-1 mb-6">
            {(['login', 'register'] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => switchMode(m)}
                className={
                  'flex-1 py-2 rounded-md text-sm font-medium transition-colors ' +
                  (mode === m
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700')
                }
              >
                {m === 'login' ? '登录' : '注册'}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* 邮箱 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                邮箱
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  autoComplete="email"
                  className={inputClass}
                />
              </div>
            </div>

            {/* 密码 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                密码
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={mode === 'register' ? '至少 8 位' : '请输入密码'}
                  autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                  className={inputClass + ' pr-10'}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  title={showPassword ? '隐藏密码' : '显示密码'}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* 确认密码（仅注册） */}
            {mode === 'register' && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  确认密码
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    placeholder="再次输入密码"
                    autoComplete="new-password"
                    className={inputClass}
                  />
                </div>
              </div>
            )}

            {/* 提交 */}
            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 rounded-lg bg-[#0072ff] hover:bg-[#0056cc] text-white text-sm font-medium transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {loading ? '请稍候…' : mode === 'login' ? '登录' : '注册并登录'}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-gray-400 mt-4">
          {mode === 'login' ? '还没有账号？' : '已有账号？'}
          <button
            type="button"
            onClick={() => switchMode(mode === 'login' ? 'register' : 'login')}
            className="ml-1 text-[#0072ff] hover:text-[#0056cc] font-medium"
          >
            {mode === 'login' ? '立即注册' : '去登录'}
          </button>
        </p>
      </div>
    </div>
  );
}
