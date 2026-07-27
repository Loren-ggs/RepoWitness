from pathlib import Path


def test_composite_action_runs_the_shared_advisory_cli():
    action = (Path(__file__).parents[1] / "action.yml").read_text()

    assert "repowitness audit" in action
    assert '--contracts-ref "${REPOWITNESS_ACTION_CONTRACTS_REF}"' in action
    assert 'cat "${report_path}" >> "${GITHUB_STEP_SUMMARY}"' in action
    assert "--fail-on" not in action
