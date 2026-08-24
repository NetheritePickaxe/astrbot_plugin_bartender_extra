const bridge = window.AstrBotPluginPage;
const $ = (id) => document.getElementById(id);

let stUrl = "";
let flashTimer = null;
let installPollTimer = null;
let _currentInfo = null;
let stRunning = false;

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

const ALL_BUTTONS = ["st-execute", "install", "ext-tag", "export-data", "uninstall", "import-btn", "refresh"];

function applyStatus(info) {
  if (!info) {
    setStatus("未获取到状态信息", "offline");
    setAllButtons({ refresh: true });
    return;
  }
  stUrl = info.st_url || "";
  $("addr").textContent = stUrl || "—";
  if (info.install_status) {
    applyInstallStatus(info.install_status);
    return;
  }
  _currentInfo = info;
  if (info.reachable) {
    setStatus("酒馆在线", "online");
    setStControl(true);
    setAllButtons({
      "st-execute": true, install: false,
      "ext-tag": true,
      "export-data": true, uninstall: true, "import-btn": true,
      refresh: true,
    });
  } else {
    setStatus("酒馆未连接", "offline");
    setStControl(false);
    if (info.has_bundled_st) {
      setAllButtons({
        "st-execute": true, install: false,
        "ext-tag": false,
        "export-data": true, uninstall: true, "import-btn": true,
        refresh: true,
      });
    } else {
      setAllButtons({
        "st-execute": false, install: true,
        "ext-tag": false,
        "export-data": false, uninstall: false, "import-btn": false,
        refresh: true,
      });
    }
  }
}

function applyInstallStatus(status) {
  setStControl(false);
  setAllButtons({
    "st-execute": false, install: false,
    "ext-tag": false,
    "export-data": false, uninstall: false, "import-btn": false,
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
      setAllButtons({ refresh: true });
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
    setAllButtons({ refresh: true });
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

const ST_ACTIONS = {
  start: { label: "启动", endpoint: "tavern/start", success: "酒馆已启动" },
  stop: { label: "关闭", endpoint: "tavern/stop", success: "酒馆已关闭" },
  restart: { label: "重启", endpoint: "tavern/restart", success: "酒馆已重启" },
};

function setDropdownOpen(open) {
  $("st-dd-menu").classList.toggle("hidden", !open);
}

function setStControl(running) {
  stRunning = running;
  $("st-dd-toggle").classList.toggle("hidden", !running);
  setDropdownOpen(false);
  $("st-execute").textContent = running ? "关闭" : "启动";
}

async function executeStAction(action) {
  const conf = ST_ACTIONS[action];
  if (!conf || $("st-execute").disabled) return;
  const btn = $("st-execute");
  const toggle = $("st-dd-toggle");
  setDropdownOpen(false);
  btn.disabled = true;
  toggle.disabled = true;
  btn.textContent = conf.label + "中…";
  try {
    const r = await bridge.apiPost(conf.endpoint, {});
    if (r && r.ok) {
      showMessage(conf.success, "success");
    } else {
      showMessage((r && r.message) || conf.label + "失败", "error");
    }
  } catch (e) {
    showMessage(e.message || conf.label + "失败", "error");
  } finally {
    btn.textContent = stRunning ? "关闭" : "启动";
    toggle.disabled = false;
    await refreshStatus();
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
  $("st-execute").addEventListener("click", () => {
    if ($("st-execute").disabled) return;
    executeStAction(stRunning ? "stop" : "start");
  });
  $("st-dd-toggle").addEventListener("click", () => {
    if ($("st-dd-toggle").classList.contains("hidden")) return;
    setDropdownOpen($("st-dd-menu").classList.contains("hidden"));
  });
  $("st-dd-menu").querySelectorAll(".dropdown-item").forEach((item) => {
    item.addEventListener("click", () => {
      executeStAction(item.dataset.action);
    });
  });
  document.addEventListener("click", (e) => {
    if (!$("st-dd").contains(e.target)) setDropdownOpen(false);
  });
  $("install").addEventListener("click", installTavern);
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
