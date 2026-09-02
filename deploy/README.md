# 部署脚本说明

把项目部署到 Ubuntu 20.04+/22.04+ 服务器（腾讯云轻量 / CVM 都行），使用 Flask + Gunicorn + Nginx 经典组合。

## 文件说明

| 文件 | 作用 |
|---|---|
| `install.sh` | 一键安装脚本（创建目录、venv、systemd、nginx 配置） |
| `blog.service` | systemd 服务文件，Supervisor 风格的进程守护 |
| `nginx.conf` | Nginx 反向代理 + 静态资源直出 |
| `nginx-subpath.conf` | **挂到已有 Halo 同域名子路径**用的反代（如 `https://blog.example.com/blog/`） |
| `blog.env.example` | 生产环境密钥模板（**复制为 `/etc/blog/blog.env` 并填密钥**） |
| `rollback.sh` | 快速回滚到上一版本（git tag 备份式） |
| `logs.sh` | 集中查看日志（应用 + nginx） |

## 一键部署流程

### A. 全新服务器（独立子域名 / 顶级域名）

```bash
# 1. 克隆代码
git clone <你的仓库地址> /var/www/blog
cd /var/www/blog

# 2. 生成生产密钥
cp deploy/blog.env.example /etc/blog/blog.env
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))" >> /etc/blog/blog.env
chmod 600 /etc/blog/blog.env

# 3. 一键安装（创建 venv、安装依赖、注册 systemd + nginx）
sudo bash deploy/install.sh

# 4. 初始化数据库
cd /var/www/blog
sudo -u www-data venv/bin/python -c "from app import app, db; app.app_context().push(); db.create_all()"
sudo -u www-data venv/bin/python seed.py  # 可选：插入演示数据

# 5. 启动服务
sudo systemctl enable --now blog
sudo systemctl status blog

# 6. 配 HTTPS（任选其一）
#    A) certbot 自动（推荐）
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d blog.example.com
#    B) 腾讯云免费证书：下载 nginx 版放 /etc/nginx/certs/，改 nginx.conf 启用 443 server block
```

### B. 与已有 Web 服务共用域名（挂在子路径下）

若域名已用于其他服务（例如 Halo 博客），想把本项目挂在 `example.com/blog/` 子路径下：

```bash
# 1-4 同上，但第 3 步改用：
sudo cp deploy/nginx-subpath.conf /etc/nginx/sites-available/blog.conf
# 2. 改 server_name 为你的域名，并确认 Halo 的 server block 已存在 location /blog/ 转 fallback 或 try_files
# 3. 改 blog.conf 里的 proxy_pass 指向 gunicorn
```

**注意**：Flask 子路径部署需要在 `app.py` 的 `app.config['APPLICATION_ROOT']` 或 `app.wsgi_app` 加 `DispatcherMiddleware`，让 `/blog/xxx` 路径被正确路由到 Flask app。`install.sh` 默认是独立子域名部署，子路径需要手动调整 app.py。

## 后续运维

- **更新代码**：`cd /var/www/blog && git pull && sudo systemctl restart blog`
- **看日志**：`bash deploy/logs.sh`
- **数据备份**：管理后台 → 备份 → 下载数据库
- **回滚**：`bash deploy/rollback.sh`（如果启用了 git tag）
