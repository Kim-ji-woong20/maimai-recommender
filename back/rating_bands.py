from __future__ import annotations

from typing import Any


CUSTOM_RATING_BANDS = [
    (14500, 14999, "14500-14999"),
    (15000, 15199, "15000-15199"),
    (15200, 15499, "15200-15499"),
    (15500, 15799, "15500-15799"),
    (15800, 15999, "15800-15999"),
    (16000, 16199, "16000-16199"),
    (16200, 16499, "16200-16499"),
    (16500, 99999, "16500+"),
]


def rating_to_band(rating: int | float | None) -> str:
    """
    maimai 레이팅을 추천용 실력 구간으로 변환한다.

    14500 미만은 기존처럼 500점 단위로 처리하고,
    14500 이상은 Best50 바닥 상수 해석을 반영한 custom band를 사용한다.
    """
    if rating is None:
        return "unknown"

    try:
        value = int(float(rating))
    except Exception:
        return "unknown"

    if value < 14500:
        low = int(value // 500) * 500
        high = low + 499
        return f"{low}-{high}"

    for low, high, label in CUSTOM_RATING_BANDS:
        if low <= value <= high:
            return label

    return "16500+"


def parse_rating_band_low(band: str) -> int | None:
    """
    rating band의 lower bound를 정렬용 숫자로 변환한다.

    예:
    - 16000-16199 -> 16000
    - 16500+ -> 16500
    - unknown -> None
    """
    try:
        text = str(band).strip()

        if not text or text == "unknown":
            return None

        if text.endswith("+"):
            return int(text[:-1])

        return int(text.split("-", 1)[0])

    except Exception:
        return None


def get_ordered_bands(bands: list[str]) -> list[str]:
    parsed = []

    for band in bands:
        low = parse_rating_band_low(band)

        if low is None:
            continue

        parsed.append((low, str(band)))

    parsed = sorted(
        parsed,
        key=lambda item: item[0],
    )

    return [band for _, band in parsed]


def get_target_band(
    current_band: str,
    available_bands: list[str],
) -> str:
    """
    현재 band보다 한 단계 높은 사용 가능 band를 target으로 고른다.

    예:
    current=16000-16199
    available에 16200-16499가 있으면 target=16200-16499
    """
    ordered_bands = get_ordered_bands(available_bands)
    current_low = parse_rating_band_low(current_band)

    if current_low is None:
        return current_band

    for band in ordered_bands:
        low = parse_rating_band_low(band)

        if low is not None and low > current_low:
            return band

    return current_band


def get_neighbor_bands(
    center_band: str,
    available_bands: list[str],
    lower_steps: int = 1,
    upper_steps: int = 1,
) -> list[str]:
    """
    중심 band 주변의 인접 band를 반환한다.

    current band용:
    lower_steps=1, upper_steps=1

    target band용:
    lower_steps=0, upper_steps=2
    """
    ordered_bands = get_ordered_bands(available_bands)

    if not ordered_bands:
        return [center_band] if center_band else []

    if center_band in ordered_bands:
        center_index = ordered_bands.index(center_band)
    else:
        center_low = parse_rating_band_low(center_band)

        if center_low is None:
            return ordered_bands[:1]

        distances = []

        for index, band in enumerate(ordered_bands):
            low = parse_rating_band_low(band)

            if low is None:
                continue

            distances.append((abs(low - center_low), index))

        if not distances:
            return [center_band] if center_band else []

        _, center_index = min(distances, key=lambda item: item[0])

    start = max(0, center_index - lower_steps)
    end = min(len(ordered_bands), center_index + upper_steps + 1)

    return ordered_bands[start:end]


def normalize_band_list(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        return [value]

    try:
        return [str(item) for item in value if str(item).strip()]
    except Exception:
        return []