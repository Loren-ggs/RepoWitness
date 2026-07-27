from pathlib import Path


def test_composite_action_runs_the_shared_advisory_cli():
    action = (Path(__file__).parents[1] / "action.yml").read_text()

    assert "repowitness audit" in action
    assert 'description: "Contract revision: base, head, or worktree."' in action
    assert '--contracts-ref "${REPOWITNESS_ACTION_CONTRACTS_REF}"' in action
    assert 'cat "${report_path}" >> "${GITHUB_STEP_SUMMARY}"' in action
    assert "--fail-on" not in action


def test_pr_workflow_runs_the_local_action_and_uploads_its_report():
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "repowitness-pr.yml"
    ).read_text()

    assert "fetch-depth: 0" in workflow
    assert "uses: ./" in workflow
    assert "contracts-ref: base" in workflow
    assert "github.event.pull_request.head.repo.full_name == github.repository" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "steps.repowitness.outputs.report" in workflow
