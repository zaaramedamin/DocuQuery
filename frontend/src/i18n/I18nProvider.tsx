/**
 * Provides the translations for the language chosen in the preferences.
 */

import { useEffect, useMemo } from 'react';
import type { ReactNode } from 'react';
import { usePreferences } from '../preferences';
import { resolveLanguage, translate, translatePlural } from './core';
import { I18nContext } from './context';
import type { I18n } from './context';

export function I18nProvider({ children }: { children: ReactNode }) {
  const { prefs } = usePreferences();
  const lang = resolveLanguage(prefs.ui_language);

  const value = useMemo<I18n>(
    () => ({
      lang,
      t: (key, vars) => translate(lang, key, vars),
      tn: (one, other, count, vars) => translatePlural(lang, one, other, count, vars),
    }),
    [lang],
  );

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
