// Day 1: render HA states, live-update ONLY from WebSocket state_changed
// events relayed by the backend. No optimistic UI.
const statusEl = document.getElementById("status");
const listEl = document.getElementById("entities");
const states = new Map();
const stateAttrs = new Map(); // entity_id -> HA attributes (last_triggered, …)

function render() {
  listEl.innerHTML = "";
  for (const [id, st] of states) {
    if (id.startsWith("input_boolean.")) continue; // helpers back templates; not devices
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = prettyEntity(id);
    name.title = id;
    const dot = document.createElement("span");
    dot.className = "dot" + (st === "on" ? " on" : "");
    dot.title = st;
    li.appendChild(name);
    li.appendChild(dot);
    if (id.startsWith("automation.")) {
      const fired = document.createElement("span");
      fired.className = "fired";
      const lt = (stateAttrs.get(id) || {}).last_triggered;
      fired.textContent = lt ? `last fired ${fmtFired(lt)}` : "never fired";
      fired.title = lt ? `last_triggered: ${lt}` : "this rule has not fired yet";
      li.appendChild(fired);
    }
    listEl.appendChild(li);
  }
  // Ambient strip: sun + lights-on at a glance. Pins follow live state too.
  const sun = states.get("sun.sun");
  const sunState = document.getElementById("sun-state");
  const sunDot = document.getElementById("sun-dot");
  if (sunState) {
    const day = sun === "above_horizon";
    sunState.textContent = sun ? (day ? "Daytime" : "Night") : "—";
    if (sunDot) sunDot.className = "dot" + (sun ? (day ? " day" : " night") : "");
  }
  const onCount = [...states].filter(([id, st]) => id.startsWith("light.") && st === "on").length;
  const lightsOn = document.getElementById("lights-on");
  if (lightsOn) lightsOn.textContent = `${onCount} light${onCount === 1 ? "" : "s"} on`;
  const autoCount = [...states.keys()].filter((id) => id.startsWith("automation.")).length;
  const autoCountEl = document.getElementById("auto-count");
  if (autoCountEl) autoCountEl.textContent = `${autoCount} automation${autoCount === 1 ? "" : "s"}`;
  if (typeof updatePins === "function") updatePins();
  if (typeof syncEntitySelect === "function") syncEntitySelect();
  if (typeof updateSteps === "function") updateSteps();
}

async function load() {
  const res = await fetch("/api/entities");
  const entities = await res.json();
  noteNames(entities);
  states.clear(); // deleted entities (e.g. reset-removed rules) must vanish too
  stateAttrs.clear();
  for (const e of entities) {
    states.set(e.entity_id, e.state);
    stateAttrs.set(e.entity_id, e.attributes || {});
  }
  render();
  await refreshEntities();
}

function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => { statusEl.textContent = "Live"; statusEl.classList.add("on"); };
  ws.onclose = () => { statusEl.textContent = "Reconnecting…"; statusEl.classList.remove("on"); setTimeout(connect, 2000); };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    const st = msg?.data?.new_state;
    if (st) {
      states.set(st.entity_id, st.state);
      stateAttrs.set(st.entity_id, st.attributes || {});
      render();
    }
  };
}

// Day 2: room photo, SAM regions, manual fallback. Overlays are drawn
// deterministically from the scene graph; reload shows the same graph.
const photoInput = document.getElementById("photo-input");
const photoEl = document.getElementById("photo");
const regionsEl = document.getElementById("regions");
const phraseInput = document.getElementById("phrase-input");
const phraseChips = document.getElementById("phrase-chips");
const segmentBtn = document.getElementById("segment-btn");
const drawBtn = document.getElementById("draw-btn");
const photoMsg = document.getElementById("photo-msg");
const regionList = document.getElementById("region-list");
let photoId = null;
let drawing = false;
let drawStart = null;

const SUGGESTED = ["lamp", "string lights", "patio door", "tv", "smart display", "reading light"];
for (const p of SUGGESTED) {
  const chip = document.createElement("button");
  chip.className = "chip";
  chip.textContent = p;
  chip.addEventListener("click", () => {
    phraseInput.value = p;
    segmentBtn.click();
  });
  phraseChips.appendChild(chip);
}

function say(msg) { photoMsg.textContent = msg; }

function fmtFired(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString();
}

// Guided demo rail: 1 Photo → 2 Bind → 3 Tap → 4 Automate → 5 What-If.
// Each chip lights up as its step completes this session; the next open
// step is highlighted so a stranger knows what to do. Buttons for later
// steps stay disabled until their prerequisites exist.
let tapped = false;
let whatifDone = false;
function updateSteps() {
  const rail = document.getElementById("steps");
  if (!rail || typeof whatifProposal === "undefined") return;
  const done = [
    photoId != null,
    Object.keys(bindings).length > 0,
    tapped,
    whatifProposal.options.length > 0,
    whatifDone,
  ];
  [...rail.children].forEach((li, i) => {
    li.classList.toggle("done", !!done[i]);
    li.classList.toggle("active", !done[i] && (i === 0 || done[i - 1]));
  });
}

let bindings = {};
let selectedId = null;

let lastRegions = [];

function renderRegions(regions) {
  lastRegions = regions;
  regionsEl.innerHTML = "";
  regionList.innerHTML = "";
  for (const r of regions) {
    const box = document.createElement("div");
    box.className = "region box" + (r.source === "manual" ? " manual" : "");
    box.dataset.oid = r.object_id;
    box.style.left = `${r.x * 100}%`;
    box.style.top = `${r.y * 100}%`;
    box.style.width = `${r.w * 100}%`;
    box.style.height = `${r.h * 100}%`;
    box.title = `${r.object_id} (${r.source})`;
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = r.object_id;
    box.appendChild(tag);
    if (bindings[r.object_id]) box.classList.add("bound");
    regionsEl.appendChild(box);
    // Screens (TV, smart display) light up when their switch is on.
    if (/tv|display|screen/i.test(`${r.object_id} ${r.phrase}`)) {
      const screen = document.createElement("div");
      screen.className = "screen";
      screen.dataset.oid = r.object_id;
      screen.style.left = `${r.x * 100}%`;
      screen.style.top = `${r.y * 100}%`;
      screen.style.width = `${r.w * 100}%`;
      screen.style.height = `${r.h * 100}%`;
      regionsEl.appendChild(screen);
    }
    // Device pin: the everyday face. Boxes appear only when selected/drawing.
    const pin = document.createElement("button");
    pin.className = "pin" + (r.source === "manual" ? " manual" : "");
    pin.dataset.oid = r.object_id;
    pin.style.left = `${(r.x + r.w / 2) * 100}%`;
    pin.style.top = `${(r.y + r.h / 2) * 100}%`;
    pin.title = `${r.object_id} (${r.source})`;
    pin.textContent = shortPinLabel(r.object_id);
    if (bindings[r.object_id]) pin.classList.add("bound");
    const activate = async (ev) => {
      if (drawing) return;
      ev.stopPropagation();
      selectRegion(r.object_id);
      if (bindings[r.object_id]) await tapSelected();
    };
    pin.addEventListener("click", activate);
    box.addEventListener("click", activate);
    regionsEl.appendChild(pin);
    const li = document.createElement("li");
    li.className = r.source;
    li.dataset.oid = r.object_id;
    const label = document.createElement("span");
    label.textContent = `${r.object_id} · ${r.phrase}`;
    li.appendChild(label);
    const badge = document.createElement("span");
    badge.className = "state-badge";
    li.appendChild(badge);
    li.title = `source: ${r.source}`;
    regionList.appendChild(li);
  }
  if (selectedId) showSelected(selectedId);
  updatePins();
}

// Pin pills carry full device names ("Reading Light", not "Reading") so two
// same-letter regions are never ambiguous. Falls back to region name.
function shortPinLabel(oid) {
  const entity = bindings[oid];
  if (entity) return prettyEntity(entity);
  return prettyOid(oid);
}

function updatePins() {
  for (const pin of regionsEl.querySelectorAll(".pin")) {
    const entity = bindings[pin.dataset.oid];
    pin.textContent = shortPinLabel(pin.dataset.oid);
    pin.classList.toggle("on", !!entity && states.get(entity) === "on");
    pin.classList.toggle("selected", pin.dataset.oid === selectedId);
  }
  for (const box of regionsEl.querySelectorAll(".box")) {
    box.classList.toggle("selected", box.dataset.oid === selectedId);
  }
  for (const screen of regionsEl.querySelectorAll(".screen")) {
    const entity = bindings[screen.dataset.oid];
    screen.classList.toggle("on", !!entity && states.get(entity) === "on");
  }
  // Region list mirrors live state: ON/OFF for bound regions, source tag otherwise.
  for (const li of regionList.querySelectorAll("li[data-oid]")) {
    const badge = li.querySelector(".state-badge");
    if (!badge) continue;
    const entity = bindings[li.dataset.oid];
    if (!entity) {
      badge.textContent = li.className.includes("manual") ? "hand-drawn" : "unbound";
      badge.classList.remove("on");
    } else {
      const on = states.get(entity) === "on";
      badge.textContent = on ? "ON" : "OFF";
      badge.classList.toggle("on", on);
    }
  }
}

async function refreshGraph() {
  if (!photoId) return;
  const res = await fetch(`/api/photos/${photoId}/graph`);
  const graph = await res.json();
  bindings = graph.bindings || {};
  renderRegions(graph.regions);
  refreshAutoSelects(Object.keys(bindings));
  document.getElementById("plan-btn").disabled = Object.keys(bindings).length === 0;
  if (selectedId) showSelected(selectedId);
  updateSteps();
}

function selectRegion(objectId) {
  selectedId = objectId;
  document.getElementById("sheet").hidden = false;
  showSelected(objectId);
  updatePins();
}

function deselect() {
  selectedId = null;
  document.getElementById("sheet").hidden = true;
  updatePins();
}
document.getElementById("sheet-close").addEventListener("click", deselect);
photoEl.addEventListener("click", () => { if (!drawing) deselect(); });

function showSelected(objectId) {
  const info = document.getElementById("selected-info");
  const bound = bindings[objectId];
  info.textContent = bound
    ? `${prettyOid(objectId)} → ${prettyEntity(bound)}`
    : `${prettyOid(objectId)} (unbound)`;
  // The picker follows the selection: preselect the bound device when bound.
  if (entitySelect && bound &&
      [...entitySelect.options].some((o) => o.value === bound)) {
    entitySelect.value = bound;
  }
}

const sourceSelect = document.getElementById("source-select");
const targetSelect = document.getElementById("target-select");
const autoText = document.getElementById("auto-text");
const planView = document.getElementById("plan-view");
function refreshAutoSelects(boundIds) {
  for (const sel of [sourceSelect, targetSelect]) {
    const keep = sel.value;
    sel.innerHTML = "";
    for (const id of boundIds) {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = `${prettyOid(id)} → ${prettyEntity(bindings[id])}`;
      sel.appendChild(opt);
    }
    if (boundIds.includes(keep)) sel.value = keep;
  }
  // Rearrange picker: bound lamps only.
  const moveObject = document.getElementById("move-object");
  if (moveObject) {
    const keep = moveObject.value;
    moveObject.innerHTML = "";
    for (const id of boundIds.filter((o) => (bindings[o] || "").startsWith("light."))) {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = `${prettyOid(id)} → ${prettyEntity(bindings[id])}`;
      moveObject.appendChild(opt);
    }
    if ([...moveObject.options].some((o) => o.value === keep)) moveObject.value = keep;
    document.getElementById("move-btn").disabled = moveObject.options.length === 0;
  }
}
document.getElementById("plan-btn").addEventListener("click", async () => {
  if (!photoId) { say("Upload a photo first."); return; }
  if (!sourceSelect.value || !targetSelect.value) { say("Bind regions first."); return; }
  say("Asking Spark for an automation plan…");
  planView.innerHTML = "";
  const delayEl = document.getElementById("auto-delay");
  const providerEl = document.getElementById("auto-provider");
  const res = await fetch("/api/automations/propose", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      photo_id: photoId,
      source_object_id: sourceSelect.value,
      target_object_id: targetSelect.value,
      text: autoText.value,
      provider: providerEl ? providerEl.value : "hosted",
      delay_s: delayEl && delayEl.value !== "" ? Number(delayEl.value) : null,
    }),
  });
  const body = await res.json();
  if (!res.ok) {
    const div = document.createElement("div");
    div.className = "plan rejected";
    div.textContent = `Rejected: ${body.detail || res.status}`;
    planView.appendChild(div);
    say("Plan rejected — see Automate panel.");
    return;
  }
  const div = document.createElement("div");
  div.className = "plan";
  const ir = body.ir;
  const cond = ir.condition ? ` when sun ${ir.condition.sun.replace("_", " ")}` : "";
  const delay = ir.delay_s ? `, off after ${ir.delay_s}s` : "";
  const providerNote = body.provider === "open"
    ? `<br /><span class="muted">Via open-weight model on Baseten (${body.model || "see host config"}) — same prompt, schema, validator and compiler as hosted.</span>`
    : `<br /><span class="muted">Via hosted ${body.model || "Muse Spark"}.</span>`;
  div.innerHTML = `<strong>${ir.description || "Automation plan"}</strong>` +
    `<br />${prettyEntity(ir.trigger.entity_id)} → ${prettyEntity(ir.action.entity_id)}${cond}${delay}` +
    `<br /><span class="muted">Compiled ${body.compiled.trigger.length} trigger(s), ` +
    `${body.compiled.action.length} action step(s) in ${body.latency_ms} ms. ` +
    `Approval required before deploy.</span>` + providerNote;
  if (body.conflict_warning) {
    const warn = document.createElement("div");
    warn.className = "plan conflict";
    warn.textContent = `Heads up: ${body.conflict_warning}`;
    div.appendChild(warn);
  }
  const btn = document.createElement("button");
  btn.className = "btn primary";
  btn.textContent = "Approve & deploy";
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "Deploying…";
    const r2 = await fetch(`/api/automations/${body.proposal_id}/approve`, { method: "POST" });
    const b2 = await r2.json();
    if (r2.ok) {
      const via = body.provider === "open" ? ` via open-weight (${body.model})` : "";
      const label = b2.already && b2.proposal_id
        ? `Already deployed (plan #${b2.proposal_id})${via}`
        : `Deployed ${b2.automation_id}${via}`;
      btn.textContent = label;
      say(`${label}.`);
      await refreshProposals();
    } else {
      btn.disabled = false;
      btn.textContent = "Approve & deploy";
      say(`Deploy failed: ${b2.detail || r2.status}`);
    }
  });
  div.appendChild(document.createElement("br"));
  div.appendChild(btn);
  planView.appendChild(div);
  say("Plan ready — review and approve to deploy.");
  await refreshProposals();
});

const whatifProposal = document.getElementById("whatif-proposal");
const whatifDoor = document.getElementById("whatif-door");
const whatifSun = document.getElementById("whatif-sun");
const whatifView = document.getElementById("whatif-view");
async function refreshProposals() {
  // Proposals belong to the current photo only. Before any photo is chosen
  // the list stays empty — global history would look prepopulated.
  const keep = whatifProposal.value;
  whatifProposal.innerHTML = "";
  if (!photoId) return;
  const res = await fetch(`/api/automations/proposals?photo_id=${photoId}`);
  const body = await res.json();
  for (const p of body.proposals) {
    const opt = document.createElement("option");
    opt.value = p.id;
    // Name the bound devices, not the region ids: "Patio Door → Reading Light".
    const sEnt = bindings[p.source_id];
    const tEnt = bindings[p.target_id];
    opt.textContent = `#${p.id} ${sEnt ? prettyEntity(sEnt) : prettyOid(p.source_id)} → ` +
      `${tEnt ? prettyEntity(tEnt) : prettyOid(p.target_id)} [${p.status}]`;
    whatifProposal.appendChild(opt);
  }
  if ([...whatifProposal.options].some((o) => o.value === keep)) whatifProposal.value = keep;
  document.getElementById("whatif-btn").disabled = whatifProposal.options.length === 0;
  updateSteps();
}
document.getElementById("whatif-btn").addEventListener("click", async () => {
  if (!photoId) { say("Upload a photo first."); return; }
  if (!whatifProposal.value) { say("Generate a plan first."); return; }
  const res = await fetch("/api/whatif", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      proposal_id: Number(whatifProposal.value),
      door: whatifDoor.value,
      sun: whatifSun.value,
    }),
  });
  const body = await res.json();
  whatifView.innerHTML = "";
  const div = document.createElement("div");
  div.className = "plan" + (body.fires ? "" : " rejected");
  const delayNote = res.ok && body.fires && body.delay_s
    ? ` Then off after ${body.delay_s}s.`
    : "";
  div.textContent = res.ok
    ? (body.fires
      ? `SIMULATED: fires — ${body.condition_note}.${delayNote}`
      : `SIMULATED: no fire — ${body.condition_note}.`)
    : `What-If failed: ${body.detail || res.status}`;
  whatifView.appendChild(div);
  if (res.ok) whatifDone = true;
  updateSteps();
});

async function tapSelected() {
  if (!photoId || !selectedId) return;
  const res = await fetch(`/api/photos/${photoId}/tap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ object_id: selectedId }),
  });
  const body = await res.json();
  if (res.ok) tapped = true;
  updateSteps();
  say(res.ok ? `Tapped ${selectedId} (${body.action}). Watch the Devices panel.` : `Tap failed: ${body.detail || res.status}`);
}

// Friendly display names everywhere: HA entity_ids never surface in the UI.
// Values stay entity_ids; only labels are humanized.
const names = new Map();
function prettyEntity(id) {
  if (names.has(id)) return names.get(id);
  return id.split(".").slice(1).join(" ").replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
function prettyOid(oid) {
  return oid.replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bTv\b/, "TV");
}
function noteNames(entities) {
  for (const e of entities) {
    const friendly = (e.attributes || {}).friendly_name;
    if (friendly) names.set(e.entity_id, friendly);
  }
}
const entitySelect = document.getElementById("entity-select");
const BINDABLE_INPUTS = ["input_boolean.tv_on", "input_boolean.display_on"];
function syncEntitySelect() {
  // Manual bind picker follows live state: rebuilt from the states map on
  // every render, so its (on/off) suffix can never go stale.
  if (!entitySelect) return;
  const keep = selectedId && bindings[selectedId] ? bindings[selectedId] : entitySelect.value;
  entitySelect.innerHTML = "";
  for (const [id, st] of states) {
    const domain = id.split(".")[0];
    if (domain !== "light" && domain !== "binary_sensor" &&
        !BINDABLE_INPUTS.includes(id)) continue;
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = `${prettyEntity(id)} (${st})`;
    entitySelect.appendChild(opt);
  }
  if ([...entitySelect.options].some((o) => o.value === keep)) entitySelect.value = keep;
}
async function refreshEntities() {
  // Manual bind picker (P0 baseline if auto-bind ever fails) + name map.
  const res = await fetch("/api/entities");
  const entities = await res.json();
  noteNames(entities);
  syncEntitySelect();
}
document.getElementById("bind-btn").addEventListener("click", async () => {
  if (!photoId || !selectedId || !entitySelect) { say("Select a region first."); return; }
  const res = await fetch(`/api/photos/${photoId}/bindings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ object_id: selectedId, entity_id: entitySelect.value }),
  });
  const body = await res.json();
  say(res.ok ? `Bound ${prettyOid(selectedId)} → ${prettyEntity(entitySelect.value)}.` : `Bind failed: ${body.detail || res.status}`);
  await refreshGraph();
});

document.getElementById("unbind-btn").addEventListener("click", async () => {
  if (!photoId || !selectedId) return;
  await fetch(`/api/photos/${photoId}/bindings/${selectedId}`, { method: "DELETE" });
  say(`Unbound ${selectedId}.`);
  await refreshGraph();
});

const proposalList = document.getElementById("proposal-list");
async function applyProposal(p) {
  const res = await fetch(`/api/photos/${photoId}/bindings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ object_id: p.object_id, entity_id: p.entity_id }),
  });
  return res.ok;
}
document.getElementById("suggest-btn").addEventListener("click", async () => {
  if (!photoId) { say("Upload a photo first."); return; }
  say("Asking Spark for binding suggestions…");
  const res = await fetch(`/api/photos/${photoId}/suggest-bindings`, { method: "POST" });
  const body = await res.json();
  if (!res.ok) { say(`Suggest failed: ${body.detail || res.status}`); return; }
  proposalList.innerHTML = "";
  if (!body.proposals.length) {
    say(body.note || "No suggestions — everything is bound or nothing matched.");
    return;
  }
  say(`${body.proposals.length} suggestion(s). Approve each, or all at once.`);
  for (const p of body.proposals) {
    const li = document.createElement("li");
    li.textContent = `${prettyOid(p.object_id)} → ${prettyEntity(p.entity_id)} (${Math.round(p.confidence * 100)}%): ${p.reason}${p.conflict ? " [CONFLICT]" : ""}`;
    const btn = document.createElement("button");
    btn.className = "btn";
    btn.textContent = "Approve";
    btn.addEventListener("click", async () => {
      say(await applyProposal(p) ? `Bound ${p.object_id}.` : `Bind failed for ${p.object_id}.`);
      await refreshGraph();
    });
    li.appendChild(btn);
    proposalList.appendChild(li);
  }
  const all = document.createElement("button");
  all.className = "btn primary";
  all.textContent = "Approve all";
  all.addEventListener("click", async () => {
    for (const p of body.proposals) {
      if (p.conflict) continue;
      await applyProposal(p);
    }
    say("Approved all non-conflicting suggestions.");
    await refreshGraph();
  });
  proposalList.appendChild(all);
});
const moveView = document.getElementById("move-view");
document.getElementById("move-btn").addEventListener("click", async () => {
  if (!photoId) { say("Upload a photo first."); return; }
  const objectSelect = document.getElementById("move-object");
  const instruction = document.getElementById("move-text").value.trim();
  if (!objectSelect.value) { say("Bind a lamp first."); return; }
  say("Asking Spark where this lamp should go…");
  moveView.innerHTML = "";
  const res = await fetch(`/api/photos/${photoId}/move-propose`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ photo_id: photoId, object_id: objectSelect.value, instruction }),
  });
  const body = await res.json();
  if (!res.ok) { say(`Move proposal failed: ${body.detail || res.status}`); return; }
  const div = document.createElement("div");
  div.className = "plan";
  div.textContent = `Move ${prettyOid(body.object_id)}: ${body.reason} ` +
    `(pin ${body.from_xy.map((v) => v.toFixed(2)).join(",")} → ${body.to_xy.map((v) => v.toFixed(2)).join(",")}).`;
  const prevBtn = document.createElement("button");
  prevBtn.className = "btn";
  prevBtn.textContent = "Preview move";
  prevBtn.addEventListener("click", async () => {
    prevBtn.disabled = true;
    const r2 = await fetch(`/api/photos/${photoId}/move-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ photo_id: photoId, move_id: body.move_id }),
    });
    const b2 = await r2.json();
    if (!r2.ok) {
      prevBtn.disabled = false;
      say(`Move preview failed: ${b2.detail || r2.status}`);
      return;
    }
    const img = document.createElement("img");
    img.src = b2.preview_url;
    img.alt = "Illustrative move preview";
    img.className = "preview-img";
    div.appendChild(document.createElement("br"));
    div.appendChild(img);
    const note = document.createElement("p");
    note.className = "muted";
    note.textContent = "Illustrative preview — the pin moves, the light stays put.";
    div.appendChild(note);
    const okBtn = document.createElement("button");
    okBtn.className = "btn primary";
    okBtn.textContent = "Approve move";
    okBtn.addEventListener("click", async () => {
      const r3 = await fetch(`/api/photos/${photoId}/move-approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ photo_id: photoId, move_id: body.move_id }),
      });
      const b3 = await r3.json();
      if (r3.ok) {
        okBtn.disabled = true;
        okBtn.textContent = `Moved ${prettyOid(b3.object_id)}`;
        say(`Pin moved. Tap it — same light, same binding.`);
        await refreshGraph();
      } else {
        say(`Move failed: ${b3.detail || r3.status}`);
      }
    });
    const noBtn = document.createElement("button");
    noBtn.className = "btn";
    noBtn.textContent = "Decline";
    noBtn.addEventListener("click", () => {
      moveView.innerHTML = "";
      say("Move declined — nothing changed.");
    });
    div.appendChild(okBtn);
    div.appendChild(document.createTextNode(" "));
    div.appendChild(noBtn);
  });
  div.appendChild(document.createElement("br"));
  div.appendChild(prevBtn);
  moveView.appendChild(div);
});

const sceneList = document.getElementById("scene-list");
async function refreshScenes() {
  const res = await fetch("/api/scenes");
  const body = await res.json();
  sceneList.innerHTML = "";
  for (const s of body.scenes) {
    const li = document.createElement("li");
    const states = Object.entries(s.states)
      .map(([id, st]) => `${prettyEntity(id)} ${st}`).join(", ");
    li.textContent = `${s.name}: ${states} `;
    const apply = document.createElement("button");
    apply.className = "btn primary";
    apply.textContent = "Apply";
    apply.title = "This click is the approval: sets the listed lights";
    apply.addEventListener("click", async () => {
      const r = await fetch(`/api/scenes/${encodeURIComponent(s.name)}/apply`, { method: "POST" });
      const b = await r.json();
      say(r.ok ? `Scene "${s.name}" applied (${b.applied.length} lights).`
                : `Apply failed: ${b.detail || r.status}`);
    });
    const del = document.createElement("button");
    del.className = "btn";
    del.textContent = "Delete";
    del.addEventListener("click", async () => {
      await fetch(`/api/scenes/${encodeURIComponent(s.name)}`, { method: "DELETE" });
      await refreshScenes();
    });
    li.appendChild(apply);
    li.appendChild(document.createTextNode(" "));
    li.appendChild(del);
    sceneList.appendChild(li);
  }
}
document.getElementById("scene-save-btn").addEventListener("click", async () => {
  const input = document.getElementById("scene-name");
  const name = input.value.trim();
  if (!name) { say("Name the scene first."); return; }
  const res = await fetch("/api/scenes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const body = await res.json();
  say(res.ok ? `Scene "${body.name}" saved.` : `Save failed: ${body.detail || res.status}`);
  input.value = "";
  await refreshScenes();
});
refreshScenes();

document.getElementById("reset-btn").addEventListener("click", async () => {
  const btn = document.getElementById("reset-btn");
  btn.disabled = true; // one reset at a time; double-clicks read as failures
  const res = await fetch("/api/reset", { method: "POST" });
  if (!res.ok) { say("Reset failed."); btn.disabled = false; return; }
  const body = await res.json();
  // A reset must LOOK like a reset: panels refresh from the server so no
  // stale automation, plan, or preview survives on screen.
  planView.innerHTML = "";
  whatifView.innerHTML = "";
  proposalList.innerHTML = "";
  moveView.innerHTML = "";
  await refreshScenes();
  if (typeof advisorView !== "undefined" && advisorView) advisorView.innerHTML = "";
  if (typeof todView !== "undefined" && todView) todView.innerHTML = "";
  if (typeof advisorPreviewWrap !== "undefined" && advisorPreviewWrap) advisorPreviewWrap.hidden = true;
  if (typeof voiceTranscript !== "undefined" && voiceTranscript) voiceTranscript.hidden = true;
  if (typeof voiceAction !== "undefined" && voiceAction) voiceAction.innerHTML = "";
  autoText.value = "";
  whatifDoor.value = "on";
  whatifSun.value = "day";
  const moveText = document.getElementById("move-text");
  if (moveText) moveText.value = "";
  const sceneName = document.getElementById("scene-name");
  if (sceneName) sceneName.value = "";
  tapped = false;
  whatifDone = false;
  updateSteps();
  deselect();
  await load();
  if (photoId) { await refreshGraph(); await refreshProposals(); }
  const n = (body.automations_cleared || []).length;
  say(`Baseline restored: everything off, ${n} automation${n === 1 ? "" : "s"} deleted, ` +
    `${body.bindings_cleared || 0} bindings cleared. Suggest bindings to start over.`);
  document.getElementById("reset-btn").disabled = false;
});

document.getElementById("demo-btn").addEventListener("click", async () => {
  say("Loading the demo room photo…");
  const res = await fetch("/api/photos/demo", { method: "POST" });
  if (!res.ok) { say(`Demo photo failed: ${res.status}`); return; }
  await usePhoto(await res.json());
});

photoInput.addEventListener("change", async () => {
  const file = photoInput.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  say("Uploading and auto-segmenting…");
  const res = await fetch("/api/photos", { method: "POST", body: form });
  if (!res.ok) { say(`Upload failed: ${res.status}`); return; }
  await usePhoto(await res.json());
});

async function usePhoto(body) {
  photoId = body.photo_id;
  tapped = false;
  whatifDone = false;
  document.getElementById("suggest-btn").disabled = false;
  photoEl.src = `/api/photos/${photoId}/image`;
  photoEl.hidden = false;
  document.getElementById("photo-empty").classList.add("gone");
  if (body.reused) {
    say(`Photo ${photoId} already known — loaded its regions directly.`);
  } else {
    const hits = (body.auto_segment || []).filter((a) => a.regions.length > 0);
    const missed = (body.auto_segment || []).filter((a) => a.regions.length === 0);
    say(`Photo ${photoId} segmented: ${hits.length} phrase(s) hit` +
      (missed.length ? `, missed: ${missed.map((a) => a.phrase).join(", ")} — draw those manually.` : "."));
  }
  await refreshGraph();
  await refreshProposals();
}

segmentBtn.addEventListener("click", async () => {
  if (!photoId) { say("Upload a photo first."); return; }
  const phrase = phraseInput.value.trim();
  if (!phrase) { say("Type a concept phrase first."); return; }
  say(`Segmenting "${phrase}"…`);
  const res = await fetch(`/api/photos/${photoId}/segment`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phrase }),
  });
  const body = await res.json();
  if (!res.ok) {
    say(`SAM missed (${body.detail || res.status}). Draw the region manually instead.`);
    return;
  }
  if (body.regions.length === 0) {
    say(body.note || "No match. Draw the region manually instead.");
    return;
  }
  const matched = body.matched_phrase && body.matched_phrase !== phrase
    ? ` (matched as "${body.matched_phrase}")` : "";
  say(`"${phrase}"${matched}: ${body.regions.length} region(s) in ${body.latency_ms} ms.`);
  await refreshGraph();
});

function photoCoords(ev) {
  const rect = photoEl.getBoundingClientRect();
  return {
    x: Math.min(Math.max((ev.clientX - rect.left) / rect.width, 0), 1),
    y: Math.min(Math.max((ev.clientY - rect.top) / rect.height, 0), 1),
  };
}

drawBtn.addEventListener("click", () => {
  if (!photoId) { say("Upload a photo first."); return; }
  drawing = !drawing;
  drawBtn.textContent = drawing ? "Cancel draw" : "Draw region";
  drawBtn.classList.toggle("active", drawing);
  document.body.classList.toggle("drawing", drawing);
  say(drawing ? "Drag on the photo to draw the fallback region." : "Draw cancelled.");
});

const photoWrap = document.getElementById("photo-wrap");
photoWrap.addEventListener("pointerdown", (ev) => {
  if (!drawing) return;
  drawStart = photoCoords(ev);
});
photoWrap.addEventListener("pointerup", async (ev) => {
  if (!drawing || !drawStart) return;
  const end = photoCoords(ev);
  const x = Math.min(drawStart.x, end.x);
  const y = Math.min(drawStart.y, end.y);
  const w = Math.abs(end.x - drawStart.x);
  const h = Math.abs(end.y - drawStart.y);
  drawing = false;
  drawBtn.textContent = "Draw region";
  drawBtn.classList.remove("active");
  document.body.classList.remove("drawing");
  if (w < 0.01 || h < 0.01) { say("Box too small, ignored."); return; }
  const label = phraseInput.value.trim() || "region";
  const res = await fetch(`/api/photos/${photoId}/regions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label, x, y, w, h }),
  });
  if (!res.ok) { say(`Manual region rejected: ${res.status}`); return; }
  const body = await res.json();
  say(`Manual region saved as ${body.object_id}.`);
  await refreshGraph();
});

// Design Advisor + time-of-day previews. Suggestions never write to HA:
// Preview shows an illustrative image, Apply is the only HA write, and
// Decline (clearing the panel) changes nothing.
const advisorView = document.getElementById("advisor-view");
const advisorPreviewWrap = document.getElementById("advisor-preview-wrap");
const advisorPreview = document.getElementById("advisor-preview");
const todView = document.getElementById("tod-view");
function advisorActionsText(setting) {
  return (setting.actions || []).map((a) =>
    `${prettyEntity(a.entity_id)} ${a.service === "light.turn_on" ? "on" : "off"}`).join(", ");
}
function advisorApplyButton(setting, label) {
  const btn = document.createElement("button");
  btn.className = "btn primary";
  btn.textContent = label || "Apply this setting";
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "Applying…";
    const res = await fetch("/api/advisor/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ setting }),
    });
    const body = await res.json();
    if (res.ok) {
      btn.textContent = `Applied: ${body.setting}`;
      say(`Applied ${body.setting} in Home Assistant.`);
      await refreshGraph();
    } else {
      btn.disabled = false;
      btn.textContent = label || "Apply this setting";
      say(`Apply failed: ${body.detail || res.status}`);
    }
  });
  return btn;
}
document.getElementById("advisor-btn").addEventListener("click", async () => {
  if (!photoId) { say("Upload a photo first."); return; }
  say("Asking Spark for lighting settings…");
  advisorView.innerHTML = "";
  const res = await fetch("/api/advisor/suggest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      photo_id: photoId,
      request_text: document.getElementById("advisor-text").value,
    }),
  });
  const body = await res.json();
  if (!res.ok) {
    const div = document.createElement("div");
    div.className = "plan rejected";
    div.textContent = `Advisor rejected: ${body.detail || res.status}`;
    advisorView.appendChild(div);
    return;
  }
  for (const setting of body.settings) {
    const div = document.createElement("div");
    div.className = "plan";
    div.innerHTML = `<strong>${setting.name}</strong><br />${setting.description}` +
      `<br /><span class="muted">${advisorActionsText(setting)}</span>`;
    const previewBtn = document.createElement("button");
    previewBtn.className = "btn";
    previewBtn.textContent = "Preview (illustrative)";
    previewBtn.addEventListener("click", async () => {
      previewBtn.disabled = true;
      previewBtn.textContent = "Generating preview…";
      const r2 = await fetch("/api/advisor/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          photo_id: photoId,
          setting,
          request_text: document.getElementById("advisor-text").value,
        }),
      });
      const b2 = await r2.json();
      previewBtn.disabled = false;
      previewBtn.textContent = "Preview (illustrative)";
      if (!r2.ok) { say(`Preview failed: ${b2.detail || r2.status}`); return; }
      advisorPreview.src = b2.preview_url;
      advisorPreviewWrap.hidden = false;
      say(`Illustrative preview ready via ${b2.model}. Approving applies only the listed light actions.`);
    });
    div.appendChild(document.createElement("br"));
    div.appendChild(previewBtn);
    div.appendChild(advisorApplyButton(setting));
    advisorView.appendChild(div);
  }
  const decline = document.createElement("button");
  decline.className = "btn";
  decline.textContent = "Decline — change nothing";
  decline.addEventListener("click", () => {
    advisorView.innerHTML = "";
    advisorPreviewWrap.hidden = true;
    say("Declined. Nothing changed in Home Assistant.");
  });
  advisorView.appendChild(decline);
  say("Advisor settings ready — preview or apply one, or decline.");
});
document.getElementById("tod-btn").addEventListener("click", async () => {
  if (!photoId) { say("Upload a photo first."); return; }
  const variant = document.getElementById("tod-variant").value;
  say(`Generating ${variant} preview…`);
  todView.innerHTML = "";
  const res = await fetch("/api/advisor/time-of-day", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ photo_id: photoId, variant }),
  });
  const body = await res.json();
  if (!res.ok) {
    const div = document.createElement("div");
    div.className = "plan rejected";
    div.textContent = `Time-of-day preview failed: ${body.detail || res.status}`;
    todView.appendChild(div);
    return;
  }
  const div = document.createElement("div");
  div.className = "plan";
  div.innerHTML = `<strong>${body.label}</strong> — illustrative preview<br />${body.description}` +
    `<br /><span class="muted">${advisorActionsText(body.setting)}</span>`;
  const img = document.createElement("img");
  img.src = body.preview_url;
  img.alt = `${body.label} illustrative preview`;
  div.appendChild(img);
  div.appendChild(advisorApplyButton(body.setting, "Apply matching settings"));
  todView.appendChild(div);
  say(`${body.label} preview ready (illustrative). Apply to set the matching lights.`);
});

// Voice: push-to-talk into the typed pipeline. Hold the button to
// record; releasing it transcribes once. The transcript is always
// shown, a supported automation transcript fills the Automate box
// (the user still clicks Generate plan, then approves), a supported
// tap transcript shows an explicit control button, and anything else
// shows "not supported yet" and is never executed. No audio is kept.
const voiceBtn = document.getElementById("voice-btn");
const voiceTranscript = document.getElementById("voice-transcript");
const voiceAction = document.getElementById("voice-action");
let voiceRecorder = null;
let voiceChunks = [];
function showTranscript(text, supported) {
  voiceTranscript.hidden = false;
  voiceTranscript.className = "plan" + (supported === false ? " rejected" : "");
  voiceTranscript.textContent = `Transcript: "${text}"` +
    (supported === false ? " — not supported yet." : "");
}
function objectIdForEntity(entityId) {
  for (const [objectId, bound] of Object.entries(bindings)) {
    if (bound === entityId) return objectId;
  }
  return null;
}
async function sendVoiceRecording(blob) {
  voiceTranscript.hidden = false;
  voiceTranscript.className = "plan";
  voiceTranscript.textContent = "Transcribing…";
  voiceAction.innerHTML = "";
  const form = new FormData();
  form.append("file", blob, "voice.wav");
  const res = await fetch("/api/voice/transcribe", { method: "POST", body: form });
  const body = await res.json();
  if (!res.ok) {
    voiceTranscript.className = "plan rejected";
    voiceTranscript.textContent = `Transcription failed: ${body.detail || res.status}`;
    say("Transcription failed.");
    return;
  }
  showTranscript(body.transcript, body.supported);
  if (!body.supported) {
    say("Not supported yet. Try one of the listed utterances, or type instead.");
    return;
  }
  const matched = body.matched;
  if (matched.kind === "tap-control") {
    const btn = document.createElement("button");
    btn.className = "btn primary";
    btn.textContent = `Turn ${prettyEntity(matched.entity_id)} on`;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      const r2 = await fetch("/api/voice/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_id: matched.entity_id, service: matched.service }),
      });
      const b2 = await r2.json();
      if (r2.ok) {
        btn.textContent = `Turned ${prettyEntity(matched.entity_id)} on`;
        say(`Turned ${prettyEntity(matched.entity_id)} on.`);
        await refreshGraph();
      } else {
        btn.disabled = false;
        say(`Voice control failed: ${b2.detail || r2.status}`);
      }
    });
    voiceAction.appendChild(btn);
    say("Transcript matches a supported tap-control utterance. Click to turn the light on.");
    return;
  }
  // Automation pattern: fill the typed pipeline, do not generate yet.
  autoText.value = matched.automate_text || "";
  const sourceId = objectIdForEntity(matched.source_entity);
  const targetId = objectIdForEntity(matched.target_entity);
  if (sourceId) sourceSelect.value = sourceId;
  if (targetId) targetSelect.value = targetId;
  say("Transcript filled into Automate. Review it, then Generate plan and approve as usual.");
}
if (voiceBtn) {
  const startVoice = async (ev) => {
    ev.preventDefault();
    if (!photoId) { say("Upload a photo first."); return; }
    if (typeof MediaRecorder === "undefined") {
      say("Voice recording is not supported in this browser. Type the instruction instead.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      voiceChunks = [];
      voiceRecorder = new MediaRecorder(stream);
      voiceRecorder.ondataavailable = (e) => { if (e.data.size) voiceChunks.push(e.data); };
      voiceRecorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        if (voiceChunks.length) {
          toWav16k(new Blob(voiceChunks)).then(sendVoiceRecording).catch(() => {
            say("Could not prepare that recording (browser audio unsupported). Type it instead.");
          });
        }
      };
      voiceRecorder.start();
      voiceBtn.textContent = "Listening… release to send";
      voiceBtn.classList.add("active");
    } catch (e) {
      say("Microphone access was not granted. Type the instruction instead.");
    }
  };
  const stopVoice = (ev) => {
    if (ev) ev.preventDefault();
    if (voiceRecorder && voiceRecorder.state === "recording") voiceRecorder.stop();
    voiceRecorder = null;
    voiceBtn.textContent = "Hold to talk";
    voiceBtn.classList.remove("active");
  };
  voiceBtn.addEventListener("pointerdown", startVoice);
  voiceBtn.addEventListener("pointerup", stopVoice);
  voiceBtn.addEventListener("pointerleave", stopVoice);
}

// The transcribe API accepts WAV uploads only, so the browser converts the
// recording (usually webm/opus) to mono 16-bit WAV at 16 kHz before upload.
function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeStr = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

async function toWav16k(blob) {
  const raw = await blob.arrayBuffer();
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  try {
    const decoded = await ctx.decodeAudioData(raw);
    const targetRate = 16000;
    const offline = new OfflineAudioContext(1, Math.floor(decoded.length * targetRate / decoded.sampleRate), targetRate);
    const src = offline.createBufferSource();
    src.buffer = decoded;
    // Multi-channel input is downmixed by connecting through one node.
    const downmix = offline.createGain();
    const splitter = offline.createChannelSplitter(decoded.numberOfChannels);
    src.connect(splitter);
    for (let c = 0; c < decoded.numberOfChannels; c++) splitter.connect(downmix, c);
    downmix.connect(offline.destination);
    src.start();
    const rendered = await offline.startRendering();
    return encodeWav(rendered.getChannelData(0), targetRate);
  } finally {
    ctx.close();
  }
}

load().then(connect);
