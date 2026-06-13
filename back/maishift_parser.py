import re
import time
import unicodedata
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup


REQUEST_DELAY_SECONDS = 1.0

USE_BROWSER_RECORDS_FALLBACK = True
BROWSER_RECORDS_TARGET_COUNT = 1000
BROWSER_RECORDS_MAX_SCROLLS = 25
BROWSER_RECORDS_STABLE_ROUNDS = 6


RANK_BASE_SET = {
    "SSS",
    "SS",
    "S",
    "AAA",
    "AA",
    "A",
    "BBB",
    "BB",
    "B",
    "C",
    "D",
}

RANK_SET = {
    "SSS+",
    "SSS",
    "SS+",
    "SS",
    "S+",
    "S",
    "AAA",
    "AA",
    "A",
    "BBB",
    "BB",
    "B",
    "C",
    "D",
}

COMBO_BASE_SET = {
    "FC",
    "AP",
}

SYNC_BASE_SET = {
    "SYNC",
    "FS",
    "FDX",
}


# ------------------------------------------------------------
# Basic normalization
# ------------------------------------------------------------

def normalize_line(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text))
    text = text.replace("\u200b", "")
    text = text.replace("⁺", "+")
    return text.strip()


def normalize_title(text: str) -> str:
    if pd.isna(text):
        return ""

    text = unicodedata.normalize("NFKC", str(text))
    text = text.replace("♥", "♡")
    text = text.replace("⁺", "+")
    text = re.sub(r"\s+", "", text)

    return text.lower()


def normalize_profile_url(profile_url: str, page: str = "home") -> str:
    profile_url = str(profile_url).strip()

    if not profile_url.startswith("http"):
        profile_url = "https://maimai.shiftpsh.com/" + profile_url.lstrip("/")

    parsed = urlparse(profile_url)

    if parsed.netloc not in {"maimai.shiftpsh.com", "www.maimai.shiftpsh.com"}:
        raise ValueError("maishift 프로필 URL만 입력할 수 있습니다.")

    match = re.search(r"/profile/([^/]+)", parsed.path)

    if not match:
        raise ValueError("프로필 URL 형식이 올바르지 않습니다.")

    profile_id = match.group(1)

    return f"https://maimai.shiftpsh.com/profile/{profile_id}/{page}"


def extract_profile_id(profile_url: str) -> str:
    match = re.search(r"/profile/([^/]+)", profile_url)

    if not match:
        return "unknown"

    return match.group(1)


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()

    time.sleep(REQUEST_DELAY_SECONDS)

    return response.text


def html_to_visible_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")

    for img in soup.find_all("img"):
        alt = img.get("alt")
        if alt:
            img.replace_with(f"\n{alt}\n")

    text = soup.get_text("\n")
    lines = [normalize_line(line) for line in text.splitlines()]

    return [line for line in lines if line]


# ------------------------------------------------------------
# Profile rating parsing
# ------------------------------------------------------------

def parse_profile_rating(lines: list[str]) -> int | None:
    markers = {"플레이 카운트", "Play Count"}

    for i, line in enumerate(lines):
        if line not in markers:
            continue

        window = lines[max(0, i - 15):i]

        # 15432 / 15,432
        for token in reversed(window):
            clean = token.replace(",", "").replace(" ", "")

            if re.fullmatch(r"\d{5}", clean):
                return int(clean)

        # 1 / 5 / 4 / 3 / 2
        digit_tokens = []

        for token in reversed(window):
            clean = token.replace(",", "").replace(" ", "")

            if re.fullmatch(r"\d", clean):
                digit_tokens.append(clean)
            elif digit_tokens:
                break

        if len(digit_tokens) >= 5:
            rating_text = "".join(reversed(digit_tokens[:5]))
            return int(rating_text)

    return None


# ------------------------------------------------------------
# Shared parser utilities
# ------------------------------------------------------------

def normalize_chart_type(line: str) -> str | None:
    text = normalize_line(line).upper()

    if re.search(r"\bDX\b", text):
        return "dx"

    if (
        re.search(r"\bSTANDARD\b", text)
        or re.search(r"\bSTD\b", text)
        or re.search(r"\bST\b", text)
    ):
        return "std"

    return None


def is_rating_number(line: str) -> bool:
    return bool(re.fullmatch(r"\d{2,4}", str(line).strip()))


def is_stop_header(line: str) -> bool:
    return line in {
        "기록",
        "순회",
        "사진관",
        "히스토리",
        "전체",
        "History",
        "All",
    }


def is_integer_token(token: str) -> bool:
    return bool(re.fullmatch(r"\d+", normalize_line(token)))


# ------------------------------------------------------------
# Fragment parsers for records page
# ------------------------------------------------------------

def parse_record_level_fragments(lines: list[str], start_idx: int) -> tuple[float | None, int]:
    """
    records 페이지용.

    처리 구조:
    14 / . / 4 / DX
    14 / .4 / DX
    13 / .9 / + / DX
    13 / . / 9 / + / DX
    """
    if start_idx >= len(lines):
        return None, start_idx

    first = normalize_line(lines[start_idx])

    if not re.fullmatch(r"\d{1,2}", first):
        return None, start_idx

    idx = start_idx + 1
    level_text = first

    if idx < len(lines):
        token = normalize_line(lines[idx])

        # 14 / . / 4
        if token == ".":
            if idx + 1 < len(lines) and re.fullmatch(r"\d", normalize_line(lines[idx + 1])):
                level_text += "." + normalize_line(lines[idx + 1])
                idx += 2
            else:
                return None, start_idx

        # 14 / .4
        elif re.fullmatch(r"\.\d", token):
            level_text += token
            idx += 1

    if idx < len(lines) and normalize_line(lines[idx]) == "+":
        idx += 1

    try:
        return float(level_text), idx
    except ValueError:
        return None, start_idx


def parse_rank_fragments(
    lines: list[str],
    start_idx: int,
    max_lookahead: int = 40,
) -> tuple[str | None, int | None, int]:
    """
    처리 구조:
    SSS+
    SSS / +
    SS+
    SS / +
    S+
    S / +
    AAA
    """
    end = min(len(lines), start_idx + max_lookahead)

    for idx in range(start_idx, end):
        token = normalize_line(lines[idx]).upper()

        if token in RANK_SET:
            return token, idx, idx + 1

        if token not in RANK_BASE_SET:
            continue

        if token in {"SSS", "SS", "S"}:
            if idx + 1 < len(lines) and normalize_line(lines[idx + 1]) == "+":
                return token + "+", idx, idx + 2

        return token, idx, idx + 1

    return None, None, start_idx


def parse_combo_sync_or_score(
    lines: list[str],
    start_idx: int,
    max_lookahead: int = 20,
) -> tuple[str, str, float | None, int | None, int | None]:
    """
    rank 뒤쪽에서 combo, sync, score, chart_rating을 읽는다.

    처리 구조:
    SYNC / 100 / . / 5079 / % / 324
    SYNC / 100. / 5079% / 324
    FC+ / 100. / 8326% / 312
    100.5079%324
    """
    combo = ""
    sync = ""
    achievement = None
    chart_rating = None
    score_end_idx = None

    idx = start_idx
    end = min(len(lines), start_idx + max_lookahead)

    while idx < end:
        token = normalize_line(lines[idx]).upper()

        # 100 / . / 5079 / % / 324
        if (
            re.fullmatch(r"\d{1,3}", token)
            and idx + 4 < len(lines)
            and normalize_line(lines[idx + 1]) == "."
            and re.fullmatch(r"\d+", normalize_line(lines[idx + 2]))
            and normalize_line(lines[idx + 3]) == "%"
            and re.fullmatch(r"\d{1,4}", normalize_line(lines[idx + 4]))
        ):
            achievement_text = f"{token}.{normalize_line(lines[idx + 2])}"
            achievement = float(achievement_text)
            chart_rating = int(normalize_line(lines[idx + 4]))
            score_end_idx = idx + 5
            break

        # 100. / 5079% / 324
        if (
            re.fullmatch(r"\d{1,3}\.", token)
            and idx + 2 < len(lines)
            and re.fullmatch(r"\d+%", normalize_line(lines[idx + 1]))
            and re.fullmatch(r"\d{1,4}", normalize_line(lines[idx + 2]))
        ):
            achievement_text = token + normalize_line(lines[idx + 1]).replace("%", "")
            achievement = float(achievement_text)
            chart_rating = int(normalize_line(lines[idx + 2]))
            score_end_idx = idx + 3
            break

        # 100.5079%324
        one_line = re.fullmatch(
            r"(?P<achievement>\d{1,3}(?:\.\d+)?)\s*%\s*(?P<rating>\d{1,4})",
            token,
        )

        if one_line:
            achievement = float(one_line.group("achievement"))
            chart_rating = int(one_line.group("rating"))
            score_end_idx = idx + 1
            break

        # combo: FC, FC+, AP, AP+
        if token in {"FC", "FC+", "AP", "AP+"}:
            combo = token
            idx += 1
            continue

        if token in COMBO_BASE_SET:
            if idx + 1 < len(lines) and normalize_line(lines[idx + 1]) == "+":
                combo = token + "+"
                idx += 2
                continue

            combo = token
            idx += 1
            continue

        # sync: SYNC, FS, FS+, FDX, FDX+
        if token in {"SYNC", "FS", "FS+", "FDX", "FDX+"}:
            sync = token
            idx += 1
            continue

        if token in SYNC_BASE_SET:
            if (
                token in {"FS", "FDX"}
                and idx + 1 < len(lines)
                and normalize_line(lines[idx + 1]) == "+"
            ):
                sync = token + "+"
                idx += 2
                continue

            sync = token
            idx += 1
            continue

        idx += 1

    return combo, sync, achievement, chart_rating, score_end_idx


def parse_best50_version_fragments(
    lines: list[str],
    chart_type_idx: int,
    after_chart_type_idx: int,
) -> tuple[bool, str | None, int | None, int]:
    """
    records 페이지의 Best50 표기를 파싱한다.

    처리 구조:
    DX / OLD # / 1
    DX / OLD #1
    STANDARD / NEW # / 1
    STANDARD / NEW #1
    """
    is_best50 = False
    best50_section = None
    best50_order = None
    idx = after_chart_type_idx

    chart_type_line = normalize_line(lines[chart_type_idx]).upper()

    inline_match = re.search(r"\b(NEW|OLD)\s*#\s*(\d+)", chart_type_line)

    if inline_match:
        return (
            True,
            inline_match.group(1).lower(),
            int(inline_match.group(2)),
            idx,
        )

    if idx < len(lines):
        token = normalize_line(lines[idx]).upper()

        split_match = re.fullmatch(r"(NEW|OLD)\s*#", token)

        if split_match and idx + 1 < len(lines) and is_integer_token(lines[idx + 1]):
            is_best50 = True
            best50_section = split_match.group(1).lower()
            best50_order = int(normalize_line(lines[idx + 1]))
            idx += 2
            return is_best50, best50_section, best50_order, idx

        inline_next_match = re.fullmatch(r"(NEW|OLD)\s*#\s*(\d+)", token)

        if inline_next_match:
            is_best50 = True
            best50_section = inline_next_match.group(1).lower()
            best50_order = int(inline_next_match.group(2))
            idx += 1
            return is_best50, best50_section, best50_order, idx

        if token in {"NEW", "OLD"}:
            best50_section = token.lower()
            idx += 1

            if idx < len(lines) and re.fullmatch(r"#\s*\d+", normalize_line(lines[idx])):
                is_best50 = True
                best50_order = int(re.sub(r"\D", "", normalize_line(lines[idx])))
                idx += 1

            return is_best50, best50_section, best50_order, idx

    return is_best50, best50_section, best50_order, idx


# ------------------------------------------------------------
# /home Best 50 parser
# ------------------------------------------------------------

def parse_level_from_fragments(lines: list[str], start_idx: int) -> tuple[float | None, int]:
    return parse_record_level_fragments(lines, start_idx)


def find_home_best50_start(lines: list[str]) -> int | None:
    for i, line in enumerate(lines):
        clean = line.replace("#", "").strip()

        if clean in {"레이팅 대상곡", "Best 50"}:
            return i

    return None


def parse_achievement_start_home(lines: list[str], start_idx: int) -> int | None:
    for i in range(start_idx, min(start_idx + 12, len(lines))):
        if re.fullmatch(r"\d{1,3}(?:\.\d+)?", lines[i]):
            if i + 1 < len(lines) and lines[i + 1] == "%":
                return i

    return None


def parse_achievement_from_index_home(lines: list[str], achievement_idx: int) -> tuple[float, str, int]:
    achievement = float(lines[achievement_idx])
    rank = lines[achievement_idx + 2] if achievement_idx + 2 < len(lines) else ""

    return achievement, rank, achievement_idx + 3


def extract_best50_records_from_home_lines(lines: list[str]) -> list[dict]:
    start_idx = find_home_best50_start(lines)

    if start_idx is None:
        raise ValueError("레이팅 대상곡 영역을 찾지 못했습니다.")

    records = []
    i = start_idx + 1
    section = None

    while i < len(lines):
        line = lines[i]

        if is_stop_header(line):
            break

        if line in {"최신곡", "New Songs"}:
            section = "new"
            i += 1
            continue

        if line in {"구곡", "Old Songs"}:
            section = "old"
            i += 1
            continue

        chart_type = normalize_chart_type(line)

        if chart_type is None:
            i += 1
            continue

        try:
            rating_idx = None

            for j in range(i + 1, min(i + 8, len(lines))):
                if is_rating_number(lines[j]):
                    rating_idx = j
                    break

            if rating_idx is None:
                i += 1
                continue

            displayed_rank = "".join(lines[i + 1:rating_idx])
            chart_rating = int(lines[rating_idx])

            internal_level, title_start_idx = parse_level_from_fragments(lines, rating_idx + 1)

            if internal_level is None:
                i += 1
                continue

            achievement_idx = parse_achievement_start_home(lines, title_start_idx)

            if achievement_idx is None:
                i += 1
                continue

            title_parts = lines[title_start_idx:achievement_idx]
            title = " ".join(title_parts).strip()

            achievement, rank, end_idx = parse_achievement_from_index_home(lines, achievement_idx)

            records.append({
                "title": title,
                "chart_type": chart_type,
                "internal_level": internal_level,
                "achievement": achievement,
                "rank": rank or displayed_rank,
                "chart_rating": chart_rating,
                "combo": "",
                "sync": "",
                "is_best50": True,
                "best50_section": section or "unknown",
                "best50_order": None,
                "record_source": "home_best50",
            })

            i = end_idx

        except Exception:
            i += 1

    return records


# ------------------------------------------------------------
# /records parser
# ------------------------------------------------------------

def find_records_table_start(lines: list[str]) -> int:
    for i, line in enumerate(lines):
        if normalize_line(line) == "Re:M":
            return i + 1

    for i, line in enumerate(lines):
        if normalize_line(line) == "채보 유형":
            return i

    for i, line in enumerate(lines):
        if normalize_line(line) == "Records":
            return i

    return 0


def find_chart_type_after_level(
    lines: list[str],
    start_idx: int,
    max_lookahead: int = 8,
) -> tuple[str | None, int | None]:
    end = min(len(lines), start_idx + max_lookahead)

    for idx in range(start_idx, end):
        chart_type = normalize_chart_type(lines[idx])

        if chart_type:
            return chart_type, idx

    return None, None


def extract_records_from_record_lines(lines: list[str]) -> list[dict]:
    """
    /records 페이지의 visible text에서 기록을 파싱한다.

    처리 구조 예:
    14 / . / 4 / DX / OLD # / 1 / FLUFFY FLASH / Kobaryo / SSS / + / SYNC / 100 / . / 5079 / % / 324
    14 / .4 / DX / OLD #1 / FLUFFY FLASH / Kobaryo / SSS+ / SYNC / 100. / 5079% / 324
    """
    records = []
    i = find_records_table_start(lines)

    while i < len(lines):
        internal_level, level_end_idx = parse_record_level_fragments(lines, i)

        if internal_level is None:
            i += 1
            continue

        chart_type, chart_type_idx = find_chart_type_after_level(lines, level_end_idx)

        if chart_type is None or chart_type_idx is None:
            i += 1
            continue

        is_best50, best50_section, best50_order, title_start_idx = parse_best50_version_fragments(
            lines=lines,
            chart_type_idx=chart_type_idx,
            after_chart_type_idx=chart_type_idx + 1,
        )

        rank, rank_idx, rank_end_idx = parse_rank_fragments(
            lines=lines,
            start_idx=title_start_idx,
            max_lookahead=50,
        )

        if rank is None or rank_idx is None:
            i += 1
            continue

        title_parts = []

        for token in lines[title_start_idx:rank_idx]:
            clean = normalize_line(token)

            if not clean:
                continue

            if clean in {"Image"}:
                continue

            title_parts.append(clean)

        title = " ".join(title_parts).strip()

        if not title:
            i += 1
            continue

        combo, sync, achievement, chart_rating, score_end_idx = parse_combo_sync_or_score(
            lines=lines,
            start_idx=rank_end_idx,
            max_lookahead=25,
        )

        if achievement is None or chart_rating is None or score_end_idx is None:
            i += 1
            continue

        records.append({
            "title": title,
            "chart_type": chart_type,
            "internal_level": internal_level,
            "achievement": achievement,
            "rank": rank,
            "chart_rating": chart_rating,
            "combo": combo,
            "sync": sync,
            "is_best50": is_best50,
            "best50_section": best50_section or "unknown",
            "best50_order": best50_order,
            "record_source": "records",
        })

        i = score_end_idx

    return records


def fetch_records_lines_with_browser(
    records_url: str,
    target_count: int = BROWSER_RECORDS_TARGET_COUNT,
    max_scrolls: int = BROWSER_RECORDS_MAX_SCROLLS,
) -> tuple[list[str], int]:
    """
    maishift records 페이지는 초기 HTML에는 약 50개만 있고,
    브라우저 스크롤 시 추가 records가 렌더링된다.

    이 함수는 Playwright로 실제 페이지를 열고 스크롤한 뒤,
    현재 DOM의 HTML을 html_to_visible_lines()로 다시 파싱한다.

    주의:
    - inner_text()를 쓰면 DX/STANDARD 이미지 alt가 빠질 수 있다.
    - 따라서 page.content() 기반으로 img alt를 복원한다.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "Playwright가 설치되어 있지 않습니다. "
            "back venv에서 `python -m pip install playwright` 및 "
            "`python -m playwright install chromium`을 실행하세요."
        ) from e

    best_lines: list[str] = []
    best_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page = browser.new_page(
            viewport={
                "width": 1600,
                "height": 1200,
            }
        )

        page.goto(
            records_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        page.wait_for_timeout(2000)

        previous_height = -1
        previous_count = -1
        stable_rounds = 0

        for _ in range(max_scrolls + 1):
            html = page.content()
            lines = html_to_visible_lines(html)
            parsed_records = extract_records_from_record_lines(lines)
            parsed_count = len(parsed_records)

            if parsed_count > best_count:
                best_count = parsed_count
                best_lines = lines

            if best_count >= target_count:
                break

            current_height = page.evaluate("document.documentElement.scrollHeight")

            if current_height == previous_height and parsed_count == previous_count:
                stable_rounds += 1
            else:
                stable_rounds = 0

            if stable_rounds >= BROWSER_RECORDS_STABLE_ROUNDS:
                break

            previous_height = current_height
            previous_count = parsed_count

            page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            page.wait_for_timeout(800)

        browser.close()

    return best_lines, best_count


# ------------------------------------------------------------
# Matching with base chart DB
# ------------------------------------------------------------

def prepare_chart_db(charts: pd.DataFrame) -> pd.DataFrame:
    charts = charts.copy()

    charts["title_norm"] = charts["title"].apply(normalize_title)

    if "artist" in charts.columns:
        charts["artist_norm"] = charts["artist"].apply(normalize_title)
    else:
        charts["artist_norm"] = ""

    charts["title_artist_norm"] = charts["title_norm"] + charts["artist_norm"]
    charts["title_len"] = charts["title_norm"].str.len()

    return charts


def title_match_score(
    record_title_norm: str,
    chart_title_norm: str,
    chart_title_artist_norm: str,
) -> float:
    if not record_title_norm or not chart_title_norm:
        return 0.0

    if record_title_norm == chart_title_norm:
        return 100.0

    if record_title_norm == chart_title_artist_norm:
        return 98.0

    if record_title_norm.startswith(chart_title_norm):
        return 90.0 + min(len(chart_title_norm), 30) / 100.0

    if len(chart_title_norm) >= 5 and chart_title_norm in record_title_norm:
        return 70.0 + min(len(chart_title_norm), 30) / 100.0

    return 0.0


def match_chart_ids(records: list[dict], charts: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    charts = prepare_chart_db(charts)

    matched = []
    unmatched = []

    difficulty_priority = {
        "remaster": 5,
        "master": 4,
        "expert": 3,
        "advanced": 2,
        "basic": 1,
    }

    for record in records:
        record_title_norm = normalize_title(record["title"])
        chart_type = record["chart_type"]
        internal_level = float(record["internal_level"])

        candidates = charts[
            (charts["chart_type"] == chart_type)
            & ((charts["internal_level"] - internal_level).abs() <= 0.15)
        ].copy()

        if candidates.empty:
            unmatched.append(record)
            continue

        candidates["title_match_score"] = candidates.apply(
            lambda row: title_match_score(
                record_title_norm=record_title_norm,
                chart_title_norm=row["title_norm"],
                chart_title_artist_norm=row["title_artist_norm"],
            ),
            axis=1,
        )

        candidates = candidates[candidates["title_match_score"] > 0].copy()

        if candidates.empty:
            unmatched.append(record)
            continue

        candidates["difficulty_priority"] = (
            candidates["difficulty"].map(difficulty_priority).fillna(0)
        )
        candidates["level_diff"] = (
            candidates["internal_level"] - internal_level
        ).abs()

        chosen = candidates.sort_values(
            [
                "title_match_score",
                "level_diff",
                "title_len",
                "difficulty_priority",
            ],
            ascending=[False, True, False, False],
        ).iloc[0]

        matched_record = {
            **record,
            "chart_id": chosen["chart_id"],
            "song_id": chosen["song_id"],
            "matched_title": chosen["title"],
            "difficulty": chosen["difficulty"],
            "level": chosen["level"],
            "base_internal_level": float(chosen["internal_level"]),
            "category": chosen.get("category", ""),
            "song_version": chosen.get("song_version", ""),
            "chart_version": chosen.get("chart_version", ""),
            "is_new": bool(chosen.get("is_new", False)),
        }

        matched.append(matched_record)

    return matched, unmatched


def matched_records_to_df(matched_records: list[dict]) -> pd.DataFrame:
    rows = []

    for rec in matched_records:
        rows.append({
            "chart_id": rec["chart_id"],
            "achievement": rec["achievement"],
            "rank": rec["rank"],
            "play_count": 1,
            "chart_rating": rec["chart_rating"],
            "is_best50": bool(rec.get("is_best50", False)),
            "best50_section": rec.get("best50_section", "unknown"),
            "best50_order": rec.get("best50_order"),
            "record_source": rec.get("record_source", "unknown"),
            "combo": rec.get("combo", ""),
            "sync": rec.get("sync", ""),
        })

    return pd.DataFrame(rows)


def combine_record_sources(records_df: pd.DataFrame, best50_df: pd.DataFrame) -> pd.DataFrame:
    frames = []

    if records_df is not None and not records_df.empty:
        temp = records_df.copy()
        temp["source_priority"] = temp["record_source"].map({
            "records": 0,
            "home_best50": 1,
        }).fillna(9)
        frames.append(temp)

    if best50_df is not None and not best50_df.empty:
        temp = best50_df.copy()
        temp["source_priority"] = temp["record_source"].map({
            "records": 0,
            "home_best50": 1,
        }).fillna(9)
        frames.append(temp)

    if not frames:
        return pd.DataFrame(
            columns=[
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
        )

    combined = pd.concat(frames, ignore_index=True)

    combined = combined.sort_values(
        ["chart_id", "is_best50", "source_priority", "chart_rating", "achievement"],
        ascending=[True, False, True, False, False],
    )

    combined = combined.drop_duplicates(subset=["chart_id"], keep="first")
    combined = combined.drop(columns=["source_priority"], errors="ignore")

    return combined.reset_index(drop=True)


# ------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------

def parse_maishift_profile_to_records(
    profile_url: str,
    charts: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    """
    입력 프로필 URL을 받아 현재 유저 기록 DataFrame을 생성한다.

    처리 순서:
    1. /records 정적 HTML 파싱
    2. records가 50개 이하이면 Playwright 브라우저 스크롤 fallback
    3. /home Best 50 파싱
    4. records + Best 50 병합
    """
    home_url = normalize_profile_url(profile_url, page="home")
    records_url = normalize_profile_url(profile_url, page="records")
    profile_id = extract_profile_id(home_url)

    records_raw = []
    records_matched = []
    records_unmatched = []
    records_rating = None
    records_source_mode = "static_html"
    records_browser_error = ""

    best50_raw = []
    best50_matched = []
    best50_unmatched = []
    home_rating = None

    try:
        records_html = fetch_html(records_url)
        records_lines = html_to_visible_lines(records_html)

        records_rating = parse_profile_rating(records_lines)
        records_raw = extract_records_from_record_lines(records_lines)

        if USE_BROWSER_RECORDS_FALLBACK and len(records_raw) <= 50:
            try:
                browser_lines, browser_count = fetch_records_lines_with_browser(
                    records_url=records_url,
                    target_count=BROWSER_RECORDS_TARGET_COUNT,
                    max_scrolls=BROWSER_RECORDS_MAX_SCROLLS,
                )

                browser_records_raw = extract_records_from_record_lines(browser_lines)

                if len(browser_records_raw) > len(records_raw):
                    records_lines = browser_lines
                    records_raw = browser_records_raw
                    records_source_mode = "browser_scroll"

            except Exception as e:
                records_browser_error = str(e)

        records_matched, records_unmatched = match_chart_ids(records_raw, charts)

    except Exception as e:
        records_unmatched.append({
            "title": "__records_page_parse_failed__",
            "chart_type": "",
            "internal_level": "",
            "error": str(e),
        })

    try:
        home_html = fetch_html(home_url)
        home_lines = html_to_visible_lines(home_html)

        home_rating = parse_profile_rating(home_lines)
        best50_raw = extract_best50_records_from_home_lines(home_lines)
        best50_matched, best50_unmatched = match_chart_ids(best50_raw, charts)

    except Exception as e:
        best50_unmatched.append({
            "title": "__home_best50_parse_failed__",
            "chart_type": "",
            "internal_level": "",
            "error": str(e),
        })

    records_df = matched_records_to_df(records_matched)
    best50_df = matched_records_to_df(best50_matched)

    combined_df = combine_record_sources(records_df, best50_df)

    if combined_df.empty:
        raise ValueError("프로필에서 매칭 가능한 기록을 찾지 못했습니다.")

    profile_rating = records_rating or home_rating
    all_unmatched = records_unmatched + best50_unmatched

    profile_info = {
        "profile_id": profile_id,
        "profile_url": home_url,
        "records_url": records_url,
        "rating": profile_rating,

        "records_source_mode": records_source_mode,
        "records_browser_error": records_browser_error,
        "browser_records_target_count": BROWSER_RECORDS_TARGET_COUNT,
        "browser_records_max_scrolls": BROWSER_RECORDS_MAX_SCROLLS,

        "extracted_count": int(len(combined_df)),
        "matched_count": int(len(combined_df)),
        "unmatched_count": int(len(all_unmatched)),

        "records_extracted_count": int(len(records_raw)),
        "records_matched_count": int(len(records_matched)),
        "records_unmatched_count": int(len(records_unmatched)),

        "best50_extracted_count": int(len(best50_raw)),
        "best50_matched_count": int(len(best50_matched)),
        "best50_unmatched_count": int(len(best50_unmatched)),

        "combined_record_count": int(len(combined_df)),
        "best50_in_combined_count": int(combined_df["is_best50"].sum())
        if "is_best50" in combined_df.columns
        else 0,

        "unmatched_titles": [
            {
                "title": rec.get("title"),
                "chart_type": rec.get("chart_type"),
                "internal_level": rec.get("internal_level"),
                "error": rec.get("error", ""),
            }
            for rec in all_unmatched[:10]
        ],
    }

    return combined_df, profile_info