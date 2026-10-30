/**
 * HistoryPanel — the flyout next to the rail with every saved chat and a
 * search across their titles and messages.
 */

import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { Search, X, Loader2, Pencil, Trash2, Plus, MessageCircle } from 'lucide-react';
import * as api from '../api';
import { useI18n } from '../i18n';
import type { ConversationInfo, SearchResult } from '../types';
import { plainText, splitHighlight, timeAgo } from '../utils/format';
import { useConfirm, useToast } from '../hooks/useNotifications';

interface HistoryPanelProps {
  conversations: ConversationInfo[];
  activeId: string | null;
  focusSearch: boolean;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onClose: () => void;
}

export default function HistoryPanel({
  conversations,
  activeId,
  focusSearch,
  onSelect,
  onNewChat,
  onRename,
  onDelete,
  onClose,
}: HistoryPanelProps) {
  const { t } = useI18n();
  const toast = useToast();
  const confirm = useConfirm();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [search, setSearch] = useState('');
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);

  const term = search.trim();
  const isSearching = term.length >= 2;

  useEffect(() => {
    if (focusSearch) searchRef.current?.focus();
  }, [focusSearch]);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => e.key === 'Escape' && !editingId && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, editingId]);

  // Debounced search across every chat's title and messages.
  useEffect(() => {
    if (!isSearching) {
      setResults(null);
      setSearchError('');
      return;
    }
    let cancelled = false;
    setSearching(true);
    const timer = setTimeout(() => {
      api
        .searchConversations(term)
        .then((found) => {
          if (!cancelled) {
            setResults(found);
            setSearchError('');
          }
        })
        .catch((e: unknown) => !cancelled && setSearchError(e instanceof Error ? e.message : t('Search failed')))
        .finally(() => !cancelled && setSearching(false));
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [term, isSearching]);

  const commit = async () => {
    const id = editingId;
    const title = draft.trim();
    setEditingId(null);
    if (id && title) {
      try {
        await onRename(id, title);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t('Could not rename the chat'));
      }
    }
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') commit();
    if (e.key === 'Escape') setEditingId(null);
  };

  const remove = async (c: ConversationInfo) => {
    const ok = await confirm({
      title: t('Delete this chat?'),
      message: t('"{title}" will be deleted, along with any link you shared to it.', { title: c.title }),
      confirmLabel: t('Delete'),
      danger: true,
    });
    if (!ok) return;
    try {
      await onDelete(c.id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('Could not delete the chat'));
    }
  };

  return (
    <>
      <div className="flyout-backdrop" onClick={onClose} />
      <aside className="flyout history" aria-label={t('Chat history')}>
        <header className="flyout-header">
          <h2>{t('Chats')}</h2>
          <button className="icon-btn" onClick={onClose} aria-label={t('Close chat history')}>
            <X size={16} />
          </button>
        </header>

        <div className="flyout-tools">
          <label className="search-field">
            <Search size={15} />
            <input
              ref={searchRef}
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('Search all chats')}
              aria-label={t('Search chats')}
              maxLength={100}
            />
            {searching && <Loader2 size={14} className="spin" />}
            {search && !searching && (
              <button type="button" onClick={() => setSearch('')} aria-label={t('Clear search')}>
                <X size={14} />
              </button>
            )}
          </label>
          <button className="btn btn-outline btn-block new-chat-btn" onClick={onNewChat}>
            <Plus size={15} /> {t('New chat')}
          </button>
        </div>

        <ul className="history-list">
          {isSearching ? (
            searchError ? (
              <li className="empty-note">{searchError}</li>
            ) : results && results.length === 0 ? (
              <li className="empty-note">{t('No chats mention “{term}”.', { term })}</li>
            ) : (
              (results ?? []).map((r) => (
                <li key={r.id}>
                  <button
                    className={`history-item result ${activeId === r.id ? 'active' : ''}`}
                    onClick={() => onSelect(r.id)}
                  >
                    <span className="history-title">
                      <Highlighted text={r.title} query={term} />
                    </span>
                    {r.snippet && (
                      <span className="history-snippet">
                        <Highlighted text={plainText(r.snippet)} query={term} />
                      </span>
                    )}
                    <span className="history-time">{timeAgo(r.updated_at, Date.now(), t)}</span>
                  </button>
                </li>
              ))
            )
          ) : conversations.length === 0 ? (
            <li className="empty-note">
              <MessageCircle size={18} />
              {t('Your chats appear here after you ask your first question.')}
            </li>
          ) : (
            conversations.map((c) => (
              <li key={c.id} className={`history-row ${activeId === c.id ? 'active' : ''}`}>
                {editingId === c.id ? (
                  <input
                    className="rename-input"
                    value={draft}
                    autoFocus
                    maxLength={120}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={onKey}
                    onBlur={commit}
                    aria-label={t('Chat title')}
                  />
                ) : (
                  <>
                    <button className="history-item" onClick={() => onSelect(c.id)}>
                      <span className="history-title">{c.title}</span>
                      <span className="history-time">{timeAgo(c.updated_at, Date.now(), t)}</span>
                    </button>
                    <div className="row-actions">
                      <button
                        className="icon-btn"
                        onClick={() => {
                          setEditingId(c.id);
                          setDraft(c.title);
                        }}
                        title={t('Rename')}
                        aria-label={t('Rename {name}', { name: c.title })}
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        className="icon-btn danger"
                        onClick={() => remove(c)}
                        title={t('Delete chat')}
                        aria-label={t('Delete {name}', { name: c.title })}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </>
                )}
              </li>
            ))
          )}
        </ul>
      </aside>
    </>
  );
}

function Highlighted({ text, query }: { text: string; query: string }) {
  return (
    <>
      {splitHighlight(text, query).map((part, i) =>
        part.match ? <mark key={i}>{part.text}</mark> : <span key={i}>{part.text}</span>,
      )}
    </>
  );
}
