/**
 * React context for translations: `const { t, tn, lang } = useI18n()`.
 * Outside a provider (tests, stories) it speaks English.
 */

import { createContext, useContext } from 'react';
import { translate, translatePlural } from './core';
import type { Lang, PluralTranslator, Translator } from './core';

export interface I18n {
  lang: Lang;
  t: Translator;
  tn: PluralTranslator;
}

export const english: I18n = {
  lang: 'en',
  t: (key, vars) => translate('en', key, vars),
  tn: (one, other, count, vars) => translatePlural('en', one, other, count, vars),
};

export const I18nContext = createContext<I18n>(english);

export function useI18n(): I18n {
  return useContext(I18nContext);
}
