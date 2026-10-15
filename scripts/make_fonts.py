"""从系统安装的 Noto 可变字体生成随包字体。

为什么打包：``Noto Serif SC`` / ``Noto Sans SC`` 在开发机上装了，
但**不是 Windows 自带字体**。多数用户的 40px 状态句会落到宋体上，
被 Windows 伪粗体化，很难看。打包子集化字体是"设计成立"和"不成立"的差别。

做法：
    1. 从可变字体实例化出需要的字重（wght=700 宋 / 400 与 600 黑）
    2. 改名成 NCMP 独立家族——避免和系统里装的 Noto 撞名，
       也符合 OFL 对改名字体的要求（Noto 保留字体名，改名版不得沿用）
    3. 子集化到 GB2312 一级＋二级汉字 + ASCII + 常用标点

用法：
    python scripts/make_fonts.py

输出到 ``app/ui/fonts/``。许可见同目录 OFL.txt。
"""
import os
import sys

from fontTools import ttLib
from fontTools.subset import Options, Subsetter
from fontTools.varLib import instancer

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_OUT_DIR = os.path.join(_ROOT, "app", "ui", "fonts")

SRC_SANS = r"C:\Windows\Fonts\NotoSansSC-VF.ttf"
SRC_SERIF = r"C:\Windows\Fonts\NotoSerifSC-VF.ttf"

# NCMP Sans SC 只出一个字重就够 600 用吗？不够——标题 600、正文 400 都要。
TARGETS = [
    # (源文件, 字重, 家族名, 样式名, 是否含 GB2312 二级汉字)
    (SRC_SANS, 400, "NCMP Sans SC", "Regular", True),
    (SRC_SANS, 600, "NCMP Sans SC", "SemiBold", True),
    (SRC_SERIF, 700, "NCMP Serif SC", "Bold", False),
]


def charset(include_level2: bool, extra: str = "") -> str:
    """要保留的字符集：ASCII + 全角标点 + GB2312 汉字 + 调用方额外给的字符。"""
    chars = set()
    # ASCII 可见字符 + 空格
    chars.update(chr(cp) for cp in range(0x20, 0x7F))
    # CJK 常用标点、全角符号
    chars.update(chr(cp) for cp in range(0x3000, 0x301F))
    chars.update(chr(cp) for cp in range(0xFF00, 0xFF65))
    for cp in (0x2026, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D,
               0x00B7, 0x2013, 0x00D7, 0x00B0, 0x2103):
        chars.add(chr(cp))
    # GB2312 一级汉字（3755 个，覆盖日常用字的绝大多数）
    for hi in range(0xB0, 0xD8):
        for lo in range(0xA1, 0xFF):
            try:
                chars.add(bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                pass
    # 二级汉字（生僻字，歌名里可能用到）只给黑体——正文用得上
    if include_level2:
        for hi in range(0xD8, 0xF8):
            for lo in range(0xA1, 0xFF):
                try:
                    chars.add(bytes([hi, lo]).decode("gb2312"))
                except UnicodeDecodeError:
                    pass
    chars.update(extra)
    chars.discard("\n")
    chars.discard("\r")
    return "".join(sorted(chars))


def build(src: str, wght: int, family: str, subfamily: str,
          include_level2: bool) -> str:
    """实例化 → 改名 → 子集化 → 落盘。返回输出路径。"""
    print(f"--- {family} {subfamily} (wght={wght}) ---")
    font = ttLib.TTFont(src)

    if "fvar" in font:
        print("  instancing wght =", wght)
        instancer.instantiateVariableFont(font, {"wght": wght}, inplace=True)

    # 改名：家族名换成 NCMP 专属，避免和系统 Noto 撞名。
    # 同时写 1/2（RIBBI 位）和 16/17（排版位），DirectWrite 两边都认。
    name = font["name"]
    full = family if subfamily == "Regular" else f"{family} {subfamily}"
    ps = (family + "-" + subfamily).replace(" ", "")
    ribbi_family = family
    ribbi_style = "Regular" if subfamily == "Regular" else subfamily
    if subfamily == "SemiBold":
        # 非 RIBBI 样式按惯例：nameID1 写成"家族+样式"，nameID2 写 Regular
        ribbi_family, ribbi_style = f"{family} {subfamily}", "Regular"

    for pid, eid, lid in ((3, 1, 0x409), (1, 0, 0)):
        name.setName(ribbi_family, 1, pid, eid, lid)
        name.setName(ribbi_style, 2, pid, eid, lid)
        name.setName(f"{full}; ncmp desktop bundled", 3, pid, eid, lid)
        name.setName(full, 4, pid, eid, lid)
        name.setName(ps, 6, pid, eid, lid)
        name.setName(family, 16, pid, eid, lid)
        name.setName(subfamily, 17, pid, eid, lid)

    if "OS/2" in font:
        font["OS/2"].usWeightClass = wght

    print("  subsetting to", len(charset(include_level2)), "codepoints")
    opts = Options()
    opts.name_IDs = ["*"]          # 保留全部名字记录，Qt 靠它们识别家族
    opts.name_languages = ["*"]
    opts.name_legacy = True
    opts.glyph_names = False
    opts.notdef_outline = True
    opts.layout_features = ["*"]   # 保留 kern 等排版特性
    subsetter = Subsetter(options=opts)
    subsetter.populate(text=charset(include_level2))
    subsetter.subset(font)

    suffix = {"Regular": "Regular", "SemiBold": "SemiBold", "Bold": "Bold"}[subfamily]
    out = os.path.join(_OUT_DIR, f"{family.replace(' ', '')}-{suffix}.ttf")
    os.makedirs(_OUT_DIR, exist_ok=True)
    font.save(out)
    size_kb = os.path.getsize(out) // 1024
    print(f"  wrote {out} ({size_kb} KB)")
    return out


def main() -> int:
    missing = [p for p in {t[0] for t in TARGETS} if not os.path.exists(p)]
    if missing:
        print("找不到源字体（需要本机装有 Noto Sans/Serif SC 可变字体）：")
        for p in missing:
            print("  ", p)
        return 1
    for src, wght, family, subfamily, lvl2 in TARGETS:
        build(src, wght, family, subfamily, lvl2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
