// Lists every English string passed to t() / tn() in the source, so none is forgotten in a translation.
//   node scripts/list-strings.mjs            → prints the strings
// The unit test in src/i18n/i18n.test.ts uses the same extraction to check the French dictionary is complete.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src');

function* walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(full);
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\./.test(entry.name) && !full.includes(`${path.sep}i18n${path.sep}`)) yield full;
  }
}

const STRING = String.raw`(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")`;
const single = new RegExp(String.raw`\b(?:t|msg)\(\s*${STRING}`, 'g');
const plural = new RegExp(String.raw`\btn\(\s*${STRING}\s*,\s*${STRING}`, 'g');

const unescape = (s) => s.replace(/\\(['"\\])/g, '$1').replace(/\\n/g, '\n');

export function extract() {
  const found = new Set();
  for (const file of walk(root)) {
    const text = fs.readFileSync(file, 'utf8');
    for (const m of text.matchAll(single)) found.add(unescape(m[1] ?? m[2]));
    for (const m of text.matchAll(plural)) {
      found.add(unescape(m[1] ?? m[2]));
      found.add(unescape(m[3] ?? m[4]));
    }
  }
  return [...found].sort((a, b) => a.localeCompare(b));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const strings = extract();
  console.log(JSON.stringify(strings, null, 1));
  console.error(`${strings.length} strings`);
}
