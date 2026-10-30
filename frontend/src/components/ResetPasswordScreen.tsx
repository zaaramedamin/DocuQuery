/**
 * Shown when the user opens the link from the "reset password" email.
 */

import { useState } from 'react';
import type { FormEvent } from 'react';
import { Lock, Loader2, AlertCircle } from 'lucide-react';
import * as api from '../api';
import { useI18n } from '../i18n';

export default function ResetPasswordScreen({
  accessToken,
  onDone,
}: {
  accessToken: string;
  /** Called after the password was changed (goes back to the sign-in screen). */
  onDone: () => void;
}) {
  const { t } = useI18n();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const mismatch = confirm.length > 0 && password !== confirm;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy || password.length < 8 || password !== confirm) return;
    setBusy(true);
    setError('');
    try {
      await api.resetPassword(accessToken, password);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('Something went wrong. Please try again.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={submit} noValidate>
        <div className="auth-brand">
          <img src="/logo.svg" alt="" className="logo-img" />
          <h1>
            Docu<span>Query</span>
          </h1>
        </div>
        <p className="auth-subtitle">{t('Choose a new password for your account.')}</p>

        {error && (
          <p className="auth-message error" role="alert">
            <AlertCircle size={15} /> {error}
          </p>
        )}

        <label className="auth-field">
          <span>{t('New password')}</span>
          <div className="auth-input">
            <Lock size={15} />
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t('At least 8 characters')}
              autoComplete="new-password"
              minLength={8}
              required
              autoFocus
            />
          </div>
        </label>

        <label className="auth-field">
          <span>{t('Confirm password')}</span>
          <div className="auth-input">
            <Lock size={15} />
            <input
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder={t('Type it again')}
              autoComplete="new-password"
              required
            />
          </div>
          {mismatch && <span className="field-error">{t("The passwords don't match.")}</span>}
        </label>

        <button className="auth-submit" type="submit" disabled={busy || password.length < 8 || password !== confirm}>
          {busy ? <Loader2 size={16} className="spin" /> : null}
          {t('Update password')}
        </button>
      </form>
    </div>
  );
}
