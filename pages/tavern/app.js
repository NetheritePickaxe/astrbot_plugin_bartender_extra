const bridge = window.AstrBotPluginPage;
const $ = (id) => document.getElementById(id);

let stUrl = "";
let flashTimer = null;

function applyTheme() {
  const ctx = bridge.getContext();
  document.documentElement.setAttribute(
    "data-theme",
    ctx && ctx.isDark ? "dark" : "light"
  );
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

async function refreshStatus() {
  setStatus("检测中…", "unknown");
  $("start").classList.add("hidden");
  try {
    const info = await bridge.apiGet("info");
    stUrl = info.st_url || "";
    $("addr").textContent = stUrl || "—";
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
      if (info.has_bundled_st) $("start").classList.remove("hidden");
      showFallback(
        "酒馆未连接",
        "未检测到酒馆服务运行。" +
          (info.has_bundled_st
            ? "可点击右上「启动酒馆」一键拉起插件目录中的酒馆。"
            : "请确认酒馆已启动，或检查插件配置中的酒馆地址与端口。")
      );
    }
  } catch (e) {
    setStatus("状态获取失败", "offline");
    showFallback("状态获取失败", e.message || "请稍后重试。");
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
  $("copy").addEventListener("click", copyAddr);
}

await bridge.ready();
applyTheme();
bridge.onContext(applyTheme);
bind();
refreshStatus();
