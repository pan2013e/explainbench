import os
import sys
import random
import threading

from tracer import Tracker, ExecutionTracer, ExpressionInspector

random.seed(42)
try:
    import numpy as np
    np.random.seed(42)
except ImportError:
    pass

_state = threading.local()

FAIL_TO_PASS_TESTS = {
    "sympy__sympy-11618": [
        "test_issue_11617"
    ],
    "sympy__sympy-12096": [
        "test_issue_12092"
    ],
    "sympy__sympy-12419": [
        "test_Identity"
    ],
    "sympy__sympy-12481": [
        "test_args"
    ],
    "sympy__sympy-12489": [
        "test_Permutation_subclassing"
    ],
    "sympy__sympy-13031": [
        "test_sparse_matrix"
    ],
    "sympy__sympy-13091": [
        "test_equality",
        "test_comparisons_with_unknown_type"
    ],
    "sympy__sympy-13372": [
        "test_evalf_bugs"
    ],
    "sympy__sympy-13480": [
        "test_coth"
    ],
    "sympy__sympy-13551": [
        "test_issue_13546"
    ],
    "sympy__sympy-13615": [
        "test_Complement"
    ],
    "sympy__sympy-13647": [
        "test_col_insert"
    ],
    "sympy__sympy-13757": [
        "test_issue_13079"
    ],
    "sympy__sympy-13798": [
        "test_latex_basic"
    ],
    "sympy__sympy-13852": [
        "test_polylog_values"
    ],
    "sympy__sympy-13877": [
        "test_determinant"
    ],
    "sympy__sympy-13878": [
        "test_arcsin"
    ],
    "sympy__sympy-13974": [
        "test_tensor_product_simp"
    ],
    "sympy__sympy-14248": [
        "test_MatrixElement_printing",
        "test_MatrixSymbol_printing"
    ],
    "sympy__sympy-14531": [
        "test_python_relational",
        "test_Rational"
    ],
    "sympy__sympy-14711": [
        "test_Vector"
    ],
    "sympy__sympy-14976": [
        "test_MpmathPrinter"
    ],
    "sympy__sympy-15017": [
        "test_ndim_array_initiation"
    ],
    "sympy__sympy-15345": [
        "test_Function"
    ],
    "sympy__sympy-15349": [
        "test_quaternion_conversions"
    ],
    "sympy__sympy-15599": [
        "test_Mod"
    ],
    "sympy__sympy-15809": [
        "test_Min",
        "test_Max"
    ],
    "sympy__sympy-15875": [
        "test_Add_is_zero"
    ],
    "sympy__sympy-15976": [
        "test_presentation_symbol"
    ],
    "sympy__sympy-16450": [
        "test_posify"
    ],
    "sympy__sympy-16597": [
        "test_infinity",
        "test_neg_infinity",
        "test_other_symbol"
    ],
    "sympy__sympy-16766": [
        "test_PythonCodePrinter"
    ],
    "sympy__sympy-16792": [
        "test_ccode_unused_array_arg"
    ],
    "sympy__sympy-16886": [
        "test_encode_morse"
    ],
    "sympy__sympy-17139": [
        "test__TR56",
        "test_issue_17137"
    ],
    "sympy__sympy-17318": [
        "test_issue_12420"
    ],
    "sympy__sympy-17630": [
        "test_issue_17624",
        "test_zero_matrix_add"
    ],
    "sympy__sympy-17655": [
        "test_point",
        "test_point3D"
    ],
    "sympy__sympy-18189": [
        "test_diophantine"
    ],
    "sympy__sympy-18199": [
        "test_solve_modular"
    ],
    "sympy__sympy-18211": [
        "test_issue_18188"
    ],
    "sympy__sympy-18698": [
        "test_factor_terms"
    ],
    "sympy__sympy-18763": [
        "test_latex_subs"
    ],
    "sympy__sympy-19040": [
        "test_issue_5786"
    ],
    "sympy__sympy-19346": [
        "test_dict"
    ],
    "sympy__sympy-19495": [
        "test_subs_CondSet"
    ],
    "sympy__sympy-19637": [
        "test_kernS"
    ],
    "sympy__sympy-19783": [
        "test_dagger_mul",
        "test_identity"
    ],
    "sympy__sympy-19954": [
        "test_sylow_subgroup"
    ],
    "sympy__sympy-20154": [
        "test_partitions",
        "test_uniq"
    ],
    "sympy__sympy-20428": [
        "test_issue_20427"
    ],
    "sympy__sympy-20438": [
        "test_Eq",
        "test_issue_19378"
    ],
    "sympy__sympy-20590": [
        "test_immutable"
    ],
    "sympy__sympy-20801": [
        "test_zero_not_false"
    ],
    "sympy__sympy-20916": [
        "test_super_sub"
    ],
    "sympy__sympy-21379": [
        "test_Mod"
    ],
    "sympy__sympy-21596": [
        "test_imageset_intersect_real"
    ],
    "sympy__sympy-21612": [
        "test_Mul"
    ],
    "sympy__sympy-21847": [
        "test_monomials"
    ],
    "sympy__sympy-21930": [
        "test_create",
        "test_commutation",
        "test_create_f",
        "test_NO",
        "test_Tensors",
        "test_issue_19661"
    ],
    "sympy__sympy-22080": [
        "test_create_expand_pow_optimization",
        "test_PythonCodePrinter",
        "test_empty_modules"
    ],
    "sympy__sympy-22456": [
        "test_String"
    ],
    "sympy__sympy-22714": [
        "test_issue_22684"
    ],
    "sympy__sympy-22914": [
        "test_PythonCodePrinter"
    ],
    "sympy__sympy-23262": [
        "test_issue_14941"
    ],
    "sympy__sympy-23413": [
        "test_hermite_normal"
    ],
    "sympy__sympy-23534": [
        "test_symbols"
    ],
    "sympy__sympy-23824": [
        "test_kahane_simplify1"
    ],
    "sympy__sympy-23950": [
        "test_as_set"
    ],
    "sympy__sympy-24066": [
        "test_issue_24062"
    ],
    "sympy__sympy-24213": [
        "test_issue_24211"
    ],
    "sympy__sympy-24443": [
        "test_homomorphism"
    ],
    "sympy__sympy-24539": [
        "test_PolyElement_as_expr"
    ],
    "sympy__sympy-24562": [
        "test_issue_24543"
    ],
    "sympy__sympy-24661": [
        "test_issue_24288"
    ]
}

def _get_allowed_functions():
    value = os.getenv("TRACER_ALLOWED_FUNCTIONS", "")
    if not value:
        return set()
    assert isinstance(value, str)
    if value.strip().lower() == 'none':
        return set()
    return set(s.strip() for s in value.split(',') if s.strip())

ALLOWED_FUNCTIONS = _get_allowed_functions()

def _looks_like_sympy_test(frame):
    co = frame.f_code
    if not co.co_name.startswith("test_"):
        return None
    fn = (co.co_filename or "").replace("\\", "/")
    if "/sympy/" in fn and "/tests/" in fn and "/test_" in fn and fn.endswith(".py"):
        instance_id = os.environ.get("INSTANCE_ID", "NA")
        fail_to_pass = FAIL_TO_PASS_TESTS.get(instance_id, [])
        if any(co.co_name == test_name for test_name in fail_to_pass):
            return co.co_name
    return None

def _profile_tracer(frame, event, arg):
    st = getattr(_state, "stack", None)
    if st is None:
        _state.stack = st = []
        _state.active = False
        _state.tid = None
        _state.tracer = None
    if event == "call":
        if not _state.active:
            tid = _looks_like_sympy_test(frame)
            if tid:
                _state.active = True
                _state.tid = tid
                _state.tracer = ExecutionTracer(
                    output_file=os.path.join(os.environ.get('TRACER_OUTPUT_DIR'), "{}.jsonl".format(tid)),
                    include_stdlib=None,
                    allowed_functions=ALLOWED_FUNCTIONS,
                )
                st.append("root")
                _state.tracer.start_tracing()
                _state.tracer._handle_call_event(frame, _state.tracer._get_function_info(frame))
                frame.f_trace = _state.tracer._trace_function
                return
        if _state.active:
            st.append("call")
    elif event == "return" and _state.active:
        if st:
            st.pop()
        if not st:
            _state.tracer.stop_tracing()
            try:
                _state.tracer.save_trace()
            except Exception as e:
                print("Failed to save trace to {}: {}".format(_state.tracer.output_file, e), file=sys.stderr, flush=True)
            _state.active = False
            _state.tid = None
            _state.tracer = None
        return

def _profile_inspector(frame, event, arg):
    st = getattr(_state, "stack", None)
    if st is None:
        _state.stack = st = []
        _state.active = False
        _state.tid = None
        _state.inspector = None
    if event == "call":
        if not _state.active:
            tid = _looks_like_sympy_test(frame)
            if tid:
                _state.active = True
                _state.tid = tid
                _state.inspector = ExpressionInspector(
                    bp_file=os.environ.get('INSPECTOR_BP_FILE'),
                    bp_line=int(os.environ.get('INSPECTOR_BP_LINE')),
                    expr=os.environ.get('INSPECTOR_EXPR'),
                    save_path=os.path.join(os.environ.get('INSPECTOR_OUTPUT_DIR'), "{}.jsonl".format(tid)),
                    count=int(os.environ.get('INSPECTOR_COUNT')),
                    mode=os.environ.get('INSPECTOR_MODE'),
                    bp_func_name=os.environ.get('INSPECTOR_BP_FUNC'),
                )
                st.append("root")
                _state.inspector.set_trace()
                return
        if _state.active:
            st.append("call")
    elif event == "return" and _state.active:
        if st:
            st.pop()
        if not st:
            _state.inspector.save_result()
            _state.active = False
            _state.tid = None
            _state.inspector = None
        return

def _profile_tracker(frame, event, arg):
    st = getattr(_state, "stack", None)
    if st is None:
        _state.stack = st = []
        _state.active = False
        _state.tid = None
        _state.tracer = None
    if event == "call":
        if not _state.active:
            tid = _looks_like_sympy_test(frame)
            if tid:
                _state.active = True
                _state.tid = tid
                _state.tracer = Tracker(
                    output_file=os.path.join(os.environ.get('TRACER_OUTPUT_DIR'), "{}.jsonl".format(tid)),
                    include_stdlib=None,
                    allowed_functions=ALLOWED_FUNCTIONS,
                )
                st.append("root")
                _state.tracer.start_tracing()
                _state.tracer._handle_call_event(frame, _state.tracer._get_function_info(frame))
                frame.f_trace = _state.tracer._trace_function
                return
        if _state.active:
            st.append("call")
    elif event == "return" and _state.active:
        if st:
            st.pop()
        if not st:
            _state.tracer.stop_tracing()
            try:
                _state.tracer.save_trace()
            except Exception as e:
                print("Failed to save trace to {}: {}".format(_state.tracer.output_file, e), file=sys.stderr, flush=True)
            _state.active = False
            _state.tid = None
            _state.tracer = None
        return

def _install_tracer():
    sys.setprofile(_profile_tracer)
    try:
        threading.setprofile(_profile_tracer)
    except Exception:
        pass

def _install_inspector():
    sys.setprofile(_profile_inspector)
    try:
        threading.setprofile(_profile_inspector)
    except Exception:
        pass

def _install_tracker():
    sys.setprofile(_profile_tracker)
    try:
        threading.setprofile(_profile_tracker)
    except Exception:
        pass

if __name__ == "__main__":
    enable_tracer = os.environ.get("ENABLE_TRACER", "0") == "1"
    enable_inspector = os.environ.get("ENABLE_INSPECTOR", "0") == "1"
    enable_tracker = os.environ.get("ENABLE_TRACKER", "0") == "1"
    if enable_tracer + enable_inspector + enable_tracker > 1:
        raise RuntimeError("Cannot enable more than one of tracer, inspector, and tracker")
    if enable_tracer:
        _install_tracer()
    elif enable_inspector:
        _install_inspector()
    elif enable_tracker:
        _install_tracker()
