from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from maishift_parser import parse_maishift_profile_to_records
from recommender import load_charts, recommend
from schemas import ProfileUrlRecommendRequest, RecommendRequest


app = FastAPI(
    title="maimai DX Recommendation API",
    description="maishift profile and cohort-stat based maimai DX chart recommender",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "message": "maimai DX Recommendation API",
        "endpoints": [
            "/health",
            "/recommend",
            "/recommend-by-url",
        ],
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
    }


@app.post("/recommend")
def recommend_default_user(req: RecommendRequest):
    """
    기본 CSV 유저 기록 기반 추천.
    현재는 back/data/sample_user_records.csv 또는 current_user_records.csv를 사용하는 fallback endpoint.
    """
    try:
        return recommend(req)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"recommendation failed: {str(e)}",
        )


@app.post("/recommend-by-url")
def recommend_by_profile_url(req: ProfileUrlRecommendRequest):
    """
    maishift profile URL을 입력받아 해당 유저의 Best 50을 실시간 파싱한 뒤 추천한다.
    """
    try:
        charts = load_charts()
        user_records_df, profile_info = parse_maishift_profile_to_records(
            profile_url=req.profile_url,
            charts=charts,
        )

        result = recommend(
            req=req,
            user_records_df=user_records_df,
            user_rating=profile_info.get("rating"),
        )

        result["input_profile"] = profile_info

        if profile_info.get("unmatched_count", 0) > 0:
            result["profile_parse_warning"] = (
                f"{profile_info['extracted_count']}개 기록 중 "
                f"{profile_info['matched_count']}개가 곡 DB와 매칭되었고, "
                f"{profile_info['unmatched_count']}개는 매칭되지 않았습니다."
            )

        return result

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"profile URL recommendation failed: {str(e)}",
        )