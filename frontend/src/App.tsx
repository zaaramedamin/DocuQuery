/**
 * Root application shell.
 * Manages top-level state (documents list, selected scope, DB status)
 * and renders the Sidebar + ChatPanel layout.
 */

import { useState, useEffect, useCallback } from 'react';
import Sidebar from './components/Sidebar';
import ChatPanel from './components/ChatPanel';
import { fetchDocuments } from './api';
import './App.css';

export default function App() {
  const [documents, setDocuments] = useState<string[]>([]);
  const [selectedDocument, setSelectedDocument] = useState<string | null>(null);
  const [dbOnline, setDbOnline] = useState(true);
  const [dbMessage, setDbMessage] = useState('Supabase Connected');

  const loadDocuments = useCallback(async () => {
    try {
      const docs = await fetchDocuments();
      setDocuments(docs);
      setDbOnline(true);
      setDbMessage('Supabase Connected');
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
        onDocumentsChange={loadDocuments}
        onSelectDocument={setSelectedDocument}
      />
      <ChatPanel
        documents={documents}
        selectedDocument={selectedDocument}
        onClearScope={() => setSelectedDocument(null)}
      />
    </div>
  );
}
