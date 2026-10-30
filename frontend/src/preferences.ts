/**
 * User preferences: language, theme, how answers are written, custom instructions…
 *
 * They are kept in this browser (so the sign-in screen already speaks the right
 * language and the theme has no flash) AND on the account, so they follow the
 * user to another device. Changes apply at once and are saved shortly after.
 */

import { createContext, useContext } from 'react';

export type Theme = 'system' | 'light' | 'dark';
export type UiLanguage = 'auto' | 'en' | 'fr';
export type ResponseStyle = 'normal' | 'casual' | 'explanatory' | 'formal';
export type AnswerLength = 'concise' | 'balanced' | 'detailed';

export interface Preferences {
  ui_language: UiLanguage;
  theme: Theme;
  response_style: ResponseStyle;
  /** Language the assistant answers in ('auto' = the language of the question). */
  answer_language: string;
  answer_length: AnswerLength;
  custom_instructions: string;
  send_with_enter: boolean;
  show_suggestions: boolean;
}

export const DEFAULT_PREFERENCES: Preferences = {
  ui_language: 'auto',
  theme: 'system',
  response_style: 'normal',
  answer_language: 'auto',
  answer_length: 'balanced',
  custom_instructions: '',
  send_with_enter: true,
  show_suggestions: true,
};

export const MAX_INSTRUCTIONS = 1000;

/** Languages the assistant can be asked to answer in (kept in sync with the backend). */
export const ANSWER_LANGUAGES: { id: string; label: string }[] = [
  { id: 'en', label: 'English' },
  { id: 'fr', label: 'Français' },
  { id: 'es', label: 'Español' },
  { id: 'de', label: 'Deutsch' },
  { id: 'it', label: 'Italiano' },
  { id: 'pt', label: 'Português' },
  { id: 'nl', label: 'Nederlands' },
  { id: 'ar', label: 'العربية' },
  { id: 'tr', label: 'Türkçe' },
  { id: 'ru', label: 'Русский' },
  { id: 'zh', label: '中文' },
  { id: 'ja', label: '日本語' },
  { id: 'ko', label: '한국어' },
  { id: 'hi', label: 'हिन्दी' },
];

const STORAGE_KEY = 'docuquery.preferences';
const OLD_STYLE_KEY = 'docuquery.responseStyle';

const ALLOWED: { [K in keyof Preferences]: (value: unknown) => boolean } = {
  ui_language: (v) => v === 'auto' || v === 'en' || v === 'fr',
  theme: (v) => v === 'system' || v === 'light' || v === 'dark',
  response_style: (v) => v === 'normal' || v === 'casual' || v === 'explanatory' || v === 'formal',
  answer_language: (v) => v === 'auto' || ANSWER_LANGUAGES.some((l) => l.id === v),
  answer_length: (v) => v === 'concise' || v === 'balanced' || v === 'detailed',
  custom_instructions: (v) => typeof v === 'string',
  send_with_enter: (v) => typeof v === 'boolean',
  show_suggestions: (v) => typeof v === 'boolean',
};

/** Keep only known preferences with valid values; everything else falls back to its default. */
export function sanitizePreferences(raw: unknown): Preferences {
  const result: Preferences = { ...DEFAULT_PREFERENCES };
  if (!raw || typeof raw !== 'object') return result;
  for (const key of Object.keys(ALLOWED) as (keyof Preferences)[]) {
    const value = (raw as Record<string, unknown>)[key];
    if (value !== undefined && ALLOWED[key](value)) {
      (result as unknown as Record<string, unknown>)[key] =
        key === 'custom_instructions' ? (value as string).slice(0, MAX_INSTRUCTIONS) : value;
    }
  }
  return result;
}

export function loadPreferences(): Preferences {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return sanitizePreferences(JSON.parse(stored));
    // The response style used to be stored on its own.
    return sanitizePreferences({ response_style: localStorage.getItem(OLD_STYLE_KEY) });
  } catch {
    return { ...DEFAULT_PREFERENCES };
  }
}

export function savePreferences(prefs: Preferences) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    /* storage unavailable: the choice lasts for this visit only */
  }
}

/**
 * Combine what this browser has with what the account has. The account wins,
 * except for a setting it never changed from the default: there the browser's
 * choice (made on the sign-in screen, say) is kept and sent up.
 */
export function mergePreferences(local: Preferences, server: Preferences): { merged: Preferences; push: Partial<Preferences> } {
  const merged = { ...server };
  const push: Partial<Preferences> = {};
  for (const key of Object.keys(DEFAULT_PREFERENCES) as (keyof Preferences)[]) {
    if (server[key] === DEFAULT_PREFERENCES[key] && local[key] !== DEFAULT_PREFERENCES[key]) {
      (merged as unknown as Record<string, unknown>)[key] = local[key];
      (push as Record<string, unknown>)[key] = local[key];
    }
  }
  return { merged, push };
}

export interface PreferencesApi {
  prefs: Preferences;
  /** Change settings. They apply now and are saved to the account (at once with `immediate`, else shortly after). */
  update: (patch: Partial<Preferences>, options?: { immediate?: boolean }) => Promise<void>;
  /** Load the account's settings (call after signing in). */
  syncFromServer: () => Promise<void>;
  /** Set when saving to the account failed (the choice is still kept on this device). */
  syncError: string;
}

export const PreferencesContext = createContext<PreferencesApi>({
  prefs: DEFAULT_PREFERENCES,
  update: async () => {},
  syncFromServer: async () => {},
  syncError: '',
});

export function usePreferences(): PreferencesApi {
  return useContext(PreferencesContext);
}
