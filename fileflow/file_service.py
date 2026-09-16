"""File validation, categorization, hashing, and safe path helpers."""

import hashlib
import mimetypes
import os
import re
import shutil
import uuid
from pathlib import Path

from werkzeug.utils import secure_filename


CATEGORIES = {
    "Images": {"jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "tiff"},
    "Documents": {"pdf", "doc", "docx", "txt", "rtf", "odt", "md"},
    "Spreadsheets": {"csv", "xls", "xlsx", "ods"},
    "Presentations": {"ppt", "pptx", "odp"},
    "Videos": {"mp4", "mkv", "avi", "mov", "webm", "mpeg"},
    "Audio": {"mp3", "wav", "flac", "aac", "ogg", "m4a"},
    "Archives": {"zip", "rar", "7z", "tar", "gz", "bz2"},
}
ALL_CATEGORIES = (*CATEGORIES.keys(), "Others", "Duplicates")
BLOCKED_EXTENSIONS = {
    "exe", "dll", "com", "bat", "cmd", "ps1", "sh", "msi", "scr", "jar", "php", "py",
}


class FileValidationError(ValueError):
    pass


def category_for(filename):
    extension = Path(filename).suffix.lower().lstrip(".")
    for category, extensions in CATEGORIES.items():
        if extension in extensions:
            return category
    return "Others"


def validate_filename(filename):
    if not filename or not filename.strip():
        raise FileValidationError("A file must have a name.")
    safe = secure_filename(filename)
    if not safe:
        raise FileValidationError("The filename contains no usable characters.")
    extension = Path(safe).suffix.lower().lstrip(".")
    if extension in BLOCKED_EXTENSIONS:
        raise FileValidationError(f".{extension} files are not allowed.")
    return safe


def unique_name(filename):
    safe = validate_filename(filename)
    stem = Path(safe).stem[:80] or "file"
    suffix = Path(safe).suffix.lower()[:16]
    return f"{stem}-{uuid.uuid4().hex[:10]}{suffix}"


def confined_path(root, *parts):
    """Return a resolved path only when it remains below root."""
    root_path = Path(root).resolve()
    candidate = root_path.joinpath(*parts).resolve()
    if candidate != root_path and root_path not in candidate.parents:
        raise FileValidationError("Unsafe storage path rejected.")
    return candidate


def save_upload(upload, storage_root):
    original = validate_filename(upload.filename)
    incoming = confined_path(storage_root, "incoming")
    incoming.mkdir(parents=True, exist_ok=True)
    stored = unique_name(original)
    destination = confined_path(incoming, stored)
    upload.save(destination)
    return original, stored, destination


def sha256_file(path, on_progress=None):
    total = max(path.stat().st_size, 1)
    consumed = 0
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            consumed += len(chunk)
            if on_progress:
                on_progress(min(65, 15 + int(consumed / total * 50)))
    return digest.hexdigest()


def collision_free_destination(directory, filename):
    """Atomically reserve a destination name so concurrent workers cannot collide."""
    directory.mkdir(parents=True, exist_ok=True)
    safe = validate_filename(filename)
    destination = confined_path(directory, safe)
    counter = 1
    while True:
        try:
            destination.touch(exist_ok=False)
            return destination
        except FileExistsError:
            destination = confined_path(
                directory, f"{Path(safe).stem} ({counter}){Path(safe).suffix}"
            )
            counter += 1


def move_to_organized(source, storage_root, category, original_filename):
    if category not in ALL_CATEGORIES:
        raise FileValidationError("Unknown organization category.")
    directory = confined_path(storage_root, "organized", category)
    destination = collision_free_destination(directory, original_filename)
    try:
        shutil.move(str(source), str(destination))
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def metadata_for(path, original_filename):
    mime, _encoding = mimetypes.guess_type(original_filename)
    return {
        "file_type": mime or "application/octet-stream",
        "size": os.path.getsize(path),
        "category": category_for(original_filename),
    }


def display_size(value):
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
