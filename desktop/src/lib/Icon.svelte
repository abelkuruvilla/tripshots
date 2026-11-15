<script>
  // One line set (lucide shapes), one size and stroke; icons take the colour of the text around them.
  let { name, size = 16 } = $props();
  const paths = {
    film: "M3 5h18v14H3z M7 5v14 M17 5v14 M3 9.5h4 M3 14.5h4 M17 9.5h4 M17 14.5h4",
    plus: "M12 5v14 M5 12h14",
    message: "M21 12a8 8 0 0 1-11.7 7.1L4 20l.9-4.6A8 8 0 1 1 21 12z",
    layers: "M12 3l9 5-9 5-9-5z M3 13l9 5 9-5",
    activity: "M3 12h4l3-8 4 16 3-8h4",
    settings: "M4 6h10 M18 6h2 M4 12h4 M12 12h8 M4 18h12 M20 18h0 M16 4v4 M10 10v4 M18 16v4",
    back: "M15 18l-6-6 6-6",
    folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
    copy: "M9 9h11v11H9z M5 15H4V4h11v1",
    play: "M7 4.5v15l12-7.5z",
    music: "M9 18V5l12-2v13 M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0z M21 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
    x: "M6 6l12 12 M18 6L6 18",
    swap: "M7 7h13l-4-4 M17 17H4l4 4",
    download: "M12 3v12 M7 10l5 5 5-5 M5 21h14",
    search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z M21 21l-4.3-4.3",
    terminal: "M4 17l6-5-6-5 M12 19h8",
    link: "M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1 M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1",
    refresh: "M21 12a9 9 0 1 1-3-6.7L21 8 M21 3v5h-5",
    sun: "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M12 2v2 M12 20v2 M4.9 4.9l1.4 1.4 M17.7 17.7l1.4 1.4 M2 12h2 M20 12h2 M4.9 19.1l1.4-1.4 M17.7 6.3l1.4-1.4",
    moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
    monitor: "M3 4h18v12H3z M8 20h8 M12 16v4",
    type: "M4 7V5h16v2 M12 5v14 M9 19h6",
    trash: "M4 7h16 M10 11v6 M14 11v6 M6 7l1 13h10l1-13 M9 7V4h6v3",
    scissors: "M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M20 4L8.1 15.9 M14.5 14.5L20 20 M8.1 8.1L12 12",
    undo: "M9 14L4 9l5-5 M4 9h10.5a5.5 5.5 0 0 1 0 11H11",
    redo: "M15 14l5-5-5-5 M20 9H9.5a5.5 5.5 0 0 0 0 11H13",
    sparkle: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z M19 16l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z",
    hash: "M4 9h16 M4 15h16 M10 3L8 21 M16 3l-2 18",
    sliders: "M4 21v-7 M4 10V3 M12 21v-9 M12 8V3 M20 21v-5 M20 12V3 M1 14h6 M9 8h6 M17 16h6",
    eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
    pause: "M7 4h3v16H7z M14 4h3v16h-3z",
    check: "M5 12.5l4.5 4.5L19 7.5",
    split: "M4 5h16v14H4z M12 3v18",
    chevron: "M6 9l6 6 6-6",
    "chevron-right": "M9 6l6 6-6 6",
    "arrow-left": "M19 12H5 M11 6l-6 6 6 6",
    "arrow-right": "M5 12h14 M13 6l6 6-6 6",
    more: "M5 12h.01 M12 12h.01 M19 12h.01",
    wand: "M15 4V2 M15 16v-2 M8 9h2 M20 9h2 M17.8 11.8l1.4 1.4 M17.8 6.2l1.4-1.4 M12.2 6.2l-1.4-1.4 M3 21l9-9",
    palette: "M12 21a9 9 0 1 1 9-9c0 2.5-2 3-3.5 3H15a2 2 0 0 0-1.5 3.3A1.6 1.6 0 0 1 12 21z M7.5 10.5h.01 M10.5 7h.01 M15 7.5h.01",
    film2: "M4 5h16v14H4z M4 15h16",
  };
</script>

<svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width={name === "more" ? 3 : 1.5}
     stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="flex: none">
  <path d={paths[name] || ""} />
</svg>
