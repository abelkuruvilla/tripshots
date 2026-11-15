<script>
  import { onMount } from "svelte";
  import { invoke } from "@tauri-apps/api/core";
  import { openUrl } from "@tauri-apps/plugin-opener";
  import { app, api, toast, refreshStatus } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";

  let st = $state(null);
  let open = $state(null); // the provider whose steps are shown
  let keys = $state({ minimax: "", gemini: "", anthropic: "", token: "" });
  let testing = $state({});
  let results = $state({});
  let watching = $state(false);
  let error = $state("");

  const NAMES = { "claude-cli": "Claude", minimax: "MiniMax", api: "Claude API" };
  const backends = [
    { id: "auto", label: "Automatic" },
    { id: "claude-cli", label: "Claude" },
    { id: "minimax", label: "MiniMax" },
    { id: "api", label: "Claude API" },
    { id: "none", label: "None" },
  ];

  async function load() {
    try {
      st = await api("/api/ai");
      app.ai = st;
      error = "";
      if (open === null) open = st.using ? null : "claude";
    } catch (e) {
      // an older engine has no AI page: say so instead of spinning
      error = /no such endpoint/.test(String(e.message || e))
        ? "This engine is older than the app. Update it in About below to set up AI here"
        : String(e.message || e);
    }
  }
  onMount(load);

  const P = (id) => st?.providers?.[id] || {};
  const label = (state) =>
    ({ ready: "Ready", logged_out: "Not logged in", missing: "Not installed", no_key: "No key", no_sdk: "Needs the Gemini library" })[state] || state;

  async function setBackend(id) {
    await api("/api/settings", { backend: id });
    await load();
    await refreshStatus();
  }
  async function saveKey(envName, field) {
    const v = keys[field].trim();
    if (!v) return;
    await api("/api/settings", { env: { [envName]: v } });
    keys[field] = "";
    await load();
    toast("Key saved", "ok");
  }
  async function removeKey(envName) {
    await api("/api/settings", { env: { [envName]: "" } });
    await load();
    toast("Key removed", "ok");
  }
  async function test(id) {
    testing[id] = true;
    results[id] = null;
    try {
      results[id] = await api("/api/ai/test", { provider: id });
    } catch (e) {
      results[id] = { ok: false, message: String(e.message || e) };
    } finally {
      testing[id] = false;
    }
  }
  async function terminal(action) {
    try {
      const cmd = await invoke("open_terminal", { action });
      toast(`Terminal opened: ${cmd}`, "info");
      watchClaude();
    } catch (e) {
      toast(String(e), "error");
    }
  }
  // after the login or install runs in the terminal, notice when Claude becomes ready (up to 3 minutes)
  async function watchClaude() {
    if (watching) return;
    watching = true;
    const until = Date.now() + 180000;
    while (Date.now() < until) {
      await new Promise((r) => setTimeout(r, 3000));
      await load().catch(() => {});
      if (P("claude").state === "ready") {
        toast("Claude is connected", "ok");
        break;
      }
    }
    watching = false;
  }
  async function copy(text) {
    await navigator.clipboard.writeText(text);
    toast("Copied", "ok");
  }
  const tone = (state) => (state === "ready" ? "ok" : state === "logged_out" || state === "no_sdk" ? "run" : "");
</script>

{#snippet head(id, title, sub, state)}
  <button class="head" onclick={() => (open = open === id ? null : id)} aria-expanded={open === id}>
    <span class="dot {tone(state)}"></span>
    <span class="title">{title}</span>
    <span class="sub quiet ellipsis">{sub}</span>
    <span class="state meta">{label(state)}</span>
    <span class="chev" class:up={open === id}><Icon name="back" size={14} /></span>
  </button>
{/snippet}

{#snippet result(id)}
  {#if results[id]}<p class="result" class:bad={!results[id].ok}>{results[id].message}</p>{/if}
{/snippet}

<section class="surface block" id="ai">
  <div class="row top">
    <h2>AI</h2>
    <div class="spacer"></div>
    <button class="btn sm ghost" onclick={load} aria-label="Check again"><Icon name="refresh" size={14} /> Check again</button>
  </div>
  <p class="muted intro">
    An AI judges your shots, picks the colour and writes the words on screen and the caption. Everything else runs on
    this computer. Set up at least one; Gemini is an optional extra that watches clips.
  </p>

  {#if st}
    <div class="choose">
      <div class="seg" role="radiogroup" aria-label="Which AI makes the creative calls">
        {#each backends as b}
          <button role="radio" aria-checked={st.backend === b.id} class:on={st.backend === b.id} onclick={() => setBackend(b.id)}>{b.label}</button>
        {/each}
      </div>
      <p class="quiet small">
        {#if st.using}Making the creative calls now: <b>{NAMES[st.using]}</b>.{:else if st.backend === "none"}No AI: shots are judged on sharpness and exposure only, and no captions are written.{:else}No AI is ready yet. Set one up below.{/if}
        {#if st.backend === "auto" && st.order.length > 1} If it runs out or stops working, {st.order.slice(1).map((n) => NAMES[n]).join(", then ")} takes over.{/if}
      </p>
    </div>

    <div class="providers">
      <!-- Claude through the Claude app login (subscription) -->
      <div class="prov" class:open={open === "claude"}>
        {@render head("claude", "Claude", "Your Claude Pro or Max plan, no key needed", P("claude").state)}
        {#if open === "claude"}
          <div class="body">
            {#if P("claude").state === "ready"}
              <p class="muted">{[P("claude").account ? `Logged in as ${P("claude").account}` : "Logged in", P("claude").plan && `${P("claude").plan} plan`, P("claude").token && "with a saved token"].filter(Boolean).join(" · ")}</p>
            {/if}
            <ol class="steps">
              <li class:done={P("claude").state !== "missing"}>
                <div><b>Install Claude Code</b> <span class="quiet">· the Claude command-line tool</span></div>
                {#if P("claude").state === "missing"}
                  <div class="row wrap">
                    <button class="btn sm primary" onclick={() => terminal("claude-install")}><Icon name="terminal" size={14} /> Install in Terminal</button>
                    <button class="btn sm ghost" onclick={() => openUrl("https://docs.claude.com/en/docs/claude-code/setup")}>Install guide</button>
                  </div>
                {:else}<div class="meta">{P("claude").path}</div>{/if}
              </li>
              <li class:done={P("claude").state === "ready"}>
                <div><b>Log in with your Claude account</b> <span class="quiet">· a browser window opens to sign in, then come back here</span></div>
                {#if P("claude").state !== "ready"}
                  <div class="row wrap">
                    <button class="btn sm primary" onclick={() => terminal("claude-login")} disabled={P("claude").state === "missing"}><Icon name="terminal" size={14} /> Log in in Terminal</button>
                    <button class="btn sm ghost" onclick={() => copy("claude auth login")}><Icon name="copy" size={14} /> Copy the command</button>
                    {#if watching}<span class="quiet small"><span class="spin"></span> waiting for the login</span>{/if}
                  </div>
                {/if}
              </li>
              <li>
                <div><b>Test it</b> <span class="quiet">· sends one short message</span></div>
                <div class="row wrap">
                  <button class="btn sm" onclick={() => test("claude")} disabled={testing.claude || P("claude").state === "missing"}>{#if testing.claude}<span class="spin"></span>{/if} Test</button>
                </div>
                {@render result("claude")}
              </li>
            </ol>
            <details>
              <summary class="quiet">Logged in, but TripShots still can't use it</summary>
              <p class="muted small">Make a long-lived token with <span class="tc">claude setup-token</span> and paste it here.</p>
              <div class="row">
                <button class="btn sm" onclick={() => terminal("claude-token")} disabled={P("claude").state === "missing"}><Icon name="terminal" size={14} /> Make a token</button>
                <input type="password" placeholder={P("claude").token ? "Token saved. Type to replace" : "Paste the token"} bind:value={keys.token} aria-label="Claude token" />
                <button class="btn sm" onclick={() => saveKey("CLAUDE_CODE_OAUTH_TOKEN", "token")} disabled={!keys.token.trim()}>Save</button>
                {#if P("claude").token}<button class="btn sm ghost" onclick={() => removeKey("CLAUDE_CODE_OAUTH_TOKEN")}>Remove</button>{/if}
              </div>
            </details>
          </div>
        {/if}
      </div>

      <!-- MiniMax -->
      <div class="prov" class:open={open === "minimax"}>
        {@render head("minimax", "MiniMax", `An API key, pay as you go · ${P("minimax").model || "MiniMax-M3"}`, P("minimax").state)}
        {#if open === "minimax"}
          <div class="body">
            <ol class="steps">
              <li>
                <div><b>Make a MiniMax account</b> <span class="quiet">· and add a balance or a plan</span></div>
                <div class="row wrap"><button class="btn sm" onclick={() => openUrl("https://platform.minimax.io")}><Icon name="link" size={14} /> Open MiniMax</button></div>
              </li>
              <li>
                <div><b>Create an API key</b> <span class="quiet">· in your account menu, under API Keys</span></div>
              </li>
              <li class:done={P("minimax").state === "ready"}>
                <div><b>Paste it here</b></div>
                <div class="row">
                  <input type="password" placeholder={P("minimax").state === "ready" ? "Key saved. Type to replace" : "MiniMax API key"} bind:value={keys.minimax} aria-label="MiniMax API key" />
                  <button class="btn sm primary" onclick={() => saveKey("MINIMAX_API_KEY", "minimax")} disabled={!keys.minimax.trim()}>Save</button>
                  {#if P("minimax").state === "ready"}<button class="btn sm ghost" onclick={() => removeKey("MINIMAX_API_KEY")}>Remove</button>{/if}
                </div>
              </li>
              <li>
                <div class="row wrap"><button class="btn sm" onclick={() => test("minimax")} disabled={testing.minimax || P("minimax").state !== "ready"}>{#if testing.minimax}<span class="spin"></span>{/if} Test</button></div>
                {@render result("minimax")}
              </li>
            </ol>
            <p class="quiet small">TripShots uses MiniMax-M3, which can look at pictures. Older text-only models can't judge footage.</p>
          </div>
        {/if}
      </div>

      <!-- Gemini -->
      <div class="prov" class:open={open === "gemini"}>
        {@render head("gemini", "Gemini", "Optional, free key · watches clips and hears dialogue", P("gemini").state)}
        {#if open === "gemini"}
          <div class="body">
            <p class="muted small">Gemini watches each clip once to find its best moment, shake and sound, and transcribes spoken words. Claude or MiniMax still make the creative calls.</p>
            <ol class="steps">
              <li>
                <div><b>Open Google AI Studio</b> <span class="quiet">· sign in with a Google account</span></div>
                <div class="row wrap"><button class="btn sm" onclick={() => openUrl("https://aistudio.google.com/apikey")}><Icon name="link" size={14} /> Open AI Studio</button></div>
              </li>
              <li>
                <div><b>Create an API key</b> <span class="quiet">· the free tier is enough for most trips</span></div>
              </li>
              <li class:done={P("gemini").state === "ready"}>
                <div><b>Paste it here</b></div>
                <div class="row">
                  <input type="password" placeholder={P("gemini").state !== "no_key" ? "Key saved. Type to replace" : "Gemini API key"} bind:value={keys.gemini} aria-label="Gemini API key" />
                  <button class="btn sm primary" onclick={() => saveKey("GEMINI_API_KEY", "gemini")} disabled={!keys.gemini.trim()}>Save</button>
                  {#if P("gemini").state !== "no_key"}<button class="btn sm ghost" onclick={() => removeKey("GEMINI_API_KEY")}>Remove</button>{/if}
                </div>
              </li>
              <li>
                <div class="row wrap"><button class="btn sm" onclick={() => test("gemini")} disabled={testing.gemini || P("gemini").state !== "ready"}>{#if testing.gemini}<span class="spin"></span>{/if} Test</button></div>
                {@render result("gemini")}
              </li>
            </ol>
          </div>
        {/if}
      </div>

      <!-- Anthropic API key -->
      <div class="prov" class:open={open === "anthropic"}>
        {@render head("anthropic", "Claude API", "Optional, an Anthropic API key, pay per use", P("anthropic").state)}
        {#if open === "anthropic"}
          <div class="body">
            <ol class="steps">
              <li>
                <div><b>Create a key in the Anthropic Console</b> <span class="quiet">· needs a payment method</span></div>
                <div class="row wrap"><button class="btn sm" onclick={() => openUrl("https://console.anthropic.com/settings/keys")}><Icon name="link" size={14} /> Open the Console</button></div>
              </li>
              <li class:done={P("anthropic").state === "ready"}>
                <div><b>Paste it here</b></div>
                <div class="row">
                  <input type="password" placeholder={P("anthropic").state === "ready" ? "Key saved. Type to replace" : "Anthropic API key"} bind:value={keys.anthropic} aria-label="Anthropic API key" />
                  <button class="btn sm primary" onclick={() => saveKey("ANTHROPIC_API_KEY", "anthropic")} disabled={!keys.anthropic.trim()}>Save</button>
                  {#if P("anthropic").state === "ready"}<button class="btn sm ghost" onclick={() => removeKey("ANTHROPIC_API_KEY")}>Remove</button>{/if}
                </div>
              </li>
              <li>
                <div class="row wrap"><button class="btn sm" onclick={() => test("anthropic")} disabled={testing.anthropic || P("anthropic").state !== "ready"}>{#if testing.anthropic}<span class="spin"></span>{/if} Test</button></div>
                {@render result("anthropic")}
              </li>
            </ol>
          </div>
        {/if}
      </div>
    </div>
    <p class="quiet small foot">Keys are saved in <span class="tc">~/.tripshots/.env</span> on this computer and only sent to the service they belong to.</p>
  {:else if error}
    <p class="muted small">{error}</p>
  {:else}
    <div class="empty"><span class="spin"></span></div>
  {/if}
</section>

<style>
  .block { padding: 20px 24px; }
  .top { margin-bottom: 8px; }
  .spacer { flex: 1; }
  .intro { margin: 0 0 16px; max-width: 720px; }
  .small { font-size: 13px; }
  .choose { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
  .choose p { margin: 0; }
  .seg { display: inline-flex; align-self: flex-start; flex-wrap: wrap; gap: 4px; padding: 4px; background: var(--raised); border-radius: 12px; }
  .seg button {
    height: 32px; padding: 0 12px; border: 0; border-radius: var(--r-ctl); background: transparent; color: var(--text-2);
    cursor: pointer; font-weight: 500; font-size: 13px; transition: background-color 150ms var(--ease), color 150ms var(--ease);
  }
  .seg button:hover { color: var(--text); }
  .seg button.on { background: var(--card); color: var(--text); box-shadow: inset 0 0 0 1px var(--line), var(--highlight); }
  .providers { border: 1px solid var(--line); border-radius: var(--r-card); overflow: hidden; }
  .prov + .prov { border-top: 1px solid var(--line); }
  .head {
    display: grid; grid-template-columns: 8px auto 1fr auto 16px; align-items: center; gap: 12px; width: 100%;
    height: 48px; padding: 0 16px; border: 0; background: transparent; color: inherit; text-align: left; cursor: pointer;
    transition: background-color 150ms var(--ease);
  }
  .head:hover { background: var(--raised); }
  .title { font-weight: 500; }
  .chev { color: var(--text-3); display: grid; place-items: center; transform: rotate(-90deg); transition: transform 150ms var(--ease); }
  .chev.up { transform: rotate(90deg); }
  .body { padding: 4px 16px 16px 36px; display: flex; flex-direction: column; gap: 12px; }
  .body > p { margin: 0; }
  .steps { margin: 0; padding: 0 0 0 20px; display: flex; flex-direction: column; gap: 12px; }
  .steps li { padding-left: 4px; }
  .steps li::marker { color: var(--text-3); font-family: var(--mono); font-size: 12px; }
  .steps li.done::marker { color: var(--ok); }
  .steps li > div + div { margin-top: 8px; }
  .row.wrap { flex-wrap: wrap; }
  .row input { max-width: 360px; height: 28px; min-height: 28px; padding: 0 8px; font-size: 13px; }
  .result { margin: 8px 0 0; font-size: 13px; color: var(--ok); user-select: text; }
  .result.bad { color: var(--err); }
  details { font-size: 13px; }
  details summary { cursor: pointer; }
  details p { margin: 8px 0; }
  .foot { margin: 12px 0 0; }
</style>
