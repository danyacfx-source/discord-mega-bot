const P = {
  home: <path d="M3 10.5 12 3l9 7.5M5 9.5V21h14V9.5M9.5 21v-6h5v6" />,
  server: (
    <>
      <path d="M3 4.5h18v6H3zM3 13.5h18v6H3zM6.5 7.5h2M6.5 16.5h2" />
    </>
  ),
  shield: <path d="m12 3 7 3v5.5c0 4.6-3 7.7-7 9.5-4-1.8-7-4.9-7-9.5V6l7-3z" />,
  gift: (
    <path d="M4 11.5h16V20H4zM3 7.5h18v4H3zM12 7.5V20M12 7.5c-1.5-3.5-6-3.5-6-1s3.5 1.5 6 1zM12 7.5c1.5-3.5 6-3.5 6-1s-3.5 1.5-6 1z" />
  ),
  ticket: <path d="M4 8.5A2.5 2.5 0 0 1 6.5 6h11A2.5 2.5 0 0 1 20 8.5v2a2 2 0 0 0 0 4v1a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 15.5v-1a2 2 0 0 0 0-4v-2zM14 6.5v11" />,
  eraser: <path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21H7zM5 11l8 8M22 21H7" />,
  pie: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 3v9h9" />
    </>
  ),
  cake: (
    <path d="M4 21.5h16v-7.5a3 3 0 0 0-3-3H7a3 3 0 0 0-3 3v7.5zM4 17.2c1.5 1.2 2.5 1.2 4 0s2.5-1.2 4 0 2.5 1.2 4 0 2.5-1.2 4 0M12 11V7.5M12 4.2a1.4 1.4 0 0 0-1.4 1.4c0 .8 1.4 1.9 1.4 1.9s1.4-1.1 1.4-1.9A1.4 1.4 0 0 0 12 4.2z" />
  ),
  speaker: <path d="M11 5 6.5 9H3v6h3.5L11 19V5zM15.5 9a4.5 4.5 0 0 1 0 6M18.5 6.5a8.5 8.5 0 0 1 0 11" />,
  monitor: <path d="M3 5h18v11.5H3zM9 20.5h6M12 16.5v4" />,
  bot: <path d="M12 3v2.5M6 5.5h12a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7.5a2 2 0 0 1 2-2zM9 11v1.6M15 11v1.6M9.5 15.3h5" />,
  "file-text": <path d="M6 3h8l4 4v14H6zM14 3v4h4M9 12.5h6M9 16.5h6" />,
  "user-plus": (
    <>
      <circle cx="9" cy="7.5" r="3.6" />
      <path d="M3 20.5a6 6 0 0 1 12 0M19 8v6M22 11h-6" />
    </>
  ),
  layout: <path d="M3 5.5h18v13H3zM3 10.2h18M15 10.2v8.3" />,
  cards: (
    <>
      <rect x="7.5" y="4" width="12.5" height="13" rx="1.6" />
      <path d="M4 7.5v11A1.5 1.5 0 0 0 5.5 20H17" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5.2l3.2 1.9" />
    </>
  ),
  sliders: <path d="M4 7h16M4 12h16M4 17h16" />,
  flask: <path d="M9 3h6M10 3v6.2L5.2 18.6A2 2 0 0 0 7 21.5h10a2 2 0 0 0 1.8-2.9L14 9.2V3M7.6 15.5h8.8" />,
  image: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <circle cx="8.5" cy="10" r="1.5" />
      <path d="M21 16.5 15.5 11 7 19" />
    </>
  ),
  eye: <path d="M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12z" />,
  trending: <path d="m3 17 6-6 4 4 8-8M15 7h6v6" />,
  database: (
    <>
      <path d="M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m16.5 16.5 4.5 4.5" />
    </>
  ),
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.1 5.1l1.8 1.8M17.1 17.1l1.8 1.8M5.1 18.9l1.8-1.8M17.1 6.9l1.8-1.8" />
    </>
  ),
  moon: <path d="M20.5 14.5A8.5 8.5 0 1 1 9.5 3.5a7 7 0 0 0 11 11z" />,
  "log-out": <path d="M9 21H5.5A1.5 1.5 0 0 1 4 19.5v-15A1.5 1.5 0 0 1 5.5 3H9M16 17l5-5-5-5M21 12H9" />,
  activity: <path d="M3 12h4l3-8 4 16 3-8h4" />,
  cpu: (
    <>
      <rect x="6.5" y="6.5" width="11" height="11" rx="1.5" />
      <rect x="10" y="10" width="4" height="4" />
      <path d="M9.5 2.5v4M14.5 2.5v4M9.5 17.5v4M14.5 17.5v4M2.5 9.5h4M2.5 14.5h4M17.5 9.5h4M17.5 14.5h4" />
    </>
  ),
  users: (
    <>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M3 20a6 6 0 0 1 12 0M16 4.8a3.5 3.5 0 0 1 0 6.9M17.5 14.4A6 6 0 0 1 21 20" />
    </>
  ),
  message: <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 3.8V16H6.5A2.5 2.5 0 0 1 4 13.5z" />,
  banknote: (
    <>
      <rect x="3" y="6.5" width="18" height="11" rx="2" />
      <circle cx="12" cy="12" r="2.4" />
      <path d="M6.5 10v4M17.5 10v4" />
    </>
  ),
  alert: <path d="M12 4 2.8 20h18.4L12 4zM12 10.2v4M12 17.2v.1" />,
  bell: <path d="M18 9.5a6 6 0 1 0-12 0c0 4.8-2 6.2-2 6.2h16s-2-1.4-2-6.2zM10.2 19.8a2 2 0 0 0 3.6 0" />,
  "circle-x": (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m9.2 9.2 5.6 5.6M14.8 9.2l-5.6 5.6" />
    </>
  ),
  refresh: <path d="M20 8a8.5 8.5 0 1 0 1 6M20 3.5V8h-4.5" />,
  globe: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z" />
    </>
  ),
  film: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M8 5v14M16 5v14M3 9.5h5M3 14.5h5M16 9.5h5M16 14.5h5" />
    </>
  ),
  heart: <path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10z" />,
  plus: <path d="M12 5v14M5 12h14" />,
  x: <path d="m6 6 12 12M18 6 6 18" />,
  "chevron-left": <path d="M14.5 6 8.5 12l6 6" />,
  "chevron-right": <path d="M9.5 6l6 6-6 6" />,
  copy: (
    <>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1" />
    </>
  ),
  send: <path d="M21 3 3 10.5l7 3 3 7L21 3zM10 14l4-4" />,
  trash: <path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13M10 11v5M14 11v5" />,
};

export function Icon({ name, size = 16, class: cls = "" }) {
  const body = P[name];
  if (!body) return null;
  return (
    <svg
      class={"icn " + cls}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.7"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      {body}
    </svg>
  );
}
