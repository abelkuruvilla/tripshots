<script>
  // Asked once, before anything is sent: both answers are one click and look alike, and either can be changed in
  // Settings, Privacy.
  import { api, toast } from "../lib/store.svelte.js";

  let { ondone } = $props();
  let busy = $state(false);

  async function answer(yes) {
    busy = true;
    try {
      await api("/api/telemetry", { consent: yes });
      ondone(yes);
    } catch (e) {
      toast(String(e.message || e), "error");
    } finally {
      busy = false;
    }
  }
</script>

<div class="scrim">
  <div class="box surface" role="dialog" aria-modal="true" aria-labelledby="consent-title">
    <h2 id="consent-title">Help make TripShots better?</h2>
    <p>TripShots can send anonymous counts of what gets used, and a note when something crashes, so the parts people
      use get better and the bugs get fixed first.</p>
    <div class="lists">
      <div>
        <h3>What would be sent</h3>
        <ul>
          <li>A random id made on this Mac, which you can reset</li>
          <li>The app version, macOS version and chip</li>
          <li>Which screens, commands and editor tools are used, whether they worked, and roughly how long they took</li>
          <li>When something crashes: the kind of error and where in TripShots, with names and paths removed</li>
        </ul>
      </div>
      <div>
        <h3>Never sent</h3>
        <ul>
          <li>Your photos, clips, music or reels</li>
          <li>File or folder names, places, people or GPS</li>
          <li>Anything you type: hooks, captions, notes</li>
          <li>Your AI keys, your Instagram login or your IP address</li>
        </ul>
      </div>
    </div>
    <p class="quiet small">Change your answer any time in Settings, Privacy, where you can also see everything that was sent.</p>
    <div class="row">
      <button class="btn" disabled={busy} onclick={() => answer(false)}>No thanks</button>
      <button class="btn" disabled={busy} onclick={() => answer(true)}>Yes, send anonymous counts</button>
    </div>
  </div>
</div>

<style>
  .scrim { position: fixed; inset: 0; z-index: 70; background: var(--scrim); display: grid; place-items: center; padding: 24px; animation: fade var(--menu) var(--ease); }
  .box { background: var(--card); width: min(640px, 100%); max-height: 100%; overflow: auto; padding: 28px 32px; border-radius: var(--r-card); box-shadow: var(--float); }
  h2 { margin: 0 0 8px; }
  h3 { font-size: 13px; font-weight: 600; margin: 0 0 6px; }
  p { margin: 0 0 16px; color: var(--text-2); }
  .lists { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px 24px; margin-bottom: 16px; }
  ul { margin: 0; padding-left: 18px; font-size: 13px; color: var(--text-2); display: flex; flex-direction: column; gap: 4px; }
  .small { font-size: 13px; }
  .row { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; }
</style>
