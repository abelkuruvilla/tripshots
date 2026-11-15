<script>
  // A job's state in words, with a dot: colour is never the only sign.
  let { state, question = false } = $props();
  const words = { running: "Working", done: "Done", failed: "Failed", cancelled: "Stopped" };
  let tone = $derived(state === "running" ? "run" : question ? "run" : state === "done" ? "ok" : "err");
</script>

<span class="state">{#if state === "running"}<span class="spin" style="width: 10px; height: 10px; border-width: 1.5px; color: var(--accent)"></span>{:else}<span class="dot {tone}"></span>{/if}{question ? "Needs an answer" : words[state] || state}</span>
