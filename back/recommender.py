from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

CHARTS_PATH = DATA_DIR / "maimai_charts_13_15.csv"
COHORT_STATS_PATH = DATA_DIR / "cohort_chart_stats.csv"
LEVEL_STATS_PATH = DATA_DIR / "level_distribution_stats.csv"
RAW_USER_BEST50_PATH = DATA_DIR / "raw_user_best50.csv"


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


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default

        return float(value)

    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if pd.isna(value):
            return default

        return int(float(value))

    except Exception:
        return default


def safe_str(value: Any, default: str = "") -> str:
    try:
        if pd.isna(value):
            return default

        return str(value)

    except Exception:
        return default


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


def calculate_chart_rating(internal_level: Any, achievement: Any) -> int:
    """
    maimai 곡별 레이팅을 근사 계산한다.

    실제 게임 내부 계산식과 완전히 동일하다고 보장하기보다는,
    추천 후보 간 상승 여지를 비교하기 위한 안정적인 보조 지표로 사용한다.
    """
    ds = safe_float(internal_level, 0.0)
    ach = safe_float(achievement, 0.0)

    if ds <= 0 or ach <= 0:
        return 0

    ach = min(ach, 100.5)

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

    records = records[
        records["chart_id"].str.len() > 0
    ].copy()

    records = records.sort_values(
        ["is_best50", "chart_rating", "achievement"],
        ascending=[False, False, False],
    )

    records = records.drop_duplicates(
        subset=["chart_id"],
        keep="first",
    ).reset_index(drop=True)

    return records[USER_RECORD_COLUMNS]


def load_base_data(user_records_df: pd.DataFrame | None = None) -> pd.DataFrame:
    charts = load_charts()
    user_records = prepare_user_records(user_records_df)

    df = charts.merge(
        user_records,
        on="chart_id",
        how="left",
    )

    df["achievement"] = pd.to_numeric(
        df["achievement"],
        errors="coerce",
    ).fillna(0.0)

    df["play_count"] = pd.to_numeric(
        df["play_count"],
        errors="coerce",
    ).fillna(0.0)

    df["chart_rating"] = pd.to_numeric(
        df["chart_rating"],
        errors="coerce",
    ).fillna(0.0)

    df["best50_order"] = pd.to_numeric(
        df["best50_order"],
        errors="coerce",
    ).fillna(0.0)

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
        lambda row: calculate_chart_rating(
            row["internal_level"],
            REVERSE_BORDER_MAX,
        ),
        axis=1,
    )

    df["rating_gain"] = (
        df["max_rating"] - df["current_rating"]
    ).clip(lower=0.0)

    df["reverse_border"] = (
        (df["played"])
        & (df["achievement"] >= REVERSE_BORDER_MIN)
        & (df["achievement"] < REVERSE_BORDER_MAX)
    )

    df["reverse_border_gap"] = (
        REVERSE_BORDER_MAX - df["achievement"]
    ).clip(lower=0.0)

    df.loc[~df["reverse_border"], "reverse_border_gap"] = 0.0

    df["candidate_label"] = df.apply(classify_candidate, axis=1)

    return df


def classify_candidate(row: pd.Series) -> str:
    if bool(row.get("is_best50", False)):
        return "best50"

    if bool(row.get("played", False)):
        return "played_not_best50"

    return "unplayed_or_unmatched"


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

    estimated = best50["current_rating"].sort_values(
        ascending=False
    ).head(50).sum()

    if estimated <= 0:
        return None

    return int(round(float(estimated)))


def parse_rating_band_low(band: str) -> int | None:
    try:
        return int(str(band).split("-")[0])
    except Exception:
        return None


def rating_to_band(rating: int | None) -> str:
    if rating is None:
        return "unknown"

    low = int(rating // 500) * 500
    high = low + 499

    return f"{low}-{high}"


def get_available_bands(cohort_stats: pd.DataFrame) -> list[str]:
    if cohort_stats.empty or "rating_band" not in cohort_stats.columns:
        return []

    bands = []

    for band in cohort_stats["rating_band"].dropna().astype(str).unique():
        low = parse_rating_band_low(band)

        if low is not None:
            bands.append((low, band))

    bands = sorted(bands, key=lambda item: item[0])

    return [band for _, band in bands]


def get_target_band(current_band: str, available_bands: list[str]) -> str:
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

    return current_band


def pick_first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col

    return None


def extract_band_features(
    cohort_stats: pd.DataFrame,
    rating_band: str,
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

    band_df = cohort_stats[
        cohort_stats["rating_band"].astype(str) == str(rating_band)
    ].copy()

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
            "sss_plus_ratio",
            "sssp_ratio",
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
        ],
    }

    out = pd.DataFrame()
    out["chart_id"] = band_df["chart_id"].astype(str)

    for dst_name, candidates in feature_specs.items():
        source_col = pick_first_existing_column(band_df, candidates)
        out_col = f"{prefix}_{dst_name}"

        if source_col is None:
            out[out_col] = 0.0
            continue

        if dst_name in {
            "best50_rate",
            "sss_rate",
            "sss_plus_rate",
        }:
            out[out_col] = normalize_rate_series(band_df[source_col])
        else:
            out[out_col] = pd.to_numeric(
                band_df[source_col],
                errors="coerce",
            ).fillna(0.0)

    out = out.drop_duplicates(
        subset=["chart_id"],
        keep="first",
    ).reset_index(drop=True)

    return out


def merge_cohort_features(
    df: pd.DataFrame,
    cohort_stats: pd.DataFrame,
    current_band: str,
    target_band: str,
) -> pd.DataFrame:
    df = df.copy()

    current_features = extract_band_features(
        cohort_stats=cohort_stats,
        rating_band=current_band,
        prefix="current",
    )

    target_features = extract_band_features(
        cohort_stats=cohort_stats,
        rating_band=target_band,
        prefix="target",
    )

    if not current_features.empty:
        df = df.merge(
            current_features,
            on="chart_id",
            how="left",
        )

    if not target_features.empty:
        df = df.merge(
            target_features,
            on="chart_id",
            how="left",
        )

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

    return df


def filter_by_main_level(df: pd.DataFrame, main_level: str, goal: str) -> pd.DataFrame:
    """
    사용자가 선택한 주력 레벨 범위로 후보를 필터링한다.

    모든 추천 목표에서 선택 레벨 범위를 엄격하게 적용한다.
    """
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

    return df[
        df["chart_type"].astype(str).str.lower() == chart_type.lower()
    ].copy()


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
    """
    cohort 평균이 없을 때 사용할 레벨별 보완 기준 달성률.

    약점 보완 모드는 '내가 이미 친 곡 중에서 상대적으로 낮은 기록'을 찾는 목적이므로,
    DB 평균이 없더라도 기본 기준을 사용해 후보를 만들 수 있게 한다.
    """
    default_reference = {
        "13": 100.0,
        "13+": 99.5,
        "14": 99.0,
        "14+": 98.5,
        "15": 97.5,
    }

    return default_reference.get(main_level, 99.0)


def preference_score(row: pd.Series, chart_type: str, bpm_preference: str = "any") -> float:
    """
    과거 BPM 선호 옵션과의 호환성을 위해 남겨둔 함수.

    현재 UI에서는 BPM 선호를 제거했으므로,
    실질적으로는 chart_type 일치 여부만 약하게 반영한다.
    """
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

    if rating_gain <= 0:
        return 0.0

    target_best50_score = safe_float(row.get("target_best50_rate", 0.0))
    current_best50_score = safe_float(row.get("current_best50_rate", 0.0))
    cohort_score = 0.65 * target_best50_score + 0.35 * current_best50_score

    rating_gain_score = min(100.0, rating_gain * 6.0)
    level_score = level_fit_score(row, req.main_level)
    pref_score = preference_score(
        row,
        req.chart_type,
        getattr(req, "bpm_preference", "any"),
    )

    played = bool(row.get("played", False))
    is_best50 = bool(row.get("is_best50", False))

    if is_best50:
        candidate_bonus = 35.0
    elif played:
        candidate_bonus = 80.0
    else:
        candidate_bonus = 65.0

    score = (
        0.35 * rating_gain_score
        + 0.30 * cohort_score
        + 0.15 * level_score
        + 0.10 * candidate_bonus
        + 0.10 * pref_score
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

    if target_evidence_exists or current_evidence_exists:
        score = (
            0.35 * best50_score
            + 0.20 * sss_plus_score
            + 0.15 * record_score
            + 0.15 * challenge_score
            + 0.15 * candidate_bonus
        )
    else:
        score = (
            0.45 * challenge_score
            + 0.30 * level_score
            + 0.25 * candidate_bonus
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

    rating_gain_score = min(
        100.0,
        safe_float(row.get("rating_gain", 0.0)) * 5.0,
    )

    level_score = level_fit_score(row, req.main_level)

    current_best50_score = safe_float(row.get("current_best50_rate", 0.0))
    target_best50_score = safe_float(row.get("target_best50_rate", 0.0))
    cohort_interest_score = max(current_best50_score, target_best50_score)

    is_best50 = bool(row.get("is_best50", False))

    if is_best50:
        candidate_bonus = 70.0
    else:
        candidate_bonus = 85.0

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

    proximity_score = max(
        0.0,
        100.0 - min(100.0, gap * 5000.0),
    )

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
    """
    나와 비슷한 유저 추천 모드 점수.

    collaborative_score를 주력으로 사용하고,
    target_band Best50 등장률, 레벨 적합도, 개선 가능성을 보조로 반영한다.
    """
    collaborative = safe_float(row.get("collaborative_score", 0.0))

    if collaborative <= 0:
        return 0.0

    target_best50_score = safe_float(row.get("target_best50_rate", 0.0))
    level_score = level_fit_score(row, req.main_level)

    played = bool(row.get("played", False))
    is_best50 = bool(row.get("is_best50", False))

    if is_best50:
        improvement_score = min(
            40.0,
            safe_float(row.get("rating_gain", 0.0)) * 4.0,
        )
        candidate_bonus = 10.0

    elif played:
        improvement_score = min(
            100.0,
            safe_float(row.get("rating_gain", 0.0)) * 8.0,
        )
        candidate_bonus = 75.0

    else:
        improvement_score = 50.0
        candidate_bonus = 60.0

    score = (
        0.65 * collaborative
        + 0.15 * target_best50_score
        + 0.10 * level_score
        + 0.05 * improvement_score
        + 0.05 * candidate_bonus
    )

    return round(max(0.0, min(score, 100.0)), 2)


def get_input_best50_chart_ids(df: pd.DataFrame) -> set[str]:
    """
    입력 유저의 Best50 chart_id 집합을 추출한다.

    협업 필터링에서는 이 집합을 입력 유저 벡터로 사용한다.
    """
    if "is_best50" not in df.columns:
        return set()

    if "chart_id" not in df.columns:
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
    """
    Best50 기반 user-item matrix를 이용해 협업 필터링 feature를 생성한다.

    방식:
    1. 입력 유저 Best50 chart_id 집합 생성
    2. raw_user_best50.csv에서 DB 유저별 Best50 집합 생성
    3. 입력 유저와 DB 유저 간 cosine similarity 계산
    4. 유사 유저 top-k 선정
    5. 유사 유저들이 보유한 chart_id에 유사도 가중 등장률 부여
    """
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
        debug["reason"] = (
            f"input best50 count is less than {SIMILAR_USER_MIN_INPUT_BEST50}"
        )
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

        similarity = intersection_count / math.sqrt(
            input_len * len(user_chart_ids)
        )

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
            chart_weight_sum[chart_id] = (
                chart_weight_sum.get(chart_id, 0.0) + similarity
            )
            chart_user_count[chart_id] = (
                chart_user_count.get(chart_id, 0) + 1
            )

    df["_chart_id_str"] = df["chart_id"].astype(str)

    df["collaborative_weight_sum"] = df["_chart_id_str"].map(
        chart_weight_sum
    ).fillna(0.0)

    df["similar_user_chart_count"] = df["_chart_id_str"].map(
        chart_user_count
    ).fillna(0).astype(int)

    df["similar_user_weighted_rate"] = (
        df["collaborative_weight_sum"] / total_similarity * 100.0
    )

    df["collaborative_score"] = df["similar_user_weighted_rate"].clip(
        lower=0.0,
        upper=100.0,
    )

    similarity_values = [
        item["similarity"]
        for item in similarities
    ]

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


def make_reason(row: pd.Series, goal: str) -> tuple[str, str]:
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
        max_rating = safe_float(row.get("max_rating", 0.0))

        if bool(row.get("played", False)):
            reason = (
                f"현재 곡별 레이팅은 {current_rating:.0f}이고, "
                f"100.5% 기준 최대 레이팅은 {max_rating:.0f}입니다. "
                f"상승 여지가 약 {rating_gain:.0f} 남아 있으며, "
                f"상위 레이팅 구간 Best50 등장률은 {target_rate:.1f}%입니다."
            )
        else:
            reason = (
                f"아직 입력 유저 기록에 없는 후보입니다. "
                f"상위 레이팅 구간 Best50 등장률이 {target_rate:.1f}%로 확인되어, "
                f"레이팅 상승용 신규 후보로 추천합니다."
            )

        target = "100.5% 근처 달성률 확보"

        return reason, target

    if goal == "skill_up":
        target_rate = safe_float(row.get("target_best50_rate", 0.0))
        current_rate = safe_float(row.get("current_best50_rate", 0.0))
        sss_plus_rate = safe_float(row.get("target_sss_plus_rate", 0.0))

        reason = (
            f"선택한 레벨대에서 실력 향상 후보로 계산되었습니다. "
            f"상위 구간 Best50 등장률은 {target_rate:.1f}%, "
            f"현재 구간 Best50 등장률은 {current_rate:.1f}%, "
            f"상위 구간 SSS+ 비율은 {sss_plus_rate:.1f}%입니다."
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

        default_reference = get_default_weakness_reference(
            safe_str(row.get("level", "")),
        )

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

    return df.sort_values(
        valid_columns,
        ascending=valid_ascending,
    ).reset_index(drop=True)


def recommend(
    req: Any,
    user_records_df: pd.DataFrame | None = None,
    user_rating: int | None = None,
) -> dict[str, Any]:
    df = load_base_data(user_records_df)

    input_best50_chart_ids = get_input_best50_chart_ids(df)

    similar_user_debug = {
        "available": False,
        "reason": "similar_user mode was not selected",
        "input_best50_count": len(input_best50_chart_ids),
    }

    estimated_rating = estimate_rating_from_records(df)
    effective_rating = user_rating if user_rating is not None else estimated_rating

    cohort_stats = load_cohort_stats()
    _ = load_level_stats()

    available_bands = get_available_bands(cohort_stats)

    current_band = rating_to_band(effective_rating)
    target_band = get_target_band(current_band, available_bands)

    df = merge_cohort_features(
        df=df,
        cohort_stats=cohort_stats,
        current_band=current_band,
        target_band=target_band,
    )

    df = filter_by_main_level(
        df=df,
        main_level=req.main_level,
        goal=req.goal,
    )

    df = filter_by_chart_type(
        df=df,
        chart_type=req.chart_type,
    )

    candidate_pool_count_before_goal = int(len(df))

    summary = ""
    sort_columns = [
        "recommend_score",
        "target_best50_rate",
        "rating_gain",
        "internal_level",
    ]
    sort_ascending = [False, False, False, False]

    if req.goal == "reverse_border":
        df["recommend_score"] = df.apply(
            lambda row: reverse_border_score(row, req),
            axis=1,
        )

        df = df[
            (df["recommend_score"] > 0)
            & (df["reverse_border"])
        ].copy()

        summary = (
            "역보더 탐색 모드입니다. "
            "현재 달성률이 100.4000% 이상 100.5000% 미만인 곡을 "
            "100.5%에 가까운 순서와 Best50 여부를 함께 고려해 추천합니다."
        )

        sort_columns = [
            "reverse_border_gap",
            "internal_level",
            "is_best50",
            "current_rating",
        ]
        sort_ascending = [True, False, False, False]

    elif req.goal == "similar_user":
        df, similar_user_debug = add_collaborative_features(
            df=df,
            input_best50_chart_ids=input_best50_chart_ids,
            top_k=SIMILAR_USER_TOP_K,
        )

        df["recommend_score"] = df.apply(
            lambda row: similar_user_score(row, req),
            axis=1,
        )

        df = df[
            (df["recommend_score"] > 0)
            & (~df["is_best50"])
        ].copy()

        summary = (
            "나와 비슷한 유저 추천 모드입니다. "
            f"입력 유저의 Best50 {len(input_best50_chart_ids)}개를 기준으로 "
            "DB 유저들과 cosine similarity를 계산하고, "
            f"유사 유저 Top {SIMILAR_USER_TOP_K}명의 Best50 등장 패턴을 반영했습니다."
        )

        sort_columns = [
            "recommend_score",
            "collaborative_score",
            "similar_user_chart_count",
            "target_best50_rate",
        ]
        sort_ascending = [False, False, False, False]

    elif req.goal == "skill_up":
        df["recommend_score"] = df.apply(
            lambda row: skill_up_score(row, req),
            axis=1,
        )

        df = df[df["recommend_score"] > 0].copy()

        summary = (
            "실력 향상 모드입니다. "
            "선택한 레벨 범위 안에서 현재/상위 레이팅 구간 통계와 레벨 난이도를 함께 고려합니다."
        )

        sort_columns = [
            "recommend_score",
            "target_best50_rate",
            "current_best50_rate",
            "internal_level",
        ]
        sort_ascending = [False, False, False, False]

    elif req.goal == "weakness":
        df["recommend_score"] = df.apply(
            lambda row: weakness_score(row, req),
            axis=1,
        )

        df = df[
            (df["recommend_score"] > 0)
            & (df["played"])
        ].copy()

        summary = (
            "약점 보완 모드입니다. "
            "입력 유저가 이미 플레이한 곡 중 달성률, 레이팅 상승 여지, 레벨 기준을 함께 고려합니다."
        )

        sort_columns = [
            "recommend_score",
            "rating_gain",
            "achievement",
            "internal_level",
        ]
        sort_ascending = [False, False, True, False]

    else:
        df["recommend_score"] = df.apply(
            lambda row: rating_up_score(row, req),
            axis=1,
        )

        df = df[df["recommend_score"] > 0].copy()

        summary = (
            "레이팅 상승 모드입니다. "
            "입력 유저의 현재 기록, 100.5% 기준 상승 여지, 동일/상위 레이팅 구간 Best50 통계를 함께 고려합니다."
        )

        sort_columns = [
            "recommend_score",
            "rating_gain",
            "target_best50_rate",
            "internal_level",
        ]
        sort_ascending = [False, False, False, False]

    candidate_pool_count_after_goal = int(len(df))
    reverse_border_candidate_count = int(
        df["reverse_border"].sum()
    ) if "reverse_border" in df.columns else 0

    candidate_type_counts = (
        df["candidate_label"].value_counts().to_dict()
        if "candidate_label" in df.columns
        else {}
    )

    df = sort_candidates(
        df=df,
        sort_columns=sort_columns,
        sort_ascending=sort_ascending,
    )

    top_n = safe_int(getattr(req, "top_n", 10), 10)
    top_n = max(1, min(top_n, 30))

    recommendations = []

    for idx, (_, row) in enumerate(df.head(top_n).iterrows(), start=1):
        reason, target = make_reason(row, req.goal)

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
            "display_level": safe_str(
                row.get("display_level", row.get("level", "")),
            ),
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
            "rating_gain": float(safe_float(row.get("rating_gain", 0.0))),
            "current_best50_rate": float(safe_float(row.get("current_best50_rate", 0.0))),
            "target_best50_rate": float(safe_float(row.get("target_best50_rate", 0.0))),
            "current_avg_achievement": float(safe_float(row.get("current_avg_achievement", 0.0))),
            "target_avg_achievement": float(safe_float(row.get("target_avg_achievement", 0.0))),
            "current_sss_rate": float(safe_float(row.get("current_sss_rate", 0.0))),
            "target_sss_rate": float(safe_float(row.get("target_sss_rate", 0.0))),
            "current_sss_plus_rate": float(safe_float(row.get("current_sss_plus_rate", 0.0))),
            "target_sss_plus_rate": float(safe_float(row.get("target_sss_plus_rate", 0.0))),
            "recommend_score": float(safe_float(row.get("recommend_score", 0.0))),
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
            "selected_main_level": req.main_level,
            "selected_goal": req.goal,
            "selected_chart_type": req.chart_type,
            "available_bands": available_bands,
            "input_best50_count": int(len(input_best50_chart_ids)),
            "similar_user_debug": similar_user_debug,
            "candidate_pool_count": candidate_pool_count_after_goal,
            "candidate_pool_count_before_goal": candidate_pool_count_before_goal,
            "reverse_border_candidate_count": reverse_border_candidate_count,
            "candidate_type_counts": candidate_type_counts,
            "best50_record_count": int(
                df["is_best50"].sum()
            ) if "is_best50" in df.columns else 0,
            "played_record_count": int(
                df["played"].sum()
            ) if "played" in df.columns else 0,
        },
    }