/**
 * SourceViewer — modal that shows the cited page of a source.
 *
 *  PDF            → the original file in the browser's PDF viewer, at the page
 *  Image          → the image, plus the text that was read from it
 *  DOCX/TXT/MD/URL → the extracted text, scrolled to the cited section
 *
 * The files are fetched with the session token (an <iframe src> can't send
 * an Authorization header) and shown from a temporary blob URL.
 */

import { useEffect, useRef, useState } from 'react';
import { X, ExternalLink, FileText, Download, Loader2, AlertCircle } from 'lucide-react';
import * as api from '../api';
import { useI18n } from '../i18n';
import type { DocInfo } from '../types';
import { fileTypeLabel, pageUnit } from '../utils/format';
import { useToast } from '../hooks/useNotifications';

interface SourceViewerProps {
  filename: string;
  page: number;
  doc: DocInfo | undefined;
  onClose: () => void;
}

interface Loaded {
  blobUrl?: string;
  pages?: string[];
}

export default function SourceViewer({ filename, page, doc, onClose }: SourceViewerProps) {
  const { t } = useI18n();
  const toast = useToast();
  const fileType = doc?.file_type ?? 'pdf';
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState('');
  const activeRef = useRef<HTMLElement | null>(null);

  // Load once per file (changing only the page re-uses the loaded data).
  useEffect(() => {
    let cancelled = false;
    let createdUrl: string | undefined;
    setData(null);
    setError('');

    (async () => {
      try {
        if (fileType === 'pdf') {
          createdUrl = URL.createObjectURL(await api.fetchDocumentBlob(filename));
          if (!cancelled) setData({ blobUrl: createdUrl });
        } else if (fileType === 'image') {
          createdUrl = URL.createObjectURL(await api.fetchDocumentBlob(filename));
          const pages = await api.fetchDocumentPages(filename);
          if (!cancelled) setData({ blobUrl: createdUrl, pages });
        } else {
          const pages = await api.fetchDocumentPages(filename);
          if (!cancelled) setData({ pages });
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : t('Could not load this source'));
      }
    })();

    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filename, fileType]);

  // Bring the cited section into view for text sources.
  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }, [data, page]);

  // Close with the Escape key.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const isPdf = fileType === 'pdf';
  const pdfSrc = data?.blobUrl ? `${data.blobUrl}#page=${page}` : undefined;
  const unit = pageUnit(fileType);
  const unitLabel = unit === 'page' ? t('Page') : unit === 'slide' ? t('Slide') : t('Section');
  const label = `${unitLabel} ${page}`;

  const download = async () => {
    try {
      const url = URL.createObjectURL(await api.fetchDocumentBlob(filename));
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('Download failed'));
    }
  };

  return (
    <div className="pdf-modal-overlay" onClick={onClose}>
      <div className="pdf-modal-container" onClick={(e) => e.stopPropagation()}>
        <header className="pdf-modal-header">
          <div className="pdf-modal-title">
            <FileText size={18} className="pdf-icon" />
            <div className="pdf-meta">
              <h3>{filename}</h3>
              <span className="pdf-page-tag">
                {fileTypeLabel(fileType)} · {label}
              </span>
            </div>
          </div>
          <div className="pdf-modal-controls">
            {doc?.source_url && (
              <a
                href={doc.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="pdf-control-btn"
                title={t('Open the original web page')}
              >
                <ExternalLink size={14} />
                <span>{t('Original')}</span>
              </a>
            )}
            {isPdf && pdfSrc && (
              <a href={pdfSrc} target="_blank" rel="noopener noreferrer" className="pdf-control-btn" title={t('Open in new tab')}>
                <ExternalLink size={14} />
                <span>{t('Full screen')}</span>
              </a>
            )}
            {fileType !== 'url' && fileType !== 'pdf' && (
              <button className="pdf-control-btn" onClick={download} title={t('Download the original file')}>
                <Download size={14} />
                <span>{t('Download')}</span>
              </button>
            )}
            <button className="pdf-control-btn close-btn" onClick={onClose} title={t('Close (Esc)')}>
              <X size={16} />
            </button>
          </div>
        </header>

        <div className="pdf-modal-body">
          {error ? (
            <div className="viewer-state error">
              <AlertCircle size={20} />
              <p>{error}</p>
            </div>
          ) : !data ? (
            <div className="viewer-state">
              <Loader2 size={20} className="spin" />
              <p>{t('Loading…')}</p>
            </div>
          ) : isPdf ? (
            <iframe
              src={pdfSrc}
              title={filename}
              className="pdf-modal-iframe"
              key={`${filename}-${page}`} // Force reload on page changes
            />
          ) : (
            <div className="text-viewer">
              {fileType === 'image' && data.blobUrl && (
                <img src={data.blobUrl} alt={filename} className="viewer-image" />
              )}
              {(data.pages ?? []).map((text, i) => {
                const active = i + 1 === page;
                return (
                  <section
                    key={i}
                    className={`text-page ${active ? 'active' : ''}`}
                    ref={active ? (el) => void (activeRef.current = el) : undefined}
                  >
                    {(data.pages?.length ?? 0) > 1 && <span className="text-page-label">{unitLabel} {i + 1}</span>}
                    <p>{text}</p>
                  </section>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
