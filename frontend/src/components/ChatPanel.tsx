/**
 * ChatPanel — the conversation: questions, the sources each answer used,
 * the streamed answer with its actions, and the composer.
 *
 * Conversations are saved on the server. The panel loads a saved chat when
 * `conversationId` changes, and reports back when the first question of a
 * new chat creates one.
 */

import { useState, useRef, useEffect } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import {
  ArrowUp,
  Square,
  ThumbsUp,
  ThumbsDown,
  Copy,
  Check,
  PenLine,
  Download,
  ChevronDown,
  Link2,
  Sparkle,
  Forward,
  Paperclip,
  FileText,
  Upload,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { DocInfo, Message, Source } from '../types';
import * as api from '../api';
import { useI18n } from '../i18n';
import { buildMarkdown, downloadTextFile, exportFileName, printConversation } from '../utils/exportChat';
import { ACCEPTED_EXTENSIONS, pageUnit } from '../utils/format';
import { TYPE_ICONS } from '../utils/icons';
import { getSuggestions } from '../utils/suggestions';
import type { ResponseStyle } from '../utils/styles';
import { useDismiss } from '../hooks/useDismiss';
import { useToast } from '../hooks/useNotifications';

interface ChatPanelProps {
  documents: DocInfo[];
  selectedDocuments: string[];
  /** Search inside the sources carrying this tag (used when no files are selected). */
  activeTag: string | null;
  /** Search inside the sources of this folder (used when no files are selected). */
  activeFolder: string | null;
  responseStyle: ResponseStyle;
  /** Enter sends (Shift+Enter adds a line); when false, Ctrl/⌘+Enter sends. */
  sendWithEnter: boolean;
  showSuggestions: boolean;
  conversationId: string | null;
  conversationTitle: string;
  /** A question asked from elsewhere (e.g. a suggestion in the library panel). */
  askRequest: { id: number; text: string } | null;
  onShareChat: () => void;
  onViewSource: (filename: string, page: number) => void;
  onUploadFiles: (files: FileList | File[]) => void;
  /** A plan limit stopped the question; the message explains it. */
  onUpgradeNeeded: (reason: string) => void;
  /** The first question of a new chat made the server create this conversation. */
  onConversationCreated: (id: string) => void;
  /** Chat list / quota changed (new message saved): refresh them. */
  onActivity: () => void;
}

type StreamEvent = {
  type: string;
  conversation_id?: string;
  message_id?: string;
  sources?: Source[];
  token?: string;
  error?: string;
};

export default function ChatPanel({
  documents,
  selectedDocuments,
  activeTag,
  activeFolder,
  responseStyle,
  sendWithEnter,
  showSuggestions,
  conversationId,
  conversationTitle,
  askRequest,
  onShareChat,
  onViewSource,
  onUploadFiles,
  onUpgradeNeeded,
  onConversationCreated,
  onActivity,
}: ChatPanelProps) {
  const { t } = useI18n();
  const toast = useToast();
  const [messages, setMessages] = useState<Message[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [opening, setOpening] = useState(false);
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Id of a conversation this panel just created itself: its messages are already on screen.
  const createdIdRef = useRef<string | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, loading]);

  // Load a saved chat when the user opens one (or reset on "New chat").
  useEffect(() => {
    if (createdIdRef.current && conversationId === createdIdRef.current) {
      createdIdRef.current = null;
      return;
    }
    abortRef.current?.abort();
    setLoading(false);
    setStreamingId(null);
    if (!conversationId) {
      setMessages([]);
      return;
    }

    let cancelled = false;
    setOpening(true);
    api
      .fetchConversation(conversationId)
      .then(({ messages: saved }) => !cancelled && setMessages(saved))
      .catch((err: unknown) => {
        if (cancelled) return;
        const text = err instanceof Error ? err.message : t('Could not open this chat');
        setMessages([{ id: 'open-error', sender: 'assistant', text: `**${t('Error')}:** ${text}` }]);
      })
      .finally(() => !cancelled && setOpening(false));
    return () => {
      cancelled = true;
    };
    // The chat is reloaded when it changes, not when the interface language does.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  const updateMessage = (id: string, changes: Partial<Message>) =>
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...changes } : m)));

  /** Ask a question and stream the answer. `regenerate` replaces the last exchange. */
  const ask = async (question: string, regenerate = false) => {
    if (loading || opening || !question.trim() || documents.length === 0) return;
    const stamp = Date.now();
    const assistantId = `assistant-${stamp}`;
    const controller = new AbortController();
    abortRef.current = controller;

    setMessages((prev) => [
      ...(regenerate ? prev.slice(0, -2) : prev),
      { id: `user-${stamp}`, sender: 'user', text: question },
      { id: assistantId, sender: 'assistant', text: '', sources: [], question },
    ]);
    setLoading(true);
    setStreamingId(assistantId);

    let answer = '';
    try {
      const response = await api.authFetch('/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question,
          filenames: selectedDocuments,
          tag: selectedDocuments.length === 0 && !activeFolder ? activeTag : null,
          folder: selectedDocuments.length === 0 ? activeFolder : null,
          conversation_id: conversationId,
          regenerate,
          style: responseStyle,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const err = await response.json().catch(() => null);
        throw api.apiError(err, t('Query failed'), response.status);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error(t('No readable stream available from backend'));
      const decoder = new TextDecoder('utf-8');
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
          let event: StreamEvent;
          try {
            event = JSON.parse(trimmed.slice(5).trim());
          } catch {
            console.error('Skipping malformed SSE chunk:', trimmed);
            continue;
          }

          if (event.type === 'error') {
            throw new Error(event.error || t('The model failed to generate a response.'));
          } else if (event.type === 'meta') {
            updateMessage(assistantId, { serverId: event.message_id });
            if (event.conversation_id && event.conversation_id !== conversationId) {
              createdIdRef.current = event.conversation_id;
              onConversationCreated(event.conversation_id);
            }
          } else if (event.type === 'sources') {
            updateMessage(assistantId, { sources: event.sources ?? [] });
          } else if (event.type === 'token') {
            answer += event.token ?? '';
            updateMessage(assistantId, { text: answer });
          }
        }
      }

      if (!answer) {
        updateMessage(assistantId, { text: `_${t('The model returned an empty response. Please try again.')}_` });
      }
    } catch (err) {
      if (controller.signal.aborted) {
        // The user pressed Stop: keep whatever was generated so far.
        if (answer) updateMessage(assistantId, { stopped: true });
        else setMessages((prev) => prev.filter((m) => m.id !== assistantId));
      } else {
        const text = err instanceof Error ? err.message : t('Something went wrong');
        updateMessage(assistantId, { text: `**${t('Error')}:** ${text}` });
        if (err instanceof api.ApiError && err.upgrade) onUpgradeNeeded(err.message);
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setLoading(false);
      setStreamingId(null);
      onActivity();
    }
  };

  // Questions asked from the library panel's suggestions.
  useEffect(() => {
    if (askRequest) ask(askRequest.text);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [askRequest?.id]);

  const submit = (text: string) => {
    const question = text.trim();
    if (!question || loading) return;
    setQuery('');
    ask(question);
  };

  const lastAssistant = [...messages].reverse().find((m) => m.sender === 'assistant');
  const handleRegenerate = () => {
    if (lastAssistant?.question) ask(lastAssistant.question, true);
  };

  const handleFeedback = (message: Message, feedback: 'up' | 'down') => {
    if (message.feedback) return; // already rated
    updateMessage(message.id, { feedback });
    // Fire-and-forget — feedback storage must never disturb the chat.
    api.sendFeedback(message.serverId ?? message.id, feedback, message.question ?? '', message.text).catch(() => {});
  };

  const exportTitle = conversationTitle || messages.find((m) => m.sender === 'user')?.text.slice(0, 60) || t('Conversation');
  const exportMarkdown = () => {
    downloadTextFile(
      exportFileName(exportTitle, 'md'),
      buildMarkdown(exportTitle, messages, selectedDocuments, new Date(), t),
    );
    toast.success(t('Conversation exported as Markdown.'));
  };

  const hasDocs = documents.length > 0;
  const empty = messages.length === 0 && !opening;
  const canRegenerate = !loading && !opening && !!conversationId && !!lastAssistant?.question && !!lastAssistant.text;
  const placeholder = !hasDocs
    ? t('Add a source to start asking')
    : selectedDocuments.length >= 2
      ? t('Ask how these sources compare')
      : empty
        ? t('Ask a question about your sources')
        : t('Ask a follow-up question');

  const composer = (
    <Composer
      value={query}
      onChange={setQuery}
      onSubmit={submit}
      onStop={() => abortRef.current?.abort()}
      onUploadFiles={onUploadFiles}
      sendWithEnter={sendWithEnter}
      loading={loading}
      disabled={!hasDocs || opening}
      placeholder={placeholder}
      large={empty}
    />
  );

  return (
    <main className={`chat ${empty ? 'is-empty' : ''}`}>
      <div className="chat-scroll">
        <div className="chat-column">
          <div className="print-header">
            <h1>{exportTitle}</h1>
            <p>
              DocuQuery, {new Date().toLocaleDateString()}.{' '}
              {selectedDocuments.length ? t('Sources: {list}', { list: selectedDocuments.join(', ') }) : t('All sources')}
            </p>
          </div>

          {empty ? (
            <Welcome
              documents={documents}
              selectedDocuments={selectedDocuments}
              activeTag={activeTag}
              activeFolder={activeFolder}
              showSuggestions={showSuggestions}
              composer={composer}
              onAsk={(q) => ask(q)}
              onUploadFiles={onUploadFiles}
            />
          ) : (
            <>
              {opening && <p className="chat-loading">{t('Opening chat…')}</p>}
              {messages.map((msg) =>
                msg.sender === 'user' ? (
                  <div key={msg.id} className="question">
                    <p className="question-bubble">{msg.text}</p>
                  </div>
                ) : (
                  <Answer
                    key={msg.id}
                    message={msg}
                    documents={documents}
                    streaming={msg.id === streamingId}
                    canRegenerate={canRegenerate && msg.id === lastAssistant?.id}
                    canShare={!!conversationId}
                    onShare={onShareChat}
                    onExportMarkdown={exportMarkdown}
                    onExportPdf={() => printConversation(exportTitle)}
                    onViewSource={onViewSource}
                    onFeedback={handleFeedback}
                    onRegenerate={handleRegenerate}
                  />
                ),
              )}
            </>
          )}
          <div ref={endRef} />
        </div>
      </div>

      {!empty && <div className="composer-dock">{composer}</div>}
    </main>
  );
}

/* ── Composer ──────────────────────────────────────────────────────── */

function Composer({
  value,
  onChange,
  onSubmit,
  onStop,
  onUploadFiles,
  sendWithEnter,
  loading,
  disabled,
  placeholder,
  large,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (v: string) => void;
  onStop: () => void;
  onUploadFiles: (files: FileList | File[]) => void;
  sendWithEnter: boolean;
  loading: boolean;
  disabled: boolean;
  placeholder: string;
  large: boolean;
}) {
  const { t } = useI18n();
  const fileRef = useRef<HTMLInputElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);

  // Grow with the text, up to a limit.
  useEffect(() => {
    const el = areaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [value]);

  const send = (e?: FormEvent) => {
    e?.preventDefault();
    if (!loading) onSubmit(value);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Enter' || e.nativeEvent.isComposing) return;
    // Enter sends and Shift+Enter adds a line; with "Press Enter to send" off, Ctrl/⌘+Enter sends.
    const sends = sendWithEnter ? !e.shiftKey : e.ctrlKey || e.metaKey;
    if (sends) {
      e.preventDefault();
      send();
    }
  };

  return (
    <form id="chat-form" className={`composer ${large ? 'composer-large' : ''}`} onSubmit={send}>
      <button
        type="button"
        className="composer-attach"
        onClick={() => fileRef.current?.click()}
        aria-label={t('Add a file to your library')}
        title={t('Add a file to your library')}
      >
        <Paperclip size={16} />
      </button>
      <input
        ref={fileRef}
        type="file"
        multiple
        accept={ACCEPTED_EXTENSIONS.join(',')}
        style={{ display: 'none' }}
        onChange={(e) => {
          if (e.target.files?.length) onUploadFiles(e.target.files);
          e.target.value = '';
        }}
      />
      <textarea
        ref={areaRef}
        id="query-input"
        rows={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKey}
        placeholder={placeholder}
        maxLength={4000}
        disabled={disabled || loading}
        aria-label={t('Your question')}
      />
      {loading ? (
        <button type="button" id="send-btn" className="send stop" onClick={onStop} aria-label={t('Stop generating')} title={t('Stop')}>
          <Square size={13} fill="currentColor" />
        </button>
      ) : (
        <button type="submit" id="send-btn" className="send" disabled={disabled || !value.trim()} aria-label={t('Ask')} title={t('Ask')}>
          <ArrowUp size={17} />
        </button>
      )}
    </form>
  );
}

/* ── Empty state ───────────────────────────────────────────────────── */

function Welcome({
  documents,
  selectedDocuments,
  activeTag,
  activeFolder,
  showSuggestions,
  composer,
  onAsk,
  onUploadFiles,
}: {
  documents: DocInfo[];
  selectedDocuments: string[];
  activeTag: string | null;
  activeFolder: string | null;
  showSuggestions: boolean;
  composer: React.ReactNode;
  onAsk: (q: string) => void;
  onUploadFiles: (files: FileList | File[]) => void;
}) {
  const { t } = useI18n();
  const fileRef = useRef<HTMLInputElement>(null);
  const single = selectedDocuments.length === 1 ? documents.find((d) => d.filename === selectedDocuments[0]) : undefined;
  const { questions } = getSuggestions(documents, selectedDocuments, activeTag, activeFolder, t);

  if (documents.length === 0) {
    return (
      <section className="welcome">
        <h1 className="welcome-title">{t('Ask questions about your documents')}</h1>
        <p className="welcome-sub">
          {t('Add a PDF, an Office file, a spreadsheet, an image or a web page. Every answer shows the pages it came from.')}
        </p>
        <button className="btn btn-ink btn-lg" onClick={() => fileRef.current?.click()}>
          <Upload size={16} /> {t('Upload your first file')}
        </button>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept={ACCEPTED_EXTENSIONS.join(',')}
          style={{ display: 'none' }}
          onChange={(e) => {
            if (e.target.files?.length) onUploadFiles(e.target.files);
            e.target.value = '';
          }}
        />
        <p className="welcome-hint">{t('You can also drop files, add links or paste text in the library on the right.')}</p>
      </section>
    );
  }

  const heading = single
    ? single.filename
    : selectedDocuments.length >= 2
      ? t('Comparing {count} sources', { count: selectedDocuments.length })
      : activeFolder
        ? t('Searching the folder {name}', { name: activeFolder })
        : activeTag
          ? t('Searching #{name}', { name: activeTag })
          : t('What do you want to know?');
  const sub = single?.summary
    ? single.summary
    : selectedDocuments.length >= 2
      ? selectedDocuments.join(', ')
      : activeFolder
        ? t('Answers come from the sources in this folder, with the pages they cite.')
        : activeTag
          ? t('Answers come from the tagged sources, with the pages they cite.')
          : t('Answers come from your library, with the pages they cite.');

  return (
    <section className="welcome">
      <h1 className="welcome-title">{heading}</h1>
      <p className="welcome-sub">{sub}</p>
      {composer}
      {showSuggestions && questions.length > 0 && (
        <div className="welcome-suggestions">
          {questions.slice(0, 4).map((q) => (
            <button key={q} className="suggestion-chip" onClick={() => onAsk(q)}>
              {q}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

/* ── One answer ────────────────────────────────────────────────────── */

interface SourceGroup {
  filename: string;
  pages: number[];
  excerpt: string;
}

function groupSources(sources: Source[] = []): SourceGroup[] {
  const groups = new Map<string, SourceGroup>();
  for (const s of sources) {
    const group = groups.get(s.filename) ?? { filename: s.filename, pages: [], excerpt: s.text };
    if (!group.pages.includes(s.page)) group.pages.push(s.page);
    groups.set(s.filename, group);
  }
  return [...groups.values()].map((g) => ({ ...g, pages: g.pages.sort((a, b) => a - b) }));
}

function Answer({
  message,
  documents,
  streaming,
  canRegenerate,
  canShare,
  onShare,
  onExportMarkdown,
  onExportPdf,
  onViewSource,
  onFeedback,
  onRegenerate,
}: {
  message: Message;
  documents: DocInfo[];
  streaming: boolean;
  canRegenerate: boolean;
  canShare: boolean;
  onShare: () => void;
  onExportMarkdown: () => void;
  onExportPdf: () => void;
  onViewSource: (filename: string, page: number) => void;
  onFeedback: (message: Message, feedback: 'up' | 'down') => void;
  onRegenerate: () => void;
}) {
  const { t } = useI18n();
  const { text, feedback, stopped } = message;
  const groups = groupSources(message.sources);
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? groups : groups.slice(0, 3);
  const hidden = groups.length - visible.length;
  const done = !!text && !streaming;

  return (
    <article className="answer">
      {groups.length > 0 && (
        <section className="answer-section">
          <h2 className="answer-heading">
            <Link2 size={17} /> {t('Sources')}
          </h2>
          <div className="source-cards">
            {visible.map((g) => {
              const doc = documents.find((d) => d.filename === g.filename);
              const Icon = doc ? TYPE_ICONS[doc.file_type] : FileText;
              const unit = doc ? pageUnit(doc.file_type) : 'page';
              return (
                <button
                  key={g.filename}
                  className="source-card"
                  title={g.excerpt || t('Open in the viewer')}
                  onClick={() => onViewSource(g.filename, g.pages[0])}
                >
                  <span className="source-card-title">{g.filename}</span>
                  <span className="source-card-meta">
                    <Icon size={13} />
                    {unit === 'page' ? t('p.') : unit === 'slide' ? t('slide') : t('section')} {g.pages.join(', ')}
                  </span>
                </button>
              );
            })}
            {hidden > 0 && (
              <button className="source-card source-more" onClick={() => setShowAll(true)}>
                {t('+{count} more', { count: hidden })}
              </button>
            )}
          </div>
        </section>
      )}

      <section className="answer-section">
        <h2 className="answer-heading">
          <Sparkle size={17} className={streaming ? 'spin-slow' : ''} /> {t('Answer')}
        </h2>
        {text ? (
          <div className="markdown-prose">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
          </div>
        ) : streaming ? (
          <div className="answer-skeleton" aria-label={t('Writing the answer')}>
            <span />
            <span />
            <span />
          </div>
        ) : null}
        {stopped && <p className="stopped-note">{t('Generation stopped.')}</p>}
      </section>

      {done && (
        <div className="answer-actions">
          <div className="answer-actions-left">
            {canShare && (
              <button className="btn btn-outline btn-sm" onClick={onShare}>
                <Forward size={14} /> {t('Share')}
              </button>
            )}
            <ExportMenu onMarkdown={onExportMarkdown} onPdf={onExportPdf} />
            {canRegenerate && (
              <button className="btn btn-outline btn-sm" onClick={onRegenerate} aria-label={t('Regenerate answer')}>
                <PenLine size={14} /> {t('Rewrite')}
              </button>
            )}
          </div>
          <div className="answer-actions-right">
            <CopyButton text={text} />
            <button
              className={`icon-btn ${feedback === 'up' ? 'selected' : ''}`}
              onClick={() => onFeedback(message, 'up')}
              disabled={!!feedback}
              aria-label={t('Helpful')}
              title={t('Helpful')}
            >
              <ThumbsUp size={14} />
            </button>
            <button
              className={`icon-btn ${feedback === 'down' ? 'selected' : ''}`}
              onClick={() => onFeedback(message, 'down')}
              disabled={!!feedback}
              aria-label={t('Not helpful')}
              title={t('Not helpful')}
            >
              <ThumbsDown size={14} />
            </button>
          </div>
          {feedback && <p className="feedback-thanks">{t('Thanks, your feedback was saved.')}</p>}
        </div>
      )}
    </article>
  );
}

function ExportMenu({ onMarkdown, onPdf }: { onMarkdown: () => void; onPdf: () => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const ref = useDismiss<HTMLDivElement>(open, () => setOpen(false));
  return (
    <div className="menu-anchor export-menu" ref={ref}>
      <button
        className="btn btn-outline btn-sm export-btn"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={t('Export this conversation')}
      >
        <Download size={14} /> {t('Export')} <ChevronDown size={12} />
      </button>
      {open && (
        <div className="popover menu menu-up" role="menu">
          <button
            className="menu-item"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onMarkdown();
            }}
          >
            Markdown (.md)
          </button>
          <button
            className="menu-item"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onPdf();
            }}
          >
            {t('PDF (print…)')}
          </button>
        </div>
      )}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const { t } = useI18n();
  const toast = useToast();
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard API unavailable (insecure context): fall back to a temporary textarea.
      const area = document.createElement('textarea');
      area.value = text;
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      document.execCommand('copy');
      area.remove();
    }
    setCopied(true);
    toast.success(t('Answer copied to the clipboard.'));
    setTimeout(() => setCopied(false), 1600);
  };

  return (
    <button className="btn btn-outline btn-sm" onClick={copy} aria-label={t('Copy answer')}>
      {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? t('Copied') : t('Copy')}
    </button>
  );
}
