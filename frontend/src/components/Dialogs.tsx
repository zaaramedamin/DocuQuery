/**
 * Modal dialogs: share a chat / source, paste text as a source, confirm a page
 * sent from the browser button, and put sources in a folder.
 */

import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Copy, Check, Link2, Loader2, Share2, AlertCircle, Bookmark, FolderPlus } from 'lucide-react';
import * as api from '../api';
import { useI18n } from '../i18n';
import type { ImportPayload, ShareInfo, ShareKind } from '../types';
import { buildBookmarklet, shareUrl } from '../utils/route';
import Modal from './Modal';
import { useToast } from '../hooks/useNotifications';

/* ── Share ─────────────────────────────────────────────────────────── */

export function ShareDialog({
  kind,
  refName,
  label,
  onClose,
}: {
  kind: ShareKind;
  /** Conversation id, or the document's file name. */
  refName: string;
  /** What is being shared, for display. */
  label: string;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [share, setShare] = useState<ShareInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .listShares()
      .then((all) => !cancelled && setShare(all.find((s) => s.kind === kind && s.ref === refName) ?? null))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : t('Could not load sharing')))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, refName]);

  const create = async () => {
    setBusy(true);
    setError('');
    try {
      setShare(await api.createShare(kind, refName));
      toast.success(t('Share link created.'));
    } catch (e) {
      setError(e instanceof Error ? e.message : t('Could not create the link'));
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    if (!share) return;
    setBusy(true);
    setError('');
    try {
      await api.revokeShare(share.id);
      setShare(null);
      toast.info(t('Sharing is off. The old link no longer works.'));
    } catch (e) {
      setError(e instanceof Error ? e.message : t('Could not turn the link off'));
    } finally {
      setBusy(false);
    }
  };

  const link = share ? shareUrl(share.token) : '';
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
    } catch {
      inputRef.current?.select();
      document.execCommand('copy');
    }
    setCopied(true);
    toast.success(t('Link copied to the clipboard.'));
    setTimeout(() => setCopied(false), 1600);
  };

  return (
    <Modal
      title={kind === 'conversation' ? t('Share this chat') : t('Share this source')}
      icon={<Share2 size={16} />}
      onClose={onClose}
    >
      <p className="modal-subject" title={label}>
        {label}
      </p>
      <p className="modal-note">
        {kind === 'conversation'
          ? t(
              'Anyone with the link can read this conversation, without signing in. They see your questions and the answers, and which pages were cited — not your documents.',
            )
          : t(
              'Anyone with the link who signs in can add their own copy of this source to their library. Your original and your chats are not shared.',
            )}
      </p>

      {error && (
        <p className="auth-message error" role="alert">
          <AlertCircle size={15} /> {error}
        </p>
      )}

      {loading ? (
        <p className="modal-note">
          <Loader2 size={14} className="spin" /> {t('Loading…')}
        </p>
      ) : share ? (
        <>
          <div className="share-link">
            <Link2 size={14} />
            <input ref={inputRef} readOnly value={link} onFocus={(e) => e.target.select()} aria-label={t('Share link')} />
            <button onClick={copy}>
              {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? t('Copied') : t('Copy')}
            </button>
          </div>
          <button className="btn btn-danger" onClick={stop} disabled={busy}>
            {t('Stop sharing')}
          </button>
          <p className="modal-note small">
            {t('Turning sharing off breaks the link immediately. Sharing again makes a new link.')}
          </p>
        </>
      ) : (
        <button className="btn btn-ink" onClick={create} disabled={busy}>
          {busy ? <Loader2 size={15} className="spin" /> : <Link2 size={15} />} {t('Create link')}
        </button>
      )}
    </Modal>
  );
}

/* ── Paste text ────────────────────────────────────────────────────── */

const MIN_TEXT = 20;

export function PasteTextDialog({
  onSubmit,
  onClose,
}: {
  onSubmit: (payload: Partial<ImportPayload> & { text: string }) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [title, setTitle] = useState('');
  const [link, setLink] = useState('');
  const [text, setText] = useState('');
  const bookmarkRef = useRef<HTMLAnchorElement>(null);

  // React refuses to render "javascript:" links, so the browser button's href is set directly.
  useEffect(() => {
    bookmarkRef.current?.setAttribute('href', buildBookmarklet(window.location.origin));
  }, []);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim().length < MIN_TEXT) return;
    onSubmit({ title: title.trim(), url: link.trim(), text });
    onClose();
  };

  return (
    <Modal title={t('Paste text as a source')} icon={<Copy size={16} />} onClose={onClose}>
      <p className="modal-note">
        {t(
          'Some sites refuse automated readers or only show their content to a real browser. Open the page yourself, copy the text you can see, and paste it here.',
        )}
      </p>
      <form className="modal-form" onSubmit={submit}>
        <label>
          <span>{t('Title (optional)')}</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} placeholder={t('e.g. Article name')} />
        </label>
        <label>
          <span>{t('Link to the page (optional)')}</span>
          <input value={link} onChange={(e) => setLink(e.target.value)} maxLength={2000} placeholder="https://…" inputMode="url" />
        </label>
        <label>
          <span>{t('Text')}</span>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={8}
            placeholder={t('Paste the article or page text here…')}
            autoFocus
          />
        </label>
        <button className="btn btn-ink" type="submit" disabled={text.trim().length < MIN_TEXT}>
          {t('Add as source')}
        </button>
      </form>

      <div className="bookmarklet-box">
        <Bookmark size={15} />
        <div>
          <strong>{t('One-click version')}</strong>
          <p>
            {t(
              "Drag this button to your bookmarks bar. On any page (even paywalled or login-only ones you can see), click it to send that page's text here — you'll be asked to confirm.",
            )}
          </p>
          <a ref={bookmarkRef} className="bookmarklet-link" onClick={(e) => e.preventDefault()} draggable>
            {t('Add to DocuQuery')}
          </a>
        </div>
      </div>
    </Modal>
  );
}

/* ── Confirm a page sent from the browser button ──────────────────── */

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
}

export function ImportDialog({
  payload,
  onConfirm,
  onCancel,
}: {
  payload: ImportPayload;
  onConfirm: (payload: ImportPayload) => void;
  onCancel: () => void;
}) {
  const { t, tn } = useI18n();
  const [title, setTitle] = useState(payload.title);
  const words = payload.text.trim().split(/\s+/).length;
  const host = hostOf(payload.url);

  return (
    <Modal title={t('Add this page to your library?')} icon={<Bookmark size={16} />} onClose={onCancel}>
      <p className="modal-note">
        {host
          ? t('A page you were viewing on {host} was sent to DocuQuery. Only add it if you started this yourself.', { host })
          : t('A page you were viewing was sent to DocuQuery. Only add it if you started this yourself.')}
      </p>
      <label className="modal-form">
        <span className="field-label">{t('Title')}</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
      </label>
      <p className="import-preview">
        <strong>{tn('{count} word', '{count} words', words, { count: words.toLocaleString() })}</strong> ·{' '}
        {t('starts with: “{text}”', {
          text: payload.text.trim().slice(0, 220) + (payload.text.trim().length > 220 ? '…' : ''),
        })}
      </p>
      <div className="modal-actions">
        <button className="btn btn-outline" onClick={onCancel}>
          {t('Cancel')}
        </button>
        <button className="btn btn-ink" onClick={() => onConfirm({ ...payload, title: title.trim() })}>
          {t('Add to my library')}
        </button>
      </div>
    </Modal>
  );
}

/* ── Put sources in a folder ──────────────────────────────────────── */

export function FolderDialog({
  filenames,
  folders,
  anyInFolder,
  onSubmit,
  onClose,
}: {
  /** The sources being moved. */
  filenames: string[];
  /** Names of the folders that already exist. */
  folders: string[];
  /** At least one of the sources is in a folder now (so "Remove from folder" makes sense). */
  anyInFolder: boolean;
  /** Move the sources into `folder`, or out of any folder with `null`. */
  onSubmit: (folder: string | null) => Promise<void>;
  onClose: () => void;
}) {
  const { t, tn } = useI18n();
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const typed = name.trim();
  const existing = folders.find((f) => f.toLowerCase() === typed.toLowerCase());

  const run = async (folder: string | null) => {
    setBusy(true);
    setError('');
    try {
      await onSubmit(folder);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('Could not move the sources'));
      setBusy(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (typed && !busy) run(typed);
  };

  return (
    <Modal title={t('Move to a folder')} icon={<FolderPlus size={16} />} onClose={onClose}>
      <p className="modal-subject">{tn('{count} source selected', '{count} sources selected', filenames.length)}</p>
      <ul className="folder-files">
        {filenames.slice(0, 4).map((f) => (
          <li key={f} title={f}>
            {f}
          </li>
        ))}
        {filenames.length > 4 && <li className="more">{t('and {count} more', { count: filenames.length - 4 })}</li>}
      </ul>

      <form className="modal-form" onSubmit={submit}>
        <label>
          <span>{t('Folder name')}</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={60}
            placeholder={t('e.g. Contracts 2026')}
            autoFocus
            aria-label={t('Folder name')}
          />
        </label>

        {folders.length > 0 && (
          <div className="folder-picker">
            <span className="field-label">{t('Or pick an existing folder')}</span>
            <div className="folder-chips">
              {folders.map((f) => (
                <button
                  type="button"
                  key={f}
                  className={`tag-chip ${existing === f ? 'active' : ''}`}
                  onClick={() => setName(f)}
                >
                  {f}
                </button>
              ))}
            </div>
          </div>
        )}

        {error && (
          <p className="auth-message error" role="alert">
            <AlertCircle size={15} /> {error}
          </p>
        )}

        <div className="modal-actions spread">
          {anyInFolder ? (
            <button type="button" className="btn btn-outline" onClick={() => run(null)} disabled={busy}>
              {t('Remove from folder')}
            </button>
          ) : (
            <span />
          )}
          <span className="modal-actions-right">
            <button type="button" className="btn btn-outline" onClick={onClose}>
              {t('Cancel')}
            </button>
            <button type="submit" className="btn btn-ink" disabled={!typed || busy}>
              {busy ? <Loader2 size={15} className="spin" /> : null}
              {existing ? t('Move to folder') : t('Create folder')}
            </button>
          </span>
        </div>
      </form>
    </Modal>
  );
}
