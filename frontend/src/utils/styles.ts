/**
 * Response styles: how answers are written. The choice is part of the user's
 * preferences (see preferences.ts) and is sent with every question.
 */

import { msg } from '../i18n/core';
import type { ResponseStyle } from '../preferences';

export type { ResponseStyle };

/** Labels and descriptions are English keys (marked with msg): pass them through `t()` when shown. */
export const RESPONSE_STYLES: { id: ResponseStyle; label: string; description: string }[] = [
  { id: 'normal', label: msg('Normal'), description: msg('Balanced answers for everyday questions.') },
  { id: 'casual', label: msg('Casual'), description: msg('Relaxed and conversational, in short sentences.') },
  {
    id: 'explanatory',
    label: msg('Explanatory'),
    description: msg('Step-by-step answers for learning, with definitions and short examples.'),
  },
  { id: 'formal', label: msg('Formal'), description: msg('Precise and professional, for reports and work documents.') },
];

export function styleLabel(style: ResponseStyle): string {
  return RESPONSE_STYLES.find((s) => s.id === style)?.label ?? 'Normal';
}
