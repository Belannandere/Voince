"""
One-shot rename Virelo -> Voince across the project.
Skips .venv, .git, __pycache__, uploads, invoices.db, and the script itself.

Usage:
    python rename_brand.py
"""

from pathlib import Path

REPLACEMENTS = [
    ("Virelo", "Voince"),
    ("virelo", "voince"),
    ("VIRELO", "VOINCE"),
]

PROJECT_ROOT = Path(__file__).resolve().parent
SKIP_DIRS = {".venv", "venv", ".git", "__pycache__", ".pytest_cache", "uploads", "node_modules"}
SKIP_FILES = {"invoices.db", "rename_brand.py"}
TEXT_EXTENSIONS = {
    ".py", ".html", ".css", ".js", ".md", ".txt", ".ini", ".env",
    ".example", ".yml", ".yaml", ".json", ".svg", ".toml",
}

changed_files = []
renamed_files = []


def _should_skip(p: Path) -> bool:
    if any(part in SKIP_DIRS for part in p.parts):
        return True
    if p.name in SKIP_FILES:
        return True
    if p.name == ".env":
        return True  # keep user's local secrets untouched
    return False


def _is_text(p: Path) -> bool:
    return p.suffix in TEXT_EXTENSIONS or p.suffix == ""


def _replace_in_file(p: Path) -> None:
    try:
        text = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return

    new_text = text
    for old, new in REPLACEMENTS:
        new_text = new_text.replace(old, new)

    if new_text != text:
        p.write_text(new_text, encoding="utf-8")
        changed_files.append(str(p.relative_to(PROJECT_ROOT)))


def _rename_file(p: Path) -> None:
    """Rename the file if its name contains 'virelo' (case-insensitive)."""
    name = p.name
    new_name = name
    for old, new in REPLACEMENTS:
        new_name = new_name.replace(old, new)
    if new_name != name:
        target = p.with_name(new_name)
        p.rename(target)
        renamed_files.append((str(p.relative_to(PROJECT_ROOT)), new_name))


def main() -> None:
    for p in PROJECT_ROOT.rglob("*"):
        if p.is_dir():
            continue
        if _should_skip(p):
            continue
        if _is_text(p):
            _replace_in_file(p)
        _rename_file(p)

    print(f"Modified: {len(changed_files)} file(s)")
    for f in changed_files:
        print(f"  ~ {f}")

    if renamed_files:
        print(f"\nRenamed: {len(renamed_files)} file(s)")
        for old, new in renamed_files:
            print(f"  {old} -> {new}")

    if not changed_files and not renamed_files:
        print("Nothing to change.")


if __name__ == "__main__":
    main()