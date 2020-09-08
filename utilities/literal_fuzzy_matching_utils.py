import re
import traceback
import sys

import Levenshtein as lev

from utilities import utils, logs

# NOTE in practice, we found that levenshtein distance was an adequate tool, 
# combined with spelling corrections prior to comparisons.


def compare_letters(first, second):
    """
    Compares two letters. If the first is the same as the second, returns 1.
    If the first is similar to second, based on similarity dictionaries
    inside 'tab' list, returns the similarity ratio value.
    If the first is not like the second, returns 0.
    """
    tab = [
        {"first": '1', "second": 'I', "value": 0.9},
        {"first": '1', "second": ']', "value": 0.9},
        {"first": '1', "second": '[', "value": 0.9},
        {"first": '1', "second": '|', "value": 0.9},
        {"first": '1', "second": 'J', "value": 0.5},
        {"first": '1', "second": '!', "value": 0.9},
        
        {"first": 'I', "second": ']', "value": 0.9},
        {"first": 'I', "second": '[', "value": 0.9},
        {"first": 'I', "second": '|', "value": 0.9},
        {"first": 'I', "second": 'T', "value": 0.5},
        {"first": 'I', "second": 'J', "value": 0.5},

        {"first": '2', "second": 'Z', "value": 0.9},
        {"first": '5', "second": 'S', "value": 0.9},
        {"first": '8', "second": 'g', "value": 0.5},
        {"first": '0', "second": 'O', "value": 0.9},
        {"first": '0', "second": 'Q', "value": 0.9},
        {"first": '0', "second": 'o', "value": 0.5},
        {"first": '0', "second": 'U', "value": 0.5},
        {"first": 'O', "second": 'Q', "value": 0.9},
        {"first": 'q', "second": 'g', "value": 0.9},
        {"first": 'W', "second": 'V', "value": 0.5},
        {"first": 'w', "second": 'v', "value": 0.9},
        {"first": 'E', "second": 'B', "value": 0.5},
        {"first": 'e', "second": 'a', "value": 0.5},
        {"first": 'R', "second": 'P', "value": 0.5},
        {"first": 't', "second": 'I', "value": 0.5},
        {"first": 'U', "second": 'O', "value": 0.5},
        {"first": 'o', "second": 'a', "value": 0.5},
        {"first": 'P', "second": 'F', "value": 0.5},
        {"first": 'D', "second": 'B', "value": 0.5},
        {"first": 'h', "second": 'b', "value": 0.5},
        {"first": 'V', "second": '\\', "value": 0.9},
        {"first": '.', "second": ',', "value": 0.9},
    ]
    if first == second or first.upper() == second.upper():
        return 1.0
    for rule in tab:
        if first == rule['first'] and second == rule['second'] or \
                first == rule['second'] and second == rule['first']:
            return rule['value']
    return 0.0


def compare_words(first, second):
    result = 0.0
    if len(first) > len(second):
        length_coeff = len(second) / len(first)
    else:
        length_coeff = len(first) / len(second)

    for i in enumerate(first):
        tmp = [0.0]
        for offset in range(-1, 2):
            if -1 < i[0] + offset < len(second):
                tmp.append(
                    (1.0 - abs(offset)/10.0)
                    * compare_letters(first[i[0]], second[i[0] + offset])
                )
        result += max(tmp)
    computed_result = ((result/len(first))
                       / (abs(len(first)-len(second))+1.0)) * length_coeff
    return computed_result


def match_strings(string, pool):
    result = ""
    score = 0.0
    for string_from_pool in pool:
        if compare_strings(string, string_from_pool) > score:
            result = string_from_pool
            score = compare_strings(string, string_from_pool)
    return result


def compare_strings(first, second):
    results = []
    for substring in second.split('\n'):
        result = 0.0
        for word in first.split():
            word_list = [0.0]
            for second_word in substring.split():
                word_list.append(compare_words(word, second_word))
            result = result + max(word_list)
        results.append(result / len(first.split()))
    return max(results)


# the following static variable will be updated for all calls of make_fuzzy_regex
# to avoid remaking the same string over and over, if it exists in the list.
# conversion table can have char only one time on the left side.
fuzzy_regexes = {}
chr_to_regex_list = (
    (r'Il1it', r'[I\|\[\]!1it]'),
    (r'0Oo0CcQUu', r'[0Oo0CcQUu]'),
    (r'2Zz', r'[2Zz]'),
    (r'5Ss', r'[5Ss]'),
    (r'8gq', r'[8gq]'),
    (r'Ww',  r'[WV]V?'),
    (r'EBD', r'[EBD]'),
    (r'ea',  r'[eao]'),
    (r'RPF', r'[RPF]'),
    (r'hb',  r'[hb]'),
    (r'V',   r'(V|\\/)'),
    (r'm',   r'(rn|m)'),
    (r'\:;\-\.,"', r'?')
    )


def make_fuzzy_regex(correct_str):
    """
    given an expected correct string, generate a regex expression
    that can be compared with an ocrd string to try to find a match.
    To find a multiple-character string, replace with single-char in correct_str
    returns a compiled regex
    """

    """
    Once we make a regex for a given string, remember it in  fuzzy_regexes{}
    and attempt to just look it up.
    """
    if fuzzy_regexes.get('correct_str'):
        return fuzzy_regexes['correct_str']
    
    # for multiple-char errors, we will change the two-chr version
    # to the single-char error in the correct str just for the comparison
    # Note that we do not need to look for '\/' vs. 'V' because we know
    # which string is correct.
    correct_str = re.sub('rn', 'm', correct_str)
    i = 0
    regex_of_correct = ''
    while i < len(correct_str):
        for chr_to_regex in chr_to_regex_list:
            if correct_str[i] in chr_to_regex[0]: 
                regex_of_correct += chr_to_regex[1]
                continue
        regex_of_correct += correct_str[i]

    # replace spaces with '\s*'
    re.sub(r'\s*', r'\\s*', regex_of_correct)
    fuzzy_regexes['correct_str'] = re.compile(regex_of_correct, flags=re.I | re.S)
    return regex_of_correct


def fuzzy_compare_str(correct_str, ocr_str, thres=80, justify='full', method='levdist') -> tuple:  #bool, metric
    """ 
    compare a known correct string with an ocrd string that may have mistakes.
    justify can be 'left', 'right' or 'full'
    """
    p_correct_str = correct_str.replace("\n", " ")[:50]
    p_ocr_str = ocr_str.replace("\n", " ") #[:50]
    logs.sts(f"fuzzy_compare_str justify: {justify}:\n"
             f"correct: '{p_correct_str}'\n" 
             f"ocr:     '{p_ocr_str}'") 

    if method == 'regex':
        """ This algorithm assumes no special characters in the correct string.
            and it is relatively greedy.
            first, correct string is scanned to create a regex specifier.
            then, the ocrd string is compard with the regex specified string.
        """
        regexc = make_fuzzy_regex(correct_str)
        return regexc.match(ocr_str), None
    if method == 'table':
        match_val = compare_words(correct_str, ocr_str)
        return match_val > thres, None
    if method == 'levdist':
        min_len = min(len(correct_str), len(ocr_str))
        if justify == 'left':
            local_ocr_str = ocr_str[:min_len]
            #local_cor_str = correct_str[:min_len]
        elif justify == 'right':
            local_ocr_str = ocr_str[-min_len:]
            #local_cor_str = correct_str[-min_len:]
        else:
            local_ocr_str = ocr_str
            #local_cor_str = correct_str
            
        match_val = lev.ratio(correct_str, local_ocr_str)
        lv = "%1.5f" % match_val
        logs.sts(f" levratio = {lv}", 3)       
        return match_val >= thres, match_val
        
    print(f"Logic Error: Unrecognized method:{method}\n")
    traceback.print_stack()
    sys.exit(1)


def fuzzy_compare_strlists(correct_strlist, ocr_strlist, thres, justify='full') -> tuple: # (match_bool, metric)
    """ return True if all strings match in the order given else False"""
    utils.sts("fuzzy_compare_strlists Comparing:\n" 
             f"correct: '{join_remove_nl(correct_strlist)}'\n"
             f"ocrlist: '{join_remove_nl(ocr_strlist)}'", 3)
    metric = 1.0
    
    if len(correct_strlist) != len(ocr_strlist):
        logs.exception_report(f"Mismatched strlist lengths: correct:{correct_strlist}({len(correct_strlist)}) ocr_strlist:{ocr_strlist}({len(ocr_strlist)})")
        return False, 0.0
    
    for correct_str, ocr_str in zip(correct_strlist, ocr_strlist):
    # ouch! zip function above stops when the shortest string is exhausted. Not usable here!
        flag, metric = fuzzy_compare_str(correct_str, ocr_str, thres=thres, justify=justify, method='levdist')
        if not flag:
            # can stop early if they don't match
            return flag, metric
    return True, metric
    
    
def fuzzy_metrics_str_to_list(correct_strlist: list, ocr_str: str, fuzzy_compare_mode='best_of_all') -> list:
    """ return list of float metrics of ocr_str fuzzy compared with each correct_str in correct_strlist
        tries it both right and left justified and takes the highest value.
        if ocr_str is '', always returns 0 metric.
        fuzzy_compare_mode is set for given application as either 'left_only', 'right_only', 'full_only', 'best_of_all'
    """
    metrics = []
    for correct_str in correct_strlist:
        # take only last characters of ocr_option to match correct_str, allowing slop
        
        right_metric, left_metric, full_metric = 0,0,0
        if ocr_str:
            if fuzzy_compare_mode in ['full_only', 'best_of_all']:
                _, full_metric  = fuzzy_compare_str(correct_str, ocr_str, 0, justify='full',  method='levdist')
            if fuzzy_compare_mode in ['right_only', 'best_of_all']:
                _, right_metric = fuzzy_compare_str(correct_str, ocr_str, 0, justify='right', method='levdist')
            if fuzzy_compare_mode in ['left_only', 'best_of_all']:
                _, left_metric  = fuzzy_compare_str(correct_str, ocr_str, 0, justify='left',  method='levdist')
                
            metric = max(right_metric, left_metric, full_metric)
        else:
            metric = 0
        metrics.append(metric)
    return metrics
    
        
def fuzzy_compare_str_to_list(correct_strlist: list, ocr_str: str, thres: float, fuzzy_compare_mode='best_of_all') -> tuple:
    """ return True if ocr_str is found in correct_strlist
        with index offset where it is found, and metric.
    """
    utils.sts(f"Comparing strlists\ncorrect '{join_remove_nl(correct_strlist)}'\n"
                                  f"ocr_str '{ocr_str}'", 3)
    metrics = fuzzy_metrics_str_to_list(correct_strlist, ocr_str, fuzzy_compare_mode)

    if not metrics:
        return False, 0, 0
        
    # note that we can't just sort the metrics here because we need to keep them in order.
    max_metric = max(metrics)
    max_idx = metrics.index(max_metric)
    
    if len(metrics) > 1:
        metrics.sort(reverse=True)
        if (metrics[0] > 0.7) and (metrics[0] - metrics[1] < 0.3):
            string = f"Close fuzzy discrimination: max_metric:{metrics[0]} next_metric:{metrics[1]}\n" \
                     f"ocr_str:{ocr_str} correct_strlist:{', '.join(correct_strlist)}"
            utils.exception_report(string)

    return bool(max_metric > thres), max_idx, max_metric


def join_remove_nl(correct_strlist):
    """ Create a string suitable for log and console display """
    return re.sub("\n", ' ', ','.join(correct_strlist))#[:50]

def invert_idx_list(idx_list: list) -> list:
    """ given list of indexes, return the list "inverted", where
        in the initial list, the nth position idx is 
        returned as n in the idx'th position.
        [4,1,0,3,2] will become [2,1,4,3,0]
        if idxs are unique and in range, then two inversion return the original
    """    
    num_vals = len(idx_list)
    result_list = [None for x in range(num_vals)]
    for idx, val in enumerate(idx_list):
        if val < num_vals:
            result_list[int(val)] = idx
    return result_list

assert invert_idx_list([4,1,0,3,2]) == [2,1,4,3,0]
assert invert_idx_list([2,1,4,3,0]) == [4,1,0,3,2]

def fuzzy_compare_permuted_strsets(correct_strlist, ocr_strlist, thres, fuzzy_compare_mode='best_of_all') -> tuple:
    """ compare sets of strings in all possible permutations and return the first match of all components.
        returns tuple:
            bool    -- True if mapping meets threshold, and then map is provided.
            metric  -- minimum metric of the best mapping or first failing metric
            map     -- list of indexes of the correct_strlist that match the given order of the ocr_str_list
        resulting permutation list provide selected correct_strlist for given ocr_strlist
        True, max_metric, permutations_listoflist[best_permutation_idx]
    """
    """
        Prior algorithm was O(n!) and has been rewritten
        New algorithm should NOT calculate all the permutations, as even with only 5 options 120 mappings just be checked.
        6, 720 7, 5040; 8, 40320 cases. So this algorithm will never complete with just a dozen candidates (results in 479 million cases).
        
        INSTEAD:
            Can change to this algorithm which is O(n**2) 
        
        Each ocr_item, ocr_item should be compared with each correct_str
            create a table of fuzzy comparison metrics a row at a time.
            if any row of metrics has no item that reaches the threshold, can return immediately.
            this table can simply be a list of lists.
        
                            correct_str items
                |--------------------------------------------
        ocr_item|   0       1       2        3   ...     n-1
            0   | m[0][0] m[0][1]
            1   | m[1][0] ...
            2   | ...
           ...  |
           n-1  |
                |--------------------------------------------
        
        Then, process the array to choose the best match of each correct_str item with each ocr_item
        
        take each row, locate max_metric in the row. It should also be the best match in the column.
        return list of indexes of correct_str item that matches each ocr_item.
        record an exception if max metric of each row is not also the max metric of each column.
        
        For example, 
        assert fuzzy_compare_permuted_strsets(['Bill','John','Gary','Mary','William'], ['William','John,'Bill','Mary','Gary'], 0.9) == (True, 1.0, [4,1,0,3,2])
        
        ocr_metrics_table =
        
        [0,0,0,0,1] 4
        [0,1,0,0,0] 1
        [1,0,0,0,0] 0
        [0,0,0,1,0] 3
        [0,0,1,0,0] 2
        
         2,1,4,3,0  <- max_col_idxs
         
        then invert_idx_list(max_col_idxs) == idx_list
        
        THIS CAN BE FURTHER IMPROVED if necessary:
        This function is used in the mapping the ocr strings from rois to contests and options.
        The frame is slid down if a match is not found. If that occurs, then the existing metric matrix
        can be used again by sliding it one notch as well.
        
        PROPOSED IMPROVEMENT:
        For a given correct_strlist, save the map. If the function is invoked with the same correct_strlist, 
        try the saved map. If it matches use it. if not, continue with full analysis.
        

    """
    """
    DEPRECATED code
    permutations_listoflist = list(itertools.permutations(range(len(correct_strlist))))
    # this provides the permutations of the indexes of the options which should be searched between the two lists
    matching_permutations = []
    matching_permutation_metrics = []
    permutation_metrics = []
    for permutation_list in permutations_listoflist:
        # following sort of thing works in R but not in python.
        permuted_correct_strlist = []
        for i in permutation_list:
            permuted_correct_strlist.append(correct_strlist[i])
        
        flag, metric = fuzzy_compare_strlists(permuted_correct_strlist, ocr_strlist, thres)
        if metric == 1.0:
            # if we find an exact match, return immediately with that permutation
            return True, metric, permutation_list
        if flag:
            matching_permutations.append(permutation_list)
            matching_permutation_metrics.append(metric)
        permutation_metrics.append(metric)
    
    max_metric = max(permutation_metrics)
    if not len(matching_permutations):
        # no matches, can deal with that quickly.
        return False, max_metric, []
    if len(matching_permutations) == 1:
        return True, matching_permutation_metrics[0], matching_permutations[0]
    # more than one match, but none exact. return the best match
    best_permutation_idx = permutation_metrics.index(max_metric)
    return True, max_metric, permutations_listoflist[best_permutation_idx]
    """
    
    #import pdb; pdb.set_trace()
    ocr_metrics_table = []
    max_idxs = []
    max_metrics = []
    for ocr_str in ocr_strlist:
        ocr_metrics_list = fuzzy_metrics_str_to_list(correct_strlist, ocr_str, fuzzy_compare_mode)
        max_metric = max(ocr_metrics_list)
        max_idx = ocr_metrics_list.index(max_metric)
        if max_metric < thres:
            return False, max_metric, []                # return early if ocr_str cannot be found in correct_strlist
        max_idxs.append(max_idx)
        max_metrics.append(max_metric)
        ocr_metrics_table.append(ocr_metrics_list)      # create list of list.
    
    max_col_idxs = []
    for idx in range(len(correct_strlist)):
        metrics_by_col = [a[idx] for a in ocr_metrics_table]    # get the idx'th column
        max_metric_by_col = max(metrics_by_col)
        max_idx_by_col = metrics_by_col.index(max_metric_by_col)
        max_col_idxs.append(max_idx_by_col)
        
    inverted_col_idxs = invert_idx_list(max_col_idxs)
    
    if not max_idxs == inverted_col_idxs:
        utils.exception_report(f"### EXCEPTION: fuzzy_compare_permuted_strsets: correct_strlist:{correct_strlist}\n"
            f"cannot be mapped to ocr_strlist {ocr_strlist}\n"
            f"maxes of rows not maxes of cols.\n")
        return False, 0, []
        
    return True, min(max_metrics), max_idxs
    

def test_fuzzy_compare_permuted_strsets():
    result = fuzzy_compare_permuted_strsets(['Bill','John','Gary','Mary','William'], ['William','John','Bill','Mary','Gary'], 0.9)
    if not result == (True, 1.0, [4,1,0,3,2]):
        utils.exception_report("test_fuzzy_compare_permuted_strsets error")
    
