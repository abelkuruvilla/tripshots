<script>
  // Make a reel: say what you want (TripShots finds the footage, picks a style and a sound), or choose the footage,
  // sound and style yourself. Either way the job's progress shows here, step by step, with the reel at the end.
  import { onMount } from "svelte";
  import { open } from "@tauri-apps/plugin-dialog";
  import { app, api, media, startJob, openReel, toast, clock } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";
  import JobState from "../lib/JobState.svelte";
  import Steps from "../lib/Steps.svelte";
  import { steps } from "../lib/steps.js";

  let mode = $state(app.prefill?.style ? "choose" : "describe");
  // describe
  let request = $state("");
  const examples = ["A reel with all my drone footage", "My days in Yellowstone", "The photos I'm in, set to something calm"];
  // choose
  let sources = $state([...(app.status?.footage_folders || [])]);
  let sound = $state("");
  let style = $state(app.prefill?.style || "");
  let name = $state("");
  let orientation = $state("auto");
  let light = $state("any");
  let variants = $state(1);
  let hook = $state("");
  let planOnly = $state(false);
  let styles = $state([]);
  onMount(async () => {
    app.prefill = null;
    styles = await api("/api/styles").catch(() => []);
  });

  // the job on screen
  let job = $state(null);
  let reply = $state("");
  let asked = $state("");
  $effect(() => {
    const id = app.makeJob;
    if (!id) return;
    let alive = true;
    const tick = async () => {
      const st = await api(`/api/jobs/${id}?lines=80`).catch(() => null);
      if (!alive) return;
      if (st) job = st;
      if (!st || st.state === "running") setTimeout(tick, 1500);
    };
    tick();
    return () => (alive = false);
  });

  let res = $derived(job?.result || null);
  let running = $derived(job?.state === "running");
  let understood = $derived(res?.understood?.summary || (job?.log || []).map((l) => l.match(/^understood: (.*)/)?.[1]).filter(Boolean).pop() || "");
  let found = $derived(res?.found || null);
  let plan = $derived(res?.plan || res?.variants?.[0]?.plan || null);
  let progress = $derived(job ? steps(job.kind, job.log, res?.question ? "running" : job.state) : null);
  let now = $derived((job?.log || []).filter((l) => l.trim() && !/^understood:/.test(l)).at(-1) || "");

  async function run(kind, fields, label) {
    try {
      const st = await startJob(kind, fields, label);
      job = st;
      app.makeJob = st.id;
      reply = "";
    } catch (e) {
      toast(String(e.message || e), "error");
    }
  }
  function describe(text = request) {
    const t = text.trim();
    if (!t) return;
    asked = t;
    run("ask", { request: t, plan_only: planOnly }, t.slice(0, 48));
  }
  function answer() {
    if (!reply.trim() || !res?.question) return;
    describe(`${asked || job?.label}\n(Your question was: "${res.question}" My answer: ${reply.trim()})`);
  }
  function make() {
    if (!sources.length) return toast("Add a folder of photos and clips first", "error");
    run("make", { sources, music: sound.trim() || null, style: style || null, name: name.trim() || null,
                  orientation, light: light === "any" ? null : light, variants, dry_run: planOnly,
                  hook: hook.trim() || null }, name.trim() || "New reel");
  }
  async function add(directory) {
    const got = await open(directory ? { directory: true, multiple: true, title: "Footage folders" } : { multiple: true, title: "Photos and clips" });
    for (const f of [got].flat().filter(Boolean)) if (!sources.includes(f)) sources.push(f);
  }
  async function pickAudio() {
    const got = await open({ title: "Music", filters: [{ name: "Audio", extensions: ["mp3", "m4a", "wav", "aac", "flac", "ogg"] }] });
    if (got) sound = got;
  }
  const short = (p) => p.split(/[\\/]/).pop() || p;
  const nice = (n) => n.replace(/[-_]+/g, " ").replace(/^./, (c) => c.toUpperCase());
  const places = (f) => Object.keys(f?.places || {}).slice(0, 4).join(", ");
  let folders = $derived(app.status?.footage_folders || []);
  let chosen = $derived(styles.find((s) => s.name === style));
</script>

<div class="page">
  <div class="page-head"><h1>Make a reel</h1></div>
  <p class="page-sub">Say what you want and TripShots finds the footage, picks a style and a sound, and cuts it. Or choose them yourself</p>

  <div class="wrap">
    <div class="seg modes" role="tablist" aria-label="How to make it">
      <button role="tab" aria-selected={mode === "describe"} onclick={() => (mode = "describe")}><Icon name="message" size={14} /> Describe it</button>
      <button role="tab" aria-selected={mode === "choose"} onclick={() => (mode = "choose")}><Icon name="sliders" size={14} /> Choose it yourself</button>
    </div>

    {#if mode === "describe"}
      <section class="surface box">
        <label class="sr-only" for="req">What reel to make</label>
        <textarea id="req" rows="3" placeholder="A reel with…" bind:value={request}
                  onkeydown={(e) => e.key === "Enter" && (e.metaKey || e.ctrlKey) && describe()}></textarea>
        <div class="examples" aria-label="Examples">
          {#each examples as ex}<button class="ex" onclick={() => (request = ex)}>{ex}</button>{/each}
        </div>
        <div class="row foot">
          <span class="quiet small ellipsis">
            {#if folders.length}Looks in {folders.map(short).join(", ")}{:else}No footage folders yet{/if} ·
            <button class="link small" onclick={() => (app.view = "settings")}>{folders.length ? "Change" : "Add them in Settings"}</button>
          </span>
          <div class="spacer"></div>
          <label class="check"><input type="checkbox" bind:checked={planOnly} /> Plan first</label>
          <button class="btn primary" onclick={() => describe()} disabled={!request.trim() || running}>Make the reel <kbd class="kbd-on">⌘↵</kbd></button>
        </div>
      </section>
    {:else}
      <section class="surface box form">
        <div class="field">
          <span class="lbl">Footage <span class="hint">· folders are searched inside</span></span>
          <div class="chips">
            {#each sources as s, i}
              <span class="chip" title={s}><span class="ellipsis">{short(s)}</span>
                <button onclick={() => sources.splice(i, 1)} aria-label={`Remove ${short(s)}`}><Icon name="x" size={14} /></button></span>
            {/each}
            <button class="btn sm" onclick={() => add(true)}><Icon name="folder" size={14} /> Add a folder</button>
            <button class="btn sm ghost" onclick={() => add(false)}>Add files</button>
          </div>
        </div>
        <div class="field">
          <label for="snd">Sound <span class="hint">· a reel link uses its sound and its cut, an audio file is cut to its beat</span></label>
          <div class="row">
            <input id="snd" type="text" placeholder="instagram.com/reel/… or an audio file" bind:value={sound} />
            <button class="btn" onclick={pickAudio}><Icon name="music" /> Choose a file</button>
          </div>
        </div>
        <div class="field">
          <label for="sty">Style</label>
          <select id="sty" bind:value={style}>
            <option value="">Automatic</option>
            {#each styles as s}<option value={s.name}>{nice(s.name)}{s.user ? " · yours" : ""}</option>{/each}
          </select>
          {#if chosen?.description}<p class="quiet small help">{chosen.description}</p>{/if}
        </div>
        <div class="grid2">
          <div class="field">
            <label class="lbl" for="mk-shape">Shape</label>
            <select id="mk-shape" bind:value={orientation}>
              {#each [["auto", "Automatic (the style decides)"], ["vertical", "Upright 9:16"], ["horizontal", "Wide 16:9"],
                      ["4:3", "Classic 4:3"], ["4:5", "Portrait 4:5"], ["1:1", "Square 1:1"]] as [id, label]}
                <option value={id}>{label}</option>
              {/each}
            </select>
          </div>
          <div class="field">
            <label class="lbl" for="mk-light">Light <span class="hint">· only shots in it</span></label>
            <select id="mk-light" bind:value={light}>
              {#each [["any", "Any light"], ["golden", "Golden hour and sunset"], ["sunset", "Sunset"], ["blue", "Blue hour"],
                      ["day", "Daylight"], ["night", "Night"]] as [id, label]}
                <option value={id}>{label}</option>
              {/each}
            </select>
          </div>
          <div class="field">
            <span class="lbl">Versions <span class="hint">· to compare</span></span>
            <div class="seg" role="radiogroup" aria-label="Versions">
              {#each [1, 2, 3, 4] as n}<button role="radio" aria-checked={variants === n} onclick={() => (variants = n)}>{n}</button>{/each}
            </div>
          </div>
        </div>
        <div class="grid2">
          <div class="field">
            <label for="hook">Opening line <span class="hint">· optional, up to 7 words</span></label>
            <input id="hook" type="text" maxlength="60" bind:value={hook} />
          </div>
          <div class="field">
            <label for="nm">File name <span class="hint">· optional</span></label>
            <input id="nm" type="text" placeholder="yellowstone" bind:value={name} />
          </div>
        </div>
        <div class="row foot">
          <span class="quiet small">A reel takes a few minutes; Plan first shows the storyboard in about one</span>
          <div class="spacer"></div>
          <label class="check"><input type="checkbox" bind:checked={planOnly} /> Plan first</label>
          <button class="btn primary" onclick={make} disabled={running}>{planOnly ? "Plan the reel" : "Make the reel"}</button>
        </div>
      </section>
    {/if}

    {#if job}
      <section class="surface box result" aria-live="polite">
        <div class="row">
          <JobState state={job.state} question={!!res?.question} />
          <h2 class="ellipsis">{job.label}</h2>
          <span class="meta">{clock(job.elapsed_s)}</span>
          <div class="spacer"></div>
          {#if running}<button class="btn sm ghost" onclick={() => api(`/api/jobs/${job.id}/cancel`, {})}><Icon name="x" size={14} /> Stop</button>{/if}
          {#if plan}<button class="btn primary sm" onclick={() => openReel(plan)}><Icon name="play" size={14} /> Open the reel</button>{/if}
        </div>

        <div class="cols">
          <div class="progress">
            <Steps info={progress} />
          </div>
          <div class="facts">
            {#if understood}
              <div class="fact"><span class="lbl2 meta">Understood</span><p>{understood}</p></div>
            {/if}
            {#if found?.count}
              <div class="fact">
                <span class="lbl2 meta">Found</span>
                <p>{[`${found.count} files`, found.videos && `${found.videos} videos`, found.photos && `${found.photos} photos`,
                     Object.keys(found.days || {}).length && `${Object.keys(found.days).length} days`, places(found)].filter(Boolean).join(" · ")}</p>
                {#if found.sheet}<img class="sheet" src={media(found.sheet)} alt="Contact sheet of the footage found" />{/if}
              </div>
            {/if}
            {#if res?.question}
              <div class="fact">
                <span class="lbl2 meta">Question</span>
                <p>{res.question}</p>
                <div class="row reply">
                  <input type="text" placeholder="Your answer" bind:value={reply} aria-label="Your answer" onkeydown={(e) => e.key === "Enter" && answer()} />
                  <button class="btn primary" onclick={answer} disabled={!reply.trim()}>Answer</button>
                </div>
              </div>
            {/if}
            {#if running && now}<div class="fact"><span class="lbl2 meta">Now</span><p class="muted ellipsis" title={now}>{now}</p></div>{/if}
            {#if job.state === "failed"}<div class="fact"><span class="lbl2 meta">What happened</span><p class="err-text selectable">{job.error || now}</p></div>{/if}
            {#if job.state === "done" && plan}
              <p class="muted">{res?.dry_run || planOnly ? "The plan and its storyboard are ready: open it to look, swap shots and render it" : "Open it to watch it, change its words and colour, and copy the caption"}</p>
            {/if}
          </div>
        </div>

        <details>
          <summary class="small">Log</summary>
          <pre class="log">{(job.log || []).join("\n")}</pre>
        </details>
      </section>
    {/if}
  </div>
</div>

<style>
  .wrap { max-width: 840px; display: flex; flex-direction: column; gap: 16px; }
  .modes { align-self: flex-start; }
  .modes > button { height: 32px; padding: 0 14px; font-size: 13px; }
  .box { padding: 20px 24px; display: flex; flex-direction: column; gap: 16px; }
  .box textarea { border: 0; padding: 0; min-height: 76px; background: transparent; box-shadow: none; font-size: 16px; line-height: 24px; }
  .examples { display: flex; flex-wrap: wrap; gap: 8px; }
  .ex {
    height: 28px; padding: 0 12px; border: 1px solid var(--line); border-radius: var(--r-sm); background: transparent;
    color: var(--text-2); font-size: 13px; transition: background-color var(--fast) var(--ease), color var(--fast) var(--ease);
  }
  .ex:hover { background: var(--raised); color: var(--text); }
  .foot { padding-top: 16px; border-top: 1px solid var(--line); gap: 16px; }
  .foot > .quiet { min-width: 0; }
  .kbd-on { background: color-mix(in srgb, var(--accent-ink) 18%, transparent); color: var(--accent-ink); box-shadow: none; }
  .form { gap: 0; }
  .lbl { display: block; font-weight: 500; font-size: 13px; margin: 0 0 8px; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .chip { max-width: 280px; }
  .help { margin-top: 8px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
  .result { gap: 20px; }
  .cols { display: grid; grid-template-columns: 200px 1fr; gap: 24px; }
  .facts { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
  .fact { display: flex; flex-direction: column; gap: 4px; }
  .lbl2 { color: var(--text-3); }
  .reply { margin-top: 8px; max-width: 520px; }
  .sheet { width: 100%; max-height: 240px; object-fit: cover; object-position: top; border-radius: var(--r-ctl); box-shadow: inset 0 0 0 1px var(--line); margin-top: 8px; }
  details summary { color: var(--text-3); }
  details .log { margin-top: 8px; max-height: 220px; }
</style>
