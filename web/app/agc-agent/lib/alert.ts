import { message } from 'antd';

/**
 * 统一错误提示（本地实现）。
 * 替代 dify 原项目的 `@/utils-aigc-chat/network` 里的 AlertError —— 后者拖拽了
 * axios + 登录 + msg-content 等一整条 Java 后端基础设施，脱离 dify 后不再引入。
 */
export const AlertError = (msg: string, duration: number = 3) => {
  return message.open({
    type: 'error',
    content: msg,
    duration,
  });
};
