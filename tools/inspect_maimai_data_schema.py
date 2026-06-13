import json
from pathlib import Path
from pprint import pprint


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "back" / "data" / "raw" / "maimai_data.json"


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    print("========== INSPECT MAIMAI DATA SCHEMA ==========")
    print("Data path:", DATA_PATH)

    data = load_json(DATA_PATH)

    print("\n[1] Top-level type")
    print(type(data))

    if isinstance(data, dict):
        print("\n[2] Top-level keys")
        print(list(data.keys()))

        # 자주 쓰이는 구조 후보 자동 탐색
        if "songs" in data:
            songs = data["songs"]
        elif "data" in data:
            songs = data["data"]
        elif "charts" in data:
            songs = data["charts"]
        else:
            songs = None

    elif isinstance(data, list):
        songs = data

    else:
        songs = None

    if songs is None:
        print("\nCould not find song list automatically.")
        return

    print("\n[3] Songs type / count")
    print(type(songs), len(songs))

    if not songs:
        print("Song list is empty.")
        return

    first_song = songs[0]

    print("\n[4] First song type")
    print(type(first_song))

    print("\n[5] First song keys")
    if isinstance(first_song, dict):
        print(list(first_song.keys()))
    else:
        pprint(first_song)
        return

    print("\n[6] First song sample")
    pprint(first_song, width=120, depth=3)

    print("\n[7] Candidate fields check")
    candidate_fields = [
        "title",
        "artist",
        "version",
        "category",
        "genre",
        "image",
        "imageUrl",
        "image_url",
        "imageName",
        "image_name",
        "jacket",
        "jacketUrl",
        "jacket_url",
        "cover",
        "coverUrl",
        "cover_url",
        "bpm",
        "charts",
        "difficulties",
        "sheets",
    ]

    for field in candidate_fields:
        if field in first_song:
            print(f"- FOUND: {field} = {first_song.get(field)}")

    print("\n[8] Search first 10 songs for version/image-like keys")
    for idx, song in enumerate(songs[:10], start=1):
        if not isinstance(song, dict):
            continue

        title = song.get("title", f"song_{idx}")

        version_like = {
            k: v
            for k, v in song.items()
            if any(word in k.lower() for word in ["version", "release", "date", "from"])
        }

        image_like = {
            k: v
            for k, v in song.items()
            if any(word in k.lower() for word in ["image", "jacket", "cover", "icon"])
        }

        print(f"\n--- {idx}. {title} ---")

        print("version-like:")
        pprint(version_like, width=120)

        print("image-like:")
        pprint(image_like, width=120)


if __name__ == "__main__":
    main()