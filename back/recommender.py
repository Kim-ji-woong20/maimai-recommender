from __future__ import annotations

import json
import math
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd

from rating_bands import parse_rating_band_low, rating_to_band


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

CHARTS_PATH = DATA_DIR / "maimai_charts_13_15.csv"
COHORT_STATS_PATH = DATA_DIR / "cohort_chart_stats.csv"
LEVEL_STATS_PATH = DATA_DIR / "level_distribution_stats.csv"
RAW_USER_BEST50_PATH = DATA_DIR / "raw_user_best50.csv"
NEW_VERSIONS_PATH = DATA_DIR / "new_versions.json"


LEVEL_BOUNDS = {
    "13": (13.0, 13.5),
    "13+": (13.6, 13.9),
    "14": (14.0, 14.5),
    "14+": (14.6, 14.9),
    "15": (15.0, 99.0),
}

USER_RECORD_COLUMNS = [
    "chart_id",
    "achievement",
    "rank",
    "play_count",
    "chart_rating",
    "is_best50",
    "best50_section",
    "best50_order",
    "record_source",
    "combo",
    "sync",
]

REVERSE_BORDER_MIN = 100.4000
REVERSE_BORDER_MAX = 100.5000

SIMILAR_USER_TOP_K = 30
SIMILAR_USER_MIN_INPUT_BEST50 = 5
SIMILAR_USER_MIN_SIMILARITY = 0.05

MIN_COHORT_USER_COUNT = 3
MIN_COHORT_RECORD_COUNT = 80
MIN_COHORT_BEST50_COUNT = 30

CURRENT_BAND_LOWER_EXPANSION_STEPS = 1
CURRENT_BAND_UPPER_EXPANSION_STEPS = 1
TARGET_BAND_LOWER_EXPANSION_STEPS = 0
TARGET_BAND_UPPER_EXPANSION_STEPS = 2

NEW_FLOOR_REQUIRED_COUNT = 15
OLD_FLOOR_REQUIRED_COUNT = 35
TOTAL_BEST50_REQUIRED_COUNT = 50

# 상위권 유저는 Best50 floor가 높기 때문에 rating_up 후보를 더 엄격하게 필터링한다.
RATING_UP_HIGH_RATING_THRESHOLD = 16400
RATING_UP_MIN_POSITIVE_FLOOR_GAIN = 0.0001

# similar_user 모드는 입력 유저의 전체 플레이 기록 기준 미플레이 후보를 우선 정렬한다.
SIMILAR_USER_UNPLAYED_SORT_FIRST = True


# ------------------------------------------------------------
# Basic helpers
# ------------------------------------------------------------

def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or pd.isna(value):
            return default
        return int(float(value))
    except Exception:
        return default


def safe_str(value: Any, default: str = "") -> str:
    try:
        if value is None or pd.isna(value):
            return default
        return str(value)
    except Exception:
        return default


DEFAULT_NEW_VERSIONS = {
    "PRISM PLUS",
    "CIRCLE",
}


def normalize_version_name(value: Any) -> str:
    """
    maimai version string을 비교 가능한 형태로 정규화한다.

    예:
    - PRiSM PLUS -> PRISM PLUS
    - CiRCLE -> CIRCLE
    - maimai DX PRiSM PLUS -> PRISM PLUS
    """
    text = safe_str(value, "").strip()

    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)
    text = text.upper()
    text = text.replace("MAIMAI DX", "")
    text = text.replace("MAIMAI", "")
    text = text.replace("DX", "")
    text = text.replace("_", " ")
    text = text.replace("-", " ")
    text = " ".join(text.split())

    return text


def load_new_versions() -> set[str]:
    """
    data/new_versions.json에서 NEW Best15 대상 버전 목록을 읽는다.

    파일이 없거나 깨져 있으면 PRiSM PLUS / CiRCLE을 기본값으로 사용한다.
    """
    if not NEW_VERSIONS_PATH.exists():
        return set(DEFAULT_NEW_VERSIONS)

    try:
        with open(NEW_VERSIONS_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)

        versions = payload.get("new_versions", [])
        normalized_versions = {
            normalize_version_name(version)
            for version in versions
            if normalize_version_name(version)
        }

        if normalized_versions:
            return normalized_versions

    except Exception:
        pass

    return set(DEFAULT_NEW_VERSIONS)


CURRENT_NEW_VERSIONS = load_new_versions()


def version_matches_new_version(version_text: Any) -> bool:
    normalized = normalize_version_name(version_text)

    if not normalized:
        return False

    for new_version in CURRENT_NEW_VERSIONS:
        if not new_version:
            continue

        if normalized == new_version:
            return True

        if normalized.endswith(new_version):
            return True

        if new_version in normalized:
            return True

    return False


def is_new_version_chart(row: pd.Series) -> bool:
    candidates = [
        row.get("version", ""),
        row.get("sheet_version", ""),
        row.get("song_version", ""),
        row.get("chart_version", ""),
    ]

    return any(version_matches_new_version(value) for value in candidates)


def normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return False

    if isinstance(value, (int, float)):
        if pd.isna(value):
            return False
        return value != 0

    text = str(value).strip().lower()

    return text in {
        "true",
        "1",
        "yes",
        "y",
        "t",
        "best50",
        "b50",
    }


def normalize_is_new(value: Any) -> bool:
    return normalize_bool(value)


def make_empty_user_records() -> pd.DataFrame:
    return pd.DataFrame(columns=USER_RECORD_COLUMNS)


def normalize_rate_to_percent(value: Any) -> float:
    number = safe_float(value, 0.0)

    if number <= 1.5:
        number *= 100.0

    return max(0.0, min(number, 100.0))


def normalize_rate_series(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").fillna(0.0)

    if len(numeric) > 0 and numeric.max() <= 1.5:
        numeric = numeric * 100.0

    return numeric.clip(lower=0.0, upper=100.0)


def min_max_scale_series(series: pd.Series, default: float = 0.0) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").fillna(default)

    if numeric.empty:
        return numeric

    min_value = numeric.min()
    max_value = numeric.max()

    if max_value <= min_value:
        return pd.Series([50.0] * len(numeric), index=numeric.index)

    return ((numeric - min_value) / (max_value - min_value) * 100.0).clip(0.0, 100.0)


# ------------------------------------------------------------
# maimai rating approximation
# ------------------------------------------------------------

def calculate_chart_rating(internal_level: Any, achievement: Any) -> int:
    """
    maimai 곡별 레이팅을 근사 계산한다.

    실제 게임 내부 계산식과 완전히 동일하다고 보장하기보다는,
    추천 후보 간 상승 여지와 Best50 floor 대체 가능성을 비교하기 위한
    안정적인 보조 지표로 사용한다.
    """
    ds = safe_float(internal_level, 0.0)
    ach = safe_float(achievement, 0.0)

    if ds <= 0 or ach <= 0:
        return 0

    ach = min(ach, REVERSE_BORDER_MAX)

    coefficient_table = [
        (100.5, 22.4),
        (100.0, 21.6),
        (99.5, 21.1),
        (99.0, 20.8),
        (98.0, 20.3),
        (97.0, 20.0),
        (94.0, 16.8),
        (90.0, 15.2),
        (80.0, 13.6),
        (75.0, 12.0),
        (70.0, 11.2),
        (60.0, 9.6),
        (50.0, 8.0),
        (40.0, 6.4),
        (30.0, 4.8),
        (20.0, 3.2),
        (10.0, 1.6),
        (0.0, 0.0),
    ]

    coefficient = 0.0

    for threshold, candidate_coefficient in coefficient_table:
        if ach >= threshold:
            coefficient = candidate_coefficient
            break

    return int(math.floor(ds * ach * coefficient / 100.0))


# ------------------------------------------------------------
# Data loaders
# ------------------------------------------------------------

def load_charts() -> pd.DataFrame:
    if not CHARTS_PATH.exists():
        raise FileNotFoundError(f"Chart DB not found: {CHARTS_PATH}")

    charts = pd.read_csv(CHARTS_PATH)

    required_columns = [
        "chart_id",
        "title",
        "level",
        "internal_level",
        "difficulty",
        "chart_type",
    ]

    missing_columns = [
        column for column in required_columns
        if column not in charts.columns
    ]

    if missing_columns:
        raise ValueError(
            f"maimai_charts_13_15.csv missing columns: {missing_columns}"
        )

    if "is_new" not in charts.columns:
        charts["is_new"] = False

    charts["is_new"] = charts["is_new"].apply(normalize_is_new)

    optional_columns = {
        "song_id": "",
        "artist": "",
        "category": "",
        "version": "",
        "sheet_version": "",
        "release_date": "",
        "image_name": "",
        "thumbnail_url": "",
        "display_level": "",
        "bpm": 0.0,
        "is_special": False,
        "note_designer": "",
        "tap_count": 0,
        "hold_count": 0,
        "slide_count": 0,
        "touch_count": 0,
        "break_count": 0,
        "total_note_count": 0,
    }

    for col, default_value in optional_columns.items():
        if col not in charts.columns:
            charts[col] = default_value

    text_columns = [
        "chart_id",
        "song_id",
        "title",
        "artist",
        "category",
        "version",
        "sheet_version",
        "release_date",
        "image_name",
        "thumbnail_url",
        "level",
        "display_level",
        "difficulty",
        "chart_type",
        "note_designer",
    ]

    for col in text_columns:
        charts[col] = charts[col].fillna("").astype(str)

    numeric_columns = [
        "internal_level",
        "bpm",
        "tap_count",
        "hold_count",
        "slide_count",
        "touch_count",
        "break_count",
        "total_note_count",
    ]

    for col in numeric_columns:
        charts[col] = pd.to_numeric(charts[col], errors="coerce").fillna(0.0)

    charts["is_special"] = charts["is_special"].apply(normalize_bool)

    return charts


def load_cohort_stats() -> pd.DataFrame:
    if not COHORT_STATS_PATH.exists():
        return pd.DataFrame()

    df = pd.read_csv(COHORT_STATS_PATH)

    if "chart_id" not in df.columns or "rating_band" not in df.columns:
        return pd.DataFrame()

    df["chart_id"] = df["chart_id"].fillna("").astype(str)
    df["rating_band"] = df["rating_band"].fillna("").astype(str)

    df = df[
        (df["chart_id"].str.len() > 0)
        & (df["rating_band"].str.len() > 0)
    ].copy()

    return df


def load_level_stats() -> pd.DataFrame:
    if not LEVEL_STATS_PATH.exists():
        return pd.DataFrame()

    return pd.read_csv(LEVEL_STATS_PATH)


def load_raw_user_best50() -> pd.DataFrame:
    """
    협업 필터링용 raw_user_best50.csv 로더.

    각 유저의 Best50 chart_id를 이용해 user-item matrix를 구성한다.
    """
    if not RAW_USER_BEST50_PATH.exists():
        return pd.DataFrame()

    df = pd.read_csv(RAW_USER_BEST50_PATH)

    if "chart_id" not in df.columns:
        return pd.DataFrame()

    if "profile_id" not in df.columns:
        if "user_id" in df.columns:
            df["profile_id"] = df["user_id"]
        elif "profile_url" in df.columns:
            df["profile_id"] = df["profile_url"]
        else:
            return pd.DataFrame()

    df["profile_id"] = df["profile_id"].fillna("").astype(str)
    df["chart_id"] = df["chart_id"].fillna("").astype(str)

    df = df[
        (df["profile_id"].str.len() > 0)
        & (df["chart_id"].str.len() > 0)
    ].copy()

    if "is_best50" in df.columns:
        df = df[df["is_best50"].apply(normalize_bool)].copy()

    df = df.drop_duplicates(
        subset=["profile_id", "chart_id"],
        keep="first",
    ).reset_index(drop=True)

    return df


# ------------------------------------------------------------
# User records and base candidate table
# ------------------------------------------------------------

def prepare_user_records(user_records_df: pd.DataFrame | None = None) -> pd.DataFrame:
    if user_records_df is None:
        user_records_df = make_empty_user_records()

    records = user_records_df.copy()

    for col in USER_RECORD_COLUMNS:
        if col not in records.columns:
            if col in {"achievement", "play_count", "chart_rating", "best50_order"}:
                records[col] = 0
            elif col == "is_best50":
                records[col] = False
            else:
                records[col] = ""

    records["chart_id"] = records["chart_id"].fillna("").astype(str)

    numeric_columns = [
        "achievement",
        "play_count",
        "chart_rating",
        "best50_order",
    ]

    for col in numeric_columns:
        records[col] = pd.to_numeric(records[col], errors="coerce").fillna(0.0)

    records["is_best50"] = records["is_best50"].apply(normalize_bool)
    records["best50_section"] = records["best50_section"].fillna("").astype(str)
    records["rank"] = records["rank"].fillna("").astype(str)
    records["record_source"] = records["record_source"].fillna("").astype(str)
    records["combo"] = records["combo"].fillna("").astype(str)
    records["sync"] = records["sync"].fillna("").astype(str)

    records = records[records["chart_id"].str.len() > 0].copy()

    records = records.sort_values(
        ["is_best50", "chart_rating", "achievement"],
        ascending=[False, False, False],
    )

    records = records.drop_duplicates(
        subset=["chart_id"],
        keep="first",
    ).reset_index(drop=True)

    return records[USER_RECORD_COLUMNS]


def classify_candidate(row: pd.Series) -> str:
    if bool(row.get("is_best50", False)):
        return "best50"

    if bool(row.get("played", False)):
        return "played_not_best50"

    return "unplayed_or_unmatched"


def load_base_data(user_records_df: pd.DataFrame | None = None) -> pd.DataFrame:
    charts = load_charts()
    user_records = prepare_user_records(user_records_df)

    df = charts.merge(
        user_records,
        on="chart_id",
        how="left",
    )

    df["achievement"] = pd.to_numeric(df["achievement"], errors="coerce").fillna(0.0)
    df["play_count"] = pd.to_numeric(df["play_count"], errors="coerce").fillna(0.0)
    df["chart_rating"] = pd.to_numeric(df["chart_rating"], errors="coerce").fillna(0.0)
    df["best50_order"] = pd.to_numeric(df["best50_order"], errors="coerce").fillna(0.0)

    df["is_best50"] = df["is_best50"].apply(normalize_bool)
    df["rank"] = df["rank"].fillna("").astype(str)
    df["best50_section"] = df["best50_section"].fillna("").astype(str)
    df["record_source"] = df["record_source"].fillna("").astype(str)
    df["combo"] = df["combo"].fillna("").astype(str)
    df["sync"] = df["sync"].fillna("").astype(str)

    df["played"] = df["achievement"] > 0
    df["rating_capped"] = df["achievement"] >= REVERSE_BORDER_MAX

    df["current_rating"] = df["chart_rating"]

    missing_current_rating = (
        (df["current_rating"] <= 0)
        & (df["played"])
    )

    df.loc[missing_current_rating, "current_rating"] = df.loc[
        missing_current_rating
    ].apply(
        lambda row: calculate_chart_rating(
            row["internal_level"],
            row["achievement"],
        ),
        axis=1,
    )

    df["max_rating"] = df.apply(
        lambda row: calculate_chart_rating(row["internal_level"], REVERSE_BORDER_MAX),
        axis=1,
    )
    df["expected_rating_100_5"] = df["max_rating"]

    df["rating_gain"] = (df["max_rating"] - df["current_rating"]).clip(lower=0.0)

    df["reverse_border"] = (
        (df["played"])
        & (df["achievement"] >= REVERSE_BORDER_MIN)
        & (df["achievement"] < REVERSE_BORDER_MAX)
    )

    df["reverse_border_gap"] = (REVERSE_BORDER_MAX - df["achievement"]).clip(lower=0.0)
    df.loc[~df["reverse_border"], "reverse_border_gap"] = 0.0

    df["candidate_label"] = df.apply(classify_candidate, axis=1)

    return df


# ------------------------------------------------------------
# Rating / band helpers
# ------------------------------------------------------------

def estimate_rating_from_records(df: pd.DataFrame) -> int | None:
    if df.empty or "current_rating" not in df.columns:
        return None

    best50 = df[
        (df["is_best50"])
        & (df["current_rating"] > 0)
    ].copy()

    if best50.empty:
        best50 = df[df["current_rating"] > 0].copy()

    if best50.empty:
        return None

    estimated = best50["current_rating"].sort_values(ascending=False).head(50).sum()

    if estimated <= 0:
        return None

    return int(round(float(estimated)))


def get_available_bands(cohort_stats: pd.DataFrame) -> list[str]:
    if cohort_stats.empty or "rating_band" not in cohort_stats.columns:
        return []

    bands = []

    for band in cohort_stats["rating_band"].dropna().astype(str).unique():
        band = band.strip()
        if not band:
            continue

        low = parse_rating_band_low(band)

        if low is not None:
            bands.append((low, band))

    bands = sorted(bands, key=lambda item: item[0])

    return [band for _, band in bands]


def get_target_band_from_available(current_band: str, available_bands: list[str]) -> str:
    current_low = parse_rating_band_low(current_band)

    if current_low is None:
        return current_band

    parsed = []

    for band in available_bands:
        low = parse_rating_band_low(band)

        if low is not None:
            parsed.append((low, band))

    parsed = sorted(parsed, key=lambda item: item[0])

    for low, band in parsed:
        if low > current_low:
            return band

    if current_band in available_bands:
        return current_band

    if parsed:
        return parsed[-1][1]

    return current_band


def get_band_index_map(available_bands: list[str]) -> dict[str, int]:
    return {band: idx for idx, band in enumerate(available_bands)}


def get_neighbor_bands_from_available(
    center_band: str,
    available_bands: list[str],
    lower_steps: int,
    upper_steps: int,
) -> list[str]:
    if not available_bands:
        return [center_band] if center_band else []

    index_map = get_band_index_map(available_bands)

    if center_band not in index_map:
        center_low = parse_rating_band_low(center_band)
        parsed = [
            (parse_rating_band_low(band), band)
            for band in available_bands
        ]
        parsed = [item for item in parsed if item[0] is not None]
        parsed = sorted(parsed, key=lambda item: item[0])

        if not parsed:
            return [center_band] if center_band else []

        if center_low is None:
            center_idx = 0
        else:
            center_idx = min(
                range(len(parsed)),
                key=lambda idx: abs(parsed[idx][0] - center_low),
            )

        center_band = parsed[center_idx][1]

    center_idx = index_map.get(center_band, 0)
    start_idx = max(0, center_idx - max(0, lower_steps))
    end_idx = min(len(available_bands) - 1, center_idx + max(0, upper_steps))

    return available_bands[start_idx:end_idx + 1]


# ------------------------------------------------------------
# Cohort feature helpers
# ------------------------------------------------------------

def pick_first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col

    return None


def summarize_band_samples(
    cohort_stats: pd.DataFrame,
    bands: list[str],
) -> dict[str, Any]:
    if cohort_stats.empty or not bands:
        return {
            "bands": bands,
            "row_count": 0,
            "user_count": 0.0,
            "record_count": 0.0,
            "best50_count": 0.0,
            "sufficient": False,
        }

    band_df = cohort_stats[cohort_stats["rating_band"].astype(str).isin(bands)].copy()

    if band_df.empty:
        return {
            "bands": bands,
            "row_count": 0,
            "user_count": 0.0,
            "record_count": 0.0,
            "best50_count": 0.0,
            "sufficient": False,
        }

    user_col = pick_first_existing_column(
        band_df,
        ["total_users_in_band", "band_user_count", "profile_count", "user_count", "unique_user_count", "n_users"],
    )
    record_col = pick_first_existing_column(
        band_df,
        ["record_count", "play_count", "count", "n_records"],
    )
    best50_col = pick_first_existing_column(
        band_df,
        ["best50_count", "best50_records", "best50_user_count"],
    )

    user_count = 0.0
    record_count = 0.0
    best50_count = 0.0

    if user_col is not None:
        user_count = float(pd.to_numeric(band_df[user_col], errors="coerce").fillna(0.0).max())

    if record_col is not None:
        record_count = float(pd.to_numeric(band_df[record_col], errors="coerce").fillna(0.0).sum())

    if best50_col is not None:
        best50_count = float(pd.to_numeric(band_df[best50_col], errors="coerce").fillna(0.0).sum())

    sufficient = (
        user_count >= MIN_COHORT_USER_COUNT
        or record_count >= MIN_COHORT_RECORD_COUNT
        or best50_count >= MIN_COHORT_BEST50_COUNT
    )

    return {
        "bands": bands,
        "row_count": int(len(band_df)),
        "user_count": round(user_count, 2),
        "record_count": round(record_count, 2),
        "best50_count": round(best50_count, 2),
        "sufficient": bool(sufficient),
    }


def expand_band_group_until_sufficient(
    cohort_stats: pd.DataFrame,
    center_band: str,
    available_bands: list[str],
    lower_steps: int,
    upper_steps: int,
) -> tuple[list[str], dict[str, Any]]:
    selected_bands = get_neighbor_bands_from_available(
        center_band=center_band,
        available_bands=available_bands,
        lower_steps=lower_steps,
        upper_steps=upper_steps,
    )

    sample_summary = summarize_band_samples(cohort_stats, selected_bands)

    debug = {
        "center_band": center_band,
        "selected_bands": selected_bands,
        "lower_steps": lower_steps,
        "upper_steps": upper_steps,
        "sample_summary": sample_summary,
    }

    return selected_bands, debug


def extract_band_features(
    cohort_stats: pd.DataFrame,
    rating_band: str | list[str],
    prefix: str,
) -> pd.DataFrame:
    empty_columns = [
        "chart_id",
        f"{prefix}_best50_rate",
        f"{prefix}_avg_achievement",
        f"{prefix}_sss_rate",
        f"{prefix}_sss_plus_rate",
        f"{prefix}_record_count",
        f"{prefix}_best50_count",
        f"{prefix}_user_count",
    ]

    if cohort_stats.empty:
        return pd.DataFrame(columns=empty_columns)

    if isinstance(rating_band, list):
        bands = [str(band) for band in rating_band if str(band).strip()]
    else:
        bands = [str(rating_band)] if str(rating_band).strip() else []

    if not bands:
        return pd.DataFrame(columns=empty_columns)

    band_df = cohort_stats[cohort_stats["rating_band"].astype(str).isin(bands)].copy()

    if band_df.empty:
        return pd.DataFrame(columns=empty_columns)

    feature_specs = {
        "best50_rate": [
            "best50_rate",
            "best50_ratio",
            "best50_share",
            "best50_appearance_rate",
            "best50_user_rate",
        ],
        "avg_achievement": [
            "avg_achievement",
            "mean_achievement",
            "achievement_mean",
            "achievement_avg",
        ],
        "sss_rate": [
            "sss_rate",
            "sss_ratio",
        ],
        "sss_plus_rate": [
            "sss_plus_rate",
            "sssp_rate",
            "sssplus_rate",
            "sss_plus_ratio",
            "sssp_ratio",
            "sssplus_ratio",
        ],
        "record_count": [
            "record_count",
            "play_count",
            "count",
            "n_records",
        ],
        "best50_count": [
            "best50_count",
            "best50_user_count",
            "best50_records",
        ],
        "user_count": [
            "user_count",
            "profile_count",
            "unique_user_count",
            "n_users",
            "band_user_count",
            "total_users_in_band",
        ],
    }

    normalized = pd.DataFrame()
    normalized["chart_id"] = band_df["chart_id"].astype(str)

    for dst_name, candidates in feature_specs.items():
        source_col = pick_first_existing_column(band_df, candidates)

        if source_col is None:
            normalized[dst_name] = 0.0
            continue

        if dst_name in {"best50_rate", "sss_rate", "sss_plus_rate"}:
            normalized[dst_name] = normalize_rate_series(band_df[source_col])
        else:
            normalized[dst_name] = pd.to_numeric(band_df[source_col], errors="coerce").fillna(0.0)

    # 여러 band를 합칠 때, count를 weight로 둔 weighted mean을 사용한다.
    normalized["_rate_weight"] = normalized["record_count"].clip(lower=0.0)
    normalized.loc[normalized["_rate_weight"] <= 0, "_rate_weight"] = 1.0

    def weighted_average(group: pd.DataFrame, col: str) -> float:
        weights = pd.to_numeric(group["_rate_weight"], errors="coerce").fillna(1.0)
        values = pd.to_numeric(group[col], errors="coerce").fillna(0.0)

        if weights.sum() <= 0:
            return float(values.mean()) if len(values) else 0.0

        return float((values * weights).sum() / weights.sum())

    rows = []

    for chart_id, group in normalized.groupby("chart_id"):
        rows.append({
            "chart_id": chart_id,
            f"{prefix}_best50_rate": weighted_average(group, "best50_rate"),
            f"{prefix}_avg_achievement": weighted_average(group, "avg_achievement"),
            f"{prefix}_sss_rate": weighted_average(group, "sss_rate"),
            f"{prefix}_sss_plus_rate": weighted_average(group, "sss_plus_rate"),
            f"{prefix}_record_count": float(group["record_count"].sum()),
            f"{prefix}_best50_count": float(group["best50_count"].sum()),
            f"{prefix}_user_count": float(group["user_count"].max()),
        })

    if not rows:
        return pd.DataFrame(columns=empty_columns)

    return pd.DataFrame(rows)


def merge_cohort_features(
    df: pd.DataFrame,
    cohort_stats: pd.DataFrame,
    current_band: str,
    target_band: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    df = df.copy()

    available_bands = get_available_bands(cohort_stats)

    current_bands_used, current_debug = expand_band_group_until_sufficient(
        cohort_stats=cohort_stats,
        center_band=current_band,
        available_bands=available_bands,
        lower_steps=CURRENT_BAND_LOWER_EXPANSION_STEPS,
        upper_steps=CURRENT_BAND_UPPER_EXPANSION_STEPS,
    )

    target_bands_used, target_debug = expand_band_group_until_sufficient(
        cohort_stats=cohort_stats,
        center_band=target_band,
        available_bands=available_bands,
        lower_steps=TARGET_BAND_LOWER_EXPANSION_STEPS,
        upper_steps=TARGET_BAND_UPPER_EXPANSION_STEPS,
    )

    current_features = extract_band_features(
        cohort_stats=cohort_stats,
        rating_band=current_bands_used,
        prefix="current",
    )

    target_features = extract_band_features(
        cohort_stats=cohort_stats,
        rating_band=target_bands_used,
        prefix="target",
    )

    if not current_features.empty:
        df = df.merge(current_features, on="chart_id", how="left")

    if not target_features.empty:
        df = df.merge(target_features, on="chart_id", how="left")

    default_columns = [
        "current_best50_rate",
        "current_avg_achievement",
        "current_sss_rate",
        "current_sss_plus_rate",
        "current_record_count",
        "current_best50_count",
        "current_user_count",
        "target_best50_rate",
        "target_avg_achievement",
        "target_sss_rate",
        "target_sss_plus_rate",
        "target_record_count",
        "target_best50_count",
        "target_user_count",
    ]

    for col in default_columns:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    band_debug = {
        "current_bands_used": current_bands_used,
        "target_bands_used": target_bands_used,
        "current_band_debug": current_debug,
        "target_band_debug": target_debug,
        "min_cohort_user_count": MIN_COHORT_USER_COUNT,
        "min_cohort_record_count": MIN_COHORT_RECORD_COUNT,
        "min_cohort_best50_count": MIN_COHORT_BEST50_COUNT,
    }

    return df, band_debug


# ------------------------------------------------------------
# Best50 floor features
# ------------------------------------------------------------

def normalize_best50_section(value: Any) -> str:
    text = safe_str(value, "").strip().lower()

    if text in {"new", "新曲", "new_best", "new_best15", "best15", "b15"}:
        return "new"

    if text in {"old", "others", "other", "old_best", "old_best35", "best35", "b35", "旧曲"}:
        return "old"

    return "unknown"


def infer_floor_section(row: pd.Series) -> str:
    section = normalize_best50_section(row.get("best50_section", ""))

    if section in {"new", "old"}:
        return section

    # 추천 후보곡은 best50_section이 비어 있으므로 version 기준으로 NEW/OLD를 판정한다.
    # PRiSM PLUS / CiRCLE 같은 현행·직전 버전은 NEW floor와 비교해야 한다.
    if is_new_version_chart(row):
        return "new"

    if normalize_is_new(row.get("is_new", False)):
        return "new"

    return "old"


def calculate_user_best50_floors(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty or "is_best50" not in df.columns:
        return {
            "available": False,
            "reason": "empty user records",
            "new_floor": None,
            "old_floor": None,
            "overall_floor": None,
            "new_count": 0,
            "old_count": 0,
            "total_best50_count": 0,
            "new_floor_required_count": NEW_FLOOR_REQUIRED_COUNT,
            "old_floor_required_count": OLD_FLOOR_REQUIRED_COUNT,
        }

    best50 = df[
        (df["is_best50"])
        & (pd.to_numeric(df["current_rating"], errors="coerce").fillna(0.0) > 0)
    ].copy()

    if best50.empty:
        return {
            "available": False,
            "reason": "no positive Best50 chart rating",
            "new_floor": None,
            "old_floor": None,
            "overall_floor": None,
            "new_count": 0,
            "old_count": 0,
            "total_best50_count": 0,
            "new_floor_required_count": NEW_FLOOR_REQUIRED_COUNT,
            "old_floor_required_count": OLD_FLOOR_REQUIRED_COUNT,
        }

    best50["floor_section"] = best50.apply(infer_floor_section, axis=1)

    new_best = best50[best50["floor_section"] == "new"].copy()
    old_best = best50[best50["floor_section"] == "old"].copy()

    new_count = int(len(new_best))
    old_count = int(len(old_best))
    total_count = int(len(best50))

    new_floor = None
    old_floor = None
    overall_floor = None

    if new_count > 0:
        new_floor = float(new_best["current_rating"].min())

    if old_count > 0:
        old_floor = float(old_best["current_rating"].min())

    if total_count > 0:
        overall_floor = float(best50["current_rating"].min())

    available = (
        total_count >= SIMILAR_USER_MIN_INPUT_BEST50
        and (new_floor is not None or old_floor is not None)
    )

    complete = (
        new_count >= NEW_FLOOR_REQUIRED_COUNT
        and old_count >= OLD_FLOOR_REQUIRED_COUNT
    )

    reason = "ok" if available else "not enough Best50 records"

    return {
        "available": available,
        "complete": complete,
        "reason": reason,
        "new_floor": new_floor,
        "old_floor": old_floor,
        "overall_floor": overall_floor,
        "new_count": new_count,
        "old_count": old_count,
        "total_best50_count": total_count,
        "new_floor_required_count": NEW_FLOOR_REQUIRED_COUNT,
        "old_floor_required_count": OLD_FLOOR_REQUIRED_COUNT,
        "total_best50_required_count": TOTAL_BEST50_REQUIRED_COUNT,
    }


def get_floor_for_section(user_floor_summary: dict[str, Any], floor_section: str) -> float | None:
    if floor_section == "new":
        value = user_floor_summary.get("new_floor")
    elif floor_section == "old":
        value = user_floor_summary.get("old_floor")
    else:
        value = user_floor_summary.get("overall_floor")

    if value is None:
        value = user_floor_summary.get("overall_floor")

    if value is None:
        return None

    floor = safe_float(value, 0.0)

    if floor <= 0:
        return None

    return floor


def add_floor_features(df: pd.DataFrame, user_floor_summary: dict[str, Any]) -> pd.DataFrame:
    df = df.copy()

    df["floor_section"] = df.apply(infer_floor_section, axis=1)

    df["applicable_floor"] = df["floor_section"].apply(
        lambda section: get_floor_for_section(user_floor_summary, section)
    )

    df["applicable_floor"] = pd.to_numeric(df["applicable_floor"], errors="coerce")

    df["expected_rating_100_5"] = pd.to_numeric(
        df["expected_rating_100_5"],
        errors="coerce",
    ).fillna(0.0)

    df["current_rating"] = pd.to_numeric(df["current_rating"], errors="coerce").fillna(0.0)

    df["floor_gain"] = 0.0
    df["floor_gain_available"] = df["applicable_floor"].notna()

    not_best50_mask = ~df["is_best50"].apply(normalize_bool)
    best50_mask = df["is_best50"].apply(normalize_bool)

    df.loc[not_best50_mask & df["floor_gain_available"], "floor_gain"] = (
        df.loc[not_best50_mask & df["floor_gain_available"], "expected_rating_100_5"]
        - df.loc[not_best50_mask & df["floor_gain_available"], "applicable_floor"]
    ).clip(lower=0.0)

    # 이미 Best50인 곡은 floor 대체가 아니라 현재 점수에서 100.5%로 올렸을 때의 직접 증가분을 사용한다.
    df.loc[best50_mask, "floor_gain"] = (
        df.loc[best50_mask, "expected_rating_100_5"]
        - df.loc[best50_mask, "current_rating"]
    ).clip(lower=0.0)

    df["floor_gain_score"] = (df["floor_gain"] * 10.0).clip(lower=0.0, upper=100.0)

    df["floor_gain_label"] = df.apply(
        lambda row: make_floor_gain_label(row),
        axis=1,
    )

    return df


def make_floor_gain_label(row: pd.Series) -> str:
    floor_section = safe_str(row.get("floor_section", ""))
    expected_rating = safe_float(row.get("expected_rating_100_5", 0.0))
    current_rating = safe_float(row.get("current_rating", 0.0))
    applicable_floor = row.get("applicable_floor")
    floor_gain = safe_float(row.get("floor_gain", 0.0))
    is_best50 = bool(row.get("is_best50", False))

    section_label = "NEW" if floor_section == "new" else "OLD"

    if is_best50:
        return (
            f"Best50 내 기존 곡: 현재 {current_rating:.0f} → 100.5% 기준 {expected_rating:.0f}, "
            f"직접 상승 가능 +{floor_gain:.0f}"
        )

    if applicable_floor is None or pd.isna(applicable_floor):
        return (
            f"{section_label} floor 정보 없음. 100.5% 기준 예상 곡별 레이팅 {expected_rating:.0f}"
        )

    return (
        f"{section_label} floor {float(applicable_floor):.0f} 대비 "
        f"100.5% 기준 {expected_rating:.0f}, 대체 이득 +{floor_gain:.0f}"
    )


# ------------------------------------------------------------
# Filtering and scoring
# ------------------------------------------------------------

def filter_by_main_level(df: pd.DataFrame, main_level: str, goal: str) -> pd.DataFrame:
    if main_level not in LEVEL_BOUNDS:
        return df.copy()

    low, high = LEVEL_BOUNDS[main_level]

    filtered = df[
        (df["internal_level"] >= low)
        & (df["internal_level"] <= high)
    ].copy()

    return filtered


def filter_by_chart_type(df: pd.DataFrame, chart_type: str) -> pd.DataFrame:
    if chart_type == "any":
        return df.copy()

    return df[df["chart_type"].astype(str).str.lower() == chart_type.lower()].copy()


def level_fit_score(row: pd.Series, main_level: str) -> float:
    if main_level not in LEVEL_BOUNDS:
        return 70.0

    low, high = LEVEL_BOUNDS[main_level]
    internal_level = safe_float(row.get("internal_level", 0.0))

    if not (low <= internal_level <= high):
        return 0.0

    if main_level == "15":
        return 100.0

    center = (low + high) / 2.0
    half_span = max((high - low) / 2.0, 0.1)
    distance = abs(internal_level - center)

    score = 100.0 - min(30.0, (distance / half_span) * 30.0)

    return round(max(0.0, min(score, 100.0)), 2)


def get_default_weakness_reference(main_level: str) -> float:
    default_reference = {
        "13": 100.0,
        "13+": 99.5,
        "14": 99.0,
        "14+": 98.5,
        "15": 97.5,
    }

    return default_reference.get(main_level, 99.0)


def preference_score(row: pd.Series, chart_type: str, bpm_preference: str = "any") -> float:
    score = 50.0

    if chart_type == "any":
        score += 20.0
    elif safe_str(row.get("chart_type", "")).lower() == chart_type.lower():
        score += 30.0

    return round(max(0.0, min(score, 100.0)), 2)


def rating_up_score(row: pd.Series, req: Any) -> float:
    if bool(row.get("rating_capped", False)):
        return 0.0

    rating_gain = safe_float(row.get("rating_gain", 0.0))
    floor_gain = safe_float(row.get("floor_gain", 0.0))
    floor_gain_available = bool(row.get("floor_gain_available", False))

    if rating_gain <= 0 and floor_gain <= 0:
        return 0.0

    target_best50_score = safe_float(row.get("target_best50_rate", 0.0))
    current_best50_score = safe_float(row.get("current_best50_rate", 0.0))
    cohort_score = 0.65 * target_best50_score + 0.35 * current_best50_score

    rating_gain_score = min(100.0, rating_gain * 6.0)
    floor_gain_score = min(100.0, floor_gain * 10.0)

    # floor 정보가 없으면 기존 rating_gain 기반 scoring으로 크게 손해 보지 않도록 fallback한다.
    if not floor_gain_available:
        floor_gain_score = rating_gain_score

    level_score = level_fit_score(row, req.main_level)
    pref_score = preference_score(row, req.chart_type, getattr(req, "bpm_preference", "any"))

    played = bool(row.get("played", False))
    is_best50 = bool(row.get("is_best50", False))

    if is_best50:
        candidate_bonus = 35.0
    elif played:
        candidate_bonus = 80.0
    else:
        candidate_bonus = 65.0

    score = (
        0.30 * floor_gain_score
        + 0.20 * rating_gain_score
        + 0.25 * cohort_score
        + 0.10 * level_score
        + 0.10 * candidate_bonus
        + 0.05 * pref_score
    )

    return round(max(0.0, min(score, 100.0)), 2)


def skill_up_score(row: pd.Series, req: Any) -> float:
    target_best50_score = safe_float(row.get("target_best50_rate", 0.0))
    target_sss_plus_score = safe_float(row.get("target_sss_plus_rate", 0.0))
    target_record_count = safe_float(row.get("target_record_count", 0.0))
    target_best50_count = safe_float(row.get("target_best50_count", 0.0))

    current_best50_score = safe_float(row.get("current_best50_rate", 0.0))
    current_sss_plus_score = safe_float(row.get("current_sss_plus_rate", 0.0))
    current_record_count = safe_float(row.get("current_record_count", 0.0))
    current_best50_count = safe_float(row.get("current_best50_count", 0.0))

    level_score = level_fit_score(row, req.main_level)

    if level_score <= 0:
        return 0.0

    played = bool(row.get("played", False))
    is_best50 = bool(row.get("is_best50", False))

    if is_best50:
        candidate_bonus = 25.0
    elif played:
        candidate_bonus = 70.0
    else:
        candidate_bonus = 85.0

    target_evidence_exists = (
        target_best50_score > 0
        or target_sss_plus_score > 0
        or target_record_count > 0
        or target_best50_count > 0
    )

    current_evidence_exists = (
        current_best50_score > 0
        or current_sss_plus_score > 0
        or current_record_count > 0
        or current_best50_count > 0
    )

    if target_evidence_exists:
        best50_score = target_best50_score
        sss_plus_score = target_sss_plus_score
        record_count = target_record_count
    elif current_evidence_exists:
        best50_score = current_best50_score * 0.85
        sss_plus_score = current_sss_plus_score * 0.85
        record_count = current_record_count
    else:
        best50_score = 0.0
        sss_plus_score = 0.0
        record_count = 0.0

    record_score = min(100.0, math.log1p(record_count) * 18.0)

    internal_level = safe_float(row.get("internal_level", 0.0))

    if req.main_level in LEVEL_BOUNDS:
        low, high = LEVEL_BOUNDS[req.main_level]

        if high > low:
            position = (internal_level - low) / (high - low)
            position = max(0.0, min(position, 1.0))
            challenge_score = 60.0 + position * 40.0
        else:
            challenge_score = 80.0
    else:
        challenge_score = 75.0

    floor_gain_score = min(100.0, safe_float(row.get("floor_gain", 0.0)) * 8.0)

    if target_evidence_exists or current_evidence_exists:
        score = (
            0.32 * best50_score
            + 0.18 * sss_plus_score
            + 0.14 * record_score
            + 0.14 * challenge_score
            + 0.14 * candidate_bonus
            + 0.08 * floor_gain_score
        )
    else:
        score = (
            0.40 * challenge_score
            + 0.28 * level_score
            + 0.24 * candidate_bonus
            + 0.08 * floor_gain_score
        )
        score = min(score, 68.0)

    return round(max(0.0, min(score, 100.0)), 2)


def weakness_score(row: pd.Series, req: Any) -> float:
    if not bool(row.get("played", False)):
        return 0.0

    achievement = safe_float(row.get("achievement", 0.0))

    if achievement <= 0:
        return 0.0

    if achievement >= REVERSE_BORDER_MAX:
        return 0.0

    current_avg = safe_float(row.get("current_avg_achievement", 0.0))
    target_avg = safe_float(row.get("target_avg_achievement", 0.0))

    cohort_reference = 0.0

    if current_avg > 0:
        cohort_reference = current_avg

    if target_avg > cohort_reference:
        cohort_reference = target_avg

    default_reference = get_default_weakness_reference(req.main_level)

    reference_achievement = max(cohort_reference, default_reference)
    gap = reference_achievement - achievement

    if gap <= 0:
        return 0.0

    gap_score = min(100.0, gap * 16.0)
    rating_gain_score = min(100.0, safe_float(row.get("rating_gain", 0.0)) * 5.0)
    level_score = level_fit_score(row, req.main_level)

    current_best50_score = safe_float(row.get("current_best50_rate", 0.0))
    target_best50_score = safe_float(row.get("target_best50_rate", 0.0))
    cohort_interest_score = max(current_best50_score, target_best50_score)

    is_best50 = bool(row.get("is_best50", False))
    candidate_bonus = 70.0 if is_best50 else 85.0

    score = (
        0.45 * gap_score
        + 0.20 * rating_gain_score
        + 0.15 * level_score
        + 0.10 * cohort_interest_score
        + 0.10 * candidate_bonus
    )

    return round(max(0.0, min(score, 100.0)), 2)


def reverse_border_score(row: pd.Series, req: Any) -> float:
    if not bool(row.get("reverse_border", False)):
        return 0.0

    gap = safe_float(row.get("reverse_border_gap", 0.0))
    proximity_score = max(0.0, 100.0 - min(100.0, gap * 5000.0))
    level_score = level_fit_score(row, req.main_level)
    is_best50 = bool(row.get("is_best50", False))
    best50_bonus = 100.0 if is_best50 else 60.0

    score = (
        0.55 * proximity_score
        + 0.25 * level_score
        + 0.20 * best50_bonus
    )

    return round(max(0.0, min(score, 100.0)), 2)


def similar_user_score(row: pd.Series, req: Any) -> float:
    collaborative = safe_float(row.get("collaborative_score", 0.0))

    if collaborative <= 0:
        return 0.0

    target_best50_score = safe_float(row.get("target_best50_rate", 0.0))
    level_score = level_fit_score(row, req.main_level)

    played = bool(row.get("played", False))
    is_best50 = bool(row.get("is_best50", False))

    if is_best50:
        improvement_score = min(40.0, safe_float(row.get("rating_gain", 0.0)) * 4.0)
        candidate_bonus = 5.0
    elif played:
        # 이미 친 곡은 약점 보완/역보더 모드가 더 적합하므로 similar_user에서는 보조 후보로 낮춘다.
        improvement_score = min(100.0, safe_float(row.get("rating_gain", 0.0)) * 8.0)
        candidate_bonus = 45.0
    else:
        # similar_user의 핵심은 "비슷한 유저는 성과를 냈지만 입력 유저는 아직 안 친 곡"이다.
        improvement_score = 65.0
        candidate_bonus = 90.0

    score = (
        0.68 * collaborative
        + 0.12 * target_best50_score
        + 0.08 * level_score
        + 0.04 * improvement_score
        + 0.08 * candidate_bonus
    )

    return round(max(0.0, min(score, 100.0)), 2)


def similar_user_evidence_exists(row: pd.Series) -> bool:
    """
    similar_user 모드에서 최소한의 유사 유저 근거가 있는 후보인지 판정한다.

    여기서 타 유저 데이터는 전체 플레이 기록이 아니라 raw_user_best50.csv 기반
    유사 유저 Best50 및 cohort 통계 중심으로 사용한다.
    """
    collaborative = safe_float(row.get("collaborative_score", 0.0))
    chart_count = safe_int(row.get("similar_user_chart_count", 0), 0)
    weighted_rate = safe_float(row.get("similar_user_weighted_rate", 0.0))

    return collaborative > 0 or chart_count > 0 or weighted_rate > 0


def build_rating_up_candidate_debug(
    df_before_floor_filter: pd.DataFrame,
    df_after_floor_filter: pd.DataFrame,
    req: Any,
    effective_rating: int | None,
    user_floor_summary: dict[str, Any],
    requested_top_n: int,
    strict_floor_gain_filter_used: bool,
) -> dict[str, Any]:
    """
    rating_up 후보 부족/상위권 대응 정보를 debug에 담는다.

    상위권 유저는 이미 Best50 floor가 높기 때문에 floor_gain > 0 후보가 적어지는 것이 정상이다.
    이 경우 후보를 억지로 채우지 않고, 부족 상태를 명시한다.
    """
    if df_before_floor_filter is None:
        df_before_floor_filter = pd.DataFrame()

    if df_after_floor_filter is None:
        df_after_floor_filter = pd.DataFrame()

    before_count = int(len(df_before_floor_filter))
    after_count = int(len(df_after_floor_filter))

    if "floor_gain" in df_before_floor_filter.columns:
        floor_gain_series = pd.to_numeric(
            df_before_floor_filter["floor_gain"],
            errors="coerce",
        ).fillna(0.0)
        positive_floor_gain_count = int((floor_gain_series > RATING_UP_MIN_POSITIVE_FLOOR_GAIN).sum())
        max_floor_gain = float(floor_gain_series.max()) if len(floor_gain_series) else 0.0
    else:
        positive_floor_gain_count = 0
        max_floor_gain = 0.0

    if "expected_rating_100_5" in df_before_floor_filter.columns and not df_before_floor_filter.empty:
        highest_expected_rating_100_5 = float(
            pd.to_numeric(
                df_before_floor_filter["expected_rating_100_5"],
                errors="coerce",
            ).fillna(0.0).max()
        )
    else:
        highest_expected_rating_100_5 = 0.0

    rating_value = safe_int(effective_rating, 0)
    high_rating_user = rating_value >= RATING_UP_HIGH_RATING_THRESHOLD
    selected_main_level = safe_str(getattr(req, "main_level", ""), "")
    candidate_shortage = after_count < requested_top_n
    limited_level_15_pool = selected_main_level == "15" and after_count > 0

    if candidate_shortage:
        if limited_level_15_pool:
            # 15레벨은 보스곡 구간으로 후보 수 자체가 매우 적다.
            # 일반 UI에 후보 부족 문구를 붙이면 오히려 부자연스러우므로 message는 비운다.
            shortage_message = ""
            shortage_reason = "limited_level_15_pool"
        elif high_rating_user:
            shortage_message = (
                "상위권 유저는 Best50 floor가 높아 현재 조건에서 실제 레이팅 상승 후보가 적습니다. "
                "더 높은 레벨 또는 더 높은 보면상수 조건을 확인하는 것이 적절합니다."
            )
            shortage_reason = "high_rating_floor_too_high"
        else:
            shortage_message = (
                "현재 조건에서 Best50 floor를 넘길 수 있는 레이팅 상승 후보가 요청 개수보다 적습니다. "
                "더 높은 레벨 또는 다른 타입 조건을 함께 확인하는 것이 좋습니다."
            )
            shortage_reason = "fewer_than_requested"
    else:
        shortage_message = ""
        shortage_reason = "none"

    return {
        "enabled": True,
        "selected_main_level": selected_main_level,
        "requested_top_n": int(requested_top_n),
        "effective_rating": rating_value,
        "high_rating_threshold": RATING_UP_HIGH_RATING_THRESHOLD,
        "high_rating_user": bool(high_rating_user),
        "user_floor_available": bool(user_floor_summary.get("available", False)),
        "user_floor_complete": bool(user_floor_summary.get("complete", False)),
        "new_floor": user_floor_summary.get("new_floor"),
        "old_floor": user_floor_summary.get("old_floor"),
        "overall_floor": user_floor_summary.get("overall_floor"),
        "candidate_count_before_floor_filter": before_count,
        "positive_floor_gain_candidate_count": positive_floor_gain_count,
        "candidate_count_after_floor_filter": after_count,
        "strict_floor_gain_filter_used": bool(strict_floor_gain_filter_used),
        "candidate_shortage": bool(candidate_shortage),
        "candidate_shortage_reason": shortage_reason,
        "limited_level_15_pool": bool(limited_level_15_pool),
        "candidate_shortage_message": shortage_message,
        "max_floor_gain": round(max_floor_gain, 4),
        "highest_expected_rating_100_5": round(highest_expected_rating_100_5, 4),
    }


# ------------------------------------------------------------
# Collaborative filtering
# ------------------------------------------------------------

def get_input_best50_chart_ids(df: pd.DataFrame) -> set[str]:
    if "is_best50" not in df.columns or "chart_id" not in df.columns:
        return set()

    best50 = df[
        (df["is_best50"])
        & (df["chart_id"].notna())
    ].copy()

    return set(best50["chart_id"].astype(str).tolist())


def initialize_collaborative_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    default_values = {
        "collaborative_score": 0.0,
        "collaborative_weight_sum": 0.0,
        "similar_user_weighted_rate": 0.0,
        "similar_user_chart_count": 0,
        "similar_user_count": 0,
        "similar_user_avg_similarity": 0.0,
    }

    for col, default_value in default_values.items():
        if col not in df.columns:
            df[col] = default_value

    return df


def add_collaborative_features(
    df: pd.DataFrame,
    input_best50_chart_ids: set[str],
    top_k: int = SIMILAR_USER_TOP_K,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    df = initialize_collaborative_columns(df)

    debug = {
        "available": False,
        "reason": "",
        "input_best50_count": len(input_best50_chart_ids),
        "raw_user_count": 0,
        "similar_user_count": 0,
        "top_k": top_k,
        "avg_similarity": 0.0,
        "max_similarity": 0.0,
        "min_similarity": 0.0,
        "top_similarities": [],
    }

    if len(input_best50_chart_ids) < SIMILAR_USER_MIN_INPUT_BEST50:
        debug["reason"] = f"input best50 count is less than {SIMILAR_USER_MIN_INPUT_BEST50}"
        return df, debug

    raw = load_raw_user_best50()

    if raw.empty:
        debug["reason"] = "raw_user_best50.csv is empty or invalid"
        return df, debug

    valid_chart_ids = set(df["chart_id"].astype(str).tolist())
    raw = raw[raw["chart_id"].astype(str).isin(valid_chart_ids)].copy()

    if raw.empty:
        debug["reason"] = "no raw best50 chart_id matched current candidate pool"
        return df, debug

    user_groups = raw.groupby("profile_id")["chart_id"].apply(
        lambda values: set(values.astype(str).tolist())
    )

    debug["raw_user_count"] = int(len(user_groups))

    input_len = len(input_best50_chart_ids)
    similarities = []

    for profile_id, user_chart_ids in user_groups.items():
        if not user_chart_ids:
            continue

        intersection_count = len(input_best50_chart_ids & user_chart_ids)

        if intersection_count == 0:
            continue

        similarity = intersection_count / math.sqrt(input_len * len(user_chart_ids))

        if similarity < SIMILAR_USER_MIN_SIMILARITY:
            continue

        if similarity >= 0.999 and user_chart_ids == input_best50_chart_ids:
            continue

        similarities.append({
            "profile_id": profile_id,
            "similarity": float(similarity),
            "chart_ids": user_chart_ids,
            "intersection_count": intersection_count,
            "best50_count": len(user_chart_ids),
        })

    if not similarities:
        debug["reason"] = "no similar users found"
        return df, debug

    similarities = sorted(
        similarities,
        key=lambda item: item["similarity"],
        reverse=True,
    )[:top_k]

    total_similarity = sum(item["similarity"] for item in similarities)

    if total_similarity <= 0:
        debug["reason"] = "total similarity is zero"
        return df, debug

    chart_weight_sum = {}
    chart_user_count = {}

    for item in similarities:
        similarity = item["similarity"]

        for chart_id in item["chart_ids"]:
            chart_weight_sum[chart_id] = chart_weight_sum.get(chart_id, 0.0) + similarity
            chart_user_count[chart_id] = chart_user_count.get(chart_id, 0) + 1

    df["_chart_id_str"] = df["chart_id"].astype(str)

    df["collaborative_weight_sum"] = df["_chart_id_str"].map(chart_weight_sum).fillna(0.0)
    df["similar_user_chart_count"] = df["_chart_id_str"].map(chart_user_count).fillna(0).astype(int)
    df["similar_user_weighted_rate"] = df["collaborative_weight_sum"] / total_similarity * 100.0
    df["collaborative_score"] = df["similar_user_weighted_rate"].clip(lower=0.0, upper=100.0)

    similarity_values = [item["similarity"] for item in similarities]
    avg_similarity = sum(similarity_values) / len(similarity_values)

    df["similar_user_count"] = len(similarities)
    df["similar_user_avg_similarity"] = avg_similarity

    df = df.drop(columns=["_chart_id_str"])

    debug.update({
        "available": True,
        "reason": "ok",
        "similar_user_count": int(len(similarities)),
        "avg_similarity": round(float(avg_similarity), 4),
        "max_similarity": round(float(max(similarity_values)), 4),
        "min_similarity": round(float(min(similarity_values)), 4),
        "top_similarities": [
            {
                "profile_id": item["profile_id"],
                "similarity": round(float(item["similarity"]), 4),
                "intersection_count": int(item["intersection_count"]),
                "best50_count": int(item["best50_count"]),
            }
            for item in similarities[:10]
        ],
    })

    return df, debug


# ------------------------------------------------------------
# Reason and output helpers
# ------------------------------------------------------------

def make_reason(row: pd.Series, goal: str) -> tuple[str, str]:
    floor_gain = safe_float(row.get("floor_gain", 0.0))
    floor_label = safe_str(row.get("floor_gain_label", ""))

    if goal == "reverse_border":
        achievement = safe_float(row.get("achievement", 0.0))
        gap = safe_float(row.get("reverse_border_gap", 0.0))

        reason = (
            f"현재 달성률이 {achievement:.4f}%로, "
            f"100.5%까지 {gap:.4f}% 부족한 역보더 후보입니다. "
            f"기준 범위는 100.4000% 이상 100.5000% 미만입니다."
        )
        target = "100.5% 달성으로 레이팅 캡 도달"

        return reason, target

    if goal == "similar_user":
        collaborative_score = safe_float(row.get("collaborative_score", 0.0))
        weighted_rate = safe_float(row.get("similar_user_weighted_rate", 0.0))
        similar_user_count = int(safe_float(row.get("similar_user_count", 0)))
        chart_count = int(safe_float(row.get("similar_user_chart_count", 0)))
        avg_similarity = safe_float(row.get("similar_user_avg_similarity", 0.0))

        reason = (
            f"입력 유저의 Best50 구성과 유사한 유저 {similar_user_count}명을 기준으로 계산한 추천입니다. "
            f"이 곡은 유사 유저 중 {chart_count}명의 Best50에 등장했으며, "
            f"유사도 가중 등장률은 {weighted_rate:.1f}%입니다. "
            f"평균 유사도는 {avg_similarity:.3f}, "
            f"협업 필터링 점수는 {collaborative_score:.1f}입니다."
        )
        target = "유사 유저 Best50 기반 추천"

        return reason, target

    if goal == "rating_up":
        rating_gain = safe_float(row.get("rating_gain", 0.0))
        target_rate = safe_float(row.get("target_best50_rate", 0.0))
        current_rating = safe_float(row.get("current_rating", 0.0))
        expected_rating = safe_float(row.get("expected_rating_100_5", 0.0))

        if bool(row.get("played", False)):
            reason = (
                f"현재 곡별 레이팅은 {current_rating:.0f}이고, "
                f"100.5% 기준 예상 곡별 레이팅은 {expected_rating:.0f}입니다. "
                f"현재 기록 대비 상승 여지는 약 {rating_gain:.0f}, "
                f"Best50 floor 기준 대체/직접 이득은 약 {floor_gain:.0f}입니다. "
                f"{floor_label} "
                f"상위 레이팅 구간 Best50 등장률은 {target_rate:.1f}%입니다."
            )
        else:
            reason = (
                f"아직 입력 유저 기록에 없는 후보입니다. "
                f"100.5% 기준 예상 곡별 레이팅은 {expected_rating:.0f}이고, "
                f"Best50 floor 기준 대체 이득은 약 {floor_gain:.0f}입니다. "
                f"{floor_label} "
                f"상위 레이팅 구간 Best50 등장률은 {target_rate:.1f}%입니다."
            )

        target = "Best50 floor를 넘기는 100.5% 근처 달성"

        return reason, target

    if goal == "skill_up":
        target_rate = safe_float(row.get("target_best50_rate", 0.0))
        current_rate = safe_float(row.get("current_best50_rate", 0.0))
        sss_plus_rate = safe_float(row.get("target_sss_plus_rate", 0.0))

        reason = (
            f"선택한 레벨대에서 실력 향상 후보로 계산되었습니다. "
            f"상위 구간 Best50 등장률은 {target_rate:.1f}%, "
            f"현재 구간 Best50 등장률은 {current_rate:.1f}%, "
            f"상위 구간 SSS+ 비율은 {sss_plus_rate:.1f}%입니다. "
            f"Best50 floor 기준 이득은 약 {floor_gain:.0f}으로 보조 반영했습니다."
        )
        target = "실력 향상"

        return reason, target

    if goal == "weakness":
        achievement = safe_float(row.get("achievement", 0.0))
        current_avg = safe_float(row.get("current_avg_achievement", 0.0))
        target_avg = safe_float(row.get("target_avg_achievement", 0.0))

        cohort_reference = 0.0

        if current_avg > 0:
            cohort_reference = current_avg

        if target_avg > cohort_reference:
            cohort_reference = target_avg

        default_reference = get_default_weakness_reference(safe_str(row.get("level", "")))
        reference_achievement = max(cohort_reference, default_reference)
        gap = max(0.0, reference_achievement - achievement)

        reason = (
            f"현재 달성률은 {achievement:.4f}%이며, "
            f"보완 기준 달성률은 약 {reference_achievement:.4f}%입니다. "
            f"차이는 약 {gap:.4f}%입니다."
        )
        target = "약점 보완"

        return reason, target

    reason = "선택한 조건과 레이팅 구간 통계를 기준으로 추천된 후보입니다."
    target = "추천 조건에 따른 후보"

    return reason, target


def sort_candidates(
    df: pd.DataFrame,
    sort_columns: list[str],
    sort_ascending: list[bool],
) -> pd.DataFrame:
    valid_columns = []
    valid_ascending = []

    for col, asc in zip(sort_columns, sort_ascending):
        if col in df.columns:
            valid_columns.append(col)
            valid_ascending.append(asc)

    if not valid_columns:
        return df.copy()

    return df.sort_values(valid_columns, ascending=valid_ascending).reset_index(drop=True)


def select_display_candidates(
    df: pd.DataFrame,
    goal: str,
    top_n: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    최종 추천 표시 후보를 선택한다.

    rating_up 모드에서는 OLD floor가 낮아 구곡이 상단을 독점할 수 있다.
    PRiSM PLUS / CiRCLE 같은 NEW 후보도 실제 레이팅 상승 가능성이 있으면
    일정 비율을 표시하여 NEW/OLD floor 분리 설계가 UI에서 확인되도록 한다.
    """
    if df is None or df.empty:
        return pd.DataFrame(), {
            "display_candidate_count": 0,
            "display_new_count": 0,
            "display_old_count": 0,
            "new_quota_requested": 0,
            "new_quota_applied": 0,
        }

    top_n = max(1, int(top_n))

    if goal != "rating_up" or "floor_section" not in df.columns:
        display_df = df.head(top_n).copy()
        return display_df, {
            "display_candidate_count": int(len(display_df)),
            "display_new_count": int((display_df.get("floor_section", pd.Series(dtype=str)).astype(str) == "new").sum()) if "floor_section" in display_df.columns else 0,
            "display_old_count": int((display_df.get("floor_section", pd.Series(dtype=str)).astype(str) == "old").sum()) if "floor_section" in display_df.columns else 0,
            "new_quota_requested": 0,
            "new_quota_applied": 0,
        }

    if top_n < 6:
        display_df = df.head(top_n).copy()
        return display_df, {
            "display_candidate_count": int(len(display_df)),
            "display_new_count": int((display_df["floor_section"].astype(str) == "new").sum()),
            "display_old_count": int((display_df["floor_section"].astype(str) == "old").sum()),
            "new_quota_requested": 0,
            "new_quota_applied": 0,
        }

    floor_gain_series = pd.to_numeric(df.get("floor_gain", 0.0), errors="coerce").fillna(0.0)
    new_candidates = df[
        (df["floor_section"].astype(str) == "new")
        & (floor_gain_series > RATING_UP_MIN_POSITIVE_FLOOR_GAIN)
    ].copy()

    new_quota_requested = min(top_n, max(2, int(round(top_n * 0.30))))
    selected_parts = []

    if not new_candidates.empty:
        selected_parts.append(new_candidates.head(new_quota_requested))

    if selected_parts:
        selected_df = pd.concat(selected_parts, ignore_index=False)
    else:
        selected_df = pd.DataFrame(columns=df.columns)

    selected_ids = set(selected_df["chart_id"].astype(str).tolist()) if not selected_df.empty and "chart_id" in selected_df.columns else set()
    remaining_slots = top_n - int(len(selected_df))

    if remaining_slots > 0:
        rest = df[~df["chart_id"].astype(str).isin(selected_ids)].head(remaining_slots).copy()
        selected_df = pd.concat([selected_df, rest], ignore_index=False)

    selected_df = selected_df.drop_duplicates(subset=["chart_id"], keep="first").copy()

    # NEW quota는 "표시 후보군에 포함"시키기 위한 장치이고,
    # 최종 노출 순위는 다시 추천 점수 / floor_gain 기준으로 정렬한다.
    # 이렇게 해야 PRiSM PLUS / CiRCLE 후보가 완전히 묻히지는 않으면서도,
    # NEW 후보가 무조건 상단을 독점하는 부자연스러운 UI를 피할 수 있다.
    selected_df = sort_candidates(
        df=selected_df,
        sort_columns=[
            "recommend_score",
            "floor_gain",
            "target_best50_rate",
            "rating_gain",
            "internal_level",
        ],
        sort_ascending=[False, False, False, False, False],
    ).head(top_n).copy()

    display_debug = {
        "display_candidate_count": int(len(selected_df)),
        "display_new_count": int((selected_df["floor_section"].astype(str) == "new").sum()) if "floor_section" in selected_df.columns else 0,
        "display_old_count": int((selected_df["floor_section"].astype(str) == "old").sum()) if "floor_section" in selected_df.columns else 0,
        "new_quota_requested": int(new_quota_requested),
        "new_quota_applied": int(min(len(new_candidates), new_quota_requested)),
        "new_candidate_count_before_display": int(len(new_candidates)),
        "display_final_resort_applied": True,
        "display_final_sort_keys": [
            "recommend_score",
            "floor_gain",
            "target_best50_rate",
            "rating_gain",
            "internal_level",
        ],
    }

    return selected_df.reset_index(drop=True), display_debug


# ------------------------------------------------------------
# Main recommendation function
# ------------------------------------------------------------

def recommend(
    req: Any,
    user_records_df: pd.DataFrame | None = None,
    user_rating: int | None = None,
) -> dict[str, Any]:
    df = load_base_data(user_records_df)

    user_floor_summary = calculate_user_best50_floors(df)
    df = add_floor_features(df, user_floor_summary)

    input_best50_chart_ids = get_input_best50_chart_ids(df)

    similar_user_debug = {
        "available": False,
        "reason": "similar_user mode was not selected",
        "input_best50_count": len(input_best50_chart_ids),
    }

    rating_up_debug = {
        "enabled": False,
        "reason": "rating_up mode was not selected",
    }

    top_n = safe_int(getattr(req, "top_n", 10), 10)
    top_n = max(1, min(top_n, 30))

    estimated_rating = estimate_rating_from_records(df)
    effective_rating = user_rating if user_rating is not None else estimated_rating

    cohort_stats = load_cohort_stats()
    _ = load_level_stats()

    available_bands = get_available_bands(cohort_stats)

    current_band = rating_to_band(effective_rating)
    target_band = get_target_band_from_available(current_band, available_bands)

    df, band_debug = merge_cohort_features(
        df=df,
        cohort_stats=cohort_stats,
        current_band=current_band,
        target_band=target_band,
    )

    df = filter_by_main_level(df=df, main_level=req.main_level, goal=req.goal)
    df = filter_by_chart_type(df=df, chart_type=req.chart_type)

    candidate_pool_count_before_goal = int(len(df))

    summary = ""
    sort_columns = ["recommend_score", "target_best50_rate", "floor_gain", "rating_gain", "internal_level"]
    sort_ascending = [False, False, False, False, False]

    if req.goal == "reverse_border":
        df["recommend_score"] = df.apply(lambda row: reverse_border_score(row, req), axis=1)
        df = df[(df["recommend_score"] > 0) & (df["reverse_border"])].copy()

        summary = (
            "역보더 탐색 모드입니다. "
            "현재 달성률이 100.4000% 이상 100.5000% 미만인 곡을 "
            "100.5%에 가까운 순서와 Best50 여부를 함께 고려해 추천합니다."
        )

        sort_columns = ["reverse_border_gap", "internal_level", "is_best50", "current_rating"]
        sort_ascending = [True, False, False, False]

    elif req.goal == "similar_user":
        df, similar_user_debug = add_collaborative_features(
            df=df,
            input_best50_chart_ids=input_best50_chart_ids,
            top_k=SIMILAR_USER_TOP_K,
        )

        df["similar_user_evidence"] = df.apply(similar_user_evidence_exists, axis=1)
        df["recommend_score"] = df.apply(lambda row: similar_user_score(row, req), axis=1)

        similar_user_candidate_count_before_filter = int(len(df))
        df = df[
            (df["recommend_score"] > 0)
            & (~df["is_best50"])
            & (df["similar_user_evidence"])
        ].copy()

        similar_user_debug.update({
            "candidate_count_before_filter": similar_user_candidate_count_before_filter,
            "candidate_count_after_filter": int(len(df)),
            "unplayed_candidate_count_after_filter": int((~df["played"]).sum()) if "played" in df.columns else 0,
            "played_candidate_count_after_filter": int(df["played"].sum()) if "played" in df.columns else 0,
            "unplayed_sort_first": SIMILAR_USER_UNPLAYED_SORT_FIRST,
        })

        summary = (
            "나와 비슷한 유저 추천 모드입니다. "
            f"입력 유저의 Best50 {len(input_best50_chart_ids)}개를 기준으로 "
            "DB 유저들과 cosine similarity를 계산하고, "
            f"유사 유저 Top {SIMILAR_USER_TOP_K}명의 Best50 등장 패턴을 반영했습니다. "
            "입력 유저의 전체 플레이 기록을 기준으로 이미 플레이한 곡과 미플레이 곡을 구분합니다."
        )

        if SIMILAR_USER_UNPLAYED_SORT_FIRST:
            sort_columns = [
                "played",
                "recommend_score",
                "collaborative_score",
                "similar_user_chart_count",
                "target_best50_rate",
            ]
            sort_ascending = [True, False, False, False, False]
        else:
            sort_columns = [
                "recommend_score",
                "collaborative_score",
                "similar_user_chart_count",
                "target_best50_rate",
            ]
            sort_ascending = [False, False, False, False]

    elif req.goal == "skill_up":
        df["recommend_score"] = df.apply(lambda row: skill_up_score(row, req), axis=1)
        df = df[df["recommend_score"] > 0].copy()

        summary = (
            "실력 향상 모드입니다. "
            "선택한 레벨 범위 안에서 현재/상위 레이팅 구간 통계와 레벨 난이도를 함께 고려하고, "
            "Best50 floor 기준 이득은 보조 feature로 반영합니다."
        )

        sort_columns = [
            "recommend_score",
            "target_best50_rate",
            "current_best50_rate",
            "floor_gain",
            "internal_level",
        ]
        sort_ascending = [False, False, False, False, False]

    elif req.goal == "weakness":
        df["recommend_score"] = df.apply(lambda row: weakness_score(row, req), axis=1)
        df = df[(df["recommend_score"] > 0) & (df["played"])].copy()

        summary = (
            "약점 보완 모드입니다. "
            "입력 유저가 이미 플레이한 곡 중 달성률, 레이팅 상승 여지, 레벨 기준을 함께 고려합니다."
        )

        sort_columns = ["recommend_score", "rating_gain", "achievement", "internal_level"]
        sort_ascending = [False, False, True, False]

    else:
        df["recommend_score"] = df.apply(lambda row: rating_up_score(row, req), axis=1)
        df = df[df["recommend_score"] > 0].copy()

        rating_up_candidates_before_floor_filter = df.copy()
        strict_floor_gain_filter_used = bool(user_floor_summary.get("available", False))

        if strict_floor_gain_filter_used and "floor_gain" in df.columns:
            df = df[
                pd.to_numeric(df["floor_gain"], errors="coerce").fillna(0.0)
                > RATING_UP_MIN_POSITIVE_FLOOR_GAIN
            ].copy()

        rating_up_debug = build_rating_up_candidate_debug(
            df_before_floor_filter=rating_up_candidates_before_floor_filter,
            df_after_floor_filter=df,
            req=req,
            effective_rating=effective_rating,
            user_floor_summary=user_floor_summary,
            requested_top_n=top_n,
            strict_floor_gain_filter_used=strict_floor_gain_filter_used,
        )

        summary = (
            "레이팅 상승 모드입니다. "
            "입력 유저의 NEW/OLD Best50 floor, 100.5% 기준 예상 곡별 레이팅, "
            "동일/상위 레이팅 구간 Best50 통계를 함께 고려합니다."
        )

        if rating_up_debug.get("candidate_shortage"):
            summary = f"{summary} {rating_up_debug.get('candidate_shortage_message', '')}".strip()

        sort_columns = [
            "recommend_score",
            "floor_gain",
            "target_best50_rate",
            "rating_gain",
            "internal_level",
        ]
        sort_ascending = [False, False, False, False, False]

    candidate_pool_count_after_goal = int(len(df))
    reverse_border_candidate_count = int(df["reverse_border"].sum()) if "reverse_border" in df.columns else 0

    candidate_type_counts = (
        df["candidate_label"].value_counts().to_dict()
        if "candidate_label" in df.columns
        else {}
    )

    df = sort_candidates(df=df, sort_columns=sort_columns, sort_ascending=sort_ascending)

    display_df, display_debug = select_display_candidates(
        df=df,
        goal=req.goal,
        top_n=top_n,
    )

    if req.goal == "rating_up":
        rating_up_debug.update(display_debug)

    recommendations = []

    for idx, (_, row) in enumerate(display_df.iterrows(), start=1):
        reason, target = make_reason(row, req.goal)

        applicable_floor = row.get("applicable_floor")
        if applicable_floor is None or pd.isna(applicable_floor):
            applicable_floor_value = None
        else:
            applicable_floor_value = float(applicable_floor)

        recommendations.append({
            "rank": idx,
            "chart_id": safe_str(row.get("chart_id", "")),
            "song_id": safe_str(row.get("song_id", "")),
            "title": safe_str(row.get("title", "")),
            "artist": safe_str(row.get("artist", "")),
            "category": safe_str(row.get("category", "")),
            "version": safe_str(row.get("version", "")),
            "sheet_version": safe_str(row.get("sheet_version", "")),
            "release_date": safe_str(row.get("release_date", "")),
            "image_name": safe_str(row.get("image_name", "")),
            "thumbnail_url": safe_str(row.get("thumbnail_url", "")),
            "difficulty": safe_str(row.get("difficulty", "")),
            "level": safe_str(row.get("level", "")),
            "display_level": safe_str(row.get("display_level", row.get("level", ""))),
            "internal_level": float(safe_float(row.get("internal_level", 0.0))),
            "chart_type": safe_str(row.get("chart_type", "")),
            "bpm": float(safe_float(row.get("bpm", 0.0))),
            "played": bool(row.get("played", False)),
            "achievement": float(safe_float(row.get("achievement", 0.0))),
            "rank_label": safe_str(row.get("rank", "")),
            "play_count": int(safe_int(row.get("play_count", 0))),
            "is_best50": bool(row.get("is_best50", False)),
            "best50_section": safe_str(row.get("best50_section", "")),
            "best50_order": int(safe_int(row.get("best50_order", 0))),
            "record_source": safe_str(row.get("record_source", "")),
            "combo": safe_str(row.get("combo", "")),
            "sync": safe_str(row.get("sync", "")),
            "current_rating": float(safe_float(row.get("current_rating", 0.0))),
            "max_rating": float(safe_float(row.get("max_rating", 0.0))),
            "expected_rating_100_5": float(safe_float(row.get("expected_rating_100_5", 0.0))),
            "rating_gain": float(safe_float(row.get("rating_gain", 0.0))),
            "floor_section": safe_str(row.get("floor_section", "")),
            "applicable_floor": applicable_floor_value,
            "floor_gain": float(safe_float(row.get("floor_gain", 0.0))),
            "floor_gain_score": float(safe_float(row.get("floor_gain_score", 0.0))),
            "floor_gain_label": safe_str(row.get("floor_gain_label", "")),
            "floor_gain_available": bool(row.get("floor_gain_available", False)),
            "current_best50_rate": float(safe_float(row.get("current_best50_rate", 0.0))),
            "target_best50_rate": float(safe_float(row.get("target_best50_rate", 0.0))),
            "current_avg_achievement": float(safe_float(row.get("current_avg_achievement", 0.0))),
            "target_avg_achievement": float(safe_float(row.get("target_avg_achievement", 0.0))),
            "current_sss_rate": float(safe_float(row.get("current_sss_rate", 0.0))),
            "target_sss_rate": float(safe_float(row.get("target_sss_rate", 0.0))),
            "current_sss_plus_rate": float(safe_float(row.get("current_sss_plus_rate", 0.0))),
            "target_sss_plus_rate": float(safe_float(row.get("target_sss_plus_rate", 0.0))),
            "recommend_score": float(safe_float(row.get("recommend_score", 0.0))),
            "similar_user_score": float(safe_float(row.get("collaborative_score", 0.0))),
            "similar_user_evidence": bool(row.get("similar_user_evidence", False)),
            "candidate_label": safe_str(row.get("candidate_label", "")),
            "reverse_border": bool(row.get("reverse_border", False)),
            "reverse_border_gap": float(safe_float(row.get("reverse_border_gap", 0.0))),
            "collaborative_score": float(safe_float(row.get("collaborative_score", 0.0))),
            "similar_user_weighted_rate": float(safe_float(row.get("similar_user_weighted_rate", 0.0))),
            "similar_user_chart_count": int(safe_int(row.get("similar_user_chart_count", 0))),
            "similar_user_count": int(safe_int(row.get("similar_user_count", 0))),
            "similar_user_avg_similarity": float(safe_float(row.get("similar_user_avg_similarity", 0.0))),
            "reason": reason,
            "target": target,
        })

    return {
        "goal": req.goal,
        "summary": summary,
        "recommendations": recommendations,
        "debug": {
            "estimated_rating_from_records": estimated_rating,
            "effective_rating": effective_rating,
            "current_band": current_band,
            "target_band": target_band,
            "current_bands_used": band_debug.get("current_bands_used", [current_band]),
            "target_bands_used": band_debug.get("target_bands_used", [target_band]),
            "band_debug": band_debug,
            "user_floor_summary": user_floor_summary,
            "selected_main_level": req.main_level,
            "selected_goal": req.goal,
            "selected_chart_type": req.chart_type,
            "available_bands": available_bands,
            "input_best50_count": int(len(input_best50_chart_ids)),
            "similar_user_debug": similar_user_debug,
            "rating_up_debug": rating_up_debug,
            "candidate_pool_count": candidate_pool_count_after_goal,
            "display_candidate_count": int(len(display_df)),
            "candidate_pool_count_before_goal": candidate_pool_count_before_goal,
            "reverse_border_candidate_count": reverse_border_candidate_count,
            "candidate_type_counts": candidate_type_counts,
            "best50_record_count": int(df["is_best50"].sum()) if "is_best50" in df.columns else 0,
            "played_record_count": int(df["played"].sum()) if "played" in df.columns else 0,
        },
    }