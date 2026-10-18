import type { CSSProperties } from 'react'
const paths = {
  circuit: <path d="M3 7h4l2-3 3 6 3-6 2 3h4M3 17h6m6 0h6M9 13v8m6-8v8M3 7v10m18-10v10" />,
  plus: <path d="M12 5v14M5 12h14" />,
  history: <path d="M4 8a9 9 0 1 1-1 6M4 3v5h5m3-1v5l3 2" />,
  settings: <><path d="m9 3-1 3-3 1 1 3-2 2 2 2-1 3 3 1 1 3h6l1-3 3-1-1-3 2-2-2-2 1-3-3-1-1-3Z" /><circle cx="12" cy="12" r="3" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-10v.2" /></>,
  arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
  image: <><rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="8" cy="8" r="1.5" /><path d="m3 17 5-5 4 4 4-5 5 6" /></>,
  file: <path d="M14 3H5v18h14V8Zm0 0v5h5M8 12h8m-8 4h6" />,
  download: <path d="M12 3v12m-5-5 5 5 5-5M4 15v5h16v-5" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  refresh: <path d="M20 8a9 9 0 0 0-15-3L3 8m0-5v5h5m-4 8a9 9 0 0 0 15 3l2-3m0 5v-5h-5" />,
  expand: <path d="M4 9V4h5m6 0h5v5M4 15v5h5m6 0h5v-5" />,
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
} as const
export default function Icon({ name, style }: { name: keyof typeof paths; style?: CSSProperties }) {
  return <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}>{paths[name]}</svg>
}
