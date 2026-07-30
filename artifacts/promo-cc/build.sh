#!/usr/bin/env bash
# 从确定性 HTML 场景生成成片：1080×1920 / 60fps / H.264。
#   bash artifacts/promo-cc/build.sh
# 可选：SHUTTER=2 开运动模糊（渲染时间翻倍，换更"电影感"的拖影）
set -euo pipefail

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
FRAMES="$HERE/.frames"
FPS=60
SHUTTER="${SHUTTER:-1}"
if [ "$SHUTTER" -gt 1 ]; then
  OUT="$HERE/out/jobradar-promo-1080x1920-mblur.mp4"
else
  OUT="$HERE/out/jobradar-promo-1080x1920.mp4"
fi
mkdir -p "$HERE/out"

python3 "$HERE/render.py" --fps "$FPS" --w 1080 --h 1920 --quality 95 \
  --shutter "$SHUTTER" --out "$FRAMES"

if [ "$SHUTTER" -gt 1 ]; then
  # 多采样帧按 SHUTTER 张一组平均 → 真运动模糊，然后抽回目标帧率
  VF="tmix=frames=${SHUTTER}:weights=$(printf '1 %.0s' $(seq "$SHUTTER")),fps=${FPS}"
  IN_RATE=$(( FPS * SHUTTER ))
else
  VF="null"
  IN_RATE=$FPS
fi

ffmpeg -y -v warning -stats \
  -framerate "$IN_RATE" -start_number 0 -i "$FRAMES/f_%06d.jpg" \
  -vf "$VF" \
  -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p \
  -movflags +faststart -r "$FPS" "$OUT"

rm -rf "$FRAMES"
echo "成片：$OUT"
ffprobe -v error -show_entries format=duration,size -show_entries stream=width,height,r_frame_rate \
  -of default=noprint_wrappers=1 "$OUT"
