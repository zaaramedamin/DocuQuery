/**
 * Upload queue shared by every way of adding a source: files, web links,
 * pasted text and pages sent from the browser button.
 *
 * Uploads run one at a time so embedding bursts don't hit API rate limits.
 * Each item reports real progress from the server.
 */

import { useCallback, useRef, useState } from 'react';
import * as api from '../api';
import { useI18n } from '../i18n';
import type { DocInfo, ImportPayload, UploadProgress } from '../types';
import { isAcceptedFile } from '../utils/format';

export interface QueueItem {
  key: string;
  label: string;
  percent: number;
  message: string;
  status: 'active' | 'done' | 'error';
}

const newKey = () => `${Date.now()}-${Math.random().toString(36).slice(2)}`;

export function useUploadQueue(
  onUploaded: (doc: DocInfo) => void,
  /** An upload failed: the error (an `ApiError` for plan limits) and the item's label. */
  onFailed?: (error: Error, label: string) => void,
) {
  const { t, tn } = useI18n();
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const chain = useRef<Promise<void>>(Promise.resolve());

  const patch = useCallback(
    (key: string, changes: Partial<QueueItem>) =>
      setQueue((items) => items.map((item) => (item.key === key ? { ...item, ...changes } : item))),
    [],
  );
  const dismiss = useCallback((key: string) => setQueue((items) => items.filter((item) => item.key !== key)), []);

  const enqueue = useCallback(
    (label: string, run: (onProgress: (p: UploadProgress) => void) => Promise<DocInfo>) => {
      const key = newKey();
      setQueue((items) => [...items, { key, label, percent: 0, message: t('Waiting…'), status: 'active' }]);

      chain.current = chain.current.then(async () => {
        patch(key, { message: t('Starting…') });
        try {
          const doc = await run((p) => patch(key, { percent: p.percent, message: p.message }));
          const warning = doc.warnings?.[0];
          patch(key, {
            percent: 100,
            status: 'done',
            message: warning ?? tn('Indexed {count} passage', 'Indexed {count} passages', doc.chunks_count),
          });
          onUploaded(doc);
          setTimeout(() => dismiss(key), warning ? 8000 : 3500);
        } catch (err) {
          const error = err instanceof Error ? err : new Error(t('Upload failed'));
          patch(key, { status: 'error', message: error.message });
          onFailed?.(error, label);
        }
      });
    },
    [dismiss, onFailed, onUploaded, patch, t, tn],
  );

  const uploadFiles = useCallback(
    (files: FileList | File[]) => {
      for (const file of Array.from(files)) {
        if (!isAcceptedFile(file.name)) {
          setQueue((items) => [
            ...items,
            { key: newKey(), label: file.name, percent: 0, status: 'error', message: t('Unsupported file type.') },
          ]);
          continue;
        }
        enqueue(file.name, (onProgress) => api.uploadFile(file, onProgress));
      }
    },
    [enqueue, t],
  );

  const uploadLink = useCallback(
    (input: string) => {
      let address = input.trim();
      if (!address) return;
      if (!/^https?:\/\//i.test(address)) address = `https://${address}`;
      enqueue(address.replace(/^https?:\/\//i, ''), (onProgress) => api.uploadUrl(address, onProgress));
    },
    [enqueue],
  );

  const uploadText = useCallback(
    (payload: Partial<ImportPayload> & { text: string }) => {
      enqueue(payload.title || t('Pasted text'), (onProgress) => api.uploadText(payload, onProgress));
    },
    [enqueue, t],
  );

  return { queue, dismiss, uploadFiles, uploadLink, uploadText };
}
