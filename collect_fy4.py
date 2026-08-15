#!/usr/bin/env python3
"""
LiveEarth — FY-4B 云图动画（风云四号 B 星，GitHub Pages 增量版）
=================================================================

数据源：NSMC 国家卫星气象中心 FY-4B GeoColor 全盘图（仅提供"最新一张"直链）
  https://img.nsmc.org.cn/CLOUDIMAGE/FY4B/AGRI/GCLR/FY4B_DISK_GCLR.JPG

每次运行（workflow cron 每 30 分钟）：
  1. 下载 NSMC 最新一张（~11MB）
  2. 压缩到 720×720 JPEG（~200KB），盖掉 NSMC 官方水印 + 加北京时间戳
  3. 存入 frames/fy4/（文件名 = 拍摄时间，天然时间序）
  4. 清理 WINDOW_HOURS 之前的旧帧
  5. 用积累的帧合成 fy4.mp4（H.264, 6fps）
  6. 输出 index2.html + fy4.mp4 到 dist/

frames/ 由 GitHub Actions cache 持久化（免费 10GB），70h×30min≈140帧×200KB≈28MB。
首次部署后需积累约 3 天才有完整 70h 动画，之后滚动更新。

依赖: pip install pillow
合成: 需要 ffmpeg（GitHub Actions runner 已安装）
"""

import io
import os
import re
import sys
import time
import shutil
import datetime
import tempfile
import subprocess
import urllib.request
from email.utils import parsedate_to_datetime
from PIL import Image, ImageDraw, ImageFont

# NSMC 全盘图实测 10992×11912 ≈ 1.3 亿像素，超过 PIL 默认 DecompressionBomb 上限，
# 必须放宽，否则 Image.open 直接拒绝。
Image.MAX_IMAGE_PIXELS = 300_000_000
Image.DecompressionBombWarning = Image.DecompressionBombError  # 上限内不再警告

# =====================================================================
#  配置（均可用环境变量覆盖）
# =====================================================================

SOURCE_URL = os.environ.get(
    "FY4_SOURCE_URL",
    "https://img.nsmc.org.cn/CLOUDIMAGE/FY4B/AGRI/GCLR/FY4B_DISK_GCLR.JPG",
)

OUT_W = int(os.environ.get("OUT_W", "720"))      # 输出画布（方形，完整地球）
OUT_H = int(os.environ.get("OUT_H", "720"))
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "82"))

WINDOW_HOURS = int(os.environ.get("WINDOW_HOURS", "70"))   # 动画时间窗
FRAME_STEP_MIN = int(os.environ.get("FRAME_STEP_MIN", "30"))
FPS = int(os.environ.get("FPS", "6"))
CRF = os.environ.get("CRF", "23")
MAX_DOWNLOAD_RETRY = int(os.environ.get("MAX_DOWNLOAD_RETRY", "4"))

FRAMES_DIR = os.environ.get("FY4_FRAMES_DIR", "frames/fy4")
DIST_DIR = os.environ.get("DIST_DIR", "dist")

# NSMC 图片尺寸（实测 10992×11912 全盘图）；地球圆盘几何常量
EARTH_CENTER_X = 5494
EARTH_CENTER_Y = 5913
WATERMARK_BOX = (66, 85, 1706, 543)   # NSMC 官方水印区域（左下角），盖黑

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

# 模拟浏览器，避免被 NSMC 拦截
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "image/jpeg,image/png,*/*",
    "Referer": "https://www.nsmc.org.cn/",
}


# =====================================================================
#  SSL（NSMC 有 TLS 怪癖，用宽松上下文）
# =====================================================================

def make_ssl_ctx():
    ctx = __import__("ssl").create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = __import__("ssl").CERT_NONE
    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    except Exception:
        pass
    return ctx


SSL_CTX = make_ssl_ctx()


# =====================================================================
#  下载
# =====================================================================

def download_latest(timeout=90):
    """下载 NSMC 最新全盘图，返回 (bytes, capture_time_utc)。
    拍摄时间从 HTTP Last-Modified 解析（NSMC 不提供历史帧 URL）。"""
    last_err = None
    for attempt in range(1, MAX_DOWNLOAD_RETRY + 1):
        try:
            req = urllib.request.Request(SOURCE_URL, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                data = resp.read()
                lm_raw = resp.headers.get("Last-Modified")
            capture = None
            if lm_raw:
                try:
                    capture = parsedate_to_datetime(lm_raw)
                    if capture.tzinfo is None:
                        capture = capture.replace(tzinfo=datetime.timezone.utc)
                    else:
                        capture = capture.astimezone(datetime.timezone.utc)
                except Exception as e:
                    print(f"    [warn] parse Last-Modified failed: {e}")
            print(f"    [OK] {len(data)/1024/1024:.2f} MB, Last-Modified={lm_raw}")
            return data, capture
        except Exception as e:
            last_err = e
            print(f"    [warn] attempt {attempt} failed: {e}")
            time.sleep(2 * attempt)
    raise RuntimeError(f"download failed after {MAX_DOWNLOAD_RETRY} tries: {last_err}")


# =====================================================================
#  帧处理
# =====================================================================

def load_font(size):
    for p in FONT_PATHS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_frame(data, out_path, capture):
    """解压 → 盖 NSMC 水印 → 裁剪地球圆盘 → 缩放到 720×720 → 加北京时水印 → 存 JPEG。"""
    img = Image.open(io.BytesIO(data)).convert("RGB")

    # 1) 盖掉 NSMC 官方水印
    ImageDraw.Draw(img).rectangle(WATERMARK_BOX, fill=(0, 0, 0))

    # 2) 裁剪出地球圆盘（方形，以圆心为中心；原图 10992×11912 留 2h 余量）
    half = min(EARTH_CENTER_X - 54, EARTH_CENTER_Y)   # 圆盘半径（像素）
    left = EARTH_CENTER_X - half
    top = EARTH_CENTER_Y - half
    img = img.crop((left, top, left + 2 * half, top + 2 * half))

    # 3) 缩放到输出尺寸
    img = img.resize((OUT_W, OUT_H), Image.LANCZOS)

    # 4) 加北京时水印（右下角）
    if capture is not None:
        beijing = capture + datetime.timedelta(hours=8)
        text = f"FY-4B  {beijing.strftime('%Y-%m-%d %H:%M')} CST"
    else:
        text = "FY-4B"
    font_size = max(18, int(OUT_H * 0.03))
    font = load_font(font_size)
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    margin = max(10, int(OUT_H * 0.025))
    pos = (OUT_W - tw - margin, OUT_H - th - margin)
    for dx in (-2, -1, 0, 1, 2):
        for dy in (-2, -1, 0, 1, 2):
            if dx or dy:
                draw.text((pos[0] + dx, pos[1] + dy), text, font=font, fill=(0, 0, 0))
    draw.text(pos, text, font=font, fill=(235, 235, 235))

    img.save(out_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return out_path


# =====================================================================
#  帧管理（增量）
# =====================================================================

FRAME_NAME_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})\.jpg$")


def frame_time(path):
    m = FRAME_NAME_RE.match(os.path.basename(path))
    if not m:
        return None
    y, mo, d, h, mi = (int(x) for x in m.groups())
    return datetime.datetime(y, mo, d, h, mi, tzinfo=datetime.timezone.utc)


def prune_frames(now_utc):
    """删除超过 WINDOW_HOURS 的旧帧，返回剩余帧（时间正序）。"""
    cutoff = now_utc - datetime.timedelta(hours=WINDOW_HOURS)
    kept = []
    if not os.path.isdir(FRAMES_DIR):
        os.makedirs(FRAMES_DIR, exist_ok=True)
        return kept
    for name in sorted(os.listdir(FRAMES_DIR)):
        if not name.endswith(".jpg"):
            continue
        path = os.path.join(FRAMES_DIR, name)
        t = frame_time(path)
        if t is None:
            continue
        if t < cutoff:
            os.remove(path)
            print(f"    [prune] {name}")
        else:
            kept.append(path)
    return kept


def dedupe(kept, capture):
    """如果已有同一时间点的帧则跳过（同名文件）。"""
    if capture is None:
        return None
    name = capture.strftime("%Y%m%d_%H%M") + ".jpg"
    path = os.path.join(FRAMES_DIR, name)
    if os.path.exists(path):
        return None
    return path


# =====================================================================
#  合成 MP4
# =====================================================================

def build_mp4(frame_paths, out_path):
    """按时间序合成 MP4（用文件列表而非 glob，保证严格时间序）。"""
    if len(frame_paths) < 2:
        print(f"    [warn] only {len(frame_paths)} frames, need >=2 to build mp4")
        return False
    list_file = os.path.join(os.path.dirname(out_path), "fy4_frames.txt")
    with open(list_file, "w") as f:
        for p in frame_paths:
            # ffmpeg concat demuxer: 每行 file '<path>'，路径原样写入（无 shell 层，无需转义）
            f.write(f"file '{os.path.abspath(p)}'\n")
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),          # 输入选项：必须在 -i 之前
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", CRF,
        "-movflags", "+faststart",
        out_path,
    ]
    print(f"    [ffmpeg] {' '.join(cmd)}")
    if shutil.which("ffmpeg") is None:
        print("    [warn] ffmpeg not found in PATH; skipping mp4 build (frames still saved)")
        return False
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        print(r.stderr[-2000:])
        raise RuntimeError(f"ffmpeg exit={r.returncode}")
    print(f"    [mp4] {out_path} ({os.path.getsize(out_path)/1024/1024:.2f} MB)")
    return True


# =====================================================================
#  主流程
# =====================================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print(f"LiveEarth FY-4B — {datetime.datetime.now(datetime.timezone.utc).isoformat()}")
    print("=" * 70)

    now = datetime.datetime.now(datetime.timezone.utc)

    # 1) 恢复已有帧并清理旧帧
    kept = prune_frames(now)
    print(f"[frames] existing after prune: {len(kept)}")

    # 2) 下载最新一张
    print("[download] fetching latest FY-4B...")
    data, capture = download_latest()

    # 3) 去重后存入帧库
    new_path = dedupe(kept, capture)
    if new_path is not None:
        os.makedirs(FRAMES_DIR, exist_ok=True)
        render_frame(data, new_path, capture)
        print(f"[frames] added {os.path.basename(new_path)}")
        kept.append(new_path)
    else:
        print("[frames] latest already in store (same timestamp), skipping")

    # 4) 重新按时间排序 + 再次清理（新帧可能触发边界）
    kept = prune_frames(now)
    kept = [p for p in kept if os.path.exists(p)]
    print(f"[frames] total in window: {len(kept)}")

    # 5) 合成 MP4
    os.makedirs(DIST_DIR, exist_ok=True)
    mp4_path = os.path.join(DIST_DIR, "fy4.mp4")
    mp4_ok = build_mp4(kept, mp4_path)

    # 6) 复制页面（无论视频是否就绪都部署，页面可先存在）
    idx_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "index2.html")
    if os.path.exists(idx_src):
        shutil.copy(idx_src, os.path.join(DIST_DIR, "index2.html"))
        print("[dist] index2.html copied")

    if mp4_ok:
        print(f"[dist] fy4.mp4 ready ({os.path.getsize(mp4_path)/1024/1024:.2f} MB)")
    else:
        print("[dist] no fy4.mp4 yet (need >=2 frames; accumulating)")

    print(f"[done] elapsed {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
