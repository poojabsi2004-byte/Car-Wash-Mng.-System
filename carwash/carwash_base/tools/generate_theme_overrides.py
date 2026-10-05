#!/usr/bin/env python3
"""Generate static/src/css/carwash_theme_overrides.css from Odoo's compiled backend CSS.

Odoo's backend primary colour (#71639e in v19) is baked into the compiled stylesheet
in ~400 places (button variables, links, stage bar, checkboxes' inline SVGs, ...).
This script finds every rule using a shade of that colour family and re-emits just
those declarations, scoped to ``body.o_cw_app`` (set while the Car Wash app is open)
and with each shade remapped to the matching shade of the Car Wash brand colour.

Re-run it after upgrading Odoo:

    curl -s http://localhost:8069/web/assets/<hash>/web.assets_web.min.css -o /tmp/web.css
    python3 carwash_base/tools/generate_theme_overrides.py /tmp/web.css
"""
import colorsys
import os
import re
import sys

TARGET = "#084b76"
SCOPE = "body.o_cw_app"
# Odoo's primary family: hue ~254deg with low saturation. Brighter violets (tags,
# avatars, other palettes) are deliberately left alone.
HUE_RANGE = (245, 262)
SAT_RANGE = (0.13, 0.27)


def _hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _in_family(r, g, b):
    h, light, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return HUE_RANGE[0] <= h * 360 <= HUE_RANGE[1] and SAT_RANGE[0] <= s <= SAT_RANGE[1]


PRIMARY = _hex_to_rgb("#71639e")
PRIMARY_L = colorsys.rgb_to_hls(*(c / 255 for c in PRIMARY))[1]
TARGET_RGB = _hex_to_rgb(TARGET)


def _remap(r, g, b):
    """Same tint/shade of TARGET as (r, g, b) is of Odoo's primary."""
    light = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)[1]
    if light >= PRIMARY_L:
        t = (light - PRIMARY_L) / (1 - PRIMARY_L)
        return tuple(round(c + (255 - c) * t) for c in TARGET_RGB)
    t = (PRIMARY_L - light) / PRIMARY_L
    return tuple(round(c * (1 - t)) for c in TARGET_RGB)


HEX_RE = re.compile(r"(#|%23)([0-9a-fA-F]{6})\b")
RGB_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d+)?),\s*(\d{1,3}(?:\.\d+)?),\s*(\d{1,3}(?:\.\d+)?)(?=\s*(?:[;),]|$))")


def _replace_colors(text):
    changed = False

    def hex_sub(match):
        nonlocal changed
        rgb = _hex_to_rgb(match.group(2))
        if not _in_family(*rgb):
            return match.group(0)
        changed = True
        return match.group(1) + "%02x%02x%02x" % _remap(*rgb)

    def rgb_sub(match):
        nonlocal changed
        rgb = tuple(float(x) for x in match.groups())
        if not all(0 <= c <= 255 for c in rgb) or not _in_family(*rgb):
            return match.group(0)
        changed = True
        return "%d, %d, %d" % _remap(*rgb)

    text = HEX_RE.sub(hex_sub, text)
    text = RGB_RE.sub(rgb_sub, text)
    return text, changed


def _scope_selector(selector):
    out = []
    for sel in selector.split(","):
        sel = sel.strip()
        if not sel:
            continue
        if sel in (":root", "html", "body") or sel.startswith(":root"):
            out.append(SCOPE + sel[len(":root"):] if sel.startswith(":root") else SCOPE)
        elif sel.startswith("body"):
            out.append(SCOPE + sel[4:])
        elif sel.startswith(".o_web_client"):
            out.append(SCOPE + sel)
        elif sel.startswith("html"):
            continue
        else:
            out.append(f"{SCOPE} {sel}")
    return ", ".join(out)


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _parse(css, pos=0):
    """Yield (prelude, body) blocks; nested at-rules are returned as (prelude, [children])."""
    items = []
    buf = ""
    while pos < len(css):
        ch = css[pos]
        if ch == "{":
            prelude = buf.strip()
            buf = ""
            if prelude.startswith("@media") or prelude.startswith("@supports") or prelude.startswith("@layer"):
                children, pos = _parse(css, pos + 1)
                items.append((prelude, children))
            else:
                depth, start = 1, pos + 1
                pos += 1
                while pos < len(css) and depth:
                    depth += {"{": 1, "}": -1}.get(css[pos], 0)
                    pos += 1
                items.append((prelude, css[start:pos - 1]))
                continue
        elif ch == "}":
            return items, pos + 1
        elif ch == ";" and buf.strip().startswith("@"):
            buf = ""  # @import / @charset
        else:
            buf += ch
        pos += 1
    return items, pos


def _emit(items, indent=""):
    lines = []
    for prelude, body in items:
        if isinstance(body, list):
            inner = _emit(body, indent + "    ")
            if inner:
                lines.append(f"{indent}{prelude} {{")
                lines.extend(inner)
                lines.append(f"{indent}}}")
            continue
        if prelude.startswith("@") or "{" in body:  # keyframes, font-face, nested blocks
            continue
        decls = []
        for decl in body.split(";"):
            if ":" not in decl:
                continue
            new, changed = _replace_colors(decl.strip())
            if changed:
                decls.append(new)
        if decls:
            selector = _scope_selector(prelude)
            if selector:
                lines.append(f"{indent}{selector} {{ {'; '.join(decls)}; }}")
    return lines


def main(src):
    css = _strip_comments(open(src, encoding="utf-8").read())
    items, _pos = _parse(css)
    lines = _emit(items)
    out = os.path.join(os.path.dirname(__file__), "..", "static", "src", "css", "carwash_theme_overrides.css")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    header = (
        "/* GENERATED by carwash_base/tools/generate_theme_overrides.py - do not edit by hand.\n"
        f" * Remaps Odoo's backend primary colour family to {TARGET} inside the Car Wash app. */\n"
    )
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(header + "\n".join(lines) + "\n")
    print(f"{len(lines)} lines written to {os.path.normpath(out)}")


if __name__ == "__main__":
    main(sys.argv[1])
