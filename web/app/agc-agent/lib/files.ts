// 文件下载：与 debug-agent.html 保持一致 —— 始终经同源 /chat/files/{id} 带 auth 抓取
// 二进制后走 Blob 触发下载。不再走 /files/{id}/url 预签名直链：S3 预签名地址指向内网
// OBS（无 CORS、浏览器可能无法解析），且跨域 <a download> 的文件名会被浏览器忽略。

import { AlertError } from './alert';
import { pyFetchBlob } from './pyNetwork';

function saveBlob(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // 延迟释放，避免个别浏览器在下载尚未开始时 revoke 导致失败
  setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}

export async function downloadFile(conversationId: string, path: string): Promise<void> {
  try {
    const blob = await pyFetchBlob(
      `/chat/files/${conversationId}?path=${encodeURIComponent(path)}&download=true`,
    );
    const filename = path.split('/').pop() ?? 'download';
    saveBlob(blob, filename);
  } catch (e) {
    console.warn('[skillhub] download failed', e);
    AlertError('文件下载失败');
  }
}

export async function downloadDirectory(conversationId: string, path: string): Promise<void> {
  try {
    const blob = await pyFetchBlob(
      `/chat/files/${conversationId}/download-dir?path=${encodeURIComponent(path)}`,
    );
    const dirName = path.replace(/\/+$/, '').split('/').pop() || 'download';
    saveBlob(blob, `${dirName}.zip`);
  } catch (e) {
    console.warn('[skillhub] directory download failed', e);
    AlertError('目录下载失败');
  }
}

/** 在新标签页用浏览器原生渲染打开文件（图片 / PDF / HTML 等浏览器可直接渲染的类型）。
 * 后端仅接受 ``Authorization: Bearer`` Header 鉴权，直接 ``window.open`` 服务地址会 401，
 * 故带 auth 抓取后经 blob URL 交给浏览器。先同步开窗，绕过异步取内容导致的 popup 拦截。 */
export function openFileInBrowser(conversationId: string, path: string): void {
  const win = window.open('about:blank', '_blank');
  if (!win) {
    AlertError('浏览器拦截了弹窗，请允许本站弹出窗口后重试');
    return;
  }
  pyFetchBlob(`/chat/files/${conversationId}?path=${encodeURIComponent(path)}`)
    .then((blob) => {
      const objectUrl = URL.createObjectURL(blob);
      win.location.replace(objectUrl);
      // blob URL 由新窗口持有，本页不主动 revoke（提前释放会让新页白屏）；
      // 浏览器会在创建它的文档卸载时统一回收。
    })
    .catch((e) => {
      console.warn('[skillhub] open in browser failed', e);
      win.close();
      AlertError('文件打开失败');
    });
}
