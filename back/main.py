import os
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from maishift_parser import parse_maishift_profile_to_records
from recommender import load_charts, recommend
from schemas import ProfileUrlRecommendRequest, RecommendRequest


PROFILE_CACHE_TTL_SECONDS = int(os.getenv("PROFILE_CACHE_TTL_SECONDS", "3600"))

profile_parse_cache: dict[str, dict[str, Any]] = {}


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


def get_profile_parse_result(
    profile_url: str,
    force_refresh: bool = False,
):
    """
    maishift 프로필 파싱 결과를 profile_url 기준으로 메모리 캐싱한다.

    캐시 대상:
    - user_records_df
    - profile_info

    캐시 목적:
    - 추천 목표, 주력 레벨, 채보 타입만 바꿀 때 maishift 파싱을 반복하지 않도록 한다.
    """
    cache_key = normalize_profile_cache_key(profile_url)
    now = time.time()

    cached = profile_parse_cache.get(cache_key)

    if cached and not force_refresh:
        created_at = float(cached.get("created_at", 0.0))
        age = now - created_at

        if age <= PROFILE_CACHE_TTL_SECONDS:
            user_records_df = cached["user_records_df"].copy()
            profile_info = dict(cached["profile_info"])

            cache_info = {
                "enabled": True,
                "hit": True,
                "cache_key": cache_key,
                "ttl_seconds": PROFILE_CACHE_TTL_SECONDS,
                "age_seconds": int(age),
                "force_refresh": False,
            }

            return user_records_df, profile_info, cache_info

    charts = load_charts()

    user_records_df, profile_info = parse_maishift_profile_to_records(
        profile_url=profile_url,
        charts=charts,
    )

    profile_parse_cache[cache_key] = {
        "created_at": now,
        "user_records_df": user_records_df.copy(),
        "profile_info": dict(profile_info),
    }

    cache_info = {
        "enabled": True,
        "hit": False,
        "cache_key": cache_key,
        "ttl_seconds": PROFILE_CACHE_TTL_SECONDS,
        "age_seconds": 0,
        "force_refresh": bool(force_refresh),
    }

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