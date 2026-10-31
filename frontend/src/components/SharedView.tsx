/**
 * The page behind a share link (#/share/<token>).
 *
 *  Chat   → a read-only transcript, visible to anyone (no sign-in).
 *  Source → a preview and an "Add to my library" button for signed-in users.
 */

import { useEffect, useState } from 'react';
import { Loader2, AlertCircle, Link2, Sparkle, Check, FileText } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import * as api from '../api';
import { useI18n } from '../i18n';
import type { SharedView as SharedData } from '../types';
import { fileTypeLabel, formatBytes, pageCountLabel } from '../utils/format';
import { TYPE_ICONS } from '../utils/icons';
import AuthScreen from './AuthScreen';

export default function SharedView({
  token,
  signedIn,
  onAdded,
  onExit,
}: {
  token: string;
  signedIn: boolean;
  /** A source was added to the library (the app then opens it). */
  onAdded: (filename: string) => void;
  /** Leave the shared page and go to the normal app. */
  onExit: () => void;
}) {
  const { t, tn } = useI18n();
  const [data, setData] = useState<SharedData | null>(null);
  const [error, setError] = useState('');
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState('');

  useEffect(() => {
    let cancelled = false;
    api
      .getShared(token)
      .then((d) => !cancelled && setData(d))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : t('This link is not available')));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const add = async () => {
    setAdding(true);
    setAddError('');
    try {
      const doc = await api.acceptShared(token);
      onAdded(doc.filename);
    } catch (e) {
      setAddError(e instanceof Error ? e.message : t('Could not add this source'));
      setAdding(false);
    }
  };

  return (
    <div className="shared-page">
      <header className="shared-header">
        <a className="shared-brand" href="#" onClick={(e) => (e.preventDefault(), onExit())}>
          <img src="/logo.svg?v=2" alt="" />
          <span>DocuQuery</span>
        </a>
        <button className="btn btn-outline" onClick={onExit}>
          {signedIn ? t('Back to my library') : t('Open DocuQuery')}
        </button>
      </header>

      <main className="shared-main">
        {error ? (
          <div className="state-message error">
            <AlertCircle size={22} />
            <p>{error}</p>
          </div>
        ) : !data ? (
          <div className="state-message">
            <Loader2 size={22} className="spin" />
            <p>{t('Loading…')}</p>
          </div>
        ) : data.kind === 'conversation' ? (
          <>
            <div className="shared-title">
              <h1>{data.title}</h1>
              <p>{t("A conversation shared with you. It's read-only.")}</p>
            </div>
            <div className="shared-messages">
              {data.messages.map((m, i) =>
                m.role === 'user' ? (
                  <div key={i} className="question">
                    <p className="question-bubble">{m.content}</p>
                  </div>
                ) : (
                  <article key={i} className="answer">
                    {m.sources.length > 0 && (
                      <section className="answer-section">
                        <h2 className="answer-heading">
                          <Link2 size={17} /> {t('Sources')}
                        </h2>
                        <div className="source-cards">
                          {[...new Map(m.sources.map((s) => [s.filename, s])).keys()].map((name) => (
                            <span key={name} className="source-card static">
                              <span className="source-card-title">{name}</span>
                              <span className="source-card-meta">
                                <FileText size={13} /> {t('p.')} {[...new Set(m.sources.filter((s) => s.filename === name).map((s) => s.page))].sort((a, b) => a - b).join(', ')}
                              </span>
                            </span>
                          ))}
                        </div>
                      </section>
                    )}
                    <section className="answer-section">
                      <h2 className="answer-heading">
                        <Sparkle size={17} /> {t('Answer')}
                      </h2>
                      <div className="markdown-prose">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                      </div>
                    </section>
                  </article>
                ),
              )}
            </div>
          </>
        ) : (
          <div className="shared-doc">
            <div className="shared-doc-card">
              <span className="doc-icon large">
                {(() => {
                  const Icon = TYPE_ICONS[data.file_type] ?? FileText;
                  return <Icon size={20} />;
                })()}
              </span>
              <div>
                <h1>{data.filename}</h1>
                <p className="shared-doc-meta">
                  {fileTypeLabel(data.file_type)}, {pageCountLabel(data.file_type, data.page_count, tn)}, {formatBytes(data.size_bytes)}
                </p>
              </div>
            </div>
            {data.summary && <p className="shared-summary">{data.summary}</p>}

            {addError && (
              <p className="auth-message error" role="alert">
                <AlertCircle size={15} /> {addError}
              </p>
            )}

            {signedIn ? (
              <button className="btn btn-ink btn-lg" onClick={add} disabled={adding}>
                {adding ? <Loader2 size={15} className="spin" /> : <Check size={15} />} {t('Add to my library')}
              </button>
            ) : (
              <>
                <p className="shared-note">{t('Sign in or create a free account to add your own copy of this source.')}</p>
                <AuthScreen embedded />
              </>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
