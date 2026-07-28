from pathlib import Path


def test_composite_action_runs_the_shared_advisory_cli():
    action = (Path(__file__).parents[1] / "action.yml").read_text()

    assert "repowitness audit" in action
    assert 'description: "Contract revision: base, head, or worktree."' in action
    assert '--contracts-ref "${REPOWITNESS_ACTION_CONTRACTS_REF}"' in action
    assert 'cat "${report_path}" >> "${GITHUB_STEP_SUMMARY}"' in action
    assert "--fail-on" not in action


def test_composite_action_forwards_each_check_result_to_the_shared_cli():
    action = (Path(__file__).parents[1] / "action.yml").read_text()

    assert "check-results:" in action
    assert "REPOWITNESS_ACTION_CHECK_RESULTS: ${{ inputs.check-results }}" in action
    assert 'check_result_args+=(--check-results "${check_result_path}")' in action
    assert '"${check_result_args[@]}"' in action


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
    assert "actions/upload-artifact@v7" in workflow
    assert "steps.repowitness.outputs.report" in workflow


def test_pr_workflow_collects_snapshot_bound_deterministic_checks():
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "repowitness-pr.yml"
    ).read_text()

    assert "repowitness snapshot" in workflow
    assert "python -m pytest tests/ -q" in workflow
    assert "ruff check repowitness tests" in workflow
    assert "python -m compileall -q repowitness tests" in workflow
    assert workflow.count("continue-on-error: true") == 3
    assert '"schema_version": "1"' in workflow
    assert '"snapshot": $snapshot' in workflow
    assert 'result_path="${RUNNER_TEMP}/repowitness-check-results.json"' in workflow
    assert "check-results: ${{ steps.check-evidence.outputs.path }}" in workflow
    assert workflow.index("repowitness snapshot") < workflow.index(
        "python -m pytest tests/ -q"
    )
    assert workflow.index("python -m compileall -q repowitness tests") < workflow.index(
        "uses: ./"
    )
