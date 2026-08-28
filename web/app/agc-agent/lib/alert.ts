import { toast } from 'sonner';

/**
 * 统一错误提示（本地实现）。
 * 替代 dify 原项目的 `@/utils-aigc-chat/network` 里的 AlertError —— 后者拖拽了
 * axios + 登录 + msg-content 等一整条 Java 后端基础设施，脱离 dify 后不再引入。
 * 底层改用 shadcn/ui 的 sonner toast，替代原 antd 的 `message`。
 */
export const AlertError = (msg: string, duration: number = 3) => {
  // antd 的 message duration 单位是秒，sonner 的 duration 单位是毫秒
  toast.error(msg, { duration: duration * 1000 });
};
