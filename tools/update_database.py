import argparse
import csv
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / "tools"
DATA_DIR = PROJECT_ROOT / "back" / "data"

PROFILE_URLS_PATH = DATA_DIR / "profile_urls.csv"
RAW_BEST50_PATH = DATA_DIR / "raw_user_best50.csv"
COHORT_STATS_PATH = DATA_DIR / "cohort_chart_stats.csv"
LEVEL_STATS_PATH = DATA_DIR / "level_distribution_stats.csv"
UPDATE_LOG_PATH = DATA_DIR / "update_log.csv"

COLLECT_URLS_SCRIPT = TOOLS_DIR / "collect_profile_urls.py"
COLLECT_PROFILES_SCRIPT = TOOLS_DIR / "collect_maishift_profiles.py"
BUILD_SCRIPT = TOOLS_DIR / "build_cohort_stats.py"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def format_elapsed(seconds: float) -> str:
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours > 0:
        return f"{hours}h {minutes}m {sec}s"

    if minutes > 0:
        return f"{minutes}m {sec}s"

    return f"{sec}s"


def print_section(title: str) -> None:
    print("\n" + "=" * 70, flush=True)
    print(title, flush=True)
    print("=" * 70, flush=True)


def run_script_realtime(
    script_path: Path,
    label: str,
    extra_args: list[str] | None = None,
) -> tuple[bool, str, float]:
    """
    하위 Python 스크립트를 실행하고 stdout/stderr를 실시간으로 출력한다.
    """
    if not script_path.exists():
        message = f"{label} script not found: {script_path}"
        print(f"[{now_text()}] FAIL: {message}", flush=True)
        return False, message, 0.0

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    command = [
        sys.executable,
        "-u",
        str(script_path),
    ]

    if extra_args:
        command.extend(extra_args)

    print_section(f"[{now_text()}] START: {label}")
    print("Command:", " ".join(command), flush=True)
    print("Working directory:", PROJECT_ROOT, flush=True)

    start_time = time.time()
    process = None

    try:
        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        assert process.stdout is not None

        for line in process.stdout:
            print(line, end="", flush=True)

        return_code = process.wait()
        elapsed = time.time() - start_time

        if return_code != 0:
            message = (
                f"{label} failed with return code {return_code} "
                f"after {format_elapsed(elapsed)}"
            )
            print(f"\n[{now_text()}] FAIL: {message}", flush=True)
            return False, message, elapsed

        message = f"{label} completed in {format_elapsed(elapsed)}"
        print(f"\n[{now_text()}] DONE: {message}", flush=True)
        return True, message, elapsed

    except KeyboardInterrupt:
        elapsed = time.time() - start_time

        if process is not None:
            try:
                process.terminate()
            except Exception:
                pass

        message = f"{label} interrupted by user after {format_elapsed(elapsed)}"
        print(f"\n[{now_text()}] INTERRUPTED: {message}", flush=True)
        return False, message, elapsed

    except Exception as e:
        elapsed = time.time() - start_time
        message = f"{label} crashed after {format_elapsed(elapsed)}: {e}"
        print(f"\n[{now_text()}] ERROR: {message}", flush=True)
        return False, message, elapsed


def file_status(path: Path) -> dict:
    if not path.exists():
        return {
            "path": str(path.relative_to(PROJECT_ROOT)),
            "exists": False,
            "size_bytes": 0,
            "rows": None,
        }

    rows = None

    try:
        if path.suffix.lower() == ".csv":
            rows = len(pd.read_csv(path))
    except Exception:
        rows = None

    return {
        "path": str(path.relative_to(PROJECT_ROOT)),
        "exists": True,
        "size_bytes": path.stat().st_size,
        "rows": rows,
    }


def print_file_statuses() -> None:
    print_section("DATA FILE STATUS")

    paths = [
        PROFILE_URLS_PATH,
        RAW_BEST50_PATH,
        COHORT_STATS_PATH,
        LEVEL_STATS_PATH,
    ]

    for path in paths:
        status = file_status(path)

        print(
            f"- {status['path']}: "
            f"exists={status['exists']}, "
            f"rows={status['rows']}, "
            f"size={status['size_bytes']} bytes",
            flush=True,
        )


def print_profile_url_summary() -> None:
    if not PROFILE_URLS_PATH.exists():
        print("\nprofile_urls.csv not found.", flush=True)
        return

    try:
        df = pd.read_csv(PROFILE_URLS_PATH)

        print_section("PROFILE URL SUMMARY")
        print(f"Total profile URL rows: {len(df)}", flush=True)

        if "profile_id" in df.columns:
            print(f"Unique profile_id: {df['profile_id'].dropna().nunique()}", flush=True)

        for col in ["profile_url", "url"]:
            if col in df.columns:
                print(f"Unique URLs in '{col}': {df[col].dropna().nunique()}", flush=True)

        if "rating_band" in df.columns:
            print("\nProfile URL rating_band distribution:", flush=True)
            print(df["rating_band"].value_counts().sort_index().to_string(), flush=True)

        if "first_seen_at" in df.columns:
            print("\nFirst seen latest values:", flush=True)
            print(
                df["first_seen_at"]
                .dropna()
                .astype(str)
                .sort_values(ascending=False)
                .head(5)
                .to_string(index=False),
                flush=True,
            )

    except Exception as e:
        print(f"\nFailed to summarize profile_urls.csv: {e}", flush=True)


def print_raw_best50_summary() -> None:
    if not RAW_BEST50_PATH.exists():
        print("\nraw_user_best50.csv not found.", flush=True)
        return

    try:
        df = pd.read_csv(RAW_BEST50_PATH)

        print_section("RAW USER BEST50 SUMMARY")
        print(f"Total rows: {len(df)}", flush=True)

        for col in ["profile_id", "user_id", "profile_url"]:
            if col in df.columns:
                print(f"Unique {col}: {df[col].dropna().nunique()}", flush=True)

        if "rating_band" in df.columns:
            print("\nrating_band distribution:", flush=True)
            print(df["rating_band"].value_counts().sort_index().to_string(), flush=True)

        if "level" in df.columns:
            print("\nlevel distribution:", flush=True)
            print(df["level"].value_counts().sort_index().to_string(), flush=True)

    except Exception as e:
        print(f"\nFailed to summarize raw_user_best50.csv: {e}", flush=True)


def print_cohort_summary() -> None:
    if not COHORT_STATS_PATH.exists():
        print("\ncohort_chart_stats.csv not found.", flush=True)
        return

    try:
        df = pd.read_csv(COHORT_STATS_PATH)

        print_section("COHORT STATS SUMMARY")
        print(f"Total rows: {len(df)}", flush=True)

        if "rating_band" in df.columns:
            print("\nrating_band distribution in cohort stats:", flush=True)
            print(df["rating_band"].value_counts().sort_index().to_string(), flush=True)

        if "chart_id" in df.columns:
            print(f"\nUnique chart_id count: {df['chart_id'].dropna().nunique()}", flush=True)

    except Exception as e:
        print(f"\nFailed to summarize cohort_chart_stats.csv: {e}", flush=True)


def append_update_log(
    started_at: str,
    finished_at: str,
    url_collect_ok: bool | None,
    collect_ok: bool | None,
    build_ok: bool | None,
    url_collect_elapsed: float | None,
    collect_elapsed: float | None,
    build_elapsed: float | None,
    note: str,
) -> None:
    UPDATE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "started_at",
        "finished_at",
        "url_collect_ok",
        "collect_ok",
        "build_ok",
        "url_collect_elapsed_seconds",
        "collect_elapsed_seconds",
        "build_elapsed_seconds",
        "note",
    ]

    file_exists = UPDATE_LOG_PATH.exists()

    with open(UPDATE_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        writer.writerow({
            "started_at": started_at,
            "finished_at": finished_at,
            "url_collect_ok": url_collect_ok,
            "collect_ok": collect_ok,
            "build_ok": build_ok,
            "url_collect_elapsed_seconds": round(url_collect_elapsed, 2)
            if url_collect_elapsed is not None
            else "",
            "collect_elapsed_seconds": round(collect_elapsed, 2)
            if collect_elapsed is not None
            else "",
            "build_elapsed_seconds": round(build_elapsed, 2)
            if build_elapsed is not None
            else "",
            "note": note,
        })


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update maimai recommender data pipeline."
    )

    parser.add_argument(
        "--skip-url-collect",
        action="store_true",
        help="Skip collect_profile_urls.py.",
    )

    parser.add_argument(
        "--skip-collect",
        action="store_true",
        help="Skip collect_maishift_profiles.py and only build cohort stats.",
    )

    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip build_cohort_stats.py.",
    )

    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Only print current data summaries without running scripts.",
    )

    parser.add_argument(
        "--url-dry-run",
        action="store_true",
        help="Run collect_profile_urls.py in dry-run mode.",
    )

    parser.add_argument(
        "--no-before-summary",
        action="store_true",
        help="Do not print data summaries before running scripts.",
    )

    parser.add_argument(
        "--no-after-summary",
        action="store_true",
        help="Do not print data summaries after running scripts.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    started_at = now_text()

    url_collect_ok = None
    collect_ok = None
    build_ok = None

    url_collect_elapsed = None
    collect_elapsed = None
    build_elapsed = None

    notes = []

    print_section("MAIMAI RECOMMENDER DB UPDATE")
    print("Project root:", PROJECT_ROOT, flush=True)
    print("Python:", sys.executable, flush=True)
    print("Started at:", started_at, flush=True)

    if not args.no_before_summary:
        print_file_statuses()
        print_profile_url_summary()
        print_raw_best50_summary()
        print_cohort_summary()

    if args.summary_only:
        print("\nsummary-only mode. No scripts executed.", flush=True)
        return

    pipeline_start = time.time()

    if not args.skip_url_collect:
        url_args = []

        if args.url_dry_run:
            url_args.append("--dry-run")

        url_collect_ok, url_collect_msg, url_collect_elapsed = run_script_realtime(
            COLLECT_URLS_SCRIPT,
            "collect_profile_urls.py",
            extra_args=url_args,
        )
        notes.append(url_collect_msg)
    else:
        print_section("SKIP: collect_profile_urls.py")
        url_collect_ok = None
        url_collect_elapsed = None
        notes.append("url collect skipped")

    if not args.skip_collect:
        collect_ok, collect_msg, collect_elapsed = run_script_realtime(
            COLLECT_PROFILES_SCRIPT,
            "collect_maishift_profiles.py",
        )
        notes.append(collect_msg)
    else:
        print_section("SKIP: collect_maishift_profiles.py")
        collect_ok = None
        collect_elapsed = None
        notes.append("profile collect skipped")

    if not args.skip_build:
        build_ok, build_msg, build_elapsed = run_script_realtime(
            BUILD_SCRIPT,
            "build_cohort_stats.py",
        )
        notes.append(build_msg)
    else:
        print_section("SKIP: build_cohort_stats.py")
        build_ok = None
        build_elapsed = None
        notes.append("build skipped")

    if not args.no_after_summary:
        print_file_statuses()
        print_profile_url_summary()
        print_raw_best50_summary()
        print_cohort_summary()

    finished_at = now_text()
    total_elapsed = time.time() - pipeline_start

    append_update_log(
        started_at=started_at,
        finished_at=finished_at,
        url_collect_ok=url_collect_ok,
        collect_ok=collect_ok,
        build_ok=build_ok,
        url_collect_elapsed=url_collect_elapsed,
        collect_elapsed=collect_elapsed,
        build_elapsed=build_elapsed,
        note=" | ".join(notes),
    )

    print_section("UPDATE FINISHED")
    print("Finished at:", finished_at, flush=True)
    print("Total elapsed:", format_elapsed(total_elapsed), flush=True)
    print("Log path:", UPDATE_LOG_PATH, flush=True)


if __name__ == "__main__":
    main()