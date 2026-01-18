#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}


def col_letters_to_index(letters: str) -> int:
    idx = 0
    for ch in letters:
        if not ch.isalpha():
            break
        idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
    return idx - 1


def read_xlsx_rows(xlsx_path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(xlsx_path) as z:
        sheet_name = None
        for name in z.namelist():
            if name.startswith("xl/worksheets/sheet"):
                sheet_name = name
                break
        if sheet_name is None:
            raise ValueError("No worksheet found in xlsx.")

        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for si in root.findall("s:si", ns):
                texts = []
                for t in si.findall(".//s:t", ns):
                    texts.append(t.text or "")
                shared_strings.append("".join(texts))

        root = ET.fromstring(z.read(sheet_name))
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows = []
        for row in root.findall(".//s:sheetData/s:row", ns):
            row_values: dict[int, str] = {}
            max_idx = -1
            for cell in row.findall("s:c", ns):
                cell_ref = cell.get("r", "")
                col_letters = "".join(ch for ch in cell_ref if ch.isalpha())
                col_idx = col_letters_to_index(col_letters)
                max_idx = max(max_idx, col_idx)
                value_node = cell.find("s:v", ns)
                if value_node is None:
                    value = ""
                else:
                    if cell.get("t") == "s":
                        value = shared_strings[int(value_node.text)]
                    else:
                        value = value_node.text or ""
                row_values[col_idx] = value
            rows.append((row_values, max_idx))

    if not rows:
        return []

    header_values, header_max = rows[0]
    header = [""] * (header_max + 1)
    for idx, value in header_values.items():
        header[idx] = value

    result: list[dict[str, str]] = []
    for row_values, max_idx in rows[1:]:
        row_list = [""] * (max(header_max, max_idx) + 1)
        for idx, value in row_values.items():
            row_list[idx] = value
        row_dict = {}
        for idx, name in enumerate(header):
            if name:
                row_dict[name] = row_list[idx] if idx < len(row_list) else ""
        result.append(row_dict)
    return result


def build_filename_index(root_dir: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            path = Path(dirpath) / filename
            index.setdefault(filename, []).append(path)
    return index


def normalize_filename(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    cleaned = []
    last_was_sep = False
    for ch in normalized:
        if ch.isalnum():
            cleaned.append(ch)
            last_was_sep = False
        else:
            if not last_was_sep:
                cleaned.append("_")
                last_was_sep = True
    return "".join(cleaned).strip("_")


def normalize_id(value: str) -> str:
    value = value.strip()
    if value.endswith(".0"):
        value = value[:-2]
    return value


def ensure_unique_path(dest: Path, suffix: str) -> Path:
    if not dest.exists():
        return dest
    stem = dest.stem
    ext = dest.suffix
    candidate = dest.with_name(f"{stem}_{suffix}{ext}")
    counter = 2
    while candidate.exists():
        candidate = dest.with_name(f"{stem}_{suffix}_{counter}{ext}")
        counter += 1
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize Navan assets by filename.")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path("/Users/amineka/Downloads/Navan_Content"),
        help="Base directory containing Assets and Scenes.xlsx and Assets/.",
    )
    parser.add_argument(
        "--xlsx",
        type=Path,
        default=None,
        help="Path to Assets and Scenes.xlsx.",
    )
    parser.add_argument(
        "--assets-dir",
        type=Path,
        default=None,
        help="Path to Assets directory.",
    )
    parser.add_argument(
        "--transcripts-dir",
        type=Path,
        default=None,
        help="Path to transcripts directory.",
    )
    parser.add_argument(
        "--videos-out",
        type=Path,
        default=None,
        help="Output directory for normalized videos.",
    )
    parser.add_argument(
        "--transcripts-out",
        type=Path,
        default=None,
        help="Output directory for normalized transcripts.",
    )
    parser.add_argument(
        "--report-missing",
        action="store_true",
        help="Print lists of missing videos/transcripts.",
    )
    args = parser.parse_args()

    base_dir = args.base_dir
    xlsx_path = args.xlsx or base_dir / "Assets and Scenes.xlsx"
    assets_dir = args.assets_dir or base_dir / "Assets"
    transcripts_dir = args.transcripts_dir or assets_dir / "transcripts"
    videos_out = args.videos_out or base_dir / "normalized_videos"
    transcripts_out = args.transcripts_out or base_dir / "normalized_transcripts"

    rows = read_xlsx_rows(xlsx_path)
    filename_index = build_filename_index(assets_dir)

    videos_out.mkdir(parents=True, exist_ok=True)
    transcripts_out.mkdir(parents=True, exist_ok=True)

    total_videos = 0
    copied_videos = 0
    missing_videos = 0
    copied_transcripts = 0
    missing_transcripts = 0
    missing_video_names: list[str] = []
    missing_transcript_names: list[str] = []
    ambiguous_video_names: list[str] = []

    normalized_index: dict[str, list[Path]] = {}
    for name, paths in filename_index.items():
        normalized_index.setdefault(normalize_filename(name), []).extend(paths)

    for row in rows:
        filename = row.get("filename", "").strip()
        asset_type = row.get("asset_type", "").strip().lower()
        if not filename:
            continue
        ext = Path(filename).suffix.lower()
        is_video = asset_type == "video" or ext in VIDEO_EXTS
        if not is_video:
            continue

        total_videos += 1
        source_candidates = filename_index.get(filename, [])
        if not source_candidates:
            normalized_key = normalize_filename(filename)
            source_candidates = normalized_index.get(normalized_key, [])
        if not source_candidates:
            missing_videos += 1
            missing_video_names.append(filename)
            continue
        if len(source_candidates) > 1:
            ambiguous_video_names.append(filename)

        source_path = source_candidates[0]
        dest_path = ensure_unique_path(videos_out / filename, normalize_id(row.get("id", "")))
        shutil.copy2(source_path, dest_path)
        copied_videos += 1

        asset_id = normalize_id(row.get("id", ""))
        if asset_id:
            transcript_candidates = [
                transcripts_dir / f"{asset_id}_transcript.json",
                transcripts_dir / f"{asset_id}.json",
            ]
            transcript_path = next((p for p in transcript_candidates if p.exists()), None)
            if transcript_path is None:
                missing_transcripts += 1
                missing_transcript_names.append(filename)
            else:
                transcript_name = Path(filename).stem + ".json"
                transcript_dest = ensure_unique_path(
                    transcripts_out / transcript_name, normalize_id(row.get("id", ""))
                )
                shutil.copy2(transcript_path, transcript_dest)
                copied_transcripts += 1

    print("Done.")
    print(f"Videos listed: {total_videos}")
    print(f"Videos copied: {copied_videos}")
    print(f"Videos missing: {missing_videos}")
    print(f"Transcripts copied: {copied_transcripts}")
    print(f"Transcripts missing: {missing_transcripts}")
    print(f"Videos output: {videos_out}")
    print(f"Transcripts output: {transcripts_out}")
    if args.report_missing:
        if missing_video_names:
            print("Missing videos:")
            for name in missing_video_names:
                print(f"- {name}")
        if missing_transcript_names:
            print("Missing transcripts:")
            for name in missing_transcript_names:
                print(f"- {name}")
        if ambiguous_video_names:
            print("Ambiguous video matches (picked first):")
            for name in ambiguous_video_names:
                print(f"- {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
