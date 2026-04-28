#!/usr/bin/env python
"""Generate a deterministic newspaper PDF preview without scraping or API calls."""

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.newspaper import build_newspaper_pdf  # noqa: E402


def article(source, title, description, published_at, theme):
    return {
        "source": source,
        "title": title,
        "description": description,
        "url": "https://example.com/" + title.lower().replace(" ", "-")[:48],
        "published_at": published_at,
        "importance": 4,
        "theme": theme,
    }


def story(label, trend, theme, importance, source_count, briefing, articles, previous_context=None):
    return {
        "canonical_label": label,
        "story_label": label,
        "theme": theme,
        "themes": {theme},
        "trend": trend,
        "source_count": source_count,
        "importance_avg": importance,
        "previous_context": previous_context or {},
        "articles": articles,
        "observation_ids": [],
    }, briefing


def build_sample_package():
    stories = []
    briefings = {}

    samples = [
        story(
            "Chad water clash",
            "new",
            "Geopolitics & War",
            4.0,
            2,
            (
                "At least 42 people were killed in eastern Chad after a family dispute over access "
                "to a water source widened into communal violence near the Sudan border. The army "
                "has been deployed, but the episode points to a wider pattern of resource pressure, "
                "weak local mediation, and instability around displaced communities."
            ),
            [
                article("NOS", "42 killed after water-source dispute in Chad", "Authorities deployed the army after violence near Guereda.", "Mon, 27 Apr 2026 10:53:00 GMT", "Geopolitics & War"),
                article("DW", "Clashes over water resources in Chad kill over 40", "Officials say traditional mediation will follow the investigation.", "Mon, 27 Apr 2026 09:40:00 GMT", "Geopolitics & War"),
            ],
        ),
        story(
            "Mali attacks",
            "up",
            "Geopolitics & War",
            4.7,
            5,
            (
                "Coordinated militant attacks across Mali exposed severe pressure on the ruling "
                "junta and raised questions about whether Russia-backed security support can contain "
                "the insurgency. The reported killing of senior defense figures makes the crisis "
                "politically sharper than another isolated raid."
            ),
            [
                article("NYT", "Mali defense minister killed by al-Qaeda-linked militants", "The attack struck close to the center of military power.", "Mon, 27 Apr 2026 16:19:00 GMT", "Geopolitics & War"),
                article("Guardian", "Mali militant attacks expose limits of Russian influence", "Insurgent groups appear to be coordinating more effectively.", "Mon, 27 Apr 2026 14:35:00 GMT", "Geopolitics & War"),
            ],
            {"delta_summary": "Earlier reporting focused on scattered attacks and rising pressure on the junta."},
        ),
        story(
            "Ukraine drone campaign",
            "steady",
            "Geopolitics & War",
            4.2,
            7,
            (
                "Ukraine is leaning further into drone operations to offset Russia's manpower and "
                "firepower advantage. The war remains locked in attrition, with fresh strikes and "
                "civilian damage alongside a wider European debate about how long support can be "
                "sustained without a clearer path to settlement."
            ),
            [
                article("BBC News", "Ukraine drone commander targets Russian oil and morale", "Unmanned systems remain central to Kyiv's military adaptation.", "Mon, 27 Apr 2026 10:04:00 GMT", "Geopolitics & War"),
                article("Guardian", "Odesa bears brunt of latest Russian attacks", "Civilian injuries kept pressure on air-defense supply.", "Mon, 27 Apr 2026 14:36:00 GMT", "Geopolitics & War"),
            ],
            {"summary": "The conflict has remained a war of adaptation, endurance, and constrained diplomacy."},
        ),
        story(
            "Iran war economic fallout",
            "up",
            "Economy",
            3.8,
            10,
            (
                "The Iran conflict is increasingly being measured through economic transmission "
                "rather than battlefield movement. Energy costs, trade uncertainty, and pressure on "
                "manufacturing are spreading unevenly, while allies question whether Washington has "
                "a credible political end state."
            ),
            [
                article("Al Jazeera", "Will the Iran war push millions back into poverty?", "Food and fuel prices are creating wider risks.", "Mon, 27 Apr 2026 16:23:00 GMT", "Economy"),
                article("NYT", "Iran war shakes global economy", "The US has been partly insulated, but global effects are mounting.", "Mon, 27 Apr 2026 15:03:00 GMT", "Economy"),
            ],
            {"delta_summary": "Previously: markets were reacting mainly to oil and shipping disruption."},
        ),
        story(
            "Northern Ireland bombing",
            "new",
            "Geopolitics & War",
            4.0,
            1,
            (
                "Police released footage of a car bomb attack in Northern Ireland, reviving concern "
                "about dissident violence and the resilience of local security arrangements. The "
                "immediate issue is whether the event remains contained or signals a broader pattern."
            ),
            [
                article("BBC News", "Police release footage of reckless car bomb attack", "The incident prompted renewed concern about dissident groups.", "Mon, 27 Apr 2026 16:33:00 GMT", "Geopolitics & War"),
            ],
        ),
        story(
            "Old campaign finance story",
            "down",
            "USA Politics",
            2.8,
            2,
            (
                "Coverage of the campaign-finance dispute continued, but today's reporting mostly "
                "repeated earlier allegations and procedural updates. It remains worth tracking, "
                "though it is no longer driving the day."
            ),
            [
                article("Example News", "Campaign finance inquiry enters procedural phase", "Officials filed routine motions in the case.", "Mon, 27 Apr 2026 08:30:00 GMT", "USA Politics"),
            ],
            {"summary": "Earlier coverage centered on the initial allegations and partisan reaction."},
        ),
    ]

    for item, briefing in samples:
        stories.append(item)
        briefings[item["canonical_label"]] = briefing

    return {
        "generated_at": datetime(2026, 4, 27, 20, 42),
        "stories": stories,
        "sections": [],
        "display_stories": stories,
        "briefings": briefings,
    }


def main():
    parser = argparse.ArgumentParser(description="Render a local newspaper PDF preview.")
    parser.add_argument(
        "--out",
        default="test_output/preview/newspaper_preview.pdf",
        help="PDF path to write. Defaults to test_output/preview/newspaper_preview.pdf",
    )
    args = parser.parse_args()

    out = ROOT / args.out if not Path(args.out).is_absolute() else Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    build_newspaper_pdf(build_sample_package()).save(out)
    print(out)


if __name__ == "__main__":
    main()
