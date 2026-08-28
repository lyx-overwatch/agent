// Heyu Agent 接口方法封装（对应 docs/api/*.md），返回后端「裸 JSON」原样，不做解包。
// 领域类型（Conversation / Message / FileNode 等）由接线层负责从这些 snake_case 结构映射。

import { pyDELETE, pyGET, pyPOST, pyUpload } from '../lib/pyNetwork';

// ── API 响应类型（snake_case，与后端一致）──────────────────────────────
export interface ApiModel {
  name: string;
  display_name: string;
  model: string;
  supports_thinking: boolean;
  thinking_locked: boolean;
  supports_vision: boolean;
}

export interface ApiConversation {
  conversation_id: string;
  thread_id: string;
  title: string | null;
  title_pending?: boolean;
  status: string;
  total_tokens: number;
  cache_read: number;
  cache_creation: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface ApiMessage {
  id: string;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  event_type: string;
  tool_name: string | null;
  tool_input: string | null;
  tool_output: string | null;
  file_metadata: string | null;
  description: string | null;
  duration_ms: number | null;
  created_at: string | null;
  is_subagent?: boolean;
  subagent_type?: string;
}

export interface ApiFileTreeNode {
  name: string;
  type: 'file' | 'directory';
  virtual_path: string;
  children: ApiFileTreeNode[] | null;
  size: number | null;
  extension: string | null;
  content_type: string | null;
  previewable: boolean;
  label?: string;
}

export interface VerifyResponse {
  user_id: string;
  is_new_user: boolean;
  role: string; // "user" | "admin"，前端据此决定是否展示审核入口
}

export interface AuthUser {
  user_id: string;
  email: string | null;
  username: string | null;
  role: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

/** /skills/mine、/skills/marketplace、/skills/pending 返回的条目（裸数组） */
export interface ApiSkillItem {
  name: string;
  display_name: string;
  description: string;
  author_id: string | null;
  author_name: string | null;
  review_status: string | null;
  review_note: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  version: string | null;
  created_at: string | null;
  added: boolean;
}

/** /skills/available 返回的条目（裸数组，origin 标记来源） */
export interface ApiAvailableSkillItem {
  name: string;
  display_name: string | null;
  description: string;
  origin: 'builtin' | 'mine' | 'added';
  review_status: string | null;
  review_note: string | null;
  version: string | null;
}

/** /skills/builtin 返回的条目（裸数组） */
export interface ApiBuiltinSkillItem {
  name: string;
  description: string;
}

export const skillhubApi = {
  verify: () => pyPOST<VerifyResponse>('/auth/verify'),

  login: (email: string, password: string) =>
    pyPOST<AuthResponse>('/auth/login', { email, password }),

  register: (email: string, password: string) =>
    pyPOST<AuthResponse>('/auth/register', { email, password }),

  listConversations: () =>
    pyGET<{ conversations: ApiConversation[] }>('/conversations'),

  createConversation: (files?: File[]) => {
    const fd = new FormData();
    files?.forEach((f) => fd.append('files', f));
    return pyUpload<{ conversation_id: string; thread_id: string; files: unknown[] }>(
      '/conversations',
      fd,
    );
  },

  appendFiles: (conversationId: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append('files', f));
    return pyUpload<{ conversation_id: string; files: unknown[] }>(
      `/conversations/${conversationId}/files`,
      fd,
    );
  },

  deleteConversation: (conversationId: string) =>
    pyDELETE<{ conversation_id: string; deleted: boolean }>(
      `/conversations/${conversationId}`,
    ),

  getMessages: (conversationId: string) =>
    pyGET<{ conversation_id: string; messages: ApiMessage[] }>(
      `/chat/messages/${conversationId}`,
    ),

  getModels: () => pyGET<{ models: ApiModel[] }>('/models'),

  getSkills: () => pyGET<{ name: string; description: string }[]>('/skills'),

  // ── 技能创作者生态（phase2）──────────────────────────────
  uploadSkill: (file: File, displayName?: string, description?: string) => {
    const fd = new FormData();
    fd.append('file', file);
    if (displayName) fd.append('display_name', displayName);
    if (description) fd.append('description', description);
    return pyUpload<{ skill_name: string; display_name: string; review_status: string }>(
      '/skills',
      fd,
    );
  },

  getBuiltin: () => pyGET<ApiBuiltinSkillItem[]>('/skills/builtin'),

  getMine: () => pyGET<ApiSkillItem[]>('/skills/mine'),

  getMarketplace: () => pyGET<ApiSkillItem[]>('/skills/marketplace'),

  getAvailable: () => pyGET<ApiAvailableSkillItem[]>('/skills/available'),

  getPending: () => pyGET<ApiSkillItem[]>('/skills/pending'),

  addSkill: (name: string) =>
    pyPOST<{ skill_name: string; added: boolean }>(
      `/skills/${encodeURIComponent(name)}/add`,
    ),

  removeAddedSkill: (name: string) =>
    pyDELETE<{ skill_name: string; added: boolean }>(
      `/skills/${encodeURIComponent(name)}/add`,
    ),

  publishSkill: (name: string) =>
    pyPOST<{ skill_name: string; review_status: string }>(
      `/skills/${encodeURIComponent(name)}/publish`,
    ),

  deleteSkill: (name: string) =>
    pyDELETE<{ skill_name: string; deleted: boolean }>(
      `/skills/${encodeURIComponent(name)}`,
    ),

  reviewSkill: (name: string, action: 'approve' | 'reject', reason?: string) =>
    pyPOST<{ skill_name: string; review_status: string; review_note: string | null }>(
      `/skills/${encodeURIComponent(name)}/review`,
      { action, reason },
    ),

  getFileTree: (conversationId: string) =>
    pyGET<{ conversation_id: string; roots: ApiFileTreeNode[] }>(
      `/conversations/${conversationId}/files/tree`,
    ),

  stopStream: (conversationId: string) => {
    const fd = new FormData();
    fd.append('conversation_id', conversationId);
    return pyUpload<{ status: string; conversation_id: string }>(
      '/chat/stream/stop',
      fd,
    );
  },
};
