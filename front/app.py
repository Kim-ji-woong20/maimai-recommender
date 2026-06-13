import os
from typing import Any

import requests
import streamlit as st


API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
REQUEST_TIMEOUT_SECONDS = 300


GOAL_OPTIONS = {
    "레이팅 상승": "rating_up",
    "실력 향상": "skill_up",
    "약점 보완": "weakness",
    "역보더 탐색": "reverse_border",
}

MAIN_LEVEL_OPTIONS = ["13", "13+", "14", "14+", "15"]

CHART_TYPE_OPTIONS = {
    "상관없음": "any",
    "DX": "dx",
    "STANDARD": "std",
}

BPM_OPTIONS = {
    "상관없음": "any",
    "느린 곡": "slow",
    "보통": "normal",
    "빠른 곡": "fast",
}


# ------------------------------------------------------------
# API calls
# ------------------------------------------------------------

def extract_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
        return str(data.get("detail", data))
    except Exception:
        return response.text


def check_api_health() -> tuple[bool, str]:
    try:
        response = requests.get(
            f"{API_BASE_URL}/health",
            timeout=10,
        )

        if response.status_code == 200:
            return True, "백엔드 연결 정상"

        return False, f"백엔드 응답 오류: {response.status_code}"

    except Exception as e:
        return False, f"백엔드 연결 실패: {e}"


def call_recommend_by_url(payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        f"{API_BASE_URL}/recommend-by-url",
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code != 200:
        raise RuntimeError(extract_error_message(response))

    return response.json()


# ------------------------------------------------------------
# Rendering helpers
# ------------------------------------------------------------

def bool_to_text(value: Any) -> str:
    return "예" if bool(value) else "아니오"


def format_score(value: Any, played: bool) -> str:
    if not played:
        return "-"

    try:
        return f"{float(value):.4f}%"
    except Exception:
        return "-"


def goal_empty_message(goal: str) -> str:
    if goal == "reverse_border":
        return (
            "선택한 조건에서 역보더 후보가 없습니다. "
            "현재 파싱된 기록 중 선택 레벨 범위에 100.4000% 이상 100.5000% 미만인 채보가 없을 수 있습니다. "
            "주력 레벨 또는 채보 타입 조건을 완화해보세요."
        )

    if goal == "rating_up":
        return (
            "선택한 조건에서 레이팅 상승 후보를 찾지 못했습니다. "
            "상위권 유저의 경우 이미 100.5% 이상인 곡이 많거나, "
            "현재 cohort 통계에서 유의미한 후보가 부족할 수 있습니다. "
            "주력 레벨을 낮추거나 채보 타입을 '상관없음'으로 변경해보세요."
        )

    if goal == "skill_up":
        return (
            "선택한 조건에서 실력 향상용 후보를 찾지 못했습니다. "
            "주력 레벨 또는 채보 타입 조건을 완화해보세요."
        )

    if goal == "weakness":
        return (
            "선택한 조건에서 약점 보완 후보를 찾지 못했습니다. "
            "파싱된 기록이 부족하거나, 동일 레이팅대 통계와 비교 가능한 기록이 적을 수 있습니다."
        )

    return "추천 결과가 없습니다. 조건을 완화해보세요."


def render_profile_info(result: dict[str, Any], developer_mode: bool = False) -> None:
    profile_info = result.get("input_profile")

    if not profile_info:
        return

    st.subheader("입력 프로필 정보")

    col1, col2 = st.columns(2)

    with col1:
        st.metric("Profile ID", profile_info.get("profile_id", "-"))

    with col2:
        st.metric("Rating", profile_info.get("rating", "-"))

    if not developer_mode:
        return

    st.divider()

    col3, col4 = st.columns(2)

    with col3:
        st.metric("Parsed", profile_info.get("extracted_count", "-"))

    with col4:
        st.metric("Matched", profile_info.get("matched_count", "-"))

    records_count = int(profile_info.get("records_extracted_count", 0) or 0)
    records_matched = int(profile_info.get("records_matched_count", 0) or 0)
    records_unmatched = int(profile_info.get("records_unmatched_count", 0) or 0)
    best50_count = int(profile_info.get("best50_extracted_count", 0) or 0)
    combined_count = int(profile_info.get("combined_record_count", 0) or 0)
    best50_in_combined = int(profile_info.get("best50_in_combined_count", 0) or 0)

    records_source_mode = profile_info.get("records_source_mode", "-")
    records_browser_error = profile_info.get("records_browser_error", "")

    with st.expander("개발자용 파싱 상세 정보", expanded=False):
        st.write(f"Records 수집 방식: {records_source_mode}")
        st.write(f"Records 페이지 추출 수: {records_count}")
        st.write(f"Records 매칭 성공 수: {records_matched}")
        st.write(f"Records 매칭 실패 수: {records_unmatched}")
        st.write(f"Best 50 페이지 추출 수: {best50_count}")
        st.write(f"최종 병합 기록 수: {combined_count}")
        st.write(f"병합 기록 중 Best 50 포함 수: {best50_in_combined}")
        st.write(f"Records URL: {profile_info.get('records_url', '-')}")

        if records_browser_error:
            st.warning(f"브라우저 records 수집 오류: {records_browser_error}")

    warning = result.get("profile_parse_warning")

    if warning:
        st.warning(warning)

    unmatched_titles = profile_info.get("unmatched_titles", [])

    if unmatched_titles:
        with st.expander("개발자용 매칭 실패 항목 일부 보기", expanded=False):
            for item in unmatched_titles:
                st.write(
                    f"- {item.get('title')} "
                    f"({item.get('chart_type')}, {item.get('internal_level')}) "
                    f"{item.get('error', '')}"
                )


def render_debug_info(result: dict[str, Any], developer_mode: bool = False) -> None:
    if not developer_mode:
        return

    debug = result.get("debug")

    if not debug:
        return

    with st.expander("개발자용 추천 기준 디버그 정보", expanded=False):
        st.json(debug)

def render_cache_info(result: dict[str, Any], developer_mode: bool = False) -> None:
    if not developer_mode:
        return

    cache_info = result.get("profile_cache")

    if not cache_info:
        return

    with st.expander("개발자용 프로필 캐시 정보", expanded=False):
        st.json(cache_info)

def render_raw_response(result: dict[str, Any], developer_mode: bool = False) -> None:
    if not developer_mode:
        return

    with st.expander("개발자용 API 원본 응답 보기", expanded=False):
        st.json(result)


def render_recommendation_card(rec: dict[str, Any], developer_mode: bool = False) -> None:
    rank = rec.get("rank")
    title = rec.get("title")
    difficulty = rec.get("difficulty")
    level = rec.get("level")
    internal_level = rec.get("internal_level")
    chart_type = rec.get("chart_type")

    played = bool(rec.get("played", False))
    is_best50 = bool(rec.get("is_best50", False))
    achievement = rec.get("achievement", 0.0)

    reverse_border = bool(rec.get("reverse_border", False))
    reverse_border_gap = rec.get("reverse_border_gap", 0.0)

    with st.container(border=True):
        title_text = f"### {rank}. {title}"

        if reverse_border:
            title_text += "  \n`역보더`"

        st.markdown(title_text)

        col1, col2, col3, col4, col5, col6 = st.columns(6)

        with col1:
            st.metric("채보", str(difficulty).upper())

        with col2:
            st.metric("레벨", level)

        with col3:
            st.metric("내부상수", internal_level)

        with col4:
            st.metric("타입", str(chart_type).upper())

        with col5:
            st.metric("현재 달성률", format_score(achievement, played))

        with col6:
            st.metric("Best 50 포함", bool_to_text(is_best50))

        if reverse_border:
            try:
                st.caption(f"100.5%까지 부족한 차이: {float(reverse_border_gap):.4f}%")
            except Exception:
                pass

        if developer_mode:
            with st.expander("개발자용 추천 상세", expanded=False):
                st.write(f"Chart ID: {rec.get('chart_id')}")
                st.write(f"BPM: {rec.get('bpm')}")
                st.write(f"추천점수: {rec.get('recommend_score')}")
                st.write(f"후보 유형: {rec.get('candidate_label')}")
                st.write(f"현재 곡별 레이팅: {rec.get('current_rating')}")
                st.write(f"100.5% 기준 최대 레이팅: {rec.get('max_rating')}")
                st.write(f"레이팅 상승 여지: {rec.get('rating_gain')}")
                st.write(f"목표: {rec.get('target')}")
                st.write(f"추천 이유: {rec.get('reason')}")


def render_recommendations(result: dict[str, Any], developer_mode: bool = False) -> None:
    st.subheader("추천 결과")

    recommendations = result.get("recommendations", [])
    goal = result.get("goal", "")

    if not recommendations:
        st.warning(goal_empty_message(goal))
        return

    if developer_mode:
        summary = result.get("summary", "")

        if summary:
            st.info(summary)

    for rec in recommendations:
        render_recommendation_card(rec, developer_mode=developer_mode)


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def initialize_session_state() -> None:
    if "last_result" not in st.session_state:
        st.session_state.last_result = None

    if "last_error" not in st.session_state:
        st.session_state.last_error = None

    if "last_payload" not in st.session_state:
        st.session_state.last_payload = None


def main() -> None:
    st.set_page_config(
        page_title="maimai DX 추천 시스템",
        page_icon="🎵",
        layout="wide",
    )

    initialize_session_state()

    st.title("maimai DX 고레벨 추천 시스템")
    st.caption("maishift 프로필과 유사 레이팅대 유저 통계를 활용한 추천 웹 애플리케이션")

    st.markdown(
        """
        maishift 프로필 기록과 유사 레이팅대 유저 통계를 기반으로  
        현재 레이팅 구간에서 도전할 만한 maimai DX 고레벨 채보를 추천합니다.
        """
    )

    with st.sidebar:
        st.header("추천 설정")

        api_ok, api_message = check_api_health()

        if api_ok:
            st.success(api_message)
        else:
            st.error(api_message)

        developer_mode = st.checkbox(
            "개발자 모드",
            value=False,
            help="파싱 수, 매칭 실패 항목, API 원본 응답, 디버그 정보를 표시합니다.",
        )

        if developer_mode:
            st.caption(f"API: `{API_BASE_URL}`")

        with st.form("recommend_form"):
            profile_url = st.text_input(
                "maishift 프로필 URL",
                value="https://maimai.shiftpsh.com/profile/kong3171/home",
                placeholder="https://maimai.shiftpsh.com/profile/사용자ID/home",
            )

            force_refresh = st.checkbox(
                "프로필 캐시 무시하고 새로 파싱",
                value=False,
                help=(
                    "같은 프로필 URL은 기본적으로 백엔드 캐시를 사용합니다. "
                    "최신 기록을 강제로 다시 가져오고 싶을 때만 체크하세요."
                ),
            )

            goal_label = st.selectbox(
                "추천 목표",
                list(GOAL_OPTIONS.keys()),
            )

            main_level = st.selectbox(
                "주력 레벨",
                MAIN_LEVEL_OPTIONS,
                index=2,
            )

            chart_type_label = st.selectbox(
                "채보 타입",
                list(CHART_TYPE_OPTIONS.keys()),
            )

            bpm_label = st.selectbox(
                "BPM 선호",
                list(BPM_OPTIONS.keys()),
            )

            top_n = st.slider(
                "추천 개수",
                min_value=5,
                max_value=30,
                value=10,
                step=5,
            )

            submitted = st.form_submit_button(
                "추천 실행",
                type="primary",
                use_container_width=True,
            )

    if submitted:
        st.session_state.last_result = None
        st.session_state.last_error = None

        payload = {
            "profile_url": profile_url.strip(),
            "goal": GOAL_OPTIONS[goal_label],
            "main_level": main_level,
            "chart_type": CHART_TYPE_OPTIONS[chart_type_label],
            "bpm_preference": BPM_OPTIONS[bpm_label],
            "top_n": top_n,
            "force_refresh": force_refresh,
        }

        try:
            if not profile_url.strip():
                raise ValueError("maishift 프로필 URL을 입력하세요.")

            with st.spinner("프로필과 추천 데이터를 분석하는 중입니다..."):
                result = call_recommend_by_url(payload)

            st.session_state.last_payload = payload
            st.session_state.last_result = result

        except Exception as e:
            st.session_state.last_payload = payload
            st.session_state.last_error = str(e)

    if st.session_state.last_error:
        st.error("추천 생성 중 오류가 발생했습니다.")

        if developer_mode:
            st.code(st.session_state.last_error)

            if st.session_state.last_payload:
                with st.expander("요청 payload 확인", expanded=False):
                    st.json(st.session_state.last_payload)
        else:
            st.write("입력한 maishift 프로필 URL을 확인하거나 잠시 후 다시 시도하세요.")

        return

    if st.session_state.last_result is None:
        st.info("왼쪽 사이드바에서 maishift 프로필 URL과 추천 조건을 설정한 뒤 `추천 실행` 버튼을 누르세요.")
        return

    if developer_mode and st.session_state.last_payload:
        with st.expander("개발자용 마지막 요청 payload", expanded=False):
            st.json(st.session_state.last_payload)

    result = st.session_state.last_result

    render_profile_info(result, developer_mode=developer_mode)
    render_recommendations(result, developer_mode=developer_mode)
    render_cache_info(result, developer_mode=developer_mode)
    render_debug_info(result, developer_mode=developer_mode)
    render_raw_response(result, developer_mode=developer_mode)


if __name__ == "__main__":
    main()