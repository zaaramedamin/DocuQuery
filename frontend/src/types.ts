/**
 * Shared TypeScript types for the DocuQuery frontend.
 */

export interface Source {
  filename: string;
  page: number;
  text: string;
}

export interface Message {
  id: string;
  sender: 'user' | 'assistant' | 'system';
  text: string;
  sources?: Source[];
  /** The user question this assistant message answered (used for feedback). */
  question?: string;
  /** Feedback the user gave on this assistant message. */
  feedback?: 'up' | 'down';
}
