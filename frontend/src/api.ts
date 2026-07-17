/**
 * Centralised API helper functions.
 * Each function maps to one backend endpoint.
 */

// Load API base URL from Vite environment variables for production deployment
export const API_BASE_URL = import.meta.env.VITE_API_URL || '';
const API = `${API_BASE_URL}/api`;

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

export async function sendFeedback(
  messageId: string,
  feedback: 'up' | 'down',
  question: string,
  answer: string,
): Promise<void> {
  await fetch(`${API}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message_id: messageId, feedback, question, answer }),
  });
}
