/**
 * Shared TypeScript types for the DocuQuery frontend.
 */

export interface Source {
  filename: string;
  page: number;
  text: string;
}

export interface Message {
  /** Stable React key. For saved messages this equals the server id. */
  id: string;
  /** Id assigned by the server once the answer is saved (used for feedback). */
  serverId?: string;
  sender: 'user' | 'assistant';
  text: string;
  sources?: Source[];
  /** The user question this assistant message answered (used for feedback). */
  question?: string;
  /** Feedback the user gave on this assistant message. */
  feedback?: 'up' | 'down';
  /** The user pressed Stop before the answer finished. */
  stopped?: boolean;
}

export type FileType = 'pdf' | 'docx' | 'pptx' | 'xlsx' | 'csv' | 'txt' | 'md' | 'image' | 'url';

export interface DocInfo {
  id: string;
  filename: string;
  file_type: FileType;
  size_bytes: number;
  page_count: number;
  chunks_count: number;
  summary: string | null;
  suggested_questions: string[];
  source_url: string | null;
  tags: string[];
  /** The folder the source is in, if any. */
  folder: string | null;
  created_at: string;
  /** Present only on the document returned right after an upload (e.g. skipped OCR pages). */
  warnings?: string[];
}

export interface ConversationInfo {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface AuthUser {
  id: string;
  email: string | null;
}

export interface Session {
  access_token: string;
  refresh_token: string;
  /** Unix timestamp (seconds) when the access token expires. */
  expires_at?: number | null;
  user: AuthUser;
}

export type Plan = 'free' | 'pro';

export interface Usage {
  plan: Plan;
  /** Biggest file the user's plan accepts. */
  max_upload_bytes: number;
  documents: { used: number; limit: number };
  storage: { used_bytes: number; limit_bytes: number };
  questions_today: { used: number; limit: number };
}

export interface PlanLimits {
  max_upload_bytes: number;
  documents: number;
  storage_bytes: number;
  daily_questions: number;
  ocr_pages: number;
}

export interface Account {
  id: string;
  email: string | null;
  display_name: string;
  plan: Plan;
  subscription: {
    status: string | null;
    /** When the paid period ends / renews (ISO date). */
    renews_at: string | null;
    cancel_at_period_end: boolean;
  };
  billing: {
    /** Upgrading to Pro is switched on (it is a demo: nothing is charged). */
    available: boolean;
    price_cents: number;
    currency: string;
  };
  limits: Record<Plan, PlanLimits>;
}

export interface UploadProgress {
  percent: number;
  message: string;
}

export interface SearchResult {
  id: string;
  title: string;
  updated_at: string;
  /** Excerpt around the match (empty when only the title matched). */
  snippet: string;
}

export type ShareKind = 'conversation' | 'document';

export interface ShareInfo {
  id: string;
  token: string;
  kind: ShareKind;
  /** Conversation id, or the document's file name. */
  ref: string;
  created_at: string | null;
}

export type SharedView =
  | {
      kind: 'conversation';
      title: string;
      messages: { role: 'user' | 'assistant'; content: string; sources: { filename: string; page: number }[] }[];
    }
  | {
      kind: 'document';
      filename: string;
      file_type: FileType;
      page_count: number;
      size_bytes: number;
      summary: string | null;
    };

/** Text sent from the user's own browser (or pasted) to be added as a source. */
export interface ImportPayload {
  title: string;
  url: string;
  text: string;
}
