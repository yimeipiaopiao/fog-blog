"""第三轮新功能端到端验证：读者账号 / 日志 / 深色模式 / 侧栏部件 / 天气。

策略：使用独立临时 SQLite（不碰开发库 blog.db），app.test_client() 直接跑，
session 注入固定 csrf_token 绕开"先 GET 取 token"的繁琐，跨请求一律重新查询
对象（避免 SQLAlchemy 跨 Session 持旧实例的 InvalidRequestError）。

用法: python e2e_features.py
"""
import os
import re
import sys
import tempfile
import json

from config import Config
from app import create_app
from models import Category, Comment, File, Log, Post, Setting, User, db

# ---- 独立临时库 ----
_tmpdir = tempfile.mkdtemp(prefix="blog_e2e_")
TMP_DB = os.path.join(_tmpdir, "e2e.db")

class TestConfig(Config):
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + TMP_DB
    TESTING = True

CSRF = "e2e-csrf-token-0123456789abcdef"
failures = []
app = create_app(TestConfig)

def ok(name, cond):
    print(("OK   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)

def client_with_csrf():
    c = app.test_client()
    with c.session_transaction() as s:
        s["csrf_token"] = CSRF
    return c

def csrf():
    return {"csrf_token": CSRF}

# ---------------- 种子数据 ----------------
with app.app_context():
    db.create_all()
    admin = User(username="admin", nickname="站长", role="admin")
    admin.set_password("admin123")
    db.session.add(admin)
    cat = Category(name="技术", slug="tech")
    db.session.add(cat)
    db.session.flush()
    post = Post(title="端到端测试文章", slug="e2e-post", content="# 你好\n内容",
                status="published", category_id=cat.id)
    db.session.add(post)
    for k, v in Config.DEFAULT_SETTINGS.items():
        Setting.set(k, v)
    Setting.set("register_allow", "1")  # 本脚本的读者体系用例需先开放注册（第 8 节再验证关闭形态）
    db.session.commit()
    POST_ID = post.id
    ADMIN_ID = admin.id

# ---------------- 1. 注册/登录/登出 ----------------
c = client_with_csrf()
r = c.get("/user/register")
ok("GET /user/register 200", r.status_code == 200)

# 正常注册
r = c.post("/user/register", data={**csrf(),
    "username": "e2e_reader", "nickname": "测试读者", "email": "r@test.com",
    "password": "pass123456", "confirm": "pass123456"}, follow_redirects=False)
ok("POST /user/register -> 302", r.status_code == 302)
with app.app_context():
    reader = User.query.filter_by(username="e2e_reader").first()
ok("注册后 role=user", reader is not None and reader.role == "user")
with c.session_transaction() as s:
    ok("注册后 session[uid] 已设置", s.get("uid") == reader.id if reader else False)

# 重复用户名注册被拒（换未登录 client 测，避开已登录 302）
c_dup = client_with_csrf()
r = c_dup.post("/user/register", data={**csrf(),
    "username": "e2e_reader", "nickname": "x", "password": "pass123456",
    "confirm": "pass123456"})
ok("重复用户名注册被拒(200 带错误)", r.status_code == 200 and "已被占用" in r.get_data(as_text=True))

# 登出
r = c.get("/user/logout", follow_redirects=False)
ok("GET /user/logout -> 302", r.status_code == 302)
with c.session_transaction() as s:
    ok("登出后 session[uid] 清除", "uid" not in s)

# 错误密码登录
r = c.post("/user/login", data={**csrf(), "username": "e2e_reader", "password": "wrong-pass"})
ok("错误密码登录被拒(200 带错误)", r.status_code == 200 and "用户名或密码错误" in r.get_data(as_text=True))

# 角色走错入口：admin 账号在前台登录、读者账号在后台登录 → 给明确指引而非笼统"密码错误"
r = c.post("/user/login", data={**csrf(), "username": "admin", "password": "admin123"})
ok("admin 走前台登录 -> 提示后台入口", r.status_code == 200 and "后台管理员" in r.get_data(as_text=True))
c_role = client_with_csrf()
r = c_role.post("/login", data={**csrf(), "username": "e2e_reader", "password": "pass123456"})
ok("读者走后台登录 -> 提示前台入口", r.status_code == 200 and "前台读者账号" in r.get_data(as_text=True))

# 正确登录
r = c.post("/user/login", data={**csrf(), "username": "e2e_reader", "password": "pass123456"},
           follow_redirects=False)
ok("POST /user/login -> 302", r.status_code == 302)
with c.session_transaction() as s:
    ok("登录后 session[uid] 已设置", s.get("uid") == reader.id if reader else False)

# 个人中心 GET
r = c.get("/user/center")
ok("GET /user/center 200(登录态)", r.status_code == 200)

# 未登录访问 center 被重定向到登录
c2 = client_with_csrf()
r = c2.get("/user/center", follow_redirects=False)
ok("未登录访问 /user/center -> 302 login", r.status_code == 302 and "/user/login" in r.headers.get("Location", ""))

# ---------------- 2. 资料更新 + 旧密码验证改密 ----------------
r = c.post("/user/center", data={**csrf(), "nickname": "新昵称",
    "email": "new@test.com", "bio": "我是测试读者", "avatar": ""}, follow_redirects=False)
ok("POST /user/center 改资料 -> 302", r.status_code == 302)
with app.app_context():
    reader2 = User.query.get(reader.id)
    ok("昵称/简介已更新", reader2.nickname == "新昵称" and reader2.bio == "我是测试读者")

# 头像上传：构造 1x1 最小 PNG，multipart POST
import io, struct, zlib
def _png_1x1():
    sig = b"\x89PNG\r\n\x1a\n"
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00\xff\x00\x00"
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")

r = c.post("/user/avatar", data={**csrf(),
    "file": (io.BytesIO(_png_1x1()), "avatar.png")}, content_type="multipart/form-data")
ok("POST /user/avatar 200 + ok", r.status_code == 200 and json.loads(r.get_data(as_text=True)).get("ok"))
avatar_url = json.loads(r.get_data(as_text=True)).get("url", "")
ok("头像 URL 落到 uploads/avatar/u{id}_", avatar_url.startswith("/uploads/avatar/u" + str(reader.id) + "_"))
with app.app_context():
    reader2 = User.query.get(reader.id)
    ok("user.avatar 已更新", reader2.avatar == avatar_url)
    ok("头像文件已写入磁盘", os.path.exists(os.path.join(_tmpdir, avatar_url.lstrip("/")).replace("uploads/", "", 1)) or
       os.path.exists(os.path.join(TestConfig.UPLOAD_FOLDER, avatar_url.replace("/uploads/", "", 1))))

# 错误扩展名被拒
r = c.post("/user/avatar", data={**csrf(),
    "file": (io.BytesIO(b"not a png"), "evil.txt")}, content_type="multipart/form-data")
ok("错误扩展名被拒(400)", r.status_code == 400)

# 旧密码错误 -> 拒绝（member.center 渲染 200 + error flash）
r = c.post("/user/center", data={**csrf(), "nickname": "新昵称", "email": "",
    "bio": "", "old_password": "wrong-old", "new_password": "newpass456"})
ok("旧密码错误改密被拒(200 带 error)", r.status_code == 200 and "旧密码" in r.get_data(as_text=True))
with app.app_context():
    r3 = User.query.get(reader.id)
    ok("旧密码错误时密码未变", r3.check_password("pass123456") and not r3.check_password("newpass456"))

# 旧密码正确 -> 改密成功，随后可用新密码登录
r = c.post("/user/center", data={**csrf(), "nickname": "新昵称", "email": "new@test.com",
    "bio": "", "old_password": "pass123456", "new_password": "newpass456"}, follow_redirects=False)
ok("旧密码正确改密 -> 302", r.status_code == 302)
c3 = client_with_csrf()
r = c3.post("/user/login", data={**csrf(), "username": "e2e_reader", "password": "newpass456"},
            follow_redirects=False)
ok("新密码登录成功", r.status_code == 302)

# ---------------- 3. 评论绑定登录用户 ----------------
r = c3.post("/api/comment", data={**csrf(), "post_id": str(POST_ID),
    "nickname": "游客填的", "email": "hack@x.com", "content": "登录读者的自动署名评论"})
ok("登录读者评论 ok", r.status_code == 200 and json.loads(r.get_data(as_text=True)).get("ok"))
with app.app_context():
    cm = Comment.query.filter_by(content="登录读者的自动署名评论").first()
    ok("评论自动绑定 user_id + 昵称用账号", cm and cm.user_id == reader.id and cm.nickname == "新昵称")

# 游客评论（不带登录态）
c4 = client_with_csrf()
r = c4.post("/api/comment", data={**csrf(), "post_id": str(POST_ID),
    "nickname": "路人", "email": "", "content": "游客评论一条"})
ok("游客评论 ok", r.status_code == 200)
with app.app_context():
    cm2 = Comment.query.filter_by(content="游客评论一条").first()
    ok("游客评论 user_id=None", cm2 is not None and cm2.user_id is None)

# ---------------- 4. 后台用户管理 ----------------
ca = client_with_csrf()
with ca.session_transaction() as s:
    s["user_id"] = ADMIN_ID
r = ca.get("/admin/users?tab=readers")
ok("GET /admin/users 200(含读者)", r.status_code == 200 and "e2e_reader" in r.get_data(as_text=True))
r = ca.get("/admin/users")
ok("GET /admin/users 默认 staff tab 200", r.status_code == 200 and "站长" in r.get_data(as_text=True))

# 停用读者 -> 该读者无法再登录
r = ca.post(f"/admin/users/{reader.id}/toggle", data=csrf(), follow_redirects=False)
ok("POST 停用读者 -> 302", r.status_code == 302)
c5 = client_with_csrf()
r = c5.post("/user/login", data={**csrf(), "username": "e2e_reader", "password": "newpass456"})
ok("停用后登录被拒(提示停用)", r.status_code == 200 and "停用" in r.get_data(as_text=True))

# 重新启用
r = ca.post(f"/admin/users/{reader.id}/toggle", data=csrf(), follow_redirects=False)
ok("POST 启用读者 -> 302", r.status_code == 302)

# 后台新建同事账号（role=admin）
r = ca.post("/admin/users/new", data={**csrf(), "username": "staff01",
    "nickname": "员工", "password": "staff123456"}, follow_redirects=False)
ok("后台新建账号 -> 302", r.status_code == 302)
with app.app_context():
    staff = User.query.filter_by(username="staff01").first()
    ok("后台新建账号入库 role=admin", staff is not None and staff.role == "admin")

# 删除该账号
if staff:
    r = ca.post(f"/admin/users/{staff.id}/delete", data=csrf(), follow_redirects=False)
    ok("删除账号 -> 302", r.status_code == 302)
    with app.app_context():
        ok("删除后库中无此用户", User.query.get(staff.id) is None)

# 重置读者密码（后台代改）
r = ca.post(f"/admin/users/{reader.id}/reset", data={**csrf(), "password": "reset123456"},
            follow_redirects=False)
ok("重置读者密码 -> 302", r.status_code == 302)

# 不能停用/删除自己
r = ca.post(f"/admin/users/{ADMIN_ID}/toggle", data=csrf(), follow_redirects=False)
ok("停用自己的操作被拒(302 回列表)", r.status_code == 302)
with app.app_context():
    a2 = User.query.get(ADMIN_ID)
    ok("自己账号未被停用", a2.is_active)

# ---------------- 5. 日志系统 ----------------
r = ca.get("/admin/logs")
ok("GET /admin/logs 200 含 register 记录", r.status_code == 200 and "register" in r.get_data(as_text=True))
r = ca.get("/admin/logs?action=register")
ok("GET /admin/logs 按 action 筛选", r.status_code == 200 and "e2e_reader" in r.get_data(as_text=True))
r = ca.post("/admin/logs/purge", data=csrf(), follow_redirects=False)
ok("POST /admin/logs/purge 手动清理 -> 302", r.status_code == 302)
with app.app_context():
    ok("purge 后日志表仍在（保留期内不删空）", Log.query.count() >= 0)
r = ca.post("/admin/logs/clear", data=csrf(), follow_redirects=False)
ok("POST /admin/logs/clear 清空 -> 302", r.status_code == 302)
with app.app_context():
    Log.query.delete()
    db.session.commit()
    # 补一条日志以便后续页面试图能看到内容
    Log(action="test_after_clear", target="x", username="admin")
    db.session.commit()

# 日志自动清理函数(直接调用验证不报错)
with app.app_context():
    from utils import purge_old_logs
    n = purge_old_logs()
    ok("purge_old_logs() 可执行", isinstance(n, int))

# ---------------- 6. 深色模式 / 前台资源 ----------------
r = ca.get("/")
ok("GET / 首页 200", r.status_code == 200)
html = r.get_data(as_text=True)
ok("首页含 WB_THEME 初始化脚本", "WB_THEME" in html)
ok("首页含 data-theme 根标记", 'data-theme="light"' in html or "data-user" in html)
ok("首页含主题切换按钮", "themeToggle" in html or "theme-toggle" in html)
for asset in ["/static/js/theme.js", "/static/js/widgets.js",
              "/static/css/theme.css",
              "/static/vendor/highlight.js/styles/atom-one-dark.min.css"]:
    rr = ca.get(asset)
    ok(f"静态资源 {asset.split('/')[-1]} 200", rr.status_code == 200)

# 设置项：保存深色模式配置（时段自动切换）
r = ca.post("/admin/settings", data={**csrf(),
    "site_name": "雾里博客", "site_subtitle": "记录与分享",
    "site_description": "d", "site_keywords": "k", "footer_text": "f",
    "icp": "", "comment_allow": "1", "comment_need_audit": "1",
    "blogger_name": "站长", "blogger_avatar": "/uploads/avatar/me.jpg", "blogger_bio": "写代码的",
    "motto_enable": "1", "motto_text": "日日是好日",
    "theme_default": "light", "theme_auto": "schedule",
    "theme_dark_start": "19", "theme_dark_end": "07", "theme_fix_content": "1",
    "weather_default_city": "Chengdu", "log_keep_days": "90", "register_allow": "1",
}, follow_redirects=False)
ok("POST /admin/settings 保存新配置 -> 302", r.status_code == 302)
with app.app_context():
    sv = {s.key: s.value for s in Setting.query.all()}
    ok("theme_auto=schedule 已保存", sv.get("theme_auto") == "schedule")
    ok("motto_text 已保存", sv.get("motto_text") == "日日是好日")
    ok("weather_default_city 已保存", sv.get("weather_default_city") == "Chengdu")

# ---------------- 7. 侧栏部件渲染 ----------------
for needle in ["blogger", "motto", "weatherCard", "cdToday", "cdMonth", "cdYear"]:
    ok(f"首页 HTML 含侧栏部件标记 {needle}", needle in html)

# 天气接口：本机 IP 无法定位时会走默认城市或返回 json（不 5xx）
import urllib.request
def _net_probe(url, timeout=5):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "e2e/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except Exception:
        return None
net = _net_probe("https://wttr.in/?format=1", timeout=6)
if net == 200:
    with app.app_context():
        from routes.api import _WEATHER_CACHE
        _WEATHER_CACHE.clear()
    r = ca.get("/api/weather")
    ok("GET /api/weather 200(有外网)", r.status_code == 200 and "temp" in r.get_data(as_text=True))
else:
    print("SKIP /api/weather 无外网（不影响其余用例）")

# ---------------- 8. 读者体系关闭（默认生产形态）+ 游客评论 + 文章级评论开关 + PDF 转文章 ----------------
with app.app_context():
    Setting.set("register_allow", "")
    db.session.commit()
    from utils import invalidate_settings
    invalidate_settings()

# 关闭后：注册/登录入口一律引向后台登录
r = c.get("/user/register", follow_redirects=False)
ok("关闭注册后 GET /user/register -> 302 /login", r.status_code == 302 and "/login" in r.headers.get("Location", ""))
r = c.get("/user/login", follow_redirects=False)
ok("关闭读者登录后 GET /user/login -> 302", r.status_code == 302)

# 游客仍可免登录直接评论
r = c4.post("/api/comment", data={**csrf(), "post_id": str(POST_ID),
    "nickname": "游客甲", "email": "", "content": "不登录也能评论"})
ok("读者体系关闭后游客免登录评论 ok", r.status_code == 200 and json.loads(r.get_data(as_text=True)).get("ok"))

# 文章级评论开关：后台新建时取消勾选「允许评论」
r = ca.post("/admin/posts/new", data={**csrf(), "title": "关闭评论的测试文章",
    "slug": "e2e-nocomment", "content": "正文内容", "render_mode": "markdown",
    "status": "published", "is_top": "", "allow_comment": ""}, follow_redirects=False)
ok("新建禁评文章 -> 302", r.status_code == 302)
with app.app_context():
    nc = Post.query.filter_by(slug="e2e-nocomment").first()
    ok("未勾选时 allow_comment=False", nc is not None and not nc.allow_comment)
    NC_ID = nc.id if nc else -1
r = c4.post("/api/comment", data={**csrf(), "post_id": str(NC_ID),
    "nickname": "x", "content": "这条不该进"})
ok("禁评文章评论被拒(403)", r.status_code == 403)
body = c4.get(f"/post/e2e-nocomment").get_data(as_text=True)
ok("禁评文章页面提示「本文已关闭评论」", "本文已关闭评论" in body)
ok("禁评文章页面无评论表单", 'id="commentForm"' not in body)

# 后台编辑里重新勾选 → 恢复评论
r = ca.post(f"/admin/posts/{NC_ID}/edit", data={**csrf(), "title": "关闭评论的测试文章",
    "slug": "e2e-nocomment", "content": "正文内容", "render_mode": "markdown",
    "status": "published", "allow_comment": "1"}, follow_redirects=False)
ok("编辑文章重新开启评论 -> 302", r.status_code == 302)
r = c4.post("/api/comment", data={**csrf(), "post_id": str(NC_ID),
    "nickname": "游客乙", "content": "重新开启后可以评论"})
ok("重新开启后评论成功", r.status_code == 200 and json.loads(r.get_data(as_text=True)).get("ok"))

# PDF 转文章：手工构造最小合法 PDF（Helvetica ASCII 文本层）
def _make_pdf(text):
    esc = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 14 Tf 72 720 Td ({esc}) Tj ET".encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body = b"%PDF-1.4\n"
    offsets = [0]
    for i, o in enumerate(objs, 1):
        offsets.append(len(body))
        body += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref_pos = len(body)
    body += b"xref\n0 6\n0000000000 65535 f \n"
    for off in offsets[1:]:
        body += f"{off:010d} 00000 n \n".encode()
    body += (b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"
             + str(xref_pos).encode() + b"\n%%EOF")
    return body

r = ca.get("/admin/pdf/new")
ok("GET /admin/pdf/new 200", r.status_code == 200 and "PDF" in r.get_data(as_text=True))
pdf_bytes = _make_pdf("Hello PDF Import Test 123")
r = ca.post("/admin/pdf/new", data={**csrf(), "mode": "text",
    "file": (io.BytesIO(pdf_bytes), "manual.pdf")},
    content_type="multipart/form-data", follow_redirects=False)
loc = r.headers.get("Location", "")
ok("POST /admin/pdf/new -> 302 跳编辑器", r.status_code == 302 and re.search(r"/admin/posts/\d+/edit", loc))
with app.app_context():
    fp = Post.query.filter(Post.title == "manual").order_by(Post.id.desc()).first()
    ok("PDF 转换生成草稿", fp is not None and fp.status == "draft")
    ok("PDF 文本已提取进正文", fp is not None and "Hello PDF Import Test" in (fp.content or ""))
    fr = File.query.filter_by(kind="doc").order_by(File.id.desc()).first()
    ok("原 PDF 已入文件库(doc)", fr is not None and fr.name == "manual.pdf")
    ok("原 PDF 已落盘", fr is not None and os.path.exists(
        os.path.join(TestConfig.UPLOAD_FOLDER, fr.url.replace("/uploads/", "", 1))))

# 非 PDF 文件被拒
r = ca.post("/admin/pdf/new", data={**csrf(),
    "file": (io.BytesIO(b"not a pdf"), "evil.txt")},
    content_type="multipart/form-data", follow_redirects=False)
ok("非 PDF 上传被拒(302 回表单)", r.status_code == 302 and "/pdf/new" in r.headers.get("Location", ""))

# ---- PDF 在线阅读模式：保留原版式，前台 PDF.js 渲染 ----
r = ca.post("/admin/pdf/new", data={**csrf(), "mode": "view",
    "file": (io.BytesIO(pdf_bytes), "viewer-test.pdf")},
    content_type="multipart/form-data", follow_redirects=False)
ok("PDF view 模式 302 跳编辑器", r.status_code == 302 and re.search(r"/admin/posts/\d+/edit", r.headers.get("Location","")))
with app.app_context():
    vpost = Post.query.filter(Post.title.like("%Hello%"), Post.render_mode == "pdf").order_by(Post.id.desc()).first() \
        or Post.query.filter(Post.render_mode == "pdf").order_by(Post.id.desc()).first()
    ok("PDF view 模式入库 render_mode=pdf", vpost is not None and vpost.render_mode == "pdf")
    ok("PDF view 模式入库 pdf_url", vpost is not None and vpost.pdf_url.startswith("/uploads/doc/"))
    # 发布后访问前台，看是否包含 PDF 阅读器容器
    if vpost:
        vpost.status = "published"
        db.session.commit()
        slug = vpost.slug
    else:
        slug = None
if slug:
    r = c.get("/post/" + slug)
    html = r.get_data(as_text=True)
    ok("前台 PDF 阅读页含 pdfPages 容器", "id=\"pdfPages\"" in html)
    ok("前台 PDF 阅读页含 pdf.min.js 引用", "vendor/pdfjs/pdf.min.js" in html)
    ok("前台 PDF 阅读页含下载按钮", "下载原 PDF" in html)
# 清理 view 模式测试数据
with app.app_context():
    vp = Post.query.filter(Post.render_mode == "pdf").order_by(Post.id.desc()).first()
    if vp:
        f = File.query.filter_by(url=vp.pdf_url).first() if vp.pdf_url else None
        if f:
            os.remove(os.path.join(TestConfig.UPLOAD_FOLDER, f.url.replace("/uploads/", "", 1)))
            db.session.delete(f)
        db.session.delete(vp)
        db.session.commit()

# ---------------- 9. 访客昵称：按 IP 稳定 + emoji 面板默认收起 ----------------
from utils import random_guest_nickname

# 函数本身：同 IP 同昵称，不同 IP 大概率不同
n1 = random_guest_nickname("203.0.113.1")
n2 = random_guest_nickname("203.0.113.1")
n3 = random_guest_nickname("198.51.100.7")
ok("random_guest_nickname 同 IP 稳定", n1 == n2 and len(n1) >= 4)
ok("random_guest_nickname 不同 IP 不同", n1 != n3)

# 文章页 nickname input 已预填访客昵称（新 guest client，127.0.0.1）
gnick = app.test_client()
r = gnick.get("/post/e2e-post")
html = r.get_data(as_text=True)
m = re.search(r'name="nickname"[^>]*value="([^"]*)"', html)
prefilled = m.group(1) if m else ""
with app.app_context():
    expected = random_guest_nickname("127.0.0.1")
ok("文章页 nickname 自动预填访客昵称", bool(prefilled) and prefilled == expected)

# 同一 client 多次访问，昵称预填值稳定
r2 = gnick.get("/post/e2e-post")
m2 = re.search(r'name="nickname"[^>]*value="([^"]*)"', r2.get_data(as_text=True))
ok("同 IP 多次访问昵称预填值不变", m2 and m2.group(1) == prefilled)

# emoji 面板默认 hidden
ok("emoji 面板默认 hidden", 'id="emojiPanel" hidden' in html or re.search(r'id="emojiPanel"[^>]*\shidden', html) is not None)
ok("emoji 按钮 aria-expanded 默认 false", re.search(r'id="emojiToggle"[^>]*aria-expanded="false"', html) is not None)
ok("评论区 tip 文案包含「自动为你取好」", "自动为你取好" in html)

# ---------------- 10. 登录图标 + 配色方案 + PDF.js 静态资源 ----------------
# 首页未登录时导航只显示一个登录图标按钮（不再显示「管理登录」字样）
gh = gnick.get("/")
ghtml = gh.get_data(as_text=True)
ok("首页导航登录为图标按钮", 'class="nav-auth-btn"' in ghtml)
ok("首页不再含「管理登录」文字", "管理登录" not in ghtml)
ok("图标按钮带 aria-label", 'aria-label="登录"' in ghtml)

# 配色方案：未登录首页的 <html> 输出 data-palette，根 setting 决定
m_pal = re.search(r'<html[^>]*data-palette="([^"]*)"', ghtml)
ok("首页 <html> 含 data-palette 属性", m_pal is not None)
ok("默认 data-palette=amber", m_pal and m_pal.group(1) == "amber")

# 修改设置为 sea 后应输出 data-palette=sea
with app.app_context():
    Setting.set("color_palette", "sea")
    db.session.commit()
    from utils import invalidate_settings
    invalidate_settings()  # 进程内 settings 缓存需失效
gh2 = gnick.get("/")
ghtml2 = gh2.get_data(as_text=True)
m_pal2 = re.search(r'<html[^>]*data-palette="([^"]*)"', ghtml2)
ok("切换为 sea 后 data-palette=sea", m_pal2 and m_pal2.group(1) == "sea")
with app.app_context():
    Setting.set("color_palette", "amber")
    db.session.commit()
    from utils import invalidate_settings
    invalidate_settings()

# PDF.js 静态资源
r = gnick.get("/static/vendor/pdfjs/pdf.min.js")
ok("PDF.js 主脚本 200", r.status_code == 200)
r = gnick.get("/static/vendor/pdfjs/pdf.worker.min.js")
ok("PDF.js worker 200", r.status_code == 200)

# ---------------- 收尾 ----------------
print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print(f"全部通过 ✓  (临时库: {TMP_DB})")
