"""
graph.py — SP-09: a knowledge graph that stores HARD RULES
(activity -> allowed factor) and LINEAGE (number -> factor -> source).

Works TWO ways automatically:
  - If Neo4j is running -> uses real Neo4j.
  - If not              -> uses a simple in-memory graph (fallback).
Either way, the rest of the code calls the same 3 methods.
"""

import csv
import re
from paths import DATA_DIR

# ---- Neo4j connection settings (change password if yours differs) ----
NEO4J_URL  = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "test1234"      # <-- put YOUR Neo4j password here


# =====================================================================
# BACKEND 1: real Neo4j
# =====================================================================
class Neo4jGraph:
    def __init__(self):
        from neo4j import GraphDatabase
        self.driver = GraphDatabase.driver(NEO4J_URL, auth=(NEO4J_USER, NEO4J_PASS))
        self.driver.verify_connectivity()          # raises if Neo4j isn't running
        self.backend = "neo4j"

    def clear(self):
        with self.driver.session() as s:
            s.run("MATCH (n) DETACH DELETE n")       # wipe old data

    def add_rule(self, activity, unit, factor_id, value):
        # store: (Activity)-[:USES_FACTOR]->(Factor)   = the HARD RULE
        with self.driver.session() as s:
            s.run("""
                MERGE (a:Activity {name:$activity, unit:$unit})
                MERGE (f:Factor {id:$factor_id})
                  SET f.value = $value
                MERGE (a)-[:USES_FACTOR]->(f)
            """, activity=activity, unit=unit, factor_id=factor_id, value=value)

    def get_factor(self, activity, unit):
        # follow the rule: electricity+kWh -> its allowed factor
        with self.driver.session() as s:
            rec = s.run("""
                MATCH (a:Activity {name:$activity, unit:$unit})-[:USES_FACTOR]->(f:Factor)
                RETURN f.id AS id, f.value AS value
            """, activity=activity, unit=unit).single()
            return (rec["id"], rec["value"]) if rec else (None, None)

    def add_lineage(self, line_id, factor_id, source):
        # store: (Number)-[:USED]->(Factor) and (Number)-[:FROM_SOURCE]->(Source)
        with self.driver.session() as s:
            s.run("""
                MERGE (n:Number {line_id:$line_id})
                MERGE (f:Factor {id:$factor_id})
                MERGE (src:SourceDoc {name:$source})
                MERGE (n)-[:USED]->(f)
                MERGE (n)-[:FROM_SOURCE]->(src)
            """, line_id=line_id, factor_id=factor_id, source=source)

    def close(self):
        self.driver.close()


# =====================================================================
# BACKEND 2: in-memory fallback (no Neo4j needed)
# =====================================================================
class MemoryGraph:
    def __init__(self):
        self.rules = {}       # (activity, unit) -> (factor_id, value)
        self.lineage = []     # list of (line_id, factor_id, source)
        self.backend = "memory"

    def clear(self):
        self.rules.clear(); self.lineage.clear()

    def add_rule(self, activity, unit, factor_id, value):
        self.rules[(activity, unit)] = (factor_id, value)

    def get_factor(self, activity, unit):
        return self.rules.get((activity, unit), (None, None))

    def add_lineage(self, line_id, factor_id, source):
        self.lineage.append((line_id, factor_id, source))

    def close(self):
        pass


# =====================================================================
# pick a backend automatically
# =====================================================================
def get_graph():
    """Use Neo4j if it's running; otherwise fall back to memory."""
    try:
        g = Neo4jGraph()
        print("✅ Using real Neo4j.")
        return g
    except Exception as e:
        print(f"⚠️  Neo4j not available ({type(e).__name__}) — using in-memory graph instead.")
        return MemoryGraph()


# =====================================================================
# load the hard rules from the factor library
# =====================================================================
def factor_activity_type(row):
    """Map a factor row to a clean activity type. Order matters: specific first."""
    text = f"{row['activity']} {row['aliases']}".lower()
    # check most specific / least ambiguous first, whole-word match
    checks = [
        ("electricity", ["electricity", "grid"]),
        ("diesel",      ["diesel", "hsd"]),
        ("petrol",      ["petrol", "gasoline", "motor spirit"]),
        ("lpg",         ["lpg", "propane", "cooking gas"]),
        ("natural gas", ["natural gas", "png", "piped natural gas"]),
    ]
    for activity, words in checks:
        for w in words:
            if re.search(r"\b" + re.escape(w) + r"\b", text):
                return activity
    return row["activity"].strip().lower()

def load_rules_into_graph(g):
    """Read the factor library and store activity->factor rules in the graph."""
    g.clear()
    with open(DATA_DIR / "emission_factors.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            # skip the Combined-Margin electricity factor (not for corporate Scope 2)
            if row["factor_id"] == "EF-IN-ELEC-GRID-CM":
                continue
            activity = factor_activity_type(row)
            unit = row["unit_in"].strip().lower()
            g.add_rule(activity, unit, row["factor_id"], float(row["factor_kgco2e_per_unit"]))


# =====================================================================
# quick test when run directly
# =====================================================================
def main():
    g = get_graph()
    print(f"Backend: {g.backend}\n")

    load_rules_into_graph(g)

    # test the HARD RULE lookups
    print("Rule lookups (activity, unit) -> factor:")
    for activity, unit in [("electricity", "kwh"), ("diesel", "litre"),
                           ("natural gas", "m3"), ("petrol", "litre")]:
        fid, val = g.get_factor(activity, unit)
        print(f"   {activity:12} {unit:6} -> {fid} ({val})")

    # add one lineage example
    g.add_lineage("ELEC-0001", "EF-IN-ELEC-GRID", "electricity_bills.csv row 2")
    print("\nLineage stored for ELEC-0001 -> EF-IN-ELEC-GRID -> electricity_bills.csv row 2")

    g.close()


if __name__ == "__main__":
    main()