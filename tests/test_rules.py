from repowitness.domain import ChangedFile, Rule
from repowitness.rules import select_applicable_rules, select_rules


def _rule(rule_id, applies_to=(), scope_path=""):
    return Rule(
        rule_id=rule_id,
        source_span_id=f"span-{rule_id}",
        statement=f"Rule {rule_id}",
        applies_to=applies_to,
        scope_path=scope_path,
    )


def test_select_applicable_rules_respects_nested_source_scope_and_globs():
    rules = (
        _rule("root-python", ("**/*.py",)),
        _rule("api-only", ("*.py",), "src/api"),
        _rule("web-only", ("**/*.ts",), "web"),
    )
    changes = (ChangedFile(path="src/api/app.py", status="modified"),)

    selected = select_applicable_rules(rules, changes)

    assert [rule.rule_id for rule in selected] == ["root-python", "api-only"]


def test_select_applicable_rules_considers_old_rename_path():
    rules = (_rule("old-api", ("legacy/*.py",)),)
    changes = (
        ChangedFile(
            path="src/new_api.py",
            old_path="legacy/api.py",
            status="renamed",
        ),
    )

    assert select_applicable_rules(rules, changes) == rules


def test_rule_selection_explains_a_valid_pattern_excluded_from_the_diff():
    rule = _rule("docs-only", ("docs/**/*.md",))

    selection = select_rules(
        (rule,),
        (ChangedFile(path="src/app.py", status="modified"),),
        known_paths=("docs/guide/setup.md", "src/app.py"),
    )

    assert selection.applicable_rules == ()
    assert selection.decisions[0].rule_id == "docs-only"
    assert selection.decisions[0].status == "not_applicable"
    assert selection.decisions[0].reason == (
        "Declared applies_to patterns match repository files but not the "
        "current changes."
    )
