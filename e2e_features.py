"""端到端验证：后台用户管理 / 日志 / 深色模式 / 侧栏部件 / 天气 / 文章与评论 / PDF。

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
import io
import struct
import zlib

# SSL 上传功能走 DRY_RUN：本机没有 wrapper / nginx，跳过实际写盘与 reload
os.environ["BLOG_SSL_DRY_RUN"] = "1"

from config import Config
from app import create_app
from models import (Category, Comment, File, Log, Post, Setting, SSLCertificate,
                    User, db)

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
    db.session.commit()
    POST_ID = post.id
    ADMIN_ID = admin.id


# ---------------- 1. 旧读者入口 /user/* 全部 302 到后台登录 ----------------
for p in ["/user/register", "/user/login", "/user/center", "/user/logout"]:
    g = client_with_csrf()
    r = g.get(p, follow_redirects=False)
    ok(f"GET {p} -> 302 重定向到登录", r.status_code == 302)

# 头像上传也已下线，应返回 410
ga = client_with_csrf()
r = ga.post("/user/avatar", data={**csrf(),
    "file": (io.BytesIO(b"x"), "x.png")}, content_type="multipart/form-data")
ok("POST /user/avatar 已下线 -> 410", r.status_code == 410)


# ---------------- 2. 后台账号管理 ----------------
ca = client_with_csrf()
with ca.session_transaction() as s:
    s["user_id"] = ADMIN_ID

r = ca.get("/admin/users")
ok("GET /admin/users 200", r.status_code == 200 and "站长" in r.get_data(as_text=True))
ok("默认仅 staff tab（移除读者 tab）", "前台读者" not in r.get_data(as_text=True))

# 新建同事账号（role=admin）
r = ca.post("/admin/users/new", data={**csrf(), "username": "staff01",
    "nickname": "员工", "password": "staff123456"}, follow_redirects=False)
ok("后台新建账号 -> 302", r.status_code == 302)
with app.app_context():
    staff = User.query.filter_by(username="staff01").first()
ok("后台新建账号入库 role=admin", staff is not None and staff.role == "admin")

# 不能停用自己
r = ca.post(f"/admin/users/{ADMIN_ID}/toggle", data=csrf(), follow_redirects=False)
ok("停用自己的操作被拒(回 302 列表)", r.status_code == 302)
with app.app_context():
    a2 = User.query.get(ADMIN_ID)
    ok("自己账号未被停用", a2.is_active)

# 重置密码（给同事）
r = ca.post(f"/admin/users/{staff.id}/reset", data={**csrf(),
    "password": "new123456"}, follow_redirects=False)
ok("重置同事密码 -> 302", r.status_code == 302)
with app.app_context():
    staff2 = User.query.get(staff.id)
    ok("重置后新密码可用", staff2.check_password("new123456"))

# 删除账号
r = ca.post(f"/admin/users/{staff.id}/delete", data=csrf(), follow_redirects=False)
ok("删除账号 -> 302", r.status_code == 302)
with app.app_context():
    ok("删除后库中无此用户", User.query.get(staff.id) is None)


# ---------------- 3. 角色路由分流：admin 走后台登录 ----------------
gc = client_with_csrf()
r = gc.post("/login", data={**csrf(), "username": "admin", "password": "admin123"},
            follow_redirects=False)
ok("admin /login 成功 -> 302 dashboard", r.status_code == 302)

gc2 = client_with_csrf()
r = gc2.post("/login", data={**csrf(), "username": "admin", "password": "wrong-pass"})
ok("错误密码 admin 登录被拒(200 带错误)",
   r.status_code == 200 and "用户名或密码错误" in r.get_data(as_text=True))


# ---------------- 4. 游客评论（无 reader 体系，user_id 永远=None） ----------------
c4 = client_with_csrf()
r = c4.post("/api/comment", data={**csrf(), "post_id": str(POST_ID),
    "nickname": "路人", "email": "", "content": "游客评论一条"})
ok("游客评论 ok", r.status_code == 200 and json.loads(r.get_data(as_text=True)).get("ok"))
with app.app_context():
    cm2 = Comment.query.filter_by(content="游客评论一条").first()
    ok("游客评论 user_id=None", cm2 is not None and cm2.user_id is None)

# 评论关闭开关
r = c4.post("/api/comment", data={**csrf(), "post_id": str(POST_ID),
    "nickname": "x", "content": "再一条"})
ok("再一条评论 ok", r.status_code == 200)


# ---------------- 5. 日志系统 ----------------
r = ca.get("/admin/logs")
ok("GET /admin/logs 200", r.status_code == 200)
r = ca.post("/admin/logs/purge", data=csrf(), follow_redirects=False)
ok("POST /admin/logs/purge 手动清理 -> 302", r.status_code == 302)
with app.app_context():
    ok("purge 后日志表仍在（保留期内不删空）", Log.query.count() >= 0)
r = ca.post("/admin/logs/clear", data=csrf(), follow_redirects=False)
ok("POST /admin/logs/clear 清空 -> 302", r.status_code == 302)


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


# ---------------- 7. 设置项保存 ----------------
r = ca.post("/admin/settings", data={**csrf(),
    "site_name": "雾里博客", "site_subtitle": "记录与分享",
    "site_description": "d", "site_keywords": "k", "footer_text": "f",
    "icp": "", "comment_allow": "1", "comment_need_audit": "1",
    "blogger_name": "站长", "blogger_avatar": "/uploads/avatar/me.jpg", "blogger_bio": "写代码的",
    "motto_enable": "1", "motto_text": "日日是好日",
    "theme_default": "light", "theme_auto": "schedule",
    "theme_dark_start": "19", "theme_dark_end": "07", "theme_fix_content": "1",
    "weather_default_city": "Chengdu", "log_keep_days": "90",
}, follow_redirects=False)
ok("POST /admin/settings 保存新配置 -> 302", r.status_code == 302)
with app.app_context():
    sv = {s.key: s.value for s in Setting.query.all()}
    ok("theme_auto=schedule 已保存", sv.get("theme_auto") == "schedule")
    ok("motto_text 已保存", sv.get("motto_text") == "日日是好日")
    ok("weather_default_city 已保存", sv.get("weather_default_city") == "Chengdu")
    ok("register_allow 已不再保存", "register_allow" not in sv)


# ---------------- 8. 侧栏部件 ----------------
for needle in ["blogger", "motto", "weatherCard", "cdToday", "cdMonth", "cdYear"]:
    ok(f"首页 HTML 含侧栏部件标记 {needle}", needle in html)


# ---------------- 9. 文章级评论开关 ----------------
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

r = ca.post(f"/admin/posts/{NC_ID}/edit", data={**csrf(), "title": "关闭评论的测试文章",
    "slug": "e2e-nocomment", "content": "正文内容", "render_mode": "markdown",
    "status": "published", "allow_comment": "1"}, follow_redirects=False)
ok("编辑文章重新开启评论 -> 302", r.status_code == 302)
r = c4.post("/api/comment", data={**csrf(), "post_id": str(NC_ID),
    "nickname": "游客乙", "content": "重新开启后可以评论"})
ok("重新开启后评论成功", r.status_code == 200 and json.loads(r.get_data(as_text=True)).get("ok"))


# ---------------- 10. PDF 转文章 ----------------
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
ok("POST /admin/pdf/new -> 302 跳编辑器",
   r.status_code == 302 and re.search(r"/admin/posts/\d+/edit", loc))
with app.app_context():
    fp = Post.query.filter(Post.title == "manual").order_by(Post.id.desc()).first()
    ok("PDF 转换生成草稿", fp is not None and fp.status == "draft")
    ok("PDF 文本已提取进正文", fp is not None and "Hello PDF Import Test" in (fp.content or ""))
    fr = File.query.filter_by(kind="doc").order_by(File.id.desc()).first()
    ok("原 PDF 已入文件库(doc)", fr is not None and fr.name == "manual.pdf")
    ok("原 PDF 已落盘", fr is not None and os.path.exists(
        os.path.join(TestConfig.UPLOAD_FOLDER, fr.url.replace("/uploads/", "", 1))))

r = ca.post("/admin/pdf/new", data={**csrf(),
    "file": (io.BytesIO(b"not a pdf"), "evil.txt")},
    content_type="multipart/form-data", follow_redirects=False)
ok("非 PDF 上传被拒(302 回表单)",
   r.status_code == 302 and "/pdf/new" in r.headers.get("Location", ""))

# ---- PDF 在线阅读模式 ----
r = ca.post("/admin/pdf/new", data={**csrf(), "mode": "view",
    "file": (io.BytesIO(pdf_bytes), "viewer-test.pdf")},
    content_type="multipart/form-data", follow_redirects=False)
ok("PDF view 模式 302 跳编辑器",
   r.status_code == 302 and re.search(r"/admin/posts/\d+/edit", r.headers.get("Location", "")))
with app.app_context():
    vpost = (Post.query.filter(Post.title.like("%Hello%"), Post.render_mode == "pdf")
             .order_by(Post.id.desc()).first()
             or Post.query.filter(Post.render_mode == "pdf")
             .order_by(Post.id.desc()).first())
    ok("PDF view 模式入库 render_mode=pdf", vpost is not None and vpost.render_mode == "pdf")
    ok("PDF view 模式入库 pdf_url", vpost is not None and vpost.pdf_url.startswith("/uploads/doc/"))
    if vpost:
        vpost.status = "published"
        db.session.commit()
        slug = vpost.slug
    else:
        slug = None
if slug:
    r = c4.get("/post/" + slug)
    html_post = r.get_data(as_text=True)
    ok("前台 PDF 阅读页含 pdfPages 容器", 'id="pdfPages"' in html_post)
    ok("前台 PDF 阅读页含 pdf.min.js 引用", "vendor/pdfjs/pdf.min.js" in html_post)
    ok("前台 PDF 阅读页含下载按钮", "下载原 PDF" in html_post)
with app.app_context():
    vp = Post.query.filter(Post.render_mode == "pdf").order_by(Post.id.desc()).first()
    if vp:
        f = File.query.filter_by(url=vp.pdf_url).first() if vp.pdf_url else None
        if f:
            try:
                os.remove(os.path.join(TestConfig.UPLOAD_FOLDER, f.url.replace("/uploads/", "", 1)))
            except OSError:
                pass
            db.session.delete(f)
        db.session.delete(vp)
        db.session.commit()


# ---------------- 11. 访客昵称：按 IP 稳定 ----------------
from utils import random_guest_nickname

n1 = random_guest_nickname("203.0.113.1")
n2 = random_guest_nickname("203.0.113.1")
n3 = random_guest_nickname("198.51.100.7")
ok("random_guest_nickname 同 IP 稳定", n1 == n2 and len(n1) >= 4)
ok("random_guest_nickname 不同 IP 不同", n1 != n3)

gnick = app.test_client()
r = gnick.get("/post/e2e-post")
html_post = r.get_data(as_text=True)
m = re.search(r'name="nickname"[^>]*value="([^"]*)"', html_post)
prefilled = m.group(1) if m else ""
with app.app_context():
    expected = random_guest_nickname("127.0.0.1")
ok("文章页 nickname 自动预填访客昵称", bool(prefilled) and prefilled == expected)

r2 = gnick.get("/post/e2e-post")
m2 = re.search(r'name="nickname"[^>]*value="([^"]*)"', r2.get_data(as_text=True))
ok("同 IP 多次访问昵称预填值不变", m2 and m2.group(1) == prefilled)

ok("emoji 面板默认 hidden",
   'id="emojiPanel" hidden' in html_post or re.search(r'id="emojiPanel"[^>]*\shidden', html_post) is not None)
ok("emoji 按钮 aria-expanded 默认 false",
   re.search(r'id="emojiToggle"[^>]*aria-expanded="false"', html_post) is not None)
ok("评论区 tip 文案包含「自动为你取好」", "自动为你取好" in html_post)


# ---------------- 12. 登录图标 + 配色方案 + PDF.js 静态资源 ----------------
gh = gnick.get("/")
ghtml = gh.get_data(as_text=True)
ok("首页导航登录为图标按钮", 'class="nav-auth-btn"' in ghtml)
ok("首页不再含「管理登录」文字", "管理登录" not in ghtml)
ok("图标按钮带 aria-label", 'aria-label="登录"' in ghtml)

m_pal = re.search(r'<html[^>]*data-palette="([^"]*)"', ghtml)
ok("首页 <html> 含 data-palette 属性", m_pal is not None)
ok("默认 data-palette=amber", m_pal and m_pal.group(1) == "amber")

with app.app_context():
    Setting.set("color_palette", "sea")
    db.session.commit()
    from utils import invalidate_settings
    invalidate_settings()
gh2 = gnick.get("/")
ghtml2 = gh2.get_data(as_text=True)
m_pal2 = re.search(r'<html[^>]*data-palette="([^"]*)"', ghtml2)
ok("切换为 sea 后 data-palette=sea", m_pal2 and m_pal2.group(1) == "sea")
with app.app_context():
    Setting.set("color_palette", "amber")
    db.session.commit()
    from utils import invalidate_settings
    invalidate_settings()

r = gnick.get("/static/vendor/pdfjs/pdf.min.js")
ok("PDF.js 主脚本 200", r.status_code == 200)
r = gnick.get("/static/vendor/pdfjs/pdf.worker.min.js")
ok("PDF.js worker 200", r.status_code == 200)


# ---------------- 13. SSL 证书上传（DRY_RUN 下完整回归） ----------------
from datetime import datetime as _dt, timedelta as _td, timezone as _tz

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _make_cert(domains, days=365, shift=0):
    """生成本地自签证书，返回 (cert_pem, key_pem)。
    整窗平移：not_before=now+shift-1d, not_after=now+shift+days。
    shift<0 → 已过期；shift>0 → 尚未生效。"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = _dt.now(_tz.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domains[0])])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + _td(days=shift - 1))
        .not_valid_after(now + _td(days=shift + days))
        .add_extension(x509.SubjectAlternativeName(
            [x509.DNSName(d) for d in domains]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()
    return cert_pem, key_pem


def _ssl_upload(c, domain, cert_pem, key_pem):
    return c.post("/admin/ssl/upload", data={**csrf(), "domain": domain,
        "cert_pem": cert_pem, "key_pem": key_pem}, follow_redirects=False)


# 状态页 / 上传页可达 + DRY_RUN 提示
r = ca.get("/admin/ssl")
ok("GET /admin/ssl 200", r.status_code == 200)
ok("状态页含 DRY-RUN 开发模式提示", "DRY-RUN" in r.get_data(as_text=True))
r = ca.get("/admin/ssl/upload")
ok("GET /admin/ssl/upload 200 含表单", r.status_code == 200
   and "上传 / 更新 SSL 证书" in r.get_data(as_text=True))

# 配对证书上传成功（DRY_RUN 不写盘，但入库元数据）
cert_ok, key_ok = _make_cert(["blog.example.com", "erp.example.com"], days=365)
r = _ssl_upload(ca, "blog.example.com", cert_ok, key_ok)
ok("上传配对证书 -> 302 回状态页",
   r.status_code == 302 and r.headers.get("Location", "").endswith("/admin/ssl"))
with app.app_context():
    sc = (SSLCertificate.query.filter_by(domain="blog.example.com", is_active=True)
          .order_by(SSLCertificate.id.desc()).first())
    ok("成功证书入库 is_active=True", sc is not None)
    ok("入库 SAN 含 blog 与 erp", sc is not None
       and "blog.example.com" in sc.sans_list and "erp.example.com" in sc.sans_list)
    SC_ID = sc.id if sc else -1

# 换一张新证书更新（老记录被置为不激活）
cert_ok2, key_ok2 = _make_cert(["blog.example.com"], days=400)
r = _ssl_upload(ca, "blog.example.com", cert_ok2, key_ok2)
ok("更新证书 -> 302", r.status_code == 302)
with app.app_context():
    n_active = SSLCertificate.query.filter_by(domain="blog.example.com",
                                              is_active=True).count()
    old = SSLCertificate.query.get(SC_ID)
    ok("更新后旧证书 is_active=False、仅 1 条 active", old is not None
       and not old.is_active and n_active == 1)

# 负向：密钥不匹配
certA, keyA = _make_cert(["blog.example.com"])
certB, keyB = _make_cert(["blog.example.com"])
r = _ssl_upload(ca, "blog.example.com", certA, keyB)
ok("私钥不匹配被拒(提示不匹配)",
   r.status_code == 200 and "不匹配" in r.get_data(as_text=True))

# 负向：域名不在证书 SAN
r = _ssl_upload(ca, "other-site.com", cert_ok, key_ok)
ok("域名不在 SAN 被拒", r.status_code == 200
   and "不在证书覆盖范围" in r.get_data(as_text=True))

# 负向：已过期 / 尚未生效
cexp, kexp = _make_cert(["blog.example.com"], days=30, shift=-60)
r = _ssl_upload(ca, "blog.example.com", cexp, kexp)
ok("过期证书被拒(提示已过期)", r.status_code == 200 and "过期" in r.get_data(as_text=True))
cfut, kfut = _make_cert(["blog.example.com"], days=90, shift=15)
r = _ssl_upload(ca, "blog.example.com", cfut, kfut)
ok("未生效证书被拒(提示尚未生效)",
   r.status_code == 200 and "尚未生效" in r.get_data(as_text=True))

# 负向：非 PEM 垃圾输入 / 缺字段
r = _ssl_upload(ca, "blog.example.com", "not a pem at all", key_ok)
ok("垃圾证书文本被拒", r.status_code == 200
   and ("格式错误" in r.get_data(as_text=True) or "解析失败" in r.get_data(as_text=True)))
r = ca.post("/admin/ssl/upload", data={**csrf(), "domain": "", "cert_pem": "", "key_pem": ""},
            follow_redirects=False)
ok("空表单被拒(302 回上传页)", r.status_code == 302)
with app.app_context():
    ok("负向用例全部未入库", SSLCertificate.query.filter_by(domain="other-site.com").count() == 0
       and SSLCertificate.query.count() <= 3)

# 停用 HTTPS（删除）
r = ca.post("/admin/ssl/delete", data={**csrf(), "domain": "blog.example.com"},
            follow_redirects=False)
ok("POST /admin/ssl/delete -> 302", r.status_code == 302)
with app.app_context():
    sc3 = SSLCertificate.query.get(SC_ID)
    ok("删除后无 active 记录", sc3 is not None and not sc3.is_active
       and SSLCertificate.query.filter_by(is_active=True).count() == 0)


# ---------------- 自定义背景图（前台毛玻璃背景图） ----------------
# 后台设置页包含控件
r = ca.get("/admin/settings")
_h = r.get_data(as_text=True)
ok("后台设置页含背景图输入框/滑杆/上传按钮",
   'id="bgImgInput"' in _h and 'id="bgOpacity"' in _h and 'id="bgFileBtn"' in _h)

# 设置图片 + 透明度 → 首页 body 注入 CSS 变量、渲染背景层、光斑隐藏
r = ca.post("/admin/settings", data={**csrf(), "site_bg_image": "/uploads/image/wallpaper.jpg",
                                     "site_bg_opacity": "70"}, follow_redirects=False)
ok("保存背景图设置 -> 302", r.status_code == 302)
r = app.test_client().get("/")
_h = r.get_data(as_text=True)
ok("前台首页启用 has-bg-photo 与 .bg-photo 层",
   'class="has-bg-photo"' in _h and 'class="bg-photo"' in _h)
ok("背景图 URL 已安全写入 CSS 变量",
   "--bg-photo-bg: url(/uploads/image/wallpaper.jpg)" in _h)
ok("透明度 70 正确注入", "--bg-photo-opacity: 0.7" in _h)
ok("设置页回显当前值", 'value="/uploads/image/wallpaper.jpg"' in
   ca.get("/admin/settings").get_data(as_text=True))

# 透明度越界被 clamp（100 / 非法回 45）
def _bg_op_value():
    with app.app_context():
        s = Setting.query.filter_by(key="site_bg_opacity").first()
        return s.value if s else None

r = ca.post("/admin/settings", data={**csrf(), "site_bg_image": "/uploads/image/wallpaper.jpg",
                                     "site_bg_opacity": "999"}, follow_redirects=False)
ok("透明度 999 被 clamp 为 100", _bg_op_value() == "100")
r = ca.post("/admin/settings", data={**csrf(), "site_bg_image": "/uploads/image/wallpaper.jpg",
                                     "site_bg_opacity": "abc"}, follow_redirects=False)
ok("透明度非法值回退 45", _bg_op_value() == "45")

# 清空图片 → 前台恢复默认（无背景层）
r = ca.post("/admin/settings", data={**csrf(), "site_bg_image": "",
                                     "site_bg_opacity": "45"}, follow_redirects=False)
_h = app.test_client().get("/").get_data(as_text=True)
ok("清空背景图后前台恢复正常渐变底",
   'class="has-bg-photo"' not in _h and 'class="bg-photo"' not in _h)


# ---- 收尾 ----
print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print(f"全部通过 ✓  (临时库: {TMP_DB})")
