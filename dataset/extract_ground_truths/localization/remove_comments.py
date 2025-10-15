import os
import ast
from typing import List
from tqdm import tqdm

class DocstringReplacer(ast.NodeTransformer):
    """
    An AST visitor that replaces docstrings with a placeholder.
    It visits every Function, Class, and Module node, checks for a docstring,
    and if one is found, replaces it with ast.Expr(ast.Constant(value="Docstring")).
    """
    def _replace_docstring_if_present(self, node):
        """Helper to check for and replace a docstring on a given node."""
        if (node.body and
                isinstance(node.body[0], ast.Expr) and
                isinstance(node.body[0].value, ast.Constant) and
                isinstance(node.body[0].value.value, str)):
            node.body[0] = ast.Expr(value=ast.Constant(value="Docstring"))

        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node):
        return self._replace_docstring_if_present(node)

    def visit_AsyncFunctionDef(self, node):
        return self._replace_docstring_if_present(node)

    def visit_ClassDef(self, node):
        return self._replace_docstring_if_present(node)
        
    def visit_Module(self, node):
        return self._replace_docstring_if_present(node)


def remove_comments_and_docstrings(source: str) -> str:
    """
    Removes all comments and replaces all docstrings in a Python source string.
    """
    try:
        tree = ast.parse(source)

        transformer = DocstringReplacer()
        new_tree = transformer.visit(tree)
        
        ast.fix_missing_locations(new_tree)

        return ast.unparse(new_tree)
    except (SyntaxError, ValueError):
        return source

def collect_py_files(input_dir: str)->List[str]:
    py_files = []
    for root, dirs, files in os.walk(input_dir):
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))
    return py_files

def main():
    """
    Reads file paths from a JSONL file, cleans the Python code in each file
    by removing comments and docstrings, and writes the cleaned code back
    to the original file.
    """
    PATH = "/home/yusuf/explainbench/dataset/extract_ground_truths/localization/swe_bench_files"
    py_files = collect_py_files(PATH)
    
    if not os.path.exists(PATH):
        print(f"Error: The input file was not found at {PATH}")
        return

    parsable_count = 0
    unparsable_count = 0
    files_processed_count = 0
    for temp_path in tqdm(py_files, desc="Cleaning files", unit="file"):
        try:
            with open(temp_path, "r", encoding="utf-8") as f1:
                code = f1.read()

            cleaned_code = remove_comments_and_docstrings(code)
            try:
                ast.parse(cleaned_code)
                
                parsable_count += 1
                
                with open(temp_path, "w", encoding="utf-8") as f1:
                    f1.write(cleaned_code)

            except SyntaxError as se:
                unparsable_count += 1
                tqdm.write(f"    CRITICAL ERROR: Generated code for {temp_path} is invalid and will NOT be saved.")
                tqdm.write(f"    Parser error: {se}")
        except Exception as e:
            tqdm.write(f"    ERROR processing file {temp_path}: {e}")

    print("Processing complete.")
    print("\n--- Verification Summary ---")
    print(f"Total files attempted: {files_processed_count}")
    print(f"Successfully verified and written: {parsable_count} files")
    print(f"Failed verification (invalid code generated): {unparsable_count} files")


if __name__ == "__main__":
    main()