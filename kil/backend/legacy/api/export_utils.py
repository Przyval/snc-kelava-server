"""
CSV Export Utility
===================
Shared helper for exporting data tables as CSV.
Used by any API endpoint that supports ?format=csv.
"""

import csv
import io
from datetime import date, datetime

from flask import make_response


def _serialize_value(v):
    """Convert a value to a CSV-safe string."""
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, bool):
        return "Ya" if v else "Tidak"
    return str(v)


def rows_to_csv_response(rows, filename="export.csv", columns=None):
    """
    Convert a list of dicts to a CSV download response.

    Args:
        rows: List of dict rows from DB query
        filename: Download filename
        columns: Optional list of column names to include (in order).
                 If None, uses all keys from first row.

    Returns:
        Flask Response with CSV content
    """
    if not rows:
        return make_response("No data to export", 204)

    if columns:
        fieldnames = columns
    else:
        fieldnames = list(rows[0].keys())

    output = io.StringIO()
    # BOM for Excel UTF-8 compatibility
    output.write("\ufeff")

    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for row in rows:
        writer.writerow({k: _serialize_value(row.get(k)) for k in fieldnames})

    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response
