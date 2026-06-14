from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

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
DEBUG_DIR = DATA_DIR / "debug_profile_rating"

if str(BACK_DIR) not in sys.path:
    sys.path.insert(0, str(BACK_DIR))

from rating_bands import rating_to_band


PROFILE_URLS_PATH = DATA_DIR / "profile_urls.csv"
FAILED_PATH = DATA_DIR / "collect_maishift_profiles_failed.csv"

BASE_URL = "https://maimai.shiftpsh.com"
MAX_THEORETICAL_RATING = 16740

DEFAULT_REQUEST_DELAY_SECONDS = 2.0
DEFAULT_TIMEOUT_SECONDS = 20


# 이미지로 확인한 주변 유저.
# --add-known-profiles 옵션을 줄 때 profile_urls.csv에 추가/갱신된다.
KNOWN_PROFILES = [
    {
        "profile_id": "tuna1030",
        "profile_url": "https://maimai.shiftpsh.com/profile/tuna1030/home",
        "rating": 16615,
        "source_url": "manual_best50_image",
    },
    {
        "profile_id": "hapum",
        "profile_url": "https://maimai.shiftpsh.com/profile/hapum/home",
        "rating": 16006,
        "source_url": "manual_best50_image",
    },
    {
        "profile_id": "nanheam_1022",
        "profile_url": "https://maimai.shiftpsh.com/profile/nanheam_1022/home",
        "rating": 15664,
        "source_url": "manual_best50_image",
    },
    {
        "profile_id": "none",
        "profile_url": "https://maimai.shiftpsh.com/profile/none/home",
        "rating": 16246,
        "source_url": "manual_best50_image",
    },
    {
        "profile_id": "kong3171",
        "profile_url": "https://maimai.shiftpsh.com/profile/kong3171/home",
        "rating": 15432,
        "source_url": "manual_best50_image",
    },
]


# ------------------------------------------------------------
# Basic helpers
# ------------------------------------------------------------

def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_line(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text))
    text = text.replace("\u200b", "")

    return text.strip()


def extract_profile_id(url: str) -> str | None:
    if not isinstance(url, str):
        return None

    match = re.search(
        r"maimai\.shiftpsh\.com/profile/([A-Za-z0-9_\-]+)",
        url,
        flags=re.IGNORECASE,
    )

    if match:
        return match.group(1)

    match = re.search(
        r"/profile/([A-Za-z0-9_\-]+)",
        url,
        flags=re.IGNORECASE,
    )

    if match:
        return match.group(1)

    text = str(url).strip().strip("/")

    if re.fullmatch(r"[A-Za-z0-9_\-]+", text):
        return text

    return None


def normalize_profile_url(value: str) -> str:
    profile_id = extract_profile_id(value)

    if not profile_id:
        return ""

    return f"{BASE_URL}/profile/{profile_id}/home"


def is_valid_profile_url(url: str) -> bool:
    try:
        parsed = urlparse(str(url))
        return (
            parsed.scheme in {"http", "https"}
            and parsed.netloc.lower() == "maimai.shiftpsh.com"
            and "/profile/" in parsed.path
        )
    except Exception:
        return False


def coerce_rating(value) -> int | None:
    try:
        if pd.isna(value):
            return None

        number = int(float(value))

        if number <= 0:
            return None

        return number

    except Exception:
        return None


def is_plausible_rating(value: int) -> bool:
    # maimai 현재 프로젝트 기준. 낮은 rating도 CSV에는 보존하되,
    # 말이 안 되는 값은 rating 파싱 실패로 본다.
    return 10000 <= int(value) <= MAX_THEORETICAL_RATING


# ------------------------------------------------------------
# HTML parsing
# ------------------------------------------------------------

def fetch_html(url: str, timeout: int, max_retries: int = 4) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }

    retry_status_codes = {429, 500, 502, 503, 504}
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=timeout,
            )

            if response.status_code in retry_status_codes:
                wait_seconds = min(60, 5 * attempt * attempt)
                last_error = (
                    f"{response.status_code} {response.reason}; "
                    f"retry {attempt}/{max_retries} after {wait_seconds}s"
                )

                print(f"  - temporary server error: {last_error}", flush=True)
                time.sleep(wait_seconds)
                continue

            response.raise_for_status()
            return response.text

        except requests.RequestException as e:
            wait_seconds = min(60, 5 * attempt * attempt)
            last_error = str(e)

            if attempt < max_retries:
                print(
                    f"  - request failed: {last_error}; "
                    f"retry {attempt}/{max_retries} after {wait_seconds}s",
                    flush=True,
                )
                time.sleep(wait_seconds)
                continue

            raise

    raise RuntimeError(f"request failed after retries: {last_error}")


def html_to_visible_lines(html_text: str) -> list[str]:
    soup = BeautifulSoup(html_text, "html.parser")

    for img in soup.find_all("img"):
        alt = img.get("alt")

        if alt:
            img.replace_with(f"\n{alt}\n")

    text = soup.get_text("\n")
    lines = [normalize_line(line) for line in text.splitlines()]

    return [line for line in lines if line]


def parse_rating_near_play_count(lines: list[str]) -> int | None:
    """
    maishift profile HTML에서 rating은 보통 '플레이 카운트' 직전의
    한 자리 숫자들이 분리된 형태로 들어온다.

    예:
    1
    6
    0
    0
    6
    플레이 카운트

    또는:
    16,006
    플레이 카운트
    """
    play_count_markers = {"플레이 카운트", "Play Count"}

    marker_indices = [
        idx
        for idx, line in enumerate(lines)
        if line in play_count_markers
    ]

    for marker_idx in marker_indices:
        # 1) 직전 몇 줄 안에 16,006 또는 16006 형태가 있는 경우
        for i in range(marker_idx - 1, max(-1, marker_idx - 12), -1):
            line = lines[i]

            if re.fullmatch(r"\d{1,2},\d{3}", line):
                rating = int(line.replace(",", ""))

                if is_plausible_rating(rating):
                    return rating

            if re.fullmatch(r"\d{5}", line):
                rating = int(line)

                if is_plausible_rating(rating):
                    return rating

        # 2) 한 자리 숫자들이 분리되어 있는 경우
        digits = []
        i = marker_idx - 1

        while i >= 0 and len(digits) < 6:
            line = lines[i]

            if re.fullmatch(r"\d", line):
                digits.append(line)
                i -= 1
                continue

            # rating 블록 바로 앞에서 끊겼다고 본다.
            break

        digits.reverse()

        if digits:
            rating_text = "".join(digits)

            if re.fullmatch(r"\d{5}", rating_text):
                rating = int(rating_text)

                if is_plausible_rating(rating):
                    return rating

    return None


def parse_rating_from_html(html_text: str) -> int | None:
    lines = html_to_visible_lines(html_text)

    rating = parse_rating_near_play_count(lines)

    if rating is not None:
        return rating

    return None


def parse_rating_from_profile(profile_url: str, timeout: int) -> int | None:
    html_text = fetch_html(profile_url, timeout=timeout)
    lines = html_to_visible_lines(html_text)

    rating = parse_rating_near_play_count(lines)

    if rating is not None:
        return rating

    profile_id = extract_profile_id(profile_url) or "unknown"
    save_rating_parse_debug(
        profile_id=profile_id,
        profile_url=profile_url,
        html_text=html_text,
        lines=lines,
        reason="rating_parse_failed",
    )

    return None

def save_rating_parse_debug(
    profile_id: str,
    profile_url: str,
    html_text: str,
    lines: list[str],
    reason: str,
) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    safe_profile_id = re.sub(r"[^A-Za-z0-9_\-]+", "_", profile_id)

    html_path = DEBUG_DIR / f"{safe_profile_id}.html"
    lines_path = DEBUG_DIR / f"{safe_profile_id}_lines.txt"
    meta_path = DEBUG_DIR / f"{safe_profile_id}_meta.txt"

    html_path.write_text(html_text, encoding="utf-8")

    with open(lines_path, "w", encoding="utf-8") as f:
        for idx, line in enumerate(lines):
            f.write(f"{idx:04d}\t{line}\n")

    meta_path.write_text(
        f"profile_id: {profile_id}\n"
        f"profile_url: {profile_url}\n"
        f"reason: {reason}\n"
        f"saved_at: {now_text()}\n",
        encoding="utf-8",
    )

# ------------------------------------------------------------
# CSV load/save
# ------------------------------------------------------------

def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    base_columns = [
        "profile_id",
        "profile_url",
        "source_url",
        "first_seen_at",
        "last_seen_at",
        "rating",
        "rating_band",
        "collected_at",
        "rating_collected_at",
        "rating_collect_status",
        "rating_collect_error",
    ]

    for col in base_columns:
        if col not in df.columns:
            df[col] = ""

    # pandas 2.x dtype 충돌 방지:
    # CSV에서 빈 컬럼은 float64로 추론될 수 있으므로,
    # 상태/에러/URL/시각 컬럼은 명시적으로 문자열(object) 컬럼으로 고정한다.
    text_columns = [
        "profile_id",
        "profile_url",
        "source_url",
        "first_seen_at",
        "last_seen_at",
        "rating_band",
        "collected_at",
        "rating_collected_at",
        "rating_collect_status",
        "rating_collect_error",
    ]

    for col in text_columns:
        df[col] = df[col].fillna("").astype("object")

    # rating만 숫자 컬럼으로 유지한다.
    # 빈 문자열은 NaN으로 정리해서 이후 coerce_rating / normalize_rating_columns와 충돌하지 않게 한다.
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")

    return df


def load_profile_urls() -> pd.DataFrame:
    if not PROFILE_URLS_PATH.exists():
        return pd.DataFrame(
            columns=[
                "profile_id",
                "profile_url",
                "source_url",
                "first_seen_at",
                "last_seen_at",
                "rating",
                "rating_band",
                "collected_at",
                "rating_collected_at",
                "rating_collect_status",
                "rating_collect_error",
            ]
        )

    df = pd.read_csv(PROFILE_URLS_PATH)
    df = ensure_columns(df)

    df["profile_id"] = df["profile_id"].fillna("").astype(str)
    df["profile_url"] = df["profile_url"].fillna("").astype(str)

    missing_id_mask = df["profile_id"].str.len() == 0
    df.loc[missing_id_mask, "profile_id"] = df.loc[
        missing_id_mask,
        "profile_url",
    ].apply(lambda url: extract_profile_id(url) or "")

    missing_url_mask = df["profile_url"].str.len() == 0
    df.loc[missing_url_mask, "profile_url"] = df.loc[
        missing_url_mask,
        "profile_id",
    ].apply(normalize_profile_url)

    df["profile_url"] = df["profile_url"].apply(normalize_profile_url)

    df = df[
        (df["profile_id"].astype(str).str.len() > 0)
        & (df["profile_url"].astype(str).str.len() > 0)
    ].copy()

    # 중복 profile_id는 마지막 행을 신뢰한다.
    # 수동 추가/갱신 row가 뒤에 붙는 경우를 고려한 정책이다.
    df = df.drop_duplicates(
        subset=["profile_id"],
        keep="last",
    ).reset_index(drop=True)

    return df


def normalize_rating_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    ratings = pd.to_numeric(df["rating"], errors="coerce")

    df["rating"] = ratings.astype("Int64")

    df["rating_band"] = df["rating"].apply(
        lambda value: rating_to_band(int(value)) if pd.notna(value) else ""
    )

    return df


def save_profile_urls(df: pd.DataFrame) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    df = ensure_columns(df)
    df = normalize_rating_columns(df)

    preferred_columns = [
        "profile_id",
        "profile_url",
        "source_url",
        "first_seen_at",
        "last_seen_at",
        "rating",
        "rating_band",
        "collected_at",
        "rating_collected_at",
        "rating_collect_status",
        "rating_collect_error",
    ]

    extra_columns = [
        col
        for col in df.columns
        if col not in preferred_columns
    ]

    df = df[preferred_columns + extra_columns]

    df.to_csv(
        PROFILE_URLS_PATH,
        index=False,
        encoding="utf-8-sig",
        quoting=csv.QUOTE_MINIMAL,
    )


def save_failed_rows(failed_rows: list[dict]) -> None:
    failed_df = pd.DataFrame(failed_rows)

    failed_df.to_csv(
        FAILED_PATH,
        index=False,
        encoding="utf-8-sig",
    )


# ------------------------------------------------------------
# Manual known profiles
# ------------------------------------------------------------

def add_known_profiles(df: pd.DataFrame) -> pd.DataFrame:
    now = now_text()
    df = ensure_columns(df)

    rows = []

    for profile in KNOWN_PROFILES:
        rating = int(profile["rating"])

        rows.append({
            "profile_id": profile["profile_id"],
            "profile_url": normalize_profile_url(profile["profile_url"]),
            "source_url": profile.get("source_url", "manual"),
            "first_seen_at": now,
            "last_seen_at": now,
            "rating": rating,
            "rating_band": rating_to_band(rating),
            "collected_at": now,
            "rating_collected_at": now,
            "rating_collect_status": "manual_known_profile",
            "rating_collect_error": "",
        })

    add_df = pd.DataFrame(rows)
    merged = pd.concat([df, add_df], ignore_index=True)

    merged["profile_id"] = merged["profile_id"].fillna("").astype(str)
    merged["profile_url"] = merged["profile_url"].fillna("").astype(str)

    merged = merged[merged["profile_id"].str.len() > 0].copy()
    merged["profile_url"] = merged["profile_url"].apply(normalize_profile_url)

    merged = merged.drop_duplicates(
        subset=["profile_id"],
        keep="last",
    ).reset_index(drop=True)

    return merged


# ------------------------------------------------------------
# Collection logic
# ------------------------------------------------------------

def should_collect_row(row: pd.Series, refresh: bool, missing_only: bool) -> bool:
    current_rating = coerce_rating(row.get("rating"))

    if refresh:
        return True

    if missing_only:
        return current_rating is None

    return current_rating is None


def collect_ratings(
    df: pd.DataFrame,
    refresh: bool,
    missing_only: bool,
    request_delay: float,
    timeout: int,
    max_profiles: int | None,
    profile_id_filter: set[str] | None,
) -> tuple[pd.DataFrame, list[dict], dict]:
    df = ensure_columns(df).copy()

    total_rows = len(df)
    processed_count = 0
    updated_count = 0
    skipped_count = 0
    failed_count = 0

    failed_rows = []

    for idx, row in df.iterrows():
        profile_id = str(row.get("profile_id", "")).strip()
        profile_url = normalize_profile_url(str(row.get("profile_url", "")))

        if not profile_id or not profile_url:
            skipped_count += 1
            continue

        if profile_id_filter is not None and profile_id not in profile_id_filter:
            skipped_count += 1
            continue

        # rating_band는 이미 rating이 있으면 항상 새 custom band 기준으로 갱신한다.
        current_rating = coerce_rating(row.get("rating"))

        if current_rating is not None:
            df.at[idx, "rating_band"] = rating_to_band(current_rating)

        if not should_collect_row(row, refresh=refresh, missing_only=missing_only):
            df.at[idx, "rating_collect_status"] = "skipped_existing_rating"
            skipped_count += 1
            continue

        if max_profiles is not None and processed_count >= max_profiles:
            skipped_count += 1
            continue

        processed_count += 1

        print(
            f"[{processed_count}] fetching {profile_id}: {profile_url}",
            flush=True,
        )

        try:
            rating = parse_rating_from_profile(
                profile_url=profile_url,
                timeout=timeout,
            )

            if rating is None:
                failed_count += 1

                message = "rating_parse_failed"

                df.at[idx, "rating_collect_status"] = "failed"
                df.at[idx, "rating_collect_error"] = message

                failed_rows.append({
                    "profile_id": profile_id,
                    "profile_url": profile_url,
                    "reason": message,
                    "collected_at": now_text(),
                })

                print(f"  - failed: {message}", flush=True)

            else:
                rating = int(rating)
                band = rating_to_band(rating)

                df.at[idx, "profile_url"] = profile_url
                df.at[idx, "rating"] = rating
                df.at[idx, "rating_band"] = band
                df.at[idx, "collected_at"] = now_text()
                df.at[idx, "rating_collected_at"] = now_text()
                df.at[idx, "rating_collect_status"] = "ok"
                df.at[idx, "rating_collect_error"] = ""

                updated_count += 1

                print(f"  - ok: rating={rating}, band={band}", flush=True)

        except Exception as e:
            failed_count += 1

            message = str(e)

            df.at[idx, "rating_collect_status"] = "failed"
            df.at[idx, "rating_collect_error"] = message

            failed_rows.append({
                "profile_id": profile_id,
                "profile_url": profile_url,
                "reason": message,
                "collected_at": now_text(),
            })

            print(f"  - error: {message}", flush=True)

        if request_delay > 0:
            time.sleep(request_delay)

    summary = {
        "total_rows": total_rows,
        "processed_count": processed_count,
        "updated_count": updated_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
    }

    return df, failed_rows, summary


def print_summary(df: pd.DataFrame, title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)

    df = ensure_columns(df)
    ratings = pd.to_numeric(df["rating"], errors="coerce")

    print(f"total profiles: {len(df)}")
    print(f"rating filled: {int(ratings.notna().sum())}")
    print(f"rating empty: {int(ratings.isna().sum())}")

    if ratings.notna().sum() > 0:
        tmp = df.copy()
        tmp["rating"] = ratings
        tmp["rating_band"] = tmp["rating"].apply(
            lambda value: rating_to_band(int(value)) if pd.notna(value) else ""
        )

        print("\nrating band distribution:")
        print(tmp["rating_band"].value_counts().sort_index().to_string())

        print("\ntop 20 ratings:")
        print(
            tmp[
                tmp["rating"].notna()
            ][
                ["profile_id", "rating", "rating_band", "profile_url"]
            ]
            .sort_values("rating", ascending=False)
            .head(20)
            .to_string(index=False)
        )


# ------------------------------------------------------------
# CLI
# ------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fill or refresh maishift profile ratings in back/data/profile_urls.csv. "
            "This script does not discover new URLs; it enriches existing profile URLs."
        )
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh ratings for all profiles, not only empty rating rows.",
    )

    parser.add_argument(
        "--missing-only",
        action="store_true",
        default=True,
        help="Collect only rows whose rating is empty. This is the default.",
    )

    parser.add_argument(
        "--add-known-profiles",
        action="store_true",
        help="Add/update the five manually confirmed profiles from the Best50 images.",
    )

    parser.add_argument(
        "--profile-id",
        action="append",
        default=[],
        help="Only collect specific profile_id. Can be used multiple times.",
    )

    parser.add_argument(
        "--max-profiles",
        type=int,
        default=None,
        help="Maximum number of profiles to fetch in this run.",
    )

    parser.add_argument(
        "--request-delay",
        type=float,
        default=DEFAULT_REQUEST_DELAY_SECONDS,
        help="Delay seconds between profile requests.",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout seconds.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write profile_urls.csv or failed CSV.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print("========== COLLECT MAISHIFT PROFILE RATINGS ==========")
    print("Project root:", PROJECT_ROOT)
    print("Profile URL CSV:", PROFILE_URLS_PATH)
    print("Failed CSV:", FAILED_PATH)
    print("Started at:", now_text())

    df = load_profile_urls()

    print_summary(df, "BEFORE")

    if args.add_known_profiles:
        df = add_known_profiles(df)
        print("\nmanual known profiles were added/updated.")

    profile_id_filter = (
        set(str(value).strip() for value in args.profile_id if str(value).strip())
        if args.profile_id
        else None
    )

    df, failed_rows, summary = collect_ratings(
        df=df,
        refresh=args.refresh,
        missing_only=args.missing_only,
        request_delay=args.request_delay,
        timeout=args.timeout,
        max_profiles=args.max_profiles,
        profile_id_filter=profile_id_filter,
    )

    df = normalize_rating_columns(df)

    print_summary(df, "AFTER")

    print("\nrun summary:")
    for key, value in summary.items():
        print(f"- {key}: {value}")

    print(f"- failed rows: {len(failed_rows)}")

    if args.dry_run:
        print("\ndry-run mode. No files were written.")
    else:
        save_profile_urls(df)
        save_failed_rows(failed_rows)

        print(f"\nsaved: {PROFILE_URLS_PATH}")
        print(f"saved: {FAILED_PATH}")

    print("Finished at:", now_text())


if __name__ == "__main__":
    main()