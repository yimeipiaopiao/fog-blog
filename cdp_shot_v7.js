// v7 同步机制视觉验证：验证配色 / 深浅色 前后台同步的视觉效果
// 截图目标（v7_* 前缀）：
//   1. 前台 sea 配色 + dark（验证前台切换按钮工作）
//   2. 前台 grape 配色 + light（验证 palette picker 工作）
//   3. 后台 dashboard 顶栏（验证新增的 theme/palette/登出按钮）
//   4. 后台 settings 页（验证配色下拉框原样 + 顶栏按钮）
//   5. 开屏 splash（验证 splash 跟随 data-palette 颜色变化）
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const ADMIN_SESSION = process.argv[2];
const PORT = process.argv[3] || "5000";
const BASE = `http://127.0.0.1:${PORT}`;
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const OUT_DIR = path.join(__dirname, "shots");
const CDP_PORT = 9337;

const TARGETS = [
  { p: "/", name: "v7_home_default_amber", admin: false, splash: true },
  { p: "/", name: "v7_home_sea_dark",  admin: false, palette: "sea", dark: true,  splash: true  },
  { p: "/", name: "v7_home_grape",     admin: false, palette: "grape", splash: true },
  { p: "A:/admin/",         name: "v7_admin_dashboard_topbar", admin: true },
  { p: "A:/admin/settings", name: "v7_admin_settings_topbar",  admin: true, fullPage: true },
];

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const profile = path.join(__dirname, "cdp_profile_v7_" + Date.now());
  const edge = spawn(EDGE, [
    "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
    "--force-prefers-reduced-motion",
    `--remote-debugging-port=${CDP_PORT}`,
    `--user-data-dir=${profile}`,
    "--window-size=1440,900",
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
    } catch { await sleep(300); }
  }
  if (!version) {
    console.error("CDP 未就绪");
    edge.kill();
    process.exit(1);
  }
  const ws = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });

  let msgId = 0;
  const pending = new Map();
  function send(method, params = {}, sessId = null) {
    return new Promise((resolve) => {
      const id = ++msgId; pending.set(id, resolve);
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
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  const s = (method, params = {}) => send(method, params, sessionId);
  await s("Network.enable"); await s("Page.enable");

  for (const t of TARGETS) {
    let cookie = null, p = t.p;
    if (t.admin) { cookie = ADMIN_SESSION; p = p.replace(/^A:/, ""); }
    const fullPage = !!t.fullPage;

    // 清掉浏览器 cookies + 注入 admin cookie
    await s("Network.clearBrowserCookies");
    if (cookie) {
      await s("Network.setCookie", { name: "session", value: cookie, url: BASE, path: "/" });
    }
    await s("Page.navigate", { url: BASE + p });
    await sleep(1400);

    // 先清掉 wb-theme 用 localStorage（注意：admin 也要清，否则 DB 默认 light 时手选 dark 会污染）
    await s("Runtime.evaluate", { expression: `try{localStorage.removeItem('wb-palette'); localStorage.removeItem('wb-theme');}catch(e){}` });
    await s("Page.navigate", { url: BASE + p });
    await sleep(2200);

    if (t.dark) {
      // 设深色
      await s("Runtime.evaluate", { expression: `localStorage.setItem('wb-theme','dark'); location.reload();` });
      await sleep(2200);
    }
    if (t.palette) {
      // 配色切换：直接 set data-palette 模拟用户已点选
      await s("Runtime.evaluate", { expression: `localStorage.setItem('wb-palette','${t.palette}'); location.reload();` });
      await sleep(2200);
    }

    // 首页开屏（24h 内不再显示：清掉 seen 标记强制显示）
    if (t.splash) {
      await s("Runtime.evaluate", { expression: `try{localStorage.removeItem('wb-splash-seen');}catch(e){}` });
      await s("Page.navigate", { url: BASE + p });
      await sleep(2500);  // 让 splash 卡片初始化动画开始
    }

    const opts = { format: "png" };
    if (fullPage) opts.captureBeyondViewport = true;
    const { data } = await s("Page.captureScreenshot", opts);
    const file = path.join(OUT_DIR, t.name + ".png");
    fs.writeFileSync(file, Buffer.from(data, "base64"));
    console.log("已截图:", t.name, p, t.dark ? "[dark]" : "", t.palette ? `[${t.palette}]` : "");
  }

  console.log("\n完成 " + TARGETS.length + " 张 v7 截图 →", OUT_DIR);
  edge.kill();
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch (_) {}
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  try { edge && edge.kill(); } catch (_) {}
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch (_) {}
  process.exit(1);
});
