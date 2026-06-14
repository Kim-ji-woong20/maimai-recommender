from __future__ import annotations

import math
import re
import sys
import time
import unicodedata
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup


# ------------------------------------------------------------
# Path settings
# ------------------------------------------------------------

CURRENT_FILE = Path(__file__).resolve()

if CURRENT_FILE.parent.name == "tools":
    PROJECT_ROOT = CURRENT_FILE.parents[1]
else:
    PROJECT_ROOT = CURRENT_FILE.parent

BACK_DIR = PROJECT_ROOT / "back"
DATA_DIR = BACK_DIR / "data"

if str(BACK_DIR) not in sys.path:
    sys.path.insert(0, str(BACK_DIR))

from rating_bands import get_ordered_bands, parse_rating_band_low, rating_to_band


PROFILE_URLS_PATH = DATA_DIR / "profile_urls.csv"
CHARTS_PATH = DATA_DIR / "maimai_charts_13_15.csv"

OUT_RAW_BEST50_PATH = DATA_DIR / "raw_user_best50.csv"
OUT_COHORT_STATS_PATH = DATA_DIR / "cohort_chart_stats.csv"
OUT_LEVEL_STATS_PATH = DATA_DIR / "level_distribution_stats.csv"
OUT_FAILED_PATH = DATA_DIR / "cohort_build_failed_profiles.csv"
OUT_UNMATCHED_PATH = DATA_DIR / "cohort_build_unmatched_records.csv"

REQUEST_DELAY_SECONDS = 2.0


# ------------------------------------------------------------
# Rating calculation
# ------------------------------------------------------------

RATING_FACTORS = [
    (100.5, 0.224),  # SSS+
    (100.0, 0.216),  # SSS
    (99.5, 0.211),   # SS+
    (99.0, 0.208),   # SS
    (98.0, 0.203),   # S+
    (97.0, 0.200),   # S
    (94.0, 0.168),   # AAA
    (90.0, 0.152),   # AA
    (80.0, 0.136),   # A
    (0.0, 0.000),
]


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


# ------------------------------------------------------------
# Text / HTML parsing
# ------------------------------------------------------------

def normalize_line(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text))
    text = text.replace("\u200b", "")

    return text.strip()


def normalize_title(text: str) -> str:
    if pd.isna(text):
        return ""

    text = unicodedata.normalize("NFKC", str(text))
    text = text.replace("♥", "♡")
    text = re.sub(r"\s+", "", text)

    return text.lower()


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()

    return response.text


def html_to_visible_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")

    for img in soup.find_all("img"):
        alt = img.get("alt")

        if alt:
            img.replace_with(f"\n{alt}\n")

    text = soup.get_text("\n")
    lines = [normalize_line(line) for line in text.splitlines()]

    return [line for line in lines if line]


def find_rating_section_start(lines: list[str]) -> int | None:
    for i, line in enumerate(lines):
        clean = line.replace("#", "").strip()

        if clean in {"레이팅 대상곡", "Best 50"}:
            return i

    return None


def is_chart_type(line: str) -> bool:
    return line.upper() in {"DX", "STANDARD", "STD"}


def convert_chart_type(line: str) -> str:
    line = line.upper()

    if line == "DX":
        return "dx"

    return "std"


def is_rating_number(line: str) -> bool:
    return bool(re.fullmatch(r"\d{2,4}", line))


def is_stop_header(line: str) -> bool:
    return line in {
        "기록",
        "순회",
        "사진관",
        "히스토리",
        "전체",
        "History",
        "All",
    }


def parse_level_from_fragments(
    lines: list[str],
    start_idx: int,
) -> tuple[float | None, int]:
    """
    Examples:
    14 . 2      -> 14.2
    13 . 8 +    -> 13.8
    15          -> 15.0
    """
    if start_idx >= len(lines):
        return None, start_idx

    first = lines[start_idx]

    if not re.fullmatch(r"\d{1,2}", first):
        return None, start_idx

    level_text = first
    idx = start_idx + 1

    if idx < len(lines) and lines[idx] == ".":
        if idx + 1 < len(lines) and re.fullmatch(r"\d", lines[idx + 1]):
            level_text += "." + lines[idx + 1]
            idx += 2

    if idx < len(lines) and lines[idx] == "+":
        idx += 1

    try:
        return float(level_text), idx
    except ValueError:
        return None, start_idx


def parse_achievement_start(lines: list[str], start_idx: int) -> int | None:
    """
    Example:
    100.6602
    %
    SSS+
    """
    for i in range(start_idx, min(start_idx + 12, len(lines))):
        if re.fullmatch(r"\d{1,3}(?:\.\d+)?", lines[i]):
            if i + 1 < len(lines) and lines[i + 1] == "%":
                return i

    return None


def parse_achievement_from_index(
    lines: list[str],
    achievement_idx: int,
) -> tuple[float, str, int]:
    achievement = float(lines[achievement_idx])
    rank = lines[achievement_idx + 2] if achievement_idx + 2 < len(lines) else ""

    return achievement, rank, achievement_idx + 3


def extract_best50_records_from_lines(lines: list[str]) -> list[dict]:
    start_idx = find_rating_section_start(lines)

    if start_idx is None:
        raise ValueError("rating section not found")

    records = []
    i = start_idx + 1

    section = None

    while i < len(lines):
        line = lines[i]

        if is_stop_header(line):
            break

        if line in {"최신곡", "New Songs"}:
            section = "new"
            i += 1
            continue

        if line in {"구곡", "Old Songs"}:
            section = "old"
            i += 1
            continue

        if not is_chart_type(line):
            i += 1
            continue

        chart_type = convert_chart_type(line)

        try:
            rating_idx = None

            for j in range(i + 1, min(i + 8, len(lines))):
                if is_rating_number(lines[j]):
                    rating_idx = j
                    break

            if rating_idx is None:
                i += 1
                continue

            displayed_rank = "".join(lines[i + 1:rating_idx])
            chart_rating = int(lines[rating_idx])

            internal_level, title_start_idx = parse_level_from_fragments(
                lines,
                rating_idx + 1,
            )

            if internal_level is None:
                i += 1
                continue

            achievement_idx = parse_achievement_start(lines, title_start_idx)

            if achievement_idx is None:
                i += 1
                continue

            title_parts = lines[title_start_idx:achievement_idx]
            title = " ".join(title_parts).strip()

            achievement, rank, end_idx = parse_achievement_from_index(
                lines,
                achievement_idx,
            )

            records.append({
                "title": title,
                "chart_type": chart_type,
                "internal_level": internal_level,
                "achievement": achievement,
                "rank": rank or displayed_rank,
                "chart_rating": chart_rating,
                "best50_section": section or "unknown",
            })

            i = end_idx

        except Exception:
            i += 1

    return records


# ------------------------------------------------------------
# Matching with base chart DB
# ------------------------------------------------------------

def match_chart_ids(
    records: list[dict],
    charts: pd.DataFrame,
) -> tuple[list[dict], list[dict]]:
    charts = charts.copy()
    charts["title_norm"] = charts["title"].apply(normalize_title)

    matched = []
    unmatched = []

    difficulty_priority = {
        "remaster": 5,
        "master": 4,
        "expert": 3,
        "advanced": 2,
        "basic": 1,
    }

    for record in records:
        title_norm = normalize_title(record["title"])
        chart_type = record["chart_type"]
        internal_level = float(record["internal_level"])

        candidates = charts[
            (charts["title_norm"] == title_norm)
            & (charts["chart_type"] == chart_type)
            & ((charts["internal_level"] - internal_level).abs() <= 0.051)
        ].copy()

        if candidates.empty:
            candidates = charts[
                (charts["title_norm"] == title_norm)
                & (charts["chart_type"] == chart_type)
            ].copy()

            if not candidates.empty:
                candidates["level_diff"] = (
                    candidates["internal_level"] - internal_level
                ).abs()
                candidates = candidates[candidates["level_diff"] <= 0.15]

        if candidates.empty:
            candidates = charts[
                (charts["chart_type"] == chart_type)
                & (
                    charts["title_norm"].apply(
                        lambda x: title_norm in x or x in title_norm
                    )
                )
            ].copy()

            if not candidates.empty:
                candidates["level_diff"] = (
                    candidates["internal_level"] - internal_level
                ).abs()
                candidates = candidates[candidates["level_diff"] <= 0.15]

        if candidates.empty:
            unmatched.append(record)
            continue

        candidates["difficulty_priority"] = (
            candidates["difficulty"].map(difficulty_priority).fillna(0)
        )
        candidates["level_diff"] = (
            candidates["internal_level"] - internal_level
        ).abs()

        chosen = candidates.sort_values(
            ["level_diff", "difficulty_priority"],
            ascending=[True, False],
        ).iloc[0]

        matched_record = {
            **record,
            "chart_id": chosen["chart_id"],
            "song_id": chosen["song_id"],
            "matched_title": chosen["title"],
            "difficulty": chosen["difficulty"],
            "level": chosen["level"],
            "base_internal_level": float(chosen["internal_level"]),
            "category": chosen.get("category", ""),
            "song_version": chosen.get("version", chosen.get("song_version", "")),
            "chart_version": chosen.get("sheet_version", chosen.get("chart_version", "")),
            "is_new": bool(chosen.get("is_new", False)),
        }

        matched.append(matched_record)

    return matched, unmatched


# ------------------------------------------------------------
# Stats
# ------------------------------------------------------------

def add_rank_flags(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["is_sss_or_higher"] = df["achievement"] >= 100.0
    df["is_sss_plus"] = df["achievement"] >= 100.5

    return df


def sort_by_rating_band(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "rating_band" not in df.columns:
        return df

    out = df.copy()
    out["_rating_band_low"] = out["rating_band"].apply(parse_rating_band_low)
    out["_rating_band_low"] = out["_rating_band_low"].fillna(999999)

    sort_cols = ["_rating_band_low"]
    ascending = [True]

    if "best50_rate" in out.columns:
        sort_cols += ["best50_rate"]
        ascending += [False]

    if "sss_plus_rate" in out.columns:
        sort_cols += ["sss_plus_rate"]
        ascending += [False]

    if "avg_chart_rating" in out.columns:
        sort_cols += ["avg_chart_rating"]
        ascending += [False]

    out = out.sort_values(sort_cols, ascending=ascending)
    out = out.drop(columns=["_rating_band_low"])

    return out.reset_index(drop=True)


def build_cohort_chart_stats(
    raw_df: pd.DataFrame,
    profile_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    rating_band x chart_id 단위 cohort 통계를 생성한다.

    recommender.py의 extract_band_features()가 찾는 컬럼명을 직접 제공한다.
    """
    raw_df = add_rank_flags(raw_df).copy()

    band_user_counts = (
        profile_df.groupby("rating_band")["profile_id"]
        .nunique()
        .to_dict()
    )

    grouped = raw_df.groupby(["rating_band", "chart_id"], as_index=False)

    stats = grouped.agg(
        record_count=("profile_id", "count"),
        player_count=("profile_id", "nunique"),
        best50_count=("profile_id", "count"),
        avg_achievement=("achievement", "mean"),
        median_achievement=("achievement", "median"),
        sss_rate=("is_sss_or_higher", "mean"),
        sss_plus_rate=("is_sss_plus", "mean"),
        avg_chart_rating=("chart_rating", "mean"),
        max_chart_rating=("chart_rating", "max"),
        title=("title", "first"),
        difficulty=("difficulty", "first"),
        level=("level", "first"),
        internal_level=("internal_level", "first"),
        chart_type=("chart_type", "first"),
        category=("category", "first"),
        is_new=("is_new", "first"),
        best50_section=("best50_section", "first"),
    )

    stats["band_user_count"] = stats["rating_band"].map(band_user_counts).fillna(0).astype(int)
    stats["total_users_in_band"] = stats["band_user_count"]

    stats["best50_rate"] = 0.0
    valid_user_mask = stats["band_user_count"] > 0
    stats.loc[valid_user_mask, "best50_rate"] = (
        stats.loc[valid_user_mask, "player_count"]
        / stats.loc[valid_user_mask, "band_user_count"]
    )

    # recommender.py 호환용 alias
    stats["user_count"] = stats["band_user_count"]
    stats["profile_count"] = stats["band_user_count"]
    stats["best50_user_count"] = stats["best50_count"]
    stats["sssplus_rate"] = stats["sss_plus_rate"]

    numeric_cols = [
        "avg_achievement",
        "median_achievement",
        "sss_rate",
        "sss_plus_rate",
        "sssplus_rate",
        "avg_chart_rating",
        "best50_rate",
    ]

    for col in numeric_cols:
        stats[col] = pd.to_numeric(stats[col], errors="coerce").fillna(0.0).round(4)

    stats = sort_by_rating_band(stats)

    ordered_columns = [
        "rating_band",
        "chart_id",
        "record_count",
        "player_count",
        "best50_count",
        "best50_user_count",
        "band_user_count",
        "user_count",
        "profile_count",
        "total_users_in_band",
        "best50_rate",
        "avg_achievement",
        "median_achievement",
        "sss_rate",
        "sss_plus_rate",
        "sssplus_rate",
        "avg_chart_rating",
        "max_chart_rating",
        "title",
        "difficulty",
        "level",
        "internal_level",
        "chart_type",
        "category",
        "is_new",
        "best50_section",
    ]

    for col in ordered_columns:
        if col not in stats.columns:
            stats[col] = ""

    return stats[ordered_columns]


def build_level_distribution_stats(
    raw_df: pd.DataFrame,
    profile_df: pd.DataFrame,
) -> pd.DataFrame:
    raw_df = add_rank_flags(raw_df).copy()

    raw_df["internal_level_rounded"] = raw_df["internal_level"].round(1)

    band_user_counts = (
        profile_df.groupby("rating_band")["profile_id"]
        .nunique()
        .to_dict()
    )

    grouped = raw_df.groupby(
        ["rating_band", "internal_level_rounded"],
        as_index=False,
    )

    stats = grouped.agg(
        record_count=("profile_id", "count"),
        player_count=("profile_id", "nunique"),
        best50_count=("profile_id", "count"),
        avg_achievement=("achievement", "mean"),
        median_achievement=("achievement", "median"),
        sss_rate=("is_sss_or_higher", "mean"),
        sss_plus_rate=("is_sss_plus", "mean"),
        avg_chart_rating=("chart_rating", "mean"),
    )

    stats = stats.rename(columns={"internal_level_rounded": "internal_level"})

    stats["band_user_count"] = stats["rating_band"].map(band_user_counts).fillna(0).astype(int)
    stats["total_users_in_band"] = stats["band_user_count"]

    stats["coverage_rate"] = 0.0
    valid_user_mask = stats["band_user_count"] > 0
    stats.loc[valid_user_mask, "coverage_rate"] = (
        stats.loc[valid_user_mask, "player_count"]
        / stats.loc[valid_user_mask, "band_user_count"]
    )

    stats["user_count"] = stats["band_user_count"]
    stats["profile_count"] = stats["band_user_count"]
    stats["sssplus_rate"] = stats["sss_plus_rate"]

    numeric_cols = [
        "avg_achievement",
        "median_achievement",
        "sss_rate",
        "sss_plus_rate",
        "sssplus_rate",
        "avg_chart_rating",
        "coverage_rate",
    ]

    for col in numeric_cols:
        stats[col] = pd.to_numeric(stats[col], errors="coerce").fillna(0.0).round(4)

    stats["_rating_band_low"] = stats["rating_band"].apply(parse_rating_band_low)
    stats["_rating_band_low"] = stats["_rating_band_low"].fillna(999999)

    stats = stats.sort_values(
        ["_rating_band_low", "internal_level"],
        ascending=[True, True],
    ).drop(columns=["_rating_band_low"])

    return stats.reset_index(drop=True)


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def load_profile_urls() -> pd.DataFrame:
    if not PROFILE_URLS_PATH.exists():
        raise FileNotFoundError(f"profile_urls.csv not found: {PROFILE_URLS_PATH}")

    df = pd.read_csv(PROFILE_URLS_PATH)

    required_cols = {"profile_id", "profile_url", "rating"}
    missing = required_cols - set(df.columns)

    if missing:
        raise ValueError(f"profile_urls.csv missing columns: {missing}")

    df = df.drop_duplicates(subset=["profile_url"], keep="first").copy()

    df["profile_id"] = df["profile_id"].fillna("").astype(str)
    df["profile_url"] = df["profile_url"].fillna("").astype(str)
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")

    df = df[
        (df["profile_id"].str.len() > 0)
        & (df["profile_url"].str.len() > 0)
        & (df["rating"].notna())
    ].copy()

    df["rating"] = df["rating"].astype(int)

    # 핵심 변경:
    # profile_urls.csv에 기존 500점 rating_band가 있어도 신뢰하지 않고,
    # back/rating_bands.py의 custom band 기준으로 항상 재계산한다.
    df["rating_band"] = df["rating"].apply(rating_to_band)

    df = df[df["rating_band"] != "unknown"].copy()

    return df.reset_index(drop=True)


def print_rating_band_counts(profile_df: pd.DataFrame) -> None:
    available_bands = get_ordered_bands(
        profile_df["rating_band"].dropna().astype(str).unique().tolist()
    )

    counts = profile_df["rating_band"].value_counts().to_dict()

    for band in available_bands:
        print(f"{band}: {counts.get(band, 0)}")


def main():
    print("=== build cohort stats ===")
    print(f"project root: {PROJECT_ROOT}")
    print(f"profile urls: {PROFILE_URLS_PATH}")
    print(f"charts db: {CHARTS_PATH}")

    profile_df = load_profile_urls()
    charts_df = pd.read_csv(CHARTS_PATH)

    charts_df["chart_type"] = charts_df["chart_type"].fillna("").astype(str)
    charts_df["title"] = charts_df["title"].fillna("").astype(str)
    charts_df["internal_level"] = pd.to_numeric(
        charts_df["internal_level"],
        errors="coerce",
    ).fillna(0.0)

    print("\nprofile count by custom rating band:")
    print_rating_band_counts(profile_df)

    all_rows = []
    failed_rows = []
    unmatched_rows = []

    total_profiles = len(profile_df)

    for profile_idx, (_, row) in enumerate(profile_df.iterrows(), start=1):
        profile_id = row["profile_id"]
        profile_url = row["profile_url"]
        rating = int(row["rating"])
        rating_band = row["rating_band"]

        print(f"\n[{profile_idx}/{total_profiles}] parsing {profile_id} ({rating}, {rating_band})")
        print(f"URL: {profile_url}")

        try:
            html = fetch_html(profile_url)
            lines = html_to_visible_lines(html)
            records = extract_best50_records_from_lines(lines)

            if len(records) == 0:
                failed_rows.append({
                    "profile_id": profile_id,
                    "profile_url": profile_url,
                    "rating": rating,
                    "rating_band": rating_band,
                    "reason": "no_best50_records",
                })
                print("[failed] no best50 records")
                time.sleep(REQUEST_DELAY_SECONDS)
                continue

            matched, unmatched = match_chart_ids(records, charts_df)

            if len(unmatched) > 0:
                print(f"[warn] unmatched records: {len(unmatched)}")

                for rec in unmatched:
                    unmatched_rows.append({
                        "profile_id": profile_id,
                        "profile_url": profile_url,
                        "rating": rating,
                        "rating_band": rating_band,
                        "title": rec.get("title"),
                        "chart_type": rec.get("chart_type"),
                        "internal_level": rec.get("internal_level"),
                        "achievement": rec.get("achievement"),
                        "rank": rec.get("rank"),
                        "chart_rating": rec.get("chart_rating"),
                        "best50_section": rec.get("best50_section"),
                    })

            for rec in matched:
                chart_rating = int(rec["chart_rating"])

                calculated_rating = calculate_chart_rating(
                    rec["base_internal_level"],
                    rec["achievement"],
                )

                all_rows.append({
                    "profile_id": profile_id,
                    "profile_url": profile_url,
                    "rating": rating,
                    "rating_band": rating_band,
                    "chart_id": rec["chart_id"],
                    "song_id": rec["song_id"],
                    "title": rec["matched_title"],
                    "displayed_title": rec["title"],
                    "difficulty": rec["difficulty"],
                    "level": rec["level"],
                    "internal_level": rec["base_internal_level"],
                    "chart_type": rec["chart_type"],
                    "achievement": rec["achievement"],
                    "rank": rec["rank"],
                    "chart_rating": chart_rating,
                    "calculated_chart_rating": calculated_rating,
                    "best50_section": rec["best50_section"],
                    "category": rec["category"],
                    "song_version": rec["song_version"],
                    "chart_version": rec["chart_version"],
                    "is_new": rec["is_new"],
                    "is_best50": True,
                })

            print(
                f"[ok] extracted={len(records)}, "
                f"matched={len(matched)}, unmatched={len(unmatched)}"
            )

        except Exception as e:
            failed_rows.append({
                "profile_id": profile_id,
                "profile_url": profile_url,
                "rating": rating,
                "rating_band": rating_band,
                "reason": str(e),
            })
            print(f"[failed] {e}")

        time.sleep(REQUEST_DELAY_SECONDS)

    raw_df = pd.DataFrame(all_rows)

    if raw_df.empty:
        print("\nNo raw best50 rows were created. Stop.")

        failed_df = pd.DataFrame(failed_rows)
        failed_df.to_csv(OUT_FAILED_PATH, index=False, encoding="utf-8-sig")

        unmatched_df = pd.DataFrame(unmatched_rows)
        unmatched_df.to_csv(OUT_UNMATCHED_PATH, index=False, encoding="utf-8-sig")

        return

    raw_df.to_csv(OUT_RAW_BEST50_PATH, index=False, encoding="utf-8-sig")

    cohort_stats_df = build_cohort_chart_stats(raw_df, profile_df)
    cohort_stats_df.to_csv(OUT_COHORT_STATS_PATH, index=False, encoding="utf-8-sig")

    level_stats_df = build_level_distribution_stats(raw_df, profile_df)
    level_stats_df.to_csv(OUT_LEVEL_STATS_PATH, index=False, encoding="utf-8-sig")

    failed_df = pd.DataFrame(failed_rows)
    failed_df.to_csv(OUT_FAILED_PATH, index=False, encoding="utf-8-sig")

    unmatched_df = pd.DataFrame(unmatched_rows)
    unmatched_df.to_csv(OUT_UNMATCHED_PATH, index=False, encoding="utf-8-sig")

    print("\n=== result ===")
    print(f"profiles: {total_profiles}")
    print(f"raw best50 rows: {len(raw_df)}")
    print(f"failed profiles: {len(failed_df)}")
    print(f"unmatched records: {len(unmatched_df)}")

    print(f"\nsaved: {OUT_RAW_BEST50_PATH}")
    print(f"saved: {OUT_COHORT_STATS_PATH}")
    print(f"saved: {OUT_LEVEL_STATS_PATH}")
    print(f"saved: {OUT_FAILED_PATH}")
    print(f"saved: {OUT_UNMATCHED_PATH}")

    print("\nraw rows by custom rating band:")
    print(raw_df["rating_band"].value_counts())

    print("\ncohort stats columns:")
    print(list(cohort_stats_df.columns))

    print("\ncohort stats preview:")
    print(cohort_stats_df.head(10))

    print("\nlevel distribution stats preview:")
    print(level_stats_df.head(10))


if __name__ == "__main__":
    main()