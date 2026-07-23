import os
import pytest
import random

from tracer import Tracker, ExecutionTracer, ExpressionInspector

random.seed(42)
try:
    import numpy as np
    np.random.seed(42)
except ImportError:
    pass

def get_list_option(value):
    if value is None:
        return set()
    assert isinstance(value, str)
    if value.strip().lower() == 'none':
        return set()
    return set(s.strip() for s in value.split(',') if s.strip())

def validate_options(config):
    if config._disable:
        return
    assert config._output is not None, "--output must be specified when tracer is enabled"
    if config._mode == 'tracer':
        return
    if config._mode == 'inspector':
        assert config._use_tracker is False, "--use-tracker cannot be used in inspector mode"
        assert config._bp_file is not None, "--bp-file must be specified in inspector mode"
        assert config._bp_line is not None, "--bp-line must be specified in inspector mode"
        assert config._expr is not None, "--expr must be specified in inspector mode"

def pytest_addoption(parser):
    group = parser.getgroup("tracer")
    # General options
    group.addoption('--mode', choices=['tracer', 'inspector'], default='tracer')
    group.addoption('--output', default=None)
    group.addoption('--disable', action='store_true', default=False)
    # Tracer-specific options
    group.addoption('--allowed-functions', default=None)
    # Inspector-specific options
    group.addoption('--bp-file', default=None)
    group.addoption('--bp-line', type=int, default=None)
    group.addoption('--expr', default=None)
    group.addoption('--count', type=int, default=1)
    group.addoption('--inspector-mode', choices=['before', 'after'], default='before')
    group.addoption('--bp-func', default=None)
    # Tracker-specific options
    group.addoption('--use-tracker', action='store_true', default=False)
    # Optional options
    group.addoption('--test-name', default=None)
    group.addoption('--include-stdlib', default=None)

def pytest_configure(config):
    config._mode = config.getoption('--mode')
    config._output = config.getoption('--output')
    config._disable = config.getoption('--disable')
    config._allowed_functions = get_list_option(config.getoption('--allowed-functions'))
    config._bp_file = config.getoption('--bp-file')
    config._bp_line = config.getoption('--bp-line')
    config._expr = config.getoption('--expr')
    config._count = config.getoption('--count')
    config._inspector_mode = config.getoption('--inspector-mode')
    config._bp_func = config.getoption('--bp-func')
    config._use_tracker = config.getoption('--use-tracker')
    config._test_name = config.getoption('--test-name')
    config._include_stdlib = get_list_option(config.getoption('--include-stdlib'))
    try:
        validate_options(config)
    except AssertionError as e:
        raise pytest.UsageError(e)

def pytest_unconfigure(config):
    del config._mode, config._output, config._disable
    del config._allowed_functions, config._bp_file, config._bp_line
    del config._expr, config._count, config._inspector_mode, config._bp_func
    del config._use_tracker, config._test_name, config._include_stdlib

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    config = item.config
    if config._disable:
        yield
        return
    test_name = item.nodeid
    if config._test_name is not None and config._test_name != test_name:
        yield
        return
    output_file = os.path.join(config._output, "{}.jsonl".format(test_name))
    if config._mode == 'tracer':
        if config._use_tracker:
            with Tracker(
                output_file=output_file,
                include_stdlib=config._include_stdlib,
                allowed_functions=config._allowed_functions,
            ):
                yield
            return
        else:
            with ExecutionTracer(
                output_file=output_file,
                include_stdlib=config._include_stdlib,
                allowed_functions=config._allowed_functions,
            ):
                yield
            return
    if config._mode == 'inspector':
        with ExpressionInspector(
            config._bp_file,
            config._bp_line,
            config._expr,
            save_path=output_file,
            count=config._count,
            mode=config._inspector_mode,
            bp_func_name=config._bp_func,
        ):
            outcome = yield
            outcome.force_result(None)
        return
