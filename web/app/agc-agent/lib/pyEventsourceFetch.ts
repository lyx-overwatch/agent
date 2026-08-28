// /py/api 的 SSE 流式请求（FormData 版）。
// chat/stream 是 multipart/form-data，现有 eventsourceFetch 只发 JSON，故单独实现。
// 事件解析：后端每行 `data: <json>`（扁平 `type` 字段），结尾 `data: [DONE]`。

import { fetchEventSource } from '@microsoft/fetch-event-source';

export interface PyStreamCallbacks {
  getAbortController: (c: AbortController) => void;
  onMessage: (data: unknown, event?: string) => void;
  onClose: () => void;
  onError: (err: unknown) => void;
}

export async function pyEventsourceFetch(
  url: string,
  formData: FormData,
  { getAbortController, onMessage, onClose, onError }: PyStreamCallbacks,
): Promise<void> {
  const abortController = new AbortController();
  getAbortController(abortController);

  const token = localStorage.getItem('token') ?? '';
  const path = url.startsWith('/') ? url : `/${url}`;

  // onClose 幂等收尾：正常 EOF 与「收到 [DONE] 后主动 abort」都会走到这里，
  // 避免重复触发 refreshConversations。
  let closed = false;
  const finish = () => {
    if (closed) return;
    closed = true;
    onClose();
  };

  await fetchEventSource(`/py/api${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
    signal: abortController.signal,
    openWhenHidden: true,
    onmessage(event) {
      if (event.data === '[DONE]') {
        // 后端已完整结束。主动 abort 让 fetchEventSource 立即正常 resolve，而不是
        // 继续读 EOF —— Next 反代在流结束后可能用 RST 重置连接，浏览器会把后续读
        // 报成 `TypeError: network error`，进而误触发「网络连接中断，请重试」。
        finish();
        abortController.abort();
        return;
      }
      try {
        const parsed = JSON.parse(event.data);
        if (parsed && typeof parsed === 'object') onMessage(parsed, event.event);
      } catch {
        // 忽略无法解析的行（心跳/空行）
      }
    },
    onclose() {
      // 无 [DONE] 的正常 EOF（如后端前台异常后直接关闭）：收尾一次
      finish();
    },
    onerror(err) {
      onError(err);
      // fetchEventSource 约定：抛错才停止重连
      throw err;
    },
  });
}
