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

  await fetchEventSource(`/py/api${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
    signal: abortController.signal,
    openWhenHidden: true,
    onmessage(event) {
      if (event.data === '[DONE]') return;
      try {
        const parsed = JSON.parse(event.data);
        if (parsed && typeof parsed === 'object') onMessage(parsed, event.event);
      } catch {
        // 忽略无法解析的行（心跳/空行）
      }
    },
    onclose() {
      onClose();
    },
    onerror(err) {
      onError(err);
      // fetchEventSource 约定：抛错才停止重连
      throw err;
    },
  });
}
