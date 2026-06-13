import argparse
import csv
import html
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "back" / "data"

PROFILE_URLS_PATH = DATA_DIR / "profile_urls.csv"
SEED_URLS_PATH = DATA_DIR / "profile_seed_urls.txt"

DEFAULT_SEED_URLS = [
    "https://maimai.shiftpsh.com/",
]

PROFILE_PATTERN = re.compile(
    r"https?://maimai\.shiftpsh\.com/profile/([A-Za-z0-9_\-]+)/?(?:home|records)?",
    re.IGNORECASE,
)

RELATIVE_PROFILE_PATTERN = re.compile(
    r"/profile/([A-Za-z0-9_\-]+)/?(?:home|records)?",
    re.IGNORECASE,
)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_profile_url(profile_id: str) -> str:
    profile_id = str(profile_id).strip().strip("/")

    return f"https://maimai.shiftpsh.com/profile/{profile_id}/home"


def extract_profile_id(url: str) -> str | None:
    if not isinstance(url, str):
        return None

    match = re.search(
        r"maimai\.shiftpsh\.com/profile/([A-Za-z0-9_\-]+)",
        url,
        flags=re.IGNORECASE,
    )

    if match:
        return match.group(1)

    match = re.search(
        r"/profile/([A-Za-z0-9_\-]+)",
        url,
        flags=re.IGNORECASE,
    )

    if match:
        return match.group(1)

    return None


def load_existing_profile_urls() -> pd.DataFrame:
    if not PROFILE_URLS_PATH.exists():
        return pd.DataFrame(
            columns=[
                "profile_id",
                "profile_url",
                "source_url",
                "first_seen_at",
                "last_seen_at",
            ]
        )

    df = pd.read_csv(PROFILE_URLS_PATH)

    if "profile_url" not in df.columns:
        if "url" in df.columns:
            df["profile_url"] = df["url"]
        else:
            df["profile_url"] = ""

    if "profile_id" not in df.columns:
        df["profile_id"] = df["profile_url"].apply(extract_profile_id)

    for col in ["source_url", "first_seen_at", "last_seen_at"]:
        if col not in df.columns:
            df[col] = ""

    df["profile_id"] = df["profile_id"].fillna("").astype(str)
    df["profile_url"] = df["profile_url"].fillna("").astype(str)

    df = df[df["profile_id"].str.len() > 0].copy()
    df["profile_url"] = df["profile_id"].apply(normalize_profile_url)

    df = df.drop_duplicates(subset=["profile_id"], keep="first").reset_index(drop=True)

    return df


def load_seed_urls_from_file() -> list[str]:
    if not SEED_URLS_PATH.exists():
        return []

    urls = []

    with open(SEED_URLS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            text = line.strip()

            if not text:
                continue

            if text.startswith("#"):
                continue

            urls.append(text)

    return urls


def normalize_seed_url(url: str) -> str:
    url = str(url).strip()

    if not url:
        return ""

    parsed = urlparse(url)

    if not parsed.scheme:
        url = "https://" + url

    return url


def is_allowed_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower() == "maimai.shiftpsh.com"
    except Exception:
        return False


def fetch_html(url: str, timeout: int) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=timeout,
    )

    response.raise_for_status()

    return response.text


def extract_profile_urls_from_html(page_url: str, body: str) -> set[str]:
    body = html.unescape(body)
    found_ids = set()

    for match in PROFILE_PATTERN.finditer(body):
        found_ids.add(match.group(1))

    for match in RELATIVE_PROFILE_PATTERN.finditer(body):
        found_ids.add(match.group(1))

    # href 안의 상대 링크를 조금 더 넓게 수집
    href_pattern = re.compile(
        r'href=["\']([^"\']*?/profile/[A-Za-z0-9_\-]+/?(?:home|records)?[^"\']*)["\']',
        re.IGNORECASE,
    )

    for match in href_pattern.finditer(body):
        href = match.group(1)
        absolute_url = urljoin(page_url, href)
        profile_id = extract_profile_id(absolute_url)

        if profile_id:
            found_ids.add(profile_id)

    return {normalize_profile_url(profile_id) for profile_id in found_ids}


def merge_profile_urls(
    existing_df: pd.DataFrame,
    discovered_urls: set[str],
    source_url_map: dict[str, str],
) -> tuple[pd.DataFrame, int]:
    now = now_text()

    existing_ids = set(existing_df["profile_id"].dropna().astype(str).tolist())

    new_rows = []

    for profile_url in sorted(discovered_urls):
        profile_id = extract_profile_id(profile_url)

        if not profile_id:
            continue

        if profile_id in existing_ids:
            continue

        new_rows.append({
            "profile_id": profile_id,
            "profile_url": normalize_profile_url(profile_id),
            "source_url": source_url_map.get(profile_url, ""),
            "first_seen_at": now,
            "last_seen_at": now,
        })

    if not new_rows:
        return existing_df, 0

    new_df = pd.DataFrame(new_rows)

    merged = pd.concat([existing_df, new_df], ignore_index=True)

    merged["profile_id"] = merged["profile_id"].fillna("").astype(str)
    merged = merged[merged["profile_id"].str.len() > 0].copy()
    merged["profile_url"] = merged["profile_id"].apply(normalize_profile_url)

    merged = merged.drop_duplicates(subset=["profile_id"], keep="first")
    merged = merged.sort_values("profile_id").reset_index(drop=True)

    return merged, len(new_rows)


def save_profile_urls(df: pd.DataFrame) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    preferred_cols = [
        "profile_id",
        "profile_url",
        "source_url",
        "first_seen_at",
        "last_seen_at",
    ]

    for col in preferred_cols:
        if col not in df.columns:
            df[col] = ""

    extra_cols = [col for col in df.columns if col not in preferred_cols]
    df = df[preferred_cols + extra_cols]

    df.to_csv(
        PROFILE_URLS_PATH,
        index=False,
        encoding="utf-8-sig",
        quoting=csv.QUOTE_MINIMAL,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect maishift profile URLs and update profile_urls.csv."
    )

    parser.add_argument(
        "--seed-url",
        action="append",
        default=[],
        help="Seed URL to scan. Can be used multiple times.",
    )

    parser.add_argument(
        "--use-existing-as-seed",
        action="store_true",
        help="Also scan existing profile URLs as seed pages.",
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=30,
        help="Maximum number of pages to fetch.",
    )

    parser.add_argument(
        "--max-new",
        type=int,
        default=300,
        help="Stop after discovering this many new profile URLs.",
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay seconds between requests.",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="HTTP timeout seconds.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write profile_urls.csv.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print("========== COLLECT PROFILE URLS ==========")
    print("Project root:", PROJECT_ROOT)
    print("Profile URL CSV:", PROFILE_URLS_PATH)
    print("Started at:", now_text())

    existing_df = load_existing_profile_urls()
    before_count = len(existing_df)

    print(f"Existing profiles: {before_count}")

    seed_urls = []

    seed_urls.extend(DEFAULT_SEED_URLS)
    seed_urls.extend(load_seed_urls_from_file())
    seed_urls.extend(args.seed_url)

    if args.use_existing_as_seed:
        seed_urls.extend(existing_df["profile_url"].dropna().astype(str).tolist())

    seed_urls = [normalize_seed_url(url) for url in seed_urls]
    seed_urls = [url for url in seed_urls if url and is_allowed_url(url)]
    seed_urls = list(dict.fromkeys(seed_urls))

    if args.max_pages > 0:
        seed_urls = seed_urls[: args.max_pages]

    print(f"Seed pages to scan: {len(seed_urls)}")

    discovered_urls = set()
    source_url_map = {}

    for idx, seed_url in enumerate(seed_urls, start=1):
        print(f"[{idx}/{len(seed_urls)}] Fetching: {seed_url}", flush=True)

        try:
            body = fetch_html(seed_url, timeout=args.timeout)
            urls = extract_profile_urls_from_html(seed_url, body)

            print(f"  - found profile URLs: {len(urls)}", flush=True)

            for profile_url in urls:
                discovered_urls.add(profile_url)
                source_url_map.setdefault(profile_url, seed_url)

            merged_preview, new_count_preview = merge_profile_urls(
                existing_df,
                discovered_urls,
                source_url_map,
            )

            print(f"  - newly discovered so far: {new_count_preview}", flush=True)

            if args.max_new > 0 and new_count_preview >= args.max_new:
                print(f"Reached max-new limit: {args.max_new}")
                break

        except Exception as e:
            print(f"  - failed: {e}", flush=True)

        if idx < len(seed_urls):
            time.sleep(args.delay)

    merged_df, new_count = merge_profile_urls(
        existing_df,
        discovered_urls,
        source_url_map,
    )

    print("\n========== RESULT ==========")
    print(f"Before: {before_count}")
    print(f"Discovered URLs on scanned pages: {len(discovered_urls)}")
    print(f"New profiles: {new_count}")
    print(f"After: {len(merged_df)}")

    if args.dry_run:
        print("dry-run mode. profile_urls.csv was not updated.")
    else:
        save_profile_urls(merged_df)
        print(f"Saved: {PROFILE_URLS_PATH}")

    print("Finished at:", now_text())


if __name__ == "__main__":
    main()