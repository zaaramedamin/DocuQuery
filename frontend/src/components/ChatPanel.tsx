/**
 * ChatPanel component — header scope bar, message feed, and input area.
 */

import { useState, useRef, useEffect } from 'react';
import type { FormEvent } from 'react';
import { Send, Zap, BookOpen, Database } from 'lucide-react';
import type { Message, Source } from '../types';
import * as api from '../api';

interface ChatPanelProps {
  documents: string[];
  selectedDocument: string | null;
  onClearScope: () => void;
}

export default function ChatPanel({ documents, selectedDocument, onClearScope }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'welcome',
      sender: 'system',
      text: 'Upload your PDF sources on the left, then ask natural language questions. Answers are generated from your documents with page-level citations.',
    },
  ]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const question = query.trim();
    if (!question || loading) return;

    setQuery('');
    setMessages((prev) => [...prev, { id: `user-${Date.now()}`, sender: 'user', text: question }]);
    setLoading(true);

    try {
      const data = await api.queryDocuments(question, selectedDocument);
      setMessages((prev) => [
        ...prev,
        { id: `assistant-${Date.now()}`, sender: 'assistant', text: data.answer, sources: data.sources },
      ]);
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        { id: `error-${Date.now()}`, sender: 'assistant', text: `Error: ${err.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const hasDocs = documents.length > 0;

  return (
    <main className="chat-panel">
      {/* Scope header */}
      <header className="chat-header">
        <div className="current-scope">
          <span className="scope-label">Querying:</span>
          <span className="scope-value">{selectedDocument ?? 'All Sources'}</span>
          {selectedDocument && (
            <button className="clear-scope-btn" onClick={onClearScope}>
              × Clear
            </button>
          )}
        </div>
      </header>

      {/* Message feed */}
      <div className="message-feed">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {loading && <TypingIndicator />}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <div className="input-area">
        <form id="chat-form" onSubmit={handleSubmit}>
          <input
            type="text"
            id="query-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={hasDocs ? 'Ask a question about your sources…' : 'Add a source to begin…'}
            autoComplete="off"
            required
            disabled={!hasDocs || loading}
          />
          <button type="submit" id="send-btn" disabled={!hasDocs || !query.trim() || loading}>
            <span className="btn-text">Ask</span>
            <Send size={14} className="btn-icon" />
          </button>
        </form>
      </div>
    </main>
  );
}

/* ── Sub-components ────────────────────────────────────────────── */

function MessageBubble({ message }: { message: Message }) {
  const { sender, text, sources } = message;
  const cls = sender === 'user' ? 'user-msg' : sender === 'system' ? 'system-msg' : 'assistant-msg';
  const avatar = sender === 'user' ? 'You' : sender === 'system' ? '✦' : 'AI';

  return (
    <div className={`message ${cls}`}>
      <div className="msg-avatar">{avatar}</div>
      <div className="msg-body">
        {sender === 'system' ? <WelcomeContent text={text} /> : <QueryContent text={text} sources={sources} />}
      </div>
    </div>
  );
}

function WelcomeContent({ text }: { text: string }) {
  return (
    <>
      <h3>Welcome to DocuQuery</h3>
      <p className="welcome-subtitle">{text}</p>
      <div className="features-grid">
        <Feature
          icon={<Zap size={20} />}
          title="Semantic Search"
          desc="Retrieves information by contextual meaning, not keyword matching."
        />
        <Feature
          icon={<BookOpen size={20} />}
          title="Page Citations"
          desc="Every answer is grounded with exact page references from your PDFs."
        />
        <Feature
          icon={<Database size={20} />}
          title="Supabase + pgvector"
          desc="Vectors are stored in PostgreSQL and searched at the database level."
        />
      </div>
    </>
  );
}

function Feature({ icon, title, desc }: { icon: React.ReactNode; title: string; desc: string }) {
  return (
    <div className="feature-item">
      <span className="feature-icon">{icon}</span>
      <strong>{title}</strong>
      <span>{desc}</span>
    </div>
  );
}

function QueryContent({ text, sources }: { text: string; sources?: Source[] }) {
  const unique = sources?.reduce<Source[]>((acc, cur) => {
    if (!acc.find((s) => s.filename === cur.filename && s.page === cur.page)) acc.push(cur);
    return acc;
  }, []);

  return (
    <>
      <p>{text}</p>
      {unique && unique.length > 0 && (
        <div className="sources-container">
          <span className="sources-title">Sources</span>
          <div className="sources-chips">
            {unique.map((src, i) => (
              <span key={i} className="source-chip" title={src.text}>
                {src.filename} · p.{src.page}
              </span>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

function TypingIndicator() {
  return (
    <div className="message assistant-msg">
      <div className="msg-avatar">AI</div>
      <div className="msg-body">
        <div className="typing-indicator">
          <span /><span /><span />
        </div>
      </div>
    </div>
  );
}
