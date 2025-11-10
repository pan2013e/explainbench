from dataset.extract_ground_truths.effect.get_divergent_lines import main
from tracer.serializer import serialize

def test_astropy_7166():
    expected = {'type_changes': {"root['seen_variables']['dct']['bar']['__doc__']": {'old_type': type(None), 'new_type': str, 'old_value': None, 'new_value': 'BAR'}}}
    line = main("astropy__astropy-7166", agent='gold', test_id=0, is_return=True)
    assert expected == line
    
def test_astropy_12907():    
    expected = {'values_changed': {"root['seen_variables']['cright']['values'][2][1]": {'new_value': 0.0, 'old_value': 1.0}, "root['seen_variables']['cright']['values'][3][0]": {'new_value': 0.0, 'old_value': 1.0}}}
    line = main("astropy__astropy-12907", agent='gold', test_id=0, is_return=True)
    assert expected == line

def test_astropy_7671():
    expected = {'values_changed': {"root['seen_variables']['version']": {'new_value': '0.12.0', 'old_value': '0.12.0.dev'}}}
    line = main("astropy__astropy-7671", agent='gold', test_id=0, is_return=True)
    assert expected == line
    
if __name__ == "__main__":
    try:
        test_astropy_7166()
        test_astropy_12907()
        test_astropy_7671()
        print("All tests passed")
    except Exception as e:
        print(e)