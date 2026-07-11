"""
ingest.py  —  SP-01: read messy bill files (CSV + PDF) into ONE common format.

This step ONLY reads files and remembers where each row came from.
It does NOT clean data, fix units, or calculate anything — that comes later.
"""

import pandas as pd          # library for reading tables (CSV/Excel)
import pdfplumber            # library for reading PDFs
from pathlib import Path     # small helper for working with file names/paths

from paths import DATA_DIR
from logging_setup import get_logger

log = get_logger(__name__)


# ---------- 1. READ ONE CSV FILE ----------
def ingest_csv(file_path):
    """Read one CSV file and return a list of records."""
    df = pd.read_csv(file_path)          # load the file into a table (DataFrame)
    file_name = Path(file_path).name     # just the name, e.g. "electricity_bills.csv"

    records = []
    for i, row in df.iterrows():         # go through the table one row at a time
        record = {
            "source_file": file_name,
            "source_row": int(i) + 2,    # +2 because row 1 in the file is the header
            "source_type": "csv",
            "raw": row.dropna().to_dict()  # keep only the filled-in cells, as a dict
        }
        records.append(record)           # add this record to our list

    log.info("Loaded CSV %s: %d rows, %d cols", file_name, df.shape[0], df.shape[1])
    return records


# ---------- 2. READ ONE PDF FILE ----------
def ingest_pdf(file_path):
    """Read one PDF file and return a list of records (one per page)."""
    file_name = Path(file_path).name

    records = []
    with pdfplumber.open(file_path) as pdf:            # open the PDF safely
        for page_number, page in enumerate(pdf.pages, start=1):  # each page, from 1
            text = page.extract_text() or ""           # get the page text ("" if none)
            record = {
                "source_file": file_name,
                "source_page": page_number,
                "source_type": "pdf",
                "raw_text": text
            }
            records.append(record)

    log.info("Loaded PDF %s: %d page(s)", file_name, len(records))
    return records


# ---------- 3. RUN EVERYTHING ----------
def main():
    all_records = []                     # one big list for everything we load

    # the CSV files we want to read
    csv_files = [
        DATA_DIR / "electricity_bills.csv",
        DATA_DIR / "diesel_invoices.csv",
        DATA_DIR / "erp_spend_export.csv",
    ]
    for path in csv_files:
        all_records += ingest_csv(path)  # read each CSV and add its records

    # read the PDF bill
    all_records += ingest_pdf(DATA_DIR / "electricity_bill_sample.pdf")

    # ----- summary -----
    print("\nTotal records loaded:", len(all_records))

    # show one CSV record so we can see the shape
    print("\nExample CSV record:")
    print(all_records[0])

    # show one PDF record
    print("\nExample PDF record:")
    for r in all_records:
        if r["source_type"] == "pdf":
            print("source_file:", r["source_file"])
            print("source_page:", r["source_page"])
            print("first line of text:", r["raw_text"].splitlines()[0])
            break


# this line means: only run main() when we run THIS file directly
if __name__ == "__main__":
    main()