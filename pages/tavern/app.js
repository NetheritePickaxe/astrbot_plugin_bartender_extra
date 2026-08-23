const bridge = window.AstrBotPluginPage;
const $ = (id) => document.getElementById(id);

let stUrl = "";
let flashTimer = null;
let lastInfo = null;
let lastError = null;
let installPollTimer = null;
let lastActionBtn = null;

// 语言同步：bridge 的 applyContext 已自动处理 data-theme，这里只补 lang 属性
function applyLang() {
  try {
    const ctx = bridge.getContext();
    document.documentElement.lang = (ctx && ctx.lang) || "zh-CN";
  } catch {}
}

function isMixedContent() {
  try {
    return (
      window.location.protocol === "https:" &&
      new URL(stUrl).protocol === "http:"
    );
  } catch {
    return false;
  }
}

function setStatus(text, kind) {
  $("status-text").textContent = text;
  $("dot").className = "dot " + (kind || "unknown");
}

const KNOWN_ACTIONS = ["start", "install", "stop-wrap", "ext-tag"];

function revealAction(id) {
  hideActions();
  if (id === "stop-wrap") {
    const w = $("stop-wrap");
    if (w) w.classList.remove("hidden");
    const main = $("stop-btn");
    if (main) { main.disabled = false; main.textContent = "关闭酒馆"; }
    const caret = $("stop-menu-btn");
    if (caret) caret.disabled = false;
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
  if (lastActionBtn === "stop-wrap") {
    const main = $("stop-btn");
    const caret = $("stop-menu-btn");
    if (main) {
      main.disabled = !!on;
      if (text !== undefined) main.textContent = on ? text : "关闭酒馆";
    }
    if (caret) caret.disabled = !!on;
    if (on) $("stop-menu").classList.add("hidden");
  } else {
    const el = $(lastActionBtn);
    if (!el) return;
    el.disabled = !!on;
    if (text !== undefined) el.textContent = text;
  }
}

function showFrame() {
  if (!stUrl || isMixedContent()) {
    showFallback();
    return;
  }
  const f = $("frame");
  if (f.src !== stUrl) f.src = stUrl;
  f.classList.remove("hidden");
  $("fallback").classList.add("hidden");
}

function showFallback(title, desc) {
  $("frame").classList.add("hidden");
  $("frame").removeAttribute("src");
  if (title) $("fallback-title").textContent = title;
  if (desc) $("fallback-desc").textContent = desc;
  $("fallback").classList.remove("hidden");
}

// 按最近一次探测结果渲染状态区（语言切换后按当前语言重绘）
function applyStatus(info) {
  stUrl = info.st_url || "";
  $("addr").textContent = stUrl || "—";
  // 安装进行中/刚完成 → 优先展示安装状态，隐藏操作按钮
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
    if (isMixedContent()) {
      showFallback(
        "混合内容被拦截",
        "面板为 HTTPS 而酒馆为 HTTP，浏览器禁止内嵌。请复制地址在新标签页打开，或将面板改用 HTTP 访问。"
      );
    } else {
      showFrame();
    }
  } else {
    setStatus("酒馆未连接", "offline");
    if (info.has_bundled_st) {
      revealAction("start");
    } else {
      revealAction("install");
    }
    showFallback(
      "酒馆未连接",
      "未检测到酒馆服务运行。" +
        (info.has_bundled_st
          ? "可点击右上「启动酒馆」一键拉起插件目录中的酒馆。"
          : "未检测到酒馆，点击「安装酒馆」一键下载并安装。")
    );
  }
}

// 安装状态渲染：进行中显示进度，完成/失败显示结果并停轮询
function applyInstallStatus(status) {
  hideActions();
  if (status === "downloading" || status === "starting") {
    setStatus("安装中…", "unknown");
    showFallback("安装中…", "正在下载酒馆…");
  } else if (status === "extracting") {
    setStatus("安装中…", "unknown");
    showFallback("安装中…", "正在解压…");
  } else if (status === "installing_deps") {
    setStatus("安装中…", "unknown");
    showFallback("安装中…", "正在安装依赖(可能需要数分钟)…");
  } else if (status === "done") {
    stopInstallPolling();
    setStatus("安装完成", "online");
    showFallback("安装完成", "SillyTavern 已安装，可点击「启动酒馆」启动。");
    revealAction("start");
  } else if (typeof status === "string" && status.startsWith("failed")) {
    stopInstallPolling();
    setStatus("安装失败", "offline");
    showFallback("安装失败", status);
    revealAction("install");
  }
}

// 安装轮询：每 2 秒拉取一次 info 读取安装状态
async function pollInstall() {
  if (installPollTimer) return;
  installPollTimer = setInterval(async () => {
    try {
      const info = await bridge.apiGet("info");
      lastInfo = info;
      if (!info.install_status) {
        // 后台已清空状态 → 回到正常流程
        stopInstallPolling();
        applyStatus(info);
        return;
      }
      applyInstallStatus(info.install_status);
    } catch (e) {
      stopInstallPolling();
      lastError = e.message || "请稍后重试。";
      setStatus("状态获取失败", "offline");
      showFallback("状态获取失败", lastError);
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
    showFallback("状态获取失败", lastError);
  }
}

async function startTavern() {
  const btn = $("start");
  btn.disabled = true;
  btn.textContent = "启动中…";
  try {
    const r = await bridge.apiPost("tavern/start", {});
    if (r && r.ok) {
      await refreshStatus();
    } else {
      alert((r && r.message) || "启动失败");
    }
  } catch (e) {
    alert(e.message || "启动失败");
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
      btn.textContent = "安装中…";
      await refreshStatus();
      pollInstall();
    } else {
      alert((r && r.message) || "安装失败");
      btn.textContent = "安装酒馆";
    }
  } catch (e) {
    alert(e.message || "安装失败");
  } finally {
    btn.disabled = false;
  }
}

async function stopTavern() {
  hideMenu();
  const btn = $("stop-btn");
  btn.disabled = true;
  btn.textContent = "关闭中…";
  try {
    const r = await bridge.apiPost("tavern/stop", {});
    if (r && r.ok) {
      await refreshStatus();
    } else {
      alert((r && r.message) || "关闭失败");
      btn.disabled = false;
      btn.textContent = "关闭酒馆";
    }
  } catch (e) {
    alert(e.message || "关闭失败");
    btn.disabled = false;
    btn.textContent = "关闭酒馆";
  }
}

async function restartTavern() {
  hideMenu();
  const btn = $("stop-btn");
  btn.disabled = true;
  btn.textContent = "重启中…";
  try {
    const r = await bridge.apiPost("tavern/restart", {});
    if (r && r.ok) {
      await refreshStatus();
    } else {
      alert((r && r.message) || "重启失败");
      btn.disabled = false;
      btn.textContent = "关闭酒馆";
    }
  } catch (e) {
    alert(e.message || "重启失败");
    btn.disabled = false;
    btn.textContent = "关闭酒馆";
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
  } catch {
    // 落地兜底
  }
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
}

await bridge.ready();

// 语言同步（bridge 已自动处理 data-theme 主题跟随）
applyLang();
bridge.onContext(applyLang);

// 恢复上次 session 的操作按钮（F5 重载时避免按钮直接消失）
try {
  const restored = localStorage.getItem("st_action_btn");
  if (restored && KNOWN_ACTIONS.includes(restored)) revealAction(restored);
} catch {}

bind();
refreshStatus();
