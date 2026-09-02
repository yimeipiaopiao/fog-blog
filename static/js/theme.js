/* 深色模式：手动切换 / 时段与系统自动 / 高亮主题联动 / 正文深色字反色修复 */
(function () {
  var T = window.WB_THEME || { def: "light", auto: "off", start: 19, end: 7, fix: "0" };
  var root = document.documentElement;

  function isDarkHour() {
    var h = new Date().getHours(), s = Number(T.start), e = Number(T.end);
    if (s === e) return false;
    return (s < e) ? (h >= s && h < e) : (h >= s || h < e);
  }

  function effective() {
    var f = localStorage.getItem("wb-theme");
    if (f === "light" || f === "dark") return f;
    if (T.auto === "system") {
      try { if (window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches) return "dark"; } catch (e) {}
    } else if (T.auto === "schedule" && isDarkHour()) return "dark";
    return T.def === "dark" ? "dark" : "light";
  }

  function apply() {
    var dark = effective() === "dark";
    root.setAttribute("data-theme", dark ? "dark" : "light");
    // highlight.js 深浅主题联动
    var light = document.getElementById("hljsLight");
    var darkSheet = document.getElementById("hljsDark");
    if (light) light.disabled = dark;
    if (darkSheet) darkSheet.disabled = !dark;
    fixContentColors(dark);
    var btn = document.getElementById("themeToggle");
    if (btn) {
      var f = localStorage.getItem("wb-theme") || "auto";
      root.setAttribute("data-user", f);
      var nxt = plannedNext();
      btn.title = nxt === "dark" ? "当前浅色，点击切换深色" :
                  nxt === "light" ? "当前深色，点击切换浅色" :
                  "恢复自动（跟随系统/时段）";
    }
  }

  /* 反色修复：正文里「写死成深色」的内联文字，深色下自动提亮 */
  function luminance(rgb) {
    var c = rgb.map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  }
  function parseColor(str) {
    var m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(str || "");
    if (m) return [+m[1], +m[2], +m[3]];
    var h = /^#([0-9a-f]{6})$/i.exec((str || "").trim());
    if (h) { var n = parseInt(h[1], 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
    return null;
  }
  function fixContentColors(dark) {
    var targets = document.querySelectorAll(".post-content *, .page-content *");
    if (!dark || T.fix !== "1") {
      // 回到浅色/关闭修复：还原被改过的内联颜色
      for (var r = 0; r < targets.length; r++) {
        if (targets[r].dataset && targets[r].dataset.wbOrig) {
          targets[r].style.color = targets[r].dataset.wbOrig;
          delete targets[r].dataset.wbOrig;
        }
      }
      return;
    }
    for (var i = 0; i < targets.length; i++) {
      var el = targets[i];
      var cs = el.style && el.style.color;
      if (!cs) continue;
      var rgb = parseColor(cs);
      if (rgb && luminance(rgb) < 0.45 && !el.dataset.wbOrig) {
        el.dataset.wbOrig = cs;
        el.style.color = "#eadfcb";
      }
    }
  }

  /* 模拟“自动”档位的视觉，用于判断手动档切回自动时是否会产生无变化点击 */
  function autoVisual() {
    var had = localStorage.getItem("wb-theme");
    localStorage.removeItem("wb-theme");
    var v = effective();
    if (had) localStorage.setItem("wb-theme", had);
    return v;
  }

  /* 计算下一次点击应该切换到的档位，保证每点一次视觉必变：
     - 手动浅色 → 深色
     - 手动深色 → 自动；若自动档视觉仍是深色（时段/系统在夜间），则直接回浅色
     - 自动档    → 切到与当前视觉相反的档位（原来自动→浅色会造成“点了没反应”） */
  function plannedNext() {
    var f = localStorage.getItem("wb-theme");
    var cur = effective();
    if (f === "light") return "dark";
    if (f === "dark") return autoVisual() === "dark" ? "light" : "auto";
    return cur === "dark" ? "light" : "dark";
  }

  function toggle() {
    var next = plannedNext();
    if (next === "auto") localStorage.removeItem("wb-theme"); else localStorage.setItem("wb-theme", next);
    apply();
  }

  var btn = document.getElementById("themeToggle");
  if (btn) btn.addEventListener("click", toggle);

  // 跟随系统时监听系统外观变化
  if (T.auto === "system" && window.matchMedia) {
    try {
      matchMedia("(prefers-color-scheme: dark)").addEventListener("change", apply);
    } catch (e) {}
  }

  // 个人中心头像下拉菜单
  var chip = document.getElementById("userChip");
  var menu = document.getElementById("userMenu");
  if (chip && menu) {
    var cbtn = chip.querySelector(".user-chip-btn");
    cbtn.addEventListener("click", function (e) {
      e.stopPropagation();
      var open = menu.hidden;
      menu.hidden = !open;
      cbtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("click", function (e) {
      if (!chip.contains(e.target)) { menu.hidden = true; cbtn.setAttribute("aria-expanded", "false"); }
    });
  }

  apply();
})();
