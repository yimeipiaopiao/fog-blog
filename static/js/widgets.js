/* 侧栏小部件：免费天气（后端代理）+ 时间倒计时 */
(function () {
  var ICONS = {
    thunder: "⛈️", rain: "🌧️", drizzle: "🌦️", snow: "❄️", sleet: "🌨️",
    fog: "🌫️", mist: "🌫️", haze: "🌫️", cloud: "☁️", overcast: "☁️",
    partly: "⛅", sunny: "☀️", clear: "☀️", windy: "💨"
  };
  function iconFor(en) {
    var t = (en || "").toLowerCase();
    if (t.indexOf("thunder") >= 0 || t.indexOf("storm") >= 0) return ICONS.thunder;
    if (t.indexOf("snow") >= 0 || t.indexOf("sleet") >= 0) return t.indexOf("sleet") >= 0 ? ICONS.sleet : ICONS.snow;
    if (t.indexOf("drizzle") >= 0) return ICONS.drizzle;
    if (t.indexOf("rain") >= 0) return ICONS.rain;
    if (t.indexOf("fog") >= 0 || t.indexOf("mist") >= 0 || t.indexOf("haze") >= 0) return ICONS.fog;
    if (t.indexOf("overcast") >= 0 || (t.indexOf("cloud") >= 0 && t.indexOf("part") < 0)) return ICONS.overcast;
    if (t.indexOf("part") >= 0 && t.indexOf("cloud") >= 0) return ICONS.partly;
    if (t.indexOf("wind") >= 0) return ICONS.windy;
    if (t.indexOf("sun") >= 0 || t.indexOf("clear") >= 0) return ICONS.sunny;
    return "🌤️";
  }
  var TXT = {
    thunder: "雷雨", rain: "雨", drizzle: "小雨", snow: "雪", sleet: "雨夹雪",
    fog: "雾", mist: "雾", haze: "霾", cloud: "多云", overcast: "阴",
    partly: "多云间晴", sunny: "晴", clear: "晴", windy: "大风"
  };
  function textFor(en) {
    var t = (en || "").toLowerCase();
    for (var k in TXT) {
      if (t.indexOf(k) >= 0 && (k !== "cloud" || (t.indexOf("part") < 0 && t.indexOf("overcast") < 0))) return TXT[k];
    }
    if (t.indexOf("part") >= 0) return "多云";
    return en || "";
  }

  var card = document.getElementById("weatherCard");
  if (card) {
    function render(wx) {
      var city = document.getElementById("wxCity");
      var body = document.getElementById("wxBody");
      if (!wx || !wx.ok) {
        city.textContent = "暂不可用";
        body.innerHTML = '<p class="wx-err">天气服务暂不可用（可后台配置默认城市）</p>';
        return;
      }
      city.textContent = wx.city || "";
      var hum = wx.humidity ? " · 湿度 " + wx.humidity + "%" : "";
      var wind = wx.wind ? " · 风力 " + wx.wind + "km/h" : "";
      body.innerHTML =
        '<div class="wx-body-row">' +
        '<span class="wx-icon">' + iconFor(wx.text_en) + "</span>" +
        '<span class="wx-temp">' + (wx.temp != null ? wx.temp + "°" : "--") + "</span>" +
        '<span class="wx-info">' + textFor(wx.text_en) + hum + wind + "</span>" +
        "</div>" +
        '<p class="wx-refresh">自动每 30 分钟更新 · 数据来源免费接口</p>';
    }
    function load() {
      fetch("/api/weather", { headers: { "Accept": "application/json" } })
        .then(function (r) { return r.json(); })
        .then(render)
        .catch(function () {
          var city = document.getElementById("wxCity");
          var body = document.getElementById("wxBody");
          if (city) city.textContent = "暂不可用";
          if (body) body.innerHTML = '<p class="wx-err">天气加载失败</p>';
        });
    }
    load();
    setInterval(load, 30 * 60 * 1000);
  }

  // ---------- 倒计时 ----------
  var cdToday = document.getElementById("cdToday");
  var cdMonth = document.getElementById("cdMonth");
  var cdYear = document.getElementById("cdYear");
  if (cdToday && cdMonth && cdYear) {
    function fmtHm(ms) {
      if (ms <= 0) return "已结束";
      var totalMin = Math.floor(ms / 60000);
      if (totalMin < 60) return totalMin + " 分钟";
      var h = Math.floor(totalMin / 60), m = totalMin % 60;
      return (m ? h + " 小时 " + m + " 分" : h + " 小时");
    }
    function fmtDH(ms) {
      if (ms <= 0) return "已结束";
      var totalH = Math.floor(ms / 3600000);
      if (totalH < 48) return fmtHm(ms);
      var d = Math.floor(totalH / 24), h = totalH % 24;
      return (h ? d + " 天 " + h + " 小时" : d + " 天");
    }
    function tick() {
      var now = new Date();
      var eod = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
      var eom = new Date(now.getFullYear(), now.getMonth() + 1, 1);
      var eoy = new Date(now.getFullYear() + 1, 0, 1);
      cdToday.textContent = fmtHm(eod - now);
      cdMonth.textContent = fmtDH(eom - now);
      cdYear.textContent = fmtDH(eoy - now);
    }
    tick();
    setInterval(tick, 30000);
  }

  // ---------- 访客自选配色（5 套毛玻璃主题） ----------
  (function () {
    var wrap = document.getElementById("paletteWrap");
    if (!wrap) return;
    var btn = document.getElementById("paletteToggle");
    var picker = document.getElementById("palettePicker");
    var reset = document.getElementById("paletteReset");
    if (!btn || !picker) return;

    function defPalette() {
      return document.documentElement.getAttribute("data-default-palette") || "amber";
    }
    function currentPalette() {
      return document.documentElement.getAttribute("data-palette") || defPalette();
    }
    function applyPalette(v, persist) {
      document.documentElement.setAttribute("data-palette", v);
      // 高亮当前选项
      var opts = picker.querySelectorAll("[data-palette]");
      for (var i = 0; i < opts.length; i++) {
        var on = opts[i].getAttribute("data-palette") === v;
        opts[i].classList.toggle("is-active", on);
      }
      if (persist) {
        try { localStorage.setItem("wb-palette", v); } catch (e) {}
      }
    }
    function close() { picker.hidden = true; }
    function toggle() { picker.hidden = !picker.hidden; }

    // 初始化高亮
    applyPalette(currentPalette(), false);

    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      toggle();
    });
    // 选色
    var opts = picker.querySelectorAll("[data-palette]");
    for (var i = 0; i < opts.length; i++) {
      opts[i].addEventListener("click", function (ev) {
        var v = ev.currentTarget.getAttribute("data-palette");
        applyPalette(v, true);
        close();
      });
    }
    // 恢复默认
    if (reset) {
      reset.addEventListener("click", function () {
        try { localStorage.removeItem("wb-palette"); } catch (e) {}
        applyPalette(defPalette(), false);
        close();
      });
    }
    // 点外部 / Esc 关闭
    document.addEventListener("click", function (e) {
      if (picker.hidden) return;
      if (!wrap.contains(e.target)) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !picker.hidden) close();
    });
  })();
})();
