<script>
  // A panel that slides in from the right over a scrim. Escape or the scrim closes it; focus moves into it on open
  // and back to what opened it on close.
  import { onMount, tick } from "svelte";
  import Icon from "./Icon.svelte";

  let { title, onclose, width = 560, children, foot } = $props();
  let box = $state(null);
  onMount(() => {
    const back = document.activeElement;
    tick().then(() => (box?.querySelector("input, textarea, select, button:not(.close)") || box)?.focus());
    return () => back?.focus?.();
  });
  function keys(e) {
    if (e.key === "Escape") onclose();
    if (e.key !== "Tab" || !box) return;  // keep Tab inside the sheet
    const f = [...box.querySelectorAll("button, input, textarea, select, [tabindex]:not([tabindex='-1'])")].filter((x) => !x.disabled);
    if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f.at(-1).focus(); }
    else if (!e.shiftKey && document.activeElement === f.at(-1)) { e.preventDefault(); f[0].focus(); }
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions (Escape closes it) -->
<div class="scrim" onclick={(e) => e.target === e.currentTarget && onclose()}>
  <div class="sheet" style="width: min({width}px, 92vw)" role="dialog" aria-modal="true" aria-label={title} tabindex="-1"
       bind:this={box} onkeydown={keys}>
    <header>
      <h2>{title}</h2>
      <button class="btn ghost icon close" onclick={onclose} aria-label="Close"><Icon name="x" /></button>
    </header>
    <div class="body">{@render children()}</div>
    {#if foot}<footer>{@render foot()}</footer>{/if}
  </div>
</div>

<style>
  .scrim { position: fixed; inset: 0; z-index: 40; background: var(--scrim); display: flex; justify-content: flex-end; animation: fade var(--menu) var(--ease); }
  .sheet {
    height: 100%; display: flex; flex-direction: column; background: var(--card); border-left: 1px solid var(--line);
    box-shadow: var(--float); animation: slide-in var(--enter) var(--ease); outline: none;
  }
  header { display: flex; align-items: center; gap: 12px; padding: 40px 24px 16px; }
  header h2 { flex: 1; font-size: 18px; line-height: 24px; }
  .body { flex: 1; overflow: auto; padding: 0 24px 24px; }
  footer { display: flex; align-items: center; gap: 8px; padding: 16px 24px; border-top: 1px solid var(--line); }
</style>
