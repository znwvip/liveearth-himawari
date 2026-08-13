# LiveEarth — Himawari-8 云图动画

过去 **48 小时**的 Himawari-8（向日葵 8 号）真彩色地球云图延时动画，云端自动采集合成 MP4，浏览器打开即看，本地不做任何保存。

> 灵感来自 [LiveEarth-FY4B-Wallpaper](https://github.com/whuchenshuo/LiveEarth-FY4B-Wallpaper)，数据源换成了日本 Himawari-8，输出从桌面壁纸改成了网页 MP4 动画。

## 架构

```
GitHub Actions（每 30 分钟）
  │ 直接从 NICT 下载过去 48h 的 96 帧（每帧 4 tile 拼接）
  │ 裁剪 16:9 → 720p → 北京时间水印
  │ ffmpeg 合成 MP4（H.264, 6fps）
  ▼
GitHub Pages（托管 index.html + latest.mp4）
  ▼
浏览器（<video> 播放器，带播放控制）
```

**零存储依赖**：NICT 自身保留 72h+ 历史数据，每次直接从它拉取，无需 R2 / 数据库。
**零密钥**：只依赖 GitHub 内置 GITHUB_TOKEN，无需配置任何 secret，无需绑信用卡。

## 数据源

- **卫星**：Himawari-8（日本气象厅 JMA），静止轨道 140.7°E
- **产品**：D531106 真彩色全盘图（True Color Reproduction）
- **更新频率**：每 **10 分钟**
- **提供方**：NICT（日本国立情报通信研究机构）
- **历史保留**：至少 72 小时

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

## 快速开始（2 步）

### 第 1 步：启用 GitHub Pages

1. 打开仓库 **Settings → Pages**
2. **Source** 选 `Deploy from a branch`
3. **Branch** 选 `gh-pages` → `/ (root)` → 保存
4. 记下网址：`https://znwvip.github.io/liveearth-himawari/`

> 首次需要手动点这一次；之后 workflow 每次自动把最新动画推到这个分支。

### 第 2 步：手动触发一次

1. 仓库 → **Actions** → 左侧 `collect-himawari` → **Run workflow**
2. 等 3~5 分钟（下载 96 帧 + 合成 + 部署）
3. 打开 `https://znwvip.github.io/liveearth-himawari/` 看动画

> 之后每 30 分钟自动更新，你不用再管。

## 网页播放控制

- **播放/暂停**：点视频，或按空格
- **进度条**：直接拖动跳到任意时间
- **倍速**：0.5× / 1× / 2× / 4×
- **循环**：默认开启，可关闭
- **全屏**：右下角按钮或双击视频
- **快退/快进**：键盘 ← →（每次 5 秒）

## 自定义

### 换分辨率（720p → 1080p）

编辑 `.github/workflows/collect.yml` 的 env：

```yaml
OUT_W: "1920"
OUT_H: "1080"
ZOOM: "8"        # 1080p 建议用 8d（2200px）
```

### 改抽帧间隔 / 时间窗 / 帧率

`collect.py` 顶部（也可用环境变量覆盖）：

| 变量 | 默认 | 含义 |
|---|---|---|
| `WINDOW_HOURS` | 48 | 动画时间窗 |
| `FRAME_STEP_MIN` | 30 | MP4 抽帧间隔（分钟）|
| `FPS` | 6 | MP4 帧率 |
| `CRF` | 23 | H.264 质量（越小越清晰，文件越大）|
| `MAX_WORKERS` | 8 | 并发下载线程数 |

### 改采集频率

编辑 `collect.yml` 的 cron。当前 `*/30 * * * *` 表示每 30 分钟。

## 目录结构

```
liveearth-himawari/
├── collect.py                    # 采集 + 合成主脚本
├── .github/workflows/collect.yml # 定时任务
├── web/index.html                # 播放器页面
└── README.md
```

## 常见问题

**第一次跑很慢？** 正常，要下载 96 帧。之后每次也差不多 3~5 分钟。

**网页 404？** 确认 Settings → Pages 的 Source 已选 gh-pages 分支；第一次 workflow 跑完才会生成页面。

**动画有几帧缺失？** NICT 偶有单帧 404，脚本会自动跳过该帧，不影响整体。

**时间戳是 UTC 还是北京时？** 视频水印是北京时间（UTC+8）。

**成本？** 全部免费：GitHub Actions（public 仓库无限分钟）+ Pages 托管，无需任何付费服务。

## 许可

代码 MIT。卫星影像版权归 JMA / NICT，仅供个人、非商业使用。
