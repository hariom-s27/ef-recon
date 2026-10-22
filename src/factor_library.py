"""ADR-003 / efl-1: select current default rows for one configured reporting FY."""
import csv
import hashlib
import re
from datetime import date
from pathlib import Path

import config
from paths import DATA_DIR

RELEASE = "efl-1"


def read_rows(csv_path=None):
    """Read physical library rows without selection, cache or network calls."""
    if csv_path is None:
        csv_path = DATA_DIR / "emission_factors.csv"
    with open(csv_path, newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def select_active(rows, reporting_fy):
    """Exactly one current default per factor_id, retaining first-occurrence order."""
    match = re.fullmatch(r"(\d{4})-(\d{2})", reporting_fy)
    if match is None:
        raise ValueError(f"Invalid reporting FY: {reporting_fy!r}; expected YYYY-YY")
    year = int(match[1])
    if int(match[2]) != (year + 1) % 100:
        raise ValueError(f"Invalid reporting FY: {reporting_fy!r}")
    fy_start, fy_end = date(year, 4, 1), date(year + 1, 3, 31)
    groups = {}
    for row in rows:
        factor_id = row["factor_id"]
        candidates = groups.setdefault(factor_id, [])
        default = row.get("is_default", "").strip()
        if default not in ("0", "1"):
            raise ValueError(f"{factor_id}: is_default must be 0 or 1")
        start, end = (row.get(key, "").strip() for key in ("valid_from", "valid_to"))
        if not start and not end:
            covers_fy = True  # Release 1 non-CEA rows are always valid.
        else:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start) or not re.fullmatch(
                    r"\d{4}-\d{2}-\d{2}", end):
                raise ValueError(f"{factor_id}: validity needs two ISO dates or two blanks")
            valid_from, valid_to = date.fromisoformat(start), date.fromisoformat(end)
            if valid_from > valid_to:
                raise ValueError(f"{factor_id}: valid_from is after valid_to")
            covers_fy = valid_from <= fy_start and fy_end <= valid_to
        if default == "1" and not row.get("known_to", "").strip() and covers_fy:
            candidates.append(row)
    if not groups:
        raise ValueError("Factor library is empty")
    selected = []
    for factor_id, candidates in groups.items():
        if len(candidates) != 1:
            raise ValueError(
                f"{factor_id}: expected exactly one active row for FY {reporting_fy}; "
                f"found {len(candidates)}")
        selected.append(candidates[0])
    return selected


def read_active(csv_path=None, reporting_fy=None):
    """Shared raw active rows for totals and other non-matcher consumers."""
    if reporting_fy is None:
        reporting_fy = config.REPORTING_FY
    return select_active(read_rows(csv_path), reporting_fy)


def cache_path(csv_path, reporting_fy):
    """A different release, FY or CSV content cannot reuse an embedding cache."""
    csv_path = Path(csv_path)
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    return csv_path.parent.parent / "output" / (
        f"factors_cache_{RELEASE}_{reporting_fy}_{digest}.pkl")

