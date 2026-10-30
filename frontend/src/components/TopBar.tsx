/**
 * TopBar — what the next question searches (scope), how answers are written
 * (response style), where you are (breadcrumb), the plan button, and chat-level actions.
 */

import { useState } from 'react';
import {
  Layers,
  SlidersHorizontal,
  ChevronDown,
  Check,
  Search,
  UserPlus,
  Plus,
  PanelRight,
  Tag,
  Columns2,
  FileText,
  Folder,
  Sparkles,
} from 'lucide-react';
import { useI18n } from '../i18n';
import type { DocInfo, Plan } from '../types';
import { useDismiss } from '../hooks/useDismiss';
import { RESPONSE_STYLES, styleLabel } from '../utils/styles';
import type { ResponseStyle } from '../utils/styles';
import { folderMembers, tagMembers } from '../utils/suggestions';

interface TopBarProps {
  documents: DocInfo[];
  selectedDocuments: string[];
  activeTag: string | null;
  activeFolder: string | null;
  onSelectTag: (tag: string | null) => void;
  onSelectFolder: (folder: string | null) => void;
  onClearScope: () => void;
  responseStyle: ResponseStyle;
  onStyleChange: (style: ResponseStyle) => void;
  plan: Plan;
  onUpgrade: () => void;
  onOpenPlan: () => void;
  title: string;
  hasConversation: boolean;
  libraryOpen: boolean;
  onSearchChats: () => void;
  onShareChat: () => void;
  onNewChat: () => void;
  onToggleLibrary: () => void;
}

export default function TopBar(props: TopBarProps) {
  const { t } = useI18n();
  const { title, hasConversation, libraryOpen, plan, onSearchChats, onShareChat, onNewChat, onToggleLibrary } = props;

  return (
    <header className="topbar">
      <div className="topbar-left">
        <ScopeMenu {...props} />
        <StyleMenu value={props.responseStyle} onChange={props.onStyleChange} />
      </div>

      <div className="breadcrumb" aria-label={t('Location')}>
        {hasConversation ? (
          <>
            <span className="breadcrumb-parent">{t('Chats')}</span>
            <span className="breadcrumb-sep">/</span>
            <span className="breadcrumb-current" title={title}>
              {title || t('Untitled chat')}
            </span>
          </>
        ) : (
          <span className="breadcrumb-current">{t('New chat')}</span>
        )}
      </div>

      <div className="topbar-right">
        {plan === 'free' ? (
          <button className="btn btn-pro" onClick={props.onUpgrade} aria-label={t('Upgrade to Pro')}>
            <Sparkles size={15} />
            <span className="label-long">{t('Upgrade to Pro')}</span>
            <span className="label-short">Pro</span>
          </button>
        ) : (
          <button className="btn btn-pro-on" onClick={props.onOpenPlan} aria-label={t('Your Pro plan')} title={t('Your Pro plan')}>
            <Sparkles size={14} /> Pro
          </button>
        )}
        <button className="btn btn-outline topbar-optional" onClick={onSearchChats} aria-label={t('Search chats')}>
          <Search size={15} />
          <span className="btn-label">{t('Search chats')}</span>
        </button>
        <button className="btn btn-outline topbar-optional" onClick={onShareChat} disabled={!hasConversation} aria-label={t('Share this chat')}>
          <UserPlus size={15} />
          <span className="btn-label">{t('Share')}</span>
        </button>
        <button className="btn btn-ink" onClick={onNewChat} aria-label={t('New chat')}>
          <Plus size={15} />
          <span className="btn-label">{t('New chat')}</span>
        </button>
        <button
          className={`btn btn-outline btn-icon library-toggle ${libraryOpen ? 'on' : ''}`}
          onClick={onToggleLibrary}
          aria-label={libraryOpen ? t('Hide library') : t('Show library')}
          title={libraryOpen ? t('Hide library') : t('Show library')}
        >
          <PanelRight size={16} />
        </button>
      </div>
    </header>
  );
}

function ScopeMenu({
  documents,
  selectedDocuments,
  activeTag,
  activeFolder,
  onSelectTag,
  onSelectFolder,
  onClearScope,
}: TopBarProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const ref = useDismiss<HTMLDivElement>(open, () => setOpen(false));

  const tags = new Map<string, { label: string; count: number }>();
  const folders = new Map<string, { label: string; count: number }>();
  for (const doc of documents) {
    for (const tag of doc.tags ?? []) {
      const entry = tags.get(tag.toLowerCase()) ?? { label: tag, count: 0 };
      entry.count += 1;
      tags.set(tag.toLowerCase(), entry);
    }
    if (doc.folder) {
      const entry = folders.get(doc.folder.toLowerCase()) ?? { label: doc.folder, count: 0 };
      entry.count += 1;
      folders.set(doc.folder.toLowerCase(), entry);
    }
  }

  const picked = selectedDocuments.length > 0;
  const comparing = selectedDocuments.length >= 2;
  const inFolder = !picked && !!activeFolder;
  const tagged = !picked && !activeFolder && !!activeTag;
  const label = picked
    ? comparing
      ? t('Compare {count} sources', { count: selectedDocuments.length })
      : selectedDocuments[0]
    : inFolder
      ? `${activeFolder} (${folderMembers(documents, activeFolder!).length})`
      : tagged
        ? `#${activeTag} (${tagMembers(documents, activeTag!).length})`
        : t('All sources');
  const Icon = picked ? (comparing ? Columns2 : FileText) : inFolder ? Folder : tagged ? Tag : Layers;
  const everything = !picked && !inFolder && !tagged;

  return (
    <div className="menu-anchor" ref={ref}>
      <button
        className={`pill ${!everything ? 'pill-active' : ''}`}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('Searching: {scope}', { scope: label })}
      >
        <Icon size={15} />
        <span className="pill-text">{label}</span>
        <ChevronDown size={14} className="pill-chevron" />
      </button>
      {open && (
        <div className="popover menu" role="menu">
          <p className="popover-title">{t('Questions search')}</p>
          <button
            className="menu-item"
            role="menuitemradio"
            aria-checked={everything}
            onClick={() => {
              onClearScope();
              setOpen(false);
            }}
          >
            <Layers size={15} /> {t('All sources')}
            {everything && <Check size={14} className="menu-check" />}
          </button>
          {[...folders.values()].map(({ label: name, count }) => {
            const on = inFolder && activeFolder!.toLowerCase() === name.toLowerCase();
            return (
              <button
                key={`folder:${name.toLowerCase()}`}
                className="menu-item"
                role="menuitemradio"
                aria-checked={on}
                onClick={() => {
                  onSelectFolder(name);
                  setOpen(false);
                }}
              >
                <Folder size={15} /> {name}
                <span className="menu-count">{count}</span>
                {on && <Check size={14} className="menu-check" />}
              </button>
            );
          })}
          {[...tags.values()].map(({ label: tag, count }) => {
            const on = tagged && activeTag!.toLowerCase() === tag.toLowerCase();
            return (
              <button
                key={`tag:${tag.toLowerCase()}`}
                className="menu-item"
                role="menuitemradio"
                aria-checked={on}
                onClick={() => {
                  onSelectTag(tag);
                  setOpen(false);
                }}
              >
                <Tag size={15} /> #{tag}
                <span className="menu-count">{count}</span>
                {on && <Check size={14} className="menu-check" />}
              </button>
            );
          })}
          {picked && (
            <>
              <div className="menu-divider" />
              <p className="popover-title">{comparing ? t('Comparing') : t('Selected')}</p>
              {selectedDocuments.map((name) => (
                <p key={name} className="menu-static" title={name}>
                  <FileText size={14} /> {name}
                </p>
              ))}
              <button
                className="menu-item"
                onClick={() => {
                  onClearScope();
                  setOpen(false);
                }}
              >
                {t('Clear selection')}
              </button>
            </>
          )}
          <p className="popover-note">
            {t('Tick sources in the library to ask about specific files, or two to four to compare them.')}
          </p>
        </div>
      )}
    </div>
  );
}

function StyleMenu({ value, onChange }: { value: ResponseStyle; onChange: (s: ResponseStyle) => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const ref = useDismiss<HTMLDivElement>(open, () => setOpen(false));

  return (
    <div className="menu-anchor style-menu" ref={ref}>
      <button
        className="pill"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('Response style: {style}', { style: t(styleLabel(value)) })}
      >
        <SlidersHorizontal size={15} />
        <span className="pill-text">{t(styleLabel(value))}</span>
        <ChevronDown size={14} className="pill-chevron" />
      </button>
      {open && (
        <div className="popover menu menu-wide" role="menu">
          <p className="popover-title">{t('How answers are written')}</p>
          {RESPONSE_STYLES.map((s) => (
            <button
              key={s.id}
              className="menu-item menu-item-stacked"
              role="menuitemradio"
              aria-checked={value === s.id}
              onClick={() => {
                onChange(s.id);
                setOpen(false);
              }}
            >
              <span className="menu-item-main">
                {t(s.label)}
                {value === s.id && <Check size={14} className="menu-check" />}
              </span>
              <span className="menu-item-sub">{t(s.description)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
