/**
 * Root application shell.
 *
 * `App` decides what to show: a share link, the new-password page, the
 * sign-in screen, or — once signed in — the `Workspace`. `Workspace` owns the
 * signed-in state (documents, scope, folders, tags, saved chats, plan and usage,
 * upload queue, dialogs) and lays out the rail, top bar, chat, library panel and
 * history flyout.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import Rail from './components/Rail';
import TopBar from './components/TopBar';
import HistoryPanel from './components/HistoryPanel';
import LibraryPanel from './components/LibraryPanel';
import ChatPanel from './components/ChatPanel';
import SourceViewer from './components/SourceViewer';
import AuthScreen from './components/AuthScreen';
import ResetPasswordScreen from './components/ResetPasswordScreen';
import SharedView from './components/SharedView';
import SettingsDialog from './components/SettingsDialog';
import UpgradeDialog from './components/UpgradeDialog';
import { FolderDialog, ImportDialog, ShareDialog } from './components/Dialogs';
import { useToast } from './hooks/useNotifications';
import { useUploadQueue } from './hooks/useUploadQueue';
import { useI18n } from './i18n';
import { usePreferences } from './preferences';
import * as api from './api';
import type { Account, AuthUser, ConversationInfo, DocInfo, ImportPayload, Plan, ShareKind, Usage } from './types';
import type { SettingsTab } from './components/SettingsDialog';
import { clearHash, parseHash, readImportMessage } from './utils/route';
import { formatBytes } from './utils/format';
import { checkUploadSizes } from './utils/uploadLimits';
import type { ResponseStyle } from './utils/styles';
import { styleLabel } from './utils/styles';
import './App.css';

/** Most sources that can be compared at once (matches the backend limit). */
const MAX_COMPARE = 4;

interface PageState {
  /** Token from a password-reset email. */
  recoveryToken: string | null;
  /** Message for the sign-in screen (expired link, password updated…). */
  authNotice: { kind: 'notice' | 'error'; text: string } | null;
  /** Token of the share link being viewed. */
  shareToken: string | null;
}

/** Read the URL once at load. Secrets in the hash are removed from the address bar immediately. */
function readInitialPage(): PageState {
  const route = parseHash(window.location.hash);
  const state: PageState = { recoveryToken: null, authNotice: null, shareToken: null };
  if (!route) return state;
  if (route.kind === 'share') {
    state.shareToken = route.token;
    return state;
  }
  if (route.kind === 'recovery') state.recoveryToken = route.accessToken;
  if (route.kind === 'auth-error') state.authNotice = { kind: 'error', text: route.message };
  clearHash();
  return state;
}

export default function App() {
  const { t } = useI18n();
  const [user, setUser] = useState<AuthUser | null>(() => api.getSession()?.user ?? null);
  const [page, setPage] = useState<PageState>(readInitialPage);
  const [selectOnOpen, setSelectOnOpen] = useState<string | null>(null);
  const [pendingImport, setPendingImport] = useState<(ImportPayload & { nonce: string }) | null>(null);
  const lastNonce = useRef('');

  useEffect(() => api.onAuthChange((session) => setUser(session?.user ?? null)), []);

  // Following a share link while the app is already open.
  useEffect(() => {
    const onHash = () => {
      const route = parseHash(window.location.hash);
      if (route?.kind === 'share') setPage((p) => ({ ...p, shareToken: route.token }));
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  // A page sent from the user's own browser via the browser button. Only the window
  // that opened us may send it, and nothing is added until the user confirms.
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (!window.opener || event.source !== window.opener) return;
      const payload = readImportMessage(event.data);
      if (!payload) return;
      (event.source as Window).postMessage({ type: 'docuquery-received', nonce: payload.nonce }, event.origin);
      if (payload.nonce === lastNonce.current) return; // the button re-sends until it hears back
      lastNonce.current = payload.nonce;
      setPendingImport(payload);
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  if (page.recoveryToken) {
    return (
      <ResetPasswordScreen
        accessToken={page.recoveryToken}
        onDone={() =>
          setPage((p) => ({
            ...p,
            recoveryToken: null,
            authNotice: { kind: 'notice', text: t('Password updated. Sign in with your new password.') },
          }))
        }
      />
    );
  }

  if (page.shareToken) {
    const leave = () => {
      clearHash();
      setPage((p) => ({ ...p, shareToken: null }));
    };
    return (
      <SharedView
        token={page.shareToken}
        signedIn={!!user}
        onAdded={(filename) => {
          setSelectOnOpen(filename);
          leave();
        }}
        onExit={leave}
      />
    );
  }

  if (!user) {
    const { authNotice } = page;
    return (
      <AuthScreen
        key={authNotice ? `${authNotice.kind}:${authNotice.text}` : 'plain'}
        notice={authNotice?.kind === 'notice' ? authNotice.text : ''}
        error={authNotice?.kind === 'error' ? authNotice.text : ''}
      />
    );
  }

  return (
    <Workspace
      user={user}
      initialSelection={selectOnOpen}
      pendingImport={pendingImport}
      onImportHandled={() => setPendingImport(null)}
    />
  );
}

/** Screens wide enough to show the library panel next to the chat. */
const WIDE = '(min-width: 1180px)';

function Workspace({
  user,
  initialSelection,
  pendingImport,
  onImportHandled,
}: {
  user: AuthUser;
  initialSelection: string | null;
  pendingImport: (ImportPayload & { nonce: string }) | null;
  onImportHandled: () => void;
}) {
  const { t, tn } = useI18n();
  const toast = useToast();
  const { prefs, update, syncFromServer } = usePreferences();

  const [documents, setDocuments] = useState<DocInfo[]>([]);
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>(initialSelection ? [initialSelection] : []);
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [activeFolder, setActiveFolder] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationInfo[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [account, setAccount] = useState<Account | null>(null);
  const [viewingSource, setViewingSource] = useState<{ filename: string; page: number } | null>(null);
  const [shareTarget, setShareTarget] = useState<{ kind: ShareKind; ref: string; label: string } | null>(null);
  const [history, setHistory] = useState<{ open: boolean; focusSearch: boolean }>({ open: false, focusSearch: false });
  const [libraryOpen, setLibraryOpen] = useState(() => window.matchMedia?.(WIDE).matches ?? true);
  const [settingsTab, setSettingsTab] = useState<SettingsTab | null>(null);
  const [upgrade, setUpgrade] = useState<{ reason: string } | null>(null);
  const [folderTarget, setFolderTarget] = useState<string[] | null>(null);
  const [askRequest, setAskRequest] = useState<{ id: number; text: string } | null>(null);

  const plan: Plan = usage?.plan ?? account?.plan ?? 'free';
  const responseStyle: ResponseStyle = prefs.response_style;

  const loadDocuments = useCallback(async () => {
    try {
      const docs = await api.fetchDocuments();
      setDocuments(docs);

      // Drop selections / previews / tag and folder scope of things that no longer exist.
      const names = new Set(docs.map((d) => d.filename));
      setSelectedDocuments((prev) => prev.filter((n) => names.has(n)));
      setViewingSource((prev) => (prev && !names.has(prev.filename) ? null : prev));
      setActiveTag((prev) =>
        prev && docs.some((d) => (d.tags ?? []).some((x) => x.toLowerCase() === prev.toLowerCase())) ? prev : null,
      );
      setActiveFolder((prev) => (prev && docs.some((d) => (d.folder ?? '').toLowerCase() === prev.toLowerCase()) ? prev : null));
    } catch {
      /* the library keeps its last known state; actions show their own errors */
    }
  }, []);

  const loadConversations = useCallback(async () => {
    try {
      const list = await api.fetchConversations();
      setConversations(list);
      return list;
    } catch {
      /* the chat list is non-critical */
      return null;
    }
  }, []);

  const loadUsage = useCallback(async () => {
    try {
      setUsage(await api.fetchUsage());
    } catch {
      /* usage is informational */
    }
  }, []);

  const loadAccount = useCallback(async () => {
    try {
      const fresh = await api.fetchAccount();
      setAccount(fresh);
      return fresh;
    } catch {
      /* the plan falls back to what /usage reports */
      return null;
    }
  }, []);

  useEffect(() => {
    loadDocuments();
    loadConversations();
    loadUsage();
    loadAccount();
    syncFromServer().catch(() => {
      /* preferences keep their values from this browser */
    });
  }, [loadDocuments, loadConversations, loadUsage, loadAccount, syncFromServer]);

  // Wide screens show the library beside the chat; narrow ones keep it as a drawer that starts closed.
  useEffect(() => {
    const query = window.matchMedia?.(WIDE);
    if (!query) return;
    const onChange = (e: MediaQueryListEvent) => setLibraryOpen(e.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  const refreshDocuments = useCallback(() => {
    loadDocuments();
    loadUsage();
  }, [loadDocuments, loadUsage]);

  const refreshChats = useCallback(() => {
    loadConversations();
    loadUsage();
  }, [loadConversations, loadUsage]);

  /** After the settings dialog changed the account's data: reload everything it may have touched. */
  const refreshEverything = useCallback(async () => {
    loadDocuments();
    loadUsage();
    loadAccount();
    const list = await loadConversations();
    if (list) setConversationId((current) => (current && !list.some((c) => c.id === current) ? null : current));
  }, [loadDocuments, loadUsage, loadAccount, loadConversations]);

  const openUpgrade = useCallback((reason = '') => setUpgrade({ reason }), []);

  // Several files finishing in a row get one notification instead of a stack of them.
  const justAdded = useRef<string[]>([]);
  const addedTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const announceAdded = useCallback(
    (name: string) => {
      justAdded.current.push(name);
      clearTimeout(addedTimer.current);
      addedTimer.current = setTimeout(() => {
        const names = justAdded.current;
        justAdded.current = [];
        toast.success(
          names.length === 1
            ? t('"{name}" was added to your library.', { name: names[0] })
            : t('{count} sources were added to your library.', { count: names.length }),
        );
      }, 700);
    },
    [toast, t],
  );

  const onUploaded = useCallback(
    (doc: DocInfo) => {
      refreshDocuments();
      setSelectedDocuments([doc.filename]);
      setActiveTag(null);
      setActiveFolder(null);
      announceAdded(doc.filename);
    },
    [refreshDocuments, announceAdded],
  );

  const onUploadFailed = useCallback(
    (error: Error, label: string) => {
      if (error instanceof api.ApiError && error.upgrade) openUpgrade(error.message);
      else toast.error(`${label}: ${error.message}`);
    },
    [openUpgrade, toast],
  );

  const { queue, dismiss, uploadFiles, uploadLink, uploadText } = useUploadQueue(onUploaded, onUploadFailed);

  /** Check each file against the plan's size limit before sending it, so a too-big file never leaves the browser. */
  const guardedUpload = useCallback(
    (files: FileList | File[]) => {
      const limit = usage?.max_upload_bytes ?? account?.limits[plan].max_upload_bytes;
      const proLimit = account?.limits.pro.max_upload_bytes;
      const { accepted, needsPro, tooLarge } = checkUploadSizes(Array.from(files), limit, plan, proLimit);
      for (const file of tooLarge) {
        toast.error(
          t('"{name}" is {size}, which is over the {limit} limit for a single file.', {
            name: file.name,
            size: formatBytes(file.size),
            limit: formatBytes(proLimit && plan === 'free' ? proLimit : (limit ?? 0)),
          }),
        );
      }
      if (needsPro.length) {
        openUpgrade(
          needsPro.length === 1
            ? t('"{name}" is {size}. The Free plan accepts files up to {limit}.', {
                name: needsPro[0].name,
                size: formatBytes(needsPro[0].size),
                limit: formatBytes(limit ?? 0),
              })
            : t('{count} of these files are over the Free plan limit of {limit} per file.', {
                count: needsPro.length,
                limit: formatBytes(limit ?? 0),
              }),
        );
      }
      if (accepted.length) uploadFiles(accepted);
    },
    [account, openUpgrade, plan, toast, t, uploadFiles, usage],
  );

  const isNarrow = () => !(window.matchMedia?.(WIDE).matches ?? true);

  const toggleDocument = (filename: string) =>
    setSelectedDocuments((prev) =>
      prev.includes(filename)
        ? prev.filter((n) => n !== filename)
        : prev.length >= MAX_COMPARE
          ? prev
          : [...prev, filename],
    );

  const selectTag = (tag: string | null) => {
    setActiveTag(tag);
    setActiveFolder(null);
    setSelectedDocuments([]);
  };

  const selectFolder = (folder: string | null) => {
    setActiveFolder(folder);
    setActiveTag(null);
    setSelectedDocuments([]);
  };

  const clearScope = () => {
    setSelectedDocuments([]);
    setActiveTag(null);
    setActiveFolder(null);
  };

  const setTags = async (filename: string, tags: string[]) => {
    const saved = await api.setTags(filename, tags);
    setDocuments((prev) => prev.map((d) => (d.filename === filename ? { ...d, tags: saved } : d)));
    setActiveTag((prev) => {
      if (!prev) return prev;
      const stillUsed =
        saved.some((x) => x.toLowerCase() === prev.toLowerCase()) ||
        documents.some((d) => d.filename !== filename && (d.tags ?? []).some((x) => x.toLowerCase() === prev.toLowerCase()));
      return stillUsed ? prev : null;
    });
    toast.success(t('Tags updated.'));
  };

  const moveToFolder = async (filenames: string[], folder: string | null) => {
    const final = await api.assignFolder(filenames, folder);
    await loadDocuments();
    toast.success(
      final
        ? tn('Moved {count} source to “{folder}”.', 'Moved {count} sources to “{folder}”.', filenames.length, { folder: final })
        : tn('Took {count} source out of its folder.', 'Took {count} sources out of their folder.', filenames.length),
    );
  };

  const renameFolder = async (name: string, newName: string) => {
    const final = await api.renameFolder(name, newName);
    setActiveFolder((prev) => (prev && prev.toLowerCase() === name.toLowerCase() ? final : prev));
    await loadDocuments();
    toast.success(t('Folder renamed to “{name}”.', { name: final }));
  };

  const deleteFolder = async (name: string) => {
    await api.deleteFolder(name);
    setActiveFolder((prev) => (prev && prev.toLowerCase() === name.toLowerCase() ? null : prev));
    await loadDocuments();
    toast.info(t('Folder “{name}” removed. Its sources were kept.', { name }));
  };

  const renameConversation = async (id: string, title: string) => {
    await api.renameConversation(id, title);
    setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, title } : c)));
    toast.success(t('Chat renamed.'));
  };

  const deleteConversation = async (id: string) => {
    await api.deleteConversation(id);
    setConversations((prev) => prev.filter((c) => c.id !== id));
    setConversationId((current) => (current === id ? null : current));
    toast.success(t('Chat deleted.'));
  };

  const changeStyle = (style: ResponseStyle) => {
    update({ response_style: style });
    toast.success(t('Answers will be written in the "{style}" style.', { style: t(styleLabel(style)) }));
  };

  const closeHistory = useCallback(() => setHistory({ open: false, focusSearch: false }), []);
  const newChat = () => {
    setConversationId(null);
    closeHistory();
  };
  const activeTitle = conversations.find((c) => c.id === conversationId)?.title ?? '';
  const shareChat = () =>
    conversationId && setShareTarget({ kind: 'conversation', ref: conversationId, label: activeTitle || t('This chat') });
  const askFromPanel = (text: string) => {
    setAskRequest({ id: Date.now(), text });
    if (isNarrow()) setLibraryOpen(false);
  };

  return (
    <div className={`workspace ${libraryOpen ? 'with-library' : ''}`}>
      <Rail
        user={user}
        account={account}
        usage={usage}
        hasConversation={!!conversationId}
        historyOpen={history.open}
        libraryOpen={libraryOpen}
        onNewChat={newChat}
        onShowChat={closeHistory}
        onToggleHistory={() => setHistory((h) => ({ open: !h.open, focusSearch: false }))}
        onToggleLibrary={() => setLibraryOpen((o) => !o)}
        onOpenSettings={(tab) => setSettingsTab(tab ?? 'general')}
        onUpgrade={() => openUpgrade()}
        onSignOut={api.signOut}
      />

      <div className="main">
        <TopBar
          documents={documents}
          selectedDocuments={selectedDocuments}
          activeTag={activeTag}
          activeFolder={activeFolder}
          onSelectTag={selectTag}
          onSelectFolder={selectFolder}
          onClearScope={clearScope}
          responseStyle={responseStyle}
          onStyleChange={changeStyle}
          plan={plan}
          onUpgrade={() => openUpgrade()}
          onOpenPlan={() => setSettingsTab('plan')}
          title={activeTitle}
          hasConversation={!!conversationId}
          libraryOpen={libraryOpen}
          onSearchChats={() => setHistory({ open: true, focusSearch: true })}
          onShareChat={shareChat}
          onNewChat={newChat}
          onToggleLibrary={() => setLibraryOpen((o) => !o)}
        />

        <div className="main-body">
          <ChatPanel
            documents={documents}
            selectedDocuments={selectedDocuments}
            activeTag={activeTag}
            activeFolder={activeFolder}
            responseStyle={responseStyle}
            sendWithEnter={prefs.send_with_enter}
            showSuggestions={prefs.show_suggestions}
            conversationId={conversationId}
            conversationTitle={activeTitle}
            askRequest={askRequest}
            onShareChat={shareChat}
            onViewSource={(filename, pageNumber) => setViewingSource({ filename, page: pageNumber })}
            onUploadFiles={guardedUpload}
            onUpgradeNeeded={openUpgrade}
            onConversationCreated={(id) => {
              setConversationId(id);
              loadConversations(); // the title is known as soon as the chat exists
            }}
            onActivity={refreshChats}
          />

          <LibraryPanel
            open={libraryOpen}
            documents={documents}
            selectedDocuments={selectedDocuments}
            activeTag={activeTag}
            activeFolder={activeFolder}
            showSuggestions={prefs.show_suggestions}
            queue={queue}
            onDismissUpload={dismiss}
            onUploadFiles={guardedUpload}
            onUploadLink={uploadLink}
            onUploadText={uploadText}
            onSelectTag={selectTag}
            onSelectFolder={selectFolder}
            onSetTags={setTags}
            onMoveToFolder={setFolderTarget}
            onRenameFolder={renameFolder}
            onDeleteFolder={deleteFolder}
            onShareDocument={(filename) => setShareTarget({ kind: 'document', ref: filename, label: filename })}
            onDocumentsChange={refreshDocuments}
            onToggleDocument={toggleDocument}
            onClearSelection={() => setSelectedDocuments([])}
            onAsk={askFromPanel}
            onClose={() => setLibraryOpen(false)}
          />
        </div>
      </div>

      {history.open && (
        <HistoryPanel
          conversations={conversations}
          activeId={conversationId}
          focusSearch={history.focusSearch}
          onSelect={(id) => {
            setConversationId(id);
            closeHistory();
          }}
          onNewChat={newChat}
          onRename={renameConversation}
          onDelete={deleteConversation}
          onClose={closeHistory}
        />
      )}

      {viewingSource && (
        <SourceViewer
          filename={viewingSource.filename}
          page={viewingSource.page}
          doc={documents.find((d) => d.filename === viewingSource.filename)}
          onClose={() => setViewingSource(null)}
        />
      )}
      {shareTarget && (
        <ShareDialog
          kind={shareTarget.kind}
          refName={shareTarget.ref}
          label={shareTarget.label}
          onClose={() => setShareTarget(null)}
        />
      )}
      {folderTarget && (
        <FolderDialog
          filenames={folderTarget}
          folders={[...new Map(documents.filter((d) => d.folder).map((d) => [d.folder!.toLowerCase(), d.folder!])).values()].sort(
            (a, b) => a.localeCompare(b),
          )}
          anyInFolder={documents.some((d) => folderTarget.includes(d.filename) && d.folder)}
          onSubmit={(folder) => moveToFolder(folderTarget, folder)}
          onClose={() => setFolderTarget(null)}
        />
      )}
      {settingsTab && (
        <SettingsDialog
          tab={settingsTab}
          user={user}
          account={account}
          usage={usage}
          onClose={() => setSettingsTab(null)}
          onUpgrade={() => {
            setSettingsTab(null);
            openUpgrade();
          }}
          onChanged={refreshEverything}
        />
      )}
      {upgrade && (
        <UpgradeDialog
          account={account}
          reason={upgrade.reason}
          onClose={() => setUpgrade(null)}
          onUpgraded={() => {
            refreshEverything();
            toast.success(t('Welcome to DocuQuery Pro! Your new limits are active.'));
          }}
        />
      )}
      {pendingImport && (
        <ImportDialog
          payload={pendingImport}
          onCancel={onImportHandled}
          onConfirm={(payload) => {
            uploadText({ title: payload.title, url: payload.url, text: payload.text });
            onImportHandled();
          }}
        />
      )}
    </div>
  );
}
