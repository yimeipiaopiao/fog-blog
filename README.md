# 雾里博客 · 毛玻璃风格轻量博客

基于 **Flask + SQLite** 的轻量博客系统，前台采用半透明毛玻璃（Glassmorphism）设计，自带完整管理后台。零外部 CDN 依赖、单文件数据库、原生 HTML/CSS/JS，2G 内存小服务器即可流畅运行。

## 功能一览

| 模块 | 功能 |
| --- | --- |
| 内容创作 | Markdown / HTML 双模式编辑器（可互转）、行内预览 / 分屏 / 全屏、撤销重做、字数统计、目录（TOC）、emoji 面板、定时发布、文章置顶 |
| 文件系统 | 集中文件库（图片 / 文档 / 视频 / 音频 / 压缩包，≤ 200MB）、编辑器内拖拽 / 粘贴上传、文章直接引用 `/uploads/<kind>/<file>` |
| 内容管理 | 分类、标签、时间归档、独立页面、友情链接、自定义导航 |
| 互动评论 | 自建评论 + 审核、游客免注册评论（**按 IP 自动派生稳定昵称**）、浏览统计（session 去重）、点赞、留言板、文章级评论开关 |
| 用户系统 | 默认仅管理员（前台注册默认关闭），游客可直接评论；后台账号管理（启用 / 停用 / 重置密码 / 删除） |
| 主题体验 | 5 套毛玻璃配色（amber / sea / mint / grape / rose，浅深双调）、前台访客自选配色、深色模式（手动 / 定时 / 跟随系统） |
| PDF 阅读 | **PDF 转文章**：上传 PDF 即可生成文章页，前台用内置 PDF.js **无感连续滚动阅读**（保留原版式、加载进度、逐页淡入、单页重试、懒渲染，百页大 PDF 不卡）；或提取文字转为 Markdown 草稿 |
| 侧栏组件 | 博主信息卡、每日一句、免费天气（IP 定位，无需 API Key）、人生倒计时 |
| 搜索与 SEO | 全文搜索、RSS、sitemap.xml、robots.txt、相关文章、代码高亮 |
| 系统管理 | 仪表板、站点设置、操作日志（自动清理）、数据备份（下载 DB + JSON 导出） |

## 快速开始（5 分钟跑起来）

要求：Python 3.9+，无需数据库服务（SQLite 单文件）。

```bash
# 1. 克隆并进入
git clone https://github.com/<你的用户名>/<仓库名>.git
cd <仓库名>

# 2. 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. 初始化演示数据（建库 + 分类/标签 + 3 篇演示文章 + 默认管理员）
python seed.py

# 4. 启动
python app.py                     # 或 flask --app app run --debug

# 浏览器打开
#   前台 http://127.0.0.1:5000
#   后台 http://127.0.0.1:5000/admin
```

**默认管理员**：`admin / admin123` —— **上线前请务必在后台「账号」里修改密码！**

> 不想用演示数据？手动初始化：
> ```bash
> flask --app app init-db                    # 建库
> flask --app app create-user admin 你的密码  # 建管理员
> ```

## 目录结构

```
blog/
├── app.py            # 应用入口（flask / gunicorn 启动，含 CLI 命令）
├── config.py         # 配置（数据库、上传限制、站点默认设置）
├── models.py         # 数据模型
├── utils.py          # Markdown 渲染、CSRF、登录、分页、孤儿数据清理等
├── routes/
│   ├── main.py       # 前台页面 + RSS / sitemap / robots
│   ├── auth.py       # 后台管理员登录 / 登出
│   ├── admin.py      # 后台管理（文章/分类/评论/文件库/账号/日志/设置/PDF 转文章）
│   └── api.py        # 评论 / 点赞 / 上传 / 天气等接口
├── templates/        # 前台 + 后台 + 用户中心模板（Jinja2）
├── static/
│   ├── css/          # style.css / theme.css / palette.css / admin.css
│   ├── js/           # editor.js / theme.js / widgets.js
│   └── vendor/       # 本地化第三方库：marked / turndown / highlight.js / pdf.js（无 CDN）
├── deploy/           # Ubuntu 一键部署包（install.sh + systemd + Nginx）
├── uploads/          # 上传文件（运行时生成，按类型分子目录）
├── backup/           # 数据库备份目录（运行时自动创建）
├── blog.db           # SQLite 数据库（首次初始化生成，不入库）
├── seed.py           # 演示数据脚本
├── smoke.py          # HTTP 冒烟测试
└── e2e_features.py   # 端到端回归测试
```

## Ubuntu 服务器部署

> **推荐使用自带的一键部署包**，详见 [`deploy/README.md`](deploy/README.md)：
> ```bash
> git clone <你的仓库地址> /var/www/blog
> cd /var/www/blog
> sudo bash deploy/install.sh    # 自动：venv + 依赖 + 随机 SECRET_KEY + systemd + Nginx
> ```

部署目标：Ubuntu 20.04+（腾讯云 / 阿里云等标准云服务器均可），Nginx 反代 + Gunicorn + systemd，占用内存 < 150MB。

### 手动部署要点

```bash
# 1. 安装系统依赖
apt update && apt install -y python3 python3-venv python3-pip nginx git

# 2. 安装项目依赖
cd /var/www/blog
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. 初始化 + 建管理员（不要用默认密码！）
flask --app app init-db
flask --app app create-user admin 你的强密码

# 4. 设置随机密钥（务必执行，否则 session 不安全）
python3 -c "import secrets; print('BLOG_SECRET_KEY=' + secrets.token_hex(32))"
# 输出写入 systemd 服务文件的 Environment= 行

# 5. 配置 systemd 服务 + Nginx 反代（见 deploy/blog.service 与 deploy/nginx.conf）
# 6. 申请 HTTPS（certbot --nginx 或云厂商免费证书）
```

常用维护：

```bash
systemctl restart blog                          # 重启
journalctl -u blog -f                           # 看日志
cd /var/www/blog && git pull && systemctl restart blog   # 更新
flask --app app create-user 新用户 密码          # 加管理员
```

### HTTPS：后台上传 SSL 证书（宝塔式，上传即生效）

后台「SSL 证书」页支持像宝塔面板一样粘贴证书与私钥，自动校验并生效，无需登录服务器：

1. 用任意方式取得证书（`certbot --nginx -d 你的域名`、云厂商免费证书、商业证书均可），下载 **nginx 格式**的 `fullchain.pem`（含中间证书）与 `privkey.pem`。
2. 登录后台 → 侧栏「SSL 证书」→「上传 / 更新证书」，粘贴域名 + 证书 + 私钥，点「校验并生效」。
3. 后端自动完成：PEM 解析 → **证书与私钥配对校验** → **域名必须在证书 SAN/CN 内** → 有效期检查 → 写入 `/etc/nginx/ssl/<域名>/` → 生成 HTTPS server block → `nginx -t` → 自动 reload。任一步失败都不写盘（事务式），旧证书自动备份在 `/etc/nginx/ssl/<域名>/.backup/`。

- 停用：状态页「停用 HTTPS」即回退 HTTP（证书文件保留）。
- 更新：再传一份新证书即覆盖旧配置；历史记录保留最近 20 条，过期前 30 天状态页会提示。
- 依赖 `deploy/install.sh` 部署的 sudo 白名单 wrapper（`/usr/local/bin/blog-ssl-apply`，仅 www-data 可经 sudo 执行，且只允许写 `/etc/nginx/ssl/` 与 reload nginx），私钥通过 stdin 传入、不落命令行。
- 本地开发 / CI 无 wrapper 时，设置 `BLOG_SSL_DRY_RUN=1` 即只做解析与校验、不写盘（e2e 测试即此模式）。

## 常见问题

**Q: 评论为什么不显示？**
后台「设置」开启审核后，新评论需在后台「评论管理」点击「通过」。管理员评论直接显示。

**Q: 定时发布怎么生效？**
发布时选择「定时发布」并设置未来时间，任意页面请求会自动触发发布，无需额外任务调度。

**Q: 前台注册能不能开？**
本系统不开放前台注册：仅「后台账号」一种身份，游客免登录即可评论（昵称按 IP 自动派生，可自行修改，邮箱选填）。

**Q: 访客昵称是怎么生成的？**
根据访客 IP + `SECRET_KEY` 做 md5 哈希派生稳定昵称（同一 IP 始终同名），加盐保证无法反推 IP。可手动改。

**Q: PDF 转文章两种模式区别？**
- **在线阅读（推荐）**：保留原版式（图片 / 表格 / 排版 100% 保真），前台 PDF.js 浏览器端渲染，服务器零压力，扫描版 PDF 也支持。
- **转文字草稿**：pypdf 提取文字成 Markdown 草稿，可完全编辑（图表排版会丢失）。

**Q: 几百页的大 PDF 会卡吗？**
不会。PDF 阅读采用 IntersectionObserver 懒渲染，首屏只渲染可见页 + 800px 预渲染，30+ 页相比全量渲染首屏提速约 70%。

**Q: 侧栏天气需要 API Key 吗？**
不需要。后端代理调用 `api.ip.sb` → `ip-api.com` → `wttr.in` 免费接口，IP 定位 + 城市内存缓存。内网环境无法定位时可后台设置「天气默认城市」。

**Q: 深色模式怎么配置？**
后台「站点设置 → 主题」：默认外观、自动切换（关闭 / 定时 / 跟随系统）、时段、正文深色字自动反色。

**Q: 忘记管理员密码？**
```bash
flask --app app create-user admin 新密码   # 已存在则提示，可先删后建
```

**Q: 数据备份与恢复？**
后台「备份与导出」可下载 SQLite 数据库文件。恢复：停服务 → 替换 blog.db → 启动。

**Q: 换主色调？**
后台「站点设置 → 外观配色」下拉切换 5 套配色（amber 默认）。定义在 `static/css/palette.css`，可复制 block 自定义。访客也可在前台导航「调色板」按钮自选（存 localStorage，不影响他人）。

**Q: 想要动漫壁纸做博客背景（毛玻璃透出背景图）？**
后台「站点设置 → 自定义背景图」：粘贴图片 URL 或点「上传图片」直接传本地壁纸（jpg/png/webp/gif），再用滑杆调背景图透明度（5-100%，默认 45）。保存后前台全屏铺图：文章卡片 / 导航 / 页脚仍是毛玻璃，背景图从玻璃后透出；越淡越素净利阅读、越浓玻璃透出的图越明显。留空即恢复默认渐变底 + 漂浮光斑。设置项：`site_bg_image` / `site_bg_opacity`。

## 技术栈

Flask 3 · Flask-SQLAlchemy · SQLite · python-markdown · Gunicorn · Nginx · 原生 HTML/CSS/JS · marked.js · Turndown.js · highlight.js · PDF.js

## 测试

```bash
# HTTP 冒烟测试（需服务已启动，默认 127.0.0.1:5000）
python smoke.py

# 端到端回归（独立临时库，零污染，覆盖注册/评论/日志/深色/配色/PDF 等 100+ 断言）
python e2e_features.py
```

## 开源说明

- 数据文件（`blog.db` / `uploads/` / `shots/` / `backup/`）默认被 `.gitignore` 排除，**不会进入版本库**，clone 后首次运行 `seed.py` 自动生成。
- 生产密钥通过环境变量 `BLOG_SECRET_KEY` 注入，代码内无任何硬编码密钥。
- 第三方库已全部本地化到 `static/vendor/`（无 CDN 依赖，适合国内服务器部署）。
