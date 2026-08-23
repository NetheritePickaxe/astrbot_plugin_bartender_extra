const bridge = window.AstrBotPluginPage;
const $ = (id) => document.getElementById(id);

// i18n：从 .astrbot-plugin/i18n/{locale}.json 的 pages.tavern 取词，fallback 为中文文案
const t = (key, fallback) => bridge.t("pages.tavern." + key, fallback);

let stUrl = "";
let flashTimer = null;
let lastInfo = null;
let lastError = null;

function applyTheme() {
  const ctx = bridge.getContext();
  document.documentElement.setAttribute(
    "data-theme",
    ctx && ctx.isDark ? "dark" : "light"
  );
  document.documentElement.lang = (ctx && ctx.locale) || "zh-CN";
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
  if (info.reachable) {
    setStatus(t("online", "酒馆在线"), "online");
    if (isMixedContent()) {
      showFallback(
        t("mixed_title", "混合内容被拦截"),
        t("mixed_desc", "面板为 HTTPS 而酒馆为 HTTP，浏览器禁止内嵌。请复制地址在新标签页打开，或将面板改用 HTTP 访问。")
      );
    } else {
      showFrame();
    }
  } else {
    setStatus(t("offline", "酒馆未连接"), "offline");
    if (info.has_bundled_st) $("start").classList.remove("hidden");
    showFallback(
      t("offline", "酒馆未连接"),
      t("offline_desc_base", "未检测到酒馆服务运行。") +
        (info.has_bundled_st
          ? t("offline_desc_start", "可点击右上「启动酒馆」一键拉起插件目录中的酒馆。")
          : t("offline_desc_manual", "请确认酒馆已启动，或检查插件配置中的酒馆地址与端口。"))
    );
  }
}

// 静态文案 + 最近一次状态
function render() {
  $("copy").textContent = t("copy", "复制");
  $("copy").title = t("copy_title", "复制地址");
  $("refresh").textContent = t("refresh", "刷新状态");
  $("start").textContent = t("start", "启动酒馆");
  if (lastError) {
    setStatus(t("status_fail", "状态获取失败"), "offline");
    showFallback(t("status_fail", "状态获取失败"), lastError);
  } else if (lastInfo) {
    applyStatus(lastInfo);
  }
}

async function refreshStatus() {
  lastInfo = null;
  lastError = null;
  setStatus(t("checking", "检测中…"), "unknown");
  $("start").classList.add("hidden");
  try {
    const info = await bridge.apiGet("info");
    lastInfo = info;
    applyStatus(info);
  } catch (e) {
    lastError = e.message || t("retry", "请稍后重试。");
    setStatus(t("status_fail", "状态获取失败"), "offline");
    showFallback(t("status_fail", "状态获取失败"), lastError);
  }
}

async function startTavern() {
  const btn = $("start");
  btn.disabled = true;
  btn.textContent = t("starting", "启动中…");
  try {
    const r = await bridge.apiPost("tavern/start", {});
    if (r && r.ok) {
      await refreshStatus();
    } else {
      alert((r && r.message) || t("start_fail", "启动失败"));
    }
  } catch (e) {
    alert(e.message || t("start_fail", "启动失败"));
  } finally {
    btn.disabled = false;
    btn.textContent = t("start", "启动酒馆");
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
    flash(t("copied", "已复制"));
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
    flash(t("copied", "已复制"));
  } catch {
    flash(t("press_ctrl_c", "请按 Ctrl+C"));
  }
}

function bind() {
  $("refresh").addEventListener("click", refreshStatus);
  $("start").addEventListener("click", startTavern);
  $("copy").addEventListener("click", copyAddr);
}

await bridge.ready();
applyTheme();
bridge.onContext(() => {
  applyTheme();
  render();
});
bind();
render();
refreshStatus();
