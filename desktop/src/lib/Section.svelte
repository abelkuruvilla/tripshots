<script>
  // A collapsible part of an inspector panel: its title, a one-line summary of what is set (shown when closed),
  // and whether it is open, remembered per section across reels.
  import Icon from "./Icon.svelte";

  let { id, title, summary = "", open: start = false, children, actions } = $props();
  const key = `tripshots.section:${id}`;
  let open = $state(start);
  try {
    const v = localStorage.getItem(key);
    if (v !== null) open = v === "1";
  } catch {}
  function toggle() {
    open = !open;
    try {
      localStorage.setItem(key, open ? "1" : "0");
    } catch {}
  }
</script>

<section class="sec" class:open>
  <div class="head">
    <button class="toggle" onclick={toggle} aria-expanded={open} aria-controls={`sec-${id}`}>
      <span class="chev" aria-hidden="true"><Icon name="chevron" size={14} /></span>
      <span class="title">{title}</span>
      {#if !open && summary}<span class="sum meta ellipsis">{summary}</span>{/if}
    </button>
    {#if actions}<div class="acts">{@render actions()}</div>{/if}
  </div>
  {#if open}
    <div class="body" id={`sec-${id}`}>{@render children()}</div>
  {/if}
</section>

<style>
  .sec { border-bottom: 1px solid var(--line); }
  .head { display: flex; align-items: center; gap: 8px; padding-right: 12px; }
  .toggle {
    flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px; padding: 14px 8px 14px 16px; border: 0;
    background: transparent; color: var(--text); text-align: left; font-size: 13px; font-weight: 600;
  }
  .toggle:hover .title { color: var(--accent); }
  .toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .chev { display: grid; place-items: center; color: var(--text-3); transition: transform 150ms var(--ease); transform: rotate(-90deg); }
  .open .chev { transform: none; }
  .title { flex: none; }
  .sum { flex: 1; min-width: 0; text-align: right; font-weight: 400; color: var(--text-3); font-size: 12px; }
  .acts { display: flex; gap: 4px; flex: none; }
  .body { padding: 0 16px 16px; display: flex; flex-direction: column; gap: 12px; }
</style>
