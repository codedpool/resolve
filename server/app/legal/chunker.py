"""Cut the fetched legal texts into chunks by section or clause.

A chunk's `text` is a whitespace-normalised slice of the source, never edited, so quotecheck can
prove it. Navigation noise is excluded by start and end markers in data/legal/chunking.yaml.
`search_text` is what gets embedded and indexed: the same words with page furniture removed and
a short context line (source title, heading, section) in front.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.legal.quotecheck import normalise

LEGAL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "legal"

_NOISE_LINE = re.compile(
    r"^(?:--- page \d+ ---|(?:SEC\. \d+\] )?\d* ?THE GAZETTE OF INDIA.*|\[भाग II.*|\d+ +THE GAZETTE OF INDIA.*)$"
)
_NOISE_INLINE = re.compile(
    r"--- page \d+ ---|(?:SEC\. \d+\] )?\d* ?THE GAZETTE OF INDIA(?: :)? EXTRAORDINARY(?: \[PART II—(?:SEC\. [\d()i]+\])?)? ?\d*"
    r"|\[भाग II—खण् ड 3\(i\)\] भारत का राजपत्र : ऄसाधारण \d+"
)
_SECTION_LINE = re.compile(r"^(\d{1,3})\.\s")
_SUBCLAUSE_LINE = re.compile(r"^\((\d{1,3})\)\s")
_FIRST_LINE_SUBCLAUSE = re.compile(r"^\d{1,3}\.\s*(?:.{0,120}?[—–:\-]\s*)?\((\d{1,3})\)")
_CHAPTER_LINE = re.compile(r"^CHAPTER ([IVXLC]+)\s*$")
_RULE_TITLE = re.compile(r"^\d{1,3}\.\s+(.*?)[\s.:]*(?:---|--|—|–|:-|:—)")


@dataclass(frozen=True)
class Chunk:
    source_id: str
    layer: str
    source_url: str
    fetched_at: str
    section: str
    clause: str
    heading: str
    ordinal: int
    text: str
    search_text: str
    entity_type_tags: tuple[str, ...] = ()
    review_state: str = "unreviewed"

    @property
    def key(self) -> str:
        """Idempotency key: same source position and same words give the same key."""
        raw = "\x1f".join([self.source_id, self.section, self.clause, str(self.ordinal), self.text])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @property
    def locator(self) -> str:
        return f"{self.source_id}:{self.section}{self.clause}"

    @property
    def clause_numbers(self) -> list[int]:
        return [int(n) for n in re.findall(r"\((\d+)\)", self.clause)]


@dataclass
class Corpus:
    chunks: list[Chunk] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)


def clean_for_search(text: str) -> str:
    return normalise(_NOISE_INLINE.sub(" ", text))


def _region(text: str, cfg: dict) -> str:
    start = re.search(cfg["start"], text)
    if not start:
        raise ValueError(f"start marker not found: {cfg['start']}")
    end = re.search(cfg["end"], text[start.start():]) if cfg.get("end") else None
    stop = start.start() + end.start() if end else len(text)
    return text[start.start():stop]


def _trim_noise(lines: list[str]) -> list[str]:
    def noisy(line: str) -> bool:
        return not line.strip() or bool(_NOISE_LINE.match(line.strip()))

    while lines and noisy(lines[0]):
        lines = lines[1:]
    while lines and noisy(lines[-1]):
        lines = lines[:-1]
    return lines


def _chapter_before(text: str, position: int) -> str:
    """The chapter heading in force where the chunked region starts (the heading may precede the start marker)."""
    found = ""
    for match in re.finditer(r"(?m)^CHAPTER ([IVXLC]+)\s*\n(.+)$", text[:position]):
        found = f"Chapter {match.group(1)}: {match.group(2).strip().title()}"
    return found


def _make(source_id, cfg, url, fetched, section, clause, heading, ordinal, text) -> Chunk:
    context = [cfg["short_title"]]
    if heading:
        context.append(heading)
    if cfg.get("mode") == "numbered":
        context.append(f"Section {section}{clause}")
    search = ". ".join(context) + ". " + clean_for_search(text)
    return Chunk(source_id, cfg["layer"], url, str(fetched), section, clause, heading, ordinal, text, search)


def _units(lines: list[str]) -> list[tuple[int | None, list[str]]]:
    """Split a section's lines at sequentially numbered sub-clauses. Lines before the first stay with it."""
    units: list[tuple[int | None, list[str]]] = []
    expected = 1
    for index, line in enumerate(lines):
        match = _FIRST_LINE_SUBCLAUSE.match(line) if index == 0 else None
        match = match or _SUBCLAUSE_LINE.match(line)
        if match and int(match.group(1)) == expected:
            units.append((expected, [line]))
            expected += 1
        elif units:
            units[-1][1].append(line)
        else:
            units.append((None, [line]))
    if len(units) > 1 and units[0][0] is None:
        number, body = units[1]
        units = [(number, units[0][1] + body)] + units[2:]
    return units


def _split_long(lines: list[str], maximum: int) -> list[list[str]]:
    pieces: list[list[str]] = [[]]
    size = 0
    for line in lines:
        add = len(normalise(line)) + 1
        if pieces[-1] and size + add > maximum:
            pieces.append([])
            size = 0
        pieces[-1].append(line)
        size += add
    return pieces


def _pack(units, target: int, maximum: int) -> list[tuple[str, str]]:
    """Return (clause label, text) groups. Whole section when it fits the target."""
    texts = [(n, normalise("\n".join(body))) for n, body in units]
    if sum(len(t) + 1 for _, t in texts) <= target or len(units) == 1 and len(texts[0][1]) <= maximum:
        return [("", normalise("\n".join(line for _, body in units for line in body)))]
    groups: list[tuple[str, str]] = []
    current: list[tuple[int | None, str]] = []

    def flush() -> None:
        if not current:
            return
        numbers = [n for n, _ in current if n is not None]
        label = ""
        if numbers:
            label = f"({numbers[0]})" if numbers[0] == numbers[-1] else f"({numbers[0]})-({numbers[-1]})"
        groups.append((label, " ".join(t for _, t in current)))
        current.clear()

    for (number, body), (_, text) in zip(units, texts):
        if len(text) > maximum:
            flush()
            for part, piece in enumerate(_split_long(body, maximum), start=1):
                base = f"({number})" if number is not None else ""
                groups.append((f"{base} part {part}".strip(), normalise("\n".join(_trim_noise(piece)))))
            continue
        if current and sum(len(t) + 1 for _, t in current) + len(text) > target:
            flush()
        current.append((number, text))
    flush()
    return groups


def chunk_numbered(source_id: str, text: str, cfg: dict, url: str, fetched, target: int, maximum: int) -> list[Chunk]:
    region = _region(text, cfg)
    lines = region.split("\n")
    chapter = _chapter_before(text, text.index(region))
    expected = int(cfg.get("first_number", 1))
    implicit = bool(cfg.get("implicit_first"))
    sections: list[tuple[str, str, list[str]]] = []
    chapter_pending: str | None = None
    current: tuple[str, str, list[str]] | None = None
    if implicit:
        current = (str(expected - 1), chapter, [])
    for line in lines:
        stripped = line.strip()
        chap = _CHAPTER_LINE.match(stripped)
        if chap:
            chapter_pending = chap.group(1)
            continue
        if chapter_pending is not None:
            chapter = f"Chapter {chapter_pending}: {stripped.title()}"
            chapter_pending = None
            continue
        match = _SECTION_LINE.match(line)
        if match and int(match.group(1)) == expected:
            if current:
                sections.append(current)
            heading = chapter
            if cfg.get("heading") == "rule_title":
                title = _RULE_TITLE.match(line)
                heading = title.group(1) if title else ""
            current = (match.group(1), heading, [line])
            expected += 1
        elif current:
            current[2].append(line)
    if current:
        sections.append(current)

    chunks: list[Chunk] = []
    ordinal = 0
    for number, heading, body in sections:
        joined = "\n".join(body)
        for pattern in cfg.get("tail_cut", []):
            cut = re.search(pattern, joined)
            if cut:
                joined = joined[: cut.start()]
        body = _trim_noise(joined.split("\n"))
        if not body:
            continue
        if cfg.get("heading") == "rule_title" and len(body) > 1 and not heading:
            heading = ""
        for clause, chunk_text in _pack(_units(body), target, maximum):
            chunks.append(_make(source_id, cfg, url, fetched, number, clause, heading, ordinal, chunk_text))
            ordinal += 1
    return chunks


def chunk_paragraphs(source_id: str, text: str, cfg: dict, url: str, fetched, target: int, maximum: int) -> list[Chunk]:
    region = _region(text, cfg)
    blocks = [b for b in re.split(r"\n\s*\n", region) if b.strip()]
    groups: list[list[str]] = []
    size = 0
    for block in blocks:
        folded = normalise(block)
        if len(folded) > maximum:
            lines = _trim_noise(block.split("\n"))
            for piece in _split_long(lines, maximum):
                groups.append(["\n".join(piece)])
            size = maximum
            continue
        if groups and size + len(folded) + 1 <= target:
            groups[-1].append(block)
            size += len(folded) + 1
        else:
            groups.append([block])
            size = len(folded)
    chunks = []
    for index, group in enumerate(groups):
        folded = normalise("\n\n".join(group))
        if folded:
            chunks.append(_make(source_id, cfg, url, fetched, f"p{index + 1}", "", cfg["short_title"], index, folded))
    return chunks


def load_manifest() -> dict[str, dict]:
    raw = yaml.safe_load((LEGAL_DIR / "sources.yaml").read_text(encoding="utf-8"))
    return {item["id"]: item for item in raw["sources"]}


def build_corpus(legal_dir: Path = LEGAL_DIR) -> Corpus:
    manifest = load_manifest()
    config = yaml.safe_load((legal_dir / "chunking.yaml").read_text(encoding="utf-8"))
    target, maximum = int(config["target_chars"]), int(config["max_chars"])
    corpus = Corpus()
    for source_id, cfg in config["sources"].items():
        entry = manifest[source_id]
        text = (legal_dir / entry["text_file"]).read_text(encoding="utf-8")
        corpus.sources[source_id] = text
        chunker = chunk_numbered if cfg["mode"] == "numbered" else chunk_paragraphs
        corpus.chunks.extend(chunker(source_id, text, cfg, entry["url"], entry["fetched_at"], target, maximum))
    return corpus
