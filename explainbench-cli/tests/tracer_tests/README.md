# Tracer Test Migration

The inspector files are standalone suites.
Their line numbers are part of the test behavior, so keep their source lines unchanged.
Pytest assertion rewriting changes their executable line mapping.

Run them with:

```bash
python tests/tracer_tests/inspector_mode_before_program.py
python tests/tracer_tests/inspector_mode_after_program.py
```

`serializer_program.py` is a standalone optional-dependency suite.
It expects its module name to be `__main__`.
It skips the Astropy, SymPy, and Sphinx handlers when those optional libraries are not installed.
Its socket handler needs permission to create a local socket.
Run it with:

```bash
python tests/tracer_tests/serializer_program.py
```

`tracer_program.py` is a tracing input program.
Several functions accept ordinary arguments and are not pytest test functions.
The file keeps its source content but uses a non-test filename to prevent invalid pytest fixture collection.
