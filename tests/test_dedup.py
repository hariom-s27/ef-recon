"""Test for SP-08 dedup: identical bills must collapse to one."""
from dedup import deduplicate

def test_duplicate_is_caught():
    lines = [
        {"line_id": "A", "fingerprint": "electricity|kwh|40421|jun|knp", "emissions": 1},
        {"line_id": "B", "fingerprint": "electricity|kwh|40421|jun|knp", "emissions": 1},  # dup of A
        {"line_id": "C", "fingerprint": "diesel|litre|2076|mar|pun",     "emissions": 1},
    ]
    kept, duplicates = deduplicate(lines)
    assert len(kept) == 2          # A and C
    assert len(duplicates) == 1    # B
    assert duplicates[0]["duplicate_of"] == "A"