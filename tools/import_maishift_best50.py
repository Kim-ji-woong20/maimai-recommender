import re
import unicodedata
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

PROFILE_URL = "https://maimai.shiftpsh.com/profile/kong3171/home"

CHARTS_PATH = Path("back/data/maimai_charts_13_15.csv")
OUT_RECORDS_PATH = Path("back/data/friend_records.csv")
OUT_UNMATCHED_PATH = Path("back/data/friend_records_unmatched.csv")
DEBUG_LINES_PATH = Path("back/data/maishift_debug_lines.txt")


def normalize_line(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text))
    text = text.replace("\u200b", "")
    return text.strip()


def normalize_title(text: str) -> str:
    if pd.isna(text):
        return ""

    text = unicodedata.normalize("NFKC", str(text))
    text = text.replace("♥", "♡")
    text = re.sub(r"\s+", "", text)
    return text.lower()


def fetch_visible_lines(url: str) -> list[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    for img in soup.find_all("img"):
        alt = img.get("alt")
        if alt:
            img.replace_with(f"\n{alt}\n")

    text = soup.get_text("\n")
    lines = [normalize_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    DEBUG_LINES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DEBUG_LINES_PATH, "w", encoding="utf-8") as f:
        for idx, line in enumerate(lines):
            f.write(f"{idx}: {repr(line)}\n")

    return lines


def find_rating_section_start(lines: list[str]) -> int | None:
    for i, line in enumerate(lines):
        clean = line.replace("#", "").strip()

        if clean in {"레이팅 대상곡", "Best 50"}:
            return i

    return None


def is_chart_type(line: str) -> bool:
    return line.upper() in {"DX", "STANDARD", "STD"}


def convert_chart_type(line: str) -> str:
    line = line.upper()

    if line == "DX":
        return "dx"

    return "std"


def is_rating_number(line: str) -> bool:
    return bool(re.fullmatch(r"\d{2,4}", line))


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


def parse_level_from_fragments(lines: list[str], start_idx: int) -> tuple[float | None, int]:
    """
    예:
    14 . 2      -> 14.2
    13 . 8 +    -> 13.8
    15          -> 15.0
    """
    if start_idx >= len(lines):
        return None, start_idx

    first = lines[start_idx]

    if not re.fullmatch(r"\d{1,2}", first):
        return None, start_idx

    level_text = first
    idx = start_idx + 1

    if idx < len(lines) and lines[idx] == ".":
        if idx + 1 < len(lines) and re.fullmatch(r"\d", lines[idx + 1]):
            level_text += "." + lines[idx + 1]
            idx += 2

    if idx < len(lines) and lines[idx] == "+":
        idx += 1

    try:
        return float(level_text), idx
    except ValueError:
        return None, start_idx


def parse_achievement_start(lines: list[str], start_idx: int) -> int | None:
    """
    achievement 시작 위치를 찾는다.
    예:
    100.6602
    %
    SSS+
    """
    for i in range(start_idx, min(start_idx + 12, len(lines))):
        if re.fullmatch(r"\d{1,3}(?:\.\d+)?", lines[i]):
            if i + 1 < len(lines) and lines[i + 1] == "%":
                return i

    return None


def parse_achievement_from_index(lines: list[str], achievement_idx: int) -> tuple[float, str, int]:
    achievement = float(lines[achievement_idx])
    rank = lines[achievement_idx + 2] if achievement_idx + 2 < len(lines) else ""

    return achievement, rank, achievement_idx + 3


def extract_rating_records(lines: list[str]) -> list[dict]:
    start_idx = find_rating_section_start(lines)

    if start_idx is None:
        print("레이팅 대상곡 section을 찾지 못했습니다.")
        print(f"디버그 파일을 확인하세요: {DEBUG_LINES_PATH}")
        raise ValueError("레이팅 대상곡 section을 찾지 못했습니다.")

    records = []
    i = start_idx + 1

    while i < len(lines):
        line = lines[i]

        if is_stop_header(line):
            break

        if not is_chart_type(line):
            i += 1
            continue

        chart_type = convert_chart_type(line)

        try:
            rating_idx = None

            # DX/STANDARD 뒤에 SSS, + 등이 끼고 그 다음 곡별 rating 숫자가 나온다.
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

            achievement_idx = parse_achievement_start(lines, title_start_idx)

            if achievement_idx is None:
                i += 1
                continue

            title_parts = lines[title_start_idx:achievement_idx]
            title = " ".join(title_parts).strip()

            achievement, rank, end_idx = parse_achievement_from_index(lines, achievement_idx)

            records.append({
                "title": title,
                "chart_type": chart_type,
                "internal_level": internal_level,
                "achievement": achievement,
                "rank": rank or displayed_rank,
                "chart_rating": chart_rating,
                "play_count": 1,
            })

            i = end_idx

        except Exception:
            i += 1

    return records


def match_chart_ids(records: list[dict], charts: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    charts = charts.copy()
    charts["title_norm"] = charts["title"].apply(normalize_title)

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
        title_norm = normalize_title(record["title"])
        chart_type = record["chart_type"]
        internal_level = record["internal_level"]

        candidates = charts[
            (charts["title_norm"] == title_norm)
            & (charts["chart_type"] == chart_type)
            & ((charts["internal_level"] - internal_level).abs() <= 0.051)
        ].copy()

        # 제목은 맞지만 내부 상수 표기가 약간 다른 경우 완화
        if candidates.empty:
            candidates = charts[
                (charts["title_norm"] == title_norm)
                & (charts["chart_type"] == chart_type)
            ].copy()

            if not candidates.empty:
                candidates["level_diff"] = (
                    candidates["internal_level"] - internal_level
                ).abs()
                candidates = candidates[candidates["level_diff"] <= 0.15]

        # 곡명이 2줄로 나뉘거나 부제가 빠지는 경우를 위한 완화 매칭
        if candidates.empty:
            candidates = charts[
                (charts["chart_type"] == chart_type)
                & (
                    charts["title_norm"].apply(lambda x: title_norm in x or x in title_norm)
                )
            ].copy()

            if not candidates.empty:
                candidates["level_diff"] = (
                    candidates["internal_level"] - internal_level
                ).abs()
                candidates = candidates[candidates["level_diff"] <= 0.15]

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
            ["level_diff", "difficulty_priority"],
            ascending=[True, False]
        ).iloc[0]

        matched.append({
            "chart_id": chosen["chart_id"],
            "achievement": record["achievement"],
            "rank": record["rank"],
            "play_count": record["play_count"],
        })

    matched_df = pd.DataFrame(
        matched,
        columns=["chart_id", "achievement", "rank", "play_count"]
    )

    unmatched_df = pd.DataFrame(
        unmatched,
        columns=[
            "title",
            "chart_type",
            "internal_level",
            "achievement",
            "rank",
            "chart_rating",
            "play_count",
        ]
    )

    return matched_df, unmatched_df


def main():
    lines = fetch_visible_lines(PROFILE_URL)

    print(f"visible lines: {len(lines)}")
    print(f"debug lines saved: {DEBUG_LINES_PATH}")

    records = extract_rating_records(lines)

    print(f"extracted rating records: {len(records)}")

    if len(records) == 0:
        print("레이팅 대상곡 section은 찾았지만 기록을 추출하지 못했습니다.")
        return

    charts = pd.read_csv(CHARTS_PATH)

    matched_df, unmatched_df = match_chart_ids(records, charts)

    OUT_RECORDS_PATH.parent.mkdir(parents=True, exist_ok=True)

    matched_df.to_csv(OUT_RECORDS_PATH, index=False, encoding="utf-8-sig")
    unmatched_df.to_csv(OUT_UNMATCHED_PATH, index=False, encoding="utf-8-sig")

    print(f"matched records: {len(matched_df)}")
    print(f"unmatched records: {len(unmatched_df)}")
    print(f"saved: {OUT_RECORDS_PATH}")
    print(f"saved unmatched: {OUT_UNMATCHED_PATH}")

    print("\nmatched preview:")
    print(matched_df.head())

    if len(unmatched_df) > 0:
        print("\nunmatched preview:")
        print(unmatched_df.head())


if __name__ == "__main__":
    main()