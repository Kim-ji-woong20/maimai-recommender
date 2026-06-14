from __future__ import annotations

import html
import math
import os
from io import BytesIO
from typing import Any

import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageFont, ImageOps


API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

APP_TITLE = "Maigym"


GOAL_OPTIONS = {
    "레이팅 상승": "rating_up",
    "실력 향상": "skill_up",
    "약점 보완": "weakness",
    "역보더 탐색": "reverse_border",
    "나와 비슷한 유저 추천": "similar_user",
}


CHART_TYPE_OPTIONS = {
    "상관없음": "any",
    "DX": "dx",
    "STANDARD": "std",
}


MAIN_LEVEL_OPTIONS = [
    "13",
    "13+",
    "14",
    "14+",
    "15",
]


def escape_html(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def inject_global_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Noto+Sans+JP:wght@400;500;700;800&family=Noto+Sans+KR:wght@400;500;700;800&display=swap');

        :root {
            --mg-bg: #050814;
            --mg-panel: rgba(17, 24, 39, 0.92);
            --mg-panel-2: rgba(21, 32, 52, 0.84);
            --mg-border: rgba(125, 159, 255, 0.26);
            --mg-cyan: #5ce1ff;
            --mg-blue: #4f8cff;
            --mg-purple: #9d72ff;
            --mg-text: #edf4ff;
            --mg-muted: #9fb0c8;
            --mg-dim: #738199;
        }

        html, body, [class*="css"] {
            font-family: "Inter", "Noto Sans KR", "Noto Sans JP", system-ui, sans-serif;
        }

        .stApp {
            background:
                linear-gradient(135deg, rgba(14, 32, 66, 0.88) 0%, rgba(5, 8, 20, 1) 38%, rgba(22, 14, 46, 0.96) 100%);
            color: var(--mg-text);
        }

        .block-container {
            max-width: 1180px;
            padding-top: 2rem;
            padding-bottom: 4rem;
        }

        header[data-testid="stHeader"] {
            background: transparent;
        }

        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #070b19 0%, #0b1427 52%, #100c24 100%);
            border-right: 1px solid rgba(120, 160, 255, 0.18);
        }

        section[data-testid="stSidebar"] > div {
            padding-top: 1.5rem;
        }

        .sidebar-brand {
            border: 1px solid rgba(92, 225, 255, 0.22);
            border-radius: 14px;
            padding: 16px 16px 14px;
            background: linear-gradient(135deg, rgba(79, 140, 255, 0.16), rgba(157, 114, 255, 0.14));
            margin-bottom: 18px;
        }

        .sidebar-brand strong {
            display: block;
            color: var(--mg-text);
            font-size: 1.15rem;
            letter-spacing: 0;
        }

        .sidebar-brand span {
            color: var(--mg-cyan);
            font-size: 0.78rem;
            font-weight: 700;
            text-transform: uppercase;
        }

        .maigym-hero {
            border: 1px solid var(--mg-border);
            border-radius: 18px;
            background:
                linear-gradient(135deg, rgba(21, 34, 60, 0.94), rgba(18, 20, 43, 0.92));
            padding: 30px 32px;
            margin-bottom: 22px;
            box-shadow: 0 24px 70px rgba(0, 0, 0, 0.34);
        }

        .hero-kicker,
        .section-kicker {
            color: var(--mg-cyan);
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0;
            text-transform: uppercase;
        }

        .maigym-hero h1 {
            margin: 6px 0 8px;
            color: var(--mg-text);
            font-size: 3.8rem;
            line-height: 1;
            font-weight: 800;
            letter-spacing: 0;
        }

        .maigym-hero p {
            max-width: 760px;
            color: var(--mg-muted);
            margin: 0;
            font-size: 1.04rem;
            line-height: 1.65;
        }

        .hero-chip-row,
        .stat-strip {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 18px;
        }

        .hero-chip,
        .stat-chip {
            border: 1px solid rgba(125, 159, 255, 0.26);
            border-radius: 999px;
            background: rgba(8, 14, 30, 0.62);
            color: #dce8ff;
            padding: 7px 11px;
            font-size: 0.82rem;
            font-weight: 700;
        }

        .hero-chip.is-cyan {
            border-color: rgba(92, 225, 255, 0.36);
            color: #bff5ff;
        }

        .hero-chip.is-purple {
            border-color: rgba(157, 114, 255, 0.44);
            color: #dfd3ff;
        }

        .section-heading {
            display: flex;
            align-items: end;
            justify-content: space-between;
            gap: 16px;
            margin: 24px 0 12px;
        }

        .section-heading h2 {
            color: var(--mg-text);
            font-size: 1.35rem;
            font-weight: 800;
            margin: 2px 0 0;
            letter-spacing: 0;
        }

        .section-count {
            color: var(--mg-dim);
            font-size: 0.85rem;
            font-weight: 700;
        }

        .profile-panel,
        .empty-panel {
            border: 1px solid var(--mg-border);
            border-radius: 14px;
            background: rgba(12, 19, 36, 0.74);
            padding: 18px 18px 16px;
            margin: 14px 0 12px;
        }

        .profile-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 10px;
            margin-top: 12px;
        }

        .profile-stat {
            border-left: 2px solid rgba(92, 225, 255, 0.55);
            background: rgba(255, 255, 255, 0.035);
            border-radius: 10px;
            padding: 10px 12px;
        }

        .profile-stat span,
        .stat-chip span {
            display: block;
            color: var(--mg-dim);
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
        }

        .profile-stat strong,
        .stat-chip strong {
            color: var(--mg-text);
            font-size: 1rem;
            font-weight: 800;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-color: rgba(125, 159, 255, 0.26);
            border-radius: 14px;
            background: linear-gradient(180deg, rgba(22, 31, 50, 0.92), rgba(18, 24, 39, 0.94));
            box-shadow: 0 14px 34px rgba(0, 0, 0, 0.22);
        }

        div[data-testid="stImage"] img {
            border-radius: 10px;
            border: 1px solid rgba(125, 159, 255, 0.22);
        }

        .song-title {
            display: flex;
            align-items: center;
            gap: 10px;
            margin: 2px 0 4px;
        }

        .song-rank {
            color: var(--mg-purple);
            font-size: 1.4rem;
            font-weight: 800;
            min-width: 38px;
        }

        .song-title strong {
            color: var(--mg-text);
            font-size: 1.24rem;
            line-height: 1.3;
            font-weight: 800;
        }

        .song-artist,
        .song-meta {
            color: var(--mg-muted);
            font-size: 0.9rem;
            margin-left: 48px;
        }

        .song-meta {
            color: var(--mg-dim);
            margin-top: 2px;
        }

        .song-reason {
            border-left: 2px solid rgba(92, 225, 255, 0.7);
            background: rgba(92, 225, 255, 0.06);
            border-radius: 10px;
            color: #c9d8ef;
            margin-top: 12px;
            padding: 10px 12px;
            font-size: 0.9rem;
            line-height: 1.55;
        }

        .song-reason strong {
            color: #dff8ff;
        }

        div[data-testid="stMetric"] {
            background: rgba(255, 255, 255, 0.035);
            border: 1px solid rgba(125, 159, 255, 0.18);
            border-radius: 12px;
            padding: 8px 10px;
        }

        div[data-testid="stExpander"] details {
            border-color: rgba(125, 159, 255, 0.24);
            background: rgba(8, 14, 30, 0.58);
            border-radius: 12px;
        }

        .stButton button,
        .stDownloadButton button,
        div[data-testid="stFormSubmitButton"] button {
            border: 1px solid rgba(92, 225, 255, 0.35);
            background: linear-gradient(135deg, var(--mg-blue), var(--mg-purple));
            color: white;
            border-radius: 10px;
            font-weight: 800;
        }

        .stButton button:focus,
        .stDownloadButton button:focus,
        div[data-testid="stFormSubmitButton"] button:focus {
            border-color: rgba(92, 225, 255, 0.72);
            box-shadow: 0 0 0 2px rgba(92, 225, 255, 0.18);
            outline: none;
        }

        .stTextInput input,
        .stSelectbox div[data-baseweb="select"] > div {
            background: rgba(8, 14, 30, 0.78);
            border-color: rgba(125, 159, 255, 0.28);
            color: var(--mg-text);
        }

        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
        section[data-testid="stSidebar"] .stCheckbox p {
            color: var(--mg-muted);
            font-weight: 700;
        }

        .stTextInput input::placeholder {
            color: rgba(159, 176, 200, 0.55);
            opacity: 1;
        }

        div[data-testid="stSlider"] [data-testid="stThumbValue"] {
            color: var(--mg-cyan) !important;
            font-weight: 800;
        }

        div[data-testid="stSlider"] div[role="slider"] {
            background-color: var(--mg-cyan) !important;
            border-color: var(--mg-cyan) !important;
            box-shadow: 0 0 0 4px rgba(92, 225, 255, 0.14) !important;
        }

        div[data-testid="stSlider"] div[data-baseweb="slider"] div[style*="rgb(255, 75, 75)"],
        div[data-testid="stSlider"] div[data-baseweb="slider"] div[style*="#ff4b4b"] {
            background-color: var(--mg-cyan) !important;
            color: var(--mg-cyan) !important;
            border-color: var(--mg-cyan) !important;
        }

        div[data-testid="stAlert"] {
            border: 1px solid rgba(251, 191, 36, 0.24);
            border-radius: 12px;
            background: rgba(251, 191, 36, 0.10);
            color: #f8d98a;
        }

        div[data-testid="stAlert"] p {
            color: #f8d98a;
        }

        @media (max-width: 820px) {
            .maigym-hero h1 {
                font-size: 2.8rem;
            }

            .profile-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def call_recommend_by_url(payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{API_BASE_URL}/recommend-by-url"

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=180,
        )

    except requests.exceptions.Timeout as exc:
        raise RuntimeError(
            "백엔드 응답 시간이 초과되었습니다. maishift 프로필 파싱에 시간이 오래 걸렸을 수 있습니다."
        ) from exc

    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError(
            f"백엔드 서버에 연결할 수 없습니다. 백엔드가 실행 중인지 확인하세요. API 주소: {url}"
        ) from exc

    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"백엔드 요청 중 오류가 발생했습니다: {exc}") from exc

    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(
            f"백엔드 응답을 JSON으로 해석할 수 없습니다. "
            f"status={response.status_code}, text={response.text[:500]}"
        ) from exc

    if response.status_code >= 400:
        detail = data.get("detail", data)
        raise RuntimeError(f"추천 생성 실패: {detail}")

    return data


def format_score(value: Any, played: bool = True) -> str:
    if not played:
        return "-"

    try:
        return f"{float(value):.4f}%"
    except Exception:
        return "-"


def format_number(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return "-"


def bool_to_text(value: Any) -> str:
    return "예" if bool(value) else "아니오"


def extract_profile_id_from_url(url: Any) -> str:
    try:
        text = str(url).strip()
        marker = "/profile/"

        if marker not in text:
            return ""

        after = text.split(marker, 1)[1]
        profile_id = after.split("/", 1)[0].strip()

        return profile_id

    except Exception:
        return ""


def extract_profile_id_from_cache_key(cache_key: Any) -> str:
    try:
        text = str(cache_key).strip()

        if text.startswith("profile:"):
            return text.split("profile:", 1)[1].strip()

        return ""

    except Exception:
        return ""


def get_goal_display_label(goal: Any) -> str:
    reverse_goal_options = {
        value: key
        for key, value in GOAL_OPTIONS.items()
    }

    return reverse_goal_options.get(str(goal), str(goal or "-"))


def goal_empty_message(goal: str) -> str:
    if goal == "reverse_border":
        return (
            "역보더 후보가 없습니다. "
            "현재 선택한 레벨/채보 타입 조건에서 100.4000% 이상 100.5000% 미만인 곡을 찾지 못했습니다."
        )

    if goal == "similar_user":
        return (
            "나와 비슷한 유저 추천 결과가 없습니다. "
            "입력 유저의 Best50 매칭 수가 부족하거나, "
            "현재 DB에서 유사한 기록 패턴의 유저를 충분히 찾지 못했을 수 있습니다. "
            "다른 레벨을 선택하거나 DB 업데이트 후 다시 시도해보세요."
        )

    if goal == "weakness":
        return (
            "약점 보완 후보가 없습니다. "
            "현재 선택한 조건에서 비교 가능한 플레이 기록이 부족할 수 있습니다."
        )

    if goal == "skill_up":
        return (
            "실력 향상 추천 결과가 없습니다. "
            "주력 레벨 또는 채보 타입 조건을 완화해서 다시 시도해보세요."
        )

    return (
        "추천 결과가 없습니다. "
        "주력 레벨, 채보 타입, 추천 목표를 바꿔 다시 시도해보세요."
    )


def render_section_heading(title: str, kicker: str, count_text: str = "") -> None:
    count_html = (
        f'<div class="section-count">{escape_html(count_text)}</div>'
        if count_text
        else ""
    )
    st.markdown(
        f"""
        <div class="section-heading">
            <div>
                <div class="section-kicker">{escape_html(kicker)}</div>
                <h2>{escape_html(title)}</h2>
            </div>
            {count_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_stat_strip(items: list[tuple[str, Any]]) -> None:
    chips = "".join(
        (
            '<div class="stat-chip">'
            f"<span>{escape_html(label)}</span>"
            f"<strong>{escape_html(value)}</strong>"
            "</div>"
        )
        for label, value in items
    )
    st.markdown(
        f'<div class="stat-strip">{chips}</div>',
        unsafe_allow_html=True,
    )


def render_empty_state() -> None:
    st.markdown(
        """
        <div class="empty-panel">
            <div class="section-kicker">READY</div>
            <h2 style="margin: 4px 0 6px; color: var(--mg-text);">Maigym console</h2>
            <p style="margin: 0; color: var(--mg-muted);">
                maishift 프로필 기반 추천 결과가 이곳에 표시됩니다.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_profile_info(result: dict[str, Any], developer_mode: bool = False) -> None:
    profile = result.get("input_profile") or {}

    if not profile:
        return

    cache_info = result.get("profile_cache") or {}

    profile_url = (
        profile.get("profile_url")
        or profile.get("url")
        or profile.get("home_url")
        or ""
    )

    profile_id = (
        profile.get("profile_id")
        or profile.get("profileId")
        or profile.get("id")
        or extract_profile_id_from_url(profile_url)
        or extract_profile_id_from_cache_key(cache_info.get("cache_key", ""))
    )

    nickname = (
        profile.get("nickname")
        or profile.get("user_name")
        or profile.get("username")
        or profile.get("name")
        or profile_id
        or "-"
    )

    rating = profile.get("rating", "-")

    extracted_count = (
        profile.get("records_extracted_count")
        or profile.get("extracted_record_count")
        or profile.get("records_count")
        or 0
    )

    matched_count = (
        profile.get("records_matched_count")
        or profile.get("matched_record_count")
        or 0
    )

    unmatched_count = (
        profile.get("records_unmatched_count")
        or profile.get("unmatched_record_count")
        or 0
    )

    render_section_heading("입력 프로필", "Profile")

    stats = [
        ("프로필", nickname),
        ("Rating", rating),
        ("추출 기록", extracted_count),
        ("매칭 기록", matched_count),
    ]
    stat_cards = "".join(
        (
            '<div class="profile-stat">'
            f"<span>{escape_html(label)}</span>"
            f"<strong>{escape_html(value)}</strong>"
            "</div>"
        )
        for label, value in stats
    )
    st.markdown(
        f"""
        <div class="profile-panel">
            <div class="profile-grid">{stat_cards}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    warning = result.get("profile_parse_warning")

    if warning:
        st.warning(warning)

    if developer_mode:
        with st.expander("개발자용 프로필 파싱 정보", expanded=False):
            st.write(f"미매칭 기록 수: {unmatched_count}")
            st.json(profile)


def render_applied_conditions(result: dict[str, Any]) -> None:
    debug = result.get("debug", {})

    goal = result.get("goal", "-")
    main_level = debug.get("selected_main_level", "-")
    chart_type = debug.get("selected_chart_type", "-")
    current_band = debug.get("current_band", "-")
    target_band = debug.get("target_band", "-")

    render_section_heading("적용된 추천 조건", "Conditions")
    render_stat_strip([
        ("추천 목표", get_goal_display_label(goal)),
        ("주력 레벨", main_level),
        ("채보 타입", str(chart_type).upper()),
        ("레이팅 구간", f"{current_band} → {target_band}"),
    ])


def render_recommendation_card(rec: dict[str, Any], developer_mode: bool = False) -> None:
    rank = rec.get("rank")
    title = rec.get("title")
    artist = rec.get("artist", "")

    difficulty = rec.get("difficulty")
    level = rec.get("display_level") or rec.get("level")
    internal_level = rec.get("internal_level")
    chart_type = rec.get("chart_type")

    version = rec.get("sheet_version") or rec.get("version") or "-"
    song_version = rec.get("version") or "-"
    category = rec.get("category") or "-"
    release_date = rec.get("release_date") or "-"
    thumbnail_url = rec.get("thumbnail_url") or ""

    played = bool(rec.get("played", False))
    is_best50 = bool(rec.get("is_best50", False))
    achievement = rec.get("achievement", 0.0)

    reverse_border = bool(rec.get("reverse_border", False))
    reverse_border_gap = rec.get("reverse_border_gap", 0.0)

    reason = rec.get("reason", "")
    target = rec.get("target", "")

    with st.container(border=True):
        image_col, info_col = st.columns([1, 6])

        with image_col:
            if thumbnail_url:
                st.image(thumbnail_url, width=140)
            else:
                st.caption("No image")

        with info_col:
            reverse_badge = (
                '<span class="hero-chip is-purple">역보더</span>'
                if reverse_border
                else ""
            )
            st.markdown(
                f"""
                <div class="song-title">
                    <span class="song-rank">{escape_html(rank)}.</span>
                    <strong>{escape_html(title)}</strong>
                    {reverse_badge}
                </div>
                """,
                unsafe_allow_html=True,
            )

            if artist:
                st.markdown(
                    f'<div class="song-artist">{escape_html(artist)}</div>',
                    unsafe_allow_html=True,
                )

            st.markdown(
                (
                    '<div class="song-meta">'
                    f"{escape_html(version)} · {escape_html(str(chart_type).upper())} · "
                    f"{escape_html(str(difficulty).upper())} · {escape_html(category)}"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )

            render_stat_strip([
                ("레벨", level),
                ("내부상수", internal_level),
                ("타입", str(chart_type).upper()),
                ("달성률", format_score(achievement, played)),
                ("Best 50", bool_to_text(is_best50)),
            ])

            if reverse_border:
                try:
                    st.markdown(
                        (
                            '<div class="song-reason">'
                            f"<strong>100.5%까지</strong> {float(reverse_border_gap):.4f}% 남았습니다."
                            "</div>"
                        ),
                        unsafe_allow_html=True,
                    )
                except Exception:
                    pass

            if reason:
                target_text = f"<strong>{escape_html(target)}</strong> · " if target else ""
                st.markdown(
                    (
                        '<div class="song-reason">'
                        f"{target_text}{escape_html(reason)}"
                        "</div>"
                    ),
                    unsafe_allow_html=True,
                )

            if developer_mode:
                with st.expander("개발자용 추천 상세", expanded=False):
                    st.write(f"Chart ID: {rec.get('chart_id')}")
                    st.write(f"Song ID: {rec.get('song_id')}")
                    st.write(f"BPM: {rec.get('bpm')}")
                    st.write(f"곡 최초 수록 버전: {song_version}")
                    st.write(f"채보 버전: {version}")
                    st.write(f"발매일: {release_date}")
                    st.write(f"카테고리: {category}")
                    st.write(f"이미지 URL: {thumbnail_url}")
                    st.write(f"추천점수: {rec.get('recommend_score')}")
                    st.write(f"후보 유형: {rec.get('candidate_label')}")
                    st.write(f"현재 곡별 레이팅: {rec.get('current_rating')}")
                    st.write(f"100.5% 기준 최대 레이팅: {rec.get('max_rating')}")
                    st.write(f"레이팅 상승 여지: {rec.get('rating_gain')}")
                    st.write(f"현재 레이팅 구간 Best50 등장률: {rec.get('current_best50_rate')}")
                    st.write(f"상위 레이팅 구간 Best50 등장률: {rec.get('target_best50_rate')}")
                    st.write(f"현재 레이팅 구간 평균 달성률: {rec.get('current_avg_achievement')}")
                    st.write(f"상위 레이팅 구간 평균 달성률: {rec.get('target_avg_achievement')}")
                    st.write(f"협업 필터링 점수: {rec.get('collaborative_score')}")
                    st.write(f"유사 유저 Best50 가중 등장률: {rec.get('similar_user_weighted_rate')}")
                    st.write(f"유사 유저 중 해당 곡 보유 수: {rec.get('similar_user_chart_count')}")
                    st.write(f"유사 유저 수: {rec.get('similar_user_count')}")
                    st.write(f"유사 유저 평균 유사도: {rec.get('similar_user_avg_similarity')}")
                    st.write(f"목표: {target}")
                    st.write(f"추천 이유: {reason}")


def render_recommendations(result: dict[str, Any], developer_mode: bool = False) -> None:
    recommendations = result.get("recommendations", [])

    render_section_heading(
        "추천 결과",
        "Recommendations",
        f"{len(recommendations)} charts" if recommendations else "",
    )

    summary = result.get("summary", "")

    if developer_mode and summary:
        st.info(summary)

    if not recommendations:
        st.warning(goal_empty_message(result.get("goal", "")))
        return

    for rec in recommendations:
        render_recommendation_card(
            rec=rec,
            developer_mode=developer_mode,
        )


FONT_PATHS = {
    "korean_bold": [
        "C:/Windows/Fonts/malgunbd.ttf",
        "C:/Windows/Fonts/NotoSansKR-VF.ttf",
    ],
    "korean_regular": [
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/NotoSansKR-VF.ttf",
    ],
    "japanese_bold": [
        "C:/Windows/Fonts/NotoSansJP-VF.ttf",
        "C:/Windows/Fonts/meiryob.ttc",
        "C:/Windows/Fonts/YuGothB.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
    ],
    "japanese_regular": [
        "C:/Windows/Fonts/NotoSansJP-VF.ttf",
        "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/YuGothR.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
    ],
    "linux_bold": [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Bold.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Bold.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansJP-Bold.otf",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Bold.otf",
    ],
    "linux_regular": [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansJP-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.otf",
    ],
    "common_bold": [
        "C:/Windows/Fonts/Arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
    "common_regular": [
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
}


def apply_variable_font_weight(
    font: ImageFont.FreeTypeFont,
    bold: bool,
) -> ImageFont.FreeTypeFont:
    try:
        axes = font.get_variation_axes()
    except Exception:
        return font

    values = []
    has_weight_axis = False

    for axis in axes or []:
        name = axis.get("name", b"")
        if isinstance(name, bytes):
            name = name.decode("utf-8", errors="ignore")
        name = str(name).lower()

        axis_value = axis.get("default", axis.get("minimum", 0))
        if "weight" in name or "wght" in name:
            minimum = axis.get("minimum", axis_value)
            maximum = axis.get("maximum", axis_value)
            axis_value = max(minimum, min(maximum, 700 if bold else 400))
            has_weight_axis = True

        values.append(axis_value)

    if has_weight_axis:
        try:
            font.set_variation_by_axes(values)
        except Exception:
            return font

    return font


def iter_font_candidates(bold: bool, prefer_japanese: bool) -> list[str]:
    weight = "bold" if bold else "regular"
    env_key = "MAIGYM_FONT_BOLD" if bold else "MAIGYM_FONT_REGULAR"

    ordered_groups = (
        ["japanese", "linux", "korean", "common"]
        if prefer_japanese
        else ["korean", "linux", "japanese", "common"]
    )

    candidates = []
    env_font_path = os.getenv(env_key)
    if env_font_path:
        candidates.append(env_font_path)

    for group in ordered_groups:
        candidates.extend(FONT_PATHS[f"{group}_{weight}"])

    return candidates


def find_font(
    size: int,
    bold: bool = False,
    prefer_japanese: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    PNG 렌더링용 폰트를 고른다.

    Pillow는 브라우저처럼 글자별 fallback을 하지 않으므로, UI 문구는 한글
    폰트를 우선하고 악곡 정보는 일본어 CJK 폰트를 우선한다.
    """
    for path in iter_font_candidates(bold=bold, prefer_japanese=prefer_japanese):
        try:
            if path and os.path.exists(path):
                font = ImageFont.truetype(path, size=size)
                return apply_variable_font_weight(font, bold)
        except Exception:
            continue

    return ImageFont.load_default()


def get_profile_display_name_for_image(result: dict[str, Any]) -> str:
    profile = result.get("input_profile") or {}
    cache_info = result.get("profile_cache") or {}

    profile_url = (
        profile.get("profile_url")
        or profile.get("url")
        or profile.get("home_url")
        or ""
    )

    profile_id = (
        profile.get("profile_id")
        or profile.get("profileId")
        or profile.get("id")
        or extract_profile_id_from_url(profile_url)
        or extract_profile_id_from_cache_key(cache_info.get("cache_key", ""))
    )

    return (
        profile.get("nickname")
        or profile.get("user_name")
        or profile.get("username")
        or profile.get("name")
        or profile_id
        or "-"
    )


def fetch_thumbnail_cover(url: str, size: tuple[int, int]) -> Image.Image:
    width, height = size

    if not url:
        return Image.new("RGB", size, (36, 42, 54))

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        source = Image.open(BytesIO(response.content)).convert("RGB")
        resampling = getattr(Image, "Resampling", Image).LANCZOS

        return ImageOps.fit(
            source,
            size,
            method=resampling,
            centering=(0.5, 0.5),
        )

    except Exception:
        return Image.new("RGB", size, (36, 42, 54))


def draw_text_ellipsis(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: Any,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int],
    max_width: int,
) -> None:
    value = str(text or "").strip()

    if not value:
        return

    if draw.textbbox((0, 0), value, font=font)[2] <= max_width:
        draw.text(position, value, font=font, fill=fill)
        return

    ellipsis = "…"

    while value:
        candidate = value + ellipsis
        bbox = draw.textbbox((0, 0), candidate, font=font)
        width = bbox[2] - bbox[0]

        if width <= max_width:
            draw.text(position, candidate, font=font, fill=fill)
            return

        value = value[:-1]

    draw.text(position, ellipsis, font=font, fill=fill)


def build_result_image(result: dict[str, Any]) -> bytes:
    recommendations = result.get("recommendations", [])
    profile = result.get("input_profile") or {}
    debug = result.get("debug", {})

    if not recommendations:
        image = Image.new("RGB", (1080, 360), (18, 23, 34))
        draw = ImageDraw.Draw(image)

        title_font = find_font(44, bold=True)
        text_font = find_font(24, bold=False)

        draw.text(
            (40, 40),
            APP_TITLE,
            font=title_font,
            fill=(238, 242, 250),
        )

        draw.text(
            (40, 112),
            "No recommendations",
            font=text_font,
            fill=(160, 169, 185),
        )

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)

        return buffer.getvalue()

    width = 1200
    padding = 36
    columns = 5
    card_gap = 14

    card_width = int(
        (width - padding * 2 - card_gap * (columns - 1)) / columns
    )
    card_height = 214

    header_height = 156
    section_height = 52

    row_count = math.ceil(len(recommendations) / columns)

    height = (
        padding
        + header_height
        + section_height
        + row_count * card_height
        + max(0, row_count - 1) * card_gap
        + padding
    )

    bg_color = (17, 22, 33)
    panel_color = (25, 31, 44)
    card_color = (31, 38, 53)
    card_border = (56, 66, 86)

    text_main = (238, 242, 250)
    text_sub = (166, 176, 195)
    text_muted = (115, 126, 148)

    accent = (130, 93, 255)
    accent_soft = (72, 52, 140)

    image = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(image)

    title_font = find_font(48, bold=True)
    subtitle_font = find_font(24, bold=False)
    section_font = find_font(25, bold=True)
    rank_font = find_font(27, bold=True)
    song_font = find_font(20, bold=True, prefer_japanese=True)
    meta_font = find_font(15, bold=False, prefer_japanese=True)
    small_font = find_font(14, bold=False)

    nickname = get_profile_display_name_for_image(result)
    rating = profile.get("rating", "-")
    goal_label = get_goal_display_label(result.get("goal", ""))
    main_level = debug.get("selected_main_level", "-")
    chart_type = str(debug.get("selected_chart_type", "-")).upper()

    header_x = padding
    header_y = padding
    header_w = width - padding * 2

    draw.rounded_rectangle(
        (header_x, header_y, header_x + header_w, header_y + header_height),
        radius=22,
        fill=panel_color,
        outline=(45, 54, 74),
        width=1,
    )

    draw.text(
        (header_x + 28, header_y + 24),
        APP_TITLE,
        font=title_font,
        fill=text_main,
    )

    draw.text(
        (header_x + 30, header_y + 86),
        f"{nickname} · Rating {rating}",
        font=subtitle_font,
        fill=text_sub,
    )

    badge_text = f"{goal_label} · Lv {main_level} · {chart_type}"
    badge_font = find_font(18, bold=True)
    badge_bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
    badge_text_max_w = max(180, min(360, header_w - 480))
    badge_text_w = min(badge_bbox[2] - badge_bbox[0], badge_text_max_w)
    badge_w = badge_text_w + 28
    badge_h = 38
    badge_x = header_x + header_w - badge_w - 28
    badge_y = header_y + 32

    draw.rounded_rectangle(
        (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
        radius=14,
        fill=accent_soft,
    )

    draw_text_ellipsis(
        draw=draw,
        position=(badge_x + 14, badge_y + 8),
        text=badge_text,
        font=badge_font,
        fill=(232, 226, 255),
        max_width=badge_w - 28,
    )

    section_y = header_y + header_height + 22

    draw.text(
        (padding, section_y),
        "RECOMMENDATIONS",
        font=section_font,
        fill=text_main,
    )

    chart_count_text = f"{len(recommendations)} charts"
    chart_count_bbox = draw.textbbox(
        (0, 0),
        chart_count_text,
        font=small_font,
    )
    chart_count_w = chart_count_bbox[2] - chart_count_bbox[0]

    draw.text(
        (width - padding - chart_count_w, section_y + 5),
        chart_count_text,
        font=small_font,
        fill=text_muted,
    )

    grid_y = section_y + section_height

    cover_width = card_width - 22
    cover_height = 104

    for idx, rec in enumerate(recommendations):
        row = idx // columns
        col = idx % columns

        x = padding + col * (card_width + card_gap)
        y = grid_y + row * (card_height + card_gap)

        draw.rounded_rectangle(
            (x, y, x + card_width, y + card_height),
            radius=18,
            fill=card_color,
            outline=card_border,
            width=1,
        )

        cover_x = x + 11
        cover_y = y + 11

        cover = fetch_thumbnail_cover(
            rec.get("thumbnail_url", ""),
            size=(cover_width, cover_height),
        )

        image.paste(cover, (cover_x, cover_y))

        overlay_h = 44
        overlay_y = cover_y + cover_height - overlay_h

        draw.rectangle(
            (cover_x, overlay_y, cover_x + cover_width, cover_y + cover_height),
            fill=(0, 0, 0),
        )

        level = rec.get("display_level") or rec.get("level") or "-"
        internal_level = rec.get("internal_level", "-")
        chart_type_value = str(rec.get("chart_type", "-")).upper()

        played = bool(rec.get("played", False))
        achievement = format_score(rec.get("achievement", 0.0), played)

        # 카드 폭이 좁기 때문에 점수 표기는 한 줄 내에서 겹치지 않도록 고정 배치한다.
        line1 = f"Lv {level} · {chart_type_value}"
        line2_left = f"DS {internal_level}"
        line2_right = achievement if achievement != "-" else ""

        overlay_font = find_font(13, bold=True)
        overlay_small_font = find_font(12, bold=False)

        draw.text(
            (cover_x + 8, overlay_y + 6),
            line1,
            font=overlay_font,
            fill=(245, 247, 252),
        )

        draw.text(
            (cover_x + 8, overlay_y + 25),
            line2_left,
            font=overlay_small_font,
            fill=(210, 216, 228),
        )

        if line2_right:
            score_bbox = draw.textbbox((0, 0), line2_right, font=overlay_small_font)
            score_w = score_bbox[2] - score_bbox[0]

            draw.text(
                (cover_x + cover_width - score_w - 8, overlay_y + 25),
                line2_right,
                font=overlay_small_font,
                fill=(245, 247, 252),
            )

        rank = rec.get("rank", idx + 1)
        title = rec.get("title", "")
        artist = rec.get("artist", "")

        title_x = x + 14
        title_y = cover_y + cover_height + 16

        draw.text(
            (title_x, title_y),
            f"{rank}.",
            font=rank_font,
            fill=accent,
        )

        draw_text_ellipsis(
            draw=draw,
            position=(title_x + 44, title_y + 2),
            text=title,
            font=song_font,
            fill=text_main,
            max_width=card_width - 62,
        )

        draw_text_ellipsis(
            draw=draw,
            position=(title_x + 44, title_y + 31),
            text=artist,
            font=meta_font,
            fill=text_sub,
            max_width=card_width - 62,
        )

        version = rec.get("sheet_version") or rec.get("version") or "-"
        chart_type_value = str(rec.get("chart_type", "-")).upper()
        difficulty = str(rec.get("difficulty", "-")).upper()

        meta = f"{version} · {chart_type_value} · {difficulty}"

        draw_text_ellipsis(
            draw=draw,
            position=(title_x + 44, title_y + 55),
            text=meta,
            font=meta_font,
            fill=text_muted,
            max_width=card_width - 62,
        )

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    return buffer.getvalue()


def render_result_image(result: dict[str, Any]) -> None:
    recommendations = result.get("recommendations", [])

    if not recommendations:
        return

    image_bytes = build_result_image(result)

    with st.expander("이미지 결과", expanded=False):
        st.image(image_bytes)
        st.download_button(
            label="PNG 저장",
            data=image_bytes,
            file_name="maigym_result.png",
            mime="image/png",
        )


def render_cache_info(result: dict[str, Any], developer_mode: bool = False) -> None:
    if not developer_mode:
        return

    cache_info = result.get("profile_cache")

    if not cache_info:
        return

    with st.expander("개발자용 프로필 캐시 정보", expanded=False):
        st.json(cache_info)


def render_debug_info(result: dict[str, Any], developer_mode: bool = False) -> None:
    if not developer_mode:
        return

    debug = result.get("debug")

    if not debug:
        return

    with st.expander("개발자용 디버그 정보", expanded=False):
        st.json(debug)


def render_raw_response(result: dict[str, Any], developer_mode: bool = False) -> None:
    if not developer_mode:
        return

    with st.expander("개발자용 원본 응답", expanded=False):
        st.json(result)


def render_sidebar_form() -> dict[str, Any] | None:
    st.sidebar.markdown(
        """
        <div class="sidebar-brand">
            <span>maimai DX</span>
            <strong>Maigym</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar.form("recommend_form"):
        profile_url = st.text_input(
            "maishift 프로필 URL",
            placeholder="https://maimai.shiftpsh.com/profile/xxxx/home",
        )

        goal_label = st.selectbox(
            "추천 목표",
            list(GOAL_OPTIONS.keys()),
            index=0,
        )

        main_level = st.selectbox(
            "주력 레벨",
            MAIN_LEVEL_OPTIONS,
            index=2,
        )

        chart_type_label = st.selectbox(
            "채보 타입",
            list(CHART_TYPE_OPTIONS.keys()),
            index=0,
        )

        top_n = st.slider(
            "추천 개수",
            min_value=1,
            max_value=30,
            value=10,
            step=1,
        )

        force_refresh = st.checkbox(
            "프로필 캐시 무시하고 새로 파싱",
            value=False,
            help=(
                "같은 프로필 URL은 기본적으로 백엔드 캐시를 사용합니다. "
                "최신 기록을 강제로 다시 가져오고 싶을 때만 체크하세요."
            ),
        )

        developer_mode = st.checkbox(
            "개발자 모드",
            value=False,
            help="payload, 파싱 정보, 디버그 정보, 원본 응답을 표시합니다.",
        )

        submitted = st.form_submit_button(
            "추천 생성",
            type="primary",
            use_container_width=True,
        )

    if not submitted:
        return None

    if not profile_url.strip():
        st.sidebar.error("maishift 프로필 URL을 입력하세요.")
        return None

    payload = {
        "profile_url": profile_url.strip(),
        "goal": GOAL_OPTIONS[goal_label],
        "main_level": main_level,
        "chart_type": CHART_TYPE_OPTIONS[chart_type_label],
        "top_n": top_n,
        "force_refresh": force_refresh,
    }

    return {
        "payload": payload,
        "developer_mode": developer_mode,
    }


def render_intro() -> None:
    st.markdown(
        f"""
        <div class="maigym-hero">
            <div class="hero-kicker">maimai DX recommender</div>
            <h1>{APP_TITLE}</h1>
            <p>
                maishift 프로필 기록과 cohort 통계를 조합해 지금 고를 만한 채보를
                빠르게 정리합니다.
            </p>
            <div class="hero-chip-row">
                <span class="hero-chip is-cyan">maishift profile</span>
                <span class="hero-chip">rating cohort</span>
                <span class="hero-chip is-purple">PNG export</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🎵",
        layout="wide",
    )

    inject_global_styles()
    render_intro()

    form_result = render_sidebar_form()

    if form_result is None:
        render_empty_state()
        return

    payload = form_result["payload"]
    developer_mode = form_result["developer_mode"]

    if developer_mode:
        with st.expander("개발자용 요청 payload", expanded=False):
            st.json(payload)

    with st.spinner("maishift 프로필을 파싱하고 추천을 생성하는 중입니다..."):
        try:
            result = call_recommend_by_url(payload)
        except Exception as exc:
            st.error(str(exc))
            return

    render_profile_info(
        result=result,
        developer_mode=developer_mode,
    )

    if developer_mode:
        render_applied_conditions(result)

    render_recommendations(
        result=result,
        developer_mode=developer_mode,
    )

    render_result_image(result)

    render_cache_info(
        result=result,
        developer_mode=developer_mode,
    )

    render_debug_info(
        result=result,
        developer_mode=developer_mode,
    )

    render_raw_response(
        result=result,
        developer_mode=developer_mode,
    )


if __name__ == "__main__":
    main()
