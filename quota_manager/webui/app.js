(() => {
  "use strict";

  const tokenMeta = document.querySelector('meta[name="quota-token"]');
  const token = tokenMeta ? tokenMeta.content : "";
  const POLL_MS = 20000;
  const MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
  const ACCENTS = { claude: "#FFA17D", codex: "#6CF5D5", zcode: "#A895FF" };

  const cardsEl = document.getElementById("cards");
  const emptyEl = document.getElementById("empty");
  const emptyTitleEl = document.getElementById("empty-title");
  const emptyTextEl = document.getElementById("empty-text");
  const emptyCommandEl = document.getElementById("empty-command");
  const subtitleEl = document.getElementById("subtitle");
  const syncPill = document.getElementById("sync-pill");
  const syncLabel = document.getElementById("sync-label");
  const refreshButton = document.getElementById("refresh");
  const refreshLabel = document.getElementById("refresh-label");
  const settingsButton = document.getElementById("settings");
  const toastEl = document.getElementById("toast");

  let snapshot = null;
  let refreshing = false;
  let settingsBusy = false;
  let loading = false;
  let lastError = "";
  let lastErrorToast = "";
  let renderCount = 0;
  let toastTimer = 0;

  function providers() {
    return snapshot && Array.isArray(snapshot.providers) ? snapshot.providers : [];
  }

  function asNumber(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function clamp(value, low = 0, high = 100) {
    return Math.max(low, Math.min(high, value));
  }

  function pad2(value) {
    return value < 10 ? "0" + value : String(value);
  }

  function accentFor(providerId) {
    return ACCENTS[providerId] || "#93B7C2";
  }

  function formatDuration(seconds) {
    const value = Math.max(0, Math.round(asNumber(seconds)));
    const days = Math.floor(value / 86400);
    const hours = Math.floor((value % 86400) / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    if (days > 0) return days + " д " + hours + " ч";
    if (hours > 0) return hours + " ч " + minutes + " мин";
    return Math.max(1, minutes) + " мин";
  }

  function resetLabel(timestamp) {
    const value = asNumber(timestamp);
    if (!Number.isFinite(value) || value <= 0) return "без сброса";
    const seconds = value - Date.now() / 1000;
    if (seconds <= 0) return "обновляется";
    if (seconds > 604800) {
      const date = new Date(value * 1000);
      return "сброс " + date.getDate() + " " + MONTHS[date.getMonth()];
    }
    return "сброс через " + formatDuration(seconds);
  }

  function formatTokens(value) {
    const number = asNumber(value, NaN);
    if (!Number.isFinite(number)) return "—";
    if (number >= 1e9) return (number / 1e9).toFixed(2).replace(".", ",") + "B";
    if (number >= 1e6) {
      const millions = number / 1e6;
      return (millions >= 100 ? String(Math.round(millions)) : millions.toFixed(2)).replace(".", ",") + "M";
    }
    if (number >= 1e3) return Math.round(number / 1e3) + "K";
    return String(Math.round(number));
  }

  function minimumRemaining(provider) {
    const windows = provider && Array.isArray(provider.windows) ? provider.windows : [];
    if (!windows.length) return null;
    const bestByGroup = new Map();
    for (const windowData of windows) {
      const value = asNumber(windowData.remaining_percent, NaN);
      if (!Number.isFinite(value)) continue;
      const key = String(windowData.title || windowData.id || "");
      if (!bestByGroup.has(key) || value > bestByGroup.get(key)) {
        bestByGroup.set(key, value);
      }
    }
    if (!bestByGroup.size) return null;
    return Math.min(...bestByGroup.values());
  }

  function stateColor(label) {
    if (label === "LIVE") return "#79F7E4";
    if (label === "LOW") return "#FFC15E";
    if (label === "LIMIT" || label === "AUTH" || label === "ERROR") return "#FF6D83";
    return "#91A8B1";
  }

  function providerState(provider) {
    if (!provider) return "ERROR";
    if (provider.status !== "ok") {
      const error = String(provider.error || "").toLowerCase();
      if (error.includes("auth") || error.includes("сесси") || error.includes("oauth") || error.includes("войдите")) {
        return "AUTH";
      }
      if (error.includes("времен") || error.includes("огранич")) return "PAUSED";
      return "ERROR";
    }
    const minimum = minimumRemaining(provider);
    if (minimum === null) return "EMPTY";
    if (minimum <= 0.5) return "LIMIT";
    if (minimum <= 15) return "LOW";
    return "LIVE";
  }

  function providerSecondary(provider) {
    if (!provider) return { text: "", error: false };
    if (provider.status !== "ok" && provider.error) {
      return { text: String(provider.error), error: true };
    }
    const parts = [];
    if (provider.account) parts.push(String(provider.account));
    if (provider.note) parts.push(String(provider.note));
    return { text: parts.join(" · "), error: false };
  }

  function sourceWord(count) {
    const mod10 = count % 10;
    const mod100 = count % 100;
    if (mod10 === 1 && mod100 !== 11) return "источник";
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "источника";
    return "источников";
  }

  function lastUpdatedLabel() {
    if (!snapshot || !snapshot.generated_at) return "ожидание данных";
    const date = new Date(asNumber(snapshot.generated_at) * 1000);
    return "обновлено " + pad2(date.getHours()) + ":" + pad2(date.getMinutes());
  }

  function subtitleText() {
    const list = providers();
    if (!list.length) {
      return lastError ? "локальный сервис недоступен" : "нет активных сессий";
    }
    return list.length + " " + sourceWord(list.length) + "  ·  " + lastUpdatedLabel();
  }

  function syncLabelText() {
    if (refreshing || (snapshot && snapshot.refreshing)) return "SYNC";
    if (lastError) return "OFFLINE";
    if (!snapshot || !snapshot.generated_at) return "IDLE";
    const interval = asNumber(snapshot.interval_seconds, 300);
    if (Date.now() / 1000 - asNumber(snapshot.generated_at) > Math.max(interval * 3, 900)) {
      return "STALE";
    }
    if (providers().some((provider) => !provider || provider.status !== "ok")) return "DEGRADED";
    return "LIVE";
  }

  function syncTone(label) {
    if (label === "LIVE") return "#79F7E4";
    if (label === "SYNC") return "#8BD9FF";
    if (label === "DEGRADED" || label === "STALE") return "#FFC15E";
    if (label === "OFFLINE") return "#FF6D83";
    return "#607780";
  }

  function labelText(windowData) {
    if (!windowData) return "";
    if (windowData.period === "rolling_5h") return "5-часовой лимит";
    if (windowData.period === "weekly") return "Недельный лимит";
    let text = windowData.title || "Лимит";
    if (windowData.period === "daily") text += " · день";
    else if (windowData.period === "one_time") text += " · бонус";
    return text;
  }

  function tokenValueText(windowData) {
    if (!windowData || windowData.unit !== "token") return "";
    const used = asNumber(windowData.used_value, NaN);
    const limit = asNumber(windowData.limit_value, NaN);
    if (!Number.isFinite(used) || !Number.isFinite(limit)) return "";
    return formatTokens(used) + " / " + formatTokens(limit);
  }

  function remainingPercent(windowData) {
    const value = asNumber(windowData && windowData.remaining_percent, NaN);
    if (Number.isFinite(value)) return clamp(value);
    return clamp(100 - asNumber(windowData && windowData.used_percent));
  }

  function usedPercent(windowData) {
    const value = asNumber(windowData && windowData.used_percent, NaN);
    if (Number.isFinite(value)) return clamp(value);
    return clamp(100 - remainingPercent(windowData));
  }

  function remainingText(windowData) {
    if (windowData && windowData.unit === "token") {
      return "осталось " + formatTokens(windowData.remaining_value);
    }
    return "осталось " + Math.round(remainingPercent(windowData)) + "%";
  }

  function resetText(windowData) {
    let value = resetLabel(windowData && windowData.resets_at);
    if (windowData && windowData.period === "one_time") {
      value = value.replace("сброс", "истекает");
    }
    return value;
  }

  function remainingTone(windowData) {
    const remaining = remainingPercent(windowData);
    if (remaining <= 0.5) return " limit";
    if (remaining <= 15) return " low";
    return "";
  }

  function element(tag, className, textValue) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (textValue !== undefined && textValue !== null) node.textContent = String(textValue);
    return node;
  }

  function buildRow(windowData) {
    const row = element("div", "limit-row");
    const head = element("div", "row-head");
    head.append(element("span", "row-label", labelText(windowData)));
    const right = element("div", "row-right");
    const tokenText = tokenValueText(windowData);
    if (tokenText) right.append(element("span", "token-count", tokenText));
    right.append(element("span", "percent", Math.round(usedPercent(windowData)) + "%"));
    head.append(right);
    row.append(head);

    const track = element("div", "track");
    const fill = element("div", "track-fill");
    const width = Math.round(usedPercent(windowData) * 10) / 10;
    fill.dataset.width = String(width);
    track.append(fill);
    row.append(track);

    const meta = element("div", "row-meta");
    meta.append(element("span", "remaining" + remainingTone(windowData), remainingText(windowData)));
    meta.append(element("span", "reset", resetText(windowData)));
    row.append(meta);
    return { row, fill };
  }

  function buildCard(provider) {
    const card = element("article", "card");
    const accent = accentFor(provider && provider.id);
    const state = providerState(provider);
    card.style.setProperty("--accent", accent);
    card.style.setProperty("--state", stateColor(state));

    const head = element("div", "card-head");
    const iconTile = element("div", "icon-tile");
    iconTile.dataset.provider = provider && provider.id ? String(provider.id) : "";
    const icon = element("img");
    const knownIcon = provider && ["claude", "codex", "zcode"].includes(provider.id);
    icon.src = knownIcon ? "/assets/icons/" + provider.id + ".png" : "/assets/quota-grid-mark.svg";
    icon.alt = "";
    iconTile.append(icon);

    const info = element("div", "provider-info");
    info.append(element("div", "provider-name", (provider && (provider.name || provider.id)) || "Провайдер"));
    const secondary = providerSecondary(provider);
    const meta = element("div", "provider-meta" + (secondary.error ? " error" : ""));
    meta.textContent = secondary.text;
    if (secondary.text) meta.title = secondary.text;
    info.append(meta);

    const stateEl = element("div", "provider-state");
    const dot = element("span", "state-dot");
    dot.setAttribute("aria-hidden", "true");
    stateEl.append(dot, element("span", "", state));
    head.append(iconTile, info, stateEl);
    card.append(head);

    const windows = provider && Array.isArray(provider.windows) ? provider.windows.slice(0, 4) : [];
    const fills = [];
    if (windows.length) {
      const rows = element("div", "rows");
      for (const windowData of windows) {
        const built = buildRow(windowData);
        rows.append(built.row);
        fills.push(built.fill);
      }
      card.append(rows);
    } else if (secondary.error) {
      card.append(element("div", "error-note", secondary.text || "Источник недоступен."));
    } else {
      card.append(element("div", "hint-note", "Нет активных окон лимита"));
    }
    return { card, fills };
  }

  function updateEmpty() {
    if (!snapshot && !lastError) {
      emptyTitleEl.textContent = "Загрузка…";
      emptyTextEl.textContent = "Читаю локальные сессии Claude Code, Codex и ZCode.";
      emptyCommandEl.hidden = true;
      return;
    }
    if (lastError && !snapshot) {
      emptyTitleEl.textContent = "Сервис недоступен";
      emptyTextEl.textContent = lastError;
      emptyCommandEl.hidden = true;
      return;
    }
    emptyTitleEl.textContent = "Нет активных сессий";
    emptyTextEl.textContent = "Авторизуйте Codex, Claude Code или ZCode и обновите данные.";
    emptyCommandEl.hidden = false;
  }

  function updateButtons() {
    const busy = refreshing || !!(snapshot && snapshot.refreshing);
    refreshButton.disabled = busy;
    refreshButton.classList.toggle("spinning", busy);
    refreshLabel.textContent = busy ? "Обновление…" : "Обновить";
    settingsButton.disabled = settingsBusy;
  }

  function render() {
    const list = providers();
    const label = syncLabelText();
    subtitleEl.textContent = subtitleText();
    syncLabel.textContent = label;
    syncPill.style.setProperty("--sync", syncTone(label));
    syncPill.setAttribute("aria-label", "Состояние: " + label);

    cardsEl.replaceChildren();
    emptyEl.hidden = list.length > 0;
    if (!list.length) {
      updateEmpty();
      updateButtons();
      renderCount += 1;
      return;
    }

    const animate = renderCount === 0;
    cardsEl.classList.toggle("no-motion", !animate);
    const fills = [];
    for (const provider of list) {
      const built = buildCard(provider);
      cardsEl.append(built.card);
      fills.push(...built.fills);
    }

    requestAnimationFrame(() => {
      for (const fill of fills) {
        fill.style.width = fill.dataset.width + "%";
      }
      if (!animate) {
        requestAnimationFrame(() => cardsEl.classList.remove("no-motion"));
      }
    });

    updateButtons();
    renderCount += 1;
  }

  function showToast(message, kind) {
    window.clearTimeout(toastTimer);
    toastEl.textContent = message;
    toastEl.classList.toggle("error", kind === "error");
    toastEl.classList.add("visible");
    toastTimer = window.setTimeout(() => toastEl.classList.remove("visible"), 3600);
  }

  async function api(path, options = {}) {
    const headers = Object.assign({ "X-Quota-Token": token }, options.headers || {});
    const response = await fetch(path, Object.assign({}, options, { headers, cache: "no-store" }));
    let payload = {};
    try {
      payload = await response.json();
    } catch (error) {
      payload = {};
    }
    if (!response.ok) {
      throw new Error(typeof payload.error === "string" ? payload.error : "Локальный сервис вернул ошибку.");
    }
    return payload;
  }

  async function load() {
    if (loading) return;
    loading = true;
    try {
      const data = await api("/api/status");
      snapshot = data;
      lastError = "";
      lastErrorToast = "";
      render();
      if (data && data.refreshing) window.setTimeout(load, 1500);
    } catch (error) {
      lastError = "Не удалось связаться с локальным сервисом.";
      render();
      if (lastErrorToast !== lastError) {
        lastErrorToast = lastError;
        showToast(lastError, "error");
      }
    } finally {
      loading = false;
    }
  }

  async function refreshNow() {
    if (refreshing || (snapshot && snapshot.refreshing)) return;
    refreshing = true;
    lastError = "";
    render();
    try {
      const data = await api("/api/refresh", { method: "POST" });
      snapshot = data;
      if (data && data.refreshing) {
        showToast("Обновление уже выполняется");
        window.setTimeout(load, 1200);
      } else {
        showToast("Квоты обновлены");
      }
    } catch (error) {
      lastError = "Не удалось обновить квоты.";
      showToast(lastError, "error");
    } finally {
      refreshing = false;
      render();
    }
  }

  async function openSettings() {
    if (settingsBusy) return;
    settingsBusy = true;
    updateButtons();
    try {
      const data = await api("/api/settings", { method: "POST" });
      if (data && data.ok) {
        showToast("Открываю " + data.path);
      } else {
        showToast("Настройки: " + (data && data.path ? data.path : "config.json"));
      }
    } catch (error) {
      showToast("Не удалось открыть настройки.", "error");
    } finally {
      settingsBusy = false;
      updateButtons();
    }
  }

  refreshButton.addEventListener("click", refreshNow);
  settingsButton.addEventListener("click", openSettings);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) load();
  });
  window.addEventListener("online", load);

  async function boot() {
    await load();
    if (!snapshot || !snapshot.generated_at) {
      await refreshNow();
    }
    window.setInterval(load, POLL_MS);
  }

  boot();
})();
