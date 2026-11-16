<script>
  // Settings, Privacy: the answer about anonymous counts, everything that was sent, a new anonymous id, and Report a
  // problem (shown in full before it goes; it can go to GitHub as a public issue instead).
  import { onMount } from "svelte";
  import { openUrl } from "@tauri-apps/plugin-opener";
  import { api, toast } from "../lib/store.svelte.js";
  import Sheet from "../lib/Sheet.svelte";
  import Icon from "../lib/Icon.svelte";

  let t = $state(null);
  let showLog = $state(false);
  let reporting = $state(false);
  let message = $state("");
  let email = $state("");
  let diagnostics = $state(true);
  let preview = $state(null);
  let sending = $state(false);
  let issueUrl = $state("");

  const load = async () => (t = await api("/api/telemetry?n=40").catch(() => t));
  onMount(load);

  async function setConsent(on) {
    t = { ...t, ...(await api("/api/telemetry", { consent: on })) };
    toast(on ? "Thanks: anonymous counts are on" : "Nothing more will be sent", "ok");
    load();
  }
  async function resetId() {
    await api("/api/telemetry", { action: "reset" });
    toast("A new anonymous id: what was sent before can't be linked to what comes next", "ok");
    load();
  }
  async function look() {
    const q = new URLSearchParams({ message, email, diagnostics: diagnostics ? "1" : "0" });
    preview = await api(`/api/report?${q}`);
  }
  async function send() {
    sending = true;
    try {
      const r = await api("/api/report", { message, email, diagnostics });
      if (r.ok) {
        toast("Sent. Thank you", "ok");
        reporting = false;
        message = email = "";
        preview = null;
      } else {
        issueUrl = r.issue_url || "";
        toast(`Couldn't send it (${r.error}). You can post it on GitHub instead`, "error");
      }
    } catch (e) {
      toast(String(e.message || e), "error");
    } finally {
      sending = false;
    }
  }
  const when = (ts) => new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  const summary = (b) => b.report ? "A bug report" : `${b.events.length} event${b.events.length === 1 ? "" : "s"}: ` +
    [...new Set(b.events.map((e) => e.name))].join(", ");
</script>

<section class="surface block" id="privacy">
  <h2>Privacy</h2>
  {#if t}
    <label class="check long">
      <input type="checkbox" checked={t.consent === true} disabled={!!t.blocked} onchange={(e) => setConsent(e.currentTarget.checked)} />
      <span>Send anonymous usage counts and crash reports
        <span class="hint">· which screens, commands and editor tools are used and when something breaks. Never your footage, file names, places, people or anything you type</span></span>
    </label>
    {#if t.blocked}<p class="quiet small">Off on this computer: {t.blocked}</p>{/if}
    <div class="row">
      <button class="btn sm" onclick={() => { load(); showLog = true; }}><Icon name="eye" size={14} /> See what's sent</button>
      <button class="btn sm" onclick={resetId} disabled={!t.consent}>New anonymous id</button>
      <button class="btn sm" onclick={() => (reporting = true)}><Icon name="message" size={14} /> Report a problem</button>
    </div>
    {#if t.consent}<p class="quiet small">Anonymous id {t.id}…{t.queued ? ` · ${t.queued} waiting to be sent` : ""}{t.last_sent ? ` · last sent ${when(t.last_sent)}` : ""}</p>{/if}
  {/if}
</section>

{#if showLog}
  <Sheet title="What was sent" onclose={() => (showLog = false)} width={640}>
    <p class="muted">Every batch TripShots sent from this computer, newest first, exactly as sent.
      {#if t.queued}{t.queued} more are waiting.{/if}</p>
    {#if !t.sent?.length}<p class="quiet">Nothing has been sent.</p>{/if}
    {#each t.sent || [] as b}
      <details>
        <summary>{when(b.sent)} · {summary(b)}</summary>
        <pre class="selectable">{JSON.stringify(b.events || b.report, null, 1)}</pre>
      </details>
    {/each}
    {#if t.errors?.length}
      <h3>Recent errors on this computer</h3>
      <p class="quiet small">Kept here so a bug report can include them. They are only sent when counts are on, or when you attach them to a report.</p>
      <pre class="selectable">{JSON.stringify(t.errors, null, 1)}</pre>
    {/if}
  </Sheet>
{/if}

{#if reporting}
  <Sheet title="Report a problem" onclose={() => ((reporting = false), (preview = null))}>
    <div class="form">
      <div class="field">
        <label for="rp">What happened <span class="hint">· and what you expected</span></label>
        <textarea id="rp" rows="6" bind:value={message} oninput={() => (preview = null)}></textarea>
      </div>
      <div class="field">
        <label for="re">E-mail <span class="hint">· optional, only if you'd like an answer</span></label>
        <input id="re" type="text" inputmode="email" autocomplete="email" bind:value={email} oninput={() => (preview = null)} />
      </div>
      <label class="check long"><input type="checkbox" bind:checked={diagnostics} onchange={() => (preview = null)} /><span>Attach diagnostics
        <span class="hint">· app version, macOS version, the last few errors and jobs, with names and paths removed</span></span></label>
      {#if preview}<h3>This is exactly what will be sent</h3><pre class="selectable">{JSON.stringify(preview, null, 1)}</pre>{/if}
      {#if issueUrl}<p class="small"><button class="btn sm" onclick={() => openUrl(issueUrl)}>Open a GitHub issue instead</button>
        <span class="quiet">· public: you read and post it yourself</span></p>{/if}
    </div>
    {#snippet foot()}
      <div class="spacer"></div>
      <button class="btn ghost" onclick={look} disabled={!message.trim()}>Show what's sent</button>
      <button class="btn primary" onclick={send} disabled={!message.trim() || sending}>{sending ? "Sending" : "Send"}</button>
    {/snippet}
  </Sheet>
{/if}

<style>
  .block { padding: 20px 24px; display: flex; flex-direction: column; gap: 8px; }
  .block h2 { margin-bottom: 8px; }
  .row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
  .small { font-size: 13px; margin: 0; }
  details { border-top: 1px solid var(--line); padding: 8px 0; }
  summary { cursor: pointer; font-size: 13px; }
  pre { font: 12px/1.4 var(--mono, ui-monospace, Menlo, monospace); background: var(--raised); border-radius: var(--r-ctl); padding: 8px 12px; overflow: auto; max-height: 320px; white-space: pre-wrap; word-break: break-word; }
  h3 { font-size: 13px; margin: 16px 0 6px; }
</style>
