"""Markdown-backed note storage: one .md file (with front matter) per note."""
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .theme import normalize_type


def _now():
    return datetime.now().replace(microsecond=0)


@dataclass
class Note:
    title: str
    type: str = "todo"
    content: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created: datetime = field(default_factory=_now)
    updated: datetime = field(default_factory=_now)
    path: Path | None = None
    archived_path: Path | None = None


def week_folder_name(when):
    """e.g. '2026-W43 (19 Oct - 25 Oct 2026)' — ISO week, Monday to Sunday."""
    year, week, _ = when.isocalendar()
    monday = when.date() - timedelta(days=when.weekday())
    sunday = monday + timedelta(days=6)
    return f"{year}-W{week:02d} ({monday:%d %b} - {sunday:%d %b %Y})"


def slugify(text):
    s = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:48].strip("-") or "note"


def _parse_dt(value):
    try:
        return datetime.fromisoformat(value.strip()) if value else None
    except ValueError:
        return None


class NoteStore:
    def __init__(self, folder, archive_folder=None):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.archive_folder = Path(archive_folder) if archive_folder else self.folder.parent / "archive"

    def load_all(self):
        notes = []
        for path in self.folder.glob("*.md"):
            try:
                notes.append(self._parse(path))
            except (OSError, UnicodeDecodeError):
                continue
        notes.sort(key=lambda n: n.created, reverse=True)
        return notes

    def _parse(self, path):
        text = path.read_text(encoding="utf-8")
        meta, body = {}, text
        m = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
        if m:
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
            body = text[m.end():]
        body = body.lstrip("\n")

        title = meta.get("title", "").strip()
        h = re.match(r"^#\s+(.+?)\s*(?:\n|$)", body)
        if h and (not title or h.group(1).strip() == title):
            title = title or h.group(1).strip()
            body = body[h.end():].lstrip("\n")
        title = title or path.stem.replace("-", " ").title()

        mtime = datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0)
        return Note(
            title=title,
            type=normalize_type(meta.get("type")),
            content=body.rstrip(),
            id=meta.get("id") or uuid.uuid4().hex[:8],
            created=_parse_dt(meta.get("created")) or mtime,
            updated=_parse_dt(meta.get("updated")) or mtime,
            path=path,
        )

    def save(self, note, touch=True):
        if touch:
            note.updated = _now()
        note.title = " ".join(note.title.split()) or "Untitled"
        target = self.folder / f"{slugify(note.title)}-{note.id}.md"
        self._write(target, note)
        if note.path and note.path != target and note.path.exists():
            note.path.unlink()
        note.path = target

    def archive(self, note):
        """Move a note out of the board into archive/<week>/ instead of deleting it."""
        now = _now()
        folder = self.archive_folder / week_folder_name(now)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{slugify(note.title)}-{note.id}.md"
        self._write(target, note, archived=now)
        if note.path and note.path.exists():
            note.path.unlink()
        note.path = None
        note.archived_path = target
        return target

    def restore(self, note):
        """Undo an archive: put the note back on the board."""
        archived = note.archived_path
        self.save(note, touch=False)
        if archived and archived.exists():
            archived.unlink()
            if not any(archived.parent.iterdir()):
                archived.parent.rmdir()
        note.archived_path = None

    def _write(self, target, note, archived=None):
        text = (
            "---\n"
            f"id: {note.id}\n"
            f"title: {note.title}\n"
            f"type: {note.type}\n"
            f"created: {note.created.isoformat()}\n"
            f"updated: {note.updated.isoformat()}\n"
            + (f"archived: {archived.isoformat()}\n" if archived else "")
            + "---\n\n"
            f"# {note.title}\n\n"
            f"{note.content.rstrip()}\n"
        )
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)


def seed_examples(store):
    """Drop a handful of showcase notes in on the very first run."""
    marker = store.folder / ".seeded"
    if marker.exists():
        return
    if not any(store.folder.glob("*.md")):
        samples = [
            ("Welcome to Sticky Orb", "project",
             "Hover the orb in the top-right corner to summon the wheel.\n\n"
             "- Scroll, drag or use the arrow keys to spin\n"
             "- Click a note to bring it into focus, click again to edit\n"
             "- Hover a card and hit × in its corner to delete\n"
             "- Press N for a new note, 0-5 to filter by type"),
            ("Plan the week", "todo", "- [ ] Clear the inbox\n- [x] Book flights\n- [ ] Prepare the demo"),
            ("Ship the Q4 roadmap", "task", "Finalise milestones and share them with the team by Friday."),
            ("Call back the vendor about the contract", "followup", "Confirm pricing tiers and the renewal date."),
            ("Reply to the design review thread", "email",
             "Thank everyone, summarise the decisions and attach the updated mockups."),
        ]
        now = _now()
        for i, (title, kind, content) in enumerate(samples):
            stamp = now - timedelta(minutes=i)
            store.save(Note(title=title, type=kind, content=content, created=stamp, updated=stamp), touch=False)
    marker.write_text("", encoding="utf-8")
