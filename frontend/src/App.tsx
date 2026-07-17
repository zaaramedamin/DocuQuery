/**
 * Root application shell.
 * Manages top-level state (documents list, selected scope, DB status,
 * active PDF preview, mobile sidebar drawer) and renders the
 * Sidebar + ChatPanel + PdfViewer layout.
 */

import { useState, useEffect, useCallback } from 'react';
import Sidebar from './components/Sidebar';
import ChatPanel from './components/ChatPanel';
import PdfViewer from './components/PdfViewer';
import { fetchDocuments } from './api';
import './App.css';

export default function App() {
  const [documents, setDocuments] = useState<string[]>([]);
  const [selectedDocument, setSelectedDocument] = useState<string | null>(null);
  const [dbOnline, setDbOnline] = useState(true);
  const [dbMessage, setDbMessage] = useState('Supabase Connected');
  const [viewingSource, setViewingSource] = useState<{ filename: string; page: number } | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false); // mobile drawer

  const loadDocuments = useCallback(async () => {
    try {
      const docs = await fetchDocuments();
      setDocuments(docs);
      setDbOnline(true);
      setDbMessage('Supabase Connected');

      // Sync active viewer in case the document was deleted
      setViewingSource((prev) => {
        if (prev && !docs.includes(prev.filename)) return null;
        return prev;
      });
    } catch {
      setDbOnline(false);
      setDbMessage('Supabase Offline');
    }
  }, []);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  return (
    <div className="app-container">
      <Sidebar
        documents={documents}
        selectedDocument={selectedDocument}
        dbOnline={dbOnline}
        dbMessage={dbMessage}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onDocumentsChange={loadDocuments}
        onSelectDocument={(name) => {
          setSelectedDocument(name);
          setSidebarOpen(false); // collapse drawer after choosing on mobile
        }}
      />
      {sidebarOpen && <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} />}
      <ChatPanel
        documents={documents}
        selectedDocument={selectedDocument}
        onClearScope={() => setSelectedDocument(null)}
        onViewSource={(filename, page) => setViewingSource({ filename, page })}
        onOpenSidebar={() => setSidebarOpen(true)}
      />
      {viewingSource && (
        <PdfViewer
          filename={viewingSource.filename}
          page={viewingSource.page}
          onClose={() => setViewingSource(null)}
        />
      )}
    </div>
  );
}
