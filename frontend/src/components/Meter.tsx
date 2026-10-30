/**
 * Meter — a labelled usage bar ("Storage  12 MB of 200 MB"). A limit of 0 means unlimited.
 */

import { useI18n } from '../i18n';

export default function Meter({
  label,
  used,
  limit,
  format = String,
}: {
  label: string;
  used: number;
  limit: number;
  format?: (n: number) => string;
}) {
  const { t } = useI18n();
  const unlimited = limit <= 0;
  const ratio = unlimited ? 0 : Math.min(1, used / limit);
  return (
    <div className="meter">
      <div className="meter-label">
        <span>{label}</span>
        <span>{unlimited ? format(used) : t('{used} of {limit}', { used: format(used), limit: format(limit) })}</span>
      </div>
      <div className="meter-track">
        <div className={`meter-fill ${ratio >= 0.9 ? 'high' : ''}`} style={{ width: `${ratio * 100}%` }} />
      </div>
    </div>
  );
}
