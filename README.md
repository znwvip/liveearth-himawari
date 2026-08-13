# LiveEarth — Himawari-8 云图动画

过去 **48 小时**的 Himawari-8（向日葵 8 号）真彩色地球云图延时动画，云端自动采集合成 MP4，浏览器打开即看，本地不做任何保存。

> 灵感来自 [LiveEarth-FY4B-Wallpaper](https://github.com/whuchenshuo/LiveEarth-FY4B-Wallpaper)，数据源从国产风云四号换成了海外可达性更好的日本 Himawari-8，输出从桌面壁纸改成了网页 MP4 动画。

## 它做什么

```
GitHub Actions（每 10 分钟）
  │ 下载 NICT Himawari-8 全盘图（4 个 tile 拼接 1100×1100）
  │ 裁剪 16:9 → 缩放 720p → 叠北京时间水印
  │ 上传单帧到 R2（frames/）
  │ 清理 48h 前旧帧
  │ 抽 48h 内每 30 分钟一帧 → ffmpeg 合成 MP4
  ▼
Cloudflare R2（存帧 + latest.mp4 + index.html）
  ▼
浏览器（<video> 播放器，带播放控制）
```

## 数据源

- **卫星**：Himawari-8（日本气象厅 JMA），静止轨道 140.7°E
- **产品**：D531106 真彩色全盘图（True Color Reproduction）
- **更新频率**：每 **10 分钟**
- **提供方**：NICT（日本国立情报通信研究机构）

```
https://himawari8.nict.go.jp/img/D531106/{zoom}d/550/{Y}/{m}/{d}/{HHMMSS}_{x}_{y}.png
```

| zoom | 拼接分辨率 | tile 数 | 适用 |
|---|---|---|---|
| 1d  | 550×550   | 1    | 预览 |
| 4d  | 1100×1100 | 4    | 720p（默认）|
| 8d  | 2200×2200 | 16   | 1080p |
| 16d | 4400×4400 | 64   | 4K |

⚠️ 版权：数据归 JMA / NICT，**禁止商用**，仅供个人使用。

## 快速开始（3 步）

### 第 1 步：Cloudflare R2 建桶 + 开公开访问

1. 登录 [Cloudflare](https://dash.cloudflare.com/) → 左侧 **R2**（没有就先开通，免费）
2. 点 **Create bucket**，名字填 `liveearth-himawari`，区域选 **亚太（APAC）** 或 Auto
3. 进入该 bucket → **Settings** → 找到 **Public access**（或 Domain Access）→
   - 打开 **R2.dev subdomain** 开关（`Allow Access`）
   - 记下你的公开域名，形如：`https://pub-xxxxxxxxxxxxxxxx.r2.dev`
   - 记下你的 **Account ID**（Settings 页或账号首页能看到，32 位 hex）

### 第 2 步：生成 R2 的 S3 凭证

1. Cloudflare 左侧 **R2** → 右上 **Manage R2 API Tokens**
2. **Create API token**
   - Token name：`liveearth`
   - Permissions：**Object Read & Write**
   - 指定 bucket：选刚建的 `liveearth-himawari`
3. 创建后复制 **Access Key ID** 和 **Secret Access Key**（Secret 只显示一次）

### 第 3 步：填 GitHub Secrets

1. 打开本仓库 → **Settings → Secrets and variables → Actions**
2. 点 **New repository secret**，依次添加：

| Name | 值 |
|---|---|
| `R2_ACCOUNT_ID` | 你的 Account ID |
| `R2_ACCESS_KEY_ID` | 上面复制的 Access Key ID |
| `R2_SECRET_ACCESS_KEY` | 上面复制的 Secret Access Key |
| `R2_BUCKET` | `liveearth-himawari` |

### 第 4 步：触发一次

- 仓库 → **Actions** → 左侧 `collect-himawari` → **Run workflow** → 绿色按钮
- 等 1~2 分钟跑完

### 第 5 步：打开网页

浏览器访问：

```
https://<你的 r2.dev 域名>/index.html
```

或直接看动画：

```
https://<你的 r2.dev 域名>/latest.mp4
```

## 网页播放控制

- **播放/暂停**：点视频，或按空格
- **进度条**：直接拖动跳到任意时间
- **倍速**：0.5× / 1× / 2× / 4×
- **循环**：默认开启，可关闭
- **全屏**：右下角按钮或双击视频
- **快退/快进**：键盘 ← →（每次 5 秒）

## 自定义

### 换分辨率（720p → 1080p）

编辑 `.github/workflows/collect.yml` 里的 env：

```yaml
OUT_W: "1920"
OUT_H: "1080"
ZOOM: "8"        # 1080p 建议用 8d（2200px）
```

### 改抽帧间隔 / 时间窗 / 帧率

在 `collect.py` 顶部（也可用环境变量覆盖）：

| 变量 | 默认 | 含义 |
|---|---|---|
| `WINDOW_HOURS` | 48 | 动画时间窗 |
| `FRAME_STEP_MIN` | 30 | MP4 抽帧间隔（分钟）|
| `FPS` | 6 | MP4 帧率 |
| `CRF` | 23 | H.264 质量（越小越清晰，文件越大）|

### 改采集频率

编辑 `collect.yml` 的 cron。当前 `*/10 * * * *` 表示每 10 分钟。

## 目录结构

```
liveearth-himawari/
├── collect.py                    # 采集 + 合成主脚本
├── .github/workflows/collect.yml # 定时任务
├── web/index.html                # 播放器页面
└── README.md
```

## 常见问题

**动画还没出现 / 只有一两帧？** 首次运行需要先积累至少 2 帧。等 1 小时后再看，48 小时窗口填满后动画才完整。

**网页打不开？** 确认 R2 bucket 的 public access 已开启，且用 r2.dev 域名。

**时间戳是 UTC 还是北京时？** 视频水印是北京时间（UTC+8）。

**流量/成本？** R2 免费额度：10GB 存储 + 每月 1000 万次读 + egress 免费。本项目每天约几十 MB，远在免费额度内。

## 许可

代码 MIT。卫星影像版权归 JMA / NICT，仅供个人、非商业使用。
