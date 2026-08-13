# LiveEarth — Himawari-8 完整地球云图动画

过去 **70 小时**的 Himawari-8（向日葵 8 号）真彩色**完整地球**延时动画。云端每 30 分钟自动下载、合成 MP4，浏览器打开即看，本地不做任何保存。

> 灵感来自 [LiveEarth-FY4B-Wallpaper](https://github.com/whuchenshuo/LiveEarth-FY4B-Wallpaper)，数据源换成日本 Himawari-8，输出从桌面壁纸改成了网页 MP4 动画。

## 架构

```
GitHub Actions（每 30 分钟）
  │ 直接从 NICT 下载过去 70h 的 140 帧（每帧 16 个 tile 拼成完整地球）
  │ 缩放 → 叠北京时间水印
  │ ffmpeg 合成 MP4（H.264, 6fps）
  ▼
GitHub Pages（托管 index.html + latest.mp4）
  ▼
浏览器（<video> 播放器，带播放控制）
```

**零存储依赖**：NICT 自身保留 72h+ 历史数据（本项目取 70h，留 2h 余量），无需 R2 / 数据库。
**零密钥**：只依赖 GitHub 内置 GITHUB_TOKEN，无需配置任何 secret，无需绑信用卡。

## 数据源

- **卫星**：Himawari-8（日本气象厅 JMA），静止轨道 140.7°E
- **产品**：D531106 真彩色全盘图（True Color Reproduction）
- **更新频率**：每 **10 分钟**
- **提供方**：NICT（日本国立情报通信研究机构）
- **历史保留**：至少 72 小时

```
https://himawari8.nict.go.jp/img/D531106/{level}d/550/{Y}/{m}/{d}/{HHMMSS}_{x}_{y}.png
```

> `{level}` = 每边的 tile 数；每个 tile 固定 550×550，x=列（水平），y=行（垂直）。

| level | 拼接分辨率 | tile 数 | 适用 |
|---|---|---|---|
| 1d  | 550×550     | 1     | 预览 |
| 4d  | 2200×2200   | 16    | 720（默认）|
| 8d  | 4400×4400   | 64    | 1080 |
| 16d | 8800×8800   | 256   | 4K |
| 20d | 11000×11000 | 400   | 原生分辨率 |

⚠️ 版权：数据归 JMA / NICT，**禁止商用**，仅供个人使用。

## 快速开始（2 步）

### 第 1 步：启用 GitHub Pages

1. 打开仓库 **Settings → Pages**
2. **Source** 选 `Deploy from a branch`
3. **Branch** 选 `gh-pages` → `/ (root)` → 保存
4. 网址：`https://znwvip.github.io/liveearth-himawari/`

> 首次需手动点这一次；之后 workflow 每次自动部署。注意：gh-pages 分支要等第一次 workflow 跑完才会出现。

### 第 2 步：手动触发一次

1. 仓库 → **Actions** → `collect-himawari` → **Run workflow**
2. 等 5~10 分钟（下载 140 帧 × 16 tile + 合成 + 部署）
3. 打开网页看动画

> 之后每 30 分钟自动更新，无需再管。

## 网页播放控制

- **播放/暂停**：点视频，或按空格
- **进度条**：直接拖动跳到任意时间
- **倍速**：0.5× / 1× / 2× / 4×
- **循环**：默认开启，可关闭
- **全屏**：右下角按钮
- **快退/快进**：键盘 ← →（每次 5 秒）

## 自定义

### 换分辨率（720 → 1080）

编辑 `.github/workflows/collect.yml` 的 env：

```yaml
OUT_W: "1080"
OUT_H: "1080"
ZOOM: "8"        # 1080 建议用 8d（4400×4400）
```

### 改时间窗 / 抽帧间隔 / 帧率

`collect.py` 顶部（也可用环境变量覆盖）：

| 变量 | 默认 | 含义 |
|---|---|---|
| `WINDOW_HOURS` | 70 | 动画时间窗（小时）|
| `FRAME_STEP_MIN` | 30 | MP4 抽帧间隔（分钟）|
| `FPS` | 6 | MP4 帧率 |
| `CRF` | 23 | H.264 质量（越小越清晰，文件越大）|
| `MAX_WORKERS` | 4 | 并发下载线程数 |

### 改采集频率

编辑 `collect.yml` 的 cron。当前 `*/30 * * * *` = 每 30 分钟。

## 目录结构

```
liveearth-himawari/
├── collect.py                    # 采集 + 合成主脚本
├── .github/workflows/collect.yml # 定时任务
├── web/index.html                # 播放器页面
└── README.md
```

## 常见问题

**第一次跑很慢？** 正常，要下载 140 帧 × 16 tile。每次约 5~10 分钟。

**网页 404？** 确认 Settings → Pages 的 Source 已选 gh-pages 分支；且 workflow 至少跑成功过一次。

**动画有几帧缺失？** NICT 偶有单帧 404，脚本会自动跳过该帧。

**时间戳是 UTC 还是北京时？** 视频水印是北京时间（UTC+8）。

**成本？** 全部免费：GitHub Actions（public 仓库无限分钟）+ Pages 托管。

## 许可

代码 MIT。卫星影像版权归 JMA / NICT，仅供个人、非商业使用。
