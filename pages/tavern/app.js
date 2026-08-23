const bridge = window.AstrBotPluginPage;
const $ = (id) => document.getElementById(id);

let stUrl = "";
let flashTimer = null;
let installPollTimer = null;
let _currentInfo = null;

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

const ALL_BUTTONS = ["start", "install", "stop", "restart", "ext-tag", "export-data", "uninstall", "import-btn", "refresh"];

function applyStatus(info) {
  stUrl = info.st_url || "";
  $("addr").textContent = stUrl || "—";
  if (info.install_status) {
    applyInstallStatus(info.install_status);
    return;
  }
  _currentInfo = info;
  if (info.reachable) {
    setStatus("酒馆在线", "online");
    setAllButtons({
      start: false, install: false,
      stop: true, restart: true, "ext-tag": true,
      export-data: true, uninstall: true, "import-btn": true,
      refresh: true,
    });
  } else {
    setStatus("酒馆未连接", "offline");
    if (info.has_bundled_st) {
      setAllButtons({
        start: true, install: false,
        stop: false, restart: false, "ext-tag": false,
        export-data: true, uninstall: true, "import-btn": true,
        refresh: true,
      });
    } else {
      setAllButtons({
        start: false, install: true,
        stop: false, restart: false, "ext-tag": false,
        export-data: false, uninstall: false, "import-btn": false,
        refresh: true,
      });
    }
  }
}

function applyInstallStatus(status) {
  setAllButtons({
    start: false, install: false,
    stop: false, restart: false, "ext-tag": false,
    export-data: false, uninstall: false, "import-btn": false,
    refresh: true,
  });
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
    applyStatus({ st_url: stUrl, reachable: true, has_bundled_st: true });
  } else if (typeof status === "string" && status.startsWith("failed")) {
    stopInstallPolling();
    setStatus("安装失败", "offline");
    showMessage(status, "error");
    applyStatus({ st_url: stUrl, reachable: false, has_bundled_st: false });
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

function setAllButtons(states) {
  ALL_BUTTONS.forEach((id) => {
    const el = $(id);
    if (!el) return;
    const enabled = states[id] !== false;
    el.disabled = !enabled;
    el.classList.toggle("hidden", false);
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
    btn.textContent = "启动";
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
    btn.textContent = "安装";
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
    btn.textContent = "关闭";
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
    btn.textContent = "重启";
  }
}

async function exportData() {
  const btn = $("export-data");
  btn.disabled = true;
  btn.textContent = "打包中…";
  try {
    const r = await bridge.apiPost("tavern/export-data", {});
    if (r && r.ok) {
      showMessage("导出完成，文件已开始下载", "success");
    } else {
      showMessage((r && r.message) || "导出失败", "error");
    }
  } catch (e) {
    showMessage(e.message || "导出失败", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "导出";
  }
}

async function uninstallTavern() {
  if (!confirm("确定要卸载酒馆？\n\n所有角色、聊天记录、配置将被永久删除，此操作不可撤销。")) return;
  const btn = $("uninstall");
  btn.disabled = true;
  btn.textContent = "卸载中…";
  try {
    const r = await bridge.apiPost("tavern/uninstall", {});
    if (r && r.ok) {
      showMessage("酒馆已卸载，可点击「安装酒馆」重新安装", "success");
      await refreshStatus();
    } else {
      showMessage((r && r.message) || "卸载失败", "error");
    }
  } catch (e) {
    showMessage(e.message || "卸载失败", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "卸载";
  }
}

async function importData() {
  $("import-file").click();
}

$("import-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  $("import-file").value = "";
  const btn = $("import-btn");
  btn.disabled = true;
  btn.textContent = "导入中…";
  try {
    const data = await file.arrayBuffer();
    const bytes = new Uint8Array(data);
    let binary = "";
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    const b64 = btoa(binary);
    const r = await bridge.apiPost("tavern/import-data", { file: b64 });
    if (r && r.ok) {
      showMessage(r.message || "数据导入完成，请重新启动酒馆", "success");
      await refreshStatus();
    } else {
      showMessage((r && r.message) || "导入失败", "error");
    }
  } catch (err) {
    showMessage(err.message || "导入失败", "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "导入";
  }
});

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
  $("export-data").addEventListener("click", exportData);
  $("uninstall").addEventListener("click", uninstallTavern);
  $("import-btn").addEventListener("click", importData);
  $("copy").addEventListener("click", copyAddr);
  if ($("ext-tag")) {
    $("ext-tag").addEventListener("click", () => {
      if (stUrl) window.open(stUrl, "_blank", "noopener");
    });
  }
}

await bridge.ready();
applyLang();
bridge.onContext(applyLang);
bind();
refreshStatus();
