#!/usr/bin/env python3
"""
LiveEarth — Himawari-8 云图动画（GitHub Pages 版）
=================================================

每 30 分钟跑一次（GitHub Actions cron）：
  1. 从 NICT 直接下载过去 48h 内每 30 分钟一帧（每帧 4 个 tile 拼接）
  2. 裁剪 16:9 → 缩放 720p → 叠北京时间水印
  3. ffmpeg 合成 MP4（H.264, 6fps）
  4. 输出 index.html + latest.mp4 到 dist/，交给 GitHub Pages 部署

零存储依赖：NICT 自身保留 72h+ 历史数据，无需任何对象存储/数据库。
零密钥依赖：只依赖 GitHub 内置的 GITHUB_TOKEN（部署 Pages 用）。

依赖: pip install pillow
合成: 需要 ffmpeg（GitHub Actions runner 已安装）
"""

import io
import os
import ssl
import sys
import time
import shutil
import datetime
import tempfile
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image, ImageDraw, ImageFont

# =====================================================================
#  配置（均可用环境变量覆盖）
# =====================================================================

ZOOM = int(os.environ.get("ZOOM", "4"))          # 4d = 1100×1100；8d = 2200×2200
TILE = 550                                        # 单个 tile 边长（NICT 固定 550）
GRID = {1: 1, 4: 2, 8: 4, 16: 8, 20: 20}.get(ZOOM, 2)

OUT_W = int(os.environ.get("OUT_W", "1280"))
OUT_H = int(os.environ.get("OUT_H", "720"))
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "85"))

WINDOW_HOURS = int(os.environ.get("WINDOW_HOURS", "48"))
FRAME_STEP_MIN = int(os.environ.get("FRAME_STEP_MIN", "30"))
FPS = int(os.environ.get("FPS", "6"))
CRF = os.environ.get("CRF", "23")
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "4"))

URL_TEMPLATE = (
    "https://himawari8.nict.go.jp/img/D531106/{zoom}d/{tile}/"
    "{year}/{month}/{day}/{time}_{x}_{y}.png"
)

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

# =====================================================================
#  SSL / 下载
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
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                return resp.read()
        except Exception as e:
            last_err = e
            time.sleep(1.5 * attempt)
    raise RuntimeError(f"download failed after {retries} tries: {last_err}")


# =====================================================================
#  时间点
# =====================================================================

def build_slots():
    """生成 48h 内每 FRAME_STEP_MIN 分钟一个的 UTC 时间点（时间正序）。"""
    now = datetime.datetime.now(datetime.timezone.utc)
    latest = now.replace(second=0, microsecond=0)
    latest -= datetime.timedelta(minutes=latest.minute % 10)   # 对齐 10 分钟
    latest -= datetime.timedelta(minutes=20)                    # 确保已发布

    slots = []
    slot = latest
    cutoff = now - datetime.timedelta(hours=WINDOW_HOURS)
    while slot >= cutoff:
        slots.append(slot)
        slot -= datetime.timedelta(minutes=FRAME_STEP_MIN)
    slots.reverse()
    return slots


# =====================================================================
#  单帧渲染
# =====================================================================

def load_font(size):
    for p in FONT_PATHS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_frame(slot, out_path):
    """下载 4 tile → 拼接 → 裁剪 16:9 → 缩放 → 水印 → 存 JPEG。"""
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

    # 裁剪 16:9（取中央带，保留赤道云带）
    w, h = canvas.size
    crop_h = round(w * OUT_H / OUT_W)
    top = max(0, (h - crop_h) // 2)
    img = canvas.crop((0, top, w, top + crop_h)).resize((OUT_W, OUT_H), Image.LANCZOS)

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
    for dx in (-2, -1, 0, 1, 2):
        for dy in (-2, -1, 0, 1, 2):
            if dx or dy:
                draw.text((pos[0] + dx, pos[1] + dy), text, font=font, fill=(0, 0, 0))
    draw.text(pos, text, font=font, fill=(235, 235, 235))

    img.save(out_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return out_path


# =====================================================================
#  合成 MP4
# =====================================================================

def build_mp4(frame_paths, out_path):
    list_file = os.path.join(os.path.dirname(out_path), "list.txt")
    with open(list_file, "w") as f:
        for p in frame_paths:
            f.write(f"file '{p}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-f", "concat", "-safe", "0", "-i", list_file,
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


# =====================================================================
#  主流程
# =====================================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print(f"LiveEarth Himawari-8 — {datetime.datetime.now(datetime.timezone.utc).isoformat()}")
    print("=" * 70)

    slots = build_slots()
    print(f"[slots] {len(slots)} frames ({WINDOW_HOURS}h, every {FRAME_STEP_MIN}min)")

    tmp = tempfile.mkdtemp(prefix="liveearth_")
    idx_by_slot = {slot: i for i, slot in enumerate(slots)}

    # 并发渲染所有帧
    print(f"[render] downloading & rendering {len(slots)} frames ({MAX_WORKERS} workers)...")
    results = {}
    errors = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {}
        for i, slot in enumerate(slots):
            out = os.path.join(tmp, f"{i:04d}_{slot.strftime('%Y%m%d_%H%M')}.jpg")
            futures[ex.submit(render_frame, slot, out)] = slot
        done = 0
        for fut in as_completed(futures):
            slot = futures[fut]
            try:
                fut.result()
                i = idx_by_slot[slot]
                results[slot] = os.path.join(tmp, f"{i:04d}_{slot.strftime('%Y%m%d_%H%M')}.jpg")
            except Exception as e:
                errors.append((slot, str(e)))
                print(f"    [warn] frame {slot.strftime('%Y%m%d %H:%M')} failed: {e}")
            done += 1
            if done % 16 == 0:
                print(f"      {done}/{len(slots)} done")

    # 按时间顺序收集成功帧
    ok_paths = [results[s] for s in slots if s in results]
    print(f"[frames] {len(ok_paths)}/{len(slots)} succeeded")

    if len(ok_paths) < 2:
        print(f"[FATAL] too few frames ({len(ok_paths)}/{len(slots)}), abort")
        for s, e in errors[:5]:
            print(f"  sample error [{s.strftime('%Y-%m-%d %H:%M')}]: {e}")
        sys.exit(1)

    # 合成 MP4
    print("[mp4] building...")
    build_mp4(ok_paths, "latest.mp4")
    size = os.path.getsize("latest.mp4") / 1024 / 1024
    print(f"[mp4] latest.mp4 ({size:.2f} MB)")

    # 输出到 dist/（index.html + latest.mp4）
    dist = "dist"
    if os.path.exists(dist):
        shutil.rmtree(dist)
    os.makedirs(dist)
    shutil.move("latest.mp4", os.path.join(dist, "latest.mp4"))
    idx_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "index.html")
    if os.path.exists(idx_src):
        shutil.copy(idx_src, os.path.join(dist, "index.html"))
    print(f"[dist] index.html + latest.mp4 ready")

    print(f"[done] elapsed {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
