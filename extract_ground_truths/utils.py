def remove_indentation(input_text: str) -> str:
    """
    Removes leading spaces and tabs from each line in the input text.
    """
    lines = input_text.splitlines()
    stripped_lines = [line.lstrip() for line in lines]
    return "\n".join(stripped_lines)