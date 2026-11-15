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
  };
</script>

<svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"
     stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="flex: none">
  <path d={paths[name] || ""} />
</svg>
