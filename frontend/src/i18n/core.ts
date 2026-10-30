/**
 * Translations (the plain functions; React bindings are in ./context and ./I18nProvider).
 *
 * The English text itself is the key: `t('Upload file')`. A string with no
 * French entry simply stays in English, so a missed translation never shows a
 * code. `{name}` placeholders are filled from the second argument, and `tn`
 * picks the singular or plural wording for a count.
 */

import { FR } from './fr';

export type Lang = 'en' | 'fr';
export type UiLanguage = 'auto' | Lang;
export type Vars = Record<string, string | number>;
export type Translator = (key: string, vars?: Vars) => string;
export type PluralTranslator = (one: string, other: string, count: number, vars?: Vars) => string;

export const LANGUAGES: { id: Lang; label: string }[] = [
  { id: 'en', label: 'English' },
  { id: 'fr', label: 'Français' },
];

const DICTIONARIES: Record<Lang, Record<string, string>> = { en: {}, fr: FR };

/** The supported language closest to the browser's setting (English when none matches). */
export function detectLanguage(browser: string | undefined = typeof navigator === 'undefined' ? 'en' : navigator.language): Lang {
  const code = (browser ?? 'en').toLowerCase().split('-')[0];
  return LANGUAGES.some((l) => l.id === code) ? (code as Lang) : 'en';
}

export function resolveLanguage(ui: UiLanguage, browser?: string): Lang {
  return ui === 'auto' ? detectLanguage(browser) : ui;
}

function fill(text: string, vars?: Vars): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name: string) => (name in vars ? String(vars[name]) : whole));
}

/**
 * Mark an English string for translation without translating it yet (labels kept in data
 * tables). Show it with `t(...)` later; the translation check picks it up from here.
 */
export function msg(text: string): string {
  return text;
}

export function translate(lang: Lang, key: string, vars?: Vars): string {
  return fill(DICTIONARIES[lang][key] ?? key, vars);
}

export function translatePlural(lang: Lang, one: string, other: string, count: number, vars?: Vars): string {
  const form = new Intl.PluralRules(lang).select(count) === 'one' ? one : other;
  return translate(lang, form, { count, ...vars });
}
