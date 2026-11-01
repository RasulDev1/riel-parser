"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

let api = null;
let config = null;
let dirty = false;
let lastLogId = 0;
let feedStatus = "found";
let lastFeedKey = "";
let knownIds = new Set();
let firstFeedLoad = true;

// ---------------------------------------------------------------- навигация

function showTab(tab) {
  $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$("[data-panel]").forEach((p) => p.classList.toggle("hidden", p.dataset.panel !== tab));
  if (tab === "log") scrollLog();
  try { localStorage.setItem("tab", tab); } catch (_) {}
}

$$(".nav-item").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

// ---------------------------------------------------------------- уведомления

let toastTimer;
function toast(text, kind = "ok") {
  const t = $("#toast");
  t.textContent = text;
  t.className = t.className.replace(/bg-\S+/g, "") + (kind === "ok" ? " bg-ink" : " bg-red-600");
  t.classList.remove("opacity-0", "translate-y-4");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("opacity-0", "translate-y-4"), 2800);
}

// ---------------------------------------------------------------- форматирование

const fmtPrice = (n, text) => text || (n ? n.toLocaleString("ru-RU") + " ₽" : "Цена не указана");

function timeAgo(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "только что";
  if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
  const d = new Date(ts * 1000);
  const today = new Date();
  const hm = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return `сегодня в ${hm}`;
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" }) + ` в ${hm}`;
}

function fmtCountdown(sec) {
  sec = Math.max(0, Math.round(sec));
  if (sec >= 60) return `${Math.floor(sec / 60)} мин ${sec % 60} с`;
  return `${sec} с`;
}

const STATUS = {
  sent: ["Отправлено в Telegram", "bg-brand-50 text-brand"],
  dry_run: ["Новый объект", "bg-brand-50 text-brand"],
  agent: ["Агент", "bg-red-50 text-red-700"],
  duplicate: ["Дубль", "bg-slate-100 text-slate-600"],
};

// ---------------------------------------------------------------- лента

async function loadFeed() {
  const query = $("#feed-search").value.trim();
  const client = $("#feed-client").value;
  let items = await api.listings(feedStatus, query, 300);
  if (client) items = items.filter((i) => i.client === client);

  const key = feedStatus + "|" + query + "|" + client + "|" + items.map((i) => i.id + i.client + i.status).join(",");
  if (key === lastFeedKey) return;
  lastFeedKey = key;

  const list = $("#feed-list");
  $("#feed-empty").classList.toggle("hidden", items.length > 0);
  if (!items.length) {
    const filtered = query || client || feedStatus !== "found";
    $("#feed-empty-title").textContent = filtered ? "Ничего не найдено" : "Пока ничего нового";
    $("#feed-empty-text").textContent = filtered
      ? "Попробуйте изменить фильтр или поиск."
      : "При первом запуске программа запоминает текущие объявления, а сюда попадут только те, что появятся после.";
  }

  list.innerHTML = items
    .map((i) => {
      const [label, cls] = STATUS[i.status] || [i.status, "bg-slate-100 text-slate-600"];
      const isNew = !firstFeedLoad && !knownIds.has(i.id + "|" + i.client);
      const desc = (i.description || "").slice(0, 220);
      return `
      <article class="listing ${isNew ? "fade-in ring-2 ring-brand/30" : ""}">
        <div class="min-w-0">
          <div class="mb-2 flex flex-wrap items-center gap-2">
            <span class="badge bg-ink text-white">${esc(i.client)}</span>
            <span class="badge ${cls}">${esc(label)}</span>
            <span class="text-xs text-muted">${esc(timeAgo(i.created_at))}</span>
          </div>
          <h3 class="truncate text-[15px] font-semibold">${esc(i.title)}</h3>
          ${i.address ? `<div class="mt-1 flex items-center gap-1.5 text-sm text-muted">
            <svg viewBox="0 0 24 24" class="size-3.5 shrink-0" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>
            <span class="truncate">${esc(i.address)}</span></div>` : ""}
          ${desc ? `<p class="mt-2 line-clamp-2 text-sm text-slate-600">${esc(desc)}${i.description.length > 220 ? "…" : ""}</p>` : ""}
          ${i.seller || i.reason ? `<div class="mt-2 text-xs text-muted">${i.seller ? "👤 " + esc(i.seller) : ""}${i.seller && i.reason ? " · " : ""}${i.reason ? esc(i.reason) : ""}</div>` : ""}
        </div>
        <div class="flex flex-col items-end justify-between gap-3">
          <div class="whitespace-nowrap text-lg font-semibold tabular-nums">${esc(fmtPrice(i.price, i.price_text))}</div>
          <button class="btn-secondary !py-1.5" data-open="${esc(i.url)}">
            Открыть на Авито
            <svg viewBox="0 0 24 24" class="size-3.5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17 17 7M8 7h9v9"/></svg>
          </button>
        </div>
      </article>`;
    })
    .join("");

  items.forEach((i) => knownIds.add(i.id + "|" + i.client));
  firstFeedLoad = false;
}

$("#feed-list").addEventListener("click", (e) => {
  const b = e.target.closest("[data-open]");
  if (b) api.open_url(b.dataset.open);
});
$$("#feed-filter .seg-item").forEach((b) =>
  b.addEventListener("click", () => {
    $$("#feed-filter .seg-item").forEach((x) => x.classList.toggle("active", x === b));
    feedStatus = b.dataset.status;
    loadFeed();
  }),
);
let searchTimer;
$("#feed-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadFeed, 200);
});
$("#feed-client").addEventListener("change", loadFeed);

function fillClientFilter() {
  const sel = $("#feed-client");
  const cur = sel.value;
  const names = [...new Set((config?.targets_to_watch || []).map((t) => t.client_name))];
  sel.innerHTML = `<option value="">Все клиенты</option>` + names.map((n) => `<option>${esc(n)}</option>`).join("");
  if (names.includes(cur)) sel.value = cur;
}

// ---------------------------------------------------------------- клиенты

function renderClients() {
  const list = $("#clients-list");
  list.innerHTML = "";
  const targets = config.targets_to_watch;
  $("#clients-empty").classList.toggle("hidden", targets.length > 0);
  targets.forEach((t, idx) => {
    const row = $("#client-row").content.firstElementChild.cloneNode(true);
    $("[data-k=enabled]", row).checked = t.enabled !== false;
    $("[data-k=client_name]", row).value = t.client_name || "";
    $("[data-k=avito_url]", row).value = t.avito_url || "";
    row.addEventListener("input", (e) => {
      const k = e.target.dataset.k;
      if (!k) return;
      t[k] = e.target.type === "checkbox" ? e.target.checked : e.target.value;
      markDirty();
    });
    $("[data-act=del]", row).addEventListener("click", () => {
      targets.splice(idx, 1);
      renderClients();
      markDirty();
    });
    $("[data-act=open]", row).addEventListener("click", () => {
      const url = $("[data-k=avito_url]", row).value.trim();
      api.open_url(url.startsWith("http") ? url : "https://www.avito.ru/");
    });
    list.appendChild(row);
  });
}

$("#add-client").addEventListener("click", () => {
  config.targets_to_watch.push({ client_name: "", avito_url: "", enabled: true });
  renderClients();
  const rows = $$("#clients-list [data-k=client_name]");
  rows[rows.length - 1]?.focus();
});

// ---------------------------------------------------------------- настройки

const bind = [
  ["#s-token", "telegram_bot_token"],
  ["#s-chat", "rieltor_chat_id"],
  ["#s-interval", "global_check_interval_seconds", Number],
  ["#s-jitter", "jitter_seconds", Number],
  ["#s-first", "notify_on_first_run", "check"],
  ["#s-cookies", "avito_cookies"],
  ["#s-aa", "anti_agent.enabled", "check"],
  ["#s-aa-active", "anti_agent.max_active_listings", Number],
  ["#s-aa-closed", "anti_agent.max_closed_listings", Number],
  ["#s-aa-unknown", "anti_agent.skip_if_unknown", "check"],
];

const getPath = (o, p) => p.split(".").reduce((a, k) => a?.[k], o);
function setPath(o, p, v) {
  const ks = p.split(".");
  const last = ks.pop();
  ks.reduce((a, k) => (a[k] ??= {}), o)[last] = v;
}

function renderSettings() {
  for (const [sel, path, kind] of bind) {
    const el = $(sel);
    const v = getPath(config, path);
    if (kind === "check") el.checked = !!v;
    else el.value = v ?? "";
  }
  syncAa();
}

function syncAa() {
  $("#aa-fields").classList.toggle("opacity-40", !$("#s-aa").checked);
}

for (const [sel, path, kind] of bind) {
  $(sel).addEventListener("input", (e) => {
    const el = e.target;
    setPath(config, path, kind === "check" ? el.checked : kind === Number ? (el.value === "" ? "" : Number(el.value)) : el.value);
    if (sel === "#s-aa") syncAa();
    markDirty();
  });
}

$("#test-tg").addEventListener("click", async () => {
  const out = $("#test-tg-result");
  out.className = "text-sm text-muted";
  out.textContent = "Отправляю…";
  const r = await api.test_telegram($("#s-token").value, $("#s-chat").value);
  out.className = "text-sm " + (r.ok ? "text-brand" : "text-red-600");
  out.textContent = r.ok ? "✓ Сообщение отправлено, проверьте Telegram" : "Не получилось: " + r.error;
});

// ---------------------------------------------------------------- сохранение

function markDirty() {
  dirty = true;
  $$("[data-save]").forEach((b) => (b.textContent = "Сохранить изменения"));
}

async function save() {
  const r = await api.save_config(config);
  if (!r.ok) return toast(r.error, "err");
  config = r.config;
  dirty = false;
  $$("[data-save]").forEach((b) => (b.textContent = "Сохранить"));
  renderClients();
  fillClientFilter();
  toast(r.restarted ? "Сохранено, мониторинг перезапущен" : "Сохранено");
}
$$("[data-save]").forEach((b) => b.addEventListener("click", save));
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
    e.preventDefault();
    save();
  }
});

// ---------------------------------------------------------------- запуск/стоп и статус

$("#toggle-btn").addEventListener("click", async () => {
  const btn = $("#toggle-btn");
  btn.disabled = true;
  try {
    if (btn.dataset.running === "1") {
      await api.stop();
    } else {
      if (dirty) await save();
      const r = await api.start();
      if (!r.ok) {
        toast(r.error, "err");
        if (/ссылк/i.test(r.error)) showTab("clients");
      }
    }
    await refreshStatus();
  } finally {
    btn.disabled = false;
  }
});

let status = null;
async function refreshStatus() {
  status = await api.status();
  renderStatus();
  const c = status.counts;
  $("#c-today").textContent = c.found_today;
  $("#c-total").textContent = c.found_total;
  $("#c-agents").textContent = c.agents;
  $("#c-dups").textContent = c.duplicates;
  const badge = $("#nav-feed-badge");
  badge.textContent = c.found_today;
  badge.classList.toggle("hidden", !c.found_today);

  const banner = $("#banner");
  if (status.running && status.dry_run) {
    banner.innerHTML = 'Telegram не настроен: новые объекты появляются только в ленте. <button class="font-semibold underline" id="go-settings">Настроить</button>';
    banner.classList.remove("hidden");
    $("#go-settings").onclick = () => showTab("settings");
  } else banner.classList.add("hidden");
}

function renderStatus() {
  if (!status) return;
  const dot = $("#status-dot");
  const btn = $("#toggle-btn");
  const running = status.running;
  btn.dataset.running = running ? "1" : "0";
  $("#toggle-label").textContent = running ? "Остановить" : "Запустить";
  btn.classList.toggle("danger", running);
  dot.className = "relative flex size-2.5 " + (running ? (status.phase === "blocked" ? "warn" : "on") : "");

  let title = "Остановлено";
  let sub = "Нажмите «Запустить», чтобы начать следить за новыми объявлениями.";
  if (running) {
    const left = status.next_check_at ? status.next_check_at - Date.now() / 1000 : null;
    if (status.phase === "checking") {
      title = "Проверяю";
      sub = `Ищу новые объекты для «${status.client || "…"}»`;
    } else if (status.phase === "blocked") {
      title = "Пауза: Авито ограничил доступ";
      sub = left != null ? `Продолжу через ${fmtCountdown(left)}. Откройте Авито в браузере и пройдите капчу.` : "";
    } else if (status.phase === "waiting") {
      title = "Работает";
      sub = left != null ? `Следующая проверка через ${fmtCountdown(left)}` : "Ожидание…";
    } else {
      title = "Запускаю…";
      sub = "";
    }
  }
  $("#status-title").textContent = title;
  $("#status-sub").textContent = sub;
}

// ---------------------------------------------------------------- журнал

function scrollLog() {
  const box = $("#log-box");
  box.scrollTop = box.scrollHeight;
}

async function loadLogs() {
  const items = await api.logs(lastLogId);
  if (!items.length) return;
  const box = $("#log-box");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  const frag = document.createDocumentFragment();
  for (const r of items) {
    const div = document.createElement("div");
    div.className = "log-line log-" + r.level;
    div.innerHTML = `<span class="text-slate-500">${esc(r.time)}</span>  ${esc(r.msg)}`;
    frag.appendChild(div);
    lastLogId = r.id;
  }
  box.appendChild(frag);
  while (box.childElementCount > 1500) box.firstElementChild.remove();
  if (atBottom) scrollLog();
}
$("#log-clear").addEventListener("click", () => ($("#log-box").innerHTML = ""));

// ---------------------------------------------------------------- старт

async function init() {
  api = window.pywebview.api;
  config = await api.get_config();
  config.targets_to_watch ??= [];
  renderClients();
  renderSettings();
  fillClientFilter();
  let tab = "feed";
  try { tab = localStorage.getItem("tab") || "feed"; } catch (_) {}
  showTab(config.targets_to_watch.length ? tab : "clients");

  await Promise.all([refreshStatus(), loadFeed(), loadLogs()]);
  setInterval(refreshStatus, 1500);
  setInterval(loadFeed, 3000);
  setInterval(loadLogs, 1000);
  setInterval(renderStatus, 1000);
}

if (window.pywebview?.api) init();
else window.addEventListener("pywebviewready", init);
