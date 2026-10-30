/**
 * Sort files by what the user's plan allows, before anything is sent.
 *
 *   accepted  fit the plan's per-file limit
 *   needsPro  too big for the Free plan, but Pro would take them → offer the upgrade
 *   tooLarge  too big for any plan
 *
 * The server enforces the same limits; this just spares a doomed upload.
 */

import type { Plan } from '../types';

export interface SizedFile {
  name: string;
  size: number;
}

export interface UploadCheck<T extends SizedFile> {
  accepted: T[];
  needsPro: T[];
  tooLarge: T[];
}

export function checkUploadSizes<T extends SizedFile>(
  files: T[],
  /** The user's per-file limit in bytes (unknown until the plan has loaded: then nothing is blocked). */
  limit: number | undefined,
  plan: Plan,
  /** The Pro plan's per-file limit in bytes. */
  proLimit: number | undefined,
): UploadCheck<T> {
  const result: UploadCheck<T> = { accepted: [], needsPro: [], tooLarge: [] };
  for (const file of files) {
    if (!limit || file.size <= limit) result.accepted.push(file);
    else if (plan === 'free' && proLimit && file.size <= proLimit) result.needsPro.push(file);
    else result.tooLarge.push(file);
  }
  return result;
}
