"""前台读者账号：注册 / 登录 / 登出 / 个人中心。

登录态使用独立的 session["uid"]，与后台 session["user_id"] 互不干扰，
同一浏览器可以同时保持“后台管理员”与“前台读者”两个身份。
"""
import os
import re
import uuid
from datetime import datetime

from flask import (Blueprint, current_app, flash, redirect,
                   render_template, request, session, url_for)
from werkzeug.utils import secure_filename

from models import Comment, User, db
from utils import get_client_ip, get_reader, get_setting, is_safe_url, reader_login_required, write_log

member_bp = Blueprint("member", __name__, url_prefix="/user")

_AVATAR_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}


def _safe_next():
    nxt = request.args.get("next") or request.form.get("next") or ""
    if nxt and is_safe_url(nxt):
        return nxt
    return url_for("main.index")


# ---------------- 注册 ----------------

@member_bp.route("/register", methods=["GET", "POST"])
def register():
    # 关闭注册时：提示并引向后台登录（读者体系停用）
    if get_setting("register_allow", "1") != "1":
        flash("本站未开放读者注册，仅管理员可登录后台发布内容", "info")
        return redirect(url_for("auth.login"))
    if get_reader():
        return redirect(url_for("member.center"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        nickname = (request.form.get("nickname") or "").strip() or username
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""

        if not re.fullmatch(r"[A-Za-z0-9_\u4e00-\u9fa5]{2,20}", username or ""):
            flash("用户名需为 2-20 位字母/数字/下划线/中文", "error")
        elif len(password) < 6:
            flash("密码至少 6 位", "error")
        elif password != confirm:
            flash("两次输入的密码不一致", "error")
        elif email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("邮箱格式不正确（选填）", "error")
        elif User.query.filter_by(username=username).first():
            flash("该用户名已被占用", "error")
        else:
            u = User(username=username, nickname=nickname, email=email,
                     role="user", bio="")
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            session["uid"] = u.id
            write_log("register", f"读者注册：{username}", "", username=u.username)
            flash("注册成功，欢迎加入～", "success")
            return redirect(url_for("main.index"))
    return render_template("user/register.html")


# ---------------- 登录 / 登出 ----------------

@member_bp.route("/login", methods=["GET", "POST"])
def login():
    # 读者登录停用（仅管理员后台登录）；历史读者会话仍可登出
    if get_setting("register_allow", "1") != "1":
        flash("读者登录已停用，管理员请从后台登录", "info")
        return redirect(url_for("auth.login"))
    if get_reader():
        return redirect(url_for("member.center"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        u = User.query.filter_by(username=username).first()
        if u and u.check_password(password):
            if u.role != "user":
                flash("该账号是后台管理员，请从管理后台 /admin 登录", "error")
            elif not u.is_active:
                flash("该账号已被停用，请联系管理员", "error")
            else:
                u.last_login_at = datetime.now()
                db.session.commit()
                session["uid"] = u.id
                write_log("reader_login", f"读者登录：{username}", "", username=u.username)
                flash("登录成功", "success")
                return redirect(_safe_next())
        else:
            flash("用户名或密码错误", "error")
    return render_template("user/login.html")


@member_bp.route("/logout")
def logout():
    session.pop("uid", None)
    flash("已退出登录", "success")
    return redirect(_safe_next())


# ---------------- 个人中心 ----------------

@member_bp.route("/center", methods=["GET", "POST"])
@reader_login_required
def center():
    me = get_reader()
    if request.method == "POST":
        nickname = (request.form.get("nickname") or "").strip()
        email = (request.form.get("email") or "").strip()
        bio = (request.form.get("bio") or "").strip()
        old_pwd = request.form.get("old_password") or ""
        new_pwd = request.form.get("new_password") or ""

        if not nickname or len(nickname) > 20:
            flash("昵称需在 1-20 字之间", "error")
        elif email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("邮箱格式不正确（选填）", "error")
        else:
            me.nickname = nickname
            me.email = email
            me.bio = bio[:255]
            avatar_url = (request.form.get("avatar") or "").strip()
            if avatar_url:
                me.avatar = avatar_url[:255]
            if new_pwd:
                if not old_pwd or not me.check_password(old_pwd):
                    flash("修改密码需要先验证旧密码", "error")
                    return render_template("user/center.html", me=me)
                if len(new_pwd) < 6:
                    flash("新密码至少 6 位", "error")
                    return render_template("user/center.html", me=me)
                me.set_password(new_pwd)
            db.session.commit()
            write_log("reader_profile", f"读者资料更新:{me.username}", "", username=me.username)
            flash("资料已保存", "success")
            return redirect(url_for("member.center"))
    my_comments = (
        Comment.query.filter_by(user_id=me.id)
        .order_by(Comment.created_at.desc())
        .limit(20)
        .all()
    )
    return render_template("user/center.html", me=me, my_comments=my_comments)


@member_bp.route("/avatar", methods=["POST"])
@reader_login_required
def avatar_upload():
    """个人头像上传：存储到 uploads/avatar/ 下（不进文件库）。"""
    me = get_reader()
    f = request.files.get("file")
    if not f or not f.filename:
        return {"ok": False, "msg": "未选择图片"}, 400
    ext = (secure_filename(f.filename) or "").rsplit(".", 1)[-1].lower()
    if ext not in _AVATAR_EXTS:
        return {"ok": False, "msg": "仅支持 png/jpg/jpeg/gif/webp 图片"}, 400

    # 删除旧头像（若也是本地上传的）
    if me.avatar and me.avatar.startswith("/uploads/avatar/"):
        old = os.path.join(current_app.config["UPLOAD_FOLDER"],
                           me.avatar.replace("/uploads/", "", 1))
        try:
            if os.path.exists(old):
                os.remove(old)
        except OSError:
            pass

    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], "avatar")
    os.makedirs(folder, exist_ok=True)
    stored = f"u{me.id}_{uuid.uuid4().hex[:12]}.{ext}"
    f.save(os.path.join(folder, stored))
    me.avatar = f"/uploads/avatar/{stored}"
    db.session.commit()
    write_log("reader_avatar", f"读者更新头像:{me.username}", "", username=me.username)
    return {"ok": True, "url": me.avatar}
