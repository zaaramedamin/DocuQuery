/**
 * SettingsDialog — preferences and the account in one place: General, Personalization,
 * Account, Plan & usage and Data controls.
 */

import { useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import {
  Settings,
  SlidersHorizontal,
  UserRound,
  CreditCard,
  ShieldAlert,
  Sparkles,
  Loader2,
  Download,
  Trash2,
  LogOut,
  Sun,
  Moon,
  Monitor,
} from 'lucide-react';
import * as api from '../api';
import { LANGUAGES, useI18n } from '../i18n';
import { ANSWER_LANGUAGES, MAX_INSTRUCTIONS, usePreferences } from '../preferences';
import type { AnswerLength, Preferences, Theme, UiLanguage } from '../preferences';
import type { Account, AuthUser, Usage } from '../types';
import { downloadTextFile } from '../utils/exportChat';
import { formatBytes, formatPrice } from '../utils/format';
import { RESPONSE_STYLES } from '../utils/styles';
import Meter from './Meter';
import Modal from './Modal';
import { useConfirm, useToast } from '../hooks/useNotifications';

export type SettingsTab = 'general' | 'personalization' | 'account' | 'plan' | 'data';

interface SettingsDialogProps {
  tab: SettingsTab;
  user: AuthUser;
  account: Account | null;
  usage: Usage | null;
  onClose: () => void;
  onUpgrade: () => void;
  /** The name, plan or stored data changed: reload what's shown around the dialog. */
  onChanged: () => void;
}

export default function SettingsDialog(props: SettingsDialogProps) {
  const { t } = useI18n();
  const [tab, setTab] = useState<SettingsTab>(props.tab);

  const tabs: { id: SettingsTab; label: string; icon: ReactNode }[] = [
    { id: 'general', label: t('General'), icon: <Settings size={15} /> },
    { id: 'personalization', label: t('Personalization'), icon: <SlidersHorizontal size={15} /> },
    { id: 'account', label: t('Account'), icon: <UserRound size={15} /> },
    { id: 'plan', label: t('Plan & usage'), icon: <CreditCard size={15} /> },
    { id: 'data', label: t('Data controls'), icon: <ShieldAlert size={15} /> },
  ];

  return (
    <Modal title={t('Settings')} icon={<Settings size={16} />} onClose={props.onClose} wide flush>
      <div className="settings">
        <div className="settings-tabs" role="tablist" aria-label={t('Settings')}>
          {tabs.map((item) => (
            <button
              key={item.id}
              role="tab"
              aria-selected={tab === item.id}
              className={`settings-tab ${tab === item.id ? 'active' : ''}`}
              onClick={() => setTab(item.id)}
            >
              {item.icon} <span>{item.label}</span>
            </button>
          ))}
        </div>

        <div className="settings-panel" role="tabpanel">
          {tab === 'general' && <GeneralTab />}
          {tab === 'personalization' && <PersonalizationTab />}
          {tab === 'account' && <AccountTab {...props} />}
          {tab === 'plan' && <PlanTab {...props} />}
          {tab === 'data' && <DataTab {...props} />}
        </div>
      </div>
    </Modal>
  );
}

/* ── Building blocks ───────────────────────────────────────────────── */

function Row({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <div className="setting-row">
      <div className="setting-label">
        <strong>{title}</strong>
        {hint && <span>{hint}</span>}
      </div>
      <div className="setting-control">{children}</div>
    </div>
  );
}

function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className={`switch ${checked ? 'on' : ''}`}
      onClick={() => onChange(!checked)}
    >
      <span />
    </button>
  );
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { id: T; label: string; icon?: ReactNode }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={value === o.id}
          className={value === o.id ? 'on' : ''}
          onClick={() => onChange(o.id)}
        >
          {o.icon} {o.label}
        </button>
      ))}
    </div>
  );
}

/** Save a preference and tell the user if it could only be kept on this device. */
function useSave() {
  const { t } = useI18n();
  const { update } = usePreferences();
  const toast = useToast();
  return async (patch: Partial<Preferences>, message?: string) => {
    try {
      await update(patch, { immediate: true });
      if (message) toast.success(message);
    } catch {
      toast.warning(t("Saved on this device, but we couldn't reach the server. It will sync next time."));
    }
  };
}

/* ── General ───────────────────────────────────────────────────────── */

function GeneralTab() {
  const { t } = useI18n();
  const { prefs } = usePreferences();
  const save = useSave();

  return (
    <>
      <h4 className="settings-heading">{t('General')}</h4>
      <Row title={t('Language')} hint={t('The language of menus and buttons.')}>
        <select
          value={prefs.ui_language}
          onChange={(e) => save({ ui_language: e.target.value as UiLanguage })}
          aria-label={t('Language')}
        >
          <option value="auto">{t('Automatic (browser)')}</option>
          {LANGUAGES.map((l) => (
            <option key={l.id} value={l.id}>
              {l.label}
            </option>
          ))}
        </select>
      </Row>
      <Row title={t('Appearance')} hint={t('Light, dark, or follow your device.')}>
        <Segmented<Theme>
          label={t('Appearance')}
          value={prefs.theme}
          onChange={(theme) => save({ theme })}
          options={[
            { id: 'light', label: t('Light'), icon: <Sun size={14} /> },
            { id: 'dark', label: t('Dark'), icon: <Moon size={14} /> },
            { id: 'system', label: t('System'), icon: <Monitor size={14} /> },
          ]}
        />
      </Row>
      <Row title={t('Press Enter to send')} hint={t('When off, Enter adds a new line and Ctrl+Enter (⌘+Enter) sends.')}>
        <Switch
          label={t('Press Enter to send')}
          checked={prefs.send_with_enter}
          onChange={(send_with_enter) => save({ send_with_enter })}
        />
      </Row>
      <Row title={t('Show suggestions')} hint={t('Suggested tasks and questions based on your sources.')}>
        <Switch
          label={t('Show suggestions')}
          checked={prefs.show_suggestions}
          onChange={(show_suggestions) => save({ show_suggestions })}
        />
      </Row>
    </>
  );
}

/* ── Personalization ───────────────────────────────────────────────── */

function PersonalizationTab() {
  const { t } = useI18n();
  const { prefs } = usePreferences();
  const save = useSave();
  const [instructions, setInstructions] = useState(prefs.custom_instructions);
  const [saving, setSaving] = useState(false);
  const dirty = instructions.trim() !== prefs.custom_instructions.trim();

  const saveInstructions = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    await save({ custom_instructions: instructions.trim() }, t('Custom instructions saved.'));
    setSaving(false);
  };

  return (
    <>
      <h4 className="settings-heading">{t('Personalization')}</h4>

      <Row
        title={t('Response style')}
        hint={t(RESPONSE_STYLES.find((s) => s.id === prefs.response_style)?.description ?? '')}
      >
        <select
          value={prefs.response_style}
          onChange={(e) => save({ response_style: e.target.value as Preferences['response_style'] })}
          aria-label={t('Response style')}
        >
          {RESPONSE_STYLES.map((s) => (
            <option key={s.id} value={s.id}>
              {t(s.label)}
            </option>
          ))}
        </select>
      </Row>

      <Row title={t('Answer length')} hint={t('Shorter or more thorough answers.')}>
        <Segmented<AnswerLength>
          label={t('Answer length')}
          value={prefs.answer_length}
          onChange={(answer_length) => save({ answer_length })}
          options={[
            { id: 'concise', label: t('Concise') },
            { id: 'balanced', label: t('Balanced') },
            { id: 'detailed', label: t('Detailed') },
          ]}
        />
      </Row>

      <Row title={t('Answer language')} hint={t('The language DocuQuery writes in, whatever language your documents use.')}>
        <select
          value={prefs.answer_language}
          onChange={(e) => save({ answer_language: e.target.value })}
          aria-label={t('Answer language')}
        >
          <option value="auto">{t('Same as my question')}</option>
          {ANSWER_LANGUAGES.map((l) => (
            <option key={l.id} value={l.id}>
              {l.label}
            </option>
          ))}
        </select>
      </Row>

      <form className="instructions" onSubmit={saveInstructions}>
        <div className="setting-label">
          <strong>{t('Custom instructions')}</strong>
          <span>{t('Anything DocuQuery should always keep in mind, like your role or the format you like.')}</span>
        </div>
        <textarea
          value={instructions}
          onChange={(e) => setInstructions(e.target.value.slice(0, MAX_INSTRUCTIONS))}
          rows={5}
          placeholder={t('e.g. I am a lawyer. Use bullet points and cite clause numbers.')}
          aria-label={t('Custom instructions')}
        />
        <div className="instructions-foot">
          <span className="char-count">
            {instructions.length}/{MAX_INSTRUCTIONS}
          </span>
          <button className="btn btn-ink" type="submit" disabled={!dirty || saving}>
            {saving ? <Loader2 size={14} className="spin" /> : null} {t('Save instructions')}
          </button>
        </div>
      </form>
    </>
  );
}

/* ── Account ───────────────────────────────────────────────────────── */

function AccountTab({ user, account, onChanged, onClose }: SettingsDialogProps) {
  const { t } = useI18n();
  const toast = useToast();
  const [name, setName] = useState(account?.display_name ?? '');
  const [savingName, setSavingName] = useState(false);
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [again, setAgain] = useState('');
  const [changing, setChanging] = useState(false);
  const [passwordError, setPasswordError] = useState('');

  const initial = (name || user.email || '?').trim().charAt(0).toUpperCase();

  const saveName = async (e: FormEvent) => {
    e.preventDefault();
    setSavingName(true);
    try {
      const saved = await api.updateDisplayName(name.trim());
      setName(saved);
      onChanged();
      toast.success(saved ? t('Your name was updated.') : t('Your name was removed.'));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('Could not save your name'));
    } finally {
      setSavingName(false);
    }
  };

  const savePassword = async (e: FormEvent) => {
    e.preventDefault();
    setPasswordError('');
    if (next.length < 8) return setPasswordError(t('The new password needs at least 8 characters.'));
    if (next !== again) return setPasswordError(t("The two new passwords don't match."));
    setChanging(true);
    try {
      await api.changePassword(current, next);
      setCurrent('');
      setNext('');
      setAgain('');
      toast.success(t('Password changed.'));
    } catch (err) {
      setPasswordError(err instanceof Error ? err.message : t('Could not change the password'));
    } finally {
      setChanging(false);
    }
  };

  return (
    <>
      <h4 className="settings-heading">{t('Account')}</h4>

      <form className="account-profile" onSubmit={saveName}>
        <span className="avatar-lg" aria-hidden="true">
          {initial}
        </span>
        <div className="account-fields">
          <label>
            <span>{t('Display name')}</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={60}
              placeholder={t('How should we call you?')}
            />
          </label>
          <label>
            <span>{t('Email')}</span>
            <input value={user.email ?? ''} readOnly aria-readonly="true" />
          </label>
        </div>
        <button className="btn btn-ink" type="submit" disabled={savingName || name.trim() === (account?.display_name ?? '')}>
          {savingName ? <Loader2 size={14} className="spin" /> : null} {t('Save')}
        </button>
      </form>

      <h4 className="settings-subheading">{t('Change password')}</h4>
      <form className="password-form" onSubmit={savePassword}>
        <label>
          <span>{t('Current password')}</span>
          <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
        </label>
        <label>
          <span>{t('New password')}</span>
          <input
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            autoComplete="new-password"
            placeholder={t('At least 8 characters')}
          />
        </label>
        <label>
          <span>{t('Repeat the new password')}</span>
          <input type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" />
        </label>
        {passwordError && (
          <p className="field-error" role="alert">
            {passwordError}
          </p>
        )}
        <button className="btn btn-ink" type="submit" disabled={changing || !current || !next || !again}>
          {changing ? <Loader2 size={14} className="spin" /> : null} {t('Update password')}
        </button>
      </form>

      <div className="settings-foot">
        <button
          className="btn btn-outline"
          onClick={() => {
            onClose();
            api.signOut();
          }}
        >
          <LogOut size={14} /> {t('Sign out')}
        </button>
      </div>
    </>
  );
}

/* ── Plan & usage ──────────────────────────────────────────────────── */

function PlanTab({ account, usage, onUpgrade, onChanged }: SettingsDialogProps) {
  const { t, lang } = useI18n();
  const toast = useToast();
  const confirm = useConfirm();
  const [busy, setBusy] = useState(false);

  const isPro = (usage?.plan ?? account?.plan) === 'pro';
  const price = account ? formatPrice(account.billing.price_cents, account.billing.currency, lang) : '';
  const renews = account?.subscription.renews_at ? new Date(account.subscription.renews_at).toLocaleDateString(lang) : '';

  const backToFree = async () => {
    const ok = await confirm({
      title: t('Go back to the Free plan?'),
      message: t('This is a demo, so nothing was charged. You can try Pro again at any time.'),
      confirmLabel: t('Switch to Free'),
    });
    if (!ok) return;
    setBusy(true);
    try {
      await api.switchPlan('free');
      onChanged();
      toast.info(t('You are on the Free plan again.'));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('Could not change the plan'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h4 className="settings-heading">{t('Plan & usage')}</h4>

      <div className={`plan-card ${isPro ? 'is-pro' : ''}`}>
        <div>
          <span className={`plan-badge ${isPro ? 'pro' : ''}`}>{isPro ? 'Pro' : t('Free')}</span>
          <p className="plan-line">
            {isPro
              ? account?.subscription.cancel_at_period_end && renews
                ? t('Your Pro plan ends on {date}. It will not renew.', { date: renews })
                : renews
                  ? t('{price} / month. Renews on {date}.', { price, date: renews })
                  : t('{price} / month.', { price })
              : t('Files up to {size}. Upgrade for bigger files, more sources and more questions.', {
                  size: formatBytes(usage?.max_upload_bytes ?? account?.limits.free.max_upload_bytes ?? 0),
                })}
          </p>
        </div>
        {isPro ? (
          <button className="btn btn-outline" onClick={backToFree} disabled={busy}>
            {t('Switch to Free')}
          </button>
        ) : (
          <button className="btn btn-pro" onClick={onUpgrade}>
            <Sparkles size={14} /> {t('Upgrade to Pro')}
          </button>
        )}
      </div>

      <h4 className="settings-subheading">{t('Your usage')}</h4>
      {usage ? (
        <div className="usage-list">
          <Meter label={t('Sources')} used={usage.documents.used} limit={usage.documents.limit} />
          <Meter label={t('Storage')} used={usage.storage.used_bytes} limit={usage.storage.limit_bytes} format={formatBytes} />
          <Meter label={t('Questions today')} used={usage.questions_today.used} limit={usage.questions_today.limit} />
        </div>
      ) : (
        <p className="modal-note">{t("Usage isn't available right now.")}</p>
      )}
    </>
  );
}

/* ── Data controls ─────────────────────────────────────────────────── */

function DataTab({ onChanged, onClose }: SettingsDialogProps) {
  const { t, tn } = useI18n();
  const toast = useToast();
  const confirm = useConfirm();
  const [busy, setBusy] = useState<'' | 'export' | 'chats' | 'sources' | 'account'>('');
  const [deleting, setDeleting] = useState(false);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const exportData = async () => {
    setBusy('export');
    try {
      const blob = await api.exportData();
      downloadTextFile('docuquery-export.json', await blob.text(), 'application/json');
      toast.success(t('Your data was exported.'));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('Could not export your data'));
    } finally {
      setBusy('');
    }
  };

  const removeChats = async () => {
    const ok = await confirm({
      title: t('Delete all chats?'),
      message: t('Every saved conversation, and the links you shared to them, will be deleted. Your sources stay.'),
      confirmLabel: t('Delete all chats'),
      danger: true,
    });
    if (!ok) return;
    setBusy('chats');
    try {
      const count = await api.deleteAllChats();
      onChanged();
      toast.success(tn('{count} chat deleted.', '{count} chats deleted.', count));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('Could not delete your chats'));
    } finally {
      setBusy('');
    }
  };

  const removeSources = async () => {
    const ok = await confirm({
      title: t('Delete all sources?'),
      message: t('Every source in your library, with its search index and stored file, will be deleted. Your chats stay.'),
      confirmLabel: t('Delete all sources'),
      danger: true,
    });
    if (!ok) return;
    setBusy('sources');
    try {
      const count = await api.deleteAllDocuments();
      onChanged();
      toast.success(tn('{count} source deleted.', '{count} sources deleted.', count));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('Could not delete your sources'));
    } finally {
      setBusy('');
    }
  };

  const removeAccount = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    const ok = await confirm({
      title: t('Delete your account for good?'),
      message: t('Your sources, chats, shared links and settings will be erased and cannot be recovered.'),
      confirmLabel: t('Delete my account'),
      danger: true,
    });
    if (!ok) return;
    setBusy('account');
    try {
      await api.deleteAccount(password);
      onClose();
      toast.info(t('Your account was deleted.'));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('Could not delete the account'));
      setBusy('');
    }
  };

  return (
    <>
      <h4 className="settings-heading">{t('Data controls')}</h4>

      <Row title={t('Export your data')} hint={t('Download your sources list, chats and settings as a JSON file.')}>
        <button className="btn btn-outline" onClick={exportData} disabled={busy !== ''}>
          {busy === 'export' ? <Loader2 size={14} className="spin" /> : <Download size={14} />} {t('Export')}
        </button>
      </Row>

      <h4 className="settings-subheading danger-zone">{t('Danger zone')}</h4>
      <Row title={t('Delete all chats')} hint={t('Keeps your sources.')}>
        <button className="btn btn-danger" onClick={removeChats} disabled={busy !== ''}>
          {busy === 'chats' ? <Loader2 size={14} className="spin" /> : <Trash2 size={14} />} {t('Delete')}
        </button>
      </Row>
      <Row title={t('Delete all sources')} hint={t('Keeps your chats.')}>
        <button className="btn btn-danger" onClick={removeSources} disabled={busy !== ''}>
          {busy === 'sources' ? <Loader2 size={14} className="spin" /> : <Trash2 size={14} />} {t('Delete')}
        </button>
      </Row>
      <Row title={t('Delete account')} hint={t('Erases everything and closes your account.')}>
        {!deleting ? (
          <button className="btn btn-danger" onClick={() => setDeleting(true)} disabled={busy !== ''}>
            <Trash2 size={14} /> {t('Delete account')}
          </button>
        ) : (
          <form className="delete-account" onSubmit={removeAccount}>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t('Type your password to confirm')}
              aria-label={t('Password')}
              autoComplete="current-password"
              autoFocus
            />
            <button className="btn btn-danger-solid" type="submit" disabled={!password || busy !== ''}>
              {busy === 'account' ? <Loader2 size={14} className="spin" /> : null} {t('Delete my account')}
            </button>
            {error && (
              <p className="field-error" role="alert">
                {error}
              </p>
            )}
          </form>
        )}
      </Row>
    </>
  );
}
