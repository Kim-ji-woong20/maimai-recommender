import json
import csv
from pathlib import Path

RAW_PATH = Path("back/data/raw/maimai_data.json")
OUT_PATH = Path("back/data/maimai_charts_13_15.csv")


def display_level_from_internal(value: float) -> str | None:
    if 13.0 <= value <= 13.5:
        return "13"
    if 13.6 <= value <= 13.9:
        return "13+"
    if 14.0 <= value <= 14.5:
        return "14"
    if 14.6 <= value <= 14.9:
        return "14+"
    if value >= 15.0:
        return "15"
    return None


def main():
    with open(RAW_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []

    for song in data["songs"]:
        song_id = song.get("songId")
        title = song.get("title")
        artist = song.get("artist")
        bpm = song.get("bpm")
        category = song.get("category")
        song_version = song.get("version")
        is_new = song.get("isNew")

        for sheet in song.get("sheets", []):
            internal_level = sheet.get("internalLevelValue")

            if internal_level is None:
                continue

            try:
                internal_level = float(internal_level)
            except ValueError:
                continue

            display_level = display_level_from_internal(internal_level)

            if display_level is None:
                continue

            difficulty = sheet.get("difficulty")
            chart_type = sheet.get("type")
            chart_version = sheet.get("version")
            note_designer = sheet.get("noteDesigner")
            note_counts = sheet.get("noteCounts") or {}

            chart_id = f"{song_id}__{chart_type}__{difficulty}"

            rows.append({
                "chart_id": chart_id,
                "song_id": song_id,
                "title": title,
                "artist": artist,
                "difficulty": difficulty,
                "level": display_level,
                "internal_level": internal_level,
                "chart_type": chart_type,
                "bpm": bpm,
                "category": category,
                "song_version": song_version,
                "chart_version": chart_version,
                "is_new": is_new,
                "note_designer": note_designer,
                "notes_total": note_counts.get("total"),
                "notes_tap": note_counts.get("tap"),
                "notes_hold": note_counts.get("hold"),
                "notes_slide": note_counts.get("slide"),
                "notes_touch": note_counts.get("touch"),
                "notes_break": note_counts.get("break"),
            })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "chart_id",
        "song_id",
        "title",
        "artist",
        "difficulty",
        "level",
        "internal_level",
        "chart_type",
        "bpm",
        "category",
        "song_version",
        "chart_version",
        "is_new",
        "note_designer",
        "notes_total",
        "notes_tap",
        "notes_hold",
        "notes_slide",
        "notes_touch",
        "notes_break",
    ]

    with open(OUT_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"saved: {OUT_PATH}")
    print(f"rows: {len(rows)}")


if __name__ == "__main__":
    main()