"""
src/data_loader.py
------------------
Reads CSV and Excel files into raw Pandas DataFrames.

The loader does the minimum necessary:
- Detect file type from the extension.
- Parse the file into a DataFrame.
- Normalise column names (strip whitespace, lowercase).

All schema enforcement, type coercion, and business-rule validation
is delegated to src/data_validation.py.
"""

from __future__ import annotations

import io
from typing import Union

import pandas as pd

# Maximum accepted file size in bytes (50 MB)
MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024

# Accepted extensions
ALLOWED_EXTENSIONS = {".csv", ".xlsx"}


def load_file(uploaded_file: Union[io.BytesIO, "streamlit.runtime.uploaded_file_manager.UploadedFile", str]) -> pd.DataFrame:  # type: ignore[name-defined]
    """
    Read a CSV or Excel uploaded file into a raw DataFrame.

    Parameters
    ----------
    uploaded_file
        A Streamlit UploadedFile object, a BytesIO buffer, or a file-system
        path string / pathlib.Path.  Must be a ``.csv`` or ``.xlsx`` file.

    Returns
    -------
    pd.DataFrame
        Raw DataFrame with column names normalised (stripped + lowercased).

    Raises
    ------
    ValueError
        If the file extension is not in ALLOWED_EXTENSIONS, the file exceeds
        MAX_FILE_SIZE_BYTES, or the file cannot be parsed.
    """
    import pathlib

    # ── Determine filename and size ───────────────────────────────────────────
    if isinstance(uploaded_file, (str, pathlib.Path)):
        path = pathlib.Path(uploaded_file)
        name = path.name
        size = path.stat().st_size
        data: Union[str, io.BytesIO] = str(path)
    else:
        # Streamlit UploadedFile or BytesIO
        name = getattr(uploaded_file, "name", "upload")
        # Determine size without consuming the stream
        pos = uploaded_file.tell() if hasattr(uploaded_file, "tell") else 0
        uploaded_file.seek(0, 2)  # seek to end
        size = uploaded_file.tell()
        uploaded_file.seek(pos)   # reset to original position
        data = uploaded_file

    # ── Extension check ───────────────────────────────────────────────────────
    ext = pathlib.Path(name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            f"Please upload a .csv or .xlsx file."
        )

    # ── Size check ────────────────────────────────────────────────────────────
    if size > MAX_FILE_SIZE_BYTES:
        mb = size / (1024 * 1024)
        raise ValueError(
            f"File is {mb:.1f} MB, which exceeds the 50 MB limit. "
            "Please split the file and import in batches."
        )

    # ── Parse ─────────────────────────────────────────────────────────────────
    try:
        if ext == ".csv":
            df = pd.read_csv(data, dtype=str, comment="#")  # skip comment lines; coerce types later
        else:
            df = pd.read_excel(data, dtype=str)
    except Exception as exc:
        raise ValueError(f"Could not parse file '{name}': {exc}") from exc

    # ── Normalise column names ─────────────────────────────────────────────────
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    return df
