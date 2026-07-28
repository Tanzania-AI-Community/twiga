from pathlib import Path

import pandas as pd

_GOLDEN_DIR = Path(__file__).parent / "data" / "golden"


def validate_testset(df: pd.DataFrame) -> tuple[bool, str]:
    """Returns (is_valid, error_message)."""
    if "user_query" not in df.columns:
        return False, "Missing required column: 'user_query'"
    ref_cols = [c for c in df.columns if c.startswith("reference")]
    if not ref_cols:
        return False, "Missing at least one reference column (e.g. 'reference')"
    return True, ""


def save_testset(df: pd.DataFrame, name: str) -> Path:
    _GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    if not name.endswith(".csv"):
        name = name + ".csv"
    path = _GOLDEN_DIR / name
    df.to_csv(path, index=False)
    return path


def load_testset(name: str) -> pd.DataFrame:
    if not name.endswith(".csv"):
        name = name + ".csv"
    return pd.read_csv(_GOLDEN_DIR / name)


def list_testsets() -> list[str]:
    if not _GOLDEN_DIR.exists():
        return []
    return [p.name for p in sorted(_GOLDEN_DIR.glob("*.csv"))]
