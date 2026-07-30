#!/usr/bin/env bash
# 从确定性 HTML 场景生成最终竖屏 4K / 60fps / H.264 宣传片。
# 运行：bash artifacts/promo/build.sh
# 可按需覆盖：WIDTH=1080 HEIGHT=1920 OUT_NAME=jobradar-promo.mp4 bash artifacts/promo/build.sh
set -euo pipefail

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
FRAMES="$HERE/.work/frames"
WIDTH="${WIDTH:-2160}"
HEIGHT="${HEIGHT:-3840}"
OUT_NAME="${OUT_NAME:-jobradar-promo-4k.mp4}"
OUT="$HERE/out/$OUT_NAME"

mkdir -p "$(dirname -- "$FRAMES")" "$(dirname -- "$OUT")"

python3 "$HERE/render.py" --fps 60 --w "$WIDTH" --h "$HEIGHT" --quality 96 --out "$FRAMES"

"${FFMPEG_BIN:-ffmpeg}" -y \
  -framerate 60 -start_number 0 -i "$FRAMES/f_%06d.jpg" \
  -vf "scale=in_range=full:out_range=tv,format=yuv420p" \
  -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p -color_range tv -movflags +faststart \
  -r 60 "$OUT"

echo "成片：$OUT"
