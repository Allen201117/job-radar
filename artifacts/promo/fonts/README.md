# 片中中文字体

## 为什么不用系统字体

这台机器**没装苹方（PingFang SC），也没装楷体（Kaiti SC / STKaiti）**。
原来的字体栈写了 `"PingFang SC","Hiragino Sans GB"`，实际静默回退到只有 Regular 的宋体。

而版式里写的是 `font-weight:620/680/720/760` —— 宋体没有这些字重，
浏览器只能**合成假粗体**（把笔画硬涂粗）。中文笔画一涂就糊成一团。
这才是"字体太丑"的真正原因，不是选错了字体。

验证方法：

```bash
fc-match "PingFang SC"   # 返回 Verdana = 没装
fc-match "Kaiti SC"      # 返回 Verdana = 没装
```

## 现在用什么

| 用途 | 字体 | 文件 |
|---|---|---|
| 大标题 / 收尾主张（片子的叙述声音） | 思源宋体 Source Han Serif SC | `serif-sb.woff2` (SemiBold) / `serif-r.woff2` |
| 产品界面 / 正文 / 芯片 / 品牌字标 | 思源黑体 Source Han Sans SC | `sans-m.woff2` (Medium) / `sans-r.woff2` |
| 拉丁字母与数字 | SF Pro（系统） | — |

授权：SIL Open Font License 1.1，**可商用、可嵌入视频**。

⚠️ **字体分工那条界线不要越**：宋体只给片子自己的叙述声音，
产品界面（岗位卡、洞察卡、表单、品牌字标）必须留黑体 ——
产品里就是黑体，UI 改成宋体等于让宣传片误传产品长相。

⚠️ `@font-face` 用的是**字重区间**（`font-weight:451 900`），
把 500–900 全部指到真字重文件。**别把区间改窄**，否则假粗体会回来。

> 注：`DESIGN.md` 里"禁用 webfont"是保护线上站点（GFW 下加载不可靠）。
> **视频不受此限** —— 输出是像素，字体只需在渲染时存在。

## 怎么重新生成（换字 / 加字后）

字体已按片中实际用到的 414 个字符做子集化：**80MB → 639KB**，所以能进仓库。
`scene.html` 里加了新字（尤其新公司名 / 新文案）后必须重跑，否则新字会掉成豆腐块。

```bash
# 1. 下载原始字体（约 80MB，不入库）
mkdir -p /tmp/cjk && cd /tmp/cjk
for f in Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf \
         Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Medium.otf \
         Serif/OTF/SimplifiedChinese/NotoSerifCJKsc-Regular.otf \
         Serif/OTF/SimplifiedChinese/NotoSerifCJKsc-SemiBold.otf; do
  curl -sLO "https://github.com/notofonts/noto-cjk/raw/main/$f"
done
```

```bash
# 2. 按 scene.html 里实际出现的字符子集化
python3 - <<'PY'
from fontTools import subset
import pathlib
scene = pathlib.Path("scene.html").read_text("utf-8")
chars = set(scene) | set("0123456789，。、·—…''“”（）《》%+-→↗✦ ")
text = "".join(sorted(c for c in chars if c.isprintable()))
for src, out in [("/tmp/cjk/NotoSansCJKsc-Regular.otf","fonts/sans-r.woff2"),
                 ("/tmp/cjk/NotoSansCJKsc-Medium.otf","fonts/sans-m.woff2"),
                 ("/tmp/cjk/NotoSerifCJKsc-Regular.otf","fonts/serif-r.woff2"),
                 ("/tmp/cjk/NotoSerifCJKsc-SemiBold.otf","fonts/serif-sb.woff2")]:
    subset.main([src, f"--text={text}", "--flavor=woff2",
                 "--layout-features=*", f"--output-file={out}"])
    print(out, pathlib.Path(out).stat().st_size//1024, "KB")
PY
```

需要 `python3 -m pip install fonttools brotli`。

## 换成全黑体（更接近苹方的观感）

`scene.html` 里把这一行改掉即可，其余不动：

```css
.disp{font-family:var(--display)}   /* 改成 var(--font) 就是全黑体 */
```
