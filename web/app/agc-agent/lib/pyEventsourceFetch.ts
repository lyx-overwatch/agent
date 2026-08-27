// ⚠️ 占位文件（STUB）—— 明天从原项目拷贝真实源码后整体替换本文件。
// 仅保证导出函数签名与 components/skillhub-chat.tsx 的调用点对齐。

export interface PyEventsourceHandlers {
  /** 拿到底层 AbortController，供调用方在「停止生成」时 abort */
  getAbortController?: (c: AbortController) => void;
  /** 每个 SSE 事件反序列化后的 JSON 载荷 */
  onMessage: (data: unknown) => void;
  onClose?: () => void;
  onError?: () => void;
}

export function pyEventsourceFetch(
  _path: string,
  _body: FormData,
  _handlers: PyEventsourceHandlers,
): Promise<void> {
  return Promise.reject(
    new Error('[SkillHub] pyEventsourceFetch 未接入真实实现（占位，待替换）'),
  );
}
