'use client';

import { Toaster as Sonner } from 'sonner';

type ToasterProps = React.ComponentProps<typeof Sonner>;

/**
 * 全局 toast（基于 sonner，shadcn/ui 风格）。
 * 挂在根布局，替代原 antd 的 `message`。
 * 设计对齐前端浅色风格：白底、细边框、圆角、浅阴影。
 */
const Toaster = ({ ...props }: ToasterProps) => (
  <Sonner
    theme="light"
    position="top-center"
    richColors
    closeButton
    toastOptions={{
      classNames: {
        toast: 'group toast rounded-lg border border-gray-200 shadow-lg',
        description: 'text-gray-500',
      },
    }}
    {...props}
  />
);

export { Toaster };
