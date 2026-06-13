import json
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "back" / "data" / "raw" / "maimai_data.json"


BASE_URL_CANDIDATES = [
    "https://dp4p6x0xfi5o9.cloudfront.net/maimai/img/cover/",
    "https://dp4p6x0xfi5o9.cloudfront.net/maimai/img/jacket/",
    "https://dp4p6x0xfi5o9.cloudfront.net/maimai/img/",
    "https://dp4p6x0xfi5o9.cloudfront.net/maimai/images/",
    "https://dp4p6x0xfi5o9.cloudfront.net/maimai/cover/",
    "https://dp4p6x0xfi5o9.cloudfront.net/maimai/jacket/",
]


def main() -> None:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    songs = data["songs"]
    image_name = songs[0]["imageName"]

    print("Sample title:", songs[0]["title"])
    print("Sample imageName:", image_name)
    print()

    for base_url in BASE_URL_CANDIDATES:
        url = base_url + image_name

        try:
            response = requests.head(url, timeout=10, allow_redirects=True)

            print(url)
            print("  status:", response.status_code)
            print("  content-type:", response.headers.get("content-type"))
            print("  content-length:", response.headers.get("content-length"))

            if response.status_code == 200:
                print("  FOUND:", url)

        except Exception as e:
            print(url)
            print("  failed:", e)


if __name__ == "__main__":
    main()