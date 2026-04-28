from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from src.geo import infer_story_location
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
            layout.add_story(story, briefings.get(story["canonical_label"], ""))
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

    def add_story(self, story, briefing):
        location = infer_story_location(story)
        body = _story_body(story, briefing)
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


def _story_body(story, briefing):
    parts = []
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


# Simplified Natural Earth land polygons, excluding Antarctica. Kept embedded so
# preview and runtime PDF generation stay dependency-free.
LAND_POLYGONS = [
    [
        (-12.9, 7.8), (-17.6, 14.7), (-17, 21.9), (-5.9, 35.8), (9.5, 37.3), (10.3, 33.8),
        (19.1, 30.3), (21.5, 32.8), (33.8, 31), (36.2, 36.7), (27.6, 36.7), (26.2, 39.5),
        (41.6, 41.5), (36.7, 45.2), (39.1, 47.3), (33.9, 44.4), (30.7, 46.6), (28.8, 41.1),
        (22.6, 40.3), (22.5, 36.4), (13.1, 45.7), (18.5, 40.2), (16.1, 38), (8.9, 44.4),
        (3.1, 43.1), (-2.1, 36.7), (-8.9, 36.9), (-9.4, 43), (-1.4, 44), (-4.6, 48.7),
        (8.1, 53.5), (8.5, 57.1), (10.9, 54), (19.7, 54.4), (23.3, 59.2), (29.1, 60),
        (21.3, 60.7), (23.9, 66), (17.8, 62.7), (15.9, 56.1), (5.7, 58.6), (5, 62),
        (19.2, 69.8), (28.2, 71.2), (41.1, 67.5), (33.2, 66.6), (37, 63.8), (43.9, 66.1),
        (43.5, 68.6), (68.5, 68.1), (66.7, 71), (69.9, 73), (72.8, 72.2), (72.4, 66.2),
        (74.7, 72.8), (81.5, 71.8), (80.5, 73.6), (104.4, 77.7), (114.1, 75.8),
        (109.4, 74.2), (127, 73.6), (131.3, 70.8), (140.5, 72.8), (180, 69), (180, 65),
        (177.4, 64.6), (179.2, 62.3), (163.5, 59.9), (156.8, 51), (155.9, 56.8),
        (164.5, 62.6), (142.2, 59), (135.1, 54.7), (141.4, 52.2), (138.2, 46.3),
        (127.5, 39.8), (129.1, 35.1), (126.5, 34.4), (125.3, 39.6), (121.1, 38.9),
        (121.6, 40.9), (118, 39.2), (122.4, 37.5), (119.2, 34.9), (121.7, 28.2),
        (115.9, 22.8), (105.9, 19.8), (109.3, 13.4), (105.2, 8.6), (100.1, 13.4),
        (99.2, 9.2), (104.2, 1.3), (98.3, 7.8), (97.2, 16.9), (94.2, 16), (91.4, 22.8),
        (80.3, 15.9), (77.5, 8), (72.6, 21.4), (66.4, 25.4), (48, 30), (51.8, 24),
        (56.4, 26.4), (59.8, 22.3), (55.3, 17.2), (43.5, 12.6), (32.4, 29.9),
        (42.7, 11.7), (51, 10.6), (39.2, -4.7), (40.1, -16.1), (25.8, -33.9),
        (18.4, -34.1), (15.2, -27.1), (8.5, 4.8), (-8, 4.4), (-12.9, 7.8),
    ],
    [
        (-78.2, 8.3), (-80.9, 7.2), (-87.5, 13.3), (-103.5, 18.3), (-114.8, 31.8),
        (-109.4, 23.2), (-112.2, 24.7), (-124.4, 40.3), (-122.8, 49), (-134.1, 58.1),
        (-151.7, 59.2), (-150.6, 61.3), (-158.4, 56), (-164.8, 54.4), (-157, 58.9),
        (-165.3, 60.5), (-160.8, 64.8), (-168.1, 65.7), (-161.7, 66.1), (-166.8, 68.4),
        (-156.6, 71.4), (-96.1, 67.3), (-93.9, 71.8), (-87.4, 67.2), (-85.5, 69.9),
        (-81.2, 68.7), (-94.2, 60.9), (-92.3, 57.1), (-82.3, 55.1), (-79.9, 51.2),
        (-76.5, 56.5), (-78.1, 62.3), (-73.8, 62.4), (-67.6, 58.2), (-64.6, 60.3),
        (-55.8, 53.3), (-66.4, 50.2), (-71.1, 46.8), (-65.1, 49.2), (-64.5, 46.2),
        (-63.2, 45.7), (-61.5, 45.9), (-60.5, 47), (-59.8, 45.9), (-67.1, 45.1),
        (-76.3, 39.1), (-75.7, 35.6), (-81.3, 31.4), (-80.4, 25.2), (-86.4, 30.4),
        (-97.4, 27.4), (-95.9, 18.8), (-87.1, 21.5), (-88.9, 15.9), (-83.4, 15.3),
        (-82.2, 9), (-76.8, 8.6), (-71.8, 12.4), (-71.7, 9.1), (-69.9, 12.2),
        (-61.9, 10.7), (-62.4, 9.9), (-57.1, 6), (-51.3, 4.2), (-48.6, -1.2),
        (-35.2, -5.5), (-40.9, -21.9), (-47.6, -24.9), (-53.8, -34.4), (-58.4, -33.9),
        (-56.8, -36.9), (-65.1, -41.1), (-66, -48.1), (-68.1, -52.3), (-69.5, -52.3),
        (-70.8, -52.9), (-71, -53.8), (-74.9, -52.3), (-75.6, -46.6), (-72.7, -42.4),
        (-70.2, -19.8), (-81.2, -6.1), (-78.2, 8.3),
    ],
    [
        (120.6, -33.9), (115, -34.2), (113.7, -22.5), (132.4, -11.1), (136.5, -11.9),
        (135.5, -15), (140.2, -17.7), (142.5, -10.7), (153.6, -28.1), (150, -37.4),
        (146.3, -39), (131.3, -31.5), (120.6, -33.9),
    ],
    [
        (-26.5, 82.3), (-31.9, 82.2), (-12.2, 81.3), (-20, 80.2), (-17.7, 80.1),
        (-21.7, 76.6), (-19.4, 74.3), (-26.4, 70.2), (-22.3, 70.1), (-39.8, 65.5),
        (-43.4, 60.1), (-51.6, 63.6), (-54, 67.2), (-50.9, 69.9), (-54.7, 69.6),
        (-51.4, 70.6), (-58.6, 75.5), (-73.3, 78), (-60.3, 82), (-20.8, 82.7),
        (-26.5, 82.3),
    ],
    [
        (-81.1, 83), (-72.8, 83.2), (-61.9, 82.6), (-80.6, 76.2), (-89.5, 76.5),
        (-85, 77.5), (-86.9, 80.3), (-81.8, 80.5), (-91.6, 81.9), (-81.1, 83),
    ],
    [
        (-67.9, 70.1), (-61.9, 66.9), (-68, 66.3), (-66.2, 61.9), (-78.6, 64.6),
        (-73.3, 68.1), (-90.2, 72.2), (-82.3, 73.8), (-80.7, 72.1), (-67.9, 70.1),
    ],
    [(116.6, -1.5), (116.1, -4), (112.1, -3.5), (109, 0.4), (117.1, 6.9), (119, 0.9), (116.6, -1.5)],
    [(147, -6.7), (150.7, -10.6), (137.6, -8.4), (137.9, -5.4), (130.5, -0.9), (147, -6.7)],
    [(49.7, -15.7), (47.1, -24.9), (44, -25), (44.4, -16.2), (49.2, -12), (49.7, -15.7)],
    [(-102.1, 69.1), (-113.3, 68.5), (-117.3, 70), (-112.4, 70.4), (-119.4, 71.6), (-107.5, 73.2), (-102.1, 69.1)],
    [(135.1, 33.8), (135.1, 34.6), (131, 33.9), (130.7, 31), (129.4, 33.3), (141.4, 41.4), (140.3, 35.1), (135.1, 33.8)],
    [(103.9, -5), (101.4, -2.8), (95.3, 5.5), (103.8, 0.1), (106.1, -3.1), (103.9, -5)],
    [(-5, 55.8), (-5.8, 57.8), (-3, 58.6), (1.4, 51.3), (-5.8, 50.2), (-2.9, 54), (-5, 55.8)],
    [(-172.6, 64.5), (-180, 65), (-180, 69), (-169.9, 66), (-172.6, 64.5)],
    [(-120.5, 71.4), (-123.1, 70.9), (-125.9, 71.9), (-124.9, 74.3), (-115.5, 73.5), (-120.5, 71.4)],
    [(68.9, 76.5), (58.5, 74.3), (55.4, 72.4), (57.5, 70.7), (51.6, 71.5), (55.6, 75.1), (68.9, 76.5)],
]


def _draw_locator_map(page, x, top_y, width, height, location):
    bottom = top_y - height
    label_band = 8
    map_y = bottom + label_band
    map_height = height - label_band
    page.rect(x, bottom, width, height, fill=(0.965, 0.964, 0.94), stroke=(0.78, 0.78, 0.74), line_width=0.25)
    page.line(x + 2, map_y + map_height * 0.48, x + width - 2, map_y + map_height * 0.48, 0.18, (0.84, 0.84, 0.80))
    page.line(x + width * 0.5, map_y + 2, x + width * 0.5, map_y + map_height - 2, 0.18, (0.84, 0.84, 0.80))
    land_x = x + 3
    land_y = map_y + 1
    land_width = width - 6
    land_height = map_height - 4
    for polygon in LAND_POLYGONS:
        page.polygon(
            [_project(lon, lat, land_x, land_y, land_width, land_height) for lon, lat in polygon],
            fill=(0.70, 0.70, 0.65),
        )
    for point in location.get("points", []):
        px, py = _project(point["lon"], point["lat"], land_x, land_y, land_width, land_height)
        page.circle(px, py, 2.2, fill=ACCENT, stroke=(1, 1, 1), line_width=0.35)
    if not location.get("points"):
        page.text(x + 4, map_y + map_height * 0.46, location["label"].upper(), "F2", 5.3, ACCENT)
    label = location["label"]
    if len(label) > 18:
        label = label[:17] + "."
    page.text(x + 2, bottom + 2.1, label.upper(), "F2", 4.8, MUTED)


def _project(lon, lat, x, y, width, height):
    px = x + ((lon + 180) / 360) * width
    clamped_lat = min(max(lat, -58), 78)
    py = y + ((clamped_lat + 58) / 136) * height
    return px, py


class _PDFDocument:
    def __init__(self):
        self.pages = []

    def add_page(self, width, height):
        page = _PDFPage(width, height)
        self.pages.append(page)
        return page

    def save(self, path):
        objects = {}
        next_id = 1
        font_ids = {}
        for name, base_font in {
            "F1": "Helvetica",
            "F2": "Helvetica-Bold",
            "F3": "Times-Roman",
            "F4": "Times-Bold",
            "F5": "Times-Italic",
        }.items():
            font_ids[name] = next_id
            objects[next_id] = f"<< /Type /Font /Subtype /Type1 /BaseFont /{base_font} /Encoding /WinAnsiEncoding >>".encode("ascii")
            next_id += 1

        pages_id = next_id
        next_id += 1
        catalog_id = next_id
        next_id += 1

        page_ids = []
        font_refs = " ".join(f"/{name} {obj_id} 0 R" for name, obj_id in font_ids.items())
        for page in self.pages:
            stream = "\n".join(page.ops).encode("latin-1", "replace")
            content_id = next_id
            next_id += 1
            objects[content_id] = b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"
            page_id = next_id
            next_id += 1
            page_ids.append(page_id)
            objects[page_id] = (
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {page.width:.2f} {page.height:.2f}] "
                f"/Resources << /Font << {font_refs} >> >> /Contents {content_id} 0 R >>"
            ).encode("ascii")

        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
        objects[pages_id] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")
        objects[catalog_id] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii")

        max_id = max(objects)
        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0] * (max_id + 1)
        for obj_id in range(1, max_id + 1):
            offsets[obj_id] = len(output)
            output.extend(f"{obj_id} 0 obj\n".encode("ascii"))
            output.extend(objects[obj_id])
            output.extend(b"\nendobj\n")
        xref_offset = len(output)
        output.extend(f"xref\n0 {max_id + 1}\n".encode("ascii"))
        output.extend(b"0000000000 65535 f \n")
        for obj_id in range(1, max_id + 1):
            output.extend(f"{offsets[obj_id]:010d} 00000 n \n".encode("ascii"))
        output.extend(
            f"trailer\n<< /Size {max_id + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
        )
        Path(path).write_bytes(output)


class _PDFPage:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.ops = []

    def text(self, x, y, text, font, size, fill=INK):
        self.ops.append(
            f"BT {_rgb(fill, fill_op=True)} /{font} {size:.2f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({_escape_text(text)}) Tj ET"
        )

    def line(self, x1, y1, x2, y2, width=0.5, stroke=INK):
        self.ops.append(f"{_rgb(stroke)} {width:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def rect(self, x, y, width, height, fill=None, stroke=INK, line_width=0.5):
        op = []
        if fill:
            op.append(_rgb(fill, fill_op=True))
        if stroke:
            op.append(_rgb(stroke))
        op.append(f"{line_width:.2f} w {x:.2f} {y:.2f} {width:.2f} {height:.2f} re")
        if fill and stroke:
            op.append("B")
        elif fill:
            op.append("f")
        else:
            op.append("S")
        self.ops.append(" ".join(op))

    def polygon(self, points, fill=INK, stroke=None, line_width=0.25):
        if not points:
            return
        ops = []
        if fill:
            ops.append(_rgb(fill, fill_op=True))
        if stroke:
            ops.append(_rgb(stroke))
        ops.append(f"{line_width:.2f} w")
        first = points[0]
        ops.append(f"{first[0]:.2f} {first[1]:.2f} m")
        for x, y in points[1:]:
            ops.append(f"{x:.2f} {y:.2f} l")
        ops.append("h")
        if fill and stroke:
            ops.append("B")
        elif fill:
            ops.append("f")
        else:
            ops.append("S")
        self.ops.append(" ".join(ops))

    def circle(self, x, y, radius, fill=INK, stroke=None, line_width=0.5):
        k = 0.5522847498
        c = radius * k
        ops = []
        if fill:
            ops.append(_rgb(fill, fill_op=True))
        if stroke:
            ops.append(_rgb(stroke))
        ops.append(f"{line_width:.2f} w")
        ops.append(f"{x + radius:.2f} {y:.2f} m")
        ops.append(f"{x + radius:.2f} {y + c:.2f} {x + c:.2f} {y + radius:.2f} {x:.2f} {y + radius:.2f} c")
        ops.append(f"{x - c:.2f} {y + radius:.2f} {x - radius:.2f} {y + c:.2f} {x - radius:.2f} {y:.2f} c")
        ops.append(f"{x - radius:.2f} {y - c:.2f} {x - c:.2f} {y - radius:.2f} {x:.2f} {y - radius:.2f} c")
        ops.append(f"{x + c:.2f} {y - radius:.2f} {x + radius:.2f} {y - c:.2f} {x + radius:.2f} {y:.2f} c")
        ops.append("h")
        if fill and stroke:
            ops.append("B")
        elif fill:
            ops.append("f")
        else:
            ops.append("S")
        self.ops.append(" ".join(ops))


def _rgb(color, fill_op=False):
    op = "rg" if fill_op else "RG"
    return f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} {op}"


def _escape_text(text):
    encoded = str(text or "").encode("cp1252", "replace").decode("latin-1")
    return (
        encoded
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", " ")
        .replace("\n", " ")
    )
