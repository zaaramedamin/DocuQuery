/**
 * Centralised API helper functions.
 * Each function maps to one backend endpoint. Authenticated calls go
 * through `authFetch`, which attaches the session token and transparently
 * refreshes it once when it has expired.
 */

import type {
  Account,
  AuthUser,
  ConversationInfo,
  DocInfo,
  ImportPayload,
  Message,
  Plan,
  SearchResult,
  Session,
  ShareInfo,
  ShareKind,
  SharedView,
  UploadProgress,
  Usage,
} from './types';
import type { Preferences } from './preferences';

// Load API base URL from Vite environment variables for production deployment.
// Strip a trailing slash so a value like "https://api.example.com/" still
// produces correct "…/api/…" URLs.
export const API_BASE_URL = (import.meta.env.VITE_API_URL || '').replace(/\/+$/, '');
const API = `${API_BASE_URL}/api`;

// ── Session storage ──────────────────────────────────────────────────

const SESSION_KEY = 'docuquery.session';
const listeners = new Set<(session: Session | null) => void>();

function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Session;
    return parsed?.access_token && parsed?.refresh_token ? parsed : null;
  } catch {
    return null;
  }
}

let session: Session | null = loadSession();

function setSession(next: Session | null) {
  session = next;
  try {
    if (next) localStorage.setItem(SESSION_KEY, JSON.stringify(next));
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable (private mode): the session just won't survive a reload */
  }
  listeners.forEach((fn) => fn(next));
}

export function getSession(): Session | null {
  return session;
}

/** Subscribe to sign-in / sign-out. Returns an unsubscribe function. */
export function onAuthChange(fn: (session: Session | null) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function signOut() {
  setSession(null);
}

// ── Errors ───────────────────────────────────────────────────────────

/**
 * An error from the server. Plan limits (file too big, library full, daily
 * questions used) carry `upgrade: true` when the Pro plan would lift them.
 */
export class ApiError extends Error {
  status: number;
  code?: string;
  upgrade: boolean;

  constructor(message: string, status = 0, extra: { code?: string; upgrade?: boolean } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = extra.code;
    this.upgrade = !!extra.upgrade;
  }
}

/** Build an ApiError from a FastAPI error body (the detail is a string, or an object for plan limits). */
export function apiError(body: unknown, fallback: string, status = 0): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const info = detail as { code?: unknown; upgrade?: unknown };
    return new ApiError(errorMessage(body, fallback), status, {
      code: typeof info.code === 'string' ? info.code : undefined,
      upgrade: info.upgrade === true,
    });
  }
  return new ApiError(errorMessage(body, fallback), status);
}

/** Pull a human-readable message out of a FastAPI error body. */
export function errorMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string' && detail) return detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === 'string' && message) return message;
  }
  if (Array.isArray(detail) && detail.length) {
    // Validation errors: [{ msg: "...", loc: [...] }]
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg.replace(/^Value error, /, '');
  }
  return fallback;
}

async function readError(res: Response, fallback: string): Promise<ApiError> {
  const body = await res.json().catch(() => null);
  return apiError(body, fallback, res.status);
}

// ── Authentication ───────────────────────────────────────────────────

interface AuthResponse {
  access_token?: string;
  refresh_token?: string;
  expires_at?: number | null;
  user?: AuthUser;
  needs_confirmation?: boolean;
  email?: string;
}

async function authRequest(path: 'login' | 'signup', email: string, password: string) {
  const res = await fetch(`${API}/auth/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw await readError(res, 'Could not sign in. Please try again.');
  return (await res.json()) as AuthResponse;
}

function adopt(data: AuthResponse) {
  setSession({
    access_token: data.access_token!,
    refresh_token: data.refresh_token!,
    expires_at: data.expires_at,
    user: data.user!,
  });
}

export async function login(email: string, password: string): Promise<void> {
  adopt(await authRequest('login', email, password));
}

/** Returns true when the account needs email confirmation before first sign-in. */
export async function signup(email: string, password: string): Promise<boolean> {
  const data = await authRequest('signup', email, password);
  if (data.needs_confirmation) return true;
  adopt(data);
  return false;
}

/** Email a password-reset link. Always resolves the same way, whether or not the address has an account. */
export async function forgotPassword(email: string): Promise<void> {
  const res = await fetch(`${API}/auth/forgot-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, redirect_to: window.location.origin + '/' }),
  });
  if (!res.ok) throw await readError(res, 'Could not send the reset email. Please try again.');
}

/** Set a new password using the token from the emailed reset link. */
export async function resetPassword(accessToken: string, password: string): Promise<void> {
  const res = await fetch(`${API}/auth/reset-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ access_token: accessToken, password }),
  });
  if (!res.ok) throw await readError(res, 'Could not update the password. The link may have expired.');
}

let refreshing: Promise<boolean> | null = null;

/** Exchange the refresh token for a new session. Concurrent callers share one request. */
function refreshSession(): Promise<boolean> {
  if (!session) return Promise.resolve(false);
  if (!refreshing) {
    const token = session.refresh_token;
    refreshing = (async () => {
      try {
        const res = await fetch(`${API}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: token }),
        });
        if (!res.ok) return false;
        adopt((await res.json()) as AuthResponse);
        return true;
      } catch {
        return false;
      } finally {
        refreshing = null;
      }
    })();
  }
  return refreshing;
}

/** Refresh ahead of time when the token is about to expire (used before long uploads). */
async function ensureFreshToken() {
  if (session?.expires_at && session.expires_at - Date.now() / 1000 < 60) {
    await refreshSession();
  }
}

function withAuth(init: RequestInit): RequestInit {
  const headers = new Headers(init.headers);
  if (session) headers.set('Authorization', `Bearer ${session.access_token}`);
  return { ...init, headers };
}

export async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API}${path}`;
  await ensureFreshToken();
  let res = await fetch(url, withAuth(init));
  if (res.status === 401 && session) {
    if (await refreshSession()) res = await fetch(url, withAuth(init));
    if (res.status === 401) signOut(); // session is dead: back to the login screen
  }
  return res;
}

async function getJson<T>(path: string, fallback: string): Promise<T> {
  const res = await authFetch(path);
  if (!res.ok) throw await readError(res, fallback);
  return res.json();
}

// ── Documents ────────────────────────────────────────────────────────

export async function fetchDocuments(): Promise<DocInfo[]> {
  const data = await getJson<{ documents?: DocInfo[] }>('/documents', 'Failed to fetch documents');
  return data.documents ?? [];
}

/**
 * POST to an endpoint that streams NDJSON progress events and resolves with
 * the finished document. The first 10% of the bar is the browser → server
 * transfer; the rest is the server reading, embedding and summarizing.
 */
function streamUpload(
  path: string,
  body: FormData | string,
  headers: Record<string, string>,
  onProgress: (p: UploadProgress) => void,
): Promise<DocInfo> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    let consumed = 0;
    let finished: DocInfo | null = null;
    let streamError: string | null = null;

    const consume = () => {
      const text = xhr.responseText;
      const end = text.lastIndexOf('\n');
      if (end < consumed) return;
      const lines = text.slice(consumed, end).split('\n');
      consumed = end + 1;
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const event = JSON.parse(line);
          if (event.type === 'progress') {
            onProgress({ percent: 10 + Math.round(event.percent * 0.9), message: event.message });
          } else if (event.type === 'done') {
            finished = event.document;
          } else if (event.type === 'error') {
            streamError = typeof event.detail === 'string' ? event.detail : 'Upload failed';
          }
        } catch {
          /* ignore a malformed line */
        }
      }
    };

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        onProgress({ percent: Math.round((e.loaded / e.total) * 10), message: 'Uploading…' });
      }
    };
    xhr.onprogress = consume;
    xhr.onerror = () => reject(new Error('Network error — could not reach the server.'));
    xhr.onload = () => {
      if (xhr.status === 401) {
        signOut();
        reject(new Error('Your session has expired. Please sign in again.'));
        return;
      }
      if (xhr.status >= 400) {
        let parsed: unknown = null;
        try {
          parsed = JSON.parse(xhr.responseText);
        } catch {
          /* non-JSON error body */
        }
        reject(apiError(parsed, `Upload failed (HTTP ${xhr.status})`, xhr.status));
        return;
      }
      consume();
      if (streamError) reject(new Error(streamError));
      else if (finished) resolve(finished);
      else reject(new Error('The upload ended unexpectedly. Please try again.'));
    };

    // Refresh first (if needed) so the request carries a valid token.
    ensureFreshToken().finally(() => {
      xhr.open('POST', `${API}${path}`);
      if (session) xhr.setRequestHeader('Authorization', `Bearer ${session.access_token}`);
      for (const [key, value] of Object.entries(headers)) xhr.setRequestHeader(key, value);
      xhr.send(body);
    });
  });
}

export function uploadFile(file: File, onProgress: (p: UploadProgress) => void): Promise<DocInfo> {
  const form = new FormData();
  form.append('file', file);
  return streamUpload('/upload', form, {}, onProgress);
}

export function uploadUrl(url: string, onProgress: (p: UploadProgress) => void): Promise<DocInfo> {
  return streamUpload('/upload-url', JSON.stringify({ url }), { 'Content-Type': 'application/json' }, onProgress);
}

/** Add text the user pasted, or sent from their own browser, as a source. */
export function uploadText(payload: Partial<ImportPayload> & { text: string }, onProgress: (p: UploadProgress) => void): Promise<DocInfo> {
  return streamUpload(
    '/upload-text',
    JSON.stringify({ title: payload.title ?? '', text: payload.text, url: payload.url || null }),
    { 'Content-Type': 'application/json' },
    onProgress,
  );
}

export async function setTags(filename: string, tags: string[]): Promise<string[]> {
  const res = await authFetch(`/documents/${encodeURIComponent(filename)}/tags`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tags }),
  });
  if (!res.ok) throw await readError(res, 'Could not save the tags');
  return (await res.json()).tags;
}

// ── Folders ──────────────────────────────────────────────────────────

async function sendJson(path: string, method: string, body: unknown, fallback: string): Promise<Response> {
  const res = await authFetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw await readError(res, fallback);
  return res;
}

/** Put sources in a folder (created if new), or take them out of theirs with `null`. Returns the folder's final name. */
export async function assignFolder(filenames: string[], folder: string | null): Promise<string | null> {
  const res = await sendJson('/folders/assign', 'PUT', { filenames, folder }, 'Could not move the sources');
  return (await res.json()).folder;
}

export async function renameFolder(name: string, newName: string): Promise<string> {
  const res = await sendJson('/folders', 'PATCH', { name, new_name: newName }, 'Could not rename the folder');
  return (await res.json()).folder;
}

/** Remove a folder; its sources are kept. */
export async function deleteFolder(name: string): Promise<void> {
  const res = await authFetch(`/folders?name=${encodeURIComponent(name)}`, { method: 'DELETE' });
  if (!res.ok) throw await readError(res, 'Could not remove the folder');
}

export async function deleteDocument(filename: string): Promise<void> {
  const res = await authFetch(`/documents/${encodeURIComponent(filename)}`, { method: 'DELETE' });
  if (!res.ok) throw await readError(res, 'Deletion failed');
}

/** The original file as a Blob (the viewer can't send auth headers from an <iframe>). */
export async function fetchDocumentBlob(filename: string): Promise<Blob> {
  const res = await authFetch(`/documents/file/${encodeURIComponent(filename)}`);
  if (!res.ok) throw await readError(res, 'Could not load the file');
  return res.blob();
}

export async function fetchDocumentPages(filename: string): Promise<string[]> {
  const data = await getJson<{ pages: string[] }>(
    `/document-pages/${encodeURIComponent(filename)}`,
    'Could not load the document text',
  );
  return data.pages;
}

// ── Conversations ────────────────────────────────────────────────────

export async function fetchConversations(): Promise<ConversationInfo[]> {
  const data = await getJson<{ conversations: ConversationInfo[] }>('/conversations', 'Failed to load chats');
  return data.conversations;
}

interface StoredMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources: Message['sources'];
  question: string | null;
  feedback: 'up' | 'down' | null;
}

export async function fetchConversation(id: string): Promise<{ conversation: ConversationInfo; messages: Message[] }> {
  const data = await getJson<{ conversation: ConversationInfo; messages: StoredMessage[] }>(
    `/conversations/${id}`,
    'Could not open this chat',
  );
  return {
    conversation: data.conversation,
    messages: data.messages.map((m) => ({
      id: m.id,
      serverId: m.id,
      sender: m.role,
      text: m.content,
      sources: m.sources ?? [],
      question: m.question ?? undefined,
      feedback: m.feedback ?? undefined,
    })),
  };
}

export async function renameConversation(id: string, title: string): Promise<void> {
  const res = await authFetch(`/conversations/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw await readError(res, 'Could not rename the chat');
}

export async function deleteConversation(id: string): Promise<void> {
  const res = await authFetch(`/conversations/${id}`, { method: 'DELETE' });
  if (!res.ok) throw await readError(res, 'Could not delete the chat');
}

export async function searchConversations(query: string): Promise<SearchResult[]> {
  const data = await getJson<{ results: SearchResult[] }>(
    `/conversations/search?q=${encodeURIComponent(query)}`,
    'Search failed',
  );
  return data.results;
}

// ── Sharing ──────────────────────────────────────────────────────────

export async function createShare(kind: ShareKind, ref: string): Promise<ShareInfo> {
  const res = await authFetch('/shares', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, ref }),
  });
  if (!res.ok) throw await readError(res, 'Could not create the link');
  return res.json();
}

export async function listShares(): Promise<ShareInfo[]> {
  return (await getJson<{ shares: ShareInfo[] }>('/shares', 'Could not load your links')).shares;
}

export async function revokeShare(id: string): Promise<void> {
  const res = await authFetch(`/shares/${id}`, { method: 'DELETE' });
  if (!res.ok) throw await readError(res, 'Could not turn the link off');
}

/** Open a share link. Public: works without being signed in. */
export async function getShared(token: string): Promise<SharedView> {
  const res = await fetch(`${API}/shared/${encodeURIComponent(token)}`);
  if (!res.ok) throw await readError(res, 'This link is not available');
  return res.json();
}

export async function acceptShared(token: string): Promise<DocInfo> {
  const res = await authFetch(`/shared/${encodeURIComponent(token)}/accept`, { method: 'POST' });
  if (!res.ok) throw await readError(res, 'Could not add this source');
  return (await res.json()).document;
}

// ── Misc ─────────────────────────────────────────────────────────────

export async function sendFeedback(
  messageId: string,
  feedback: 'up' | 'down',
  question: string,
  answer: string,
): Promise<void> {
  await authFetch('/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message_id: messageId, feedback, question, answer }),
  });
}

export function fetchUsage(): Promise<Usage> {
  return getJson<Usage>('/usage', 'Failed to load usage');
}

// ── Account, settings and plan ───────────────────────────────────────

export function fetchAccount(): Promise<Account> {
  return getJson<Account>('/account', 'Failed to load your account');
}

export async function updateDisplayName(displayName: string): Promise<string> {
  const res = await sendJson('/account', 'PATCH', { display_name: displayName }, 'Could not save your name');
  return (await res.json()).display_name;
}

export async function fetchSettings(): Promise<Partial<Preferences>> {
  return (await getJson<{ settings: Partial<Preferences> }>('/settings', 'Failed to load your settings')).settings;
}

export async function saveSettings(patch: Partial<Preferences>): Promise<void> {
  await sendJson('/settings', 'PUT', patch, 'Could not save your settings');
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await sendJson(
    '/account/password',
    'POST',
    { current_password: currentPassword, new_password: newPassword },
    'Could not change the password',
  );
}

/** Everything stored about the user, as a JSON file. */
export async function exportData(): Promise<Blob> {
  const res = await authFetch('/account/export');
  if (!res.ok) throw await readError(res, 'Could not export your data');
  return res.blob();
}

export async function deleteAllChats(): Promise<number> {
  const res = await authFetch('/account/chats', { method: 'DELETE' });
  if (!res.ok) throw await readError(res, 'Could not delete your chats');
  return (await res.json()).deleted;
}

export async function deleteAllDocuments(): Promise<number> {
  const res = await authFetch('/account/documents', { method: 'DELETE' });
  if (!res.ok) throw await readError(res, 'Could not delete your sources');
  return (await res.json()).deleted;
}

/** Permanently delete the account. Asks the server to re-check the password. */
export async function deleteAccount(password: string): Promise<void> {
  await sendJson('/account/delete', 'POST', { password }, 'Could not delete the account');
  signOut();
}

// ── Pro plan (demo) ──────────────────────────────────────────────────

/** Switch the account between Free and Pro. There is no payment: it is a demonstration. */
export async function switchPlan(plan: Plan): Promise<void> {
  await sendJson('/billing/demo', 'POST', { plan }, 'Could not change the plan');
}
