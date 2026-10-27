// Day 1 skeleton: render HA states, live-update ONLY from WebSocket
// state_changed events relayed by the backend. No optimistic UI.
const statusEl = document.getElementById("status");
const listEl = document.getElementById("entities");
const states = new Map();

function render() {
  listEl.innerHTML = "";
  for (const [id, st] of states) {
    const li = document.createElement("li");
    li.textContent = `${id}: ${st}`;
    listEl.appendChild(li);
  }
}

async function load() {
  const res = await fetch("/api/entities");
  const entities = await res.json();
  for (const e of entities) states.set(e.entity_id, e.state);
  render();
}

function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => { statusEl.textContent = "Live"; };
  ws.onclose = () => { statusEl.textContent = "Reconnecting…"; setTimeout(connect, 2000); };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    const st = msg?.data?.new_state;
    if (st) {
      states.set(st.entity_id, st.state);
      render();
    }
  };
}

load().then(connect);
