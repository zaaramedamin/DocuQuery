/**
 * Rail — the narrow icon column on the left: new chat, current chat,
 * history, library, usage, settings and the account menu.
 */

import { useState } from 'react';
import type { ReactNode } from 'react';
import { House, MessageCircle, History, FolderOpen, Database, Settings, LogOut, Sparkles, UserRound } from 'lucide-react';
import { useI18n } from '../i18n';
import type { Account, AuthUser, Usage } from '../types';
import { useDismiss } from '../hooks/useDismiss';
import { formatBytes } from '../utils/format';
import Meter from './Meter';

interface RailProps {
  user: AuthUser;
  account: Account | null;
  usage: Usage | null;
  hasConversation: boolean;
  historyOpen: boolean;
  libraryOpen: boolean;
  onNewChat: () => void;
  onShowChat: () => void;
  onToggleHistory: () => void;
  onToggleLibrary: () => void;
  onOpenSettings: (tab?: 'plan' | 'account') => void;
  onUpgrade: () => void;
  onSignOut: () => void;
}

export default function Rail({
  user,
  account,
  usage,
  hasConversation,
  historyOpen,
  libraryOpen,
  onNewChat,
  onShowChat,
  onToggleHistory,
  onToggleLibrary,
  onOpenSettings,
  onUpgrade,
  onSignOut,
}: RailProps) {
  const { t } = useI18n();
  const [usageOpen, setUsageOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const usageRef = useDismiss<HTMLDivElement>(usageOpen, () => setUsageOpen(false));
  const accountRef = useDismiss<HTMLDivElement>(accountOpen, () => setAccountOpen(false));
  const displayName = account?.display_name || '';
  const initial = (displayName || user.email || '?').trim().charAt(0).toUpperCase();
  const isPro = (usage?.plan ?? account?.plan) === 'pro';

  return (
    <nav className="rail" aria-label={t('Main')}>
      <img src="/logo.svg?v=2" alt="DocuQuery" className="rail-logo" />

      <div className="rail-group">
        <RailButton label={t('New chat')} active={!hasConversation && !historyOpen} onClick={onNewChat}>
          <House size={19} />
        </RailButton>
        <RailButton
          label={t('Current chat')}
          active={hasConversation && !historyOpen}
          disabled={!hasConversation}
          onClick={onShowChat}
        >
          <MessageCircle size={19} />
        </RailButton>
        <RailButton label={t('Chat history')} active={historyOpen} onClick={onToggleHistory}>
          <History size={19} />
        </RailButton>
        <RailButton label={t('Library')} active={libraryOpen} onClick={onToggleLibrary} className="rail-library">
          <FolderOpen size={19} />
        </RailButton>

        <div className="rail-pop-anchor" ref={usageRef}>
          <RailButton label={t('Usage')} active={usageOpen} onClick={() => setUsageOpen((o) => !o)}>
            <Database size={19} />
          </RailButton>
          {usageOpen && (
            <div className="popover rail-popover" role="dialog" aria-label={t('Usage')}>
              <p className="popover-title">{t('Your usage')}</p>
              {usage ? (
                <>
                  <Meter label={t('Sources')} used={usage.documents.used} limit={usage.documents.limit} />
                  <Meter
                    label={t('Storage')}
                    used={usage.storage.used_bytes}
                    limit={usage.storage.limit_bytes}
                    format={formatBytes}
                  />
                  <Meter label={t('Questions today')} used={usage.questions_today.used} limit={usage.questions_today.limit} />
                  {!isPro && (
                    <button
                      className="menu-item menu-upgrade"
                      onClick={() => {
                        setUsageOpen(false);
                        onUpgrade();
                      }}
                    >
                      <Sparkles size={15} /> {t('Get more with Pro')}
                    </button>
                  )}
                </>
              ) : (
                <p className="popover-note">{t("Usage isn't available right now.")}</p>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="rail-group rail-bottom">
        <RailButton label={t('Settings')} onClick={() => onOpenSettings()}>
          <Settings size={19} />
        </RailButton>
        <div className="rail-pop-anchor" ref={accountRef}>
          <button
            className="rail-avatar"
            onClick={() => setAccountOpen((o) => !o)}
            aria-label={t('Account')}
            aria-expanded={accountOpen}
            title={displayName || user.email || t('Account')}
          >
            {initial}
            {isPro && <span className="avatar-pro" aria-hidden="true" />}
          </button>
          {accountOpen && (
            <div className="popover rail-popover rail-popover-bottom" role="menu">
              <p className="popover-title">{t('Signed in as')}</p>
              {displayName && <p className="popover-name">{displayName}</p>}
              <p className="popover-email">
                {user.email}
                <span className={`plan-badge small ${isPro ? 'pro' : ''}`}>{isPro ? 'Pro' : t('Free')}</span>
              </p>
              <button
                className="menu-item"
                role="menuitem"
                onClick={() => {
                  setAccountOpen(false);
                  onOpenSettings('account');
                }}
              >
                <UserRound size={15} /> {t('Account settings')}
              </button>
              {!isPro && (
                <button
                  className="menu-item menu-upgrade"
                  role="menuitem"
                  onClick={() => {
                    setAccountOpen(false);
                    onUpgrade();
                  }}
                >
                  <Sparkles size={15} /> {t('Upgrade to Pro')}
                </button>
              )}
              <button className="menu-item" role="menuitem" onClick={onSignOut} aria-label={t('Sign out')}>
                <LogOut size={15} /> {t('Sign out')}
              </button>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
}

function RailButton({
  label,
  active = false,
  disabled = false,
  onClick,
  className = '',
  children,
}: {
  label: string;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
  className?: string;
  children: ReactNode;
}) {
  return (
    <button
      className={`rail-btn ${active ? 'active' : ''} ${className}`}
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      aria-pressed={active}
      title={label}
    >
      {children}
    </button>
  );
}
