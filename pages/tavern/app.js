const bridge = window.AstrBotPluginPage;
const $ = (id) => document.getElementById(id);

let stUrl = "";
let flashTimer = null;
let installPollTimer = null;

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

function showButtons(ids) {
  ["start", "install", "stop", "restart", "ext-tag", "export-data", "refresh"].forEach((id) => {
    const el = $(id);
    if (el) el.classList.add("hidden");
  });
  ids.forEach((id) => {
    const el = $(id);
    if (el) el.classList.remove("hidden");
  });
}

function showMessage(text, kind) {
  const m = $("message");
  m.textContent = text;
  m.className = "message " + (kind || "info");
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
    showButtons(["stop", "restart", "ext-tag", "export-data", "refresh"]);
  } else {
    setStatus("酒馆未连接", "offline");
    if (info.has_bundled_st) {
      showButtons(["start", "refresh"]);
    } else {
      showButtons(["install", "refresh"]);
    }
  }
}

function applyInstallStatus(status) {
  showButtons([]);
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
    showButtons(["start"]);
  } else if (typeof status === "string" && status.startsWith("failed")) {
    stopInstallPolling();
    setStatus("安装失败", "offline");
    showMessage(status, "error");
    showButtons(["install"]);
  }
}

async function pollInstall() {
  if (installPollTimer) return;
  installPollTimer = setInterval(async () => {
    try {
      const info = await bridge.apiGet("info");
      if (!info.install_status) {
        stopInstallPolling();
        applyStatus(info);
        return;
      }
      applyInstallStatus(info.install_status);
    } catch (e) {
      stopInstallPolling();
      setStatus("状态获取失败", "offline");
      showMessage(e.message || "请稍后重试。", "error");
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
  setStatus("检测中…", "unknown");
  try {
    const info = await bridge.apiGet("info");
    applyStatus(info);
  } catch (e) {
    setStatus("状态获取失败", "offline");
    showMessage(e.message || "请稍后重试。", "error");
  }
}

async function startTavern() {
  const btn = $("start");
  btn.disabled = true;
  btn.textContent = "启动中…";
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
  } finally {
    btn.disabled = false;
    btn.textContent = "启动酒馆";
  }
}

async function installTavern() {
  const btn = $("install");
  btn.disabled = true;
  btn.textContent = "安装中…";
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
  } finally {
    btn.disabled = false;
    btn.textContent = "安装酒馆";
  }
}

async function stopTavern() {
  const btn = $("stop");
  btn.disabled = true;
  btn.textContent = "关闭中…";
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
  } finally {
    btn.disabled = false;
    btn.textContent = "关闭酒馆";
  }
}

async function restartTavern() {
  const btn = $("restart");
  btn.disabled = true;
  btn.textContent = "重启中…";
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
  } finally {
    btn.disabled = false;
    btn.textContent = "重启酒馆";
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
  $("stop").addEventListener("click", stopTavern);
  $("restart").addEventListener("click", restartTavern);
  $("copy").addEventListener("click", copyAddr);
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
bind();
refreshStatus();