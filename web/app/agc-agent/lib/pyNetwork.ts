// /py/api 请求层：Python 后端返回「裸 JSON」（无 code/data/msg 包裹），
// 与 utils-aigc-chat/network.tsx 的 Java 解包逻辑解耦（见 docs/move-to-cmbweb §3.2 / D2）。
//
// - 统一走同源反代：相对路径 /py/api，由 Next.js rewrites 代理到后端（BACKEND_URL）

const PREFIX = '/py/api';

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

interface RequestOptions {
  body?: unknown;
  formData?: FormData;
  signal?: AbortSignal;
}

async function request<T>(
  method: string,
  url: string,
  opts: RequestOptions = {},
): Promise<T> {
  const headers = authHeaders();
  let body: BodyInit | undefined;

  if (opts.formData) {
    // FormData：不手动设 Content-Type，让浏览器自动带 multipart 边界
    body = opts.formData;
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }

  const res = await fetch(`${PREFIX}${url}`, {
    method,
    headers,
    body,
    signal: opts.signal,
  });

  if (!res.ok) {
    let detail: string = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || data.message || JSON.stringify(data);
    } catch {
      // 非 JSON 错误体，保留 statusText
    }
    throw new Error(`${res.status} ${detail}`);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const pyGET = <T>(url: string, signal?: AbortSignal) =>
  request<T>('GET', url, { signal });

export const pyPOST = <T>(url: string, body?: unknown) =>
  request<T>('POST', url, { body });

export const pyDELETE = <T>(url: string) => request<T>('DELETE', url);

export const pyUpload = <T>(url: string, formData: FormData) =>
  request<T>('POST', url, { formData });

/** 抓取二进制文件内容（带 auth），用于预览/下载 */
export async function pyFetchBlob(url: string): Promise<Blob> {
  const headers = authHeaders();
  const res = await fetch(`${PREFIX}${url}`, { headers });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.blob();
}
