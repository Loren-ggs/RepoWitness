import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def test_composite_action_runs_the_shared_cli_with_opt_in_fail_on():
    action = (Path(__file__).parents[1] / "action.yml").read_text(
        encoding="utf-8"
    )

    assert "repowitness audit" in action
    assert 'description: "Contract revision: base, head, or worktree."' in action
    assert '--contracts-ref "${REPOWITNESS_ACTION_CONTRACTS_REF}"' in action
    assert 'cat "${report_path}" >> "${GITHUB_STEP_SUMMARY}"' in action
    assert "fail-on:" in action
    assert 'default: ""' in action
    assert 'fail_on_args+=(--fail-on "${verdict}")' in action
    assert '"${fail_on_args[@]}"' in action
    assert 'echo "exit-code=${audit_status}" >> "${GITHUB_OUTPUT}"' in action


def test_composite_action_defaults_marketplace_inputs_safely():
    action_path = Path(__file__).parents[1] / "action.yml"
    action = yaml.safe_load(action_path.read_text(encoding="utf-8"))
    source = action_path.read_text(encoding="utf-8")

    assert action["inputs"]["base"] == {
        "description": (
            "Optional base Git ref. Defaults to the PR base SHA or "
            "repository default branch."
        ),
        "required": False,
        "default": "",
    }
    assert action["inputs"]["api-key"]["default"] == ""
    assert action["inputs"]["comment"]["default"] == "true"
    assert "REPOWITNESS_EVENT_BASE_SHA: ${{ github.event.pull_request.base.sha }}" in source
    assert "REPOWITNESS_DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}" in source
    assert 'base_ref="${REPOWITNESS_ACTION_BASE:-${REPOWITNESS_EVENT_BASE_SHA:-${REPOWITNESS_DEFAULT_BRANCH}}}"' in source
    assert 'export REPOWITNESS_API_KEY="${REPOWITNESS_ACTION_API_KEY}"' in source
    assert '--base "${base_ref}"' in source


def test_composite_action_base_fallback_priority():
    if sys.platform == "win32":
        pytest.skip("Composite Action Bash behavior is checked on POSIX runners")

    action = (Path(__file__).parents[1] / "action.yml").read_text(
        encoding="utf-8"
    )
    assignment = next(
        line.strip()
        for line in action.splitlines()
        if line.strip().startswith('base_ref="')
    )
    cases = (
        (
            {
                "REPOWITNESS_ACTION_BASE": "explicit",
                "REPOWITNESS_EVENT_BASE_SHA": "pr-sha",
                "REPOWITNESS_DEFAULT_BRANCH": "main",
            },
            "explicit",
        ),
        (
            {
                "REPOWITNESS_ACTION_BASE": "",
                "REPOWITNESS_EVENT_BASE_SHA": "pr-sha",
                "REPOWITNESS_DEFAULT_BRANCH": "main",
            },
            "pr-sha",
        ),
        (
            {
                "REPOWITNESS_ACTION_BASE": "",
                "REPOWITNESS_EVENT_BASE_SHA": "",
                "REPOWITNESS_DEFAULT_BRANCH": "main",
            },
            "main",
        ),
    )

    for environment, expected in cases:
        completed = subprocess.run(
            ["bash", "-c", f"{assignment}\nprintf '%s' \"${{base_ref}}\""],
            env={**os.environ, **environment},
            check=True,
            capture_output=True,
            text=True,
        )
        assert completed.stdout == expected


def test_composite_action_manifest_and_shell_are_parseable():
    action = yaml.safe_load(
        (Path(__file__).parents[1] / "action.yml").read_text(encoding="utf-8")
    )
    if sys.platform == "win32":
        pytest.skip("Bash syntax is checked on POSIX GitHub runners")

    for step in action["runs"]["steps"]:
        if "run" in step:
            subprocess.run(
                ["bash", "-n"],
                input=re.sub(r"\$\{\{.*?\}\}", "expression", step["run"]),
                text=True,
                check=True,
                capture_output=True,
            )


def test_composite_action_forwards_each_check_result_to_the_shared_cli():
    action = (Path(__file__).parents[1] / "action.yml").read_text(
        encoding="utf-8"
    )

    assert "check-results:" in action
    assert "REPOWITNESS_ACTION_CHECK_RESULTS: ${{ inputs.check-results }}" in action
    assert 'check_result_args+=(--check-results "${check_result_path}")' in action
    assert '"${check_result_args[@]}"' in action


def test_composite_action_forwards_native_results_with_snapshot_provenance():
    action = (Path(__file__).parents[1] / "action.yml").read_text(
        encoding="utf-8"
    )

    assert "junit:" in action
    assert "sarif:" in action
    assert "evidence-snapshot:" in action
    assert 'native_result_args+=(--junit "${junit_path}")' in action
    assert 'native_result_args+=(--sarif "${sarif_path}")' in action
    assert '--evidence-snapshot "${REPOWITNESS_ACTION_EVIDENCE_SNAPSHOT}"' in action


def test_composite_action_updates_a_marker_bound_pr_comment():
    action = (Path(__file__).parents[1] / "action.yml").read_text(
        encoding="utf-8"
    )

    assert "comment:" in action
    assert "github-token:" in action
    assert "inputs.comment == 'true'" in action
    assert "inputs.github-token || github.token" in action
    assert "<!-- repowitness-report -->" in action
    assert "REPOWITNESS_PR_NUMBER: ${{ github.event.pull_request.number }}" in action
    assert "issues/${REPOWITNESS_PR_NUMBER}/comments" in action
    assert "issues/comments/${comment_id}" in action
    assert "--slurp" in action
    assert re.search(r"\|\s+jq -r", action)
    assert "--jq" not in action


def test_pr_workflow_runs_the_local_action_and_uploads_its_report():
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "repowitness-pr.yml"
    ).read_text(encoding="utf-8")

    assert "fetch-depth: 0" in workflow
    assert "uses: ./" in workflow
    assert "contracts-ref: base" in workflow
    assert "api-key: ${{ secrets.REPOWITNESS_API_KEY }}" in workflow
    assert "github.event.pull_request.head.repo.full_name == github.repository" in workflow
    assert "pull-requests: write" in workflow
    assert "fail-on: fail" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "steps.repowitness.outputs.report" in workflow


def test_pr_workflow_collects_snapshot_bound_deterministic_checks():
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "repowitness-pr.yml"
    ).read_text(encoding="utf-8")

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


def test_repowitness_workflow_wraps_checkout_audit_comment_and_artifact():
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "repowitness.yml"
    ).read_text(encoding="utf-8")

    assert workflow.startswith("name: RepoWitness\n")
    assert "workflow_call:" in workflow
    assert "api_key:" in workflow
    assert "required: true" in workflow
    assert "default: true" in workflow
    assert "pull-requests: write" in workflow
    assert "github.event.pull_request.head.repo.full_name == github.repository" in workflow
    assert "actions/checkout@v6" in workflow
    assert "fetch-depth: 0" in workflow
    assert "uses: Loren-ggs/RepoWitness@v0" in workflow
    assert "api-key: ${{ secrets.api_key }}" in workflow
    assert "comment: ${{ inputs.comment }}" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "steps.repowitness.outputs.report" in workflow
