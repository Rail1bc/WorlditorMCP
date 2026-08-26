# Nginx 反向代理部署（域名访问）

> 场景：`worlditor.raila.cn` → 玩家端口 6288；`worlditor-admin.raila.cn` →
> 管理端口 6289。nginx 与 worlditor 容器同机（compose 默认即可，无需改）。

## 0. 域名规范（重要）

DNS 主机名**不允许下划线**，`worlditor_backend.raila.cn` 无法解析。
推荐两个子域：`worlditor.raila.cn`（玩家）+ `worlditor-admin.raila.cn`（拥有者）。

## 1. DNS 解析

在 raila.cn 的 DNS 面板添加（或通配）：

```
worlditor        A → 服务器公网 IP
worlditor-admin  A → 服务器公网 IP
```

## 2. 安全基线（必须）

| 项 | 做法 |
|---|---|
| HTTPS | **必须**：明文 HTTP 下登录密码与 Bearer token 会在公网裸奔（证书免费，见 §4） |
| 防火墙 | 服务器**只放行 80/443**；6288/6289 不对公网开放（nginx 反代本机回环地址） |
| 管理端 | nginx 层加 **Basic Auth**（双保险：nginx 认证 + 端口内 tier=admin 校验） |
| 别忘了 | compose 里 `WORLDITOR_ADMIN_KEY` 保持强密钥；`AUTH_MODE=invite` |

## 3. Nginx 配置

`/etc/nginx/sites-available/worlditor`：

```nginx
# WebSocket/SSE 连接头（MCP streamable HTTP 与 /events SSE 依赖）
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    server_name worlditor.raila.cn worlditor-admin.raila.cn;
    return 301 https://$host$request_uri;   # certbot 装完证书前先注释掉这行
}

# ---- 玩家端口（公网） ----
server {
    listen 443 ssl;
    http2 on;
    server_name worlditor.raila.cn;

    ssl_certificate     /etc/letsencrypt/live/worlditor.raila.cn/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/worlditor.raila.cn/privkey.pem;

    client_max_body_size 8m;

    location / {
        proxy_pass http://127.0.0.1:6288;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_buffering off;      # SSE 实时推送关键
        proxy_read_timeout 300s;  # SSE 长连接
    }
}

# ---- 管理端口（拥有者；Basic Auth 双保险） ----
server {
    listen 443 ssl;
    http2 on;
    server_name worlditor-admin.raila.cn;

    ssl_certificate     /etc/letsencrypt/live/worlditor.raila.cn/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/worlditor.raila.cn/privkey.pem;

    client_max_body_size 8m;

    # 生成账号：htpasswd -c /etc/nginx/.worlditor_admin user && 输入强密码
    auth_basic "worlditor admin";
    auth_basic_user_file /etc/nginx/.worlditor_admin;

    location / {
        proxy_pass http://127.0.0.1:6289;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
```

启用：

```bash
sudo ln -s /etc/nginx/sites-available/worlditor /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 4. 证书（一次性）

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d worlditor.raila.cn -d worlditor-admin.raila.cn
# 自动续期（systemd timer 默认已装）；验证：sudo certbot renew --dry-run
```

## 5. 验证

```bash
# 玩家 WebUI（应弹登录页）
curl -sI https://worlditor.raila.cn | head -3
# 管理页（应要求 Basic Auth 与登录）
curl -sI https://worlditor-admin.raila.cn | head -3
# MCP 握手
curl -s -X POST https://worlditor.raila.cn/world/mcp \
  -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

## 6. 说明

- **compose 不用改**：容器内监听 `0.0.0.0`，宿主映射收敛到 `127.0.0.1:6288/6289`，
  nginx 反代本机回环地址即可；公网直连 6288/6289 端口被防火墙挡住
- **同源部署**，WebUI/API/静态资源都在 `worlditor.raila.cn` 的 443 下，
  无 CORS 配置需求（`WORLDITOR_ALLOWED_ORIGINS` 保持空）
- MCP client 地址：`https://worlditor.raila.cn/world/mcp`
- 代理日志关注：`proxy_buffering off` 是 SSE（/events 与 MCP 流式响应）的必要条件，
  缺了会出现"事件延迟/一次性收不到"
