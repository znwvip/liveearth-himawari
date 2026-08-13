#!/usr/bin/env python3
"""
LiveEarth — Himawari-8 云图动画采集器
======================================

每 10 分钟跑一次（GitHub Actions cron）：
  1. 从 NICT 下载 Himawari-8 真彩色全盘图（4d = 2×2 tile，拼接 1100×1100）
  2. 裁剪 16:9 → 缩放到 720p（可配置 1080p）
  3. 叠加北京时间水印
  4. 上传单帧到 Cloudflare R2（frames/ 目录，按时间戳命名）
  5. 清理 48 小时前的旧帧
  6. 抽取 48h 内每 30 分钟一帧，用 ffmpeg 合成 MP4（H.264, 6fps）
  7. 上传 MP4 到 R2（latest.mp4，供网页 <video> 播放）

数据源: NICT Himawari-8 Real-time Web
  https://himawari8.nict.go.jp/img/D531106/{zoom}d/550/{Y}/{m}/{d}/{HHMMSS}_{x}_{y}.png
  真彩色全盘图每 10 分钟更新一次。

依赖: pip install pillow boto3
合成: 需要 ffmpeg（GitHub Actions runner 已安装）
"""

import io
import os
import ssl
import sys
import time
import datetime
import subprocess
import urllib.request
from PIL import Image, ImageDraw, ImageFont

# =====================================================================
#  配置（均可用环境变量覆盖）
# =====================================================================

ZOOM = int(os.environ.get("ZOOM", "4"))          # 4d = 1100×1100；8d = 2200×2200
TILE = 550                                        # 单个 tile 边长（NICT 固定 550）
GRID = {1: 1, 4: 2, 8: 4, 16: 8, 20: 20}.get(ZOOM, 2)  # tile 网格数

OUT_W = int(os.environ.get("OUT_W", "1280"))      # 输出宽度
OUT_H = int(os.environ.get("OUT_H", "720"))       # 输出高度（16:9）
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "82"))

WINDOW_HOURS = int(os.environ.get("WINDOW_HOURS", "48"))          # 动画时间窗
FRAME_STEP_MIN = int(os.environ.get("FRAME_STEP_MIN", "30"))      # MP4 抽帧间隔（分钟）
FPS = int(os.environ.get("FPS", "6"))                             # MP4 帧率
CRF = os.environ.get("CRF", "23")                                 # H.264 质量（越小越清晰）

# 数据源 URL 模板
URL_TEMPLATE = (
    "https://himawari8.nict.go.jp/img/D531106/{zoom}d/{tile}/"
    "{year}/{month}/{day}/{time}_{x}_{y}.png"
)

# 水印字体（ubuntu runner 自带 DejaVu，无中文字体，故用英文）
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

# =====================================================================
#  SSL（NICT 偶有 TLS 怪癖，用宽松上下文）
# =====================================================================

def make_ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    except ssl.SSLError:
        pass
    return ctx

SSL_CTX = make_ssl_ctx()


def fetch(url, timeout=30, retries=3):
    """下载 URL，带重试。"""
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                return resp.read()
        except Exception as e:
            last_err = e
            print(f"    [warn] fetch retry {attempt}/{retries}: {e}")
            time.sleep(2 * attempt)
    raise RuntimeError(f"download failed after {retries} tries: {last_err}")


# =====================================================================
#  时间计算
# =====================================================================

def latest_slot():
    """返回最近一个『已发布』的 10 分钟对齐 UTC 时间点。

    Himawari 全盘每 10 分钟观测一次，NICT 发布有约 10-20 分钟延迟，
    所以取当前时间对齐到 10 分钟后，再往前推 20 分钟以确保图片存在。
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    slot = now.replace(second=0, microsecond=0) - datetime.timedelta(minutes=now.minute % 10)
    slot -= datetime.timedelta(minutes=20)
    return slot


def slot_to_key(slot):
    """帧文件名：UTC 时间 YYYYMMDD_HHMM.jpg"""
    return slot.strftime("%Y%m%d_%H%M") + ".jpg"


def key_to_slot(key):
    """从帧文件名反解 UTC 时间。"""
    stem = key.replace(".jpg", "")
    return datetime.datetime.strptime(stem, "%Y%m%d_%H%M").replace(tzinfo=datetime.timezone.utc)


# =====================================================================
#  下载 + 拼接
# =====================================================================

def download_frame(slot):
    """下载 4d 全盘图（GRID×GRID 个 tile）并拼接成一张方图。"""
    d = slot.strftime("%Y/%m/%d")
    t = slot.strftime("%H%M%S")
    year, month, day = slot.strftime("%Y"), slot.strftime("%m"), slot.strftime("%d")

    tiles = []
    for x in range(GRID):
        row = []
        for y in range(GRID):
            url = URL_TEMPLATE.format(
                zoom=ZOOM, tile=TILE, year=year, month=month, day=day,
                time=t, x=x, y=y,
            )
            data = fetch(url)
            row.append(Image.open(io.BytesIO(data)).convert("RGB"))
        tiles.append(row)

    canvas = Image.new("RGB", (TILE * GRID, TILE * GRID))
    for x in range(GRID):
        for y in range(GRID):
            canvas.paste(tiles[x][y], (y * TILE, x * TILE))
    return canvas


# =====================================================================
#  处理：裁剪 + 缩放 + 水印
# =====================================================================

def load_font(size):
    for p in FONT_PATHS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def process(img, slot):
    """裁剪为 16:9（取中央带，保留赤道云带）→ 缩放到目标分辨率 → 水印。"""
    w, h = img.size
    crop_h = round(w * OUT_H / OUT_W)          # 按目标宽高比裁剪
    top = max(0, (h - crop_h) // 2)
    img = img.crop((0, top, w, top + crop_h))
    img = img.resize((OUT_W, OUT_H), Image.LANCZOS)

    # 水印（北京时）
    beijing = slot + datetime.timedelta(hours=8)
    text = f"Himawari-8  {beijing.strftime('%Y-%m-%d %H:%M')} CST"
    font_size = max(18, int(OUT_H * 0.03))
    font = load_font(font_size)
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    margin = max(10, int(OUT_H * 0.025))
    pos = (OUT_W - tw - margin, OUT_H - th - margin)

    # 黑色描边 + 白色前景
    for dx in (-2, -1, 0, 1, 2):
        for dy in (-2, -1, 0, 1, 2):
            if dx or dy:
                draw.text((pos[0] + dx, pos[1] + dy), text, font=font, fill=(0, 0, 0))
    draw.text(pos, text, font=font, fill=(235, 235, 235))
    return img


def img_to_jpeg_bytes(img):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


# =====================================================================
#  Cloudflare R2（S3 兼容，boto3）
# =====================================================================

def r2_client():
    import boto3
    from botocore.config import Config
    account = os.environ["R2_ACCOUNT_ID"]
    endpoint = f"https://{account}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4", region_name="auto"),
    ), os.environ["R2_BUCKET"]


def list_frame_keys(s3, bucket):
    """列出 R2 上 frames/ 目录下所有帧文件名。"""
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix="frames/"):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            if k.endswith(".jpg"):
                keys.append(k.split("/")[-1])
    return sorted(keys)


def cleanup_frames(s3, bucket, keys, cutoff):
    """删除 48h 前的旧帧。"""
    removed = 0
    for k in keys:
        try:
            if key_to_slot(k) < cutoff:
                s3.delete_object(Bucket=bucket, Key=f"frames/{k}")
                removed += 1
        except Exception as e:
            print(f"    [warn] cleanup {k}: {e}")
    return removed


# =====================================================================
#  合成 MP4
# =====================================================================

def build_mp4(s3, bucket, keys, out_path):
    """抽取时间窗内每 FRAME_STEP_MIN 分钟一帧，下载后合成 MP4。"""
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(hours=WINDOW_HOURS)

    # 选帧：48h 内，且分钟数能被 FRAME_STEP_MIN 整除
    picked = []
    for k in keys:
        try:
            slot = key_to_slot(k)
        except Exception:
            continue
        if slot >= cutoff and slot.minute % FRAME_STEP_MIN == 0:
            picked.append(k)

    if len(picked) < 2:
        print(f"[skip] not enough frames ({len(picked)}), need >= 2")
        return None

    import tempfile
    tmp = tempfile.mkdtemp(prefix="liveearth_")
    try:
        # 下载帧
        local_files = []
        for k in picked:
            local = os.path.join(tmp, k)
            s3.download_file(bucket, f"frames/{k}", local)
            local_files.append(local)

        # 写 concat 列表
        list_file = os.path.join(tmp, "list.txt")
        with open(list_file, "w") as f:
            for lf in local_files:
                f.write(f"file '{lf}'\n")

        # ffmpeg 合成
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", list_file,
            "-vf", f"fps={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", CRF,
            "-movflags", "+faststart",
            out_path,
        ]
        print(f"[ffmpeg] {' '.join(cmd)}")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(r.stderr[-2000:])
            raise RuntimeError(f"ffmpeg exit={r.returncode}")
        return out_path
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# =====================================================================
#  主流程
# =====================================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print(f"LiveEarth Himawari-8 collector — {datetime.datetime.now(datetime.timezone.utc).isoformat()}")
    print("=" * 70)

    if not all(k in os.environ for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")):
        print("[FATAL] Missing R2 env vars (R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_BUCKET)")
        sys.exit(1)

    s3, bucket = r2_client()
    slot = latest_slot()
    print(f"[slot] {slot.isoformat()} (UTC)")

    # 1. 下载 + 拼接
    print("[1/5] download & stitch tiles...")
    img = download_frame(slot)
    print(f"      stitched {img.size[0]}x{img.size[1]}")

    # 2. 裁剪 + 缩放 + 水印
    print("[2/5] crop + resize + watermark...")
    img = process(img, slot)

    # 3. 上传单帧
    print("[3/5] upload frame to R2...")
    key = slot_to_key(slot)
    jpeg_bytes = img_to_jpeg_bytes(img)
    s3.put_object(Bucket=bucket, Key=f"frames/{key}",
                  Body=jpeg_bytes, ContentType="image/jpeg")
    print(f"      frames/{key} ({len(jpeg_bytes) / 1024:.0f} KB)")

    # 4. 清理旧帧
    print("[4/5] cleanup old frames...")
    all_keys = list_frame_keys(s3, bucket)
    cutoff = slot - datetime.timedelta(hours=WINDOW_HOURS)
    removed = cleanup_frames(s3, bucket, all_keys, cutoff)
    print(f"      {len(all_keys)} frames total, removed {removed} older than {WINDOW_HOURS}h")

    # 5. 合成 MP4 + 上传
    print("[5/5] build & upload MP4...")
    mp4 = build_mp4(s3, bucket, all_keys, "latest.mp4")
    if mp4:
        s3.upload_file("latest.mp4", bucket, "latest.mp4",
                       ExtraArgs={"ContentType": "video/mp4"})
        size = os.path.getsize("latest.mp4") / 1024 / 1024
        print(f"      latest.mp4 uploaded ({size:.2f} MB)")
    else:
        print("      (no MP4 this run — need more frames)")

    # 6. 上传网页播放器（保证 R2 上始终有最新版）
    idx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "index.html")
    if os.path.exists(idx_path):
        with open(idx_path, "rb") as f:
            s3.put_object(Bucket=bucket, Key="index.html",
                          Body=f.read(), ContentType="text/html; charset=utf-8")
        print("      web/index.html -> index.html (uploaded)")

    print(f"[done] elapsed {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
