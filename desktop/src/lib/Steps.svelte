<script>
  // Progress of a long job as named steps: done, now, still to come.
  let { info } = $props();
</script>

{#if info}
  <ol class="steps" aria-label={`Step ${Math.min(info.at + 1, info.total)} of ${info.total}: ${info.label}`}>
    {#each info.names as n, i}
      <li class:done={i < info.at} class:now={i === info.at}>
        <span class="mark" aria-hidden="true"></span><span>{n}</span>
      </li>
    {/each}
  </ol>
{/if}

<style>
  .steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
  li { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--text-3); }
  li.done { color: var(--text-2); }
  li.now { color: var(--text); font-weight: 500; }
  .mark { width: 8px; height: 8px; border-radius: 50%; box-shadow: inset 0 0 0 1.5px var(--line-strong); flex: none; }
  li.done .mark { background: var(--text-3); box-shadow: none; }
  li.now .mark { background: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
</style>
