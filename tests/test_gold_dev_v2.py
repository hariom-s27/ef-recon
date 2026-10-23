"""ADR-004 DEV artifacts: only public synthetic inputs, copied to tmp_path."""
from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil

import pytest

from gold_tools import DEV_COLUMNS, GOLD_COLUMNS, HOLDOUT_COLUMNS, normalise_description


REPO = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (
    "data/gold_labels.csv", "data/gold_dev_v2.csv", "data/emission_factors.csv",
    "data/electricity_bills.csv", "data/diesel_invoices.csv",
    "data/erp_spend_export.csv", "data/hard_cases.csv", "data/gold_spec_v2.md",
    "docs/adr/ADR-004-amendment-2026-10-23-hashes.md",
    "docs/adr/ADR-004-amendment-2026-10-23c-near-miss-column.md",
    ".gitignore",
)
APPROVED_REFS = json.loads(r'''[
  {
    "line_id": "REF-0001",
    "raw_description": "Vexlumiq Hire - 125 kVA DG set rental Oct-25",
    "canonical_qty": "1",
    "canonical_unit": "month",
    "label_rationale": "This invoice purchases equipment rental rather than diesel or generated energy.",
    "near_miss": "1",
    "type": "equipment rental"
  },
  {
    "line_id": "REF-0002",
    "raw_description": "Orzaveli Rentals - LPG cylinder cage hire",
    "canonical_qty": "2",
    "canonical_unit": "month",
    "label_rationale": "The charge is for use of storage equipment and includes no LPG purchase.",
    "near_miss": "1",
    "type": "equipment rental"
  },
  {
    "line_id": "REF-0003",
    "raw_description": "Tavruliq Power Services - DG set AMC FY25-26",
    "canonical_qty": "1",
    "canonical_unit": "contract",
    "label_rationale": "The contract pays for maintenance services rather than combustion fuel.",
    "near_miss": "1",
    "type": "AMC/maintenance"
  },
  {
    "line_id": "REF-0004",
    "raw_description": "Nimzavro Workshop - LPG burner servicing (labour)",
    "canonical_qty": "2",
    "canonical_unit": "visit",
    "label_rationale": "This is a labour charge for servicing equipment and contains no energy supply.",
    "near_miss": "1",
    "type": "AMC/maintenance"
  },
  {
    "line_id": "REF-0005",
    "raw_description": "Zeravuni Logistics - freight charges HSD drums",
    "canonical_qty": "1",
    "canonical_unit": "trip",
    "label_rationale": "The separately invoiced freight service does not represent diesel acquired for combustion.",
    "near_miss": "1",
    "type": "fuel transport/handling"
  },
  {
    "line_id": "REF-0006",
    "raw_description": "Pelqavro Handling - CNG cascade unloading charges",
    "canonical_qty": "4",
    "canonical_unit": "job",
    "label_rationale": "The line pays for material handling services and excludes the gas itself.",
    "near_miss": "1",
    "type": "fuel transport/handling"
  },
  {
    "line_id": "REF-0007",
    "raw_description": "Mirlavex - electricity bill late payment surcharge",
    "canonical_qty": "1",
    "canonical_unit": "line",
    "label_rationale": "A late-payment surcharge is a financial penalty, not electricity consumed.",
    "near_miss": "1",
    "type": "separate tax/surcharge"
  },
  {
    "line_id": "REF-0008",
    "raw_description": "Kestavri Fuels - VAT on petrol invoice (separate line)",
    "canonical_qty": "1",
    "canonical_unit": "line",
    "label_rationale": "This line records only a separately stated tax and must not duplicate the petrol quantity elsewhere.",
    "near_miss": "1",
    "type": "separate tax/surcharge"
  },
  {
    "line_id": "REF-0009",
    "raw_description": "Sorvuliq Review - energy audit fee, CNG plant",
    "canonical_qty": "1",
    "canonical_unit": "report",
    "label_rationale": "The payment buys professional audit services rather than natural gas or other energy.",
    "near_miss": "1",
    "type": "audits/consultancy"
  },
  {
    "line_id": "REF-0010",
    "raw_description": "Brevazuli Advisory - electricity tariff consultancy retainer",
    "canonical_qty": "1",
    "canonical_unit": "month",
    "label_rationale": "The retainer purchases tariff advice and includes no electricity supply.",
    "near_miss": "1",
    "type": "audits/consultancy"
  },
  {
    "line_id": "REF-0011",
    "raw_description": "Lunqavri Office Goods - A4 notebooks and paper clips",
    "canonical_qty": "1",
    "canonical_unit": "lot",
    "label_rationale": "Office stationery is not combustion fuel or purchased energy.",
    "near_miss": "0",
    "type": "stationery/services (not a near-miss)"
  },
  {
    "line_id": "REF-0012",
    "raw_description": "Dovruliq Admin - payroll processing fee",
    "canonical_qty": "1",
    "canonical_unit": "service",
    "label_rationale": "Payroll administration is a service unrelated to combustion or energy use.",
    "near_miss": "0",
    "type": "stationery/services (not a near-miss)"
  }
]''')
ACCEPT_RATIONALES = json.loads(r'''{
  "EF-IN-ELEC-GRID": "Grid electricity purchased and consumed by the site.",
  "EF-DIESEL-L": "Diesel purchased for on-site combustion, in litres.",
  "EF-PETROL-L": "Petrol used in company vehicles, in litres.",
  "EF-LPG-L": "LPG purchased for combustion, in litres.",
  "EF-NATGAS-M3": "Piped natural gas burned for heat, by volume.",
  "EF-NATGAS-KWH": "Natural gas burned for heat, billed by energy content.",
  "EF-IN-ELEC-SOLAR": "On-site rooftop solar generation with zero operational emissions."
}''')
EXPECTED_GROUPS = {
    frozenset(("DSL-0001", "DSL-0003", "DSL-0004")),
    frozenset(("DSL-0006", "DSL-0007")),
    frozenset(("ELEC-0007", "ELEC-0009")),
}


def _read(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


@pytest.fixture
def artifacts(tmp_path):
    """The repository artifacts are synthetic DEV; evaluate copies in tmp_path."""
    for relative in PUBLIC_FILES:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, target)
    return {
        "root": tmp_path,
        "dev": _read(tmp_path / "data" / "gold_dev_v2.csv"),
        "legacy": _read(tmp_path / "data" / "gold_labels.csv"),
        "factors": _read(tmp_path / "data" / "emission_factors.csv"),
    }


def _index(rows):
    return {row["line_id"]: row for row in rows}


def _groups(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[normalise_description(row["raw_description"])].append(row["line_id"])
    return {frozenset(ids) for ids in groups.values() if len(ids) > 1}


def test_dev_v2_count_and_unique_ids(artifacts):
    rows = artifacts["dev"]
    assert len(rows) == 57
    assert len({row["line_id"] for row in rows}) == 57


def test_dev_v2_retained_and_added_ids(artifacts):
    original_ids = set(_index(artifacts["legacy"]))
    expected = original_ids - {"ELEC-0015"}
    expected |= {"PDF-0001"} | {f"REF-{number:04d}" for number in range(1, 13)}
    assert set(_index(artifacts["dev"])) == expected
    assert "ELEC-0015" not in _index(artifacts["dev"])


def test_dev_v2_mapping_is_one_to_one(artifacts):
    dev = _index(artifacts["dev"])
    rules = {
        "ERP-0002": "R-ESC-UNIT", "ERP-0007": "R-ESC-MIX",
        "HARD-0001": "R-ESC-GAP", "HARD-0002": "R-ESC-GAP",
        "HARD-0003": "R-ESC-GAP", "HARD-0004": "R-ESC-GAP",
        "HARD-0005": "R-ESC-UNIT", "HARD-0006": "R-ESC-UNIT",
        "HARD-0013": "R-ESC-UNIT",
    }
    matched = []
    for original in artifacts["legacy"]:
        identity = original["line_id"]
        if identity == "ELEC-0015":
            continue
        row = dev[identity]
        gold = original["correct_factor_id"]
        decision = {"ESCALATE": "escalate", "NO_FACTOR": "refuse"}.get(gold, "accept")
        assert row["legacy_correct_factor_id"] == gold
        assert row["expected_decision"] == decision
        assert row["stratum"] == {"accept": "A", "escalate": "B", "refuse": "C"}[decision]
        if decision == "accept":
            assert row["expected_factor_id"] == gold
            assert row["expected_factor_row_id"]
            assert row["rule_id"] == "R-ACC"
        else:
            assert row["expected_factor_id"] == row["expected_factor_row_id"] == ""
            assert row["rule_id"] == (rules[identity] if decision == "escalate" else "R-REF")
        matched.append(identity)
    assert len(matched) == len(set(matched)) == 44


def test_dev_v2_preserves_legacy_canonical_fields(artifacts):
    dev = _index(artifacts["dev"])
    for original in artifacts["legacy"]:
        if original["line_id"] == "ELEC-0015":
            continue
        row = dev[original["line_id"]]
        for field in ("raw_description", "canonical_qty", "canonical_unit",
                      "messiness_tags", "source_file"):
            assert row[field].encode("utf-8") == original[field].encode("utf-8")
        assert row["qty_source"] == "column"


def test_dev_v2_accept_row_ids_belong_to_factor(artifacts):
    factors = {row["row_id"]: row for row in artifacts["factors"]}
    for row in artifacts["dev"]:
        if row["expected_decision"] == "accept":
            assert row["expected_factor_row_id"] in factors
            assert factors[row["expected_factor_row_id"]]["factor_id"] == row["expected_factor_id"]
        else:
            assert row["expected_factor_id"] == row["expected_factor_row_id"] == ""


def test_dev_v2_period_truth(artifacts):
    root = artifacts["root"]
    dev = _index(artifacts["dev"])
    source_rows = {}
    for name in {row["source_file"] for row in artifacts["legacy"]}:
        source_rows[name] = _index(_read(root / "data" / name))
    previous_fy_grid = set()
    for original in artifacts["legacy"]:
        if original["line_id"] == "ELEC-0015":
            continue
        row = dev[original["line_id"]]
        source = source_rows[original["source_file"]][original["line_id"]]
        raw_date = source.get("Billing Period", "") or source.get("Invoice Date", "")
        date = datetime.strptime(raw_date, "%d-%b-%Y").date() if raw_date else None
        assert row["period"] == (date.isoformat() if date else "")
        if row["expected_factor_id"] == "EF-IN-ELEC-GRID":
            first_year = date.year - (date.month < 4) if date else 2025
            expected = f"EF-IN-ELEC-GRID@v22.0@FY{first_year}-{str(first_year + 1)[-2:]}@incl_imports"
            assert row["expected_factor_row_id"] == expected
            if first_year == 2024:
                previous_fy_grid.add(row["line_id"])
    assert previous_fy_grid == {"ELEC-0003", "ELEC-0007", "ELEC-0013"}
    pdf = dev["PDF-0001"]
    assert (pdf["period"], pdf["canonical_qty"], pdf["canonical_unit"]) == (
        "2025-06-01", "23450", "kWh")
    assert (pdf["stratum"], pdf["qty_source"], pdf["author"]) == ("D", "text", "DEV-legacy")
    assert pdf["expected_factor_row_id"] == "EF-IN-ELEC-GRID@v22.0@FY2025-26@incl_imports"
    assert pdf["label_rationale"] == (
        "The bill records 23450 kWh of purchased grid electricity for June 2025.")
    assert all(row["period"] == "" for row in artifacts["dev"] if row["line_id"].startswith("REF-"))


def test_dev_v2_spec_hash_matches_amendment(artifacts):
    root = artifacts["root"]
    spec = (root / "data" / "gold_spec_v2.md").read_bytes().replace(b"\r\n", b"\n")
    digest = hashlib.sha256(spec).hexdigest()
    blob = hashlib.sha1(b"blob " + str(len(spec)).encode("ascii") + b"\0" + spec).hexdigest()
    amendment = (root / "docs" / "adr" / "ADR-004-amendment-2026-10-23-hashes.md").read_text(
        encoding="utf-8")
    line = next(line for line in amendment.splitlines()
                if line.startswith("| " + chr(96) + "data/gold_spec_v2.md" + chr(96) + " |"))
    entries = re.findall(r"\x60([^\x60]+)\x60", line)
    assert entries == ["data/gold_spec_v2.md", blob, digest]
    assert {row["spec_sha256"] for row in artifacts["dev"]} == {digest}


def test_dev_v2_duplicate_groups_exactly_grandfathered(artifacts):
    assert _groups(artifacts["dev"]) == EXPECTED_GROUPS


def test_dev_v2_new_rows_duplicate_nothing(artifacts):
    rows = artifacts["dev"]
    new = [row for row in rows if row["line_id"].startswith("REF-") or row["line_id"] == "PDF-0001"]
    assert len(new) == 13
    for row in new:
        normalized = normalise_description(row["raw_description"])
        assert sum(normalise_description(other["raw_description"]) == normalized
                   for other in rows) == 1


def test_dev_v2_schema_encoding_and_authors(artifacts):
    root = artifacts["root"]
    raw = (root / "data" / "gold_dev_v2.csv").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw and raw.endswith(b"\n")
    spec = (root / "data" / "gold_spec_v2.md").read_text(encoding="utf-8")
    columns_section = spec.split("## 7. Columns", 1)[1].split("## 8.", 1)[0]
    spec_columns = tuple(re.findall(r"\x60([^\x60]+)\x60", columns_section))
    assert len(spec_columns) == 19
    assert GOLD_COLUMNS == spec_columns
    assert HOLDOUT_COLUMNS == spec_columns + ("near_miss",)
    assert len(HOLDOUT_COLUMNS) == 20
    assert DEV_COLUMNS == spec_columns + ("messiness_tags", "legacy_correct_factor_id", "near_miss")
    assert next(csv.reader(raw.decode("utf-8").splitlines())) == list(DEV_COLUMNS)
    rows = artifacts["dev"]
    assert {row["set"] for row in rows} == {"DEV"}
    assert {row["canary"] for row in rows} == {""}
    assert Counter(row["author"] for row in rows) == {"DEV-legacy": 45, "P05a-agent": 12}
    assert Counter(row["stratum"] for row in rows) == {"A": 33, "B": 9, "C": 14, "D": 1}
    assert Counter(row["expected_decision"] for row in rows) == {
        "accept": 34, "escalate": 9, "refuse": 14}
    assert Counter(row["rule_id"] for row in rows) == {
        "R-ACC": 34, "R-ESC-GAP": 4, "R-ESC-UNIT": 4, "R-ESC-MIX": 1, "R-REF": 14}
    assert all(row["near_miss"] in {"0", "1"} for row in rows)
    assert all(row["stratum"] == "C" for row in rows if row["near_miss"] == "1")
    assert all(row["expected_category"] == "" and row["category_status"] == "blank" for row in rows)
    by_id = _index(rows)
    for approved in APPROVED_REFS:
        row = by_id[approved["line_id"]]
        for field in ("raw_description", "canonical_qty", "canonical_unit",
                      "near_miss", "label_rationale"):
            assert row[field] == approved[field]
        assert row["raw_description"].isascii()
        assert row["source_file"] == "dev_refusals_p05a.csv"
        assert row["author"] == "P05a-agent" and row["rule_id"] == "R-REF"
        assert row["legacy_correct_factor_id"] == ""
    assert sum(by_id[row["line_id"]]["near_miss"] == "1" for row in APPROVED_REFS) == 10
    for row in rows:
        if row["line_id"] != "PDF-0001" and row["expected_decision"] == "accept":
            assert row["label_rationale"] == ACCEPT_RATIONALES[row["expected_factor_id"]]


def test_dev_v2_ignore_rules(artifacts):
    root = artifacts["root"]
    amendment = (root / "docs" / "adr" / "ADR-004-amendment-2026-10-23-hashes.md").read_text(
        encoding="utf-8")
    paragraph = next(line for line in amendment.splitlines() if ".gitignore" in line)
    expected = re.findall(r"\x60([^\x60]+)\x60", paragraph)
    assert expected[-4] == ".gitignore"
    patterns = expected[-3:]
    assert len(patterns) == 3
    ignore_lines = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    for pattern in patterns:
        assert pattern in ignore_lines
    assert ignore_lines[-4] == "# ADR-004: sealed gold sets never enter the repo"
    assert set(ignore_lines[-3:]) == set(patterns)
