#!/usr/bin/env bash
# 从确定性 HTML 场景生成最终 1080×1920 / 60fps / H.264 宣传片。
# 运行：bash artifacts/promo/build.sh
set -euo pipefail

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
FRAMES="$HERE/.work/frames"
OUT="$HERE/out/jobradar-promo.mp4"

mkdir -p "$(dirname -- "$FRAMES")" "$(dirname -- "$OUT")"

python3 "$HERE/render.py" --fps 60 --w 1080 --h 1920 --quality 95 --out "$FRAMES"

"${FFMPEG_BIN:-ffmpeg}" -y \
  -framerate 60 -start_number 0 -i "$FRAMES/f_%06d.jpg" \
  -vf "scale=in_range=full:out_range=tv,format=yuv420p" \
  -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p -color_range tv -movflags +faststart \
  -r 60 "$OUT"

echo "成片：$OUT"
