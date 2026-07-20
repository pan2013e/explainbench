from explainbench.question_builders.local.stages.validate_candidate_expressions import (
    compute_expression_changes,
    expression_value_changed,
)


def test_compute_expression_changes_preserves_expression_order_and_rules():
    buggy = {
        "expr": ["same", "changed", "introduced"],
        "value": [1, 2, None],
        "exception": [None, None, {"stage": "evaluation", "type": "NameError"}],
    }
    patched = {
        "expr": ["same", "changed", "introduced"],
        "value": [1, 3, 4],
        "exception": [None, None, None],
    }

    assert compute_expression_changes(patched, buggy) == {
        "same": False,
        "changed": True,
        "introduced": True,
    }


def test_none_value_without_expected_evaluation_error_is_not_a_change():
    assert expression_value_changed(None, None, 4, None) is False
    assert expression_value_changed(
        None,
        {
            "stage": "evaluation",
            "type": "AttributeError",
            "message": "'NoneType' object has no attribute 'value'",
        },
        4,
        None,
    ) is True

