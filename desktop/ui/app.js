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
let feedClient = "";
let options = null;
const expanded = new Set();
const checks = {}; // результаты «Проверить поиск» по индексу клиента

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
  current: ["Уже было на Авито при запуске", "bg-slate-100 text-slate-600"],
  agent: ["Агент", "bg-red-50 text-red-700"],
  duplicate: ["Дубль", "bg-slate-100 text-slate-600"],
};

// ---------------------------------------------------------------- лента

async function loadFeed() {
  const query = $("#feed-search").value.trim();
  const client = feedClient;
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
      : "Нажмите «Запустить». Если объявления не появляются, откройте «Клиенты и поиски» и нажмите «Проверить поиск».";
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
function fillClientFilter() {
  const names = [...new Set((config?.targets_to_watch || []).map((t) => t.client_name).filter(Boolean))];
  if (feedClient && !names.includes(feedClient)) feedClient = "";
  const counts = status?.counts?.by_client || {};
  const total = status?.counts?.found_total ?? 0;
  const tab = (value, label, n) => `
    <button data-client="${esc(value)}" class="relative -mb-px flex shrink-0 items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition
      ${feedClient === value ? "border-brand text-ink" : "border-transparent text-muted hover:text-ink"}">
      ${esc(label)}${n ? `<span class="rounded-full bg-canvas px-1.5 text-[11px] tabular-nums text-muted">${n}</span>` : ""}
    </button>`;
  const html = tab("", "Все клиенты", total) + names.map((n) => tab(n, n, counts[n] || 0)).join("");
  const box = $("#client-tabs");
  if (box.dataset.html !== html) {
    box.innerHTML = html;
    box.dataset.html = html;
  }
}
$("#client-tabs").addEventListener("click", (e) => {
  const b = e.target.closest("[data-client]");
  if (!b) return;
  feedClient = b.dataset.client;
  fillClientFilter();
  loadFeed();
});

// ---------------------------------------------------------------- клиенты

const num = (v) => (v === null || v === undefined ? "" : v);
const ROOMS = [["studio", "Студия"], ["1", "1"], ["2", "2"], ["3", "3"], ["4+", "4+"]];

function optionList(list, value) {
  return list.map(([v, l]) => `<option value="${esc(v)}" ${v === value ? "selected" : ""}>${esc(l)}</option>`).join("");
}

function summary(t) {
  if (t.mode === "url") return t.avito_url ? "Своя ссылка с Авито" : "Ссылка не указана";
  const c = t.criteria;
  const city = (options.cities.find(([v]) => v === c.city) || [, c.city])[1];
  const cat = (options.categories.find(([v]) => v === c.category) || [, ""])[1];
  const deal = (options.deals.find(([v]) => v === c.deal) || [, ""])[1];
  const parts = [city, cat, deal];
  if (c.rooms?.length && c.category === "kvartiry") parts.push(c.rooms.map((r) => (r === "studio" ? "студия" : r)).join(", ") + " комн.");
  const money = (n) => (n >= 1e6 ? +(n / 1e6).toFixed(2) + " млн" : Number(n).toLocaleString("ru-RU"));
  if (c.price_min || c.price_max) parts.push([c.price_min && "от " + money(c.price_min), c.price_max && "до " + money(c.price_max)].filter(Boolean).join(" ") + " ₽");
  if (c.area_min || c.area_max) parts.push([c.area_min && "от " + c.area_min, c.area_max && "до " + c.area_max].filter(Boolean).join(" ") + " м²");
  if (c.floor_min || c.floor_max) parts.push("этаж " + [c.floor_min && "от " + c.floor_min, c.floor_max && "до " + c.floor_max].filter(Boolean).join(" "));
  if (c.districts) parts.push(c.districts);
  if (c.private_only) parts.push("только частные");
  return parts.join(" · ");
}

function rangeField(label, key, unit = "") {
  return `<label class="field"><span class="field-label">${label}${unit ? ", " + unit : ""}</span>
    <div class="flex gap-2">
      <input class="input" inputmode="numeric" placeholder="от" data-c="${key}_min" />
      <input class="input" inputmode="numeric" placeholder="до" data-c="${key}_max" />
    </div></label>`;
}

function clientCard(t, idx) {
  const open = expanded.has(idx);
  const c = t.criteria;
  const knownCity = options.cities.some(([v]) => v === c.city);
  return `
  <div class="card !p-0 ${t.enabled === false ? "opacity-60" : ""}" data-idx="${idx}">
    <div class="flex items-center gap-4 px-5 py-4">
      <input type="checkbox" class="toggle" data-k="enabled" ${t.enabled !== false ? "checked" : ""} title="Следить за этим поиском" />
      <div class="min-w-0 flex-1 cursor-pointer" data-act="toggle">
        <div class="truncate text-[15px] font-semibold">${esc(t.client_name || "Новый клиент")}</div>
        <div class="truncate text-sm text-muted">${esc(summary(t))}</div>
      </div>
      <button class="btn-secondary !py-1.5" data-act="check" title="Загрузить выдачу Авито и показать, что подходит">Проверить поиск</button>
      <button class="btn-secondary !py-1.5" data-act="toggle">${open ? "Свернуть" : "Изменить"}</button>
      <button class="icon-btn" data-act="open" title="Открыть поиск на Авито"><svg viewBox="0 0 24 24" class="size-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/></svg></button>
      <button class="icon-btn hover:!bg-red-50 hover:!text-red-600" data-act="del" title="Удалить"><svg viewBox="0 0 24 24" class="size-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg></button>
    </div>
    ${checkPanel(idx)}
    ${open ? `
    <div class="grid gap-5 border-t border-line px-5 py-5">
      <div class="flex flex-wrap items-end gap-4">
        <label class="field w-72"><span class="field-label">Клиент</span><input class="input" data-k="client_name" placeholder="Иван, 1к до 12 млн" /></label>
        <div class="field"><span class="field-label">Как искать</span>
          <div class="seg">
            <button data-mode="criteria" class="seg-item ${t.mode !== "url" ? "active" : ""}">По критериям</button>
            <button data-mode="url" class="seg-item ${t.mode === "url" ? "active" : ""}">Своя ссылка</button>
          </div>
        </div>
      </div>
      ${t.mode === "url" ? `
      <label class="field"><span class="field-label">Ссылка поиска на Авито</span>
        <input class="input font-mono text-[12.5px]" data-k="avito_url" placeholder="https://www.avito.ru/moskva/kvartiry/prodam/..." />
        <span class="field-hint">Настройте фильтры на сайте Авито и скопируйте адрес страницы со списком объявлений.</span></label>` : `
      <div class="grid grid-cols-4 gap-4">
        <label class="field"><span class="field-label">Город</span>
          <select class="input" data-c="city_select">${optionList(options.cities, knownCity ? c.city : "__other")}<option value="__other" ${knownCity ? "" : "selected"}>Другой…</option></select></label>
        <label class="field ${knownCity ? "hidden" : ""}" data-other-city><span class="field-label">Город как в адресе Авито</span>
          <input class="input font-mono text-[13px]" data-c="city" placeholder="например, kaspiysk" /></label>
        <label class="field"><span class="field-label">Что ищем</span><select class="input" data-c="category">${optionList(options.categories, c.category)}</select></label>
        <label class="field"><span class="field-label">Сделка</span><select class="input" data-c="deal">${optionList(options.deals, c.deal)}</select></label>
      </div>
      ${c.category === "kvartiry" ? `
      <div class="field"><span class="field-label">Комнаты</span>
        <div class="flex gap-2">${ROOMS.map(([v, l]) => `<button data-room="${v}" class="rounded-xl border px-4 py-2 text-sm font-medium transition ${c.rooms.includes(v) ? "border-brand bg-brand-50 text-brand" : "border-line bg-white text-muted hover:text-ink"}">${l}</button>`).join("")}
        <span class="self-center text-xs text-muted">${c.rooms.length ? "" : "любое количество"}</span></div></div>` : ""}
      <div class="grid grid-cols-4 gap-4">
        ${rangeField("Цена", "price", "₽")}
        ${rangeField("Площадь", "area", "м²")}
        ${rangeField("Этаж", "floor")}
        ${rangeField("Этажей в доме", "floors_total")}
      </div>
      <div class="flex flex-wrap gap-6">
        <label class="toggle-row"><input type="checkbox" class="toggle" data-c="not_first_floor" /><span class="pt-0.5">Не первый этаж</span></label>
        <label class="toggle-row"><input type="checkbox" class="toggle" data-c="not_last_floor" /><span class="pt-0.5">Не последний этаж</span></label>
        <label class="toggle-row"><input type="checkbox" class="toggle" data-c="private_only" /><span class="pt-0.5">Только частные лица на Авито</span></label>
      </div>
      <div class="grid grid-cols-2 gap-4">
        <label class="field"><span class="field-label">Район, метро или улица</span>
          <input class="input" data-c="districts" placeholder="Хамовники, Фрунзенская, Пироговская" />
          <span class="field-hint">Через запятую. Подойдёт объявление, где в адресе есть любое из слов. Пусто — весь город.</span></label>
        <label class="field"><span class="field-label">Исключить, если в тексте есть</span>
          <input class="input" data-c="exclude_words" placeholder="доля, аукцион, апартаменты" />
          <span class="field-hint">Через запятую. Проверяются заголовок, адрес и описание.</span></label>
      </div>`}
    </div>` : ""}
  </div>`;
}

function checkPanel(idx) {
  const r = checks[idx];
  if (!r) return "";
  if (r.loading) return `<div class="border-t border-line px-5 py-4 text-sm text-muted">Загружаю выдачу Авито… Это может занять до минуты.</div>`;
  if (!r.ok) return `<div class="border-t border-line bg-red-50 px-5 py-4 text-sm text-red-700">Не получилось: ${esc(r.error)}</div>`;
  const reasons = Object.entries(r.reasons || {}).sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `<span class="badge bg-slate-100 text-slate-600">${esc(k)}: ${v}</span>`).join(" ");
  const verdict = r.total === 0
    ? `<b class="text-red-700">Авито вернул страницу без объявлений.</b> В папке программы сохранён файл <code>debug_last_page.html</code>, пришлите его разработчику.`
    : r.matched === 0
      ? `<b class="text-amber-700">На странице ${r.total} объявлений, но ни одно не подошло под критерии.</b> Ослабьте фильтры.`
      : `<b class="text-brand">Работает: на странице ${r.total} объявлений, под критерии подходит ${r.matched}.</b>`;
  return `<div class="border-t border-line px-5 py-4 text-sm">
    <div class="flex items-start justify-between gap-4"><div>${verdict}</div>
      <button class="text-xs text-muted hover:text-ink" data-act="check-close">Скрыть</button></div>
    ${reasons ? `<div class="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted">Отсеяно: ${reasons}</div>` : ""}
    ${r.samples?.length ? `<div class="mt-3 grid gap-1">${r.samples.map((x) => `
      <div class="flex items-center gap-2 truncate">
        <span class="${x.ok ? "text-brand" : "text-slate-400"}">${x.ok ? "✓" : "✕"}</span>
        <span class="truncate ${x.ok ? "" : "text-muted"}">${esc(x.title)}</span>
        <span class="shrink-0 tabular-nums text-muted">${esc(x.price)}</span>
        ${x.ok ? "" : `<span class="shrink-0 text-xs text-slate-400">(${esc(x.reason)})</span>`}
      </div>`).join("")}</div>` : ""}
    <div class="mt-3 truncate text-xs text-muted">Запрос (${esc(r.via || "")}): ${esc(r.url || "")}</div>
  </div>`;
}

function fillCard(card, t) {
  $$("[data-k]", card).forEach((el) => {
    if (el.type === "checkbox") return;
    el.value = t[el.dataset.k] ?? "";
  });
  $$("[data-c]", card).forEach((el) => {
    const k = el.dataset.c;
    if (k === "city_select" || k === "category" || k === "deal") return;
    if (el.type === "checkbox") el.checked = !!t.criteria[k];
    else el.value = num(t.criteria[k]);
  });
}

function renderClients() {
  const list = $("#clients-list");
  const targets = config.targets_to_watch;
  $("#clients-empty").classList.toggle("hidden", targets.length > 0);
  list.innerHTML = targets.map(clientCard).join("");
  $$("[data-idx]", list).forEach((card) => fillCard(card, targets[+card.dataset.idx]));
}

$("#clients-list").addEventListener("input", (e) => {
  const card = e.target.closest("[data-idx]");
  if (!card) return;
  const t = config.targets_to_watch[+card.dataset.idx];
  const el = e.target;
  if (el.dataset.k) {
    t[el.dataset.k] = el.type === "checkbox" ? el.checked : el.value;
    if (el.dataset.k === "enabled") card.classList.toggle("opacity-60", !el.checked);
    if (el.dataset.k === "client_name") $(".text-\\[15px\\]", card).textContent = el.value || "Новый клиент";
  } else if (el.dataset.c) {
    const k = el.dataset.c;
    if (k === "city_select") {
      const other = el.value === "__other";
      $("[data-other-city]", card).classList.toggle("hidden", !other);
      t.criteria.city = other ? "" : el.value;
      if (other) $("[data-c=city]", card).focus();
    } else if (el.type === "checkbox") t.criteria[k] = el.checked;
    else if (/_(min|max)$/.test(k)) {
      el.value = el.value.replace(/[^\d.,]/g, "");
      t.criteria[k] = el.value === "" ? null : Number(el.value.replace(",", "."));
    } else t.criteria[k] = el.value;
    if (k === "category") return rerenderCard(card);
  }
  const sum = $(".text-sm.text-muted.truncate", card);
  if (sum) sum.textContent = summary(t);
  markDirty();
});

function rerenderCard(card, changed = true) {
  const idx = +card.dataset.idx;
  const fresh = document.createElement("div");
  fresh.innerHTML = clientCard(config.targets_to_watch[idx], idx);
  const el = fresh.firstElementChild;
  card.replaceWith(el);
  fillCard(el, config.targets_to_watch[idx]);
  if (changed) markDirty();
}

$("#clients-list").addEventListener("click", async (e) => {
  const card = e.target.closest("[data-idx]");
  if (!card) return;
  const idx = +card.dataset.idx;
  const t = config.targets_to_watch[idx];
  const act = e.target.closest("[data-act]")?.dataset.act;
  const mode = e.target.closest("[data-mode]")?.dataset.mode;
  const room = e.target.closest("[data-room]")?.dataset.room;
  if (act === "check") {
    checks[idx] = { loading: true };
    rerenderCard(card, false);
    const r = await api.test_search(t);
    checks[idx] = r;
    const fresh = $(`#clients-list [data-idx="${idx}"]`);
    if (fresh) rerenderCard(fresh, false);
  } else if (act === "check-close") {
    delete checks[idx];
    rerenderCard(card, false);
  } else if (act === "toggle") {
    expanded.has(idx) ? expanded.delete(idx) : expanded.add(idx);
    rerenderCard(card, false);
  } else if (act === "del") {
    if (!confirm(`Удалить поиск «${t.client_name || "без имени"}»?`)) return;
    config.targets_to_watch.splice(idx, 1);
    expanded.clear();
    renderClients();
    markDirty();
  } else if (act === "open") {
    const url = t.mode === "url" ? t.avito_url : await api.build_url(t.criteria);
    api.open_url(url && url.startsWith("http") ? url : "https://www.avito.ru/");
  } else if (mode) {
    t.mode = mode;
    rerenderCard(card);
  } else if (room) {
    const set = new Set(t.criteria.rooms);
    set.has(room) ? set.delete(room) : set.add(room);
    t.criteria.rooms = ROOMS.map(([v]) => v).filter((v) => set.has(v));
    rerenderCard(card);
  }
});

$("#add-client").addEventListener("click", () => {
  const last = config.targets_to_watch.at(-1);
  const city = last?.criteria?.city || options.defaults.city;
  config.targets_to_watch.push({
    client_name: "", avito_url: "", enabled: true, mode: "criteria",
    criteria: { ...structuredClone(options.defaults), city },
  });
  expanded.add(config.targets_to_watch.length - 1);
  renderClients();
  markDirty();
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
  ["#s-browser", "browser_mode", "check"],
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

$("#show-browser").addEventListener("click", async () => {
  const r = await api.show_browser();
  if (!r.ok) toast(r.error, "err");
});

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
  fillClientFilter();
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
  dot.className = "relative flex size-2.5 " + (running ? (["blocked", "captcha"].includes(status.phase) ? "warn" : "on") : "");

  let title = "Остановлено";
  let sub = "Нажмите «Запустить», чтобы начать следить за новыми объявлениями.";
  if (running) {
    const left = status.next_check_at ? status.next_check_at - Date.now() / 1000 : null;
    if (status.phase === "checking") {
      title = "Проверяю";
      sub = `Ищу новые объекты для «${status.client || "…"}»`;
    } else if (status.phase === "captcha") {
      title = "Нужна проверка Авито";
      sub = "Пройдите проверку «я не робот» в открывшемся окне Авито, и поиск продолжится сам.";
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
  options = await api.get_options();
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
