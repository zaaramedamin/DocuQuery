/**
 * Centralised API helper functions.
 * Each function maps to one backend endpoint.
 */

import type { Source } from './types';

const API = '/api';

export async function fetchDocuments(): Promise<string[]> {
  const res = await fetch(`${API}/documents`);
  if (!res.ok) throw new Error('Failed to fetch documents');
  const data = await res.json();
  return data.documents ?? [];
}

export async function uploadDocument(file: File): Promise<{ filename: string; chunks_count: number }> {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${API}/upload`, { method: 'POST', body: formData });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'Upload failed');
  }
  return res.json();
}

export async function deleteDocument(filename: string): Promise<void> {
  const res = await fetch(`${API}/documents/${encodeURIComponent(filename)}`, { method: 'DELETE' });
  if (!res.ok) throw new Error('Deletion failed');
}

export async function queryDocuments(
  question: string,
  filename: string | null,
): Promise<{ answer: string; sources: Source[] }> {
  const res = await fetch(`${API}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, filename }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'Query failed');
  }
  return res.json();
}
