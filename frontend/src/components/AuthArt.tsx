/**
 * AuthArt — the abstract artwork behind the sign-in page: a black-to-white
 * gradient with glossy capsules, spheres and dotted grids. Pure SVG, so it
 * stays sharp at any size and costs no image download.
 */

import { useId } from 'react';

/** [x, y, length, thickness, gradient (0 dark→mid grey, 1 light→mid grey, 2 near-black)] */
const CAPSULES: [number, number, number, number, 0 | 1 | 2][] = [
  [560, 40, 380, 110, 2],
  [700, 150, 330, 100, 1],
  [380, 330, 420, 120, 2],
  [820, 330, 360, 100, 0],
  [560, 480, 400, 110, 1],
  [980, 560, 380, 120, 2],
  [180, 640, 340, 100, 0],
  [820, 720, 360, 110, 1],
  [-80, 380, 360, 110, 2],
  [1040, 60, 300, 90, 0],
];

/** [cx, cy, radius] */
const SPHERES: [number, number, number][] = [
  [900, 120, 42],
  [1070, 260, 54],
  [640, 250, 36],
  [760, 560, 48],
  [330, 90, 60],
  [1120, 640, 40],
];

/** [x, y, width, height] */
const DOTS: [number, number, number, number][] = [
  [30, 40, 130, 110],
  [540, 90, 150, 150],
  [980, 380, 180, 200],
  [60, 560, 170, 150],
];

export default function AuthArt({ className = '' }: { className?: string }) {
  const id = useId().replace(/:/g, '');
  const ref = (name: string) => `url(#${id}-${name})`;

  return (
    <svg
      className={className}
      viewBox="0 0 1200 800"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id={`${id}-bg`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#18181b" />
          <stop offset="0.45" stopColor="#6b6b75" />
          <stop offset="1" stopColor="#e4e4ea" />
        </linearGradient>
        <linearGradient id={`${id}-cap0`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#27272a" />
          <stop offset="1" stopColor="#a1a1aa" />
        </linearGradient>
        <linearGradient id={`${id}-cap1`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#f4f4f5" />
          <stop offset="1" stopColor="#71717a" />
        </linearGradient>
        <linearGradient id={`${id}-cap2`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#09090b" />
          <stop offset="1" stopColor="#3f3f46" />
        </linearGradient>
        <radialGradient id={`${id}-ball`} cx="0.3" cy="0.28" r="0.85">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="0.45" stopColor="#a1a1aa" />
          <stop offset="1" stopColor="#27272a" />
        </radialGradient>
        <pattern id={`${id}-dots`} width="16" height="16" patternUnits="userSpaceOnUse">
          <circle cx="2" cy="2" r="1.6" fill="#fff" />
        </pattern>
        <filter id={`${id}-shadow`} x="-20%" y="-20%" width="140%" height="150%">
          <feDropShadow dx="0" dy="16" stdDeviation="16" floodColor="#000000" floodOpacity="0.32" />
        </filter>
      </defs>

      <rect width="1200" height="800" fill={ref('bg')} />

      <g filter={ref('shadow')}>
        {CAPSULES.map(([x, y, length, thickness, tone], i) => (
          <rect
            key={i}
            x={x}
            y={y}
            width={length}
            height={thickness}
            rx={thickness / 2}
            fill={ref(`cap${tone}`)}
            transform={`rotate(-45 ${x + length / 2} ${y + thickness / 2})`}
          />
        ))}
        {SPHERES.map(([cx, cy, r], i) => (
          <circle key={i} cx={cx} cy={cy} r={r} fill={ref('ball')} />
        ))}
      </g>

      {DOTS.map(([x, y, w, h], i) => (
        <rect key={i} x={x} y={y} width={w} height={h} fill={ref('dots')} opacity="0.75" />
      ))}
    </svg>
  );
}
