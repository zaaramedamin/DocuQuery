/**
 * Sidebar component — brand header, connection status, file upload zone, and document library.
 */

import { useRef, useState } from 'react';
import type { DragEvent, FormEvent } from 'react';
import { UploadCloud, Trash2, FileText, X } from 'lucide-react';
import * as api from '../api';

interface SidebarProps {
  documents: string[];
  selectedDocument: string | null;
  dbOnline: boolean;
  dbMessage: string;
  open: boolean;
  onClose: () => void;
  onDocumentsChange: () => void;
  onSelectDocument: (filename: string | null) => void;
}

export default function Sidebar({
  documents,
  selectedDocument,
  dbOnline,
  dbMessage,
  open,
  onClose,
  onDocumentsChange,
  onSelectDocument,
}: SidebarProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState('');
  const [uploadType, setUploadType] = useState<'success' | 'error' | 'loading' | ''>('');
  const [uploadProgress, setUploadProgress] = useState(0);

  // ── Upload logic ───────────────────────────────────────────────
  const handleUpload = async (file: File) => {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      showStatus('Only PDF files are allowed.', 'error');
      return;
    }

    setUploading(true);
    showStatus('Processing & embedding document…', 'loading');
    setUploadProgress(20);

    const interval = setInterval(() => {
      setUploadProgress((p) => (p < 90 ? p + 10 : p));
    }, 600);

    try {
      const data = await api.uploadDocument(file);
      clearInterval(interval);
      setUploadProgress(100);
      showStatus(`${data.chunks_count} chunks indexed successfully`, 'success');
      onDocumentsChange();
      onSelectDocument(data.filename);
      setTimeout(() => resetUpload(), 3000);
    } catch (err: any) {
      clearInterval(interval);
      showStatus(err.message || 'Upload failed', 'error');
      setUploadProgress(0);
      setTimeout(() => setUploading(false), 3000);
    }
  };

  const showStatus = (text: string, type: 'success' | 'error' | 'loading') => {
    setUploadStatus(text);
    setUploadType(type);
  };

  const resetUpload = () => {
    setUploading(false);
    setUploadStatus('');
    setUploadType('');
    setUploadProgress(0);
  };

  // ── Delete logic ───────────────────────────────────────────────
  const handleDelete = async (filename: string) => {
    if (!confirm(`Delete "${filename}" and all cached vectors?`)) return;
    try {
      await api.deleteDocument(filename);
      if (selectedDocument === filename) onSelectDocument(null);
      onDocumentsChange();
    } catch (err: any) {
      alert(`Error: ${err.message}`);
    }
  };

  // ── Drag & drop ────────────────────────────────────────────────
  const onDrag = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(e.type === 'dragenter' || e.type === 'dragover');
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files?.[0]) handleUpload(e.dataTransfer.files[0]);
  };

  const onFileChange = (e: FormEvent<HTMLInputElement>) => {
    const files = (e.target as HTMLInputElement).files;
    if (files?.[0]) handleUpload(files[0]);
  };

  return (
    <aside className={`sidebar ${open ? 'open' : ''}`}>
      {/* ── Brand header ──────────────────────────────────────── */}
      <div className="brand-header">
        <div className="logo-area">
          <img src="/logo.svg" alt="DocuQuery" className="logo-img" />
          <h1>Docu<span>Query</span></h1>
          <button className="sidebar-close-btn" onClick={onClose} aria-label="Close sources panel">
            <X size={18} />
          </button>
        </div>
        <p className="tagline">Intelligent Document RAG System</p>

        {/* Connection badge */}
        <div className="status-indicator">
          <div className={`indicator-dot ${dbOnline ? 'online' : 'offline'}`} />
          <span>{dbMessage}</span>
        </div>
      </div>

      {/* ── Scrollable body ───────────────────────────────────── */}
      <div className="sidebar-body">
        {/* Upload zone */}
        <div className="upload-section">
          <span className="section-label">Add Sources</span>
          <div
            className={`upload-card ${dragActive ? 'dragover' : ''}`}
            onClick={() => fileInputRef.current?.click()}
            onDragEnter={onDrag}
            onDragLeave={onDrag}
            onDragOver={onDrag}
            onDrop={onDrop}
          >
            <UploadCloud className="upload-icon" />
            <p className="upload-msg">
              Drop a PDF here or <span>browse files</span>
            </p>
            <input
              type="file"
              ref={fileInputRef}
              onChange={onFileChange}
              accept=".pdf"
              style={{ display: 'none' }}
            />
          </div>
          {uploading && (
            <div className="upload-progress-bar">
              <div className="progress-fill" style={{ width: `${uploadProgress}%` }} />
            </div>
          )}
          {uploadStatus && <p className={`upload-status ${uploadType}`}>{uploadStatus}</p>}
        </div>

        {/* Document library */}
        <div className="documents-section">
          <div className="section-header">
            <h2>Sources</h2>
            <span className="doc-count">{documents.length}</span>
          </div>
          <div className="document-list-container">
            <ul className="document-list">
              {documents.length === 0 ? (
                <li className="empty-state">
                  No sources added yet.
                  <br />
                  Upload a PDF to start querying.
                </li>
              ) : (
                documents.map((name) => (
                  <li
                    key={name}
                    className={`document-item ${selectedDocument === name ? 'active' : ''}`}
                    onClick={() => onSelectDocument(selectedDocument === name ? null : name)}
                  >
                    <div className="doc-info">
                      <span className="doc-name">
                        <FileText size={13} style={{ marginRight: 6, opacity: 0.5, verticalAlign: -2 }} />
                        {name}
                      </span>
                      <span className="doc-meta">PDF · Indexed</span>
                    </div>
                    <button
                      className="delete-doc-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(name);
                      }}
                      title="Delete source"
                    >
                      <Trash2 size={14} />
                    </button>
                  </li>
                ))
              )}
            </ul>
          </div>
        </div>
      </div>
    </aside>
  );
}
