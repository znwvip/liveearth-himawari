# LiveEarth — Himawari-8 云图动画

过去 **70 小时**的 Himawari-8（向日葵 8 号）真彩色地球云图延时动画，云端自动采集合成 MP4，浏览器打开即看，本地不做任何保存。

> 灵感来自 [LiveEarth-FY4B-Wallpaper](https://github.com/whuchenshuo/LiveEarth-FY4B-Wallpaper)，数据源从国产风云四号换成了海外可达性更好的日本 Himawari-8，输出从桌面壁纸改成了网页 MP4 动画。

## 它做什么

```
GitHub Actions（每 30 分钟 cron）
  │ 从 NICT 下载过去 70h 内每 30 分钟一帧（4×4=16 tile 拼接 2200×2200）
  │ 完整地球方形画布 → 缩放 720×720 → 叠北京时间水印
  │ ffmpeg 合成 MP4（H.264, 6fps）
  │ 输出 index.html + latest.mp4 到 dist/
  ▼
GitHub Pages（自动部署，force_orphan + CNAME）
  ▼
浏览器（<video> 播放器，带播放控制）
```

**零存储依赖**：NICT 自身保留 72h+ 历史数据，无需 R2 / 对象存储 / 数据库。
**零密钥依赖**：部署只用 GitHub 内置的 `GITHUB_TOKEN`，不绑卡、不配密钥。

- **在线地址**：自定义域名（Cloudflare CNAME → GitHub Pages，见「快速开始」）
- **备选地址**：https://znwvip.github.io/liveearth-himawari/

## 数据源

- **卫星**：Himawari-8（日本气象厅 JMA），静止轨道 140.7°E
- **产品**：D531106 真彩色全盘图（True Color Reproduction）
- **更新频率**：每 **10 分钟**
- **提供方**：NICT（日本国立情报通信研究机构）

```
https://himawari8.nict.go.jp/img/D531106/{zoom}d/550/{Y}/{m}/{d}/{HHMMSS}_{x}_{y}.png
```

| zoom | 拼接 tile | 源分辨率 | 本项目 |
|---|---|---|---|
| 1d  | 1×1   | 550×550   | — |
| 4d  | 4×4   | 2200×2200 | ✅ 默认（ZOOM=4）|
| 8d  | 8×8   | 4400×4400 | 升级 1080p 时用 |
| 16d | 16×16 | 8800×8800 | — |

> ⚠️ 注：代码里 `GRID` 是每边 tile 数，`ZOOM=4` → `GRID=4` → 4×4=16 tile 拼接，最终缩放到 720×720 方形画布。

⚠️ 版权：数据归 JMA / NICT，**禁止商用**，仅供个人使用。

## 运行机制

### 定时任务（`.github/workflows/collect.yml`）

- **频率**：`*/30 * * * *`（每 30 分钟，UTC），可手动 `workflow_dispatch` 触发
- **权限**：`contents: write`（推 Pages 分支用）
- **并发**：`concurrency: group=collect`，同一时间只跑一个，避免堆叠

### 采集脚本（`collect.py`）

| 变量 | 默认 | 含义 |
|---|---|---|
| `ZOOM` | 4 | 每边 tile 数（4→16 tile，2200×2200）|
| `OUT_W / OUT_H` | 720 / 720 | 输出画布（方形，完整地球）|
| `WINDOW_HOURS` | 70 | 动画时间窗（NICT 保留 72h，留 2h 余量）|
| `FRAME_STEP_MIN` | 30 | 抽帧间隔（分钟）|
| `FPS` | 6 | MP4 帧率 |
| `CRF` | 23 | H.264 质量（越小越清晰，文件越大）|
| `JPEG_QUALITY` | 85 | 单帧 JPEG 质量 |
| `MAX_WORKERS` | 4 | 并发下载渲染线程数 |

### 单次运行流程

1. **build_slots**：生成过去 70h 内每 30 分钟一个的时间点（对齐到 10 分钟、回退 20 分钟确保帧已发布）
2. **render_frame**（并发）：每帧下载 16 tile → 拼接 → 缩放到 720×720 → 右下角叠北京时间水印（`Himawari-8 YYYY-MM-DD HH:MM CST`）
3. **build_mp4**：ffmpeg `libx264` 合成，`+faststart` 便于网页边下边播
4. **输出 dist/**：`latest.mp4` + 从 `web/index.html` 复制的播放页
5. **部署**：`peaceiris/actions-gh-pages@v4` 推送到 Pages 分支（`force_orphan`），`cname` 为自定义域名（见 `collect.yml`）

> 少于 2 帧成功会 `sys.exit(1)` 中止（首次运行或数据源长时间故障时保护）。

## 快速开始

### 第 1 步：把仓库设为 GitHub Pages 源

1. 仓库 → **Settings → Pages**
2. Source 选 **GitHub Actions**（或由 `actions-gh-pages` 自动处理）
3. 仓库需 **public**（免费版自定义域名要求 public；private 会消耗更多 Actions 额度）

### 第 2 步：绑定自定义域名（可选）

1. Cloudflare DNS 添加 CNAME 记录：`earth` → `znwvip.github.io`
2. workflow 里 `cname` 字段已配好对应域名，`actions-gh-pages` 会自动写 CNAME 文件

### 第 3 步：触发一次

- 仓库 → **Actions** → `collect-himawari` → **Run workflow**
- 等 10~15 分钟跑完（下载 140 帧 + 合成 + 部署）

### 第 4 步：打开网页

打开你的 Pages 地址（`https://<用户名>.github.io/liveearth-himawari/`，或绑定的自定义域名）：

```
https://znwvip.github.io/liveearth-himawari/
```

或直接看动画：

```
https://znwvip.github.io/liveearth-himawari/latest.mp4
```

## 网页播放控制

- **播放/暂停**：点视频，或按空格
- **进度条**：直接拖动跳到任意时间
- **倍速**：0.5× / 1× / 2× / 4×
- **循环**：默认开启，可关闭
- **全屏**：右下角按钮或双击视频
- **快退/快进**：键盘 ← →（每次 5 秒）

## 自定义

### 升级分辨率（720 → 1080）

编辑 `.github/workflows/collect.yml`：

```yaml
OUT_W: "1080"
OUT_H: "1080"
ZOOM: "8"        # 8×8=64 tile，4400×4400
```

### 改时间窗 / 抽帧间隔 / 帧率

在 `collect.py` 顶部改常量，或在 workflow 的 env 里覆盖（见上表）。

### 改采集频率

编辑 `collect.yml` 的 cron。当前 `*/30 * * * *`。

## 目录结构

```
liveearth-himawari/
├── collect.py                    # 采集 + 合成主脚本
├── .github/workflows/collect.yml # 定时任务 + 部署
├── web/index.html                # 播放器页面
└── README.md
```

运行时生成 `dist/`（`index.html` + `latest.mp4`），由 Actions 部署到 Pages 分支，不提交到源码分支。

## 常见问题

**动画还没出现 / 只有一两帧？** 首次运行需要先积累至少 2 帧（否则脚本会中止保护）。等 1 小时后再看，70 小时窗口填满后动画才完整。

**网页打不开？** 检查：仓库是否 public、Pages 是否启用、自定义域名 CNAME 是否生效（指向 `znwvip.github.io`）。部署约在采集完成后 1~2 分钟生效。

**时间戳是 UTC 还是北京时？** 视频水印是北京时间（UTC+8），标注 `CST`。

**流量/成本？** GitHub Actions 免费额度 public 仓库无限量；Pages 免费托管。本项目每次约下载 16 tile × 140 帧 ≈ 2200 张图，单次约 12 分钟，完全在免费额度内。

**NICT 直连失败？** 数据源在日本，国内/公司网络可能直连不稳。项目在 GitHub Actions（境外 runner）上运行不受影响；如本地调试，可配置代理或换节点。

## 许可

代码 MIT。卫星影像版权归 JMA / NICT，仅供个人、非商业使用。
