# Deploy Guide

## 当前服务器信息

- 项目目录：`/home/ubuntu/apps/new-api-scheduler/webapp`
- Git 分支：`main`
- 容器名：`new-api-scheduler-web`
- 镜像名：`new-api-scheduler-web`
- 数据目录挂载：`/home/ubuntu/apps/new-api-scheduler/webapp/data -> /app/data`
- 端口映射：`127.0.0.1:8000 -> 8000`

## 标准发布流程

### 1. 先在本地提交并推送到 GitHub

```bash
git status
git add .
git commit -m "your commit message"
git push origin main
```

### 2. SSH 登录服务器

```bash
ssh ubuntu@<your-server-ip>
```

### 3. 在服务器上执行发布脚本

```bash
cd /home/ubuntu/apps/new-api-scheduler/webapp
bash deploy.sh
```

如果需要指定分支：

```bash
bash deploy.sh main
```

## 不用脚本时的手动发布命令

```bash
cd /home/ubuntu/apps/new-api-scheduler/webapp
git pull origin main
docker build -t new-api-scheduler-web .
docker stop new-api-scheduler-web || true
docker rm new-api-scheduler-web || true
docker run -d --name new-api-scheduler-web -p 127.0.0.1:8000:8000 -v /home/ubuntu/apps/new-api-scheduler/webapp/data:/app/data -e APP_DATA_DIR=/app/data --restart unless-stopped new-api-scheduler-web
docker logs --tail 100 new-api-scheduler-web
```

## 常用排查命令

查看项目目录：

```bash
cd /home/ubuntu/apps/new-api-scheduler/webapp
pwd
ls -la
```

查看 Git 状态：

```bash
git status
git log --oneline -5
git remote -v
```

查看容器状态：

```bash
docker ps
docker logs --tail 100 new-api-scheduler-web
docker logs -f new-api-scheduler-web
```

检查服务端口：

```bash
ss -lntp | grep :8000
curl -I http://127.0.0.1:8000/
```

## 后续约定

以后当用户说“发布到服务器”时，默认按以下步骤执行：

1. 先确认本地代码是否已提交并推送到 GitHub。
2. SSH 登录服务器。
3. 进入 `/home/ubuntu/apps/new-api-scheduler/webapp`。
4. 执行 `bash deploy.sh` 完成更新。
5. 用 `docker ps` 和 `docker logs --tail 100 new-api-scheduler-web` 验证服务状态。
