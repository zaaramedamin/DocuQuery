import { X, ExternalLink, FileText } from 'lucide-react';
import { API_BASE_URL } from '../api';

interface PdfViewerProps {
  filename: string;
  page: number;
  onClose: () => void;
}

export default function PdfViewer({ filename, page, onClose }: PdfViewerProps) {
  const pdfUrl = `${API_BASE_URL}/api/documents/file/${encodeURIComponent(filename)}#page=${page}`;

  return (
    <div className="pdf-modal-overlay" onClick={onClose}>
      <div className="pdf-modal-container" onClick={(e) => e.stopPropagation()}>
        <header className="pdf-modal-header">
          <div className="pdf-modal-title">
            <FileText size={18} className="pdf-icon" />
            <div className="pdf-meta">
              <h3>{filename}</h3>
              <span className="pdf-page-tag">Page {page}</span>
            </div>
          </div>
          <div className="pdf-modal-controls">
            <a
              href={pdfUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="pdf-control-btn"
              title="Open in new tab"
            >
              <ExternalLink size={14} />
              <span>Full Screen</span>
            </a>
            <button className="pdf-control-btn close-btn" onClick={onClose} title="Close Document">
              <X size={16} />
            </button>
          </div>
        </header>
        <div className="pdf-modal-body">
          <iframe
            src={pdfUrl}
            title={filename}
            className="pdf-modal-iframe"
            key={`${filename}-${page}`} // Force reload on page changes
          />
        </div>
      </div>
    </div>
  );
}
