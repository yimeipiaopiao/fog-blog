// 用 Edge headless (CDP) 截取博客页面截图。支持每目标注入不同身份 cookie 与深色模式。
// 用法: node cdp_shot.js <admin_cookie> [port]
//   - 目标路径前缀 ^A: 注入 admin cookie；无前缀: 游客
//   - 目标名含 "dark": 注入 localStorage wb-theme=dark 并重载
//   - 目标名含 "emoji": 滚动到底并点开 emoji 面板，全页截图
//   - 目标名含 "nocomment" / "login_gate" / "emoji_collapsed" / "pdfview": 滚动到底 + 全页截图
//   - 截前会清掉 localStorage.wb-theme 与上次 cookie，确保每个 target 状态干净
//   - 目标名 "v6_*" 即可作为命名约定；本脚本不依赖具体版本名
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const ADMIN_SESSION = process.argv[2] || "";
const PORT = process.argv[3] || "5000";
const BASE = `http://127.0.0.1:${PORT}`;
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const OUT_DIR = path.join(__dirname, "shots");
const CDP_PORT = 9333;

const TARGETS = [
  { p: "/",                                                name: "v6_home_light" },
  { p: "/",                                                name: "v6_home_dark",        dark: true },
  { p: "/post/welcome-to-fog-blog",                        name: "v6_post_emoji_collapsed" },
  { p: "/post/welcome-to-fog-blog",                        name: "v6_post_emoji",       emoji: true },
  { p: "/post/v5-nocomment",                               name: "v6_post_nocomment",   nocomment: true },
  { p: "/login",                                            name: "v6_login_gate" },
  { p: "A:/admin/pdf/new",                                 name: "v6_admin_pdf_new" },
  { p: "A:/admin/posts",                                   name: "v6_admin_posts" },
  { p: "A:/admin/settings",                                name: "v6_admin_settings" },
  { p: "A:/admin/login",                                   name: "v6_admin_login" },
  { p: "/post/pdf-demo",                                   name: "v6_pdf_view",         pdfview: true },
];

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const profile = path.join(__dirname, "cdp_profile_" + Date.now());
  const edge = spawn(EDGE, [
    "--headless=new",
    "--disable-gpu",
    "--no-sandbox",
    "--hide-scrollbars",
    "--force-prefers-reduced-motion",
    `--remote-debugging-port=${CDP_PORT}`,
    `--user-data-dir=${profile}`,
    "--window-size=1440,1000",
    "about:blank",
  ]);
  edge.stdout.on("data", () => {});
  edge.stderr.on("data", () => {});

  let version = null;
  for (let i = 0; i < 40; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`);
      version = await res.json();
      break;
    } catch {
      await sleep(300);
    }
  }
  if (!version) {
    console.error("CDP 未就绪");
    edge.kill();
    process.exit(1);
  }

  const ws = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });

  let msgId = 0;
  const pending = new Map();
  function send(method, params = {}, sessId = null) {
    return new Promise((resolve) => {
      const id = ++msgId;
      pending.set(id, resolve);
      const msg = { id, method, params };
      if (sessId) msg.sessionId = sessId;
      ws.send(JSON.stringify(msg));
    });
  }
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      pending.get(m.id)(m.result);
      pending.delete(m.id);
    }
  };

  const { targetId } = await send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await send("Target.attachToTarget", {
    targetId,
    flatten: true,
  });
  const s = (method, params = {}) => send(method, params, sessionId);

  await s("Network.enable");
  await s("Page.enable");

  const results = [];
  for (const t of TARGETS) {
    let cookie = null, p = t.p;
    if (p.startsWith("A:")) { cookie = ADMIN_SESSION; p = p.slice(2); }
    const fullPage = t.emoji || t.nocomment || t.name === "v6_login_gate" || t.name === "v6_post_emoji_collapsed" || t.pdfview;
    const isDark = !!t.dark;

    // 清掉上次的 session cookie 与 localStorage，避免上一个 target 的 dark 偏好污染 light 截图
    await s("Network.clearBrowserCookies");
    if (cookie) {
      await s("Network.setCookie", { name: "session", value: cookie, url: BASE, path: "/" });
    }
    await s("Page.navigate", { url: BASE + p });
    await sleep(1400);
    await s("Runtime.evaluate", {
      expression: "try { localStorage.removeItem('wb-theme'); } catch(e){}",
    });
    await s("Page.navigate", { url: BASE + p });
    await sleep(2200);
    if (isDark) {
      await s("Runtime.evaluate", {
        expression: `localStorage.setItem('wb-theme','dark'); location.reload();`,
      });
      await sleep(2200);
    }
    if (t.emoji) {
      // 评论区 emoji 面板：滚到底 + 点开
      await s("Runtime.evaluate", {
        expression: `window.scrollTo(0, document.body.scrollHeight); void 0;`,
      });
      await sleep(500);
      await s("Runtime.evaluate", {
        expression: `var b=document.getElementById('emojiToggle'); if(b){b.click();} void 0;`,
      });
      await sleep(600);
    } else if (t.nocomment || t.name === "v6_post_emoji_collapsed") {
      // 禁评文章 / 默认收起状态：滚到底看评论区
      await s("Runtime.evaluate", {
        expression: `window.scrollTo(0, document.body.scrollHeight); void 0;`,
      });
      await sleep(500);
    }
    if (t.pdfview) {
      // PDF 阅读页：滚到底触发懒渲染所有页
      await s("Runtime.evaluate", {
        expression: `var el=document.querySelector('.pdf-article'); if(el) el.scrollIntoView({block:'start'}); window.scrollTo(0, document.body.scrollHeight); void 0;`,
      });
      await sleep(4500);  // 给懒渲染足够时间
    }
    const opts = { format: "png" };
    if (fullPage) opts.captureBeyondViewport = true;
    const { data } = await s("Page.captureScreenshot", opts);
    const file = path.join(OUT_DIR, t.name + ".png");
    fs.writeFileSync(file, Buffer.from(data, "base64"));
    results.push(`${t.name}.png  (${p}${t.dark ? " [dark]" : ""}${t.emoji ? " [emoji]" : ""}${t.nocomment ? " [nocomment]" : ""})`);
    console.log("已截图:", t.name, p, isDark ? "[dark]" : "", t.emoji ? "[emoji]" : "", t.nocomment ? "[nocomment]" : "");
  }

  console.log("\n完成 " + results.length + " 张截图 →", OUT_DIR);
  edge.kill();
  // 清掉临时 profile 目录（防止以后被 Edge 当成"陌生父目录"或者占用）
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch (_) {}
  process.exit(0);
}

main().catch((e) => {
console.error(e);
    try { edge && edge.kill(); } catch (_) {}
    try { fs.rmSync(profile, { recursive: true, force: true }); } catch (_) {}
    process.exit(1);
});
