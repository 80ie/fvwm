"""Load and validate the Photon palette exported by the FVWM colorsets file."""

import ast
import os
import re
from pathlib import Path


PREFIX = "FVWM_PHOTON_"
SETENV_RE = re.compile(
    r'^\s*SetEnv\s+(FVWM_PHOTON_[A-Z0-9_]+)\s+"([^"]+)"\s*$'
)
REF_RE = re.compile(r"^\$\[(FVWM_PHOTON_[A-Z0-9_]+)\]$")

REQUIRED = (
    "FACE", "FACE_HI", "HEADER", "GUTTER", "FRAME_MID", "WELL",
    "FACE_ALT", "BTN_HI", "BTN_LO", "WELL_SH", "WELL_LIP", "HI",
    "SH", "DARK", "HEADER_CELL", "HEADER_GLYPH", "FIELD", "TROUGH",
    "TROUGH_SH", "GROOVE", "GROOVE_MID", "GROOVE_HI", "GROOVE_LIP",
    "THUMB_HI", "THUMB_LO", "TICK_HI", "TICK_LO", "FILL_CPU",
    "FILL_MEM", "FILL_DISK", "INK", "INK_OFF", "PAGER_SECTION",
    "PAGER_DESK", "PAGER_DESK_HI", "PAGER_WIN", "PAGER_WIN_EDGE",
    "PAGER_FOCUS", "PAGER_FOCUS_EDGE", "PAGER_GRID",
)

COLORSET_ROLES = {
    30: {"fg": "INK", "bg": "FACE", "hi": "HI", "sh": "SH"},
    31: {"fg": "INK", "bg": "FACE_HI", "hi": "HI", "sh": "SH"},
    32: {"fg": "INK", "bg": "HEADER", "hi": "HI", "sh": "SH"},
    33: {"fg": "INK", "bg": "WELL", "hi": "HI", "sh": "SH"},
    34: {"fg": "PAGER_GRID", "bg": "PAGER_DESK", "hi": "HI", "sh": "SH"},
    35: {"fg": "PAGER_GRID", "bg": "PAGER_DESK_HI", "hi": "HI", "sh": "SH"},
    36: {"fg": "INK", "bg": "PAGER_WIN", "hi": "HI", "sh": "PAGER_WIN_EDGE"},
    37: {"fg": "INK", "bg": "PAGER_FOCUS", "hi": "HI", "sh": "PAGER_FOCUS_EDGE"},
}


def colorsets_path():
    root = os.environ.get("FVWM_USERDIR")
    if root:
        path = Path(root) / "colorsets"
        if path.is_file():
            return path
    return Path(__file__).resolve().parent.parent / "colorsets"


def file_palette(path=None):
    path = Path(path) if path else colorsets_path()
    raw = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = SETENV_RE.match(line)
        if match:
            raw[match.group(1)] = match.group(2)

    resolved = {}
    for key, value in raw.items():
        ref = REF_RE.match(value)
        if ref:
            value = resolved.get(ref.group(1), value)
        resolved[key] = value
    return {key.removeprefix(PREFIX): value for key, value in resolved.items()}


def validate_palette(palette):
    missing = sorted(set(REQUIRED) - palette.keys())
    invalid = sorted(
        key for key in REQUIRED
        if key in palette and not re.fullmatch(r"#[0-9a-fA-F]{6}", palette[key])
    )
    if missing or invalid:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if invalid:
            details.append("invalid: " + ", ".join(invalid))
        raise RuntimeError("invalid Photon palette (" + "; ".join(details) + ")")


def load_palette(path=None):
    palette = file_palette(path)
    palette.update({
        key.removeprefix(PREFIX): value
        for key, value in os.environ.items()
        if key.startswith(PREFIX)
    })
    validate_palette(palette)
    return palette


def check_colorset_roles(path=None):
    path = Path(path) if path else colorsets_path()
    lines = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^Colorset\s+(3[0-7])\s+", line)
        if match:
            lines[int(match.group(1))] = line

    errors = []
    for number, roles in COLORSET_ROLES.items():
        line = lines.get(number, "")
        for option, name in roles.items():
            expected = f"{option} $[{PREFIX}{name}]"
            if expected not in line:
                errors.append(f"colorset {number} must contain {expected}")
    return errors


def literal_qcolors():
    bindir = Path(__file__).resolve().parent
    errors = []
    sources = sorted(bindir.glob("photon*.py")) + [bindir / "shelf-panel"]
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "QColor":
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                errors.append(f"{path.name}:{node.lineno}: literal QColor")
    return errors


def check():
    palette = file_palette()
    validate_palette(palette)
    errors = check_colorset_roles() + literal_qcolors()
    if errors:
        raise RuntimeError("; ".join(errors))


if __name__ == "__main__":
    check()
    print("Photon colorsets and sidebar palette agree")
