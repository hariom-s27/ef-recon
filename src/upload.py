"""
upload.py — save a user upload safely: basename only, never into data/, never overwrite.
"""
from pathlib import Path, PurePosixPath, PureWindowsPath

from paths import DATA_DIR


def save_upload(name, data, dest_dir):
    """Write `data` to dest_dir/<basename of name> and return the path.
    Refuses absolute names, any '..' component, an empty basename, and any dest_dir in data/."""
    name = str(name)
    parts = name.replace("\\", "/").split("/")
    if PurePosixPath(name).is_absolute() or PureWindowsPath(name).is_absolute() or PureWindowsPath(name).drive:
        raise ValueError(f"refusing absolute upload name: {name!r}")
    if ".." in parts:
        raise ValueError(f"refusing upload name with '..': {name!r}")
    base = parts[-1]
    if base in ("", "."):
        raise ValueError(f"refusing empty upload name: {name!r}")

    dest = Path(dest_dir).resolve()
    data_dir = DATA_DIR.resolve()
    if dest == data_dir or data_dir in dest.parents:
        raise ValueError(f"refusing to save uploads under data/: {dest}")

    path = dest / base
    with open(path, "xb") as f:      # 'x': never overwrite
        f.write(bytes(data))
    return path
