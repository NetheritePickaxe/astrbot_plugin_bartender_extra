const bridge = window.AstrBotPluginPage;
const $ = (id) => document.getElementById(id);

let stUrl = "";
let flashTimer = null;
let lastInfo = null;
let lastError = null;
let installPollTimer = null;

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

function showFrame() {
  if (!stUrl || isMixedContent()) {
    showFallback();
    return;
  }
  const f = $("frame");
  if (f.src !== stUrl) f.src = stUrl;
  f.classList.remove("hidden");
  $("fallback").classList.add("hidden");
  $("start").classList.add("hidden");
  $("install").classList.add("hidden");
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
  // 安装进行中/刚完成 → 优先展示安装状态，隐藏按钮
  if (info.install_status) {
    applyInstallStatus(info.install_status);
    return;
  }
  if (info.reachable) {
    setStatus("酒馆在线", "online");
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
      $("start").classList.remove("hidden");
    } else {
      $("install").classList.remove("hidden");
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
  $("start").classList.add("hidden");
  $("install").classList.add("hidden");
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
    $("start").classList.remove("hidden");
  } else if (typeof status === "string" && status.startsWith("failed")) {
    stopInstallPolling();
    setStatus("安装失败", "offline");
    showFallback("安装失败", status);
    $("install").classList.remove("hidden");
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

// 静态文案 + 最近一次状态
function render() {
  $("copy").textContent = "复制";
  $("copy").title = "复制地址";
  $("refresh").textContent = "刷新状态";
  $("start").textContent = "启动酒馆";
  $("install").textContent = "安装酒馆";
  if (lastError) {
    setStatus("状态获取失败", "offline");
    showFallback("状态获取失败", lastError);
  } else if (lastInfo) {
    applyStatus(lastInfo);
  }
}

async function refreshStatus() {
  lastInfo = null;
  lastError = null;
  setStatus("检测中…", "unknown");
  $("start").classList.add("hidden");
  $("install").classList.add("hidden");
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
}

await bridge.ready();

bind();
refreshStatus();
