from typing import Literal

from pydantic import BaseModel, Field


GoalType = Literal[
    "rating_up",
    "skill_up",
    "weakness",
    "reverse_border",
    "similar_user",
]

MainLevelType = Literal["13", "13+", "14", "14+", "15"]
ChartType = Literal["any", "dx", "std"]
BpmPreference = Literal["any", "slow", "normal", "fast"]


class RecommendRequest(BaseModel):
    goal: GoalType = Field(default="rating_up")
    main_level: MainLevelType = Field(default="14")
    chart_type: ChartType = Field(default="any")

    # 현재 UI에서는 BPM 선호를 제거하지만,
    # 기존 backend 호환성을 위해 필드는 유지한다.
    bpm_preference: BpmPreference = Field(default="any")

    top_n: int = Field(default=10, ge=1, le=30)


class ProfileUrlRecommendRequest(RecommendRequest):
    profile_url: str = Field(
        ...,
        description="maishift profile URL",
    )
    force_refresh: bool = Field(
        default=False,
        description="If true, ignore cached profile parse result and parse maishift again.",
    )