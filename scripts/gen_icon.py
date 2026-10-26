"""从 resources/app-icon.png 生成 resources/app.ico（多分辨率 Windows ICO）。

``app-icon.png`` 是图标设计的唯一来源：改图标只需替换这张 256×256 PNG，
再运行 ``python scripts/gen_icon.py``。生成的多尺寸 ICO 同时供：

- PyInstaller ``--icon``：exe 文件图标 / 快捷方式图标
- 运行时 ``app/ui/icons.py``：窗口、系统托盘、应用内通知

三处共用同一份文件，不会再出现 exe 是新图标、托盘还是旧图标的情况。

用法：
    python scripts/gen_icon.py
"""
import os
import sys

from PIL import Image, ImageOps

SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    res_dir = os.path.join(root, "resources")
    src_path = os.path.join(res_dir, "app-icon.png")
    out = os.path.join(res_dir, "app.ico")

    if not os.path.exists(src_path):
        print(f"ERROR: missing source image: {src_path}")
        return 1

    src = Image.open(src_path).convert("RGBA")
    base = ImageOps.fit(src, (256, 256), Image.LANCZOS)
    others = [ImageOps.fit(src, (s, s), Image.LANCZOS)
              for s in SIZES if s != 256]
    base.save(out, format="ICO",
              sizes=[(s, s) for s in SIZES],
              append_images=others)

    print(f"Generated: {out}")
    print(f"File size: {os.path.getsize(out)} bytes")

    # 校验：读回 ICO，列出内部所有 entry 尺寸
    try:
        ico = Image.open(out)
        entry_sizes = sorted(set(ico.ico.sizes()))
        print(f"ICO entries: {entry_sizes}")
        missing = [s for s in SIZES if (s, s) not in entry_sizes]
        if missing:
            print(f"WARN: missing sizes: {missing}")
            return 1
    except Exception as e:
        print(f"WARN: ico verify failed: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
