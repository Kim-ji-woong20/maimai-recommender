import os
import time
from typing import Any
import pandas as pd

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from maishift_parser import parse_maishift_profile_to_records
from recommender import load_charts, recommend
from schemas import ProfileUrlRecommendRequest, RecommendRequest


PROFILE_CACHE_TTL_SECONDS = int(os.getenv("PROFILE_CACHE_TTL_SECONDS", "3600"))

PROFILE_CACHE_MIN_EXTRACTED_COUNT = int(os.getenv("PROFILE_CACHE_MIN_EXTRACTED_COUNT", "100"))

PROFILE_CACHE_MIN_MATCHED_COUNT = int(os.getenv("PROFILE_CACHE_MIN_MATCHED_COUNT", "50"))

profile_parse_cache: dict[str, dict[str, Any]] = {}

charts = load_charts()

app = FastAPI(
    title="maimai DX Recommender API",
    description=(
        "maishift 공개 프로필 기록과 유사 레이팅대 cohort 통계를 활용한 "
        "maimai DX 고레벨 채보 추천 API"
    ),
    version="0.4.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def normalize_profile_cache_key(profile_url: str) -> str:
    return str(profile_url).strip().rstrip("/")


def get_cache_age_seconds(created_at: float) -> int:
    return max(0, int(time.time() - created_at))


def extract_profile_id_from_url(profile_url: str) -> str:
    """
    maishift URL에서 profile_id를 추출한다.

    예:
    https://maimai.shiftpsh.com/profile/hapum/home
    -> hapum
    """
    try:
        text = str(profile_url).strip()
        marker = "/profile/"

        if marker not in text:
            return ""

        after = text.split(marker, 1)[1]
        profile_id = after.split("/", 1)[0].strip()

        return profile_id

    except Exception:
        return ""


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
        ],
        default=0,
    )

    matched_count = read_int_from_profile_info(
        profile_info,
        [
            "records_matched_count",
            "matched_record_count",
            "matched_count",
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

    return {
        "extracted_count": extracted_count,
        "matched_count": matched_count,
        "unmatched_count": unmatched_count,
    }


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

    return {
        "acceptable": acceptable,
        "extracted_count": counts["extracted_count"],
        "matched_count": counts["matched_count"],
        "unmatched_count": counts["unmatched_count"],
        "min_extracted_count": PROFILE_CACHE_MIN_EXTRACTED_COUNT,
        "min_matched_count": PROFILE_CACHE_MIN_MATCHED_COUNT,
    }

def get_profile_parse_result(
    profile_url: str,
    force_refresh: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    """
    maishift 프로필 파싱 결과를 캐시한다.

    개선 사항:
    - profile_id 기준 캐시 key 사용
    - low-quality parse 결과는 캐시하지 않음
    - 기존 good cache가 있고 새 파싱 결과가 low-quality이면 기존 cache를 fallback으로 사용
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
            cached_user_records_df = None
            cached_profile_info = {}
            cached_quality = None

    user_records_df, profile_info = parse_maishift_profile_to_records(
        profile_url=profile_url,
        charts=charts,
    )

    fresh_quality = make_cache_quality_info(
        profile_info=profile_info,
        user_records_df=user_records_df,
    )

    should_store_cache = fresh_quality["acceptable"]

    used_stale_fallback = False

    # force refresh 또는 TTL 만료 후 새 파싱이 low-quality인 경우,
    # 기존 캐시가 acceptable이면 기존 캐시를 fallback으로 사용한다.
    if not should_store_cache and cached is not None:
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


@app.get("/")
def root():
    return {
        "service": "maimai DX Recommender API",
        "status": "running",
        "main_endpoint": "/recommend-by-url",
        "internal_endpoint": "/recommend",
        "docs": "/docs",
        "profile_cache_ttl_seconds": PROFILE_CACHE_TTL_SECONDS,
    }


@app.get("/health")
def health_check():
    try:
        charts = load_charts()

        return {
            "status": "ok",
            "chart_count": int(len(charts)),
            "main_endpoint": "/recommend-by-url",
            "data_mode": "maishift_profile_url",
            "profile_cache_size": len(profile_parse_cache),
            "profile_cache_ttl_seconds": PROFILE_CACHE_TTL_SECONDS,
            "profile_cache_min_extracted_count": PROFILE_CACHE_MIN_EXTRACTED_COUNT,
            "profile_cache_min_matched_count": PROFILE_CACHE_MIN_MATCHED_COUNT
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

    maishift 프로필 URL을 입력받아 records/home 페이지를 파싱하고,
    해당 유저 기록과 cohort 통계를 함께 사용해 추천 결과를 생성한다.

    동일 profile_url에 대해서는 PROFILE_CACHE_TTL_SECONDS 동안 파싱 결과를 캐싱한다.
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

        return result

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"failed to parse profile or generate recommendation: {e}",
        )


def make_profile_parse_warning(profile_info: dict) -> str | None:
    extracted_count = int(profile_info.get("extracted_count", 0) or 0)
    matched_count = int(profile_info.get("matched_count", 0) or 0)

    records_extracted_count = int(profile_info.get("records_extracted_count", 0) or 0)
    records_matched_count = int(profile_info.get("records_matched_count", 0) or 0)
    records_unmatched_count = int(profile_info.get("records_unmatched_count", 0) or 0)

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

    if records_unmatched_count > 0:
        return (
            f"일부 기록은 곡 DB와 매칭되지 않았습니다. "
            f"매칭 실패 records 수: {records_unmatched_count}개. "
            f"주된 원인은 13 미만 채보, 곡명 표기 차이, 또는 DB 범위 밖 채보일 수 있습니다."
        )

    return None