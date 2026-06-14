from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from maishift_parser import parse_maishift_profile_to_records
from rating_bands import rating_to_band
from recommender import USER_RECORD_COLUMNS, load_charts, recommend
from schemas import ProfileUrlRecommendRequest, RecommendRequest


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PROFILE_URLS_PATH = DATA_DIR / "profile_urls.csv"
RAW_USER_BEST50_PATH = DATA_DIR / "raw_user_best50.csv"
RAW_USER_RECORDS_PATH = DATA_DIR / "raw_user_records.csv"
LOCAL_USER_RECORDS_MIN_RECORD_COUNT = 30


PROFILE_CACHE_TTL_SECONDS = int(os.getenv("PROFILE_CACHE_TTL_SECONDS", "3600"))
PROFILE_CACHE_MIN_EXTRACTED_COUNT = int(os.getenv("PROFILE_CACHE_MIN_EXTRACTED_COUNT", "100"))
PROFILE_CACHE_MIN_MATCHED_COUNT = int(os.getenv("PROFILE_CACHE_MIN_MATCHED_COUNT", "50"))
LOCAL_PROFILE_CACHE_MIN_RECORD_COUNT = int(os.getenv("LOCAL_PROFILE_CACHE_MIN_RECORD_COUNT", "30"))

profile_parse_cache: dict[str, dict[str, Any]] = {}

charts = load_charts()

app = FastAPI(
    title="maimai DX Recommender API",
    description=(
        "maishift 공개 프로필 기록과 유사 레이팅대 cohort 통계를 활용한 "
        "maimai DX 고레벨 채보 추천 API"
    ),
    version="0.5.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------
# Generic helpers
# ------------------------------------------------------------

def get_cache_age_seconds(created_at: float) -> int:
    return max(0, int(time.time() - created_at))


def safe_int(value: Any, default: int | None = 0) -> int | None:
    try:
        if value is None or value == "":
            return default

        if pd.isna(value):
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
    
def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default

        if pd.isna(value):
            return default

        return float(value)

    except Exception:
        return default

def normalize_bool_for_main(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return False

    if isinstance(value, (int, float)):
        try:
            if pd.isna(value):
                return False
        except Exception:
            pass
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


def count_best50_records_for_main(df: pd.DataFrame | None) -> int:
    if df is None or df.empty or "is_best50" not in df.columns:
        return 0

    return int(df["is_best50"].apply(normalize_bool_for_main).sum())


# ------------------------------------------------------------
# Profile URL / ID helpers
# ------------------------------------------------------------

def extract_profile_id_from_url(profile_url: str) -> str:
    """
    maishift URL에서 profile_id를 추출한다.

    예:
    https://maimai.shiftpsh.com/profile/hapum/home
    -> hapum
    """
    try:
        text = str(profile_url).strip()

        match = re.search(
            r"maimai\.shiftpsh\.com/profile/([A-Za-z0-9_\-]+)",
            text,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(1)

        match = re.search(
            r"/profile/([A-Za-z0-9_\-]+)",
            text,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(1)

        return ""

    except Exception:
        return ""


def normalize_profile_url(profile_url: str) -> str:
    profile_id = extract_profile_id_from_url(profile_url)

    if profile_id:
        return f"https://maimai.shiftpsh.com/profile/{profile_id}/home"

    return str(profile_url).strip()

def now_text_for_profile_db() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_rating_for_profile_db(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None

        if pd.isna(value):
            return None

        rating = int(float(value))

        if rating <= 0:
            return None

        return rating

    except Exception:
        return None


def upsert_profile_urls_csv_from_live_parse(
    profile_url: str,
    profile_info: dict[str, Any],
) -> dict[str, Any]:
    """
    live maishift 파싱에 성공한 프로필을 profile_urls.csv에 추가/갱신한다.

    주의:
    - rating 같은 숫자 컬럼에는 빈 문자열을 넣지 않는다.
    - CSV 업데이트 실패가 추천 API 전체 실패로 이어지지 않게 호출부에서 보호한다.
    """
    profile_id = safe_str(profile_info.get("profile_id", ""), "").strip()

    if not profile_id:
        profile_id = extract_profile_id_from_url(profile_url)

    normalized_url = normalize_profile_url(profile_url)

    if not profile_id:
        return {
            "updated": False,
            "action": "skipped",
            "reason": "missing profile_id",
            "profile_id": "",
            "profile_url": normalized_url,
        }

    rating = parse_rating_for_profile_db(profile_info.get("rating"))
    rating_band = rating_to_band(rating) if rating is not None else ""

    now_text = now_text_for_profile_db()

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

    if PROFILE_URLS_PATH.exists():
        try:
            df = pd.read_csv(PROFILE_URLS_PATH)
        except Exception:
            df = pd.DataFrame(columns=base_columns)
    else:
        df = pd.DataFrame(columns=base_columns)

    for col in base_columns:
        if col not in df.columns:
            df[col] = None

    # pandas dtype 충돌 방지:
    # profile_urls.csv는 관리용 CSV이므로 문자열/nullable object로 다룬다.
    object_columns = [
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

    for col in object_columns:
        df[col] = df[col].astype("object")

    # rating은 숫자형으로 유지하되, 빈 문자열은 NaN으로 정리한다.
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")

    df["profile_id"] = df["profile_id"].fillna("").astype(str)
    df["profile_url"] = df["profile_url"].fillna("").astype(str)

    lower_profile_id = profile_id.lower()
    mask = df["profile_id"].astype(str).str.lower() == lower_profile_id

    action = "updated" if mask.any() else "inserted"

    common_values = {
        "profile_id": profile_id,
        "profile_url": normalized_url,
        "source_url": "web_input_live_parse",
        "last_seen_at": now_text,
        "collected_at": now_text,
        "rating_collect_error": "",
    }

    if rating is not None:
        common_values.update(
            {
                "rating": int(rating),
                "rating_band": rating_band,
                "rating_collected_at": now_text,
                "rating_collect_status": "live_parsed",
            }
        )
    else:
        common_values.update(
            {
                "rating_band": "",
                "rating_collected_at": "",
                "rating_collect_status": "live_parsed_no_rating",
            }
        )

    if mask.any():
        idx = df[mask].index[-1]

        if not safe_str(df.at[idx, "first_seen_at"], ""):
            df.at[idx, "first_seen_at"] = now_text

        for col, value in common_values.items():
            # rating이 None인 경우 기존 rating은 지우지 않는다.
            if col == "rating" and rating is None:
                continue

            df.at[idx, col] = value

    else:
        new_row = {col: None for col in base_columns}
        new_row.update(common_values)
        new_row["first_seen_at"] = now_text

        # rating이 없으면 None으로 둔다. 절대 "" 넣지 않음.
        if rating is None:
            new_row["rating"] = None

        df = pd.concat(
            [df, pd.DataFrame([new_row])],
            ignore_index=True,
        )

    # 저장 전 rating 다시 numeric 정리
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")

    PROFILE_URLS_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(PROFILE_URLS_PATH, index=False, encoding="utf-8-sig")

    return {
        "updated": True,
        "action": action,
        "profile_id": profile_id,
        "profile_url": normalized_url,
        "rating": rating,
        "rating_band": rating_band,
        "path": str(PROFILE_URLS_PATH),
    }

def upsert_raw_user_best50_csv_from_live_records(
    profile_url: str,
    profile_info: dict[str, Any],
    user_records_df: pd.DataFrame,
) -> dict[str, Any]:
    """
    live maishift 파싱 결과에서 Best50 records를 raw_user_best50.csv에 추가/갱신한다.

    원칙:
    - Best50이 50개 완전히 확보된 경우에만 저장한다.
    - 48개, 49개 같은 partial Best50은 저장하지 않는다.
      이유: 이후 local_csv_cache가 불완전한 Best50을 안정 데이터로 오인할 수 있기 때문.
    - 같은 profile_id가 이미 있으면 기존 row를 제거하고 새 Best50 50개로 교체한다.
    """
    profile_id = safe_str(profile_info.get("profile_id", ""), "").strip()

    if not profile_id:
        profile_id = extract_profile_id_from_url(profile_url)

    normalized_url = normalize_profile_url(profile_url)

    if not profile_id:
        return {
            "updated": False,
            "action": "skipped",
            "reason": "missing profile_id",
            "profile_id": "",
            "profile_url": normalized_url,
            "path": str(RAW_USER_BEST50_PATH),
        }

    if user_records_df is None or user_records_df.empty:
        return {
            "updated": False,
            "action": "skipped",
            "reason": "empty user_records_df",
            "profile_id": profile_id,
            "profile_url": normalized_url,
            "path": str(RAW_USER_BEST50_PATH),
        }

    records = ensure_user_record_columns_for_main(user_records_df)

    best50 = records[
        records["is_best50"].apply(normalize_bool_for_main)
    ].copy()

    best50 = best50.drop_duplicates(
        subset=["chart_id"],
        keep="first",
    ).reset_index(drop=True)

    best50_count = int(len(best50))

    if best50_count < 50:
        return {
            "updated": False,
            "action": "skipped",
            "reason": f"incomplete best50 count: {best50_count}",
            "profile_id": profile_id,
            "profile_url": normalized_url,
            "best50_count": best50_count,
            "required_best50_count": 50,
            "path": str(RAW_USER_BEST50_PATH),
        }

    # 50개를 초과하면 best50_order 기준으로 50개만 유지한다.
    best50["best50_order"] = pd.to_numeric(
        best50["best50_order"],
        errors="coerce",
    )

    best50 = best50.sort_values(
        by=["best50_section", "best50_order", "chart_rating"],
        ascending=[True, True, False],
        na_position="last",
    ).head(50).copy()

    rating = parse_rating_for_profile_db(profile_info.get("rating"))
    rating_band = rating_to_band(rating) if rating is not None else ""

    now_text = now_text_for_profile_db()

    metadata_values = {
        "profile_id": profile_id,
        "profile_url": normalized_url,
        "rating": rating,
        "rating_band": rating_band,
        "cached_at": now_text,
        "cache_source": "web_input_live_parse",
    }

    for col, value in metadata_values.items():
        best50[col] = value

    # raw_user_best50.csv에 최소한 유지할 컬럼들
    required_columns = [
        "profile_id",
        "profile_url",
        "rating",
        "rating_band",
        "cached_at",
        "cache_source",
    ] + USER_RECORD_COLUMNS

    # 기존 파일의 추가 컬럼이 있으면 보존
    if RAW_USER_BEST50_PATH.exists():
        try:
            old_df = pd.read_csv(RAW_USER_BEST50_PATH)
        except Exception:
            old_df = pd.DataFrame(columns=required_columns)
    else:
        old_df = pd.DataFrame(columns=required_columns)

    all_columns = list(dict.fromkeys(
        list(old_df.columns) + required_columns + list(best50.columns)
    ))

    for col in all_columns:
        if col not in old_df.columns:
            old_df[col] = None
        if col not in best50.columns:
            best50[col] = None

    old_df["profile_id"] = old_df["profile_id"].fillna("").astype(str)

    lower_profile_id = profile_id.lower()
    existing_mask = old_df["profile_id"].astype(str).str.lower() == lower_profile_id
    removed_existing_count = int(existing_mask.sum())

    remaining_df = old_df[~existing_mask].copy()

    final_df = pd.concat(
        [
            remaining_df[all_columns],
            best50[all_columns],
        ],
        ignore_index=True,
    )

    # 숫자 컬럼 정리
    numeric_columns = [
        "rating",
        "achievement",
        "play_count",
        "chart_rating",
        "best50_order",
    ]

    for col in numeric_columns:
        if col in final_df.columns:
            final_df[col] = pd.to_numeric(final_df[col], errors="coerce")

    # bool 컬럼 정리
    if "is_best50" in final_df.columns:
        final_df["is_best50"] = final_df["is_best50"].apply(normalize_bool_for_main)

    RAW_USER_BEST50_PATH.parent.mkdir(parents=True, exist_ok=True)
    final_df.to_csv(RAW_USER_BEST50_PATH, index=False, encoding="utf-8-sig")

    action = "updated" if removed_existing_count > 0 else "inserted"

    return {
        "updated": True,
        "action": action,
        "profile_id": profile_id,
        "profile_url": normalized_url,
        "rating": rating,
        "rating_band": rating_band,
        "best50_count": int(len(best50)),
        "removed_existing_count": removed_existing_count,
        "path": str(RAW_USER_BEST50_PATH),
    }

def upsert_raw_user_records_csv_from_live_records(
    profile_url: str,
    profile_info: dict[str, Any],
    user_records_df: pd.DataFrame,
) -> dict[str, Any]:
    """
    live maishift 파싱 결과 전체 records를 raw_user_records.csv에 저장한다.

    목적:
    - input user의 전체 플레이 기록을 로컬 캐시에 보존
    - force_refresh=False 상태에서도 Best50 밖 플레이 기록을 played=True로 반영
    """
    profile_id = safe_str(profile_info.get("profile_id", ""), "").strip()

    if not profile_id:
        profile_id = extract_profile_id_from_url(profile_url)

    normalized_url = normalize_profile_url(profile_url)

    if not profile_id:
        return {
            "updated": False,
            "action": "skipped",
            "reason": "missing profile_id",
            "profile_id": "",
            "profile_url": normalized_url,
            "path": str(RAW_USER_RECORDS_PATH),
        }

    if user_records_df is None or user_records_df.empty:
        return {
            "updated": False,
            "action": "skipped",
            "reason": "empty user_records_df",
            "profile_id": profile_id,
            "profile_url": normalized_url,
            "path": str(RAW_USER_RECORDS_PATH),
        }

    records = ensure_user_record_columns_for_main(user_records_df)
    records = records.drop_duplicates(subset=["chart_id"], keep="first").copy()

    record_count = int(len(records))

    if record_count < LOCAL_USER_RECORDS_MIN_RECORD_COUNT:
        return {
            "updated": False,
            "action": "skipped",
            "reason": f"too few records: {record_count}",
            "profile_id": profile_id,
            "profile_url": normalized_url,
            "record_count": record_count,
            "min_record_count": LOCAL_USER_RECORDS_MIN_RECORD_COUNT,
            "path": str(RAW_USER_RECORDS_PATH),
        }

    rating = parse_rating_for_profile_db(profile_info.get("rating"))
    rating_band = rating_to_band(rating) if rating is not None else ""
    now_text = now_text_for_profile_db()

    records["profile_id"] = profile_id
    records["profile_url"] = normalized_url
    records["rating"] = rating
    records["rating_band"] = rating_band
    records["cached_at"] = now_text
    records["cache_source"] = "web_input_live_parse"

    required_columns = [
        "profile_id",
        "profile_url",
        "rating",
        "rating_band",
        "cached_at",
        "cache_source",
    ] + USER_RECORD_COLUMNS

    if RAW_USER_RECORDS_PATH.exists():
        try:
            old_df = pd.read_csv(RAW_USER_RECORDS_PATH)
        except Exception:
            old_df = pd.DataFrame(columns=required_columns)
    else:
        old_df = pd.DataFrame(columns=required_columns)

    all_columns = list(
        dict.fromkeys(
            list(old_df.columns)
            + required_columns
            + list(records.columns)
        )
    )

    for col in all_columns:
        if col not in old_df.columns:
            old_df[col] = None
        if col not in records.columns:
            records[col] = None

    old_df["profile_id"] = old_df["profile_id"].fillna("").astype(str)

    lower_profile_id = profile_id.lower()
    existing_mask = old_df["profile_id"].astype(str).str.lower() == lower_profile_id
    removed_existing_count = int(existing_mask.sum())

    remaining_df = old_df[~existing_mask].copy()

    final_df = pd.concat(
        [
            remaining_df[all_columns],
            records[all_columns],
        ],
        ignore_index=True,
    )

    numeric_columns = [
        "rating",
        "achievement",
        "play_count",
        "chart_rating",
        "best50_order",
    ]

    for col in numeric_columns:
        if col in final_df.columns:
            final_df[col] = pd.to_numeric(final_df[col], errors="coerce")

    if "is_best50" in final_df.columns:
        final_df["is_best50"] = final_df["is_best50"].apply(normalize_bool_for_main)

    RAW_USER_RECORDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    final_df.to_csv(RAW_USER_RECORDS_PATH, index=False, encoding="utf-8-sig")

    action = "updated" if removed_existing_count > 0 else "inserted"

    return {
        "updated": True,
        "action": action,
        "profile_id": profile_id,
        "profile_url": normalized_url,
        "rating": rating,
        "rating_band": rating_band,
        "record_count": record_count,
        "removed_existing_count": removed_existing_count,
        "path": str(RAW_USER_RECORDS_PATH),
    }

def normalize_profile_cache_key(profile_url: str) -> str:
    """
    profile_url을 캐시 key로 정규화한다.

    같은 유저의 /home, /records, trailing slash 차이로
    캐시가 여러 개 생기지 않도록 profile_id를 우선 사용한다.
    """
    text = str(profile_url).strip().rstrip("/")
    profile_id = extract_profile_id_from_url(text)

    if profile_id:
        return f"profile:{profile_id}"

    return text


# ------------------------------------------------------------
# Local CSV profile cache
# ------------------------------------------------------------

def load_profile_urls_df() -> pd.DataFrame:
    if not PROFILE_URLS_PATH.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(PROFILE_URLS_PATH)
    except Exception:
        return pd.DataFrame()

    if "profile_id" not in df.columns:
        if "profile_url" in df.columns:
            df["profile_id"] = df["profile_url"].apply(extract_profile_id_from_url)
        else:
            df["profile_id"] = ""

    if "profile_url" not in df.columns:
        df["profile_url"] = df["profile_id"].apply(
            lambda profile_id: f"https://maimai.shiftpsh.com/profile/{profile_id}/home"
            if str(profile_id).strip()
            else ""
        )

    df["profile_id"] = df["profile_id"].fillna("").astype(str)
    df["profile_url"] = df["profile_url"].fillna("").astype(str).apply(normalize_profile_url)

    return df


def find_local_profile_row(profile_id: str) -> pd.Series | None:
    if not profile_id:
        return None

    df = load_profile_urls_df()

    if df.empty:
        return None

    exact_mask = df["profile_id"].astype(str) == str(profile_id)

    if exact_mask.any():
        return df[exact_mask].iloc[-1]

    lower_profile_id = str(profile_id).lower()
    lower_mask = df["profile_id"].astype(str).str.lower() == lower_profile_id

    if lower_mask.any():
        return df[lower_mask].iloc[-1]

    return None


def read_rating_from_profile_row(profile_row: pd.Series | None) -> int | None:
    if profile_row is None:
        return None

    rating = safe_int(profile_row.get("rating"), default=None)

    if rating is None:
        return None

    if rating <= 0:
        return None

    return rating


def load_raw_user_best50_df() -> pd.DataFrame:
    if not RAW_USER_BEST50_PATH.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(RAW_USER_BEST50_PATH)
    except Exception:
        return pd.DataFrame()

    if "profile_id" not in df.columns:
        if "user_id" in df.columns:
            df["profile_id"] = df["user_id"]
        elif "profile_url" in df.columns:
            df["profile_id"] = df["profile_url"].apply(extract_profile_id_from_url)
        else:
            df["profile_id"] = ""

    if "profile_url" not in df.columns:
        df["profile_url"] = ""

    df["profile_id"] = df["profile_id"].fillna("").astype(str)
    df["profile_url"] = df["profile_url"].fillna("").astype(str)

    return df


def load_local_profile_records(profile_id: str, profile_url: str | None = None) -> pd.DataFrame:
    raw = load_raw_user_best50_df()

    if raw.empty or not profile_id:
        return pd.DataFrame(columns=USER_RECORD_COLUMNS)

    profile_id_text = str(profile_id)
    mask = raw["profile_id"].astype(str) == profile_id_text

    if not mask.any():
        lower_profile_id = profile_id_text.lower()
        mask = raw["profile_id"].astype(str).str.lower() == lower_profile_id

    if not mask.any() and profile_url:
        normalized_url = normalize_profile_url(profile_url)
        mask = raw["profile_url"].astype(str).apply(normalize_profile_url) == normalized_url

    records = raw[mask].copy()

    if records.empty:
        return pd.DataFrame(columns=USER_RECORD_COLUMNS)

    records = records[records.get("chart_id", "").notna()].copy()
    records["chart_id"] = records["chart_id"].astype(str)
    records = records[records["chart_id"].str.len() > 0].copy()

    if records.empty:
        return pd.DataFrame(columns=USER_RECORD_COLUMNS)

    if "achievement" not in records.columns:
        records["achievement"] = 0.0

    if "rank" not in records.columns:
        records["rank"] = ""

    if "chart_rating" not in records.columns:
        if "calculated_chart_rating" in records.columns:
            records["chart_rating"] = records["calculated_chart_rating"]
        else:
            records["chart_rating"] = 0

    if "best50_section" not in records.columns:
        records["best50_section"] = "unknown"

    records["achievement"] = pd.to_numeric(records["achievement"], errors="coerce").fillna(0.0)
    records["chart_rating"] = pd.to_numeric(records["chart_rating"], errors="coerce").fillna(0.0)

    records = records.sort_values(
        ["best50_section", "chart_rating", "achievement", "chart_id"],
        ascending=[True, False, False, True],
    ).reset_index(drop=True)

    user_records = pd.DataFrame()
    user_records["chart_id"] = records["chart_id"].astype(str)
    user_records["achievement"] = records["achievement"]
    user_records["rank"] = records["rank"].fillna("").astype(str)
    user_records["play_count"] = 1
    user_records["chart_rating"] = records["chart_rating"]
    user_records["is_best50"] = True
    user_records["best50_section"] = records["best50_section"].fillna("unknown").astype(str)
    user_records["best50_order"] = range(1, len(user_records) + 1)
    user_records["record_source"] = "local_raw_user_best50"
    user_records["combo"] = records["combo"].fillna("").astype(str) if "combo" in records.columns else ""
    user_records["sync"] = records["sync"].fillna("").astype(str) if "sync" in records.columns else ""

    for col in USER_RECORD_COLUMNS:
        if col not in user_records.columns:
            if col in {"achievement", "play_count", "chart_rating", "best50_order"}:
                user_records[col] = 0
            elif col == "is_best50":
                user_records[col] = True
            else:
                user_records[col] = ""

    user_records = user_records.drop_duplicates(
        subset=["chart_id"],
        keep="first",
    ).reset_index(drop=True)

    return user_records[USER_RECORD_COLUMNS]

def ensure_user_record_columns_for_main(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None:
        df = pd.DataFrame()

    df = df.copy()

    for col in USER_RECORD_COLUMNS:
        if col not in df.columns:
            if col in {"achievement", "play_count", "chart_rating", "best50_order"}:
                df[col] = 0
            elif col == "is_best50":
                df[col] = False
            else:
                df[col] = ""

    df["chart_id"] = df["chart_id"].fillna("").astype(str)
    df = df[df["chart_id"].str.len() > 0].copy()

    df["achievement"] = pd.to_numeric(df["achievement"], errors="coerce").fillna(0.0)
    df["play_count"] = pd.to_numeric(df["play_count"], errors="coerce").fillna(0.0)
    df["chart_rating"] = pd.to_numeric(df["chart_rating"], errors="coerce").fillna(0.0)
    df["best50_order"] = pd.to_numeric(df["best50_order"], errors="coerce").fillna(0.0)
    df["is_best50"] = df["is_best50"].apply(normalize_bool_for_main)

    text_cols = [
        "rank",
        "best50_section",
        "record_source",
        "combo",
        "sync",
    ]

    for col in text_cols:
        df[col] = df[col].fillna("").astype(str)

    return df[USER_RECORD_COLUMNS].copy()


def merge_live_records_with_local_best50(
    live_user_records_df: pd.DataFrame,
    profile_id: str,
    profile_url: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Hybrid profile records merge.

    - live_user_records_df:
      실시간 maishift 파싱 결과. 스코어/플레이 기록이 풍부함.

    - local_best50:
      raw_user_best50.csv 기반 Best50. NEW/OLD floor 계산이 안정적임.

    목표:
    live 기록은 유지하되, Best50 여부/섹션/곡별 레이팅은 local Best50로 보강한다.
    """
    live = ensure_user_record_columns_for_main(live_user_records_df)

    local = load_local_profile_records(
        profile_id=profile_id,
        profile_url=profile_url,
    )
    local = ensure_user_record_columns_for_main(local)

    local_best50 = local[local["is_best50"].apply(normalize_bool_for_main)].copy()

    debug = {
        "used": False,
        "reason": "",
        "profile_id": profile_id,
        "live_record_count": int(len(live)),
        "live_best50_count_before": count_best50_records_for_main(live),
        "local_best50_count": int(len(local_best50)),
        "matched_chart_count": 0,
        "appended_chart_count": 0,
        "final_record_count": int(len(live)),
        "final_best50_count": count_best50_records_for_main(live),
    }

    if not profile_id:
        debug["reason"] = "missing profile_id"
        return live, debug

    if local_best50.empty:
        debug["reason"] = "local best50 cache not found"
        return live, debug

    # 같은 chart_id가 여러 번 있으면 하나만 유지
    live = live.drop_duplicates(subset=["chart_id"], keep="first").reset_index(drop=True)
    local_best50 = local_best50.drop_duplicates(subset=["chart_id"], keep="first").reset_index(drop=True)
    
    # local Best50가 존재하는 경우, Best50 판정은 local raw_user_best50.csv를 기준으로 재정의한다.
    # live parse에서 잘못 남은 is_best50=True가 있으면 final_best50_count가 51 이상이 될 수 있기 때문이다.
    if not local_best50.empty:
        live["is_best50"] = False
        live["best50_section"] = ""
        live["best50_order"] = 0

    live_by_chart_id = {
        chart_id: idx
        for idx, chart_id in enumerate(live["chart_id"].astype(str).tolist())
    }

    rows_to_append = []
    matched_chart_count = 0
    appended_chart_count = 0

    for _, local_row in local_best50.iterrows():
        chart_id = str(local_row["chart_id"])

        if chart_id in live_by_chart_id:
            idx = live_by_chart_id[chart_id]
            matched_chart_count += 1

            # Best50 판정과 NEW/OLD 섹션은 local Best50를 신뢰한다.
            live.at[idx, "is_best50"] = True
            live.at[idx, "best50_section"] = local_row.get("best50_section", "")
            live.at[idx, "best50_order"] = local_row.get("best50_order", 0)

            # floor 계산 안정화를 위해 Best50 곡별 레이팅은 local chart_rating을 우선한다.
            local_chart_rating = safe_float(local_row.get("chart_rating", 0.0), 0.0)
            if local_chart_rating > 0:
                live.at[idx, "chart_rating"] = local_chart_rating

            # live 쪽에 achievement가 없을 때만 local 값을 보조로 사용한다.
            live_achievement = safe_float(live.at[idx, "achievement"], 0.0)
            local_achievement = safe_float(local_row.get("achievement", 0.0), 0.0)

            if live_achievement <= 0 and local_achievement > 0:
                live.at[idx, "achievement"] = local_achievement

            live_record_source = safe_str(live.at[idx, "record_source"], "")
            if "hybrid_local_best50" not in live_record_source:
                if live_record_source:
                    live.at[idx, "record_source"] = f"{live_record_source}+hybrid_local_best50"
                else:
                    live.at[idx, "record_source"] = "hybrid_local_best50"

        else:
            appended_chart_count += 1
            append_row = local_row.copy()
            append_row["record_source"] = "hybrid_local_best50_appended"
            rows_to_append.append(append_row)

    if rows_to_append:
        append_df = pd.DataFrame(rows_to_append)
        append_df = ensure_user_record_columns_for_main(append_df)
        live = pd.concat([live, append_df], ignore_index=True)

    live = ensure_user_record_columns_for_main(live)
    live = live.drop_duplicates(subset=["chart_id"], keep="first").reset_index(drop=True)

    final_best50_count = count_best50_records_for_main(live)

    debug.update({
        "used": final_best50_count > debug["live_best50_count_before"],
        "reason": "ok" if final_best50_count > debug["live_best50_count_before"] else "no additional best50 records were needed",
        "matched_chart_count": int(matched_chart_count),
        "appended_chart_count": int(appended_chart_count),
        "final_record_count": int(len(live)),
        "final_best50_count": int(final_best50_count),
    })

    return live, debug

def make_local_profile_info(
    profile_id: str,
    profile_url: str,
    user_records_df: pd.DataFrame,
    profile_row: pd.Series | None,
) -> dict[str, Any]:
    rating = read_rating_from_profile_row(profile_row)
    rating_band = rating_to_band(rating) if rating is not None else ""

    if profile_row is not None:
        raw_rating_band = safe_str(profile_row.get("rating_band"), "")

        if raw_rating_band and raw_rating_band != "nan":
            rating_band = rating_band or raw_rating_band

    record_count = int(len(user_records_df))

    return {
        "profile_id": profile_id,
        "profile_url": normalize_profile_url(profile_url),
        "rating": rating,
        "rating_band": rating_band,
        "data_source": "local_csv_cache",
        "profile_data_source": "local_csv_cache",
        "record_source": "raw_user_best50.csv",
        "parse_quality_status": "ok_local_csv_cache",
        "records_extracted_count": record_count,
        "records_matched_count": record_count,
        "records_unmatched_count": 0,
        "local_cache_record_count": record_count,
        "local_cache_min_record_count": LOCAL_PROFILE_CACHE_MIN_RECORD_COUNT,
        "source_files": {
            "profile_urls": str(PROFILE_URLS_PATH),
            "raw_user_best50": str(RAW_USER_BEST50_PATH),
        },
    }


def get_local_profile_cache_result(
    profile_url: str,
) -> tuple[pd.DataFrame, dict[str, Any]] | None:
    profile_id = extract_profile_id_from_url(profile_url)

    if not profile_id:
        return None

    user_records_df = load_local_profile_records(
        profile_id=profile_id,
        profile_url=profile_url,
    )

    if len(user_records_df) < LOCAL_PROFILE_CACHE_MIN_RECORD_COUNT:
        return None

    profile_row = find_local_profile_row(profile_id)

    profile_info = make_local_profile_info(
        profile_id=profile_id,
        profile_url=profile_url,
        user_records_df=user_records_df,
        profile_row=profile_row,
    )

    return user_records_df, profile_info


def load_local_user_records_cache(
    profile_id: str,
    profile_url: str,
) -> pd.DataFrame:
    """
    raw_user_records.csv에서 input user의 전체 플레이 기록을 불러온다.

    이 캐시는 played / achievement 판정용이다.
    Best50 floor 계산은 raw_user_best50.csv와 병합해서 보정한다.
    """
    if not RAW_USER_RECORDS_PATH.exists():
        return pd.DataFrame(columns=USER_RECORD_COLUMNS)

    try:
        df = pd.read_csv(RAW_USER_RECORDS_PATH)
    except Exception:
        return pd.DataFrame(columns=USER_RECORD_COLUMNS)

    if df.empty:
        return pd.DataFrame(columns=USER_RECORD_COLUMNS)

    profile_id = safe_str(profile_id, "").strip()
    normalized_url = normalize_profile_url(profile_url)

    if "profile_id" not in df.columns:
        df["profile_id"] = ""

    if "profile_url" not in df.columns:
        df["profile_url"] = ""

    df["profile_id"] = df["profile_id"].fillna("").astype(str)
    df["profile_url"] = df["profile_url"].fillna("").astype(str)

    mask = pd.Series(False, index=df.index)

    if profile_id:
        mask = mask | (
            df["profile_id"].astype(str).str.lower() == profile_id.lower()
        )

    if normalized_url:
        mask = mask | (
            df["profile_url"].astype(str).map(normalize_profile_url) == normalized_url
        )

    records = df[mask].copy()

    if records.empty:
        return pd.DataFrame(columns=USER_RECORD_COLUMNS)

    records = ensure_user_record_columns_for_main(records)
    records = records.drop_duplicates(subset=["chart_id"], keep="first").reset_index(drop=True)

    return records


def get_local_user_records_cache_result(
    profile_url: str,
) -> tuple[pd.DataFrame, dict[str, Any]] | None:
    """
    force_refresh=False일 때 우선 사용하는 전체 플레이 기록 기반 로컬 캐시.

    raw_user_records.csv:
    - input user의 전체 플레이 기록
    - played / achievement 판정용

    raw_user_best50.csv:
    - Best50 50개
    - NEW/OLD floor 보정용
    """
    profile_id = extract_profile_id_from_url(profile_url)

    if not profile_id:
        return None

    records = load_local_user_records_cache(
        profile_id=profile_id,
        profile_url=profile_url,
    )

    if len(records) < LOCAL_USER_RECORDS_MIN_RECORD_COUNT:
        return None

    # 전체 records에 local Best50 정보를 병합하여 floor 계산을 안정화한다.
    records, hybrid_debug = merge_live_records_with_local_best50(
        live_user_records_df=records,
        profile_id=profile_id,
        profile_url=profile_url,
    )

    best50_count = count_best50_records_for_main(records)
    profile_row = find_local_profile_row(profile_id)
    rating = read_rating_from_profile_row(profile_row)
    rating_band = rating_to_band(rating) if rating is not None else ""

    if profile_row is not None:
        raw_rating_band = safe_str(profile_row.get("rating_band"), "")
        if raw_rating_band and raw_rating_band != "nan":
            rating_band = rating_band or raw_rating_band

    if rating is None:
        try:
            raw_df = pd.read_csv(RAW_USER_RECORDS_PATH)
            raw_df["profile_id"] = raw_df["profile_id"].fillna("").astype(str)
            m = raw_df["profile_id"].astype(str).str.lower() == profile_id.lower()
            if m.any():
                first = raw_df[m].iloc[0]
                rating = parse_rating_for_profile_db(first.get("rating"))
                if rating is not None:
                    rating_band = rating_to_band(rating)
        except Exception:
            pass

    record_count = int(len(records))

    profile_info = {
        "profile_id": profile_id,
        "profile_url": normalize_profile_url(profile_url),
        "rating": rating,
        "rating_band": rating_band,
        "data_source": "local_user_records_cache",
        "profile_data_source": "local_user_records_cache",
        "record_source": "raw_user_records.csv + raw_user_best50.csv",
        "parse_quality_status": "ok_local_user_records_cache",
        "records_extracted_count": record_count,
        "records_matched_count": record_count,
        "records_unmatched_count": 0,
        "local_user_records_count": record_count,
        "local_cache_record_count": record_count,
        "local_best50_count": int(best50_count),
        "local_cache_min_record_count": LOCAL_USER_RECORDS_MIN_RECORD_COUNT,
        "hybrid_best50_fallback": hybrid_debug,
        "hybrid_best50_fallback_used": bool(hybrid_debug.get("used", False)),
        "source_files": {
            "profile_urls": str(PROFILE_URLS_PATH),
            "raw_user_records": str(RAW_USER_RECORDS_PATH),
            "raw_user_best50": str(RAW_USER_BEST50_PATH),
        },
    }

    return records, profile_info


# ------------------------------------------------------------
# Cache quality
# ------------------------------------------------------------

def read_int_from_profile_info(
    profile_info: dict[str, Any],
    keys: list[str],
    default: int = 0,
) -> int:
    for key in keys:
        value = profile_info.get(key)

        if value is None or value == "":
            continue

        try:
            return int(float(value))
        except Exception:
            continue

    return default


def get_profile_parse_counts(
    profile_info: dict[str, Any],
    user_records_df: pd.DataFrame | None = None,
) -> dict[str, int]:
    extracted_count = read_int_from_profile_info(
        profile_info,
        [
            "records_extracted_count",
            "extracted_record_count",
            "records_count",
            "parsed_record_count",
            "local_user_records_count",
            "local_cache_record_count",
        ],
        default=0,
    )

    matched_count = read_int_from_profile_info(
        profile_info,
        [
            "records_matched_count",
            "matched_record_count",
            "matched_count",
            "local_user_records_count",
            "local_cache_record_count",
        ],
        default=0,
    )

    unmatched_count = read_int_from_profile_info(
        profile_info,
        [
            "records_unmatched_count",
            "unmatched_record_count",
            "unmatched_count",
        ],
        default=0,
    )

    if matched_count <= 0 and user_records_df is not None:
        try:
            matched_count = int(len(user_records_df))
        except Exception:
            matched_count = 0

    if extracted_count <= 0 and user_records_df is not None:
        try:
            extracted_count = int(len(user_records_df))
        except Exception:
            extracted_count = 0

    return {
        "extracted_count": extracted_count,
        "matched_count": matched_count,
        "unmatched_count": unmatched_count,
    }


def is_local_profile_info(profile_info: dict[str, Any]) -> bool:
    return profile_info.get("data_source") in {
        "local_csv_cache",
        "local_user_records_cache",
    }


def is_local_user_records_profile_info(profile_info: dict[str, Any]) -> bool:
    return profile_info.get("data_source") == "local_user_records_cache"


def is_profile_parse_quality_acceptable(
    profile_info: dict[str, Any],
    user_records_df: pd.DataFrame | None = None,
) -> bool:
    counts = get_profile_parse_counts(
        profile_info=profile_info,
        user_records_df=user_records_df,
    )

    extracted_count = counts["extracted_count"]
    matched_count = counts["matched_count"]

    if is_local_user_records_profile_info(profile_info):
        return matched_count >= LOCAL_USER_RECORDS_MIN_RECORD_COUNT

    if is_local_profile_info(profile_info):
        return matched_count >= LOCAL_PROFILE_CACHE_MIN_RECORD_COUNT

    return (
        extracted_count >= PROFILE_CACHE_MIN_EXTRACTED_COUNT
        and matched_count >= PROFILE_CACHE_MIN_MATCHED_COUNT
    )


def make_cache_quality_info(
    profile_info: dict[str, Any],
    user_records_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    counts = get_profile_parse_counts(
        profile_info=profile_info,
        user_records_df=user_records_df,
    )

    acceptable = is_profile_parse_quality_acceptable(
        profile_info=profile_info,
        user_records_df=user_records_df,
    )

    if is_local_user_records_profile_info(profile_info):
        min_extracted_count = LOCAL_USER_RECORDS_MIN_RECORD_COUNT
        min_matched_count = LOCAL_USER_RECORDS_MIN_RECORD_COUNT
        quality_type = "local_user_records_cache"
    elif is_local_profile_info(profile_info):
        min_extracted_count = LOCAL_PROFILE_CACHE_MIN_RECORD_COUNT
        min_matched_count = LOCAL_PROFILE_CACHE_MIN_RECORD_COUNT
        quality_type = "local_csv_cache"
    else:
        min_extracted_count = PROFILE_CACHE_MIN_EXTRACTED_COUNT
        min_matched_count = PROFILE_CACHE_MIN_MATCHED_COUNT
        quality_type = "live_maishift_parse"

    return {
        "acceptable": acceptable,
        "quality_type": quality_type,
        "extracted_count": counts["extracted_count"],
        "matched_count": counts["matched_count"],
        "unmatched_count": counts["unmatched_count"],
        "min_extracted_count": min_extracted_count,
        "min_matched_count": min_matched_count,
    }


# ------------------------------------------------------------
# Profile parse result resolver
# ------------------------------------------------------------

def get_profile_parse_result(
    profile_url: str,
    force_refresh: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    """
    maishift 프로필 파싱 결과를 캐시한다.

    force_refresh=False일 때 우선순위:
    1. FastAPI 메모리 캐시
    2. raw_user_records.csv 기반 전체 플레이 기록 로컬 캐시
    3. raw_user_best50.csv 기반 Best50 전용 로컬 CSV 캐시
    4. maishift 라이브 파싱

    force_refresh=True일 때:
    - 메모리 캐시와 로컬 CSV 캐시를 모두 무시하고 maishift 라이브 파싱을 수행한다.
    - 라이브 파싱 성공 시 profile_urls.csv / raw_user_best50.csv / raw_user_records.csv를 갱신한다.
    """
    now = time.time()

    cache_key = normalize_profile_cache_key(profile_url)
    cached = profile_parse_cache.get(cache_key)

    if cached is not None:
        cache_age_seconds = now - float(cached.get("created_at", 0.0))
        cache_expired = cache_age_seconds > PROFILE_CACHE_TTL_SECONDS

        cached_user_records_df = cached.get("user_records_df")
        cached_profile_info = cached.get("profile_info", {})

        cached_quality = make_cache_quality_info(
            profile_info=cached_profile_info,
            user_records_df=cached_user_records_df,
        )

        if (
            not force_refresh
            and not cache_expired
            and cached_quality["acceptable"]
        ):
            cache_info = {
                "enabled": True,
                "hit": True,
                "memory_cache_hit": True,
                "local_cache_hit": cached_profile_info.get("data_source") in {"local_csv_cache", "local_user_records_cache"},
                "data_source": cached_profile_info.get("data_source", "memory_cache"),
                "cache_key": cache_key,
                "ttl_seconds": PROFILE_CACHE_TTL_SECONDS,
                "age_seconds": round(cache_age_seconds, 2),
                "force_refresh": force_refresh,
                "expired": False,
                "stored": True,
                "used_stale_fallback": False,
                "quality": cached_quality,
            }

            return (
                cached_user_records_df.copy(),
                dict(cached_profile_info),
                cache_info,
            )

        if not cached_quality["acceptable"]:
            # 불완전한 캐시는 재사용하지 않는다.
            profile_parse_cache.pop(cache_key, None)
            cached = None

    if not force_refresh:
        # 1순위: 전체 플레이 기록 기반 로컬 캐시.
        # played / achievement 판정이 Best50 밖 기록까지 반영된다.
        local_user_records_result = get_local_user_records_cache_result(profile_url)

        if local_user_records_result is not None:
            local_user_records_df, local_profile_info = local_user_records_result
            local_quality = make_cache_quality_info(
                profile_info=local_profile_info,
                user_records_df=local_user_records_df,
            )

            profile_parse_cache[cache_key] = {
                "user_records_df": local_user_records_df.copy(),
                "profile_info": dict(local_profile_info),
                "created_at": now,
            }

            cache_info = {
                "enabled": True,
                "hit": True,
                "memory_cache_hit": False,
                "local_cache_hit": True,
                "data_source": "local_user_records_cache",
                "cache_key": cache_key,
                "ttl_seconds": PROFILE_CACHE_TTL_SECONDS,
                "age_seconds": 0.0,
                "force_refresh": force_refresh,
                "expired": False,
                "stored": True,
                "used_stale_fallback": False,
                "quality": local_quality,
                "note": (
                    "Local raw_user_records.csv cache was used for full played history. "
                    "raw_user_best50.csv was merged for Best50/floor stabilization. "
                    "maishift live parsing was skipped."
                ),
            }

            return local_user_records_df, local_profile_info, cache_info

        # 2순위: 기존 Best50 전용 로컬 CSV 캐시 fallback.
        local_result = get_local_profile_cache_result(profile_url)

        if local_result is not None:
            local_user_records_df, local_profile_info = local_result
            local_quality = make_cache_quality_info(
                profile_info=local_profile_info,
                user_records_df=local_user_records_df,
            )

            profile_parse_cache[cache_key] = {
                "user_records_df": local_user_records_df.copy(),
                "profile_info": dict(local_profile_info),
                "created_at": now,
            }

            cache_info = {
                "enabled": True,
                "hit": True,
                "memory_cache_hit": False,
                "local_cache_hit": True,
                "data_source": "local_csv_cache",
                "cache_key": cache_key,
                "ttl_seconds": PROFILE_CACHE_TTL_SECONDS,
                "age_seconds": 0.0,
                "force_refresh": force_refresh,
                "expired": False,
                "stored": True,
                "used_stale_fallback": False,
                "quality": local_quality,
                "note": (
                    "Local raw_user_best50.csv cache was used as fallback. "
                    "maishift live parsing was skipped."
                ),
            }

            return local_user_records_df, local_profile_info, cache_info

    user_records_df, profile_info = parse_maishift_profile_to_records(
        profile_url=profile_url,
        charts=charts,
    )

    profile_info = dict(profile_info)
    profile_info.setdefault("data_source", "live_maishift")
    profile_info.setdefault("profile_data_source", "live_maishift")

    profile_id = safe_str(
        profile_info.get("profile_id", ""),
        "",
    )

    if not profile_id:
        profile_id = extract_profile_id_from_url(profile_url)

    # live records + local raw_user_best50 floor fallback
    before_hybrid_best50_count = count_best50_records_for_main(user_records_df)

    user_records_df, hybrid_debug = merge_live_records_with_local_best50(
        live_user_records_df=user_records_df,
        profile_id=profile_id,
        profile_url=profile_url,
    )

    after_hybrid_best50_count = count_best50_records_for_main(user_records_df)

    profile_info["hybrid_best50_fallback"] = hybrid_debug
    profile_info["hybrid_best50_fallback_used"] = bool(hybrid_debug.get("used", False))
    profile_info["best50_count_before_hybrid"] = int(before_hybrid_best50_count)
    profile_info["best50_count_after_hybrid"] = int(after_hybrid_best50_count)

    if hybrid_debug.get("used", False):
        profile_info["data_source"] = "live_maishift_hybrid_best50"
        profile_info["profile_data_source"] = "live_maishift_hybrid_best50"
        profile_info["record_source"] = "live_maishift + raw_user_best50 floor fallback"

    try:
        profile_urls_db_update = upsert_profile_urls_csv_from_live_parse(
            profile_url=profile_url,
            profile_info=profile_info,
        )
    except Exception as e:
        profile_urls_db_update = {
            "updated": False,
            "action": "error",
            "reason": str(e),
            "profile_id": safe_str(profile_info.get("profile_id", ""), ""),
            "profile_url": normalize_profile_url(profile_url),
            "path": str(PROFILE_URLS_PATH),
        }

    profile_info["profile_urls_db_update"] = profile_urls_db_update

    try:
        raw_user_best50_db_update = upsert_raw_user_best50_csv_from_live_records(
            profile_url=profile_url,
            profile_info=profile_info,
            user_records_df=user_records_df,
        )
    except Exception as e:
        raw_user_best50_db_update = {
            "updated": False,
            "action": "error",
            "reason": str(e),
            "profile_id": safe_str(profile_info.get("profile_id", ""), ""),
            "profile_url": normalize_profile_url(profile_url),
            "path": str(RAW_USER_BEST50_PATH),
        }

    profile_info["raw_user_best50_db_update"] = raw_user_best50_db_update

    try:
        raw_user_records_db_update = upsert_raw_user_records_csv_from_live_records(
            profile_url=profile_url,
            profile_info=profile_info,
            user_records_df=user_records_df,
        )
    except Exception as e:
        raw_user_records_db_update = {
            "updated": False,
            "action": "error",
            "reason": str(e),
            "profile_id": safe_str(profile_info.get("profile_id", ""), ""),
            "profile_url": normalize_profile_url(profile_url),
            "path": str(RAW_USER_RECORDS_PATH),
        }

    profile_info["raw_user_records_db_update"] = raw_user_records_db_update

    fresh_quality = make_cache_quality_info(
        profile_info=profile_info,
        user_records_df=user_records_df,
    )

    should_store_cache = fresh_quality["acceptable"]
    used_stale_fallback = False

    # force_refresh=False인 경우에만, 새 라이브 파싱이 low-quality이면 기존 acceptable memory cache를 fallback으로 사용한다.
    if not force_refresh and not should_store_cache and cached is not None:
        cached_user_records_df = cached.get("user_records_df")
        cached_profile_info = cached.get("profile_info", {})

        cached_quality = make_cache_quality_info(
            profile_info=cached_profile_info,
            user_records_df=cached_user_records_df,
        )

        if cached_quality["acceptable"]:
            used_stale_fallback = True
            cache_age_seconds = now - float(cached.get("created_at", 0.0))

            cache_info = {
                "enabled": True,
                "hit": True,
                "memory_cache_hit": True,
                "local_cache_hit": cached_profile_info.get("data_source") in {"local_csv_cache", "local_user_records_cache"},
                "data_source": cached_profile_info.get("data_source", "memory_cache"),
                "cache_key": cache_key,
                "ttl_seconds": PROFILE_CACHE_TTL_SECONDS,
                "age_seconds": round(cache_age_seconds, 2),
                "force_refresh": force_refresh,
                "expired": cache_age_seconds > PROFILE_CACHE_TTL_SECONDS,
                "stored": False,
                "used_stale_fallback": True,
                "fresh_parse_quality": fresh_quality,
                "quality": cached_quality,
                "note": (
                    "Fresh parse result was low-quality, so the previous acceptable cache was used."
                ),
            }

            return (
                cached_user_records_df.copy(),
                dict(cached_profile_info),
                cache_info,
            )

    if should_store_cache:
        profile_parse_cache[cache_key] = {
            "user_records_df": user_records_df.copy(),
            "profile_info": dict(profile_info),
            "created_at": now,
        }

    cache_info = {
        "enabled": True,
        "hit": False,
        "memory_cache_hit": False,
        "local_cache_hit": False,
        "data_source": profile_info.get("data_source", "live_maishift"),
        "cache_key": cache_key,
        "ttl_seconds": PROFILE_CACHE_TTL_SECONDS,
        "age_seconds": 0.0,
        "force_refresh": force_refresh,
        "expired": False,
        "stored": should_store_cache,
        "used_stale_fallback": used_stale_fallback,
        "quality": fresh_quality,
    }

    if not should_store_cache:
        cache_info["note"] = (
            "Fresh parse result was returned but not stored because parse quality was below cache threshold."
        )

    return user_records_df, profile_info, cache_info


# ------------------------------------------------------------
# API endpoints
# ------------------------------------------------------------

@app.get("/")
def root():
    return {
        "service": "maimai DX Recommender API",
        "status": "running",
        "main_endpoint": "/recommend-by-url",
        "internal_endpoint": "/recommend",
        "docs": "/docs",
        "profile_cache_ttl_seconds": PROFILE_CACHE_TTL_SECONDS,
        "local_profile_cache_enabled": True,
        "local_profile_cache_min_record_count": LOCAL_PROFILE_CACHE_MIN_RECORD_COUNT,
        "local_user_records_cache_enabled": True,
        "local_user_records_min_record_count": LOCAL_USER_RECORDS_MIN_RECORD_COUNT,
    }


@app.get("/health")
def health_check():
    try:
        current_charts = load_charts()

        profile_url_rows = None
        raw_best50_rows = None
        raw_user_records_rows = None

        try:
            if PROFILE_URLS_PATH.exists():
                profile_url_rows = int(len(pd.read_csv(PROFILE_URLS_PATH)))
        except Exception:
            profile_url_rows = None

        try:
            if RAW_USER_BEST50_PATH.exists():
                raw_best50_rows = int(len(pd.read_csv(RAW_USER_BEST50_PATH)))
        except Exception:
            raw_best50_rows = None

        try:
            if RAW_USER_RECORDS_PATH.exists():
                raw_user_records_rows = int(len(pd.read_csv(RAW_USER_RECORDS_PATH)))
        except Exception:
            raw_user_records_rows = None

        return {
            "status": "ok",
            "chart_count": int(len(current_charts)),
            "main_endpoint": "/recommend-by-url",
            "data_mode": "maishift_profile_url",
            "profile_cache_size": len(profile_parse_cache),
            "profile_cache_ttl_seconds": PROFILE_CACHE_TTL_SECONDS,
            "profile_cache_min_extracted_count": PROFILE_CACHE_MIN_EXTRACTED_COUNT,
            "profile_cache_min_matched_count": PROFILE_CACHE_MIN_MATCHED_COUNT,
            "local_profile_cache_enabled": True,
            "local_profile_cache_min_record_count": LOCAL_PROFILE_CACHE_MIN_RECORD_COUNT,
            "profile_urls_path_exists": PROFILE_URLS_PATH.exists(),
            "raw_user_best50_path_exists": RAW_USER_BEST50_PATH.exists(),
            "raw_user_records_path_exists": RAW_USER_RECORDS_PATH.exists(),
            "profile_url_rows": profile_url_rows,
            "raw_best50_rows": raw_best50_rows,
            "raw_user_records_rows": raw_user_records_rows,
        }

    except Exception as e:
        return {
            "status": "degraded",
            "detail": str(e),
        }


@app.post("/recommend")
def recommend_internal(req: RecommendRequest):
    """
    내부 테스트용 추천 endpoint.

    실제 서비스 흐름에서는 /recommend-by-url 사용을 권장한다.
    이 endpoint는 sample_user_records.csv 같은 더미 파일을 사용하지 않는다.
    user_records_df 없이 cohort 통계만 기반으로 추천 결과를 생성한다.
    """
    try:
        result = recommend(
            req=req,
            user_records_df=None,
            user_rating=None,
        )

        result["input_profile"] = None
        result["profile_parse_warning"] = (
            "이 endpoint는 내부 테스트용입니다. "
            "실제 maishift 프로필 기반 추천은 /recommend-by-url을 사용하세요."
        )
        result["profile_cache"] = {
            "enabled": False,
            "hit": False,
            "reason": "internal endpoint does not parse maishift profile",
        }

        return result

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"recommendation failed: {e}",
        )


@app.post("/recommend-by-url")
def recommend_by_url(req: ProfileUrlRecommendRequest):
    """
    실제 서비스용 추천 endpoint.

    maishift 프로필 URL을 입력받아 records/home 페이지를 파싱하거나,
    force_refresh=False이면 먼저 raw_user_best50.csv 로컬 캐시를 사용한다.
    """
    try:
        user_records_df, profile_info, cache_info = get_profile_parse_result(
            profile_url=req.profile_url,
            force_refresh=req.force_refresh,
        )

        user_rating = profile_info.get("rating")

        result = recommend(
            req=req,
            user_records_df=user_records_df,
            user_rating=user_rating,
        )

        result["input_profile"] = profile_info
        result["profile_parse_warning"] = make_profile_parse_warning(profile_info)
        result["profile_cache"] = cache_info
        result["profile_data_source"] = cache_info.get("data_source")

        return result

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"failed to parse profile or generate recommendation: {e}",
        )


# ------------------------------------------------------------
# Warning helper
# ------------------------------------------------------------

def make_profile_parse_warning(profile_info: dict[str, Any]) -> str | None:
    if profile_info.get("data_source") in {"local_csv_cache", "local_user_records_cache"}:
        return None

    counts = get_profile_parse_counts(profile_info)
    extracted_count = counts["extracted_count"]
    matched_count = counts["matched_count"]
    unmatched_count = counts["unmatched_count"]

    records_counts = get_profile_parse_counts(
        {
            "records_extracted_count": profile_info.get("records_extracted_count"),
            "records_matched_count": profile_info.get("records_matched_count"),
        }
    )
    records_extracted_count = records_counts["extracted_count"]
    records_matched_count = records_counts["matched_count"]

    if extracted_count == 0:
        return (
            "maishift 프로필에서 기록을 추출하지 못했습니다. "
            "프로필 URL이 올바른지, 프로필이 공개 상태인지 확인하세요."
        )

    if matched_count == 0:
        return (
            "프로필 기록은 추출했지만 현재 곡 DB와 매칭된 기록이 없습니다. "
            "곡명 표기 차이, 난이도 범위, 또는 DB 필터 조건을 확인해야 합니다."
        )

    if records_extracted_count > 0 and records_matched_count == 0:
        return (
            "records 페이지에서는 기록을 추출했지만 곡 DB와 매칭되지 않았습니다. "
            "Best 50 기록 위주로 추천이 생성되었을 수 있습니다."
        )

    if unmatched_count > 0:
        return (
            f"일부 기록은 곡 DB와 매칭되지 않았습니다. "
            f"매칭 실패 records 수: {unmatched_count}개. "
            f"주된 원인은 13 미만 채보, 곡명 표기 차이, 또는 DB 범위 밖 채보일 수 있습니다."
        )

    return None