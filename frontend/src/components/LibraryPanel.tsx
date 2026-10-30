/**
 * LibraryPanel — the right-hand column: add sources, the library (with
 * selection, folders, tags, sharing), and suggested tasks / questions for the
 * current scope.
 */

import { useEffect, useRef, useState } from 'react';
import type { DragEvent, FormEvent, KeyboardEvent } from 'react';
import {
  Upload,
  Link2,
  ClipboardPaste,
  Trash2,
  FileText,
  X,
  Plus,
  Check,
  Loader2,
  AlertCircle,
  Tag,
  Share2,
  Folder,
  FolderInput,
  FolderMinus,
  ChevronDown,
  ChevronRight,
  Pencil,
  MessageSquareText,
} from 'lucide-react';
import * as api from '../api';
import { useI18n } from '../i18n';
import type { DocInfo } from '../types';
import type { QueueItem } from '../hooks/useUploadQueue';
import { ACCEPTED_EXTENSIONS, fileTypeLabel, formatBytes, pageCountLabel } from '../utils/format';
import { folderMembers, getSuggestions, tagMembers } from '../utils/suggestions';
import { TYPE_ICONS } from '../utils/icons';
import { PasteTextDialog } from './Dialogs';
import { useConfirm, useToast } from '../hooks/useNotifications';

interface LibraryPanelProps {
  open: boolean;
  documents: DocInfo[];
  selectedDocuments: string[];
  activeTag: string | null;
  activeFolder: string | null;
  showSuggestions: boolean;
  queue: QueueItem[];
  onDismissUpload: (key: string) => void;
  onUploadFiles: (files: FileList | File[]) => void;
  onUploadLink: (url: string) => void;
  onUploadText: (payload: { title?: string; url?: string; text: string }) => void;
  onSelectTag: (tag: string | null) => void;
  onSelectFolder: (folder: string | null) => void;
  onSetTags: (filename: string, tags: string[]) => Promise<void>;
  onMoveToFolder: (filenames: string[]) => void;
  onRenameFolder: (name: string, newName: string) => Promise<void>;
  onDeleteFolder: (name: string) => Promise<void>;
  onShareDocument: (filename: string) => void;
  onDocumentsChange: () => void;
  onToggleDocument: (filename: string) => void;
  onClearSelection: () => void;
  onAsk: (question: string) => void;
  onClose: () => void;
}

export default function LibraryPanel(props: LibraryPanelProps) {
  const { t } = useI18n();
  const { open, documents, selectedDocuments, activeTag, activeFolder, showSuggestions, onAsk, onClose } = props;
  const { tasks, questions } = getSuggestions(documents, selectedDocuments, activeTag, activeFolder, t);

  return (
    <>
      {open && <div className="panel-backdrop" onClick={onClose} />}
      <aside className={`library-panel ${open ? 'open' : ''}`} aria-label={t('Library')}>
        <div className="panel-mobile-head">
          <h2>{t('Library')}</h2>
          <button className="icon-btn" onClick={onClose} aria-label={t('Close library')}>
            <X size={16} />
          </button>
        </div>

        <AddSourcesCard {...props} />
        <LibraryCard {...props} />

        {showSuggestions && tasks.length > 0 && (
          <section className="card">
            <h2 className="card-title">{t('Suggested tasks')}</h2>
            <div className="task-grid">
              {tasks.map((task) => (
                <button key={task} className="task-chip" onClick={() => onAsk(task)}>
                  {task}
                </button>
              ))}
            </div>
          </section>
        )}

        {showSuggestions && questions.length > 0 && (
          <section className="card">
            <h2 className="card-title">{t('Suggested questions')}</h2>
            <div className="question-list">
              {questions.map((q) => (
                <button key={q} className="question-row" onClick={() => onAsk(q)}>
                  {q}
                </button>
              ))}
            </div>
          </section>
        )}
      </aside>
    </>
  );
}

/* ── Add sources ───────────────────────────────────────────────────── */

function AddSourcesCard({ queue, onDismissUpload, onUploadFiles, onUploadLink, onUploadText }: LibraryPanelProps) {
  const { t } = useI18n();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [linkOpen, setLinkOpen] = useState(false);
  const [url, setUrl] = useState('');
  const [pasteOpen, setPasteOpen] = useState(false);

  const onDrag = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(e.type === 'dragenter' || e.type === 'dragover');
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files?.length) onUploadFiles(e.dataTransfer.files);
  };
  const submitLink = (e: FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;
    onUploadLink(url);
    setUrl('');
    setLinkOpen(false);
  };

  return (
    <section
      className={`card add-card ${dragActive ? 'dragover' : ''}`}
      onDragEnter={onDrag}
      onDragLeave={onDrag}
      onDragOver={onDrag}
      onDrop={onDrop}
    >
      <h2 className="card-title">{t('Sources')}</h2>
      <div className="add-art" aria-hidden="true">
        <span className="add-art-sheet back" />
        <span className="add-art-sheet front">
          <Upload size={15} />
        </span>
      </div>
      <p className="add-copy">{t('Drop files here, or add a web page or text you copied.')}</p>

      <div className="add-actions">
        <button className="btn btn-outline" onClick={() => fileInputRef.current?.click()}>
          <Upload size={14} /> {t('Upload file')}
        </button>
        <button className={`btn btn-outline ${linkOpen ? 'on' : ''}`} onClick={() => setLinkOpen((o) => !o)}>
          <Link2 size={14} /> {t('Add link')}
        </button>
      </div>
      <input
        type="file"
        ref={fileInputRef}
        multiple
        accept={ACCEPTED_EXTENSIONS.join(',')}
        style={{ display: 'none' }}
        aria-label={t('Upload files')}
        onChange={(e) => {
          if (e.target.files?.length) onUploadFiles(e.target.files);
          e.target.value = '';
        }}
      />

      {linkOpen && (
        <form className="link-form" onSubmit={submitLink}>
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://…"
            aria-label={t('Web page link')}
            inputMode="url"
            autoFocus
          />
          <button type="submit" className="btn btn-ink btn-icon" disabled={!url.trim()} aria-label={t('Add web page')}>
            <Plus size={15} />
          </button>
        </form>
      )}

      <button className="text-btn paste-btn" onClick={() => setPasteOpen(true)}>
        <ClipboardPaste size={14} /> {t('Paste text instead, for sites that block readers')}
      </button>
      <p className="add-formats">{t('PDF, Word, PowerPoint, Excel, CSV, text, Markdown and images. Scans are read with OCR.')}</p>

      {queue.length > 0 && (
        <ul className="upload-queue">
          {queue.map((item) => (
            <li key={item.key} className={`queue-item ${item.status}`}>
              <div className="queue-top">
                <span className="queue-name" title={item.label}>
                  {item.label}
                </span>
                {item.status === 'active' && <Loader2 size={13} className="spin" />}
                {item.status === 'done' && <Check size={13} />}
                {item.status === 'error' && (
                  <button className="queue-dismiss" onClick={() => onDismissUpload(item.key)} aria-label={t('Dismiss')}>
                    <X size={13} />
                  </button>
                )}
              </div>
              {item.status === 'active' && (
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${item.percent}%` }} />
                </div>
              )}
              <p className="queue-message">
                {item.status === 'error' && <AlertCircle size={12} />} {item.message}
              </p>
            </li>
          ))}
        </ul>
      )}

      {pasteOpen && <PasteTextDialog onSubmit={onUploadText} onClose={() => setPasteOpen(false)} />}
    </section>
  );
}

/* ── Library ───────────────────────────────────────────────────────── */

const COLLAPSED_KEY = 'docuquery.collapsedFolders';

function loadCollapsed(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(COLLAPSED_KEY) ?? '[]');
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

function LibraryCard({
  documents,
  selectedDocuments,
  activeTag,
  activeFolder,
  onSelectTag,
  onSelectFolder,
  onSetTags,
  onMoveToFolder,
  onRenameFolder,
  onDeleteFolder,
  onShareDocument,
  onDocumentsChange,
  onToggleDocument,
  onClearSelection,
}: LibraryPanelProps) {
  const { t, tn } = useI18n();
  const toast = useToast();
  const confirm = useConfirm();
  const [editingTags, setEditingTags] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<string[]>(loadCollapsed);

  const tagCounts = new Map<string, { label: string; count: number }>();
  const folderMap = new Map<string, { name: string; docs: DocInfo[] }>();
  for (const doc of documents) {
    for (const tag of doc.tags ?? []) {
      const entry = tagCounts.get(tag.toLowerCase()) ?? { label: tag, count: 0 };
      entry.count += 1;
      tagCounts.set(tag.toLowerCase(), entry);
    }
    if (doc.folder) {
      const entry = folderMap.get(doc.folder.toLowerCase()) ?? { name: doc.folder, docs: [] };
      entry.docs.push(doc);
      folderMap.set(doc.folder.toLowerCase(), entry);
    }
  }
  const allTags = [...tagCounts.values()].sort((a, b) => a.label.localeCompare(b.label));
  const folders = [...folderMap.values()].sort((a, b) => a.name.localeCompare(b.name));
  const unfiled = documents.filter((d) => !d.folder);
  const tagView = activeTag ? tagMembers(documents, activeTag) : null;
  const comparing = selectedDocuments.length >= 2;

  const toggleFolder = (name: string) => {
    const key = name.toLowerCase();
    const next = collapsed.includes(key) ? collapsed.filter((k) => k !== key) : [...collapsed, key];
    setCollapsed(next);
    try {
      localStorage.setItem(COLLAPSED_KEY, JSON.stringify(next));
    } catch {
      /* storage unavailable: the state just won't be remembered */
    }
  };

  const remove = async (filename: string) => {
    const ok = await confirm({
      title: t('Delete this source?'),
      message: t('"{name}" and its search index will be deleted.', { name: filename }),
      confirmLabel: t('Delete'),
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteDocument(filename);
      onDocumentsChange();
      toast.success(t('"{name}" was deleted.', { name: filename }));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('Deletion failed'));
    }
  };

  const removeFolder = async (name: string, count: number) => {
    const ok = await confirm({
      title: t('Remove the folder "{name}"?', { name }),
      message: tn(
        'The {count} source inside is kept; it just stops being grouped.',
        'The {count} sources inside are kept; they just stop being grouped.',
        count,
      ),
      confirmLabel: t('Remove folder'),
      danger: true,
    });
    if (!ok) return;
    try {
      await onDeleteFolder(name);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('Could not remove the folder'));
    }
  };

  const row = (doc: DocInfo) => (
    <DocumentRow
      key={doc.id}
      doc={doc}
      selected={selectedDocuments.includes(doc.filename)}
      editingTags={editingTags === doc.filename}
      allTags={allTags.map((tag) => tag.label)}
      onToggle={() => onToggleDocument(doc.filename)}
      onEditTags={() => setEditingTags(editingTags === doc.filename ? null : doc.filename)}
      onSetTags={(tags) => onSetTags(doc.filename, tags)}
      onShare={() => onShareDocument(doc.filename)}
      onDelete={() => remove(doc.filename)}
    />
  );

  return (
    <section className="card library-card">
      <div className="card-head">
        <h2 className="card-title">
          {t('Library')} <span className="count">{documents.length}</span>
        </h2>
      </div>

      {selectedDocuments.length > 0 && (
        <div className="selection-tools">
          <span className="selection-count">
            {tn('{count} source selected', '{count} sources selected', selectedDocuments.length)}
          </span>
          <button className="btn btn-outline btn-sm" onClick={() => onMoveToFolder(selectedDocuments)}>
            <FolderInput size={13} /> {t('Move to folder')}
          </button>
          <button className="text-btn" onClick={onClearSelection}>
            {t('Clear selection')}
          </button>
        </div>
      )}

      {allTags.length > 0 && (
        <div className="tag-filter" role="group" aria-label={t('Filter by tag')}>
          <button className={`tag-chip ${activeTag === null ? 'active' : ''}`} onClick={() => onSelectTag(null)}>
            {t('All')}
          </button>
          {allTags.map(({ label, count }) => {
            const on = activeTag?.toLowerCase() === label.toLowerCase();
            return (
              <button
                key={label.toLowerCase()}
                className={`tag-chip ${on ? 'active' : ''}`}
                onClick={() => onSelectTag(on ? null : label)}
                title={tn(
                  'Ask across the {count} source tagged "{label}"',
                  'Ask across the {count} sources tagged "{label}"',
                  count,
                  { label },
                )}
              >
                #{label} <span>{count}</span>
              </button>
            );
          })}
        </div>
      )}

      {comparing && (
        <p className="scope-note">{t('Comparing {count} sources. Answers will contrast them.', { count: selectedDocuments.length })}</p>
      )}
      {activeTag && selectedDocuments.length === 0 && !activeFolder && (
        <p className="scope-note">
          {tn(
            'Questions search the {count} source tagged #{name}.',
            'Questions search the {count} sources tagged #{name}.',
            tagView?.length ?? 0,
            { name: activeTag },
          )}
        </p>
      )}
      {activeFolder && selectedDocuments.length === 0 && (
        <p className="scope-note">
          {tn(
            'Questions search the {count} source in the folder {name}.',
            'Questions search the {count} sources in the folder {name}.',
            folderMembers(documents, activeFolder).length,
            { name: activeFolder },
          )}
        </p>
      )}

      <ul className="doc-list">
        {documents.length === 0 ? (
          <li className="empty-note">{t('Nothing here yet. Add a file or a link above.')}</li>
        ) : tagView ? (
          tagView.length === 0 ? (
            <li className="empty-note">{t('No sources have this tag.')}</li>
          ) : (
            tagView.map(row)
          )
        ) : (
          <>
            {folders.map(({ name, docs }) => (
              <FolderGroup
                key={name.toLowerCase()}
                name={name}
                count={docs.length}
                collapsed={collapsed.includes(name.toLowerCase())}
                active={activeFolder?.toLowerCase() === name.toLowerCase()}
                onToggle={() => toggleFolder(name)}
                onAsk={() => onSelectFolder(activeFolder?.toLowerCase() === name.toLowerCase() ? null : name)}
                onRename={(next) => onRenameFolder(name, next)}
                onRemove={() => removeFolder(name, docs.length)}
              >
                {docs.map(row)}
              </FolderGroup>
            ))}
            {folders.length > 0 && unfiled.length > 0 && <li className="folder-label">{t('Not in a folder')}</li>}
            {unfiled.map(row)}
          </>
        )}
      </ul>
      {documents.length > 1 && selectedDocuments.length === 0 && !activeTag && !activeFolder && (
        <p className="card-hint">{t('Tick sources to ask about them, or group them into a folder or tag.')}</p>
      )}
    </section>
  );
}

function FolderGroup({
  name,
  count,
  collapsed,
  active,
  onToggle,
  onAsk,
  onRename,
  onRemove,
  children,
}: {
  name: string;
  count: number;
  collapsed: boolean;
  active: boolean;
  onToggle: () => void;
  onAsk: () => void;
  onRename: (newName: string) => Promise<void>;
  onRemove: () => void;
  children: React.ReactNode;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState(name);
  const Chevron = collapsed ? ChevronRight : ChevronDown;

  const commit = async () => {
    const next = draft.trim();
    setRenaming(false);
    if (!next || next === name) return;
    try {
      await onRename(next);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('Could not rename the folder'));
    }
  };

  return (
    <li className={`folder-group ${active ? 'active' : ''}`}>
      <div className="folder-head">
        {renaming ? (
          <input
            className="rename-input"
            value={draft}
            autoFocus
            maxLength={60}
            aria-label={t('Folder name')}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commit();
              if (e.key === 'Escape') setRenaming(false);
            }}
            onBlur={commit}
          />
        ) : (
          <button className="folder-toggle" onClick={onToggle} aria-expanded={!collapsed} title={name}>
            <Chevron size={14} />
            <Folder size={15} />
            <span className="folder-name">{name}</span>
            <span className="count">{count}</span>
          </button>
        )}
        {!renaming && (
          <span className="row-actions">
            <button
              className={`icon-btn ${active ? 'selected' : ''}`}
              onClick={onAsk}
              aria-pressed={active}
              title={active ? t('Stop searching only this folder') : t('Ask only this folder')}
              aria-label={t('Ask only the folder {name}', { name })}
            >
              <MessageSquareText size={14} />
            </button>
            <button
              className="icon-btn"
              onClick={() => {
                setDraft(name);
                setRenaming(true);
              }}
              title={t('Rename folder')}
              aria-label={t('Rename the folder {name}', { name })}
            >
              <Pencil size={14} />
            </button>
            <button
              className="icon-btn danger"
              onClick={onRemove}
              title={t('Remove folder (keeps the sources)')}
              aria-label={t('Remove the folder {name}', { name })}
            >
              <FolderMinus size={14} />
            </button>
          </span>
        )}
      </div>
      {!collapsed && <ul className="folder-docs">{children}</ul>}
    </li>
  );
}

function DocumentRow({
  doc,
  selected,
  editingTags,
  allTags,
  onToggle,
  onEditTags,
  onSetTags,
  onShare,
  onDelete,
}: {
  doc: DocInfo;
  selected: boolean;
  editingTags: boolean;
  allTags: string[];
  onToggle: () => void;
  onEditTags: () => void;
  onSetTags: (tags: string[]) => Promise<void>;
  onShare: () => void;
  onDelete: () => void;
}) {
  const { t, tn } = useI18n();
  const Icon = TYPE_ICONS[doc.file_type] ?? FileText;
  return (
    <li className={`doc-row ${selected ? 'selected' : ''}`}>
      <div className="doc-main" onClick={onToggle} title={doc.summary ?? doc.filename}>
        <span
          className={`checkbox ${selected ? 'on' : ''}`}
          role="checkbox"
          aria-checked={selected}
          aria-label={t('Select {name}', { name: doc.filename })}
          tabIndex={0}
          onKeyDown={(e) => (e.key === ' ' || e.key === 'Enter') && (e.preventDefault(), onToggle())}
        >
          {selected && <Check size={11} strokeWidth={3} />}
        </span>
        <span className="doc-icon">
          <Icon size={15} />
        </span>
        <span className="doc-text">
          <span className="doc-name">{doc.filename}</span>
          <span className="doc-meta">
            {fileTypeLabel(doc.file_type)}, {pageCountLabel(doc.file_type, doc.page_count, tn)}
            <span className="doc-size">{formatBytes(doc.size_bytes)}</span>
          </span>
          {doc.tags?.length > 0 && (
            <span className="doc-tags">
              {doc.tags.map((tag) => (
                <span key={tag} className="doc-tag">
                  #{tag}
                </span>
              ))}
            </span>
          )}
        </span>
        <span className="row-actions" onClick={(e) => e.stopPropagation()}>
          <button className="icon-btn" onClick={onEditTags} title={t('Edit tags')} aria-label={t('Edit tags of {name}', { name: doc.filename })}>
            <Tag size={14} />
          </button>
          <button className="icon-btn" onClick={onShare} title={t('Share this source')} aria-label={t('Share {name}', { name: doc.filename })}>
            <Share2 size={14} />
          </button>
          <button className="icon-btn danger" onClick={onDelete} title={t('Delete source')} aria-label={t('Delete {name}', { name: doc.filename })}>
            <Trash2 size={14} />
          </button>
        </span>
      </div>
      {editingTags && <TagEditor tags={doc.tags ?? []} suggestions={allTags} onChange={onSetTags} />}
    </li>
  );
}

function TagEditor({
  tags,
  suggestions,
  onChange,
}: {
  tags: string[];
  suggestions: string[];
  onChange: (tags: string[]) => Promise<void>;
}) {
  const { t } = useI18n();
  const [current, setCurrent] = useState(tags);
  const [draft, setDraft] = useState('');
  const [error, setError] = useState('');
  const listId = useRef(`tags-${Math.random().toString(36).slice(2)}`).current;

  useEffect(() => setCurrent(tags), [tags]);

  const save = async (next: string[]) => {
    const previous = current;
    setCurrent(next);
    setError('');
    try {
      await onChange(next);
    } catch (err) {
      setCurrent(previous);
      setError(err instanceof Error ? err.message : t('Could not save'));
    }
  };

  const add = () => {
    const tag = draft.replace(/,/g, ' ').replace(/^#/, '').trim();
    setDraft('');
    if (tag && !current.some((x) => x.toLowerCase() === tag.toLowerCase())) save([...current, tag]);
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      add();
    } else if (e.key === 'Backspace' && !draft && current.length) {
      save(current.slice(0, -1));
    }
  };

  return (
    <div className="tag-editor">
      {current.map((tag) => (
        <span key={tag} className="doc-tag removable">
          #{tag}
          <button onClick={() => save(current.filter((x) => x !== tag))} aria-label={t('Remove tag {name}', { name: tag })}>
            <X size={10} />
          </button>
        </span>
      ))}
      <input
        value={draft}
        list={listId}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKey}
        onBlur={add}
        maxLength={30}
        placeholder={current.length ? t('Add tag') : t('Type a tag, press Enter')}
        aria-label={t('Add tag')}
        autoFocus
      />
      <datalist id={listId}>
        {suggestions
          .filter((s) => !current.some((x) => x.toLowerCase() === s.toLowerCase()))
          .map((s) => (
            <option key={s} value={s} />
          ))}
      </datalist>
      {error && <p className="field-error">{error}</p>}
    </div>
  );
}
