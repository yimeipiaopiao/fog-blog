// v8 视觉验证：v7 是 "顶部条版"；v8 改为 "左侧底部 .prefs-dock 版"
// 验证目标：
//   1. 后台 dashboard 不再有顶部条
//   2. 后台 settings 页 .prefs-dock 双按钮位于左下
//   3. 后台 settings 页 配色/深浅下拉框 data-bind 已挂载
//   4. 前台 splash / 主页仍按 color_palette 渲染（看默认/sea）
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
  { p: "A:/admin/",         name: "v8_admin_dashboard_no_topbar", admin: true, splash: false },
  { p: "A:/admin/pages",    name: "v8_admin_pages_sea",          admin: true, splash: false, fullPage: true },
  { p: "A:/admin/settings", name: "v8_admin_settings_docks",     admin: true, splash: false, fullPage: false },
  { p: "A:/admin/settings", name: "v8_admin_settings_picker_open", admin: true, splash: false, actions: ["openPalettePicker"] },
  { p: "/",                 name: "v8_home_default",             admin: false, splash: true },
  { p: "/",                 name: "v8_home_sea_dark",            admin: false, palette: "sea", dark: true, splash: true },
];

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

function adminCookieHeader() {
  // 用 Page.addCookieToAllFrames 前我们手动注入 document.cookie
  return `session=${ADMIN_SESSION}`;
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  // 启动 Edge 调试模式
  const userDataDir = path.join(__dirname, ".edge-v8");
  try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch (e) {}
  const edge = spawn(EDGE, [
    "--remote-debugging-port=" + CDP_PORT,
    "--user-data-dir=" + userDataDir,
    "--no-first-run", "--no-default-browser-check",
    "--window-size=1440,860",
    "about:blank",
  ], { stdio: "ignore", windowsHide: true });

  // 等待 CDP 端口
  for (let i = 0; i < 40; i++) {
    try {
      const ver = await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`).then(r => r.json());
      if (ver.webSocketDebuggerUrl) break;
    } catch (e) {}
    await sleep(250);
  }

  // fetch a real page to get targetId
  let res = await fetch(`http://127.0.0.1:${CDP_PORT}/json`).then(r => r.json());
  let target = res.find(t => t.type === "page") || res[0];
  let ws = await import("ws").catch(() => null);
  if (!ws) {
    // 退化用内置 WebSocket
  }
  const WebSocket = ws ? ws.WebSocket : (await import("ws")).WebSocket || global.WebSocket;
  const sock = new WebSocket(target.webSocketDebuggerUrl);

  let nextId = 1;
  const pending = new Map();
  sock.addEventListener("message", (evt) => {
    const msg = JSON.parse(evt.data);
    if (msg.id && pending.has(msg.id)) {
      const r = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) r.reject(msg.error);
      else r.resolve(msg.result);
    }
  });
  await new Promise((res2, rej2) => {
    sock.addEventListener("open", () => res2());
    sock.addEventListener("error", (e) => rej2(e));
  });

  function call(method, params = {}) {
    const id = nextId++;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      sock.send(JSON.stringify({ id, method, params }));
    });
  }

  await call("Page.enable");
  await call("Runtime.enable");

  for (const t of TARGETS) {
    const isAdmin = t.admin;
    const palette = t.palette || null;
    const dark = !!t.dark;

    // 1) 设置 cookie（admin 时设置 session，否则清空）
    await call("Network.enable");
    await call("Network.clearBrowserCookies");
    if (isAdmin) {
      await call("Network.setCookie", {
        domain: "127.0.0.1", path: "/", name: "session", value: ADMIN_SESSION,
        httpOnly: true, sameSite: "Lax",
      });
    }
    // 2) navigate
    const urlPart = t.p.replace(/^A:/, "");
    const url = BASE + urlPart;
    await call("Page.navigate", { url });
    // wait for load
    await new Promise((res2) => {
      const handler = (evt) => {
        const msg = JSON.parse(evt.data);
        if (msg.method === "Page.loadEventFired") {
          sock.removeEventListener("message", handler);
          res2();
        }
      };
      sock.addEventListener("message", handler);
      setTimeout(res2, 8000); // 兜底
    });
    await sleep(600);

    // 3) 应用 localStorage 偏好（访客模拟）
    if (!isAdmin) {
      if (palette) {
        await call("Runtime.evaluate", {
          expression: `localStorage.setItem('wb-palette', '${palette}'); location.reload();`,
        });
        await new Promise((res2) => {
          const handler = (evt) => {
            const msg = JSON.parse(evt.data);
            if (msg.method === "Page.loadEventFired") {
              sock.removeEventListener("message", handler);
              res2();
            }
          };
          sock.addEventListener("message", handler);
          setTimeout(res2, 6000);
        });
        await sleep(700);
      }
      if (dark) {
        await call("Runtime.evaluate", {
          expression: `localStorage.setItem('wb-theme', 'dark');`,
        });
      }
    }

    // 4) splash 跳过
    if (t.splash) {
      await call("Runtime.evaluate", {
        expression: `try { localStorage.setItem('wb-splash-seen', JSON.stringify({ts: Date.now()})); } catch (e) {}`,
      });
    }

    // 5) 触发 actions
    if (t.actions && t.actions.includes("openPalettePicker")) {
      await sleep(300);
      await call("Runtime.evaluate", {
        expression: `document.getElementById('paletteToggle')?.click();`,
      });
      await sleep(400);
    }

    // 6) 等 css 应用
    await sleep(900);

    // 7) 截图
    const layout = t.fullPage ? { captureBeyondViewport: true, width: 1440, height: 2000 }
                              : { captureBeyondViewport: false };
    const shot = await call("Page.captureScreenshot", {
      format: "png",
      ...layout,
    });
    const file = path.join(OUT_DIR, t.name + ".png");
    fs.writeFileSync(file, Buffer.from(shot.data, "base64"));
    console.log("✓", file);
  }

  sock.close();
  try { edge.kill("SIGTERM"); } catch (e) {}
  setTimeout(() => process.exit(0), 200);
}

main().catch((e) => { console.error(e); process.exit(1); });
