#   self_test

from utilities.barcode_parser import test_get_parsed_barcode
from utilities.vendor import test_dominion_build_effective_style_num
from utilities.literal_fuzzy_matching_utils import test_fuzzy_compare_permuted_strsets
    
def self_test(argsdict: dict):

    test_get_parsed_barcode()
    test_dominion_build_effective_style_num(argsdict)
    test_fuzzy_compare_permuted_strsets()