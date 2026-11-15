<script>
  // Expert: the music under the whole reel (where the song starts, its level and fade) and the beat punch.
  import { ed, edit } from "./editor.svelte.js";

  let reel = $derived(ed.reel);
  let mStart = $state(0);
  let gain = $state(0);
  let fade = $state(0.8);
  let punch = $state(0);
  let key = "";
  $effect(() => {
    const k = JSON.stringify([reel?.music, reel?.beat_punch]);
    if (k !== key) {
      key = k;
      mStart = reel?.music?.start || 0;
      gain = reel?.music?.gain_db || 0;
      fade = reel?.music?.fade_out ?? 0.8;
      punch = reel?.beat_punch || 0;
    }
  });
</script>

<section class="panel">
  {#if reel?.music}
    <div>
      <h2 class="ellipsis">{reel.music.label || "Music"}</h2>
      <p class="quiet small">The cuts sit on this song's beats: moving where it starts moves the beat under them</p>
    </div>
    <div class="field">
      <label for="ims">Song starts at <span class="hint">· seconds into the track</span></label>
      <input id="ims" type="number" step="0.1" min="0" bind:value={mStart} onchange={() => edit({ op: "music", start: +mStart })} />
    </div>
    <div class="field">
      <label for="img">Music level <span class="hint">· {gain > 0 ? "+" : ""}{(+gain).toFixed(0)} dB</span></label>
      <input id="img" type="range" min="-24" max="6" step="1" bind:value={gain} onchange={() => edit({ op: "music", gain_db: +gain })} />
      <p class="quiet small help">Under the sound effects; the finished reel is still mastered to Instagram's loudness</p>
    </div>
    <div class="field">
      <label for="imf">Fade out <span class="hint">· {(+fade).toFixed(1)} s</span></label>
      <input id="imf" type="range" min="0" max="5" step="0.1" bind:value={fade} onchange={() => edit({ op: "music", fade_out: +fade })} />
    </div>
  {:else}
    <p class="muted">No music in this plan</p>
  {/if}
  <div class="field">
    <label for="ibp">Beat punch <span class="hint">· {punch ? `${Math.round(punch * 100)}% zoom on each beat` : "off"}</span></label>
    <input id="ibp" type="range" min="0" max="0.12" step="0.01" bind:value={punch} onchange={() => edit({ op: "set", path: "motion.beat_punch", value: +punch })} />
  </div>
</section>

<style>
  .panel { padding: 20px; display: flex; flex-direction: column; gap: 20px; }
  .field { margin: 0; }
  .help { margin-top: 8px; }
</style>
