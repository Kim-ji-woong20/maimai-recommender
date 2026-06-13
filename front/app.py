from __future__ import annotations

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

    st.subheader("입력 프로필")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("프로필", nickname)

    with col2:
        st.metric("Rating", rating)

    with col3:
        st.metric("추출 기록 수", extracted_count)

    with col4:
        st.metric("매칭 기록 수", matched_count)

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

    st.subheader("적용된 추천 조건")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("추천 목표", goal)

    with col2:
        st.metric("주력 레벨", main_level)

    with col3:
        st.metric("채보 타입", str(chart_type).upper())

    with col4:
        st.metric("레이팅 구간", f"{current_band} → {target_band}")


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
                st.image(thumbnail_url, width=130)
            else:
                st.caption("No image")

        with info_col:
            title_text = f"### {rank}. {title}"

            if reverse_border:
                title_text += "  \n`역보더`"

            st.markdown(title_text)

            if artist:
                st.caption(artist)

            st.caption(
                f"{version} · {str(chart_type).upper()} · "
                f"{str(difficulty).upper()} · {category}"
            )

            col1, col2, col3, col4, col5 = st.columns(5)

            with col1:
                st.metric("레벨", level)

            with col2:
                st.metric("내부상수", internal_level)

            with col3:
                st.metric("타입", str(chart_type).upper())

            with col4:
                st.metric("현재 달성률", format_score(achievement, played))

            with col5:
                st.metric("Best 50 포함", bool_to_text(is_best50))

            if reverse_border:
                try:
                    st.caption(f"100.5%까지 부족한 차이: {float(reverse_border_gap):.4f}%")
                except Exception:
                    pass

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

    st.subheader("추천 결과")

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

def find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    PNG 이미지 생성용 폰트 선택 함수.

    Pillow는 브라우저처럼 자동 폰트 fallback을 잘 하지 않으므로,
    일본어/한글을 모두 포함할 가능성이 높은 CJK 폰트를 우선 사용한다.

    우선순위:
    1. 환경변수로 직접 지정한 폰트
    2. Noto Sans CJK 계열
    3. Windows 일본어 폰트: Meiryo, Yu Gothic
    4. Windows 한글 폰트: Malgun Gothic
    5. DejaVu fallback
    """
    env_key = "MAIGYM_FONT_BOLD" if bold else "MAIGYM_FONT_REGULAR"
    env_font_path = os.getenv(env_key)

    font_candidates = []

    if env_font_path:
        font_candidates.append(env_font_path)

    if bold:
        font_candidates.extend([
            # Linux / Docker / EC2에서 Noto CJK가 설치된 경우
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Bold.otf",
            "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Bold.otf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansJP-Bold.otf",
            "/usr/share/fonts/truetype/noto/NotoSansKR-Bold.otf",

            # Windows 일본어 폰트
            "C:/Windows/Fonts/meiryob.ttc",
            "C:/Windows/Fonts/YuGothB.ttc",
            "C:/Windows/Fonts/msgothic.ttc",

            # Windows 한글 폰트
            "C:/Windows/Fonts/malgunbd.ttf",

            # 일반 fallback
            "C:/Windows/Fonts/Arialbd.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ])
    else:
        font_candidates.extend([
            # Linux / Docker / EC2에서 Noto CJK가 설치된 경우
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
            "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansJP-Regular.otf",
            "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.otf",

            # Windows 일본어 폰트
            "C:/Windows/Fonts/meiryo.ttc",
            "C:/Windows/Fonts/YuGothR.ttc",
            "C:/Windows/Fonts/msgothic.ttc",

            # Windows 한글 폰트
            "C:/Windows/Fonts/malgun.ttf",

            # 일반 fallback
            "C:/Windows/Fonts/arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ])

    for path in font_candidates:
        try:
            if path and os.path.exists(path):
                return ImageFont.truetype(path, size=size)
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
    song_font = find_font(20, bold=True)
    meta_font = find_font(15, bold=False)
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
    badge_w = badge_bbox[2] - badge_bbox[0] + 28
    badge_h = 38
    badge_x = header_x + header_w - badge_w - 28
    badge_y = header_y + 32

    draw.rounded_rectangle(
        (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
        radius=14,
        fill=accent_soft,
    )

    draw.text(
        (badge_x + 14, badge_y + 8),
        badge_text,
        font=badge_font,
        fill=(232, 226, 255),
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
    st.sidebar.header("추천 조건")

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

        submitted = st.form_submit_button("추천 생성")

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
    st.title(APP_TITLE)


def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🎵",
        layout="wide",
    )

    render_intro()

    form_result = render_sidebar_form()

    if form_result is None:
        st.info("왼쪽 사이드바에서 maishift 프로필 URL과 추천 조건을 입력한 뒤 추천을 생성하세요.")
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