import json
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW_DATA_PATH = PROJECT_ROOT / "back" / "data" / "raw" / "maimai_data.json"
OUTPUT_PATH = PROJECT_ROOT / "back" / "data" / "maimai_charts_13_15.csv"

THUMBNAIL_BASE_URL = "https://dp4p6x0xfi5o9.cloudfront.net/maimai/img/cover/"


TARGET_DIFFICULTIES = {
    "expert",
    "master",
    "remaster",
}


def normalize_text(value) -> str:
    if value is None:
        return ""

    return str(value).strip()


def normalize_chart_type(value) -> str:
    text = normalize_text(value).lower()

    if text in {"dx", "deluxe", "でらっくす"}:
        return "dx"

    if text in {"std", "standard", "スタンダード"}:
        return "std"

    return text


def normalize_difficulty(value) -> str:
    text = normalize_text(value).lower()

    difficulty_map = {
        "basic": "basic",
        "advanced": "advanced",
        "expert": "expert",
        "master": "master",
        "remaster": "remaster",
        "re:master": "remaster",
        "utage": "utage",
    }

    return difficulty_map.get(text, text)


def normalize_level_label(internal_level: float) -> str:
    """
    내부상수 기준으로 추천 시스템에서 사용할 레벨 라벨을 생성한다.

    13.0 ~ 13.5 -> 13
    13.6 ~ 13.9 -> 13+
    14.0 ~ 14.5 -> 14
    14.6 ~ 14.9 -> 14+
    15.0 이상    -> 15
    """
    if 13.0 <= internal_level <= 13.5:
        return "13"

    if 13.6 <= internal_level <= 13.9:
        return "13+"

    if 14.0 <= internal_level <= 14.5:
        return "14"

    if 14.6 <= internal_level <= 14.9:
        return "14+"

    if internal_level >= 15.0:
        return "15"

    return ""


def is_target_level(internal_level: float) -> bool:
    return 13.0 <= internal_level


def make_chart_id(song_id: str, chart_type: str, difficulty: str) -> str:
    """
    곡 ID, 채보 타입, 난이도로 chart_id를 생성한다.

    주의:
    이 값은 user record 매칭과 cohort 통계 생성에 사용되므로,
    기존 데이터와 호환성을 위해 임의로 자주 바꾸면 안 된다.
    """
    return f"{song_id}__{chart_type}__{difficulty}"


def load_raw_data() -> dict:
    if not RAW_DATA_PATH.exists():
        raise FileNotFoundError(f"Raw data not found: {RAW_DATA_PATH}")

    with open(RAW_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_chart_rows(data: dict) -> list[dict]:
    songs = data.get("songs", [])

    if not isinstance(songs, list):
        raise ValueError("Invalid maimai_data.json: 'songs' must be a list")

    rows = []

    for song in songs:
        if not isinstance(song, dict):
            continue

        song_id = normalize_text(song.get("songId")) or normalize_text(song.get("title"))
        title = normalize_text(song.get("title")) or song_id
        artist = normalize_text(song.get("artist"))
        category = normalize_text(song.get("category"))
        song_version = normalize_text(song.get("version"))
        release_date = normalize_text(song.get("releaseDate"))
        image_name = normalize_text(song.get("imageName"))
        bpm = song.get("bpm", None)
        is_new = bool(song.get("isNew", False))

        thumbnail_url = (
            f"{THUMBNAIL_BASE_URL}{image_name}"
            if image_name
            else ""
        )

        sheets = song.get("sheets", [])

        if not isinstance(sheets, list):
            continue

        for sheet in sheets:
            if not isinstance(sheet, dict):
                continue

            chart_type = normalize_chart_type(sheet.get("type"))
            difficulty = normalize_difficulty(sheet.get("difficulty"))

            if difficulty not in TARGET_DIFFICULTIES:
                continue

            internal_level_raw = sheet.get("internalLevelValue")

            if internal_level_raw is None:
                internal_level_raw = sheet.get("levelValue")

            try:
                internal_level = float(internal_level_raw)
            except Exception:
                continue

            if not is_target_level(internal_level):
                continue

            level_label = normalize_level_label(internal_level)

            if not level_label:
                continue

            sheet_version = normalize_text(sheet.get("version")) or song_version
            level = normalize_text(sheet.get("level")) or level_label
            note_designer = normalize_text(sheet.get("noteDesigner"))
            is_special = bool(sheet.get("isSpecial", False))

            note_counts = sheet.get("noteCounts") or {}

            if not isinstance(note_counts, dict):
                note_counts = {}

            chart_id = make_chart_id(
                song_id=song_id,
                chart_type=chart_type,
                difficulty=difficulty,
            )

            rows.append({
                "chart_id": chart_id,
                "song_id": song_id,
                "title": title,
                "artist": artist,
                "category": category,
                "version": song_version,
                "sheet_version": sheet_version,
                "release_date": release_date,
                "image_name": image_name,
                "thumbnail_url": thumbnail_url,
                "bpm": bpm,
                "level": level_label,
                "display_level": level,
                "internal_level": internal_level,
                "difficulty": difficulty,
                "chart_type": chart_type,
                "is_new": is_new,
                "is_special": is_special,
                "note_designer": note_designer,
                "tap_count": note_counts.get("tap"),
                "hold_count": note_counts.get("hold"),
                "slide_count": note_counts.get("slide"),
                "touch_count": note_counts.get("touch"),
                "break_count": note_counts.get("break"),
                "total_note_count": note_counts.get("total"),
            })

    return rows


def build_dataframe(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        raise ValueError("No chart rows generated")

    df = pd.DataFrame(rows)

    column_order = [
        "chart_id",
        "song_id",
        "title",
        "artist",
        "category",
        "version",
        "sheet_version",
        "release_date",
        "image_name",
        "thumbnail_url",
        "bpm",
        "level",
        "display_level",
        "internal_level",
        "difficulty",
        "chart_type",
        "is_new",
        "is_special",
        "note_designer",
        "tap_count",
        "hold_count",
        "slide_count",
        "touch_count",
        "break_count",
        "total_note_count",
    ]

    existing_columns = [col for col in column_order if col in df.columns]
    extra_columns = [col for col in df.columns if col not in existing_columns]

    df = df[existing_columns + extra_columns]

    df = df.drop_duplicates(
        subset=["chart_id"],
        keep="first",
    ).reset_index(drop=True)

    difficulty_order = {
        "expert": 0,
        "master": 1,
        "remaster": 2,
    }

    chart_type_order = {
        "std": 0,
        "dx": 1,
    }

    df["_difficulty_order"] = df["difficulty"].map(difficulty_order).fillna(99)
    df["_chart_type_order"] = df["chart_type"].map(chart_type_order).fillna(99)

    df = df.sort_values(
        [
            "internal_level",
            "_chart_type_order",
            "_difficulty_order",
            "title",
        ],
        ascending=[True, True, True, True],
    ).reset_index(drop=True)

    df = df.drop(columns=["_difficulty_order", "_chart_type_order"])

    return df


def print_summary(df: pd.DataFrame) -> None:
    print("========== MAIMAI BASE DB SUMMARY ==========")
    print(f"Output path: {OUTPUT_PATH}")
    print(f"Rows: {len(df)}")
    print()

    print("[Level distribution]")
    print(df["level"].value_counts().sort_index().to_string())
    print()

    print("[Difficulty distribution]")
    print(df["difficulty"].value_counts().sort_index().to_string())
    print()

    print("[Chart type distribution]")
    print(df["chart_type"].value_counts().sort_index().to_string())
    print()

    if "version" in df.columns:
        print("[Top 15 song versions]")
        print(df["version"].value_counts().head(15).to_string())
        print()

    if "sheet_version" in df.columns:
        print("[Top 15 sheet versions]")
        print(df["sheet_version"].value_counts().head(15).to_string())
        print()

    print("[Sample rows]")
    sample_cols = [
        "title",
        "artist",
        "version",
        "sheet_version",
        "level",
        "internal_level",
        "difficulty",
        "chart_type",
        "thumbnail_url",
    ]
    sample_cols = [col for col in sample_cols if col in df.columns]
    print(df[sample_cols].head(10).to_string(index=False))


def main() -> None:
    print("========== BUILD MAIMAI BASE DB ==========")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Raw data: {RAW_DATA_PATH}")

    data = load_raw_data()
    rows = build_chart_rows(data)
    df = build_dataframe(rows)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print_summary(df)


if __name__ == "__main__":
    main()