import argparse
import csv
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://maimai.shiftpsh.com/"
HOME_URL = "https://maimai.shiftpsh.com/"

OUT_PATH = Path("back/data/profile_urls.csv")
DEBUG_LINKS_PATH = Path("back/data/maishift_main_debug_links.txt")

TARGET_BANDS = [
    (14500, 14999),
    (15000, 15499),
    (15500, 15999),
    (16000, 16499),
]


def normalize_line(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text))
    text = text.replace("\u200b", "")
    return text.strip()


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


def normalize_profile_url(href: str) -> str | None:
    """
    입력 예:
    /profile/nath
    /profile/nath/home
    https://maimai.shiftpsh.com/profile/nath
    https://maimai.shiftpsh.com/profile/nath/home

    출력:
    https://maimai.shiftpsh.com/profile/nath/home
    """
    if not href:
        return None

    if "/profile/" not in href:
        return None

    full_url = urljoin(BASE_URL, href)
    full_url = full_url.split("?")[0].split("#")[0].rstrip("/")

    match = re.search(r"https://maimai\.shiftpsh\.com/profile/([^/]+)(?:/home)?$", full_url)

    if not match:
        return None

    profile_id = match.group(1)

    return f"https://maimai.shiftpsh.com/profile/{profile_id}/home"


def extract_profile_links_from_home() -> list[str]:
    html = fetch_html(HOME_URL)
    soup = BeautifulSoup(html, "html.parser")

    urls = set()
    debug_links = []

    # 핵심 수정:
    # <a href="...">뿐 아니라 <button href="...">도 잡기 위해 href 속성이 있는 모든 태그를 탐색
    for tag in soup.find_all(attrs={"href": True}):
        href = tag.get("href")
        text = normalize_line(tag.get_text(" ", strip=True))
        tag_name = tag.name

        debug_links.append((tag_name, href, text))

        profile_url = normalize_profile_url(href)

        if profile_url:
            urls.add(profile_url)

    DEBUG_LINKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DEBUG_LINKS_PATH, "w", encoding="utf-8") as f:
        for tag_name, href, text in debug_links:
            f.write(f"{tag_name}\t{href}\t{text}\n")

    return sorted(urls)


def extract_profile_id(profile_url: str) -> str:
    match = re.search(r"/profile/([^/]+)/home", profile_url)

    if not match:
        return ""

    return match.group(1)


def parse_rating_from_profile(profile_url: str) -> int | None:
    """
    한국어 UI 기준 예:
    14 '1'
    15 '5'
    16 '4'
    17 '3'
    18 '2'
    19 '플레이 카운트'

    즉, '플레이 카운트' 직전의 연속된 한 자리 숫자를 이어붙이면 rating이 된다.
    """
    html = fetch_html(profile_url)
    lines = html_to_visible_lines(html)

    play_count_markers = {"플레이 카운트", "Play Count"}

    marker_idx = None

    for i, line in enumerate(lines):
        if line in play_count_markers:
            marker_idx = i
            break

    if marker_idx is None:
        return None

    digits = []
    i = marker_idx - 1

    while i >= 0 and len(digits) < 6:
        line = lines[i]

        if re.fullmatch(r"\d", line):
            digits.append(line)
            i -= 1
            continue

        # rating이 15,432처럼 한 줄로 들어오는 경우 대비
        if re.fullmatch(r"\d{1,2},?\d{3}", line):
            return int(line.replace(",", ""))

        break

    digits.reverse()

    if not digits:
        return None

    rating_text = "".join(digits)

    if not re.fullmatch(r"\d{4,5}", rating_text):
        return None

    return int(rating_text)


def rating_to_band(rating: int) -> str:
    for low, high in TARGET_BANDS:
        if low <= rating <= high:
            return f"{low}-{high}"

    return "out_of_target"


def load_existing_urls() -> set[str]:
    if not OUT_PATH.exists():
        return set()

    existing = set()

    with open(OUT_PATH, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            url = row.get("profile_url")
            if url:
                existing.add(url)

    return existing


def append_profile(row: dict):
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    file_exists = OUT_PATH.exists()

    fieldnames = [
        "profile_id",
        "profile_url",
        "rating",
        "rating_band",
        "collected_at",
    ]

    with open(OUT_PATH, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        writer.writerow(row)


def collect_once(request_delay: float = 2.0):
    existing_urls = load_existing_urls()

    profile_urls = extract_profile_links_from_home()

    print(f"found profile links on home: {len(profile_urls)}")

    if len(profile_urls) == 0:
        print(f"프로필 링크를 찾지 못했습니다. 디버그 파일 확인: {DEBUG_LINKS_PATH}")
        return

    new_count = 0
    skipped_count = 0
    out_of_target_count = 0
    failed_count = 0

    for url in profile_urls:
        if url in existing_urls:
            skipped_count += 1
            continue

        profile_id = extract_profile_id(url)

        try:
            rating = parse_rating_from_profile(url)
            time.sleep(request_delay)

            if rating is None:
                failed_count += 1
                print(f"[skip] rating parse failed: {url}")
                continue

            band = rating_to_band(rating)

            if band == "out_of_target":
                out_of_target_count += 1
                print(f"[skip] {profile_id} rating={rating} band={band}")
                continue

            row = {
                "profile_id": profile_id,
                "profile_url": url,
                "rating": rating,
                "rating_band": band,
                "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

            append_profile(row)
            existing_urls.add(url)
            new_count += 1

            print(f"[saved] {profile_id} rating={rating} band={band}")

        except Exception as e:
            failed_count += 1
            print(f"[error] {url} -> {e}")

    print(f"new saved: {new_count}")
    print(f"skipped existing: {skipped_count}")
    print(f"out of target: {out_of_target_count}")
    print(f"failed: {failed_count}")
    print(f"output: {OUT_PATH}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--request-delay", type=float, default=2.0)

    args = parser.parse_args()

    for round_idx in range(1, args.rounds + 1):
        print(f"\n=== collect round {round_idx}/{args.rounds} ===")
        collect_once(request_delay=args.request_delay)

        if round_idx < args.rounds:
            print(f"sleep {args.interval} seconds...")
            time.sleep(args.interval)


if __name__ == "__main__":
    main()