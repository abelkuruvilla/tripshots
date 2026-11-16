<script>
  // On-screen text: every line, and for the selected one its words, timing and lettering.
  import Icon from "../../lib/Icon.svelte";
  import { tc } from "../../lib/store.svelte.js";
  import FontPicker from "./FontPicker.svelte";
  import Section from "../../lib/Section.svelte";
  import { ed, edit, hex, frames, select as pick } from "./editor.svelte.js";

  const kinds = { hook: "Hook", location: "Place", cta: "Ending", label: "Label", caption: "Subtitle", text: "Text" };
  const swatches = ["#ffffff", "#111111", "#ffd23c", "#e8743f", "#ff6b6b", "#8fd3ff", "#7ee0b5", "#f2e3c6"];
  const anims = [["pop", "Pop"], ["slide", "Slide up"], ["fade", "Fade"], ["scale", "Grow"], ["typewriter", "Typewriter"],
                 ["tracking", "Spread"], ["rise", "Rise"], ["cut", "Cut"]];
  const positions = [["auto", "Auto"], ["upper", "Top"], ["center", "Middle"], ["lower", "Bottom"]];
  // animated motions (rendered as motion pages) and how the letters are drawn: the effects library (fxlib.py)
  const motions = [["", "Automatic"], ["rise", "Rise"], ["focus", "Pull focus"], ["cinema", "Film title"], ["tracking", "Spread"],
                   ["typewriter", "Typewriter"], ["write", "Handwritten"], ["decode", "Decode"], ["stamp", "Stamp"], ["slam", "Slam"]];
  const looks = [["", "Plain"], ["neon", "Neon"], ["glow", "Glow"], ["outline", "Outline"], ["offset", "Offset"]];

  let reel = $derived(ed.reel);
  let t = $derived(ed.sel?.kind === "text" ? reel?.texts.find((x) => x.index === ed.sel.index) : null);
  let base = $derived(t ? reel.text_defaults?.[t.type] || reel.text_defaults?.hook || {} : {});
  let look = $derived(t ? { ...base, ...t.style } : {});

  // drafts: typed, sent when the field is left
  let words = $state("");
  let lead = $state("");
  let start = $state(0);
  let length = $state(0);
  let size = $state(100);
  let lastKey = "";
  $effect(() => {
    const key = t ? `${t.index}|${t.text}|${t.start}|${t.duration}|${look.size}|${t.lead}` : "";
    if (key !== lastKey) {
      lastKey = key;
      if (t) {
        words = t.text;
        lead = t.lead || "";
        start = t.start;
        length = t.duration;
        size = look.size || 100;
      }
    }
  });

  const style = (s) => edit({ op: "edit_text", index: t.index, style: s }, true);
  async function add() {
    const at = Math.max(0, Math.min(ed.now, (reel?.duration || 2) - 1));
    const res = await edit({ op: "add_text", text: "Your words", start: frames(at), duration: 2, style: { position: "center" } }, true);
    if (res) pick({ kind: "text", index: Math.max(...ed.reel.texts.map((x) => x.index)) });
  }
  function saveWords() {
    if (words.trim() && words.trim() !== t.text) edit({ op: "edit_text", index: t.index, text: words }, true);
  }
  function saveLead() {
    if (lead.trim() !== (t.lead || "")) edit({ op: "edit_text", index: t.index, lead: lead.trim() || null }, true);
  }
  function saveTime() {
    if (Math.abs(start - t.start) > 0.01 || Math.abs(length - t.duration) > 0.01)
      edit({ op: "edit_text", index: t.index, start: frames(+start), duration: Math.max(0.2, frames(+length)) }, true);
  }
  function remove() {
    const i = t.index;
    ed.sel = null;
    edit({ op: "delete_text", index: i });
  }
  const select = (x) => pick({ kind: "text", index: x.index });
</script>

<section class="panel">
  <div class="row">
    <h2>On screen</h2>
    <span class="meta">{reel?.texts.length || 0}</span>
    <div class="spacer"></div>
    <button class="btn sm" onclick={add} disabled={ed.busy}><Icon name="plus" size={14} /> Add text</button>
  </div>

  {#if reel?.texts.length}
    <ul class="texts" role="listbox" aria-label="Text on screen">
      {#each reel.texts as x (x.index)}
        <li>
          <button class="item" class:on={t?.index === x.index} role="option" aria-selected={t?.index === x.index} onclick={() => select(x)}>
            <span class="meta">{tc(x.start)}</span>
            <span class="ellipsis">{x.text}</span>
            <span class="kind meta">{kinds[x.type] || x.type}</span>
          </button>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="quiet">No words on this reel. Add a line where the playhead is</p>
  {/if}

</section>
  {#if t}
    <Section id="text-words" title="Words and timing" open={true} summary={`${tc(t.start)} · ${(+t.duration).toFixed(1)} s`}>
      <div class="field">
        <label for="tw">Words</label>
        <textarea id="tw" rows="2" bind:value={words} onblur={saveWords}
                  onkeydown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), e.currentTarget.blur())}></textarea>
        {#if t.type === "hook" && words.trim().split(/\s+/).length > 7}<p class="note">Hooks read best at 7 words or fewer</p>{/if}
      </div>

      <div class="grid2">
        <div class="field">
          <label for="ts">Starts <span class="hint">· s</span></label>
          <div class="row">
            <input id="ts" type="number" step="0.1" min="0" bind:value={start} onchange={saveTime} />
            <button class="btn sm ghost" title="Start at the playhead" onclick={() => ((start = frames(ed.now)), saveTime())}>Here</button>
          </div>
        </div>
        <div class="field">
          <label for="tl">Lasts <span class="hint">· s</span></label>
          <input id="tl" type="number" step="0.1" min="0.2" bind:value={length} onchange={saveTime} />
        </div>
      </div>

    </Section>
    <Section id="text-letters" title="Lettering" open={true} summary={[look.size && `${look.size}px`, look.position || "auto"].filter(Boolean).join(" · ")}>
      <div class="field">
        <span class="lbl">Font</span>
        <FontPicker value={t.style.font} fallback={base.font} onpick={(id) => style({ font: id })} />
      </div>

      <div class="field">
        <label for="tz">Size <span class="hint">· {size}px</span></label>
        <input id="tz" class="range" type="range" min="32" max="300" step="2" bind:value={size} onchange={() => style({ size: +size })} />
      </div>

      <div class="field">
        <span class="lbl">Colour</span>
        <div class="swatches">
          {#each swatches as c}
            <button class="sw" class:on={hex(look.color) === c} style="background: {c}" aria-label={`Colour ${c}`} onclick={() => style({ color: c })}></button>
          {/each}
          <label class="sw custom" title="Any colour">
            <input type="color" value={hex(look.color)} onchange={(e) => style({ color: e.currentTarget.value })} aria-label="Any colour" />
          </label>
        </div>
      </div>

      <div class="field">
        <span class="lbl">Place</span>
        <div class="seg" role="radiogroup" aria-label="Where the text sits">
          {#each positions as [id, name]}
            <button role="radio" aria-checked={!look.y && (look.position || "auto") === id} class:on={!look.y && (look.position || "auto") === id}
                    onclick={() => style({ position: id, y: null, x: null })}>{name}</button>
          {/each}
        </div>
        <p class="quiet small">{look.y != null ? "Placed by hand. " : ""}Or click the preview where it should go</p>
      </div>

    </Section>
    <Section id="text-motion" title="Movement and look" summary={[t.motion || look.anim || "fade", look.look].filter(Boolean).join(" · ")}>
      <div class="grid2">
        <div class="field">
          <label for="ta">Comes in</label>
          <select id="ta" value={look.anim || "fade"} onchange={(e) => style({ anim: e.currentTarget.value })}>
            {#each anims as [id, name]}<option value={id}>{name}</option>{/each}
          </select>
        </div>
      </div>

      <div class="grid2">
        <div class="field">
          <label for="tm">Motion <span class="hint">· animated</span></label>
          <select id="tm" value={t.motion || ""} onchange={(e) => edit({ op: "edit_text", index: t.index, motion: e.currentTarget.value || null }, true)}>
            {#each motions as [id, name]}<option value={id}>{name}</option>{/each}
          </select>
        </div>
        <div class="field">
          <label for="tlk">Look</label>
          <select id="tlk" value={look.look || ""} onchange={(e) => style({ look: e.currentTarget.value || null })}>
            {#each looks as [id, name]}<option value={id}>{name}</option>{/each}
          </select>
        </div>
      </div>

    </Section>
    <Section id="text-extras" title="Extras" summary={[look.uppercase && "capitals", look.fill === "picture" && "see-through", t.lead && "line above"].filter(Boolean).join(" · ") || "none"}>
      <div class="toggles">
        <label class="check"><input type="checkbox" checked={!!look.uppercase} onchange={(e) => style({ uppercase: e.currentTarget.checked })} /> Capitals</label>
        <label class="check" title="The picture shows through the letters"><input type="checkbox" checked={look.fill === "picture"} onchange={(e) => style({ fill: e.currentTarget.checked ? "picture" : null })} /> See-through</label>
      </div>
      <div class="field">
        <label for="tlead">Small line above <span class="hint">· optional</span></label>
        <input id="tlead" type="text" bind:value={lead} onblur={saveLead} onkeydown={(e) => e.key === "Enter" && e.currentTarget.blur()} placeholder="e.g. welcome to" />
      </div>

      <div class="row foot">
        <button class="btn sm ghost danger" onclick={remove}><Icon name="trash" size={14} /> Remove this text</button>
        <div class="spacer"></div>
        {#if Object.keys(t.style).length}<button class="btn sm ghost" onclick={() => style(Object.fromEntries(Object.keys(t.style).map((k) => [k, null])))}>Reset lettering</button>{/if}
      </div>
    </Section>
  {/if}

<style>
  .panel { padding: 16px; display: flex; flex-direction: column; gap: 12px; border-bottom: 1px solid var(--line); }
  .panel + .panel { border-top: 1px solid var(--line); }
  .panel p { margin: 0; }
  .spacer { flex: 1; }
  .texts { margin: 0; padding: 0; list-style: none; max-height: 196px; overflow: auto; }
  .item {
    width: 100%; display: grid; grid-template-columns: 48px 1fr auto; gap: 8px; align-items: center; height: 36px; padding: 0 8px;
    border: 0; border-radius: var(--r-sm); background: none; cursor: pointer; text-align: left; font-size: 13px;
  }
  .item:hover { background: var(--raised); }
  .item.on { background: var(--accent-soft); }
  .kind { color: var(--text-3); }
  .editor { border-top: 1px solid var(--line); padding-top: 16px; }
  .field { margin-bottom: 16px; }
  .lbl { display: block; font-weight: 500; font-size: 13px; margin: 0 0 8px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  input[type="number"] {
    width: 100%; min-height: 36px; padding: 8px 12px; border: 1px solid var(--line-strong); border-radius: var(--r-ctl);
    background: var(--card); font-family: var(--mono); font-size: 13px; outline: none; user-select: text;
  }
  input[type="number"]:focus-visible { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
  .range { width: 100%; accent-color: var(--accent); }
  .swatches { display: flex; flex-wrap: wrap; gap: 8px; }
  .sw { width: 28px; height: 28px; border-radius: 50%; border: 0; cursor: pointer; box-shadow: inset 0 0 0 1px var(--line-strong); padding: 0; margin: 0; }
  .sw.on { box-shadow: inset 0 0 0 1px var(--line-strong), 0 0 0 2px var(--card), 0 0 0 4px var(--accent); }
  .sw.custom { position: relative; overflow: hidden; background: conic-gradient(#ff6b6b, #ffd23c, #7ee0b5, #8fd3ff, #c58bff, #ff6b6b); }
  .sw.custom input { position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%; }
  .seg { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; padding: 4px; background: var(--raised); border-radius: var(--r-ctl); }
  .seg button { height: 28px; border: 0; border-radius: var(--r-sm); background: transparent; color: var(--text-2); cursor: pointer; font-size: 12px; font-weight: 500; }
  .seg button.on { background: var(--card); color: var(--text); box-shadow: inset 0 0 0 1px var(--line); }
  .small { font-size: 12px; margin-top: 8px !important; }
  .toggles { display: flex; flex-direction: column; gap: 6px; padding-top: 2px; }
  .check { display: flex; align-items: center; gap: 8px; margin: 0; font-weight: 400; font-size: 13px; }
  .check input { width: 16px; height: 16px; margin: 0; accent-color: var(--accent); }
  .note { color: var(--accent); font-size: 12px; margin-top: 4px !important; }
  .foot { padding-top: 4px; }
  .danger:hover { color: var(--err); }
</style>
