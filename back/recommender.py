import math
from pathlib import Path

import pandas as pd


CHARTS_PATH = Path("data/maimai_charts_13_15.csv")

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

COHORT_STATS_PATH = Path("data/cohort_chart_stats.csv")
LEVEL_STATS_PATH = Path("data/level_distribution_stats.csv")


LEVEL_TO_NUM = {
    "13": 13.0,
    "13+": 13.7,
    "14": 14.0,
    "14+": 14.7,
    "15": 15.0,
}


LEVEL_BOUNDS = {
    "13": (13.0, 13.5),
    "13+": (13.6, 13.9),
    "14": (14.0, 14.5),
    "14+": (14.6, 14.9),
    "15": (15.0, 99.0),
}


REVERSE_BORDER_MIN = 100.4000
REVERSE_BORDER_MAX = 100.5000


RATING_FACTORS = [
    (100.5, 0.224),
    (100.0, 0.216),
    (99.5, 0.211),
    (99.0, 0.208),
    (98.0, 0.203),
    (97.0, 0.200),
    (94.0, 0.168),
    (90.0, 0.152),
    (80.0, 0.136),
    (0.0, 0.000),
]


# ------------------------------------------------------------
# Basic utilities
# ------------------------------------------------------------

def get_rating_factor(achievement: float) -> float:
    for threshold, factor in RATING_FACTORS:
        if achievement >= threshold:
            return factor

    return 0.0


def calculate_chart_rating(internal_level: float, achievement: float) -> int:
    if achievement <= 0:
        return 0

    capped_achievement = min(float(achievement), 100.5)
    factor = get_rating_factor(capped_achievement)

    return math.floor(float(internal_level) * capped_achievement * factor)


def calculate_max_chart_rating(internal_level: float) -> int:
    return calculate_chart_rating(internal_level, 100.5)


def normalize_is_new(value) -> bool:
    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    return text in {"true", "1", "yes"}


def normalize_bool(value) -> bool:
    if isinstance(value, bool):
        return value

    if pd.isna(value):
        return False

    text = str(value).strip().lower()

    return text in {"true", "1", "yes"}


def safe_float(value, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default

        return float(value)

    except Exception:
        return default

def safe_str(value, default: str = "") -> str:
    try:
        if pd.isna(value):
            return default

        return str(value)

    except Exception:
        return default

def safe_int(value, default: int = 0) -> int:
    try:
        if pd.isna(value):
            return default

        return int(float(value))

    except Exception:
        return default


# ------------------------------------------------------------
# Data loading
# ------------------------------------------------------------

def load_charts() -> pd.DataFrame:
    charts = pd.read_csv(CHARTS_PATH)
    charts["is_new"] = charts["is_new"].apply(normalize_is_new)

    optional_columns = {
        "artist": "",
        "category": "",
        "version": "",
        "sheet_version": "",
        "release_date": "",
        "image_name": "",
        "thumbnail_url": "",
        "display_level": "",
    }

    for col, default_value in optional_columns.items():
        if col not in charts.columns:
            charts[col] = default_value

        charts[col] = charts[col].fillna(default_value).astype(str)

    return charts

def make_empty_user_records() -> pd.DataFrame:
    """
    유저 기록이 없는 경우 사용하는 빈 기록 DataFrame.
    """
    return pd.DataFrame(columns=USER_RECORD_COLUMNS)

def prepare_user_records(user_records_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    추천 로직에서 사용할 유저 기록 DataFrame을 표준화한다.

    user_records_df가 None이면 더미 CSV를 읽지 않고 빈 기록을 사용한다.
    이 경우 추천은 cohort 통계 기반 후보 중심으로 생성된다.
    """
    if user_records_df is None:
        records = make_empty_user_records()
    else:
        records = user_records_df.copy()

    if "chart_id" not in records.columns:
        raise ValueError("user records must contain chart_id column")

    if "achievement" not in records.columns:
        records["achievement"] = 0.0

    if "rank" not in records.columns:
        records["rank"] = "NO_PLAY"

    if "play_count" not in records.columns:
        records["play_count"] = 1

    if "chart_rating" not in records.columns:
        records["chart_rating"] = pd.NA

    if "is_best50" not in records.columns:
        records["is_best50"] = False

    if "best50_section" not in records.columns:
        records["best50_section"] = "unknown"

    if "best50_order" not in records.columns:
        records["best50_order"] = pd.NA

    if "record_source" not in records.columns:
        records["record_source"] = "unknown"

    if "combo" not in records.columns:
        records["combo"] = ""

    if "sync" not in records.columns:
        records["sync"] = ""

    records["achievement"] = records["achievement"].fillna(0.0)
    records["rank"] = records["rank"].fillna("NO_PLAY")
    records["play_count"] = records["play_count"].fillna(0)
    records["is_best50"] = records["is_best50"].apply(normalize_bool)
    records["best50_section"] = records["best50_section"].fillna("unknown").astype(str)
    records["record_source"] = records["record_source"].fillna("unknown").astype(str)
    records["combo"] = records["combo"].fillna("").astype(str)
    records["sync"] = records["sync"].fillna("").astype(str)

    return records


def load_base_data(user_records_df: pd.DataFrame | None = None) -> pd.DataFrame:
    charts = load_charts()
    records = prepare_user_records(user_records_df)

    df = charts.merge(records, on="chart_id", how="left")

    df["achievement"] = df["achievement"].fillna(0.0)
    df["rank"] = df["rank"].fillna("NO_PLAY")
    df["play_count"] = df["play_count"].fillna(0)

    if "chart_rating" not in df.columns:
        df["chart_rating"] = pd.NA

    if "is_best50" not in df.columns:
        df["is_best50"] = False

    if "best50_section" not in df.columns:
        df["best50_section"] = "unknown"

    if "best50_order" not in df.columns:
        df["best50_order"] = pd.NA

    if "record_source" not in df.columns:
        df["record_source"] = "unknown"

    if "combo" not in df.columns:
        df["combo"] = ""

    if "sync" not in df.columns:
        df["sync"] = ""

    df["is_best50"] = df["is_best50"].apply(normalize_bool)
    df["best50_section"] = df["best50_section"].fillna("unknown").astype(str)
    df["record_source"] = df["record_source"].fillna("unknown").astype(str)
    df["combo"] = df["combo"].fillna("").astype(str)
    df["sync"] = df["sync"].fillna("").astype(str)

    def current_rating_from_row(row) -> int:
        if row["achievement"] <= 0:
            return 0

        site_rating = row.get("chart_rating", pd.NA)

        if not pd.isna(site_rating):
            return int(site_rating)

        return calculate_chart_rating(
            row["internal_level"],
            row["achievement"],
        )

    df["current_rating"] = df.apply(current_rating_from_row, axis=1)
    df["max_rating"] = df["internal_level"].apply(calculate_max_chart_rating)
    df["rating_gain"] = df["max_rating"] - df["current_rating"]
    df["rating_gain"] = df["rating_gain"].clip(lower=0)

    df["played"] = df["achievement"] > 0
    df["rating_capped"] = df["achievement"] >= 100.5

    df["reverse_border"] = (
        (df["played"])
        & (df["achievement"] >= REVERSE_BORDER_MIN)
        & (df["achievement"] < REVERSE_BORDER_MAX)
    )

    df["reverse_border_gap"] = (REVERSE_BORDER_MAX - df["achievement"]).clip(lower=0)
    df.loc[~df["reverse_border"], "reverse_border_gap"] = 0.0

    df["candidate_type"] = df.apply(classify_candidate_type, axis=1)
    df["candidate_label"] = df["candidate_type"].apply(candidate_type_to_label)

    return df


def load_cohort_stats() -> pd.DataFrame:
    if not COHORT_STATS_PATH.exists():
        return pd.DataFrame()

    return pd.read_csv(COHORT_STATS_PATH)


def load_level_stats() -> pd.DataFrame:
    if not LEVEL_STATS_PATH.exists():
        return pd.DataFrame()

    return pd.read_csv(LEVEL_STATS_PATH)


# ------------------------------------------------------------
# Candidate type
# ------------------------------------------------------------

def classify_candidate_type(row) -> str:
    played = bool(row.get("played", False))
    is_best50 = bool(row.get("is_best50", False))

    if played and is_best50:
        return "best50_existing"

    if played and not is_best50:
        return "played_not_best50"

    return "not_in_parsed_records"


def candidate_type_to_label(candidate_type: str) -> str:
    labels = {
        "best50_existing": "Best 50 기존 기록",
        "played_not_best50": "Best 50 밖 플레이 기록",
        "not_in_parsed_records": "현재 파싱 기록 미포함 후보",
    }

    return labels.get(candidate_type, "후보 유형 미분류")


# ------------------------------------------------------------
# Rating band utilities
# ------------------------------------------------------------

def estimate_user_total_rating(df: pd.DataFrame) -> int:
    best50 = df[
        (df["played"])
        & (df["is_best50"])
        & (df["current_rating"] > 0)
    ].copy()

    if not best50.empty:
        return int(best50["current_rating"].sum())

    played = df[df["played"]].copy()

    if played.empty:
        return 0

    new_sum = (
        played[played["is_new"]]
        .sort_values("current_rating", ascending=False)
        .head(15)["current_rating"]
        .sum()
    )

    old_sum = (
        played[~played["is_new"]]
        .sort_values("current_rating", ascending=False)
        .head(35)["current_rating"]
        .sum()
    )

    return int(new_sum + old_sum)


def parse_band_low(band: str) -> int:
    try:
        return int(str(band).split("-")[0])
    except Exception:
        return 0


def band_from_rating(rating: int, available_bands: list[str]) -> str:
    if not available_bands:
        return "15000-15499"

    band_lows = sorted([parse_band_low(b) for b in available_bands])

    if rating <= 0:
        selected_low = band_lows[0]
        return f"{selected_low}-{selected_low + 499}"

    current_low = (rating // 500) * 500
    valid_lows = [low for low in band_lows if low <= current_low]

    if valid_lows:
        selected_low = max(valid_lows)
    else:
        selected_low = min(band_lows)

    return f"{selected_low}-{selected_low + 499}"


def next_band(current_band: str, available_bands: list[str]) -> str:
    current_low = parse_band_low(current_band)
    target_low = current_low + 500
    target_band = f"{target_low}-{target_low + 499}"

    if target_band in set(available_bands):
        return target_band

    return current_band


def estimate_best50_cutoffs(df: pd.DataFrame) -> dict:
    cutoffs = {
        True: 0,
        False: 0,
    }

    best50 = df[
        (df["played"])
        & (df["is_best50"])
        & (df["current_rating"] > 0)
    ].copy()

    if not best50.empty:
        best50["section_norm"] = best50["best50_section"].astype(str).str.lower()

        new_group = best50[best50["section_norm"] == "new"]
        old_group = best50[best50["section_norm"] == "old"]

        if not new_group.empty:
            cutoffs[True] = int(new_group["current_rating"].min())

        if not old_group.empty:
            cutoffs[False] = int(old_group["current_rating"].min())

        if cutoffs[True] > 0 or cutoffs[False] > 0:
            return cutoffs

    played = df[df["played"]].copy()

    for is_new in [True, False]:
        group = played[played["is_new"] == is_new]
        limit = 15 if is_new else 35

        if group.empty:
            cutoffs[is_new] = 0
            continue

        sorted_ratings = group["current_rating"].sort_values(ascending=False)

        if len(sorted_ratings) >= limit:
            cutoffs[is_new] = int(sorted_ratings.iloc[limit - 1])
        else:
            cutoffs[is_new] = int(sorted_ratings.min())

    return cutoffs


# ------------------------------------------------------------
# Candidate filtering
# ------------------------------------------------------------

def filter_by_main_level(df: pd.DataFrame, main_level: str, goal: str) -> pd.DataFrame:
    """
    사용자가 선택한 주력 레벨 범위로 후보를 필터링한다.

    이전 버전에서는 skill_up 모드에서 상위 0.3 내부상수를 자동으로 추가 허용했지만,
    UI에서 '13+'를 선택했는데 14레벨 곡이 노출되는 혼란이 있었다.
    따라서 현재 버전에서는 모든 추천 목표에서 선택 레벨 범위를 엄격하게 적용한다.
    """
    if main_level not in LEVEL_BOUNDS:
        return df

    low, high = LEVEL_BOUNDS[main_level]

    filtered = df[
        (df["internal_level"] >= low)
        & (df["internal_level"] <= high)
    ].copy()

    return filtered


# ------------------------------------------------------------
# Cohort feature merge
# ------------------------------------------------------------

def add_empty_cohort_columns(df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "curr_player_count",
        "curr_avg_achievement",
        "curr_median_achievement",
        "curr_sss_rate",
        "curr_sssplus_rate",
        "curr_avg_chart_rating",
        "curr_best50_rate",
        "target_player_count",
        "target_avg_achievement",
        "target_median_achievement",
        "target_sss_rate",
        "target_sssplus_rate",
        "target_avg_chart_rating",
        "target_best50_rate",
        "curr_level_avg_achievement",
        "curr_level_sss_rate",
        "curr_level_sssplus_rate",
        "curr_level_coverage_rate",
        "target_level_avg_achievement",
        "target_level_sss_rate",
        "target_level_sssplus_rate",
        "target_level_coverage_rate",
    ]

    for col in columns:
        df[col] = 0.0

    return df


def fill_cohort_na(df: pd.DataFrame) -> pd.DataFrame:
    fill_cols = [
        "curr_player_count",
        "curr_avg_achievement",
        "curr_median_achievement",
        "curr_sss_rate",
        "curr_sssplus_rate",
        "curr_avg_chart_rating",
        "curr_best50_rate",
        "target_player_count",
        "target_avg_achievement",
        "target_median_achievement",
        "target_sss_rate",
        "target_sssplus_rate",
        "target_avg_chart_rating",
        "target_best50_rate",
        "curr_level_avg_achievement",
        "curr_level_sss_rate",
        "curr_level_sssplus_rate",
        "curr_level_coverage_rate",
        "target_level_avg_achievement",
        "target_level_sss_rate",
        "target_level_sssplus_rate",
        "target_level_coverage_rate",
    ]

    for col in fill_cols:
        if col not in df.columns:
            df[col] = 0.0

        df[col] = df[col].fillna(0.0)

    return df


def add_cohort_features(
    df: pd.DataFrame,
    cohort_stats: pd.DataFrame,
    level_stats: pd.DataFrame,
    current_band: str,
    target_band: str,
) -> pd.DataFrame:
    df = df.copy()

    if cohort_stats.empty:
        return add_empty_cohort_columns(df)

    current_stats = cohort_stats[cohort_stats["rating_band"] == current_band].copy()
    target_stats = cohort_stats[cohort_stats["rating_band"] == target_band].copy()

    current_cols = {
        "player_count": "curr_player_count",
        "avg_achievement": "curr_avg_achievement",
        "median_achievement": "curr_median_achievement",
        "sss_rate": "curr_sss_rate",
        "sssplus_rate": "curr_sssplus_rate",
        "avg_chart_rating": "curr_avg_chart_rating",
        "best50_rate": "curr_best50_rate",
    }

    target_cols = {
        "player_count": "target_player_count",
        "avg_achievement": "target_avg_achievement",
        "median_achievement": "target_median_achievement",
        "sss_rate": "target_sss_rate",
        "sssplus_rate": "target_sssplus_rate",
        "avg_chart_rating": "target_avg_chart_rating",
        "best50_rate": "target_best50_rate",
    }

    current_stats = current_stats[["chart_id"] + list(current_cols.keys())].rename(
        columns=current_cols
    )
    target_stats = target_stats[["chart_id"] + list(target_cols.keys())].rename(
        columns=target_cols
    )

    df = df.merge(current_stats, on="chart_id", how="left")
    df = df.merge(target_stats, on="chart_id", how="left")

    if not level_stats.empty:
        df["internal_level_rounded"] = df["internal_level"].round(1)

        current_level = level_stats[level_stats["rating_band"] == current_band].copy()
        target_level = level_stats[level_stats["rating_band"] == target_band].copy()

        current_level_cols = {
            "avg_achievement": "curr_level_avg_achievement",
            "sss_rate": "curr_level_sss_rate",
            "sssplus_rate": "curr_level_sssplus_rate",
            "coverage_rate": "curr_level_coverage_rate",
        }

        target_level_cols = {
            "avg_achievement": "target_level_avg_achievement",
            "sss_rate": "target_level_sss_rate",
            "sssplus_rate": "target_level_sssplus_rate",
            "coverage_rate": "target_level_coverage_rate",
        }

        current_level = current_level[
            ["internal_level"] + list(current_level_cols.keys())
        ].rename(columns=current_level_cols)

        target_level = target_level[
            ["internal_level"] + list(target_level_cols.keys())
        ].rename(columns=target_level_cols)

        current_level = current_level.rename(
            columns={"internal_level": "internal_level_rounded"}
        )
        target_level = target_level.rename(
            columns={"internal_level": "internal_level_rounded"}
        )

        df = df.merge(current_level, on="internal_level_rounded", how="left")
        df = df.merge(target_level, on="internal_level_rounded", how="left")

    return fill_cohort_na(df)


# ------------------------------------------------------------
# Preference / fit scores
# ------------------------------------------------------------

def preference_score(row, chart_type: str, bpm_preference: str) -> float:
    score = 0.0

    if chart_type == "any" or row["chart_type"] == chart_type:
        score += 50.0

    bpm = safe_float(row["bpm"])

    if bpm_preference == "any":
        score += 50.0
    elif bpm_preference == "slow" and bpm < 160:
        score += 50.0
    elif bpm_preference == "normal" and 160 <= bpm <= 200:
        score += 50.0
    elif bpm_preference == "fast" and bpm > 200:
        score += 50.0

    return score


def level_fit_score(row, main_level: str) -> float:
    user_level = LEVEL_TO_NUM[main_level]
    diff = abs(safe_float(row["internal_level"]) - user_level)

    return max(0.0, 100.0 - diff * 60.0)


def challenge_fit_score(row, main_level: str) -> float:
    user_level = LEVEL_TO_NUM[main_level]
    chart_level = safe_float(row["internal_level"])
    diff = chart_level - user_level

    return max(0.0, 100.0 - abs(diff - 0.5) * 80.0)


def confidence_score(player_count: float) -> float:
    count = safe_float(player_count)

    return min(100.0, count / 5.0 * 100.0)


# ------------------------------------------------------------
# Scoring functions
# ------------------------------------------------------------

def rating_up_score(row, req, cutoffs: dict) -> float:
    played = bool(row["played"])
    capped = bool(row["rating_capped"])
    is_new = bool(row["is_new"])

    if played and capped:
        return 0.0

    curr_best50 = safe_float(row["curr_best50_rate"]) * 100.0
    curr_sssplus = safe_float(row["curr_sssplus_rate"]) * 100.0
    target_best50 = safe_float(row["target_best50_rate"]) * 100.0
    target_sssplus = safe_float(row["target_sssplus_rate"]) * 100.0

    curr_conf = confidence_score(row["curr_player_count"])
    target_conf = confidence_score(row["target_player_count"])
    confidence = max(curr_conf, target_conf)

    if played:
        achievement = safe_float(row["achievement"])
        gain_score = min(100.0, safe_float(row["rating_gain"]) * 8.0)

        cohort_gap = max(0.0, safe_float(row["curr_avg_achievement"]) - achievement)
        gap_score = min(100.0, cohort_gap * 25.0)

        reverse_border_bonus = 100.0 if bool(row.get("reverse_border", False)) else 0.0

        score = (
            0.30 * gain_score
            + 0.20 * curr_sssplus
            + 0.15 * target_best50
            + 0.10 * target_sssplus
            + 0.10 * gap_score
            + 0.10 * reverse_border_bonus
            + 0.05 * confidence
        )

    else:
        cutoff = cutoffs.get(is_new, 0)
        max_rating = safe_float(row["max_rating"])
        possible_gain = max(0.0, max_rating - cutoff)
        gain_score = min(100.0, possible_gain * 5.0)

        discover_score = (
            0.35 * curr_best50
            + 0.30 * curr_sssplus
            + 0.25 * target_best50
            + 0.10 * target_sssplus
        )

        if curr_best50 == 0 and target_best50 == 0:
            return 0.0

        score = (
            0.35 * discover_score
            + 0.25 * gain_score
            + 0.15 * level_fit_score(row, req.main_level)
            + 0.15 * target_best50
            + 0.10 * confidence
        )

    score += 0.05 * preference_score(row, req.chart_type, req.bpm_preference)

    return round(max(0.0, min(score, 100.0)), 2)


def reverse_border_score(row, req) -> float:
    if not bool(row.get("reverse_border", False)):
        return 0.0

    achievement = safe_float(row["achievement"])
    gap = REVERSE_BORDER_MAX - achievement

    closeness_score = max(0.0, min(100.0, 100.0 - gap * 1000.0))
    level_score = min(100.0, max(0.0, (safe_float(row["internal_level"]) - 12.5) * 30.0))
    best50_bonus = 100.0 if bool(row.get("is_best50", False)) else 40.0

    score = (
        0.70 * closeness_score
        + 0.20 * level_score
        + 0.10 * best50_bonus
    )

    score += 0.05 * preference_score(row, req.chart_type, req.bpm_preference)

    return round(max(0.0, min(score, 100.0)), 2)


def skill_up_score(row, req) -> float:
    played = bool(row["played"])
    capped = bool(row["rating_capped"])

    curr_best50 = safe_float(row["curr_best50_rate"]) * 100.0
    curr_sssplus = safe_float(row["curr_sssplus_rate"]) * 100.0
    target_best50 = safe_float(row["target_best50_rate"]) * 100.0
    target_sssplus = safe_float(row["target_sssplus_rate"]) * 100.0

    target_conf = confidence_score(row["target_player_count"])

    if not played:
        novelty_score = 100.0
    elif not capped:
        novelty_score = 65.0
    else:
        novelty_score = 10.0

    growth_signal = max(0.0, target_best50 - curr_best50)
    growth_score = min(100.0, growth_signal * 2.0 + target_best50 * 0.6)

    score = (
        0.30 * target_best50
        + 0.20 * growth_score
        + 0.15 * target_sssplus
        + 0.15 * challenge_fit_score(row, req.main_level)
        + 0.10 * novelty_score
        + 0.05 * curr_sssplus
        + 0.05 * target_conf
    )

    score += 0.05 * preference_score(row, req.chart_type, req.bpm_preference)

    return round(max(0.0, min(score, 100.0)), 2)


def get_weak_internal_levels(df: pd.DataFrame) -> list[float]:
    played = df[df["played"]].copy()

    if played.empty:
        return []

    played["internal_level_rounded"] = played["internal_level"].round(1)

    level_summary = (
        played.groupby("internal_level_rounded")
        .agg(
            user_avg_achievement=("achievement", "mean"),
            cohort_avg_achievement=("curr_level_avg_achievement", "first"),
            played_count=("chart_id", "count"),
        )
        .reset_index()
    )

    level_summary["weakness_gap"] = (
        level_summary["cohort_avg_achievement"]
        - level_summary["user_avg_achievement"]
    )

    level_summary = level_summary[
        (level_summary["cohort_avg_achievement"] > 0)
        & (level_summary["weakness_gap"] > 0)
    ]

    if level_summary.empty:
        return []

    level_summary = level_summary.sort_values("weakness_gap", ascending=False)

    return level_summary.head(3)["internal_level_rounded"].tolist()


def weakness_score(row, req, weak_internal_levels: list[float]) -> float:
    achievement = safe_float(row["achievement"])
    played = bool(row["played"])
    capped = bool(row["rating_capped"])

    internal_level_rounded = round(safe_float(row["internal_level"]), 1)

    curr_avg = safe_float(row["curr_avg_achievement"])
    curr_best50 = safe_float(row["curr_best50_rate"]) * 100.0
    curr_sssplus = safe_float(row["curr_sssplus_rate"]) * 100.0
    target_best50 = safe_float(row["target_best50_rate"]) * 100.0

    level_avg = safe_float(row["curr_level_avg_achievement"])
    level_coverage = safe_float(row["curr_level_coverage_rate"]) * 100.0

    if played:
        if capped:
            return 0.0

        chart_gap = max(0.0, curr_avg - achievement)
        level_gap = max(0.0, level_avg - achievement)

        gap_score = min(100.0, chart_gap * 25.0 + level_gap * 10.0)
        weak_level_bonus = 100.0 if internal_level_rounded in weak_internal_levels else 40.0

        score = (
            0.35 * gap_score
            + 0.20 * weak_level_bonus
            + 0.15 * curr_best50
            + 0.10 * curr_sssplus
            + 0.10 * level_coverage
            + 0.10 * level_fit_score(row, req.main_level)
        )

    else:
        weak_level_bonus = 100.0 if internal_level_rounded in weak_internal_levels else 30.0

        if curr_best50 == 0 and target_best50 == 0:
            return 0.0

        score = (
            0.30 * weak_level_bonus
            + 0.25 * curr_best50
            + 0.15 * curr_sssplus
            + 0.15 * target_best50
            + 0.10 * level_coverage
            + 0.05 * level_fit_score(row, req.main_level)
        )

    score += 0.05 * preference_score(row, req.chart_type, req.bpm_preference)

    return round(max(0.0, min(score, 100.0)), 2)


# ------------------------------------------------------------
# Reason text
# ------------------------------------------------------------

def make_reason(goal: str, row, current_band: str, target_band: str) -> tuple[str, str]:
    achievement = safe_float(row["achievement"])
    candidate_type = row.get("candidate_type", "not_in_parsed_records")
    candidate_label = row.get("candidate_label", "현재 파싱 기록 미포함 후보")

    curr_best50 = safe_float(row["curr_best50_rate"]) * 100.0
    curr_sssplus = safe_float(row["curr_sssplus_rate"]) * 100.0
    target_best50 = safe_float(row["target_best50_rate"]) * 100.0
    target_sssplus = safe_float(row["target_sssplus_rate"]) * 100.0

    current_rating = int(safe_float(row["current_rating"]))
    max_rating = int(safe_float(row["max_rating"]))
    rating_gain = int(safe_float(row["rating_gain"]))

    if goal == "reverse_border":
        gap = safe_float(row.get("reverse_border_gap", 0.0))

        reason = (
            f"현재 달성률이 {achievement:.4f}%로, "
            f"100.5%까지 {gap:.4f}% 부족한 역보더 후보입니다. "
            f"기준 범위는 {REVERSE_BORDER_MIN:.4f}% 이상 {REVERSE_BORDER_MAX:.4f}% 미만입니다."
        )
        target = "역보더 재도전 후보"

        return reason, target

    if goal == "rating_up":
        if candidate_type == "best50_existing":
            reason = (
                f"현재 Best 50에 포함된 기존 기록입니다. "
                f"현재 기록은 {achievement:.4f}%이며 곡별 레이팅은 {current_rating}입니다. "
                f"100.5% 기준 최대 레이팅은 {max_rating}로, 아직 {rating_gain}만큼 상승 여지가 있습니다. "
                f"{current_band} 구간의 SSS+ 비율은 {curr_sssplus:.1f}%, "
                f"{target_band} 구간 Best50 등장률은 {target_best50:.1f}%입니다."
            )
            target = "Best 50 기존 기록 개선"

        elif candidate_type == "played_not_best50":
            reason = (
                f"현재 파싱된 records 페이지에는 존재하지만 Best 50에는 포함되지 않은 기록입니다. "
                f"현재 기록은 {achievement:.4f}%이며 곡별 레이팅은 {current_rating}입니다. "
                f"100.5% 기준 최대 레이팅은 {max_rating}로, 개선 시 Best 50 진입 가능성을 검토할 수 있습니다. "
                f"{current_band} 구간 Best50 등장률은 {curr_best50:.1f}%, "
                f"{target_band} 구간 Best50 등장률은 {target_best50:.1f}%입니다."
            )
            target = "Best 50 밖 플레이 기록 개선"

        else:
            reason = (
                f"현재 파싱된 Best 50 및 records 노출 기록에는 없는 후보입니다. "
                f"{current_band} 구간 Best50 등장률은 {curr_best50:.1f}%, SSS+ 비율은 {curr_sssplus:.1f}%이며, "
                f"{target_band} 구간 Best50 등장률은 {target_best50:.1f}%입니다. "
                f"동일/상위 구간에서 검증된 고효율 후보로 볼 수 있습니다."
            )
            target = "현재 파싱 기록 미포함 고효율 후보"

        return reason, target

    if goal == "skill_up":
        reason = (
            f"후보 유형은 '{candidate_label}'입니다. "
            f"{target_band} 구간 유저들의 Best50 등장률이 {target_best50:.1f}%이고, "
            f"SSS+ 비율은 {target_sssplus:.1f}%입니다. "
            f"현재 구간보다 한 단계 위 유저들이 자주 보유한 곡이므로 실력 향상용 도전곡으로 적합합니다."
        )
        target = "상위 레이팅 구간 적응"

        return reason, target

    reason = (
        f"후보 유형은 '{candidate_label}'입니다. "
        f"동일 구간 평균 달성률은 {safe_float(row['curr_avg_achievement']):.4f}%입니다. "
        f"현재 기록은 {achievement:.4f}%이며, "
        f"해당 내부상수 구간의 평균 달성률은 {safe_float(row['curr_level_avg_achievement']):.4f}%입니다. "
        f"동일 레이팅대와 비교해 보완 가치가 있는 후보입니다."
    )
    target = "동일 레이팅대 대비 약점 보완"

    return reason, target


# ------------------------------------------------------------
# Main recommend function
# ------------------------------------------------------------

def recommend(
    req,
    user_records_df: pd.DataFrame | None = None,
    user_rating: int | None = None,
):
    df = load_base_data(user_records_df)
    cohort_stats = load_cohort_stats()
    level_stats = load_level_stats()

    available_bands = []

    if not cohort_stats.empty:
        available_bands = sorted(
            cohort_stats["rating_band"].dropna().unique().tolist(),
            key=parse_band_low,
        )

    estimated_rating = estimate_user_total_rating(df)
    effective_rating = int(user_rating) if user_rating is not None else estimated_rating

    current_band = band_from_rating(effective_rating, available_bands)
    target_band = next_band(current_band, available_bands)

    df = add_cohort_features(
        df=df,
        cohort_stats=cohort_stats,
        level_stats=level_stats,
        current_band=current_band,
        target_band=target_band,
    )

    cutoffs = estimate_best50_cutoffs(df)

    if req.chart_type != "any":
        df = df[df["chart_type"] == req.chart_type]

    df = filter_by_main_level(
        df=df,
        main_level=req.main_level,
        goal=req.goal,
    )

    if req.goal == "rating_up":
        df["recommend_score"] = df.apply(
            lambda row: rating_up_score(row, req, cutoffs),
            axis=1,
        )

        df = df[df["recommend_score"] > 0]

        summary = (
            f"입력 유저 레이팅 {effective_rating} 기준 현재 구간은 {current_band}, 목표 구간은 {target_band}입니다. "
            f"선택한 주력 레벨 {req.main_level} 범위 안에서 추천했습니다."
        )

        sort_columns = [
            "recommend_score",
            "target_best50_rate",
            "curr_best50_rate",
            "target_sssplus_rate",
        ]
        sort_ascending = [False, False, False, False]

    elif req.goal == "reverse_border":
        df["recommend_score"] = df.apply(
            lambda row: reverse_border_score(row, req),
            axis=1,
        )

        df = df[df["recommend_score"] > 0]

        summary = (
            f"역보더 탐색 모드입니다. "
            f"현재 파싱된 플레이 기록 중 {REVERSE_BORDER_MIN:.4f}% 이상 "
            f"{REVERSE_BORDER_MAX:.4f}% 미만인 채보만 추렸습니다. "
            f"100.5%에 가까운 곡을 우선 표시합니다."
        )

        sort_columns = [
            "reverse_border_gap",
            "internal_level",
            "is_best50",
            "current_rating",
        ]
        sort_ascending = [True, False, False, False]

    elif req.goal == "skill_up":
        df["recommend_score"] = df.apply(
            lambda row: skill_up_score(row, req),
            axis=1,
        )

        df = df[df["recommend_score"] > 0]

        summary = (
            f"입력 유저 레이팅 {effective_rating} 기준 목표 구간 {target_band} 유저들의 Best50 등장률이 높은 곡을 중심으로 "
            f"실력 향상용 추천을 생성했습니다. "
            f"선택 주력 레벨은 {req.main_level}입니다."
        )

        sort_columns = [
            "recommend_score",
            "target_best50_rate",
            "curr_best50_rate",
            "target_sssplus_rate",
        ]
        sort_ascending = [False, False, False, False]

    else:
        weak_internal_levels = get_weak_internal_levels(df)

        df["recommend_score"] = df.apply(
            lambda row: weakness_score(row, req, weak_internal_levels),
            axis=1,
        )

        df = df[df["recommend_score"] > 0]

        weak_text = (
            ", ".join([str(x) for x in weak_internal_levels])
            if weak_internal_levels
            else "자동 추정 불가"
        )

        summary = (
            f"입력 유저 레이팅 {effective_rating} 기준 현재 구간은 {current_band}입니다. "
            f"선택한 주력 레벨 {req.main_level} 범위 안에서 약점 보완 후보를 추천했습니다. "
            f"약점 내부상수 후보는 {weak_text}입니다."
        )

        sort_columns = [
            "recommend_score",
            "target_best50_rate",
            "curr_best50_rate",
            "target_sssplus_rate",
        ]
        sort_ascending = [False, False, False, False]

    candidate_pool_count = int(len(df))
    reverse_border_candidate_count = (
        int(df["reverse_border"].sum())
        if "reverse_border" in df.columns
        else 0
    )

    if not df.empty:
        df = df.sort_values(
            sort_columns,
            ascending=sort_ascending,
        ).head(req.top_n)

    recommendations = []

    for idx, (_, row) in enumerate(df.iterrows(), start=1):
        reason, target = make_reason(req.goal, row, current_band, target_band)

        recommendations.append({
            "rank": idx,
            "chart_id": row["chart_id"],
            "title": row["title"],
            "difficulty": row["difficulty"],
            "level": row["level"],
            "internal_level": float(row["internal_level"]),
            "chart_type": row["chart_type"],
            "bpm": int(safe_float(row["bpm"])),
            "recommend_score": float(row["recommend_score"]),
            "candidate_type": row.get("candidate_type", "not_in_parsed_records"),
            "candidate_label": row.get("candidate_label", "현재 파싱 기록 미포함 후보"),
            "played": bool(row.get("played", False)),
            "is_best50": bool(row.get("is_best50", False)),
            "achievement": float(safe_float(row.get("achievement", 0.0))),
            "current_rating": int(safe_int(row.get("current_rating", 0))),
            "max_rating": int(safe_int(row.get("max_rating", 0))),
            "rating_gain": int(safe_int(row.get("rating_gain", 0))),
            "reverse_border": bool(row.get("reverse_border", False)),
            "reverse_border_gap": float(safe_float(row.get("reverse_border_gap", 0.0))),
            "reason": reason,
            "target": target,
            "artist": safe_str(row.get("artist", "")),
            "category": safe_str(row.get("category", "")),
            "version": safe_str(row.get("version", "")),
            "sheet_version": safe_str(row.get("sheet_version", "")),
            "release_date": safe_str(row.get("release_date", "")),
            "image_name": safe_str(row.get("image_name", "")),
            "thumbnail_url": safe_str(row.get("thumbnail_url", "")),
            "display_level": safe_str(row.get("display_level", row.get("level", "")))
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
            "candidate_pool_count": candidate_pool_count,
            "reverse_border_candidate_count": reverse_border_candidate_count,
            "candidate_type_counts": df["candidate_type"].value_counts().to_dict()
            if "candidate_type" in df.columns
            else {},
            "best50_record_count": int(df["is_best50"].sum())
            if "is_best50" in df.columns
            else 0,
            "played_record_count": int(df["played"].sum())
            if "played" in df.columns
            else 0,
        },
    }