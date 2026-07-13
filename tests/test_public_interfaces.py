import src.claims as claims
import src.observability as observability
import src.top10 as briefing
import src.tracker as tracker
from src.tracker import replay


def test_pipeline_entrypoints_are_importable():
    entrypoints = (
        claims.extract_and_save_claims,
        claims.get_claims_for_story,
        tracker.track,
        tracker.save_observation_memory,
        replay.rebuild_from_date,
        observability.start_run,
        observability.finish_run,
        observability.pipeline_report,
        observability.write_run_report_artifact,
        briefing.build_briefing_package,
        briefing.build_briefing_markdown,
        briefing.write_top10,
    )

    assert all(callable(entrypoint) for entrypoint in entrypoints)
