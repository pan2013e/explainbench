from dataclasses import dataclass

@dataclass
class FunctionInfo():
    file: str
    class_name: str | None
    func_name: str

    @property
    def full_name(self) -> str:
        class_name = "" if self.class_name is None else self.class_name
        long_name = self.file.removesuffix(".py").replace("/", ".")
        long_name += "." + class_name + "." + self.func_name
        return long_name

@dataclass
class IOInfo():
    input_values: str
    output_value: str

    def to_dict(self) -> dict[str, str]:
        return {
            "input_values": self.input_values,
            "output_value": self.output_value,
        }