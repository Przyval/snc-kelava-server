"""
Staff Photo Processor
=====================
Matches photos from 'Foto Karyawan/' to p_user IDs and creates
resized thumbnails in static/img/staff/<user_id>.jpg
"""

import os
import re
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("pip install Pillow first")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
FOTO_DIR = PROJECT_ROOT / "Foto Karyawan"
STATIC_DIR = (
    PROJECT_ROOT
    / "kil"
    / "backend"
    / "legacy"
    / "web"
    / "enterprise"
    / "static"
    / "img"
    / "staff"
)

THUMB_SIZE = (200, 200)


def normalize(name: str) -> str:
    """Normalize a name for fuzzy matching."""
    name = name.lower().strip()
    name = re.sub(r"\s*\(\d+\)\s*", "", name)  # remove (2) etc
    name = re.sub(r"[^a-z\s]", "", name)  # remove non-alpha
    name = re.sub(r"\s+", " ", name).strip()
    return name


def match_photo_to_user(photo_name: str, users: list[dict]) -> dict | None:
    """Find the best matching user for a photo filename."""
    stem = Path(photo_name).stem
    norm_photo = normalize(stem)

    best_match = None
    best_score = 0

    for user in users:
        norm_user = normalize(user["fullname"])

        # Exact match
        if norm_photo == norm_user:
            return user

        # Check if all words in photo name are in user name
        photo_words = set(norm_photo.split())
        user_words = set(norm_user.split())
        common = photo_words & user_words

        if len(common) >= 2:
            score = len(common) / max(len(photo_words), len(user_words))
            if score > best_score:
                best_score = score
                best_match = user

    if best_score >= 0.5:
        return best_match
    return None


def resize_photo(src: Path, dst: Path):
    """Resize photo to thumbnail, center-crop to square."""
    img = Image.open(src)
    img = img.convert("RGB")

    # Center crop to square
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))

    img = img.resize(THUMB_SIZE, Image.LANCZOS)
    img.save(dst, "JPEG", quality=85)


def main():
    # Get users from DB
    sys.path.insert(0, str(PROJECT_ROOT))
    from kil.db.kelava_db import execute_kelava_query

    users = execute_kelava_query("SELECT id, fullname FROM p_user ORDER BY fullname")
    print(f"Found {len(users)} users in database")

    if not FOTO_DIR.exists():
        print(f"Photo directory not found: {FOTO_DIR}")
        return

    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    photos = list(FOTO_DIR.glob("*.jpg")) + list(FOTO_DIR.glob("*.jpeg")) + list(FOTO_DIR.glob("*.png"))
    print(f"Found {len(photos)} photos in {FOTO_DIR}")

    matched = 0
    unmatched = []

    for photo in sorted(photos):
        user = match_photo_to_user(photo.name, users)
        if user:
            dst = STATIC_DIR / f"{user['id']}.jpg"
            resize_photo(photo, dst)
            size_kb = dst.stat().st_size / 1024
            print(f"  {photo.name} -> {user['id']}.jpg ({user['fullname']}) [{size_kb:.0f}KB]")
            matched += 1
        else:
            unmatched.append(photo.name)

    print(f"\nMatched: {matched}/{len(photos)}")
    if unmatched:
        print(f"Unmatched ({len(unmatched)}):")
        for name in unmatched:
            print(f"  - {name}")

    # Show total thumbnails
    total = len(list(STATIC_DIR.glob("*.jpg")))
    print(f"\nTotal thumbnails in static/img/staff/: {total}")


if __name__ == "__main__":
    main()
