<script>
  // The TripShots mark: a low sun over a ridge, flat, in one colour.
  let { size = 20 } = $props();
</script>

<svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" style="flex: none">
  <circle cx="12" cy="10" r="4.5" fill="var(--accent)" />
  <path d="M2 20l6.5-8 4 4.5 3-3.5L22 20z" fill="var(--text)" />
</svg>
