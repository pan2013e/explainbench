import os
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

REPR_PATTERN = re.compile(r'<(?P<object>.+?)(?:\s+at\s+)?(?:0x|x)[0-9a-fA-F]+>')
TIMESTAMP_PATTERN = re.compile(
    r'\b\d{4}-\d{2}-\d{2} '
    r'\d{2}:\d{2}:\d{2}'
    r'(?:\.\d{1,6})?\b'
)

def sanitize_exc_msg(value: str) -> str:
    def _strip_address(match: re.Match) -> str:
        return f"<{match.group('object')}>"

    value = REPR_PATTERN.sub(_strip_address, value)
    value = TIMESTAMP_PATTERN.sub("<timestamp>", value)
    return value

def sanitize_seen_variables(obj: Any) -> Any:
    def _strip_address(match: re.Match) -> str:
        return f"<{match.group('object')}>"
    
    if isinstance(obj, dict):
        cleaned: Dict[Any, Any] = {}
        for key, value in obj.items():
            cleaned[key] = sanitize_seen_variables(value)
        return cleaned
    if isinstance(obj, list):
        return [sanitize_seen_variables(item) for item in obj]
    if isinstance(obj, str):
        if obj.startswith("<") and obj.endswith(">"): # short-circuit to speed up
            return REPR_PATTERN.sub(_strip_address, obj)
    return obj

def _is_pure_number_key(key: Any) -> bool:
    if isinstance(key, int):
        return True
    if isinstance(key, str):
        return key.isdigit()
    return False

def drop_numeric_keys(obj: Any) -> Any:
    if isinstance(obj, dict):
        cleaned: Dict[Any, Any] = {}
        for key, value in obj.items():
            if _is_pure_number_key(key):
                continue
            cleaned[key] = drop_numeric_keys(value)
        return cleaned
    if isinstance(obj, list):
        return [drop_numeric_keys(item) for item in obj]
    return obj

VOLATILE_STATE_KEYS = {"_cid_gen", "_id_gen", "_counter", "_next_id"}

def scrub_py_state(obj: Any) -> Any:
    if isinstance(obj, dict):
        if "py/state" in obj and isinstance(obj["py/state"], dict):
            for k in VOLATILE_STATE_KEYS:
                obj["py/state"].pop(k, None)
        return {k: scrub_py_state(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_py_state(v) for v in obj]
    return obj

class Event(BaseModel):
    event_id: int
    event_type: str
    line_number: int
    statement: str
    filepath: str
    function_name: str
    excluded: bool = False
    
    @staticmethod
    def from_dict(data):
        event_type = data['event_type']
        if event_type == 'Function':
            event = FunctionEvent(**data)
            return event
        elif event_type == 'Return':
            event = ReturnEvent(**data)
            return event
        elif event_type == 'Exception':
            return ExceptionEvent(**data)
        elif event_type == 'Line':
            event = LineEvent(**data)
            return event
        else:
            raise ValueError(f"Unknown event type: {event_type}")

    def matches(self, other):
        if not isinstance(other, Event):
            return False
        if isinstance(self, FunctionEvent) and isinstance(other, FunctionEvent):
            return self.function_name == other.function_name
        return (self.event_type == other.event_type and
                self.statement == other.statement and
                self.function_name == other.function_name)

    def dump(self):
        return self.model_dump(exclude={
            "event_id", "event_type", "line_number", "statement", "excluded",
        })

class FunctionEvent(Event):
    caller_name: str
    parameters: Dict[str, Any]
    parameter_sources: Dict
    inherited_control_dependencies: List[int]

    def dump(self):
        return self.model_dump(exclude={
            "event_id", "event_type", "line_number", "statement", "excluded",
            "inherited_control_dependencies",
        })

class ReturnEvent(Event):
    vars_used: List[str]
    caller_name: str
    return_value: Any

    def dump(self):
        copied = self.model_copy()
        if copied.return_value:
            copied.return_value = drop_numeric_keys(copied.return_value)
            copied.return_value = sanitize_seen_variables(copied.return_value)
        return copied.model_dump(exclude={
            "event_id", "event_type", "line_number", "statement", "excluded",
            "vars_used", "caller_name",
        })

class ExceptionEvent(Event):
    exception_type: str
    exception_value: str
    vars_used: Optional[List[str]] = None

    def dump(self):
        copied = self.model_copy(update={"exception_value": sanitize_exc_msg(self.exception_value)})
        return copied.model_dump(exclude={
            "event_id", "event_type", "line_number", "statement", "excluded",
            "vars_used",
        })

class LineEvent(Event):
    vars_defined: List[str]
    vars_used: List[str]
    control_dependencies: List[int]
    inherited_control_dependencies: List[int]
    seen_variables: Dict[str, Any]

    def dump(self):
        if self.function_name.startswith("sklearn"):
            obj = self.model_copy()
            if "cachedir" in obj.seen_variables:
                obj.seen_variables["cachedir"] = "<tmpdir>"
        elif self.function_name.endswith("AdminScriptTestCase.write_settings"):
            obj = self.model_copy()
            if "settings_file_path" in obj.seen_variables:
                var = obj.seen_variables["settings_file_path"]
                obj.seen_variables["settings_file_path"] = os.path.join("<tmpdir>", os.path.basename(var))
            if "settings_file" in obj.seen_variables:
                var = obj.seen_variables["settings_file"]
                if var and "name" in var:
                    obj.seen_variables["settings_file"]["name"] = os.path.join("<tmpdir>", os.path.basename(var["name"]))
        elif self.function_name.endswith("AdminScriptTestCase.run_manage"):
            obj = self.model_copy()
            if "test_manage_py" in obj.seen_variables:
                var = obj.seen_variables["test_manage_py"]
                obj.seen_variables["test_manage_py"] = os.path.join("<tmpdir>", os.path.basename(var))
            if "fp" in obj.seen_variables:
                var = obj.seen_variables["fp"]
                if var and "name" in var:
                    obj.seen_variables["fp"]["name"] = os.path.join("<tmpdir>", os.path.basename(var["name"]))
        elif self.function_name.endswith("AdminScriptTestCase.run_test"):
            obj = self.model_copy()
            if "base_dir" in obj.seen_variables:
                obj.seen_variables["base_dir"] = "<tmpdir>"
            if "settings_file" in obj.seen_variables:
                var = obj.seen_variables["settings_file"]
                if var and "name" in var:
                    obj.seen_variables["settings_file"]["name"] = os.path.join("<tmpdir>", os.path.basename(var["name"]))
            if "test_environ" in obj.seen_variables:
                del obj.seen_variables["test_environ"]
            if "python_path" in obj.seen_variables:
                obj.seen_variables["python_path"][0] = "<tmpdir>"
        elif self.function_name.endswith("Command.collect"):
            obj = self.model_copy()
            if "found_files" in obj.seen_variables:
                del obj.seen_variables["found_files"]
        elif self.function_name.endswith("AppConfig.default_auto_field"):
            obj = self.model_copy()
            if "settings" in obj.seen_variables:
                var = obj.seen_variables["settings"]
                if var and "STATIC_ROOT" in var:
                    obj.seen_variables["settings"]["STATIC_ROOT"] = "<tmpdir>"
        elif self.function_name.endswith("Command.handle"):
            obj = self.model_copy()
            if "destination_path" in obj.seen_variables:
                obj.seen_variables["destination_path"] = "<tmpdir>"
            if "message" in obj.seen_variables:
                var = obj.seen_variables["message"]
                if isinstance(var, list) and len(var) > 2:
                    obj.seen_variables["message"][2] = ":\n\n    <tmpdir>\n\n"
        elif self.function_name.endswith("Field.__deepcopy__"):
            obj = self.model_copy()
            if "memodict" in obj.seen_variables:
                del obj.seen_variables["memodict"]
        elif self.function_name.endswith("Catalog.__iter__"):
            obj = self.model_copy()
            if "uuids" in obj.seen_variables:
                del obj.seen_variables["uuids"]
        elif self.function_name.endswith("_pytest.runner:pytest_runtest_call"):
            obj = self.model_copy()
            if "e" in obj.seen_variables:
                try:
                    var = obj.seen_variables["e"]['py/reduce'][1]['py/tuple'][0]
                    if isinstance(var, str):
                        obj.seen_variables["e"]['py/reduce'][1]['py/tuple'][0] = sanitize_exc_msg(var)
                except KeyError:
                    pass
            if "value" in obj.seen_variables:
                try:
                    var = obj.seen_variables["value"]['py/reduce'][1]['py/tuple'][0]
                    if isinstance(var, str):
                        obj.seen_variables["value"]['py/reduce'][1]['py/tuple'][0] = sanitize_exc_msg(var)
                except KeyError:
                    pass
        elif self.function_name.endswith("test_mark_mro"):
            obj = self.model_copy()
            if "get_unpacked_marks" in obj.seen_variables:
                del obj.seen_variables["get_unpacked_marks"]
        elif self.function_name.endswith("test_raises_for_invalid_status"):
            obj = self.model_copy()
            if "server_thread" in obj.seen_variables:
                var = obj.seen_variables["server_thread"]
                if "_ident" in var:
                    obj.seen_variables["server_thread"]["_ident"] = "<thread_ident>"
                if "_native_id" in var:
                    obj.seen_variables["server_thread"]["_native_id"] = "<native_thread_id>"
        elif self.function_name.endswith("Builder.read_doc"):
            obj = self.model_copy()
            try:
                del obj.seen_variables['doctree']['py/state']['settings']['env']['py/state']['all_docs']['index']
            except KeyError:
                pass
        elif self.function_name.endswith("DefaultSubstitutions.apply"):
            obj = self.model_copy()
            if "to_handle" in obj.seen_variables:
                if isinstance(obj.seen_variables["to_handle"], list):
                    obj.seen_variables["to_handle"] = sorted(obj.seen_variables["to_handle"])
        elif self.function_name.endswith("TestDataset.test_chunks_does_not_load_data"):
            obj = self.model_copy()
            if "store" in obj.seen_variables:
                del obj.seen_variables["store"]
        elif self.function_name.endswith("CDS._make_parser"):
            obj = self.model_copy()
            if "p_division_of_units" in obj.seen_variables:
                var = obj.seen_variables["p_division_of_units"]
                if "__doc__" in var:
                    obj.seen_variables["p_division_of_units"]["__doc__"] = "<docstring>"
        elif self.function_name.endswith("Store.get") or self.function_name.endswith("Store.__getitem__") or self.function_name.endswith("Store.__setitem__"):
            obj = self.model_copy()
            if "self" in obj.seen_variables:
                var = obj.seen_variables["self"]
                if "_store" in var and isinstance(var["_store"], dict):
                    obj.seen_variables["self"]["_store"] = {sanitize_exc_msg(str(k)): v for k, v in var["_store"].items()}
        else:
            obj = self
        if obj.seen_variables:
            obj.seen_variables = drop_numeric_keys(obj.seen_variables)
            obj.seen_variables = scrub_py_state(obj.seen_variables)
            obj.seen_variables = sanitize_seen_variables(obj.seen_variables)
        return obj.model_dump(exclude={
            "event_id", "event_type", "line_number", "statement", "excluded",
            "vars_defined", "vars_used",
            "control_dependencies", "inherited_control_dependencies",
        })

class InspectionException(BaseModel):
    stage: str
    type: Optional[str]
    message: Optional[str]
    traceback: Optional[List[str]]

class InspectionResult(BaseModel):
    file: str
    line: int
    expr: List[str]
    value: Optional[List[Any]]
    exception: InspectionException | List[Optional[InspectionException]]
