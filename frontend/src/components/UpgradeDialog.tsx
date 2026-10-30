/**
 * UpgradeDialog — Free vs Pro, with the button that starts the $10/month subscription.
 * `reason` is shown when the user got here by hitting a limit (a file over 10 MB, a full library…).
 */

import { useState } from 'react';
import { AlertCircle, Check, Loader2, Sparkles, Lock } from 'lucide-react';
import * as api from '../api';
import { useI18n } from '../i18n';
import type { Account, PlanLimits } from '../types';
import { formatBytes, formatPrice } from '../utils/format';
import Modal from './Modal';

export default function UpgradeDialog({
  account,
  reason,
  onClose,
  onUpgraded,
}: {
  account: Account | null;
  /** Why the user is being offered Pro right now (e.g. "report.pdf is 14 MB…"); empty when they opened it themselves. */
  reason: string;
  onClose: () => void;
  /** The plan changed: reload the account. */
  onUpgraded: () => void;
}) {
  const { t, lang } = useI18n();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const upgrade = async () => {
    setBusy(true);
    setError('');
    try {
      await api.switchPlan('pro');
      onUpgraded();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('Could not change the plan'));
      setBusy(false);
    }
  };

  const price = account ? formatPrice(account.billing.price_cents, account.billing.currency, lang) : '';
  const free = account?.limits.free;
  const pro = account?.limits.pro;

  return (
    <Modal title={t('Upgrade to DocuQuery Pro')} icon={<Sparkles size={16} />} onClose={onClose} wide>
      {reason && (
        <p className="upgrade-reason" role="alert">
          <AlertCircle size={16} /> {reason}
        </p>
      )}

      {!account || !free || !pro ? (
        <p className="modal-note">
          <Loader2 size={14} className="spin" /> {t('Loading…')}
        </p>
      ) : account.plan === 'pro' ? (
        <p className="auth-message success" role="status">
          <Check size={15} /> {t('You already have DocuQuery Pro. Thank you!')}
        </p>
      ) : (
        <>
          <div className="plan-compare">
            <PlanColumn title={t('Free')} price={t('$0')} limits={free} />
            <PlanColumn title="Pro" price={t('{price} / month', { price })} limits={pro} highlight />
          </div>

          {error && (
            <p className="auth-message error" role="alert">
              <AlertCircle size={15} /> {error}
            </p>
          )}

          {account.billing.available ? (
            <>
              <button className="btn btn-pro btn-lg btn-block" onClick={upgrade} disabled={busy}>
                {busy ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}
                {t('Try Pro (demo, no payment)')}
              </button>
              <p className="modal-note small upgrade-fine">
                <Lock size={12} /> {t('Demo only: nothing is charged, and you can switch back to Free at any time.')}
              </p>
            </>
          ) : (
            <p className="auth-message error" role="status">
              <AlertCircle size={15} /> {t('Upgrading to Pro is not available right now.')}
            </p>
          )}
        </>
      )}
    </Modal>
  );
}

function PlanColumn({
  title,
  price,
  limits,
  highlight = false,
}: {
  title: string;
  price: string;
  limits: PlanLimits;
  highlight?: boolean;
}) {
  const { t } = useI18n();
  const rows: [string, string][] = [
    [t('File size'), t('up to {size}', { size: formatBytes(limits.max_upload_bytes) })],
    [t('Sources'), String(limits.documents)],
    [t('Storage'), formatBytes(limits.storage_bytes)],
    [t('Questions a day'), limits.daily_questions.toLocaleString()],
    [t('Scanned pages read per file'), String(limits.ocr_pages)],
  ];
  return (
    <section className={`plan-col ${highlight ? 'plan-col-pro' : ''}`}>
      <h4>{title}</h4>
      <p className="plan-price">{price}</p>
      <ul>
        {rows.map(([label, value]) => (
          <li key={label}>
            <Check size={13} /> <span>{label}</span>
            <strong>{value}</strong>
          </li>
        ))}
      </ul>
    </section>
  );
}
