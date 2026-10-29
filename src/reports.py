"""
src/reports.py
--------------
Export helpers for the Smart Business Data Analytics Platform.

Provides:
  export_csv(df, filters)         → UTF-8 CSV bytes for Streamlit download
  build_pdf_report(kpis, insights, filters) → PDF bytes (or None if fpdf2 missing)

Design rules
------------
- Nothing is written to disk.  BytesIO is used throughout.
- export_csv always succeeds — it has no optional dependency.
- build_pdf_report tries to import fpdf2 at call time and returns None with
  a warning string when the library is unavailable.
- typing.Optional is used instead of X | None for Python 3.9 compatibility.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

# ── CSV export ────────────────────────────────────────────────────────────────


def export_csv(
    df: pd.DataFrame,
    filters: Optional[Dict] = None,
) -> bytes:
    """
    Serialise a DataFrame to UTF-8 CSV bytes suitable for a Streamlit
    ``st.download_button``.

    A metadata header block is prepended as comment lines (``#``) so the
    file is both human-readable and machine-parseable.

    Parameters
    ----------
    df : pd.DataFrame
        The filtered transactions (or any analytics result) to export.
    filters : dict, optional
        Applied filter values to record in the header.

    Returns
    -------
    bytes
        UTF-8-encoded CSV with a comment header.
    """
    lines: List[str] = []
    lines.append("# Smart Business Data Analytics Platform — Data Export")
    lines.append(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("# NOTE: Sample data is synthetic and for demonstration only.")

    if filters:
        for key, val in filters.items():
            lines.append(f"# Filter — {key}: {val}")

    lines.append(f"# Rows: {len(df)}")
    lines.append("#")

    header_block = "\n".join(lines) + "\n"
    csv_block = df.to_csv(index=False)
    return (header_block + csv_block).encode("utf-8")


# ── PDF report ────────────────────────────────────────────────────────────────

# Colour palette (R, G, B)
_NAVY = (31, 73, 125)
_DARK_GREY = (50, 50, 50)
_MID_GREY = (120, 120, 120)
_LIGHT_GREY_FILL = (245, 246, 248)
_WHITE = (255, 255, 255)
_RED = (200, 40, 40)
_AMBER = (180, 100, 0)
_GREEN = (30, 130, 60)

_SEVERITY_COLOURS = {
    "critical": _RED,
    "warning": _AMBER,
    "info": _GREEN,
}


def _severity_label(severity: str) -> str:
    icons = {"critical": "CRITICAL", "warning": "WARNING", "info": "INFO"}
    return icons.get(severity, severity.upper())


def build_pdf_report(
    kpis: Dict,
    insights: List[Dict],
    filters: Optional[Dict] = None,
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Build a PDF summary report in memory and return it as bytes.

    PDF layout
    ----------
    1. Header — title, generation date
    2. Applied filters summary
    3. KPI summary table
    4. Business insights list (sorted by severity: critical first)
    5. Footer with timestamp

    Parameters
    ----------
    kpis : dict
        Output of ``analytics.compute_kpis()``.
    insights : list[dict]
        Output of ``insights.generate_insights()``.
    filters : dict, optional
        Applied filter values to display in the report.

    Returns
    -------
    (pdf_bytes, error_message)
        On success  : (bytes, None)
        On failure  : (None, str) — e.g. fpdf2 not installed, or render error
    """
    try:
        from fpdf import FPDF  # fpdf2 package exposes `fpdf` module
    except ImportError:
        return None, (
            "fpdf2 is not installed. Run `pip install fpdf2` to enable PDF export."
        )

    try:
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # ── 1. Header ─────────────────────────────────────────────────────────
        pdf.set_fill_color(*_NAVY)
        pdf.rect(0, 0, 210, 28, style="F")

        pdf.set_text_color(*_WHITE)
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_y(8)
        pdf.cell(0, 8, "Smart Business Data Analytics", align="C", new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "", 9)
        pdf.cell(
            0, 6,
            f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            align="C",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(6)

        # ── 2. Applied filters ────────────────────────────────────────────────
        pdf.set_text_color(*_DARK_GREY)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Applied Filters", new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(*_NAVY)
        pdf.set_line_width(0.5)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(2)

        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_MID_GREY)
        if filters:
            for key, val in filters.items():
                pdf.cell(0, 5, f"  {key}: {val}", new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.cell(0, 5, "  No filters applied - showing all data.", new_x="LMARGIN", new_y="NEXT")

        pdf.ln(4)

        # ── 3. KPI table ──────────────────────────────────────────────────────
        pdf.set_text_color(*_DARK_GREY)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Key Performance Indicators", new_x="LMARGIN", new_y="NEXT")
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(2)

        kpi_rows = [
            ("Total Revenue",     f"${kpis.get('total_revenue', 0):,.2f}"),
            ("Total Profit",      f"${kpis.get('total_profit', 0):,.2f}"),
            ("Total Orders",      f"{kpis.get('total_orders', 0):,}"),
            ("Total Line Items",  f"{kpis.get('total_line_items', 0):,}"),
            ("Avg Order Value",   f"${kpis.get('avg_order_value', 0):,.2f}"),
            ("Profit Margin",     f"{kpis.get('profit_margin_pct', 0):.1f}%"),
        ]

        col_label_w = 80
        col_value_w = 60

        # Table header row
        pdf.set_fill_color(*_NAVY)
        pdf.set_text_color(*_WHITE)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(col_label_w, 7, "  Metric", fill=True)
        pdf.cell(col_value_w, 7, "Value", fill=True, new_x="LMARGIN", new_y="NEXT")

        # Table data rows — alternating fill
        pdf.set_font("Helvetica", "", 9)
        for i, (label, value) in enumerate(kpi_rows):
            if i % 2 == 0:
                pdf.set_fill_color(*_LIGHT_GREY_FILL)
            else:
                pdf.set_fill_color(*_WHITE)
            pdf.set_text_color(*_DARK_GREY)
            pdf.cell(col_label_w, 6, f"  {label}", fill=True)
            pdf.cell(col_value_w, 6, value, fill=True, new_x="LMARGIN", new_y="NEXT")

        pdf.ln(5)

        # ── 4. Business Insights ──────────────────────────────────────────────
        pdf.set_text_color(*_DARK_GREY)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Business Insights", new_x="LMARGIN", new_y="NEXT")
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(2)

        if not insights:
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(*_MID_GREY)
            pdf.cell(
                0, 6,
                "  No insights generated for the selected data range.",
                new_x="LMARGIN",
                new_y="NEXT",
            )
        else:
            for ins in insights:
                severity = str(ins.get("severity", "info"))
                colour = _SEVERITY_COLOURS.get(severity, _DARK_GREY)
                label = _severity_label(severity)
                message = str(ins.get("message", ""))
                recommendation = str(ins.get("recommendation", ""))

                # Severity badge
                pdf.set_fill_color(*colour)
                pdf.set_text_color(*_WHITE)
                pdf.set_font("Helvetica", "B", 8)
                pdf.cell(22, 5, f" {label}", fill=True)

                # Message
                pdf.set_text_color(*_DARK_GREY)
                pdf.set_font("Helvetica", "", 9)
                # Use multi_cell for wrapping; shift X first
                x_after_badge = pdf.get_x()
                pdf.multi_cell(
                    0, 5,
                    f" {message}",
                    new_x="LMARGIN",
                    new_y="NEXT",
                )

                # Recommendation (indented, muted)
                pdf.set_text_color(*_MID_GREY)
                pdf.set_font("Helvetica", "I", 8)
                pdf.multi_cell(
                    0, 4,
                    f"    -> {recommendation}",
                    new_x="LMARGIN",
                    new_y="NEXT",
                )
                pdf.ln(2)

        # ── 5. Footer ─────────────────────────────────────────────────────────
        pdf.set_y(-20)
        pdf.set_draw_color(*_MID_GREY)
        pdf.set_line_width(0.3)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.set_font("Helvetica", "I", 7)
        pdf.set_text_color(*_MID_GREY)
        generated_ts = datetime.now().strftime('%Y-%m-%d %H:%M')
        pdf.cell(
            0, 5,
            f"Smart Business Data Analytics Platform - Sample data is synthetic - Generated {generated_ts}",
            align="C",
        )

        # ── Serialise to bytes ─────────────────────────────────────────────────
        buf = io.BytesIO()
        pdf_bytes = pdf.output()   # fpdf2 returns bytes when no dest argument
        if isinstance(pdf_bytes, (bytes, bytearray)):
            buf.write(pdf_bytes)
        else:
            buf.write(pdf_bytes.encode("latin-1"))
        return buf.getvalue(), None

    except Exception as exc:  # noqa: BLE001
        return None, f"PDF generation failed: {exc}"
