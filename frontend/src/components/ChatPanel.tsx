/**
 * ChatPanel component — header scope bar, message feed, and input area.
 */

import { useState, useRef, useEffect } from 'react';
import type { FormEvent } from 'react';
import { Send, Zap, BookOpen, Database, Menu, ThumbsUp, ThumbsDown } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Message, Source } from '../types';
import { API_BASE_URL, sendFeedback } from '../api';

interface ChatPanelProps {
  documents: string[];
  selectedDocument: string | null;
  onClearScope: () => void;
  onViewSource: (filename: string, page: number) => void;
  onOpenSidebar: () => void;
}

export default function ChatPanel({
  documents,
  selectedDocument,
  onClearScope,
  onViewSource,
  onOpenSidebar,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'welcome',
      sender: 'system',
      text: 'Upload your PDF sources on the left, then ask natural language questions. Answers are generated from your documents with page-level citations.',
    },
  ]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const question = query.trim();
    if (!question || loading) return;

    // Conversation history (prior turns only) for backend query reformulation.
    const history = messages
      .filter((m) => m.sender !== 'system' && m.text)
      .slice(-6)
      .map((m) => ({ role: m.sender === 'user' ? 'user' : 'assistant', content: m.text }));

    setQuery('');
    setMessages((prev) => [...prev, { id: `user-${Date.now()}`, sender: 'user', text: question }]);
    setLoading(true);

    const assistantMessageId = `assistant-${Date.now()}`;
    setStreamingId(assistantMessageId);
    setMessages((prev) => [
      ...prev,
      { id: assistantMessageId, sender: 'assistant', text: '', sources: [], question },
    ]);

    try {
      const response = await fetch(`${API_BASE_URL}/api/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, filename: selectedDocument, history }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Query failed');
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder('utf-8');
      if (!reader) throw new Error('No readable stream available from backend');

      let accumulatedAnswer = '';
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');

        // Retain the final, potentially incomplete chunk in the buffer
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;

          // Parse in isolation so genuine stream errors below are NOT
          // swallowed by the JSON-parse catch.
          let parsed: { type: string; sources?: Source[]; token?: string; error?: string };
          try {
            parsed = JSON.parse(trimmed.slice(5).trim());
          } catch {
            console.error('Skipping malformed SSE chunk:', trimmed);
            continue;
          }

          if (parsed.type === 'error') {
            throw new Error(parsed.error || 'The model failed to generate a response.');
          } else if (parsed.type === 'sources') {
            const collectedSources = parsed.sources ?? [];
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantMessageId ? { ...msg, sources: collectedSources } : msg
              )
            );
          } else if (parsed.type === 'token') {
            accumulatedAnswer += parsed.token ?? '';
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantMessageId ? { ...msg, text: accumulatedAnswer } : msg
              )
            );
          }
        }
      }

      if (!accumulatedAnswer) {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMessageId
              ? { ...msg, text: '_The model returned an empty response. Please try again._' }
              : msg
          )
        );
      }
    } catch (err: any) {
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId ? { ...msg, text: `**Error:** ${err.message}` } : msg
        )
      );
    } finally {
      setLoading(false);
      setStreamingId(null);
    }
  };

  const handleFeedback = (message: Message, feedback: 'up' | 'down') => {
    if (message.feedback) return; // already rated
    setMessages((prev) =>
      prev.map((msg) => (msg.id === message.id ? { ...msg, feedback } : msg))
    );
    // Fire-and-forget — feedback storage must never disturb the chat.
    sendFeedback(message.id, feedback, message.question ?? '', message.text).catch(() => {});
  };

  const hasDocs = documents.length > 0;

  return (
    <main className="chat-panel">
      {/* Scope header */}
      <header className="chat-header">
        <button
          className="menu-btn"
          onClick={onOpenSidebar}
          aria-label="Open sources panel"
          title="Sources"
        >
          <Menu size={19} />
        </button>
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
          <MessageBubble
            key={msg.id}
            message={msg}
            streaming={msg.id === streamingId}
            onViewSource={onViewSource}
            onFeedback={handleFeedback}
          />
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

function MessageBubble({
  message,
  streaming,
  onViewSource,
  onFeedback,
}: {
  message: Message;
  streaming: boolean;
  onViewSource: (filename: string, page: number) => void;
  onFeedback: (message: Message, feedback: 'up' | 'down') => void;
}) {
  const { sender, text } = message;
  const cls = sender === 'user' ? 'user-msg' : sender === 'system' ? 'system-msg' : 'assistant-msg';
  const avatar = sender === 'user' ? 'You' : sender === 'system' ? '✦' : 'AI';

  return (
    <div className={`message ${cls}`}>
      <div className="msg-avatar">{avatar}</div>
      <div className="msg-body">
        {sender === 'system' ? (
          <WelcomeContent text={text} />
        ) : (
          <QueryContent
            message={message}
            showFeedback={sender === 'assistant' && !!text && !streaming}
            onViewSource={onViewSource}
            onFeedback={onFeedback}
          />
        )}
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

function QueryContent({
  message,
  showFeedback,
  onViewSource,
  onFeedback,
}: {
  message: Message;
  showFeedback: boolean;
  onViewSource: (filename: string, page: number) => void;
  onFeedback: (message: Message, feedback: 'up' | 'down') => void;
}) {
  const { text, sources, feedback } = message;
  const unique = sources?.reduce<Source[]>((acc, cur) => {
    if (!acc.find((s) => s.filename === cur.filename && s.page === cur.page)) acc.push(cur);
    return acc;
  }, []);

  return (
    <>
      <div className="markdown-prose">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      </div>
      {unique && unique.length > 0 && (
        <div className="sources-container">
          <span className="sources-title">Sources</span>
          <div className="sources-chips">
            {unique.map((src, i) => (
              <button
                key={i}
                className="source-chip"
                title={src.text || 'Open page in viewer'}
                onClick={() => onViewSource(src.filename, src.page)}
              >
                {src.filename} · p.{src.page}
              </button>
            ))}
          </div>
        </div>
      )}
      {showFeedback && (
        <div className="feedback-row">
          <button
            className={`feedback-btn ${feedback === 'up' ? 'selected' : ''}`}
            onClick={() => onFeedback(message, 'up')}
            disabled={!!feedback}
            aria-label="Helpful"
            title="Helpful"
          >
            <ThumbsUp size={13} />
          </button>
          <button
            className={`feedback-btn ${feedback === 'down' ? 'selected' : ''}`}
            onClick={() => onFeedback(message, 'down')}
            disabled={!!feedback}
            aria-label="Not helpful"
            title="Not helpful"
          >
            <ThumbsDown size={13} />
          </button>
          {feedback && <span className="feedback-thanks">Thanks for the feedback</span>}
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
