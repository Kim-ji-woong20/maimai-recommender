from typing import Literal

from pydantic import BaseModel, Field


GoalType = Literal["rating_up", "skill_up", "weakness", "reverse_border"]
MainLevelType = Literal["13", "13+", "14", "14+", "15"]
ChartType = Literal["any", "dx", "std"]
BpmPreference = Literal["any", "slow", "normal", "fast"]


class RecommendRequest(BaseModel):
    goal: GoalType = Field(default="rating_up")
    main_level: MainLevelType = Field(default="14")
    chart_type: ChartType = Field(default="any")
    bpm_preference: BpmPreference = Field(default="any")
    top_n: int = Field(default=10, ge=1, le=30)


class ProfileUrlRecommendRequest(RecommendRequest):
    profile_url: str = Field(
        ...,
        description="maishift profile URL. Example: https://maimai.shiftpsh.com/profile/kong3171/home",
    )

    force_refresh: bool = Field(
        default=False,
        description="If true, ignore cached profile parse result and parse maishift again.",
    )