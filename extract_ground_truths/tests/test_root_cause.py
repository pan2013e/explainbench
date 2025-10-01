from extract_ground_truths.root_cause import extract_modified_files

def test_extract_modified_files():
    sample_diff = """
    diff --git a/django/http/response.py b/django/http/response.py
    --- a/django/http/response.py
    +++ b/django/http/response.py
    @@ -229,7 +229,7 @@ def make_bytes(self, value):
    if isinstance(value, str):
    return bytes(value.encode(self.charset))
    diff --git a/docs/new_feature.txt b/docs/new_feature.txt
    --- /dev/null
    +++ b/docs/new_feature.txt
    @@ -0,0 +1 @@
    +This is a new file.
    diff --git a/tests/test_old_feature.py b/tests/test_old_feature.py
    --- a/tests/test_old_feature.py
    +++ /dev/null
    """
    
    expected_filenames = set(["docs/new_feature.txt", "django/http/response.py", "tests/test_old_feature.py"])
    modified_filenames = extract_modified_files(sample_diff)
    assert set(modified_filenames) == expected_filenames
    
