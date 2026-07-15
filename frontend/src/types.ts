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
}
