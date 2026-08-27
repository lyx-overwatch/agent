// ⚠️ 占位文件（STUB）—— 明天从原项目拷贝真实源码后整体替换本文件。
// 仅保证导出函数签名与 api/skillhub.ts、FilePreviewModal 等调用点对齐。
//
// 真实实现约定（供明天替换参考）：
// - 统一在 next.config.ts 用 rewrites 把 `/api/*` 代理到 SkillHub 后端（本地 8001）。
// - 请求 base 前缀用 `NEXT_PUBLIC_API_BASE`（默认 `/api`），路径形如 `/api/conversations`。

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? '/api';

function stub<T = never>(name: string): Promise<T> {
  return Promise.reject(
    new Error(`[SkillHub] ${name} 未接入真实实现（lib/pyNetwork 占位，待替换）`),
  );
}

export const pyGET = <T>(_path: string): Promise<T> => stub<T>('pyGET');
export const pyPOST = <T>(_path: string, _body?: unknown): Promise<T> =>
  stub<T>('pyPOST');
export const pyDELETE = <T>(_path: string): Promise<T> => stub<T>('pyDELETE');
export const pyUpload = <T>(_path: string, _formData: FormData): Promise<T> =>
  stub<T>('pyUpload');
export const pyFetchBlob = (_path: string): Promise<Blob> =>
  stub<Blob>('pyFetchBlob');

// 标记 API_BASE 已声明，避免未使用告警（真实实现会用到）。
void API_BASE;
