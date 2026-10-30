/**
 * Sign in / create account / "forgot password" screen, shown until a session exists.
 * `embedded` renders just the card (used inside the shared-link page).
 */

import { useState } from 'react';
import type { FormEvent } from 'react';
import { Mail, Lock, Loader2, AlertCircle, Check, ArrowLeft, Globe } from 'lucide-react';
import * as api from '../api';
import AuthArt from './AuthArt';
import { LANGUAGES, useI18n } from '../i18n';
import { usePreferences } from '../preferences';
import type { UiLanguage } from '../preferences';

type Mode = 'login' | 'signup' | 'forgot';

interface AuthScreenProps {
  embedded?: boolean;
  /** Message shown above the form (e.g. "Password updated — sign in"). */
  notice?: string;
  /** Error shown above the form (e.g. "That reset link has expired"). */
  error?: string;
}

function LanguagePicker() {
  const { t } = useI18n();
  const { prefs, update } = usePreferences();
  return (
    <label className="auth-lang">
      <Globe size={13} />
      <select
        value={prefs.ui_language}
        onChange={(e) => update({ ui_language: e.target.value as UiLanguage })}
        aria-label={t('Language')}
      >
        <option value="auto">{t('Automatic (browser)')}</option>
        {LANGUAGES.map((l) => (
          <option key={l.id} value={l.id}>
            {l.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function AuthScreen({ embedded = false, notice: initialNotice = '', error: initialError = '' }: AuthScreenProps) {
  const { t } = useI18n();
  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(initialError);
  const [notice, setNotice] = useState(initialNotice);

  const switchMode = (next: Mode) => {
    setMode(next);
    setError('');
    setNotice('');
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setError('');
    setNotice('');
    setBusy(true);
    try {
      if (mode === 'login') {
        await api.login(email.trim(), password); // success → App swaps this screen out
      } else if (mode === 'forgot') {
        await api.forgotPassword(email.trim());
        setNotice(
          t('If an account exists for {email}, a reset link is on its way. Check your inbox (and spam).', {
            email: email.trim(),
          }),
        );
      } else if (await api.signup(email.trim(), password)) {
        setMode('login');
        setPassword('');
        setNotice(t('Account created! Check your inbox and click the confirmation link, then sign in.'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('Something went wrong. Please try again.'));
    } finally {
      setBusy(false);
    }
  };

  const isSignup = mode === 'signup';
  const isForgot = mode === 'forgot';
  const split = !embedded; // the full page has the artwork; the embedded card (share page) stays plain

  const subtitle = isForgot
    ? t("Enter your email and we'll send you a link to choose a new password.")
    : isSignup
      ? t('Create your private document library.')
      : t('Sign in to your private document library.');

  const form = (
    <form className={split ? 'auth-form' : 'auth-card'} onSubmit={submit} noValidate>
      {split ? (
        <div className="auth-heading">
          <p className="auth-welcome">{t('Welcome to')}</p>
          <h1 className="auth-title">DocuQuery</h1>
          <p className="auth-subtitle">{subtitle}</p>
        </div>
      ) : (
        <>
          <div className="auth-brand">
            <img src="/logo.svg" alt="" className="logo-img" />
            <h1>
              Docu<span>Query</span>
            </h1>
          </div>
          <p className="auth-subtitle">{subtitle}</p>
        </>
      )}

      {split && !isForgot && (
        <div className="auth-tabs" role="tablist">
          <button type="button" role="tab" aria-selected={!isSignup} className={!isSignup ? 'active' : ''} onClick={() => switchMode('login')}>
            {t('Sign in')}
          </button>
          <button type="button" role="tab" aria-selected={isSignup} className={isSignup ? 'active' : ''} onClick={() => switchMode('signup')}>
            {t('Create account')}
          </button>
        </div>
      )}

      {notice && (
        <p className="auth-message success" role="status">
          <Check size={15} /> {notice}
        </p>
      )}
      {error && (
        <p className="auth-message error" role="alert">
          <AlertCircle size={15} /> {error}
        </p>
      )}

      <div className="auth-fields">
        <label className="auth-field">
          <span>{t('Email')}</span>
          <div className="auth-input">
            <Mail size={15} />
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
              required
              autoFocus={!embedded}
            />
          </div>
        </label>

        {!isForgot && (
          <label className="auth-field">
            <span>{t('Password')}</span>
            <div className="auth-input">
              <Lock size={15} />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={isSignup ? t('At least 8 characters') : t('Your password')}
                autoComplete={isSignup ? 'new-password' : 'current-password'}
                minLength={8}
                required
              />
            </div>
          </label>
        )}
      </div>

      {mode === 'login' && (
        <button type="button" className="forgot-link" onClick={() => switchMode('forgot')}>
          {t('Forgot password?')}
        </button>
      )}

      {split ? (
        <div className="auth-actions">
          <button className="auth-submit" type="submit" disabled={busy || !email.trim() || (!isForgot && password.length < 8)}>
            {busy ? <Loader2 size={16} className="spin" /> : null}
            {isForgot ? t('Send reset link') : isSignup ? t('Create account') : t('Sign in')}
          </button>
          <button type="button" className="auth-secondary" onClick={() => switchMode(isForgot || isSignup ? 'login' : 'signup')}>
            {isForgot ? (
              <>
                <ArrowLeft size={13} /> {t('Back to sign in')}
              </>
            ) : isSignup ? (
              t('Sign in')
            ) : (
              t('Create account')
            )}
          </button>
        </div>
      ) : (
        <>
          <button className="auth-submit" type="submit" disabled={busy || !email.trim() || (!isForgot && password.length < 8)}>
            {busy ? <Loader2 size={16} className="spin" /> : null}
            {isForgot ? t('Send reset link') : isSignup ? t('Create account') : t('Sign in')}
          </button>
          {isForgot ? (
            <p className="auth-switch">
              <button type="button" onClick={() => switchMode('login')}>
                <ArrowLeft size={12} style={{ verticalAlign: -1 }} /> {t('Back to sign in')}
              </button>
            </p>
          ) : (
            <p className="auth-switch">
              {isSignup ? t('Already have an account?') : t('New to DocuQuery?')}{' '}
              <button type="button" onClick={() => switchMode(isSignup ? 'login' : 'signup')}>
                {isSignup ? t('Sign in') : t('Create an account')}
              </button>
            </p>
          )}
        </>
      )}
      <LanguagePicker />
    </form>
  );

  if (embedded) return form;

  return (
    <div className="auth-screen auth-split">
      <AuthArt className="auth-backdrop" />
      <div className="auth-panel">
        <AuthArt className="auth-panel-art" />
        <svg className="auth-wave" viewBox="0 0 1000 560" preserveAspectRatio="none" aria-hidden="true" focusable="false">
          <path d="M0,0 H452 C548,58 484,136 462,200 C436,278 580,304 538,404 C512,470 484,512 496,560 H0 Z" />
        </svg>
        <span className="auth-corner">
          <img src="/logo.svg" alt="DocuQuery" />
        </span>
        {form}
        <p className="auth-hero" aria-hidden="true">
          {t('Ask your\ndocuments\nanything.')}
        </p>
      </div>
    </div>
  );
}
