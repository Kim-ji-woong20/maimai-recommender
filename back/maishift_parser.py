from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup


MAISHIFT_BASE_URL = "https://maimai.shiftpsh.com"

REQUEST_TIMEOUT_SECONDS = 15

# maishift records가 50개 근처에서 고정되면 부분 렌더링 실패로 본다.
PARTIAL_RENDER_RECORDS = 50
PARTIAL_RENDER_TOLERANCE = 10
PARTIAL_EXTRACTED_UPPER_BOUND = 70

# 정상 수용 기준.
# 유저별 총 기록 수가 다르므로 800개 이상 같은 고정 기준은 사용하지 않는다.
MIN_ACCEPTABLE_EXTRACTED_RECORDS = 100
MIN_ACCEPTABLE_MATCHED_RECORDS = 50

# 브라우저 수집 시 충분히 많이 모이면 조기 종료하기 위한 상한.
# 정상 판정 기준이 아니라 불필요한 추가 스크롤 방지용 목표값이다.
BROWSER_COLLECTION_TARGET_COUNT = 1000

# 전체 parser 호출은 1회로 두고, 내부에서 브라우저 세션을 여러 번 새로 연다.
# 사용자가 수동으로 "캐시 무시 후 재실행"을 여러 번 눌렀을 때 정상 로딩되던 현상을 코드 내부에서 재현한다.
PROFILE_PARSE_MAX_ATTEMPTS = 1
PROFILE_PARSE_RETRY_WAIT_SECONDS = 0.8
PROFILE_PARSE_HARD_TIMEOUT_SECONDS = 420.0

USE_BROWSER_RECORDS_FALLBACK = True

BROWSER_RECORDS_STABLE_LIMIT = 8
BROWSER_PARTIAL_50_STABLE_LIMIT = 7
MIN_SCROLLS_BEFORE_PARTIAL_50_BREAK = 22
MIN_SECONDS_BEFORE_PARTIAL_50_BREAK = 24.0
EMPTY_PAGE_STABLE_LIMIT = 3

RECORD_WAIT_SECONDS = 2.0
SCROLL_WAIT_SECONDS = 0.65


USER_RECORD_COLUMNS = [
    "chart_id",
    "achievement",
    "rank",
    "play_count",
    "chart_rating",
    "is_best50",
    "best50_section",
    "best50_order",
    "record_source",
    "combo",
    "sync",
]


CHART_TYPE_ALIASES = {
    "DX": "dx",
    "DELUXE": "dx",
    "でらっくす": "dx",
    "STANDARD": "std",
    "STD": "std",
    "ST": "std",
    "スタンダード": "std",
}


RANK_TOKENS = {
    "D",
    "C",
    "B",
    "BB",
    "BBB",
    "A",
    "AA",
    "AAA",
    "S",
    "S+",
    "SS",
    "SS+",
    "SSS",
    "SSS+",
}


COMBO_TOKENS = {
    "FC",
    "FC+",
    "FC⁺",
    "AP",
    "AP+",
    "AP⁺",
}


SYNC_TOKENS = {
    "SYNC",
    "FS",
    "FS+",
    "FS⁺",
    "FDX",
    "FDX+",
    "FDX⁺",
}


# 핵심 변경:
# 한 페이지에서 4개 전략을 길게 도는 방식이 아니라,
# 브라우저/컨텍스트/페이지를 새로 열어 여러 번 재시도한다.
# natural 계열을 우선하고, blocked는 보조 전략으로 둔다.
BROWSER_SESSION_PROFILES = [
    {
        "name": "natural_session_1",
        "block_images": False,
        "block_fonts": True,
        "initial_wait_seconds": 3.0,
        "scroll_wait_seconds": 0.55,
        "max_scrolls": 42,
        "max_seconds": 46.0,
        "parse_every_n_scrolls": 2,
        "viewport_height": 1900,
        "cache_bust": True,
    },
    {
        "name": "natural_session_2",
        "block_images": False,
        "block_fonts": True,
        "initial_wait_seconds": 3.5,
        "scroll_wait_seconds": 0.65,
        "max_scrolls": 48,
        "max_seconds": 55.0,
        "parse_every_n_scrolls": 2,
        "viewport_height": 2000,
        "cache_bust": True,
    },
    {
        "name": "natural_slow_session_1",
        "block_images": False,
        "block_fonts": False,
        "initial_wait_seconds": 4.0,
        "scroll_wait_seconds": 0.85,
        "max_scrolls": 58,
        "max_seconds": 75.0,
        "parse_every_n_scrolls": 1,
        "viewport_height": 2200,
        "cache_bust": True,
    },
    {
        "name": "blocked_session_1",
        "block_images": True,
        "block_fonts": True,
        "initial_wait_seconds": 2.5,
        "scroll_wait_seconds": 0.55,
        "max_scrolls": 46,
        "max_seconds": 52.0,
        "parse_every_n_scrolls": 2,
        "viewport_height": 2000,
        "cache_bust": True,
    },
    {
        "name": "natural_tall_session",
        "block_images": False,
        "block_fonts": True,
        "initial_wait_seconds": 4.0,
        "scroll_wait_seconds": 0.75,
        "max_scrolls": 60,
        "max_seconds": 72.0,
        "parse_every_n_scrolls": 1,
        "viewport_height": 2600,
        "cache_bust": True,
    },
    {
        "name": "natural_final_session",
        "block_images": False,
        "block_fonts": False,
        "initial_wait_seconds": 5.0,
        "scroll_wait_seconds": 0.95,
        "max_scrolls": 70,
        "max_seconds": 90.0,
        "parse_every_n_scrolls": 1,
        "viewport_height": 2400,
        "cache_bust": True,
    },
]


@dataclass
class RawRecord:
    title: str
    artist: str = ""
    chart_type: str = ""
    internal_level: float = 0.0
    level_label: str = ""
    achievement: float = 0.0
    rank: str = ""
    chart_rating: int = 0
    combo: str = ""
    sync: str = ""
    is_best50: bool = False
    best50_section: str = ""
    best50_order: int = 0
    record_source: str = ""


def normalize_profile_url(profile_url: str, page: str = "home") -> str:
    profile_id = extract_profile_id_from_url(profile_url)

    if profile_id:
        return f"{MAISHIFT_BASE_URL}/profile/{profile_id}/{page}"

    text = str(profile_url).strip().rstrip("/")

    if page == "records":
        if text.endswith("/home"):
            return text[:-5] + "/records"

        if not text.endswith("/records"):
            return text + "/records"

    if page == "home":
        if text.endswith("/records"):
            return text[:-8] + "/home"

        if not text.endswith("/home"):
            return text + "/home"

    return text


def build_cache_busted_url(url: str, attempt: int, profile_name: str) -> str:
    separator = "&" if "?" in url else "?"
    safe_profile_name = re.sub(r"[^a-zA-Z0-9_\\-]", "_", profile_name)

    return f"{url}{separator}maigym_retry={attempt}_{safe_profile_name}_{int(time.time() * 1000)}"


def extract_profile_id_from_url(profile_url: str) -> str:
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


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,ja-JP;q=0.8,ja;q=0.7,en-US;q=0.6,en;q=0.5",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    return response.text


def html_to_visible_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # DX / STANDARD 정보가 img alt에 들어 있는 경우가 있어 텍스트로 보강한다.
    # 이미지 요청을 차단해도 DOM의 img alt는 남는 경우가 많으므로 유지한다.
    for img in soup.find_all("img"):
        alt = str(img.get("alt") or "").strip()

        if alt:
            img.insert_after(soup.new_string(f"\n{alt}\n"))

    text = soup.get_text("\n")
    lines = []

    for line in text.splitlines():
        cleaned = normalize_spaces(line)

        if cleaned:
            lines.append(cleaned)

    return lines


def normalize_spaces(value: Any) -> str:
    text = str(value or "")
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_title(value: Any) -> str:
    text = normalize_spaces(value)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("～", "~")
    text = text.replace("〜", "~")
    text = text.replace("－", "-")
    text = text.replace("–", "-")
    text = text.replace("—", "-")
    text = text.replace("？", "?")
    text = text.replace("！", "!")
    text = text.replace("　", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip().casefold()


def normalize_compact_title(value: Any) -> str:
    text = normalize_title(value)
    text = re.sub(r"[\s\-_~・･.,:;!?？！（）()\[\]{}'\"`´]", "", text)

    return text


def normalize_chart_type(value: Any) -> str:
    text = normalize_spaces(value).upper()

    return CHART_TYPE_ALIASES.get(text, "")


def is_chart_type_token(value: Any) -> bool:
    return normalize_chart_type(value) in {"dx", "std"}


def is_integer_token(value: Any) -> bool:
    text = normalize_spaces(value)

    return bool(re.fullmatch(r"\d+", text.replace(",", "")))


def to_int(value: Any, default: int = 0) -> int:
    try:
        text = normalize_spaces(value).replace(",", "")
        return int(float(text))

    except Exception:
        return default


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        text = normalize_spaces(value).replace(",", "")
        return float(text)

    except Exception:
        return default


def parse_level_at(lines: list[str], index: int) -> tuple[float, str, int] | None:
    if index >= len(lines):
        return None

    first = normalize_spaces(lines[index])

    if not re.fullmatch(r"1[0-5]", first):
        return None

    base = int(first)
    cursor = index + 1
    decimal = 0
    plus = False

    if (
        cursor + 1 < len(lines)
        and normalize_spaces(lines[cursor]) == "."
        and re.fullmatch(r"\d", normalize_spaces(lines[cursor + 1]))
    ):
        decimal = int(normalize_spaces(lines[cursor + 1]))
        cursor += 2

    if cursor < len(lines) and normalize_spaces(lines[cursor]) in {"+", "⁺"}:
        plus = True
        cursor += 1

    internal_level = float(f"{base}.{decimal}") if decimal else float(base)
    level_label = f"{base}+" if plus else str(base)

    return internal_level, level_label, cursor


def parse_achievement_before_percent(lines: list[str], percent_index: int) -> float:
    if percent_index <= 0:
        return 0.0

    prev1 = normalize_spaces(lines[percent_index - 1])

    if re.fullmatch(r"\d{1,3}\.\d+", prev1):
        return to_float(prev1)

    if percent_index >= 3:
        a = normalize_spaces(lines[percent_index - 3])
        dot = normalize_spaces(lines[percent_index - 2])
        b = normalize_spaces(lines[percent_index - 1])

        if re.fullmatch(r"\d{1,3}", a) and dot == "." and re.fullmatch(r"\d{1,4}", b):
            return to_float(f"{a}.{b}")

    if percent_index >= 2:
        a = normalize_spaces(lines[percent_index - 2])
        b = normalize_spaces(lines[percent_index - 1])

        if re.fullmatch(r"\d{1,3}", a) and re.fullmatch(r"\d{1,4}", b):
            return to_float(f"{a}.{b}")

    return 0.0


def parse_rank_combo_sync(tokens: list[str]) -> tuple[str, str, str]:
    normalized = [
        normalize_spaces(token)
        for token in tokens
        if normalize_spaces(token)
    ]

    rank = ""
    combo = ""
    sync = ""

    for i, token in enumerate(normalized):
        candidate = token

        if i + 1 < len(normalized) and normalized[i + 1] in {"+", "⁺"}:
            candidate = f"{token}+"

        if candidate in RANK_TOKENS and not rank:
            rank = candidate

        if candidate in COMBO_TOKENS and not combo:
            combo = candidate

        if candidate in SYNC_TOKENS and not sync:
            sync = candidate

    return rank, combo, sync


def extract_profile_info_from_lines(
    lines: list[str],
    profile_url: str,
) -> dict[str, Any]:
    profile_id = extract_profile_id_from_url(profile_url)
    nickname = ""

    for i, line in enumerate(lines):
        if line == "친구 코드" and i >= 1:
            nickname = lines[i - 1]
            break

    if not nickname and profile_id:
        nickname = profile_id

    rating = None

    # rating이 숫자 5자리로 분리되어 나오는 경우 처리
    for i in range(0, max(0, len(lines) - 4)):
        five = lines[i:i + 5]

        if all(re.fullmatch(r"\d", normalize_spaces(x)) for x in five):
            candidate = int("".join(five))

            if 10000 <= candidate <= 20000:
                rating = candidate
                break

    if rating is None:
        for i, line in enumerate(lines):
            if line in {"[~", "[", "레이팅"}:
                for j in range(i + 1, min(i + 10, len(lines))):
                    candidate = to_int(lines[j], 0)

                    if 10000 <= candidate <= 20000:
                        rating = candidate
                        break

            if rating is not None:
                break

    if rating is None:
        joined = " ".join(lines[:150])
        match = re.search(r"\b(1[0-9]{4})\b", joined)

        if match:
            rating = int(match.group(1))

    return {
        "profile_id": profile_id,
        "profile_url": normalize_profile_url(profile_url, "home"),
        "nickname": nickname,
        "rating": rating,
    }


def parse_home_best50_records(lines: list[str]) -> list[RawRecord]:
    records = []
    order = 0

    for i, line in enumerate(lines):
        chart_type = normalize_chart_type(line)

        if chart_type not in {"dx", "std"}:
            continue

        rating_idx = None

        for j in range(i + 1, min(i + 10, len(lines))):
            value = to_int(lines[j], -1)

            if 1 <= value <= 500:
                parsed_level = parse_level_at(lines, j + 1)

                if parsed_level is not None:
                    rating_idx = j
                    break

        if rating_idx is None:
            continue

        chart_rating = to_int(lines[rating_idx], 0)
        parsed_level = parse_level_at(lines, rating_idx + 1)

        if parsed_level is None:
            continue

        internal_level, level_label, after_level = parsed_level

        if after_level >= len(lines):
            continue

        title = normalize_spaces(lines[after_level])

        if not title or title in {"DX", "STANDARD", "SSS+", "SSS", "SS", "S"}:
            continue

        percent_idx = None

        for j in range(after_level + 1, min(after_level + 7, len(lines))):
            if normalize_spaces(lines[j]) == "%":
                percent_idx = j
                break

        if percent_idx is None:
            continue

        achievement = parse_achievement_before_percent(lines, percent_idx)

        if achievement <= 0:
            continue

        rank_tokens = lines[i + 1:rating_idx]
        rank, combo, sync = parse_rank_combo_sync(rank_tokens)

        order += 1

        records.append(
            RawRecord(
                title=title,
                artist="",
                chart_type=chart_type,
                internal_level=internal_level,
                level_label=level_label,
                achievement=achievement,
                rank=rank,
                chart_rating=chart_rating,
                combo=combo,
                sync=sync,
                is_best50=True,
                best50_section="home_best50",
                best50_order=order,
                record_source="home_best50",
            )
        )

    return deduplicate_raw_records(records)


def parse_records_page_records(lines: list[str]) -> list[RawRecord]:
    records = []

    for i in range(len(lines)):
        parsed_level = parse_level_at(lines, i)

        if parsed_level is None:
            continue

        internal_level, level_label, after_level = parsed_level

        if after_level >= len(lines):
            continue

        chart_type = normalize_chart_type(lines[after_level])

        if chart_type not in {"dx", "std"}:
            continue

        cursor = after_level + 1

        if cursor < len(lines) and normalize_spaces(lines[cursor]) in {"OLD #", "NEW #", "OLD", "NEW"}:
            cursor += 1

        order_value = 0

        if cursor < len(lines) and is_integer_token(lines[cursor]):
            order_value = to_int(lines[cursor], 0)
            cursor += 1

        if cursor >= len(lines):
            continue

        title = normalize_spaces(lines[cursor])
        cursor += 1

        if not title:
            continue

        artist = ""

        if cursor < len(lines):
            artist_candidate = normalize_spaces(lines[cursor])

            if (
                artist_candidate
                and artist_candidate != "%"
                and not is_chart_type_token(artist_candidate)
                and artist_candidate not in {"OLD #", "NEW #", "OLD", "NEW"}
            ):
                artist = artist_candidate
                cursor += 1

        percent_idx = None

        for j in range(cursor, min(cursor + 18, len(lines))):
            if normalize_spaces(lines[j]) == "%":
                percent_idx = j
                break

        if percent_idx is None:
            continue

        achievement = parse_achievement_before_percent(lines, percent_idx)

        if achievement <= 0:
            continue

        chart_rating = 0

        if percent_idx + 1 < len(lines):
            next_value = to_int(lines[percent_idx + 1], 0)

            if 0 <= next_value <= 500:
                chart_rating = next_value

        rank_tokens = lines[cursor:percent_idx]
        rank, combo, sync = parse_rank_combo_sync(rank_tokens)

        records.append(
            RawRecord(
                title=title,
                artist=artist,
                chart_type=chart_type,
                internal_level=internal_level,
                level_label=level_label,
                achievement=achievement,
                rank=rank,
                chart_rating=chart_rating,
                combo=combo,
                sync=sync,
                is_best50=False,
                best50_section="",
                best50_order=order_value,
                record_source="records_page",
            )
        )

    return deduplicate_raw_records(records)


def extract_records_from_record_lines(lines: list[str]) -> list[RawRecord]:
    return parse_records_page_records(lines)


def deduplicate_raw_records(records: list[RawRecord]) -> list[RawRecord]:
    best_by_key: dict[tuple[str, str, float], RawRecord] = {}

    for record in records:
        key = (
            normalize_compact_title(record.title),
            record.chart_type,
            round(record.internal_level, 2),
        )

        old = best_by_key.get(key)

        if old is None:
            best_by_key[key] = record
            continue

        if record.is_best50 and not old.is_best50:
            best_by_key[key] = record
            continue

        if record.chart_rating > old.chart_rating:
            if old.is_best50:
                record.is_best50 = True
                record.best50_section = old.best50_section
                record.best50_order = old.best50_order

            best_by_key[key] = record
            continue

        if record.achievement > old.achievement and not old.is_best50:
            best_by_key[key] = record

    return list(best_by_key.values())


def merge_best50_flags(
    records: list[RawRecord],
    best50_records: list[RawRecord],
) -> list[RawRecord]:
    by_key: dict[tuple[str, str, float], RawRecord] = {}

    for record in records:
        key = (
            normalize_compact_title(record.title),
            record.chart_type,
            round(record.internal_level, 2),
        )

        by_key[key] = record

    for idx, best50 in enumerate(best50_records, start=1):
        key = (
            normalize_compact_title(best50.title),
            best50.chart_type,
            round(best50.internal_level, 2),
        )

        if key in by_key:
            target = by_key[key]
            target.is_best50 = True
            target.best50_section = best50.best50_section or "home_best50"
            target.best50_order = best50.best50_order or idx

            if best50.chart_rating > target.chart_rating:
                target.chart_rating = best50.chart_rating

            if best50.rank and not target.rank:
                target.rank = best50.rank

            if best50.combo and not target.combo:
                target.combo = best50.combo

            if best50.sync and not target.sync:
                target.sync = best50.sync

        else:
            best50.is_best50 = True
            best50.best50_order = best50.best50_order or idx
            by_key[key] = best50

    return list(by_key.values())


def build_chart_lookup(charts: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    lookup: dict[str, list[dict[str, Any]]] = {}

    for _, row in charts.iterrows():
        title = row.get("title", "")
        chart_type = normalize_chart_type(row.get("chart_type", ""))
        internal_level = to_float(row.get("internal_level", 0.0), 0.0)

        if not title or chart_type not in {"dx", "std"}:
            continue

        key = normalize_compact_title(title)

        item = {
            "chart_id": str(row.get("chart_id", "")),
            "title": str(row.get("title", "")),
            "chart_type": chart_type,
            "internal_level": internal_level,
            "difficulty": str(row.get("difficulty", "")),
        }

        lookup.setdefault(key, []).append(item)

    return lookup


def match_raw_record_to_chart(
    record: RawRecord,
    chart_lookup: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    title_key = normalize_compact_title(record.title)
    candidates = chart_lookup.get(title_key, [])

    if not candidates:
        return None

    filtered = [
        candidate
        for candidate in candidates
        if candidate["chart_type"] == record.chart_type
    ]

    if not filtered:
        filtered = candidates

    level_filtered = [
        candidate
        for candidate in filtered
        if abs(candidate["internal_level"] - record.internal_level) <= 0.11
    ]

    if level_filtered:
        filtered = level_filtered

    if not filtered:
        return None

    def sort_key(candidate: dict[str, Any]) -> tuple[float, int]:
        diff = abs(candidate["internal_level"] - record.internal_level)

        difficulty = str(candidate.get("difficulty", "")).lower()
        difficulty_priority = {
            "remaster": 0,
            "master": 1,
            "expert": 2,
        }.get(difficulty, 9)

        return diff, difficulty_priority

    return sorted(filtered, key=sort_key)[0]


def raw_records_to_dataframe(
    records: list[RawRecord],
    charts: pd.DataFrame,
) -> tuple[pd.DataFrame, list[RawRecord]]:
    chart_lookup = build_chart_lookup(charts)

    rows = []
    unmatched = []

    for record in records:
        matched = match_raw_record_to_chart(record, chart_lookup)

        if matched is None:
            unmatched.append(record)
            continue

        rows.append({
            "chart_id": matched["chart_id"],
            "achievement": float(record.achievement),
            "rank": record.rank,
            "play_count": 1,
            "chart_rating": int(record.chart_rating),
            "is_best50": bool(record.is_best50),
            "best50_section": record.best50_section,
            "best50_order": int(record.best50_order),
            "record_source": record.record_source,
            "combo": record.combo,
            "sync": record.sync,
        })

    if not rows:
        return pd.DataFrame(columns=USER_RECORD_COLUMNS), unmatched

    df = pd.DataFrame(rows)

    for col in USER_RECORD_COLUMNS:
        if col not in df.columns:
            if col == "is_best50":
                df[col] = False
            elif col in {"achievement", "play_count", "chart_rating", "best50_order"}:
                df[col] = 0
            else:
                df[col] = ""

    df = df[USER_RECORD_COLUMNS].copy()

    df = df.sort_values(
        ["is_best50", "chart_rating", "achievement"],
        ascending=[False, False, False],
    )

    df = df.drop_duplicates(
        subset=["chart_id"],
        keep="first",
    ).reset_index(drop=True)

    return df, unmatched


def is_count_near_partial_50(count: int) -> bool:
    return (
        PARTIAL_RENDER_RECORDS - PARTIAL_RENDER_TOLERANCE
        <= count
        <= PARTIAL_RENDER_RECORDS + PARTIAL_RENDER_TOLERANCE
    )


def is_count_partial_or_missing(count: int) -> bool:
    return count <= 0 or is_count_near_partial_50(count)


def is_partial_50_failure_counts(
    home_best50_count: int,
    static_records_count: int,
    browser_records_count: int,
    extracted_count: int,
) -> bool:
    return (
        home_best50_count >= PARTIAL_RENDER_RECORDS - 5
        and is_count_near_partial_50(static_records_count)
        and is_count_partial_or_missing(browser_records_count)
        and extracted_count <= PARTIAL_EXTRACTED_UPPER_BOUND
    )


def is_acceptable_result(
    extracted_count: int,
    matched_count: int,
    partial_50_failure: bool,
) -> bool:
    if partial_50_failure:
        return False

    return (
        extracted_count >= MIN_ACCEPTABLE_EXTRACTED_RECORDS
        and matched_count >= MIN_ACCEPTABLE_MATCHED_RECORDS
    )


def install_resource_blocking(
    context: Any,
    block_images: bool,
    block_fonts: bool,
) -> None:
    def route_handler(route: Any) -> None:
        request = route.request
        resource_type = request.resource_type
        url = request.url.lower()

        if block_images and resource_type in {"image", "media"}:
            route.abort()
            return

        if block_images and "image-relay" in url:
            route.abort()
            return

        if block_fonts and resource_type == "font":
            route.abort()
            return

        route.continue_()

    context.route("**/*", route_handler)


def advance_records_page_scroll(page: Any, scroll_index: int) -> None:
    try:
        page.mouse.wheel(0, 1900)
    except Exception:
        pass

    if scroll_index % 4 == 3:
        try:
            page.keyboard.press("PageDown")
        except Exception:
            pass

    if scroll_index % 10 == 9:
        try:
            page.keyboard.press("End")
        except Exception:
            pass

    try:
        page.evaluate(
            """
            () => {
                const amount = Math.max(900, window.innerHeight * 0.85);

                window.scrollBy(0, amount);

                const candidates = [
                    document.scrollingElement,
                    document.documentElement,
                    document.body,
                    ...Array.from(document.querySelectorAll("main, section, article, div"))
                ].filter(Boolean);

                for (const el of candidates) {
                    try {
                        const style = window.getComputedStyle(el);
                        const canScroll =
                            el.scrollHeight > el.clientHeight + 50 &&
                            style.display !== "none" &&
                            style.visibility !== "hidden";

                        if (canScroll) {
                            el.scrollTop = Math.min(
                                el.scrollTop + amount,
                                el.scrollHeight
                            );
                        }
                    } catch (e) {
                        continue;
                    }
                }
            }
            """
        )
    except Exception:
        pass


def click_possible_load_more(page: Any) -> None:
    button_texts = [
        "더 보기",
        "더보기",
        "もっと見る",
        "Load more",
        "More",
    ]

    for text in button_texts:
        try:
            locator = page.get_by_text(text, exact=False)

            if locator.count() > 0:
                locator.first.click(timeout=1000)
                page.wait_for_timeout(400)
                return

        except Exception:
            continue


def snapshot_records_from_page(page: Any) -> tuple[list[RawRecord], int]:
    html = page.content()
    lines = html_to_visible_lines(html)
    records = parse_records_page_records(lines)

    return records, len(lines)


def fetch_records_with_browser_session(
    profile_url: str,
    session_profile: dict[str, Any],
    session_index: int,
    target_count: int = BROWSER_COLLECTION_TARGET_COUNT,
) -> tuple[list[RawRecord], dict[str, Any]]:
    info = {
        "browser_available": False,
        "browser_error": "",
        "session_profile": session_profile.get("name", "unknown"),
        "session_index": session_index,
        "block_images": bool(session_profile.get("block_images", False)),
        "block_fonts": bool(session_profile.get("block_fonts", False)),
        "scrolls": 0,
        "snapshot_max_count": 0,
        "unique_record_count": 0,
        "visible_line_max_count": 0,
        "elapsed_seconds": 0.0,
        "time_limited": False,
        "partial_50_stable": False,
        "empty_page_stable": False,
        "final_url": "",
    }

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        info["browser_error"] = f"playwright import failed: {exc}"
        return [], info

    records_url = normalize_profile_url(profile_url, "records")

    if session_profile.get("cache_bust", False):
        records_url = build_cache_busted_url(
            url=records_url,
            attempt=session_index,
            profile_name=str(session_profile.get("name", "session")),
        )

    all_records: list[RawRecord] = []
    best_unique_count = 0
    snapshot_max_count = 0
    visible_line_max_count = 0
    stable_count = 0
    partial_50_stable_count = 0
    empty_page_stable_count = 0

    start_time = time.monotonic()

    max_scrolls = int(session_profile.get("max_scrolls", 45))
    max_seconds = float(session_profile.get("max_seconds", 50.0))
    initial_wait_seconds = float(session_profile.get("initial_wait_seconds", RECORD_WAIT_SECONDS))
    scroll_wait_seconds = float(session_profile.get("scroll_wait_seconds", SCROLL_WAIT_SECONDS))
    parse_every_n_scrolls = max(1, int(session_profile.get("parse_every_n_scrolls", 1)))
    viewport_height = int(session_profile.get("viewport_height", 1900))

    try:
        with sync_playwright() as p:
            launch_args = [
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-extensions",
            ]

            if session_profile.get("block_images", False):
                launch_args.append("--blink-settings=imagesEnabled=false")

            browser = p.chromium.launch(
                headless=True,
                args=launch_args,
            )

            context = None

            try:
                context = browser.new_context(
                    viewport={
                        "width": 1400,
                        "height": viewport_height,
                    },
                    locale="ko-KR",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"
                    ),
                    ignore_https_errors=True,
                )

                context.set_default_timeout(10000)

                install_resource_blocking(
                    context=context,
                    block_images=bool(session_profile.get("block_images", False)),
                    block_fonts=bool(session_profile.get("block_fonts", False)),
                )

                page = context.new_page()

                page.goto(
                    records_url,
                    wait_until="domcontentloaded",
                    timeout=45000,
                )

                page.wait_for_timeout(int(initial_wait_seconds * 1000))

                try:
                    page.keyboard.press("Home")
                    page.wait_for_timeout(300)
                except Exception:
                    pass

                for scroll_index in range(max_scrolls + 1):
                    elapsed = time.monotonic() - start_time

                    if elapsed >= max_seconds:
                        info["time_limited"] = True
                        break

                    click_possible_load_more(page)

                    should_snapshot = (
                        scroll_index == 0
                        or scroll_index % parse_every_n_scrolls == 0
                        or scroll_index == max_scrolls
                    )

                    if should_snapshot:
                        snapshot_records, visible_line_count = snapshot_records_from_page(page)

                        snapshot_count = len(snapshot_records)
                        snapshot_max_count = max(snapshot_max_count, snapshot_count)
                        visible_line_max_count = max(visible_line_max_count, visible_line_count)

                        if snapshot_records:
                            all_records.extend(snapshot_records)

                        unique_records = deduplicate_raw_records(all_records)
                        unique_count = len(unique_records)

                        if unique_count > best_unique_count:
                            best_unique_count = unique_count
                            stable_count = 0
                        else:
                            stable_count += 1

                        if is_count_near_partial_50(unique_count):
                            partial_50_stable_count += 1
                        else:
                            partial_50_stable_count = 0

                        if snapshot_count == 0 and visible_line_count <= 10:
                            empty_page_stable_count += 1
                        else:
                            empty_page_stable_count = 0

                        # 수집 목표치 도달 시 조기 종료.
                        # 이 값은 정상 판정 기준이 아니라 불필요한 추가 스크롤 방지용이다.
                        if unique_count >= target_count:
                            break

                        # 100개 이상으로 partial 50 상태를 벗어난 뒤 더 이상 늘지 않으면 종료.
                        if (
                            stable_count >= BROWSER_RECORDS_STABLE_LIMIT
                            and unique_count >= MIN_ACCEPTABLE_EXTRACTED_RECORDS
                        ):
                            break

                        # 빈 페이지 수준이면 이 세션은 실패로 보고 빠르게 다음 세션으로 넘긴다.
                        if empty_page_stable_count >= EMPTY_PAGE_STABLE_LIMIT:
                            info["empty_page_stable"] = True
                            break

                        # 50개 고정 판단은 너무 이르게 하지 않는다.
                        # 최소 스크롤 수와 최소 경과 시간이 모두 충족되어야 partial 세션 실패로 본다.
                        if (
                            partial_50_stable_count >= BROWSER_PARTIAL_50_STABLE_LIMIT
                            and scroll_index >= MIN_SCROLLS_BEFORE_PARTIAL_50_BREAK
                            and elapsed >= MIN_SECONDS_BEFORE_PARTIAL_50_BREAK
                        ):
                            info["partial_50_stable"] = True
                            break

                    advance_records_page_scroll(page, scroll_index)
                    page.wait_for_timeout(int(scroll_wait_seconds * 1000))

                    info["scrolls"] = scroll_index + 1

                final_records, final_line_count = snapshot_records_from_page(page)

                if final_records:
                    all_records.extend(final_records)

                snapshot_max_count = max(snapshot_max_count, len(final_records))
                visible_line_max_count = max(visible_line_max_count, final_line_count)

                info["final_url"] = page.url

            finally:
                if context is not None:
                    context.close()

                browser.close()

    except Exception as exc:
        info["browser_error"] = str(exc)

    final_records = deduplicate_raw_records(all_records)

    info["browser_available"] = True
    info["snapshot_max_count"] = snapshot_max_count
    info["unique_record_count"] = len(final_records)
    info["visible_line_max_count"] = visible_line_max_count
    info["elapsed_seconds"] = round(time.monotonic() - start_time, 2)

    return final_records, info


def is_better_browser_result(
    current_records: list[RawRecord],
    current_info: dict[str, Any],
    best_records: list[RawRecord],
    best_info: dict[str, Any] | None,
) -> bool:
    current_count = len(current_records)
    best_count = len(best_records)

    if best_info is None:
        return True

    if current_count <= 0 and best_count > 0:
        return False

    if current_count > 0 and best_count <= 0:
        return True

    current_partial = is_count_near_partial_50(current_count)
    best_partial = is_count_near_partial_50(best_count)

    # 50개 고정이 아닌 결과를 우선한다.
    if current_partial != best_partial:
        return not current_partial

    # 둘 다 partial이거나 둘 다 partial이 아니면 더 많이 잡힌 쪽을 우선한다.
    if current_count != best_count:
        return current_count > best_count

    # 개수가 같다면 partial_50_stable이 아닌 세션을 우선한다.
    current_stable = bool(current_info.get("partial_50_stable", False))
    best_stable = bool(best_info.get("partial_50_stable", False))

    if current_stable != best_stable:
        return not current_stable

    current_elapsed = float(current_info.get("elapsed_seconds") or 0.0)
    best_elapsed = float(best_info.get("elapsed_seconds") or 0.0)

    # 마지막 tie-breaker: 같은 결과면 더 빠른 세션을 우선한다.
    return current_elapsed < best_elapsed


def fetch_records_with_browser_retry(
    profile_url: str,
    remaining_seconds: float | None = None,
) -> tuple[list[RawRecord], dict[str, Any]]:
    best_records: list[RawRecord] = []
    best_session_info: dict[str, Any] | None = None

    best_info = {
        "attempts": 0,
        "best_record_count": 0,
        "attempt_logs": [],
        "best_strategy": "",
        "mode": "session_restart_retry",
    }

    started_at = time.monotonic()

    for session_index, session_profile in enumerate(BROWSER_SESSION_PROFILES, start=1):
        if remaining_seconds is not None:
            elapsed_total = time.monotonic() - started_at

            if elapsed_total >= remaining_seconds:
                best_info["stopped_by_remaining_time"] = True
                break

        records, info = fetch_records_with_browser_session(
            profile_url=profile_url,
            session_profile=session_profile,
            session_index=session_index,
            target_count=BROWSER_COLLECTION_TARGET_COUNT,
        )

        count = len(records)

        attempt_log = dict(info)
        attempt_log["attempt"] = session_index
        attempt_log["parsed_record_count"] = count

        best_info["attempt_logs"].append(attempt_log)

        if is_better_browser_result(
            current_records=records,
            current_info=info,
            best_records=best_records,
            best_info=best_session_info,
        ):
            best_records = records
            best_session_info = info
            best_info["best_record_count"] = count
            best_info["best_strategy"] = session_profile.get("name", "unknown")

        best_info["attempts"] = session_index

        # 정상 기준은 800개가 아니라 100개 이상 + partial 50 탈출이다.
        # 브라우저 단계에서는 매칭 수를 아직 모를 수 있으므로 raw count만으로 1차 종료한다.
        if count >= MIN_ACCEPTABLE_EXTRACTED_RECORDS and not is_count_near_partial_50(count):
            best_info["stopped_by_acceptable_raw_count"] = True
            break

        if count >= BROWSER_COLLECTION_TARGET_COUNT:
            best_info["stopped_by_collection_target"] = True
            break

        time.sleep(0.8)

    best_info["elapsed_seconds"] = round(time.monotonic() - started_at, 2)

    return best_records, best_info


def get_parse_quality_status(
    extracted_count: int,
    matched_count: int,
    browser_fallback_used: bool,
    browser_attempted: bool,
    partial_50_failure: bool,
) -> str:
    if partial_50_failure:
        return "low_quality_partial_50_records"

    if (
        extracted_count >= MIN_ACCEPTABLE_EXTRACTED_RECORDS
        and matched_count >= MIN_ACCEPTABLE_MATCHED_RECORDS
    ):
        if browser_fallback_used:
            return "ok_browser_fallback_used"

        return "ok_static"

    if browser_attempted:
        return "low_quality_browser_failed"

    return "low_quality_static_only"


def is_parse_quality_ok(profile_info: dict[str, Any]) -> bool:
    return bool(profile_info.get("parse_quality_ok", False))


def get_result_quality_score(
    user_records_df: pd.DataFrame,
    profile_info: dict[str, Any],
) -> tuple[int, int, int, int]:
    partial_50 = 1 if profile_info.get("partial_50_failure") else 0
    quality_ok = 1 if profile_info.get("parse_quality_ok") else 0
    matched = int(profile_info.get("records_matched_count") or len(user_records_df))
    extracted = int(profile_info.get("records_extracted_count") or 0)

    # partial_50이 아닌 결과를 우선한다.
    return -partial_50, quality_ok, matched, extracted


def parse_maishift_profile_to_records_once(
    profile_url: str,
    charts: pd.DataFrame,
    remaining_seconds: float | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    home_url = normalize_profile_url(profile_url, "home")
    records_url = normalize_profile_url(profile_url, "records")

    profile_info: dict[str, Any] = {
        "profile_url": home_url,
        "records_url": records_url,
        "profile_id": extract_profile_id_from_url(profile_url),
        "rating": None,
        "nickname": "",
    }

    home_lines = []
    static_record_lines = []

    static_error = ""
    home_error = ""

    try:
        home_html = fetch_html(home_url)
        home_lines = html_to_visible_lines(home_html)

        profile_info.update(
            extract_profile_info_from_lines(
                lines=home_lines,
                profile_url=home_url,
            )
        )

    except Exception as exc:
        home_error = str(exc)

    best50_records = parse_home_best50_records(home_lines) if home_lines else []

    try:
        records_html = fetch_html(records_url)
        static_record_lines = html_to_visible_lines(records_html)

        if not profile_info.get("nickname") or not profile_info.get("rating"):
            parsed_profile_info = extract_profile_info_from_lines(
                lines=static_record_lines,
                profile_url=records_url,
            )

            profile_info.update(parsed_profile_info)

    except Exception as exc:
        static_error = str(exc)

    static_records = (
        parse_records_page_records(static_record_lines)
        if static_record_lines
        else []
    )

    static_records_count = len(static_records)

    browser_attempted = False
    browser_fallback_used = False
    browser_records_count = 0
    browser_info: dict[str, Any] = {}

    selected_records = static_records

    should_use_browser = (
        USE_BROWSER_RECORDS_FALLBACK
        and static_records_count < BROWSER_COLLECTION_TARGET_COUNT
    )

    if should_use_browser:
        browser_attempted = True

        browser_records, browser_info = fetch_records_with_browser_retry(
            profile_url=records_url,
            remaining_seconds=remaining_seconds,
        )

        browser_records_count = len(browser_records)

        if browser_records_count > static_records_count:
            selected_records = browser_records
            browser_fallback_used = True

    merged_records = merge_best50_flags(
        records=selected_records,
        best50_records=best50_records,
    )

    merged_records = deduplicate_raw_records(merged_records)

    user_records_df, unmatched_records = raw_records_to_dataframe(
        records=merged_records,
        charts=charts,
    )

    extracted_count = len(merged_records)
    matched_count = len(user_records_df)
    unmatched_count = len(unmatched_records)

    partial_50_failure = is_partial_50_failure_counts(
        home_best50_count=len(best50_records),
        static_records_count=static_records_count,
        browser_records_count=browser_records_count,
        extracted_count=extracted_count,
    )

    parse_quality_status = get_parse_quality_status(
        extracted_count=extracted_count,
        matched_count=matched_count,
        browser_fallback_used=browser_fallback_used,
        browser_attempted=browser_attempted,
        partial_50_failure=partial_50_failure,
    )

    parse_quality_ok = is_acceptable_result(
        extracted_count=extracted_count,
        matched_count=matched_count,
        partial_50_failure=partial_50_failure,
    )

    profile_info.update({
        "records_extracted_count": extracted_count,
        "records_matched_count": matched_count,
        "records_unmatched_count": unmatched_count,
        "home_best50_count": len(best50_records),
        "static_records_count": static_records_count,
        "browser_records_count": browser_records_count,
        "browser_attempted": browser_attempted,
        "browser_fallback_used": browser_fallback_used,
        "partial_50_failure": partial_50_failure,
        "parse_quality_status": parse_quality_status,
        "parse_quality_ok": parse_quality_ok,
        "partial_render_records": PARTIAL_RENDER_RECORDS,
        "partial_render_tolerance": PARTIAL_RENDER_TOLERANCE,
        "min_acceptable_extracted_records": MIN_ACCEPTABLE_EXTRACTED_RECORDS,
        "min_acceptable_matched_records": MIN_ACCEPTABLE_MATCHED_RECORDS,
    })

    if home_error:
        profile_info["home_parse_error"] = home_error

    if static_error:
        profile_info["static_records_parse_error"] = static_error

    if browser_info:
        profile_info["browser_parse_info"] = browser_info

    profile_info["unmatched_samples"] = [
        {
            "title": record.title,
            "artist": record.artist,
            "chart_type": record.chart_type,
            "internal_level": record.internal_level,
            "achievement": record.achievement,
            "record_source": record.record_source,
        }
        for record in unmatched_records[:20]
    ]

    return user_records_df, profile_info


def parse_maishift_profile_to_records(
    profile_url: str,
    charts: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    maishift 프로필 URL에서 기록을 파싱한다.

    정상 판단 기준:
    - 800개 이상 같은 고정 기준을 사용하지 않는다.
    - 50개 근처에서 고정되는 partial rendering 상태를 실패로 본다.
    - extracted >= 100 and matched >= 50이면 수용 가능한 정상 파싱으로 본다.

    동작:
    - 브라우저 세션을 새로 열어 여러 번 재시도한다.
    - 정상 품질 결과가 나오면 parse_quality_ok=True를 반환한다.
    - 끝까지 실패하면 가장 나은 결과를 반환하되 parse_quality_ok=False를 유지한다.
    """
    overall_start = time.monotonic()

    best_df: pd.DataFrame | None = None
    best_info: dict[str, Any] | None = None
    attempt_summaries: list[dict[str, Any]] = []

    for attempt in range(1, PROFILE_PARSE_MAX_ATTEMPTS + 1):
        elapsed_overall = time.monotonic() - overall_start
        remaining_seconds = PROFILE_PARSE_HARD_TIMEOUT_SECONDS - elapsed_overall

        if remaining_seconds <= 0:
            break

        attempt_start = time.monotonic()

        user_records_df, profile_info = parse_maishift_profile_to_records_once(
            profile_url=profile_url,
            charts=charts,
            remaining_seconds=remaining_seconds,
        )

        profile_info["profile_parse_attempt"] = attempt
        profile_info["profile_parse_attempt_elapsed_seconds"] = round(
            time.monotonic() - attempt_start,
            2,
        )

        attempt_summary = {
            "attempt": attempt,
            "records_extracted_count": profile_info.get("records_extracted_count"),
            "records_matched_count": profile_info.get("records_matched_count"),
            "records_unmatched_count": profile_info.get("records_unmatched_count"),
            "static_records_count": profile_info.get("static_records_count"),
            "browser_records_count": profile_info.get("browser_records_count"),
            "partial_50_failure": profile_info.get("partial_50_failure"),
            "parse_quality_status": profile_info.get("parse_quality_status"),
            "parse_quality_ok": profile_info.get("parse_quality_ok"),
            "browser_fallback_used": profile_info.get("browser_fallback_used"),
            "elapsed_seconds": profile_info.get("profile_parse_attempt_elapsed_seconds"),
            "browser_parse_info": profile_info.get("browser_parse_info"),
        }

        attempt_summaries.append(attempt_summary)

        if best_df is None or best_info is None:
            best_df = user_records_df
            best_info = profile_info

        else:
            current_score = get_result_quality_score(user_records_df, profile_info)
            best_score = get_result_quality_score(best_df, best_info)

            if current_score > best_score:
                best_df = user_records_df
                best_info = profile_info

        # 정상 품질이면 반환한다.
        # 800개 같은 고정 full 기준을 기다리지 않는다.
        if is_parse_quality_ok(profile_info):
            profile_info["profile_parse_attempts"] = attempt_summaries
            profile_info["profile_parse_total_attempts"] = attempt
            profile_info["profile_parse_selected_attempt"] = attempt
            profile_info["profile_parse_retry_used"] = attempt > 1
            profile_info["profile_parse_best_effort"] = False
            profile_info["profile_parse_total_elapsed_seconds"] = round(
                time.monotonic() - overall_start,
                2,
            )

            return user_records_df, profile_info

        if attempt < PROFILE_PARSE_MAX_ATTEMPTS:
            time.sleep(PROFILE_PARSE_RETRY_WAIT_SECONDS)

    if best_df is None:
        best_df = pd.DataFrame(columns=USER_RECORD_COLUMNS)

    if best_info is None:
        best_info = {
            "profile_url": normalize_profile_url(profile_url, "home"),
            "records_url": normalize_profile_url(profile_url, "records"),
            "profile_id": extract_profile_id_from_url(profile_url),
            "rating": None,
            "nickname": extract_profile_id_from_url(profile_url),
            "records_extracted_count": 0,
            "records_matched_count": 0,
            "records_unmatched_count": 0,
            "partial_50_failure": False,
            "parse_quality_status": "low_quality_no_result",
            "parse_quality_ok": False,
        }

    selected_attempt = int(best_info.get("profile_parse_attempt", 0) or 0)

    best_info["profile_parse_attempts"] = attempt_summaries
    best_info["profile_parse_total_attempts"] = len(attempt_summaries)
    best_info["profile_parse_selected_attempt"] = selected_attempt
    best_info["profile_parse_retry_used"] = len(attempt_summaries) > 1
    best_info["profile_parse_best_effort"] = True
    best_info["profile_parse_total_elapsed_seconds"] = round(
        time.monotonic() - overall_start,
        2,
    )

    return best_df, best_info