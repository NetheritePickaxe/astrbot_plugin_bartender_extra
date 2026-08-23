const bridge = window.AstrBotPluginPage;
const $ = (id) => document.getElementById(id);

let stUrl = "";
let flashTimer = null;
let lastInfo = null;
let lastError = null;
let installPollTimer = null;
let lastActionBtn = null;

function applyLang() {
  try {
    const ctx = bridge.getContext();
    document.documentElement.lang = (ctx && ctx.lang) || "zh-CN";
  } catch {}
}

function setStatus(text, kind) {
  $("status-text").textContent = text;
  $("dot").className = "dot " + (kind || "unknown");
}

const KNOWN_ACTIONS = ["start", "install", "stop-wrap", "stop-all", "ext-tag"];

function revealAction(id) {
  hideActions();
  if (id === "stop-wrap") {
    const w = $("stop-wrap");
    if (w) w.classList.remove("hidden");
  } else {
    const el = $(id);
    if (el) el.classList.remove("hidden");
  }
  lastActionBtn = KNOWN_ACTIONS.includes(id) ? id : null;
  try { localStorage.setItem("st_action_btn", lastActionBtn || ""); } catch {}
}

function hideActions() {
  KNOWN_ACTIONS.forEach((id) => {
    const el = $(id);
    if (el) el.classList.add("hidden");
  });
  lastActionBtn = null;
  try { localStorage.removeItem("st_action_btn"); } catch {}
}

function setActionLoading(on, text) {
  if (!lastActionBtn) return;
  const el = $(lastActionBtn);
  if (!el) return;
  el.disabled = !!on;
  if (text !== undefined) el.textContent = text;
}

function showMessage(text, kind) {
  const m = $("message");
  m.textContent = text;
  m.className = "message-area " + (kind || "info");
  m.classList.remove("hidden");
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => {
    m.classList.add("hidden");
  }, 5000);
}

function applyStatus(info) {
  stUrl = info.st_url || "";
  $("addr").textContent = stUrl || "—";
  if (info.install_status) {
    applyInstallStatus(info.install_status);
    return;
  }
  if (info.reachable) {
    setStatus("酒馆在线", "online");
    if (info.has_bundled_st) {
      revealAction("stop-wrap");
    } else {
      revealAction("ext-tag");
    }
    revealAction("ext-tag");
  } else {
    setStatus("酒馆未连接", "offline");
    if (info.has_bundled_st) {
      revealAction("start");
    } else {
      revealAction("install");
    }
  }
}

function applyInstallStatus(status) {
  hideActions();
  if (status === "downloading" || status === "starting") {
    setStatus("安装中…", "unknown");
    showMessage("正在下载酒馆…", "info");
  } else if (status === "extracting") {
    setStatus("安装中…", "unknown");
    showMessage("正在解压…", "info");
  } else if (status === "installing_deps") {
    setStatus("安装中…", "unknown");
    showMessage("正在安装依赖(可能需要数分钟)…", "info");
  } else if (status === "done") {
    stopInstallPolling();
    setStatus("安装完成", "online");
    showMessage("SillyTavern 已安装，可点击「启动酒馆」启动。", "success");
    revealAction("start");
  } else if (typeof status === "string" && status.startsWith("failed")) {
    stopInstallPolling();
    setStatus("安装失败", "offline");
    showMessage(status, "error");
    revealAction("install");
  }
}

async function pollInstall() {
  if (installPollTimer) return;
  installPollTimer = setInterval(async () => {
    try {
      const info = await bridge.apiGet("info");
      lastInfo = info;
      if (!info.install_status) {
        stopInstallPolling();
        applyStatus(info);
        return;
      }
      applyInstallStatus(info.install_status);
    } catch (e) {
      stopInstallPolling();
      lastError = e.message || "请稍后重试。";
      setStatus("状态获取失败", "offline");
      showMessage(lastError, "error");
    }
  }, 2000);
}

function stopInstallPolling() {
  if (installPollTimer) {
    clearInterval(installPollTimer);
    installPollTimer = null;
  }
}

async function refreshStatus() {
  lastInfo = null;
  lastError = null;
  setStatus("检测中…", "unknown");
  if (lastActionBtn) setActionLoading(true, "检测中…");
  try {
    const info = await bridge.apiGet("info");
    lastInfo = info;
    applyStatus(info);
  } catch (e) {
    lastError = e.message || "请稍后重试。";
    setStatus("状态获取失败", "offline");
    showMessage(lastError, "error");
  }
}

async function startTavern() {
  setActionLoading(true, "启动中…");
  try {
    const r = await bridge.apiPost("tavern/start", {});
    if (r && r.ok) {
      showMessage("酒馆已启动", "success");
      await refreshStatus();
    } else {
      showMessage((r && r.message) || "启动失败", "error");
    }
  } catch (e) {
    showMessage(e.message || "启动失败", "error");
  }
  if (lastActionBtn) {
    const el = $(lastActionBtn);
    if (el) { el.disabled = false; el.textContent = "启动酒馆"; }
  }
}

async function installTavern() {
  setActionLoading(true, "安装中…");
  try {
    const r = await bridge.apiPost("tavern/install", {});
    if (r && r.ok) {
      showMessage("安装中…", "info");
      await refreshStatus();
      pollInstall();
    } else {
      showMessage((r && r.message) || "安装失败", "error");
    }
  } catch (e) {
    showMessage(e.message || "安装失败", "error");
  }
  if (lastActionBtn) {
    const el = $(lastActionBtn);
    if (el) { el.disabled = false; el.textContent = "安装酒馆"; }
  }
}

async function stopTavern() {
  hideMenu();
  setActionLoading(true, "关闭中…");
  try {
    const r = await bridge.apiPost("tavern/stop", {});
    if (r && r.ok) {
      showMessage("酒馆已关闭", "success");
      await refreshStatus();
    } else {
      showMessage((r && r.message) || "关闭失败", "error");
    }
  } catch (e) {
    showMessage(e.message || "关闭失败", "error");
  }
  if (lastActionBtn === "stop-wrap") {
    const main = $("stop-btn");
    if (main) { main.disabled = false; main.textContent = "关闭酒馆"; }
  }
}

async function restartTavern() {
  hideMenu();
  setActionLoading(true, "重启中…");
  try {
    const r = await bridge.apiPost("tavern/restart", {});
    if (r && r.ok) {
      showMessage("酒馆已重启", "success");
      await refreshStatus();
    } else {
      showMessage((r && r.message) || "重启失败", "error");
    }
  } catch (e) {
    showMessage(e.message || "重启失败", "error");
  }
  if (lastActionBtn === "stop-wrap") {
    const main = $("stop-btn");
    if (main) { main.disabled = false; main.textContent = "关闭酒馆"; }
  }
}

async function stopAll() {
  setActionLoading(true, "关闭中…");
  try {
    const r = await bridge.apiPost("tavern/stop", {});
    if (r && r.ok) {
      showMessage("酒馆已关闭，浏览器已清理", "success");
      await refreshStatus();
    } else {
      showMessage((r && r.message) || "关闭失败", "error");
    }
  } catch (e) {
    showMessage(e.message || "关闭失败", "error");
  }
  if (lastActionBtn) {
    const el = $(lastActionBtn);
    if (el) { el.disabled = false; el.textContent = "关闭全部"; }
  }
}

async function exportData() {
  const btn = $("export-data");
  btn.disabled = true;
  btn.textContent = "打包中…";
  try {
    const r = await bridge.apiPost("tavern/export-data", {});
    if (r && r.ok) {
      showMessage("导出完成", "success");
    } else {
      showMessage((r && r.message) || "导出失败", "error");
    }
  } catch (e) {
    showMessage(e.message || "导出失败", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "导出整库备份";
  }
}

function showMenu() {
  $("stop-menu").classList.remove("hidden");
}

function hideMenu() {
  $("stop-menu").classList.add("hidden");
}

async function copyAddr() {
  if (!stUrl) return;
  const btn = $("copy");
  const flash = (text) => {
    const old = btn.textContent;
    btn.textContent = text;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => {
      btn.textContent = old;
    }, 1500);
  };
  try {
    await navigator.clipboard.writeText(stUrl);
    flash("已复制");
    return;
  } catch {}
  const range = document.createRange();
  range.selectNode($("addr"));
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  try {
    document.execCommand("copy");
    flash("已复制");
  } catch {
    flash("请按 Ctrl+C");
  }
}

function bind() {
  $("refresh").addEventListener("click", refreshStatus);
  $("start").addEventListener("click", startTavern);
  $("install").addEventListener("click", installTavern);
  $("copy").addEventListener("click", copyAddr);
  $("stop-btn").addEventListener("click", stopTavern);
  $("stop-menu-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    showMenu();
  });
  document.addEventListener("click", hideMenu);
  $("stop-menu").addEventListener("click", (e) => e.stopPropagation());
  document.querySelectorAll("[data-act]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const act = btn.dataset.act;
      if (act === "stop") stopTavern();
      else if (act === "restart") restartTavern();
    });
  });
  if ($("ext-tag")) {
    $("ext-tag").addEventListener("click", () => {
      if (stUrl) window.open(stUrl, "_blank", "noopener");
    });
  }
  if ($("export-data")) {
    $("export-data").addEventListener("click", exportData);
  }
}

await bridge.ready();
applyLang();
bridge.onContext(applyLang);

try {
  const restored = localStorage.getItem("st_action_btn");
  if (restored && KNOWN_ACTIONS.includes(restored)) revealAction(restored);
} catch {}

bind();
refreshStatus();