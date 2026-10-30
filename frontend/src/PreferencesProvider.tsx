/**
 * Holds the user's preferences: applies them at once, keeps them in this browser, and saves
 * them to the account shortly after each change.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import * as api from './api';
import { PreferencesContext, loadPreferences, mergePreferences, sanitizePreferences, savePreferences } from './preferences';
import type { Preferences, PreferencesApi } from './preferences';

const SAVE_DELAY_MS = 600;

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [prefs, setPrefs] = useState<Preferences>(loadPreferences);
  const [syncError, setSyncError] = useState('');
  const current = useRef(prefs);
  const pending = useRef<Partial<Preferences>>({});
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const commit = useCallback((next: Preferences) => {
    current.current = next;
    setPrefs(next);
    savePreferences(next);
  }, []);

  const flush = useCallback(async () => {
    clearTimeout(timer.current);
    const patch = pending.current;
    pending.current = {};
    if (!Object.keys(patch).length || !api.getSession()) return;
    try {
      await api.saveSettings(patch);
      setSyncError('');
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : 'Could not save your settings');
      throw err;
    }
  }, []);

  const update = useCallback<PreferencesApi['update']>(
    async (patch, options) => {
      commit(sanitizePreferences({ ...current.current, ...patch }));
      Object.assign(pending.current, patch);
      clearTimeout(timer.current);
      if (options?.immediate) return flush();
      timer.current = setTimeout(() => flush().catch(() => {}), SAVE_DELAY_MS);
    },
    [commit, flush],
  );

  const syncFromServer = useCallback(async () => {
    await flush().catch(() => {});
    const server = sanitizePreferences(await api.fetchSettings());
    const { merged, push } = mergePreferences(current.current, server);
    commit(merged);
    if (Object.keys(push).length) {
      Object.assign(pending.current, push);
      timer.current = setTimeout(() => flush().catch(() => {}), SAVE_DELAY_MS);
    }
  }, [commit, flush]);

  // Explicit light / dark is stamped on <html>; "system" leaves it off so the CSS follows the OS.
  useEffect(() => {
    const root = document.documentElement;
    if (prefs.theme === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', prefs.theme);
  }, [prefs.theme]);

  useEffect(() => () => clearTimeout(timer.current), []);

  const value = useMemo(() => ({ prefs, update, syncFromServer, syncError }), [prefs, update, syncFromServer, syncError]);
  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

