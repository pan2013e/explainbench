from extract_ground_truths.utils import run_gumtree_diff
import os
import json

def test_run_gumtree_diff():
    left_file = "/home/yusuf/explainbench/dataset/extract_ground_truths/tests/test_gumtree/test1/hello.py"
    right_file = "/home/yusuf/explainbench/dataset/extract_ground_truths/tests/test_gumtree/test2/hello.py"
    output_file = "test.txt"
    
    output = run_gumtree_diff(
        left_file=left_file,
        right_file=right_file,
        output_file=output_file
    )
    
    assert output == True
    assert os.path.isfile(output_file)
    
    with open(output_file, 'r') as f:
        output = json.load(f)
        
    # assert "matches" in output.keys()
    # assert "actions" in output.keys()
    # assert len(output.get("actions")) == 2
    
    # os.remove(output_file)
    
    
    