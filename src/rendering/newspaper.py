from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from src.rendering import newspaper_map
from src.rendering.geo import infer_story_location
from src.rendering.pdf_writer import PDFDocument as _PDFDocument
from src.top10 import THEME_ORDER, build_briefing_package


NEWSPAPER_DIR = Path("newspapers")
PAGE_WIDTH = 595.28
PAGE_HEIGHT = 841.89
MARGIN = 36
GAP = 18
ACCENT = (0.55, 0.04, 0.04)
INK = (0.08, 0.08, 0.08)
MUTED = (0.35, 0.35, 0.35)
MAP_WIDTH = 62
MAP_HEIGHT = 36

SECTION_SPECS = [
    ("NEW TODAY", "First detected stories entering the news picture.", {"new"}),
    ("DEVELOPING STORIES", "Existing stories with visible movement today.", {"up"}),
    ("CONTINUING WATCH", "Important ongoing stories with steadier coverage.", {"steady"}),
    ("COOLING / LOWER PRIORITY", "Stories still present but losing momentum.", {"down"}),
]

LAND_POLYGONS = newspaper_map.LAND_POLYGONS
_draw_locator_map = newspaper_map.draw_locator_map
_project = newspaper_map.project


def build_newspaper_sections(package):
    stories = list(package.get("display_stories") or package.get("stories") or [])
    seen = set()
    unique_stories = []
    for story in stories:
        label = story["canonical_label"]
        if label in seen:
            continue
        seen.add(label)
        unique_stories.append(story)

    sections = []
    assigned = set()
    for title, description, trends in SECTION_SPECS:
        section_stories = [
            story for story in unique_stories
            if story.get("trend", "steady") in trends and story["canonical_label"] not in assigned
        ]
        assigned.update(story["canonical_label"] for story in section_stories)
        if section_stories:
            sections.append({
                "title": title,
                "description": description,
                "stories": section_stories,
            })

    remainder = [story for story in unique_stories if story["canonical_label"] not in assigned]
    if remainder:
        sections.append({
            "title": "BRIEFLY NOTED",
            "description": "Relevant stories without a clear movement signal.",
            "stories": remainder,
        })
    return sections


def write_newspaper_pdf(tracked, n=3, package=None):
    package = package or build_briefing_package(tracked, n=n)
    NEWSPAPER_DIR.mkdir(exist_ok=True)
    pdf = build_newspaper_pdf(package)
    out = NEWSPAPER_DIR / f"newspaper_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    pdf.save(out)
    print(f"Written: {out}")
    return out


def build_newspaper_pdf(package):
    doc = _PDFDocument()
    layout = _NewspaperLayout(doc, package.get("generated_at") or datetime.now())
    sections = build_newspaper_sections(package)
    briefings = package.get("briefings", {})

    layout.draw_front_matter(sections)
    if not sections:
        layout.add_empty_notice()
    for section in sections:
        layout.add_section(section["title"], section["description"])
        for story in section["stories"]:
            layout.add_story(
                story,
                briefings.get(story["canonical_label"], ""),
                package.get("deltas", {}).get(story["canonical_label"], ""),
            )
    layout.finish()
    return doc


class _NewspaperLayout:
    def __init__(self, doc, generated_at):
        self.doc = doc
        self.generated_at = generated_at
        self.column_width = (PAGE_WIDTH - MARGIN * 2 - GAP) / 2
        self.page = None
        self.page_number = 0
        self.column = 0
        self.y = PAGE_HEIGHT - MARGIN
        self._new_page(first=True)

    def _new_page(self, first=False):
        self.page = self.doc.add_page(PAGE_WIDTH, PAGE_HEIGHT)
        self.page.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=(1, 1, 1), stroke=None, line_width=0)
        self.page_number += 1
        self.column = 0
        self.y = PAGE_HEIGHT - MARGIN
        if not first:
            self.page.text(MARGIN, PAGE_HEIGHT - 24, "THE DAILY BRIEFING", "F2", 7, MUTED)
            self.page.text(PAGE_WIDTH - MARGIN - 36, PAGE_HEIGHT - 24, str(self.page_number), "F1", 7, MUTED)
            self.page.line(MARGIN, PAGE_HEIGHT - 31, PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 31, 0.25, (0.75, 0.75, 0.75))
            self.y = PAGE_HEIGHT - 48

    def draw_front_matter(self, sections):
        date_label = self.generated_at.strftime("%A, %d %B %Y")
        issue = self.generated_at.strftime("Issue %Y-%m-%d")
        self.page.text(MARGIN, self.y, "THE DAILY BRIEFING", "F4", 29, INK)
        self.page.text(PAGE_WIDTH - MARGIN - 108, self.y + 4, issue, "F2", 8, MUTED)
        self.y -= 17
        self.page.text(MARGIN, self.y, date_label, "F1", 8, MUTED)
        self.page.line(MARGIN, self.y - 10, PAGE_WIDTH - MARGIN, self.y - 10, 1.2, INK)
        self.y -= 34

        counts = {section["title"]: len(section["stories"]) for section in sections}
        summary = " | ".join(f"{title}: {count}" for title, count in counts.items())
        if summary:
            self.page.text(MARGIN, self.y, summary, "F2", 7.5, ACCENT)
            self.y -= 18

    def add_empty_notice(self):
        self.page.text(MARGIN, self.y, "No tracked stories found.", "F3", 11, INK)

    def add_section(self, title, description):
        self._ensure_space(44)
        x = self._x()
        self.page.line(x, self.y, x + self.column_width, self.y, 0.7, INK)
        self.y -= 13
        self.page.text(x, self.y, title, "F2", 9, ACCENT)
        self.y -= 11
        for line in _wrap_text(description, 6.8, self.column_width, "sans"):
            self.page.text(x, self.y, line, "F1", 6.8, MUTED)
            self.y -= 8
        self.y -= 5

    def add_story(self, story, briefing, delta_summary=""):
        location = infer_story_location(story)
        body = _story_body(story, briefing, delta_summary)
        source_line = _source_summary(story)
        meta = _meta_line(story, location)
        title_lines = _wrap_text(story["canonical_label"], 13, self.column_width - MAP_WIDTH - 14, "serif-bold")
        meta_lines = _wrap_text(meta, 6.5, self.column_width, "sans")
        body_lines = _paragraph_lines(body, 8.6, self.column_width, "serif")
        source_lines = _wrap_text(source_line, 6.3, self.column_width, "sans")
        header_height = (
            max(MAP_HEIGHT + 12, len(title_lines) * 14 + 12)
            + len(meta_lines) * 8
            + 12
        )
        self._ensure_space(header_height)

        x = self._x()
        top = self.y
        self.page.text(x, self.y, _story_label(story), "F2", 6.2, ACCENT)
        _draw_locator_map(self.page, x + self.column_width - MAP_WIDTH, self.y + 2, MAP_WIDTH, MAP_HEIGHT, location)
        self.y -= 13

        for line in title_lines:
            self.page.text(x, self.y, line, "F4", 13, INK)
            self.y -= 14
        reserved_y = top - MAP_HEIGHT - 8
        if self.y > reserved_y:
            self.y = reserved_y

        for line in meta_lines:
            self.page.text(x, self.y, line, "F1", 6.5, MUTED)
            self.y -= 8
        self.y -= 3

        for line in body_lines:
            if line is None:
                self._ensure_story_space(4, story)
                self.y -= 4
                continue
            self._ensure_story_space(10.2, story)
            x = self._x()
            self.page.text(x, self.y, line, "F3", 8.6, INK)
            self.y -= 10.2

        self.y -= 1
        for line in source_lines:
            self._ensure_story_space(7.5, story)
            x = self._x()
            self.page.text(x, self.y, line, "F1", 6.3, MUTED)
            self.y -= 7.5
        self.y -= 12
        self._ensure_space(8)
        x = self._x()
        self.page.line(x, self.y + 5, x + self.column_width, self.y + 5, 0.25, (0.82, 0.82, 0.82))

    def finish(self):
        pass

    def _ensure_space(self, needed):
        bottom = MARGIN + 18
        if self.y - needed >= bottom:
            return False
        if self.column == 0:
            self.column = 1
            self.y = PAGE_HEIGHT - 48 if self.page_number > 1 else PAGE_HEIGHT - MARGIN - 92
        else:
            self._new_page()
        return True

    def _ensure_story_space(self, needed, story):
        if self._ensure_space(needed):
            self.page.text(self._x(), self.y, f"{story['canonical_label']} continued", "F2", 5.8, MUTED)
            self.y -= 9

    def _x(self):
        return MARGIN + self.column * (self.column_width + GAP)


def _story_label(story):
    trend = story.get("trend", "steady")
    if trend == "new":
        return "FIRST REPORT"
    if trend == "up":
        return "DEVELOPING"
    if trend == "down":
        return "COOLING"
    return "CONTINUING STORY"


def _story_body(story, briefing, delta_summary=""):
    parts = []
    delta_summary = str(delta_summary or "").strip()
    if delta_summary:
        parts.append(f"What changed today: {delta_summary}")
    if story.get("trend") != "new":
        previous = _previous_context_line(story)
        if previous:
            parts.append(f"Previously: {previous}")
    if briefing:
        parts.append(briefing)
    else:
        parts.append(_fallback_story_body(story))
    return "\n\n".join(part for part in parts if part).strip()


def _previous_context_line(story):
    context = story.get("previous_context") or {}
    text = context.get("summary") or ""
    text = _strip_leading_label(text, {"previously", "earlier"})
    return _first_sentence(text, 34)


def _fallback_story_body(story):
    sources = story.get("source_count", 0)
    source_word = "sources" if sources != 1 else "source"
    latest = _latest_reported_at(story.get("articles", []))
    return (
        f"This story is included based on {sources} {source_word}, "
        f"with the latest report at {latest}. A generated briefing was not available."
    )


def _strip_leading_label(text, labels):
    value = str(text or "").strip()
    while True:
        lowered = value.lower()
        matched = False
        for label in labels:
            prefix = f"{label}:"
            if lowered.startswith(prefix):
                value = value[len(prefix):].strip()
                matched = True
                break
        if not matched:
            return value


def _meta_line(story, location):
    themes = _theme_summary(story)
    sources = story.get("source_count", 0)
    importance = round(story.get("importance_avg", 0), 1)
    latest = _latest_reported_at(story.get("articles", []))
    source_word = "sources" if sources != 1 else "source"
    return (
        f"{location['label']} | {themes} | importance {importance} | "
        f"{sources} {source_word} | latest {latest}"
    )


def _theme_summary(story):
    themes = [theme for theme in THEME_ORDER if theme in story.get("themes", set())]
    return " / ".join(themes) if themes else story.get("theme", "Other")


def _latest_reported_at(articles):
    parsed = [_parse_reported_at(a.get("published_at")) for a in articles]
    parsed = [value for value in parsed if value]
    if parsed:
        return max(parsed).strftime("%Y-%m-%d %H:%M UTC")
    values = [a.get("published_at") for a in articles if a.get("published_at")]
    return values[0] if values else "unknown time"


def _parse_reported_at(value):
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _source_summary(story):
    counts = Counter(a.get("source", "Unknown") for a in story.get("articles", []))
    sources = [source for source, _ in counts.most_common(5)]
    if not sources:
        return "Sources: none"
    suffix = "" if len(counts) <= 5 else f" +{len(counts) - 5}"
    return "Sources: " + ", ".join(sources) + suffix


def _first_sentence(text, word_limit):
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    sentence_end = min([idx for idx in [text.find("."), text.find("?"), text.find("!")] if idx >= 0] or [len(text)])
    return _trim_words(text[:sentence_end + 1], word_limit)


def _trim_words(text, limit):
    words = str(text or "").split()
    if len(words) <= limit:
        return str(text or "").strip()
    trimmed = " ".join(words[:limit]).rstrip(" ,;:.")
    return trimmed + "..."


def _paragraph_lines(text, size, width, font_kind):
    lines = []
    for paragraph in str(text or "").split("\n\n"):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        lines.extend(_wrap_text(paragraph, size, width, font_kind))
        lines.append(None)
    if lines and lines[-1] is None:
        lines.pop()
    return lines


def _wrap_text(text, size, max_width, font_kind):
    words = str(text or "").split()
    if not words:
        return []
    lines = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if _text_width(candidate, size, font_kind) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = word
        else:
            lines.append(_break_word(word, size, max_width, font_kind))
            current = ""
    if current:
        lines.append(current)
    return lines


def _break_word(word, size, max_width, font_kind):
    chars = []
    for char in word:
        candidate = "".join(chars) + char
        if _text_width(candidate, size, font_kind) > max_width:
            break
        chars.append(char)
    return "".join(chars) or word[:1]


def _text_width(text, size, font_kind):
    multiplier = 0.47 if font_kind == "serif" else 0.5
    if "bold" in font_kind:
        multiplier += 0.035
    total = 0
    for char in text:
        if char in " .,:;|'!iIl":
            total += size * 0.25
        elif char in "MW@#%&":
            total += size * 0.8
        elif char.isupper():
            total += size * (multiplier + 0.08)
        else:
            total += size * multiplier
    return total
