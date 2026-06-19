# 云端部署指南

---

## 推荐：GitHub Actions（完全免费）

不需要任何服务器，GitHub 免费提供定时运行。

### 部署步骤

1. **把项目上传到 GitHub**（如果还没有仓库）

2. **启用 GitHub Actions**：
   仓库 → Settings → Actions → General → 勾选 "Allow all actions"

3. **手动触发一次测试**：
   仓库 → Actions → 福彩3D 每日预测 → Run workflow

4. **完成**。之后每天 5 个时间点自动运行：
   - 09:00 晨间提醒
   - 20:50 截止提醒
   - 21:18 轮询开奖 + 命中复盘 + 明日预测
   - 22:00 二次轮询
   - 06:30 兜底轮询

### 原理

不是一直跑一个进程，而是 GitHub 每天在指定时间启动一个虚拟机，运行预测脚本（约 30 秒），然后自动关闭。数据文件（history.json）自动提交回仓库，下次运行自动同步。

```
你的电脑关机 ──→ GitHub 的服务器到点自动跑 ──→ 飞书推送
```

**零费用、零维护、不出问题。**

---

## 方案二：云服务器（50元/月，最稳定）

```bash
# 1. 安装 Docker
curl -fsSL https://get.docker.com | sh

# 2. 上传项目
scp -r fc3d_predict root@服务器IP:/root/

# 3. 启动
cd /root/fc3d_predict && docker compose up -d

# 4. 确认
docker compose logs -f
```

---

## 方案三：自己的电脑不关机

已配置开机自启（start.vbs 在启动文件夹）。电脑不关机就一直跑。
