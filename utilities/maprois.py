import sys
import re
#import os
#import math
#import csv
#import json
#import ntpath
#from io import StringIO

import pandas as pd
#import boto3
import pprint

from utilities.cvr_utils import create_contests_dod
from utilities.literal_fuzzy_matching_utils import fuzzy_compare_str, fuzzy_compare_strlists, \
    fuzzy_compare_permuted_strsets
from utilities import utils, logs
#from aws_lambda import s3utils
from utilities.style_utils import get_map_overrides, find_similar_styles, get_style_fail_to_map, get_manual_styles_to_contests
from utilities.config_d import config_dict
from utilities.vendor import get_layout_params
#from utilities import config_d
from utilities.genrois import format_rois_list_str
from utilities.images_utils import create_redlined_images
from utilities.styles_from_cvr_converter import convert_cvr_to_styles
from models.DB import DB
#from models.Job import Job
#from utilities.utils import list_from_csv_str
from utilities.analysis_utils import correct_ocr_mispellings_of_common_words_mixedcase, adjust_target_loc, correct_ocr_mispellings_of_common_names_mixedcase

ROISMAP_COLUMNS = ('style_num', 'contest', 'option', 'roi_coord_csv', 'target_x', 'target_y', 'ev_coord_str', 'p')


   
def find_ev_coord_val(target, timing_vector: list, offset=0, x_or_y='y') -> int:
    """ find index of target coord in timing vector """
    
    if x_or_y == 'y':
        coord = 'y'
        size = 'h'
    else: 
        coord = 'x'
        size = 'w'
    
    for idx, mark in enumerate(timing_vector):
        if target > mark[coord] and target < mark[coord] + mark[size]:
            return idx + offset

    string = f"### EXCEPTION: could not find timing mark for: target:{target} in timing_vector:{timing_vector}"
    utils.exception_report(string)
    return 0
    


def get_rois_coord_csv(rois_dict):
    return ','.join([str(rois_dict[x]) for x in ('p', 'x', 'y', 'w', 'h', 'blk_x', 'blk_y', 'blk_w', 'blk_h')])
    
    

default_timing_vector = {'x_timing_vector': [],
                         'y_timing_vector': [],
                        }
hardcoded_timing_vector = {'x_timing_vector': # x, w
    [[81, 36],  [148, 35],  [214, 36],  [280, 36],  [347, 36],  [414, 35],  [480, 35],
    [546, 36],  [613, 35],  [679, 35],  [745, 36],  [812, 35],  [878, 35],  [944, 36],
    [1011, 35], [1077, 35], [1144, 35], [1210, 35], [1277, 35], [1343, 35], [1409, 36],
    [1476, 36], [1543, 35], [1609, 36], [1710, 18]],
    
                         'y_timing_vector':   # y, h
    [[0, 29],   [55, 27],   [110, 28],  [165, 28],  [220, 28],  [275, 28],  [330, 28], 
    [385, 28],  [440, 28],  [495, 28],  [550, 27],  [605, 27],  [660, 28],  [715, 27],
    [770, 27],  [825, 28],  [880, 28],  [935, 28],  [990, 28],  [1045, 28], [1100, 28], 
    [1155, 28], [1210, 28], [1265, 28], [1320, 28], [1375, 28], [1430, 28], [1485, 28],
    [1540, 28], [1595, 29], [1650, 28], [1705, 29], [1761, 28], [1815, 29], [1870, 29],
    [1925, 29], [1981, 28], [2036, 28], [2091, 27], [2146, 28], [2201, 28], [2255, 29],
    [2310, 29], [2366, 28], [2421, 28], [2476, 28], [2531, 28], [2586, 28], [2640, 28],
    [2696, 27], [2751, 27], [2807, 25]],
                        }



def get_best_timing_vector(style_dict, timing_vector_key: str) -> list:
    """ Get the best version of the timing vector using either:
            the vector generated for this style
            a vector generated for another style in this run
            a hardcoded vector.
        timing_vector_key: either 'x_timing_vector' or 'y_timing_vector'
    """
    timing_vector = style_dict.get(timing_vector_key, [])
    if timing_vector:
        if not default_timing_vector[timing_vector_key]: 
            default_timing_vector[timing_vector_key] = timing_vector
            
            #utils.sts(f"Initialized default_{timing_vector_key}\n{timing_vector}")
            #import pdb; pdb.set_trace()
    elif default_timing_vector[timing_vector_key]:
        timing_vector = default_timing_vector[timing_vector_key]
    else:
        timing_vector = hardcoded_timing_vector[timing_vector_key]
        string = f"### WARNING: using hardcoded timing vector for {timing_vector_key} of style {style_dict.get('style_num', 'UNKNOWN')}"
        utils.exception_report(string)
        
    return timing_vector

def get_ev_coord_str(style_dict, rois_map_dict):
    """ create ev_coord_str to match ES&S expressvote barcode value 
    """
    
    target_x, target_y, page0, sheet0 = rois_map_dict['target_x'], rois_map_dict['target_y'], rois_map_dict['p'], 0
    
    timing_marks = style_dict.get('timing_marks')
    
    x_timing_vector = timing_marks[page0]['top_marks']
    y_timing_vector = timing_marks[page0]['left_vertical_marks']
    
    x_coord = find_ev_coord_val(target_x, x_timing_vector, offset=1, x_or_y='x')
    y_coord = find_ev_coord_val(target_y, y_timing_vector, offset=0, x_or_y='y')
    
    ev_coord_str = "%2.2u%2.2u%1u%1u" % ( \
        int(x_coord), 
        int(y_coord), 
        page0+1, sheet0+1)
 
    if re.search(r"00", ev_coord_str):
        string = f"### EXCEPTION: ev_coord_str miscalculation: {ev_coord_str} " \
                 f"on target_x:{rois_map_dict['target_x']} target_y:{rois_map_dict['target_y']}"
        utils.exception_report(string)
        rois_map_dict['ev_coord_str'] = ''
    return ev_coord_str
 

def create_rois_map_dict(
        argsdict: dict, 
        rois_list_dict: dict, 
        style_dict: dict, 
        contest_str, 
        option_name, 
        map_info, 
        layout_params={},
        targ_os_type = 'norm_targ_os',
        ):
    """ The rois_map is eventually used to extract votes from the ballots.
        Mapped rois are those that have targets that must be analyzed for marks during extraction.
        There is one map entry per target.
        
        'targ_os_type' determines which set of offsets to choose:
            'norm_targ_os'      -- (default) add normal offsets per layout_params
            'comb_yes_targ_os'  -- use layout_params['combyes_targ_os']
            'comb_no_targ_os'   -- use layout_params['combno_targ_os']
            
   """

    rois_map_dict = {
        'style_num': style_dict['style_num'],       # this is the internally generated style_num
        'card_code': style_dict.get('card_code', ''),       # this code will match the card_id on the ballot
        'contest': contest_str,                     # official contest name 
        'option': option_name,                      # official option name
        'ocr_text': '',                             # ocr'd text from the ballot for debugging purposes.
        'match_bool': map_info['match_bool'],       # was the ocr string matched properly during mapping
                                                    # or was this inferred due to position.
        'target_x': 0, 'target_y': 0,               # absolute coordinates of target, defined here.
        
        'roi_coord_csv': get_rois_coord_csv(rois_list_dict),  # location information of this roi, s,p,x,y,w,h
        'p': rois_list_dict.get('p', 0),            # also maintain 'p' because we need it to search for the applicable rois map during extraction.
        
        #'s':0, 'p':0, 'x':0, 'y':0, 'w':0, 'h':0,  # location information of the roi
        #'y_bin'                                    # deprecated. was used for timing mark alignment
        }


    # the ocr conversion is not really needed in the roismap but is included for debugging.
    rois_map_dict['ocr_text'] = str(rois_list_dict.get('ocr_text', ''))
    if not option_name.startswith('#'):
        resolve_target_coords(argsdict, style_dict, rois_map_dict, rois_list_dict, layout_params, targ_os_type)
        update_ev_coord_str(argsdict, rois_map_dict, style_dict)

    return rois_map_dict

def update_ev_coord_str(argsdict: dict, rois_map_dict: dict, style_dict: dict):
    """ ev_coord_str provides the string in the format XXYYSP of the
        target, which is what is provided in the expressvote BMD barcodes.
        If ocr of text fails, we can rely on this coordinate value.
        The coordinates are of the timing marks. 
    """ 
    rois_map_dict['ev_coord_str'] = ''
    
    if argsdict.get('vendor','') != 'ES&S':
        return None
        
    ev_coord_str = get_ev_coord_str(style_dict, rois_map_dict)
    rois_map_dict['ev_coord_str'] = f"'{ev_coord_str}'"     #surround with quotes to keep leading zeros
    
    if re.search(r"00", ev_coord_str):
        utils.exception_report(f"### EXCEPTION: ev_coord_str miscalculation: {ev_coord_str} "
                 f"on target_x:{rois_map_dict['target_x']} target_y:{rois_map_dict['target_y']}")


def calc_roi_target(rois_map_dict, style_dict, page, layout_params):
    """ given rois_map_dict with proposed target_x and target_y
        adjust to timing marks
    """
    
    target_x = rois_map_dict['target_x']
    target_y = rois_map_dict['target_y']

    style_page_timing_marks = style_dict['timing_marks'][page]
    
    adjusted_x, adjusted_y = adjust_target_loc(target_x, target_y, style_page_timing_marks, layout_params)
    
    rois_map_dict['target_y'] = adjusted_y
    rois_map_dict['target_x'] = adjusted_x
            
    
def resolve_target_coords(argsdict: dict, style_dict: dict, rois_map_dict: dict, rois_list_dict: dict, layout_params, targ_os_type = 'norm_targ_os'):
    """ the method for determining the target location is vendor and layout specific.
        updates rois_map_dict
        layout params provides the detailed offsets.
        offsets have three components, 'ref', 'x', 'y':
            ref deteremines how it is calculated, as follows:
                'tl', 'tr', 'br', 'bl' -- add offsets to
                    top-left, top-right, bottom-right, or bottom-left corner of roi
            x,y are offsets which are added to the ref location.
            
        targ_os_type determines which set of offsets to choose:
            'norm_targ_os'      -- (default) add normal offsets per layout_params
            'comb_yes_targ_os'  -- use layout_params['comb_yes_targ_os']
            'comb_no_targ_os'   -- use layout_params['comb_no_targ_os']
            
        for use_ocr_based_genrois:
            blk_x will be set to the left-edge of the region box.
            y is the centerline of the text.
            
            
    """

    x_os = int(layout_params[targ_os_type]['x'])
    y_os = int(layout_params[targ_os_type]['y'])
    ref  = str(layout_params[targ_os_type]['ref'])

    p, x, y, w, h, blk_x, blk_y, blk_w, blk_h = [int(x) for x in list(rois_map_dict['roi_coord_csv'].split(r','))]

#    x, y, w, h = [rois_map_dict[i] for i in ['x','y','w','h']]

    if argsdict['use_ocr_based_genrois']:
        if ref == 'tl':
            rois_map_dict['target_x'] = blk_x + x_os
            rois_map_dict['target_y'] = y
        elif ref == 'tr':
            rois_map_dict['target_x'] = blk_x + blk_w + x_os    # note: x_os negative.
            rois_map_dict['target_y'] = y
        elif ref == 'br':
            rois_map_dict['target_x'] = blk_x + blk_w + x_os    # note: x_os negative.
            rois_map_dict['target_y'] = y
        elif ref == 'bl':
            rois_map_dict['target_x'] = blk_x + x_os
            rois_map_dict['target_y'] = y
            
    
    else:
        if ref == 'tl':
            rois_map_dict['target_x'] = x + x_os
            rois_map_dict['target_y'] = y + y_os
        elif ref == 'tr':
            rois_map_dict['target_x'] = x + w + x_os    # note: x_os negative.
            rois_map_dict['target_y'] = y + y_os
        elif ref == 'br':
            rois_map_dict['target_x'] = x + w + x_os    # note: x_os negative.
            rois_map_dict['target_y'] = y + h + y_os    # note: y_os negative.
        elif ref == 'bl':
            rois_map_dict['target_x'] = x + x_os
            rois_map_dict['target_y'] = y + h + y_os    # note: y_os negative.
            
    calc_roi_target(rois_map_dict, style_dict, p, layout_params)    # this resolves to the timing marks.
    
        
def build_ocr_strlist(argsdict, rois_list, rois_idx, num_options):
    """ given roislist, construct ocr_strlist of type rois_list_key
    """

    # first pull out the proposed ocr strings 
    ocr_strlist = []
    rem_target = argsdict.get('rem_target_from_ocr_str', True)
    
    for option_idx in range(num_options):
        option_rois_idx = rois_idx + option_idx
        if option_rois_idx >= len(rois_list):
            break
        ocr_str = rois_list[option_rois_idx].get('ocr_text', '').strip().replace("\n", " ")
        if rem_target:
            ocr_str = re.sub(r'^\S\s', '', ocr_str)
        ocr_strlist.append(ocr_str)
        utils.sts(f"option_{option_idx}: '{ocr_str[:50]}'", 3)

    return ocr_strlist
    
def combine_ocr_lines(rois_list, rois_idx, num_lines):
    """ combine text strings starting at rois_idx into a single string
    """
    
    s_list = [rois_list[idx]['ocr_text'] for idx in range(rois_idx, rois_idx + num_lines)]

    s_str = r' '.join(s_list)
    s_str = re.sub(r'\s\s+', ' ', s_str)      # remove double+ spaces
    
    logs.sts(f"Combined {num_lines} in rois_list to create one string. rois text:\n"
        f"{pprint.pformat(s_list)}\n"
        f"Result: '{s_str}'", 3)
    
    return s_str
    

# def format_map_info(map_info):

    # s_str = pprint.pformat(map_info)
    # \
            # f"contest_str:              {map_info['contest_str']}\n" \
            # f"writein_str:              {map_info['writein_str']}\n" \
            # f"match_bool:               {map_info['match_bool']}\n" \
            # f"rois_in_this_contest:     {map_info['rois_in_this_contest']}\n" \
            # f"next_rois_idx:            {map_info['next_rois_idx']}\n"
            
    # for element in ['contest', 'options', 'descr', 'writeins']        
            # f"contest_num:              {map_info['contest']['num']}\n" \
            # f"options_os:               {map_info['options']['rois_os']}\n" \
            # f"descr_os:                 {map_info['descr']['rois_os']}\n" \
            # f"writeins_os:              {map_info['writeins']['rois_os']}\n" \
            # #f"additional_descr_rois:    {map_info['additional_descr_rois']}\n" \
            # f"options_order_idxlist:    {map_info['options']['order_idxlist']}\n" \
            # f"sts:                      {map_info['sts']}"
    # return s_str

    
    # for element in ['options', 'writeins']:
        # element_dict = map_info[element]
        # element_dict['rois_os'] = None
        # if element_dict['num']:
            # element_dict['rois_os'] = rois_idx + rois_used
            
                    
            # if element == 'options' and is_contest_simple_yes_no_type(argsdict, map_info):
                # compare_simple_yes_no_type(argsdict, rois_list, map_info, element)
            # elif element == 'writeins' and map_info['writein_str'] == '':
                # # format where no writein string will be included. Just accept the rois as writein.
                # # NOTE: This does not work well for 'use_ocr_based_genrois'
                # map_info[element]['cmpbool'], map_info[element]['metric'] = True, 1;

            # else:
                # fuzzy_compare_element_lists_to_roislist(
                    # rois_list, 
                    # element_dict=element_dict, 
                    # fuzzy_compare_mode=fuzzy_compare_mode, 
                    # permute=element_dict['permute'])

            # sts += utils.sts(f"{element} Match?:{map_info[element]['cmpbool']} ({map_info[element]['metric']})", 3)
            # rois_used += element_dict['num']

    #map_info['descr']['rois_os'] = None
    #if map_info['descr']['num']:
    #    map_info['descr']['rois_os'] = rois_idx + map_info['contest']['num']
    #    map_info['descr']['ocr_text'] = combine_ocr_lines(rois_list, rois_idx, map_info['descr']['num'])
    #    
    #    '''
    #    if argsdict['max_additional_descr_rois']:
    #        # now look ahead at additional rois to see if they are large enough to be
    #        # additional description paragraphs that should be combined.
    #        additional_descr_rois = 0
    #        for i in range(1, max_additional_descr_rois + 1):
    #            if (descr_os + i + 2 < len(rois_list) and
    #                    rois_list[descr_os + i]['h'] > max_yes_no_option_h):
    #                
    #                ocr_descr_str += ' '+rois_list[descr_os + i]['ocr_text']
    #                additional_descr_rois = i
    #                sts += utils.sts(f"Appending additional roi of height {rois_list[descr_os + i]['h']} to description: {ocr_descr_str}", 3)
    #            else:
    #                break
    #    '''        
    #    
    #    
    #    map_info['descr']['cmpbool'], map_info['descr']['metric'] = fuzzy_compare_str(
    #        map_info['descr']['expected'], map_info['descr']['ocr_text'], map_info['descr']['thres'], justify='left')
    #    sts += utils.sts(f"{'descr'} Match?:{map_info['descr']['cmpbool']} ({map_info['descr']['metric']})", 3)

    # this must be outside conditional below because of loop control below if found
    # map_info['options']['rois_os'] = rois_idx + map_info['contest']['num'] + map_info['descr']['num'] + additional_descr_rois      # this must occur outside if below.
    # already initialized  map_info['options']['order_idxlist'] = []
    
            # first pull out the proposed ocr strings 
            
            #ocr_text_options_strlist = build_ocr_strlist(argsdict, rois_list, map_info['options']['rois_os'], map_info['options']['num'])
            #if argsdict.get('permute_option_list', True):
            #    # for most options, we need to check various permutations of the options.
            #    (map_info['options']['cmpbool'], map_info['options']['metric'], map_info['options']['order_idxlist']) = fuzzy_compare_permuted_strsets(
            #        map_info['options']['expected'], ocr_text_options_strlist, map_info['options']['thres'], fuzzy_compare_mode)
            #else:
            #    # but in some states, options are not reordered, so we need not waste time checking all permutations.
            #    fuzzy_compare_element_lists(element_dict=map_info['options'], ocr_strlist=ocr_text_options_strlist, fuzzy_compare_mode=fuzzy_compare_mode)
            #    map_info['options']['order_idxlist'] = [x for x in range(len(map_info['options']['expected']))]

    #map_info['writeins']['rois_os'] = rois_idx + map_info['contest']['num'] + map_info['options']['num']
    #if map_info['writeins']['num']:
            
        # else:
           # fuzzy_compare_element_lists_to_roislist(
                # rois_list, 
                # element_dict=map_info['writeins'], 
                # fuzzy_compare_mode=fuzzy_compare_mode, 
                # permute=False)
            # writeins are never used with description, so don't need to worry about additional_descr_rois or descr_num
            # ocr_writein_strlist = build_ocr_strlist(argsdict, rois_list, map_info['writeins']['rois_os'], map_info['writeins']['num'])

            # fuzzy_compare_element_lists(element_dict=map_info['writeins'], ocr_strlist=ocr_writein_strlist, fuzzy_compare_mode=fuzzy_compare_mode)
            # map_info['writeins']['cmpbool'], map_info['writeins']['metric'] = fuzzy_compare_strlists(
            #    map_info['writeins']['expected'], ocr_writein_strlist, map_info['writeins']['thres'], fuzzy_compare_mode)

def fuzzy_compare_element(element_dict: dict, justify='left'):
    
    element_dict['cmpbool'], element_dict['metric'] = fuzzy_compare_str(
        element_dict['expected'], element_dict['ocr_text'], element_dict['thres'], justify=justify)


def fuzzy_compare_element_lists(element_dict: dict, ocr_strlist, fuzzy_compare_mode='best_of_all', permute=False):

    if not permute:
        element_dict['cmpbool'], element_dict['metric'] = fuzzy_compare_strlists(
            element_dict['expected'], ocr_strlist, element_dict['thres'], fuzzy_compare_mode)
        element_dict['order_idxlist'] = [x for x in range(len(element_dict['expected']))]
    else:
       (element_dict['cmpbool'], element_dict['metric'], element_dict['order_idxlist']) = fuzzy_compare_permuted_strsets(
            element_dict['expected'], ocr_strlist, element_dict['thres'], fuzzy_compare_mode)


    
def fuzzy_compare_element_lists_to_roislist(argsdict, rois_list, element_dict: dict, fuzzy_compare_mode='best_of_all', permute=False):  

    ocr_strlist = build_ocr_strlist_element(argsdict, rois_list, element_dict)
    fuzzy_compare_element_lists(element_dict, ocr_strlist, fuzzy_compare_mode=fuzzy_compare_mode, permute=permute)
    
def build_ocr_strlist_element(argsdict, rois_list, element_dict):
    return build_ocr_strlist(argsdict, rois_list, element_dict['rois_os'], element_dict['num'])

def is_contest_simple_yes_no_type(argsdict, map_info):
    """ Contest is yes_no type if:
            options num = 2
            descr num > 0
            yes, no found somewhere in option 1, option 2.
            and not "yes_no_in_descr" mode
        this also allows situation where the strings are longer, like "Yes for approval","No for rejection"
        (could avoid this regex over and over by having a flag stating this is indeed a yes/no option.)
    """

    return (map_info['options']['num'] == 2 and map_info['descr']['num'] and 
        (bool(re.search(r'Yes', map_info['options']['official'][0], flags=re.I))) and 
        (bool(re.search(r'No',  map_info['options']['official'][1], flags=re.I))) and 
        not argsdict['yes_no_in_descr'])
    
def compare_simple_yes_no_type(argsdict, rois_list, map_info, element):
    """ yes/no contests are different. These are very short strings and we know the order.
        this first way of handling them, they exist in separate rois. The other way is if yes/no is in
            the same roi as the description, and that is indicated with the argsdict value 'yes_no_in_descr'
            (and handled further below)
        these we will have to treat with careful comparisons
    """
    element_dict = map_info['options']

    ocr_strlist_cf              = utils.casefold_list(build_ocr_strlist_element(argsdict, rois_list, element_dict))
    official_options_list_cf    = utils.casefold_list(element_dict['official'])

    
    if official_options_list_cf == ['yes', 'no']:
        # this only works in the case when the official options are exactly yes and no.
        # use regex matching.
        yes_match = bool(re.search(r'[yv][eo][s]', ocr_strlist_cf[0]))
        no_match = bool(re.search(r'[n][eo0qc]', ocr_strlist_cf[1]))
        element_dict['cmpbool'] = yes_match and no_match
        element_dict['metric'] = 1 if element_dict['cmpbool'] else 0
    
    # still not matching or not simple yes no. Try different approach.
    # this puts both options, which are both short, together in single fuzzy match.
    if not element_dict['cmpbool']:  # and map_info['contest']['cmpbool'] and map_info['descr']['cmpbool']:
        ocr_yes_no = '='.join(ocr_strlist_cf)
        correct_yes_no = '='.join(official_options_list_cf)
        element_dict['cmpbool'], element_dict['metric'] = fuzzy_compare_str(
            correct_yes_no,
            ocr_yes_no, 
            element_dict['thres'])
        sts = utils.sts(f">>> YesNo options should probably compare: {ocr_yes_no}")
    # Added this to ensure option_order_idxlist is two element list for Yes/No options.
    element_dict['order_idxlist'] = [0, 1]
    map_info['sts'] += sts

    
def set_contest_targets(argsdict, rois_list, rois_map_df, contest_dict, style_dict, map_info):
    """ Once the rois_list has been matched successfully with a contest,
        resolve the location of the targets.
        There are two cases here,
            1. targets are normally located with respect to their own rois.
            2. targets are located inside description in known location from bottom of rois.
                in this case, there are no writeins and no rois consumed for options.
        returns total rois consumed by options and writeins.
        
        style_dict is used for style_num, card_code and timing_marks.
                
    """
    layout_params = get_layout_params(argsdict) # page0 and sheet0 not required to get option location information

    contest_str             = contest_dict['contest_str']
    #ballot_contest_name     = contest_dict['ballot_contest_name']
    official_options_list   = contest_dict['official_options_list']
    #ballot_descr           = contest_dict['ballot_descr']
    writein_num             = contest_dict['writein_num']
    #writein_options_list    = contest_dict['writein_options_list']
    #contest_name_num        = contest_dict['contest_name_num']
    #ballot_options_list     = contest_dict['ballot_options_list']
    #option_num              = contest_dict['option_num']
    #descr_num               = contest_dict['descr_num']
    #vote_for                = contest_dict['vote_for']
    utils.sts(f"set_contest_targets for {contest_str}", 3)
    
    error_flag = False

    if (argsdict['yes_no_in_descr'] and map_info['descr']['num'] and map_info['options']['num'] == 2):
        utils.sts("set_contest_targets processing yes_no_in_desc", 3)
        # This situation exists in some Dominion formats where the yes, no options are in the same
        # ROI as the description and the description may flow around the options.
        # Not compatible if 'max_additional_descr_rois' is > 1
        # targ_os_type determines which set of offsets to choose:
        #    'norm_targ_os'      -- (default) add normal offsets per layout_params
        #    'comb_yes_targ_os'  -- use layout_params['combyes_targ_os']
        #    'comb_no_targ_os'   -- use layout_params['combno_targ_os']
        if argsdict['max_additional_descr_rois']:
            utils.exception_report("EXCEPTION: Enabling 'yes_no_in_descr' is incompatible with 'max_additional_descr_rois' > 0")

        rois_map_dict = create_rois_map_dict(
            argsdict,
            rois_list[map_info['descr']['rois_os']], 
            style_dict, 
            contest_str,
            option_name='Yes',
            map_info=map_info,
            layout_params=layout_params,
            targ_os_type = 'comb_yes_targ_os',
            )

        rois_map_df = rois_map_df.append(rois_map_dict, ignore_index=True)

        rois_map_dict = create_rois_map_dict(
            argsdict,
            rois_list[map_info['descr_os']], 
            style_dict, 
            contest_str,
            option_name='No', 
            map_info=map_info,
            layout_params=layout_params,
            targ_os_type = 'comb_no_targ_os',
            )
        rois_map_df = rois_map_df.append(rois_map_dict, ignore_index=True)

    else:
        utils.sts("set_contest_targets normal case, adding options", 3)
        # normal case with options not in description box.
        for i, orderidx in enumerate(map_info['options']['order_idxlist']):
            rois_idx = map_info['options']['rois_os'] + i
            rois_map_dict = create_rois_map_dict(
                argsdict,
                rois_list[rois_idx], 
                style_dict, 
                contest_str,
                option_name=official_options_list[orderidx], 
                map_info=map_info,
                layout_params=layout_params
                #targ_os_type use default 'norm_targ_os'
                )
            rois_map_df = rois_map_df.append(rois_map_dict, ignore_index=True)

        if writein_num:
            utils.sts("set_contest_targets normal case, adding options", 3)
        for writein_idx in range(writein_num):
            try:
                rois_dict = rois_list[map_info['writeins']['rois_os'] + writein_idx]
            except IndexError:
                error_flag = True
                utils.exception_report(f"Writeins for {contest_str} exceed rois_list length:{len(rois_list)}."
                    f" writein_os:{map_info['writein_os']} + writein_idx:{writein_idx}")
                break
            rois_map_dict = create_rois_map_dict(
                argsdict,
                rois_dict, 
                style_dict, 
                contest_str,
                option_name=f'writein_{writein_idx}', 
                map_info=map_info,
                layout_params=layout_params
                #targ_os_type use default 'norm_targ_os'
                )
            rois_map_df = rois_map_df.append(rois_map_dict, ignore_index=True)
            
    return error_flag, rois_map_df


def maprois_one_style(
        argsdict,
        style_num,
        style_contest_list,
        #rois_map_df,
        contests_dod,
        style_overrides_dod={}
):
    """
    This function processes a single style to connect the rois that
    have already been detected and ocrd from the page, to the
    contests that are defined for that style. This is a graphics-first driven mapping.

    style_dict:         style information for this style and will be updated by this function
    rois_list           the list of all the rois on the front and back of the ballot, sorted by page, x, y.
    style_contest_list  provides for each style, the list of contests on the ballot for this style.
    
    returns rois_map_df for this style
    
    """
    #rois_list = DB.load_rois(style_num=style_num)
    
    rois_list   = DB.load_data(dirname='styles', subdir=style_num, name=f"{style_num}_rois.json", type='lod')
    
    for roi in rois_list:
        roi['ocr_text'] = correct_ocr_mispellings_of_common_words_mixedcase(roi['ocr_text'])
        if 'ocr_option_text' in roi:
            roi['ocr_text'] = correct_ocr_mispellings_of_common_names_mixedcase(roi['ocr_option_text'])

    rois_window_os              = 0     # current location in list of rois. Once a set of rois are mapped to a contest, this is moved to the first unused roi.
    window_slip_os              = 0     # if there are unused rois in between contests, then we may have to slip the matching window over these dead rois.
    last_match_os               = 0     # the offset of the last successful or semi-successful match.
    maprois_max_slip_os         = argsdict.get('maprois_max_slip_os', 3)           # how much further will algorithm search after non match.
    additional_descr_rois       = 0
    
    map_override = False
    error_flag = False
    contests_exhausted_error_flag = False
    missing_contest_str = ''
    #failing_contest_idx = 0
    
    #style_dict = DB.load_style(name=style_num)
    style_dict = DB.load_data(dirname='styles', subdir=style_num, name=f'{style_num}_style', format='.json', silent_error=False)

    #if style_num == '2112041':
    #    import pdb; pdb.set_trace()
    
    style_rois_map_df= pd.DataFrame(columns=ROISMAP_COLUMNS)
    

    sts = utils.sts(f"Mapping style: {style_num} =============================", 3)
    for contest_idx, contest_str in enumerate(style_contest_list):
        contest_str = contest_str.strip(' ')
        contest_dict = contests_dod[contest_str]
        contest_dict['contest_str'] = contest_str
        ballot_contest_name     = contest_dict['ballot_contest_name']
        official_options_list   = contest_dict['official_options_list']
        ballot_descr            = contest_dict['ballot_descr']
        writein_num             = contest_dict['writein_num']
        writein_options_list    = contest_dict['writein_options_list']
        contest_name_num        = contest_dict['contest_name_num']
        ballot_options_list     = contest_dict['ballot_options_list']
        option_num              = contest_dict['option_num']
        descr_num               = contest_dict['descr_num']
        #vote_for                = contest_dict['vote_for']
        
        writein_str             = argsdict.get('writein_str', 'write-in:')      # it is necessary to be able to define the writein_str as ''
        contest_dict['writein_str'] = writein_str
 
        writein_strlist = []
        writein_strlist.extend([writein_str] * int(writein_num))
        contest_dict['writein_strlist'] = writein_strlist

        sts += utils.sts(f"{'-' * 50}", 3)
        sts += utils.sts(f"  official contest name:      '{contest_str}'", 3)
        sts += utils.sts(f"  ballot_contest_name:        '{ballot_contest_name}'", 3)
        sts += utils.sts(f"  contest_name_num:           {contest_name_num}", 3)
        sts += utils.sts(f"  official_options_list:      '{', '.join(official_options_list)}'", 3)
        sts += utils.sts(f"  ballot_options_list:        '{', '.join(ballot_options_list)}'", 3)
        sts += utils.sts(f"  ballot_descr:               '{ballot_descr}'", 3)
        sts += utils.sts(f"  writein_num:                {writein_num}", 3)
        sts += utils.sts(f"  writein_strlist             '{', '.join(writein_strlist)}'", 3)
        sts += utils.sts(f"  writein_options_list:       '{', '.join(writein_options_list)}'", 3)

        # start a new rois_map_record. One record for each contest and option in this style
        # these components are common to all appends in this loop

        # The following section implements a sliding-window algorithm in an attempt to match up 
        # contests, in the order given, possible description, followed by options, in any order, then possibly write-ins

        eff_option_num = 0 if argsdict['yes_no_in_descr'] else option_num

        rois_in_this_contest = contest_name_num + descr_num + eff_option_num + writein_num
        sts += utils.sts(f"  Total ROIS in this contest  {rois_in_this_contest}", 3)
        additional_descr_rois = 0
        
        # rois window loop
        while (rois_window_os + window_slip_os + rois_in_this_contest + additional_descr_rois) <= len(rois_list):
            sts += utils.sts(f"Offset: {rois_window_os} Slip:{window_slip_os} ------------------", 3)
            
            match_base_idx = rois_window_os + window_slip_os
            rois_list[match_base_idx]['roi_num'] = match_base_idx

            map_info = \
                compare_rois_to_contest(
                    argsdict,
                    rois_list,              # list of ocr'd rois
                    match_base_idx,         # current offset into rois_list
                    contest_dict,           # official contest to compare with
                    )
            #    map_info = {
            #        'match_bool' : match_bool,
            #        'contest_str': contest_str,
            #        'options_os' : options_os,
            #        'descr_os'   : descr_os,
            #        'writein_os' : writein_os,
            #        'additional_descr_rois' : additional_descr_rois,
            #        'option_order_idxlist' : option_order_idxlist,
            #        'sts' : sts,
            #        }       
                    
            sts += map_info['sts']
    
            if not map_info['match_bool'] and not map_override:
                # if we have no match of the options and description, slip the window and try again.
                window_slip_os += 1

                if window_slip_os < maprois_max_slip_os:
                    # loop control will trigger if slip moves window past end of rois.
                    continue    # move window and try again
                
                # window has moved too far. Something is wrong.
                ##try:
                ##    rois_window_os = style_overrides_dod[style_num][contest_str]
                ##    utils.sts(f"style map override envoked for style {style_num} "
                ##              f"contest {contest_str} to os {rois_window_os}", 3)
                ##    map_override = True
                ##    continue    # execute the loop again with map_override set.
                ##except:
                ##    pass

                # Could not find an exact match. 
                # instead of failing immediately, assume that this might actually match at rois_window_os at window_slip_os = 0
                #
                #string = f"WARNING: Unable to fully rois match for contest: '{contest_str}'" \
                #         f" for style {style_num} (slip window exhausted)\n"
                ##error_flag = True
                
                # proceed as if match ocurred, knowing match_bool will be False.
                window_slip_os = 0
                match_base_idx = rois_window_os
                map_override = True
                continue
            
            err_flg, style_rois_map_df = add_contest_to_rois_map(argsdict, style_rois_map_df, rois_list, style_dict, contest_dict, map_info)
            error_flag = error_flag or err_flg

            rois_window_os = map_info['next_rois_idx'] 
            window_slip_os = 0
            last_match_os = rois_window_os
            map_override = False
            break   #   This is the normal exit of slip window loop
            
        else:
            # this executed if break not executed and rois window loop is exhausted
            # first look to see if this is an expected problem specified by style overrides.
            try:
                rois_window_os = style_overrides_dod[style_num][contest_str]
                sts += utils.sts(
                    f"style map override envoked for style {style_num} contest {contest_str} to os {rois_window_os}", 3)
                map_override = True
                continue
            except KeyError:
                error_flag = True
                
        if error_flag:
            missing_contest_str = contest_str
            break   # exit loop over contests.  Alternatively, could try to match the rest of the contests anyway.
        
    if last_match_os != len(rois_list):
        contests_exhausted_error_flag = True

    # Create summary report of the mapping
    summary_str = ( f"\n |{'=' * 50} |  Style {style_num} Summary  | {'=' * 60}\n"
                    "?|%50s | %20s | %-60s\n" % ('contest name', 'option', 'ocr_text'))
                    
    for index in range(len(style_rois_map_df.index)):
        rois_map_dict = style_rois_map_df.iloc[index]
        contest = rois_map_dict['contest']
        option = rois_map_dict['option']
        ocr_text = rois_map_dict.get('ocr_text', '')
        ocr_text = re.sub('[\n\r]', ' ', ocr_text)
        match_chr = ' ' if rois_map_dict['match_bool'] else '?'
        summary_str += "%s %50s | %20s | %-60s\n" % (match_chr, contest[:50], option[:20], ocr_text[:60])
        
    if error_flag:
        summary_str += (
            f"EXCEPTION: Style {style_num}: Unable to locate rois match starting at " +
            f"{last_match_os} for contest: '{missing_contest_str}' (rois exhausted)\n" +
            format_rois_list_str(argsdict, rois_list, start_at=last_match_os) + "\n"
            )
    elif contests_exhausted_error_flag:
        num_unused_rois = len(rois_list) - last_match_os
        if num_unused_rois > argsdict['unused_trailing_rois']:
            # out of contests but rois not used up.
            summary_str += (
                f"EXCEPTION: Style {style_num}: {num_unused_rois} ROIs not used up but " +
                f"contests have been exhausted. Only {argsdict['unused_trailing_rois']} unused rois ar allowed.\n" +
                 "If all remaining rois are blank on this sheet, check setting of 'unused_trailing_rois'\n" +
                f"Unused rois starting at {last_match_os}\n" +
                format_rois_list_str(argsdict, rois_list, start_at=last_match_os) + "\n"
                )
        else:
            contests_exhausted_error_flag = False
            
    if error_flag or contests_exhausted_error_flag:
        utils.exception_report(summary_str + "\n" + sts)
        # copy templates that did not map to assist folder.
        # this copies both pages (if available) of templates and redlines to assist folder.
        DB.copy_template(style_num, 'assist')
        
        # add additional diagnostics to map_report only when an error is detected.
        logs.append_report(('=' * 50) + "\n" + sts + "\n", rootname='map_report')
        

    logs.sts(summary_str, 3)
    logs.append_report(summary_str + "\n\n", rootname='map_report')

    DB.update_dict(dirname='styles', subdir=style_num, name=f'{style_num}_style', field='style_failed_to_map', value=(error_flag or contests_exhausted_error_flag))
    return style_rois_map_df, (error_flag or contests_exhausted_error_flag)
    

def compare_rois_to_contest(argsdict, rois_list, rois_idx, contest_dict) -> dict:
    """ this function compares one contest with the rois_list (ocr result) at list_offset
        and returns map_info dict providing mapping result information
        
        Special Heuristics:
        1. Tesseract sometimes drops lines using tsv mode in paragraphs with 
            close spacing.
        
        
    """
    fuzzy_compare_mode          = argsdict['fuzzy_compare_mode']
    #max_additional_descr_rois   = argsdict.get('max_additional_descr_rois', 1)

    #max_yes_no_option_h     = 60    # anything greater than this is probably additional description paragraph
    #                                # this would be better moved to layout_params.
    
    contest_str                 = contest_dict['contest_str']
    contest_name_num            = contest_dict['contest_name_num']      # how many rois (i.e. lines) are in the contest name
    descr_num                   = contest_dict['descr_num']
    option_num                  = contest_dict['option_num']
    eff_option_num              = 0 if argsdict['yes_no_in_descr'] else option_num
    writein_num                 = contest_dict['writein_num']
    rois_in_this_contest        = contest_name_num + descr_num + eff_option_num + writein_num
    
    # if multiple rois exist in the contest header, we still want to try to match if it is incomplete
    min_contest_name_num        = 1 if contest_name_num else 0
    min_rois_in_this_contest    = min_contest_name_num + descr_num + eff_option_num + writein_num
    writein_str                 = argsdict.get('writein_str', 'write-in:')      # it is necessary to be able to define the writein_str as ''

    sts = ''
    
    sts += utils.sts(f"{'-' * 50}", 3)
    sts += utils.sts(f"  official contest name:      '{contest_str}'", 3)
    sts += utils.sts(f"  eff_option_num:             {eff_option_num}", 3)
    sts += utils.sts(f"  descr_num:                  {descr_num}", 3)
    sts += utils.sts(f"  writein_num:                {writein_num}", 3)
    sts += utils.sts(f"  Total ROIS in this contest  {rois_in_this_contest}", 3)
        
    ballot_contest_name     = contest_dict['ballot_contest_name']
    official_options_list   = contest_dict['official_options_list']
    ballot_descr            = contest_dict['ballot_descr']
    writein_options_list    = contest_dict['writein_options_list']
    ballot_options_list     = contest_dict['ballot_options_list']
    # vote_for                = contest_dict['vote_for']
    contest_dict['writein_str'] = writein_str

    writein_strlist = []
    writein_strlist.extend([writein_str] * int(writein_num))
    contest_dict['writein_strlist'] = writein_strlist

    sts += utils.sts(f"  ballot_contest_name:        '{ballot_contest_name}'", 3)
    sts += utils.sts(f"  contest_name_num:           {contest_name_num}", 3)
    sts += utils.sts(f"  official_options_list:      '{', '.join(official_options_list)}'", 3)
    sts += utils.sts(f"  ballot_options_list:        '{', '.join(ballot_options_list)}'", 3)
    sts += utils.sts(f"  ballot_descr:               '{ballot_descr}'", 3)
    sts += utils.sts(f"  writein_strlist             '{', '.join(writein_strlist)}'", 3)
    sts += utils.sts(f"  writein_options_list:       '{', '.join(writein_options_list)}'", 3)
                                    
    map_info = {
        'contest_str'       : contest_dict['contest_str'],
        'writein_str'       : contest_dict['writein_str'],
        'match_bool'        : False,
        'rois_exhausted'    : False,
        'rois_in_this_contest' : 0,
        'sts'               : '',
        'next_rois_idx'     : None,
        'contest': {
            'num':              contest_dict['contest_name_num'],
            'cmpbool':          True,
            'metric':           1.0,
            'thres':            config_dict['fuzzy_thres']['contest'],
            'expected':         contest_dict['ballot_contest_name'],
            'rois_os':          None,
            'ocr_text':         '',
            },
        'descr': {
            'num':          contest_dict['descr_num'],
            'cmpbool':      True,
            'metric':       1.0,
            'thres':        config_dict['fuzzy_thres']['descr'],
            'expected':     contest_dict['ballot_descr'],
            'rois_os':      None,
            'ocr_text':     '',
            },
        'options': {
            'num':          contest_dict['option_num'],
            'cmpbool':      True,
            'metric':       1.0,
            'thres':        config_dict['fuzzy_thres']['options'],
            'expected':     contest_dict['ballot_options_list'],
            'official':     contest_dict['official_options_list'],
            'rois_os':      None,
            'ocr_text':     [],
            'order_idxlist': [],
            'permute':      argsdict.get('permute_option_list', True),
            },
        'writeins': {
            'num':          contest_dict['writein_num'],
            'cmpbool':      True,
            'metric':       1.0,
            'thres':        config_dict['fuzzy_thres']['writeins'],
            'expected':     contest_dict['writein_strlist'],
            'rois_os':      None,
            'ocr_text':     [],
            'order_idxlist': [],
            'permute':      False,
            }
        }
  
    eff_option_num = 0 if argsdict['yes_no_in_descr'] else map_info['options']['num']

    #additional_descr_rois = 0
    remaining_rois = len(rois_list) - rois_idx
        
    if min_rois_in_this_contest > remaining_rois:
        # impossible to match this contest: not enough rois left
        return {'match_bool':       False, 
                'rois_exhausted':   True,
                'sts': f"Contest {map_info['contest_str']} requires {rois_in_this_contest} rois but only {remaining_rois} remain."}

    rois_used = 0
    for element in ['contest', 'descr', 'options', 'writeins']:
        """ contest and descr elements are strings rather than strlists
        """
        element_dict = map_info[element]

        element_dict['rois_os'] = None
        if element_dict['num']:
            element_dict['rois_os'] = rois_idx + rois_used
            
            if element in ['contest', 'descr']:
                # contest and descr are simple strings, not strlists
                
                if argsdict.get('use_ocr_based_genrois', False):
                    element_dict['ocr_text'] = combine_ocr_lines(rois_list, rois_idx, element_dict['num'])
                else:
                    element_dict['ocr_text'] = rois_list[rois_idx]['ocr_text']
                fuzzy_compare_element(element_dict, justify='left')
                
            else:
                # options or writeins
                # options and writeins elements are strlists
                
                if element == 'options' and is_contest_simple_yes_no_type(argsdict, map_info):
                    compare_simple_yes_no_type(argsdict, rois_list, map_info, element)
                
                elif element == 'writeins' and map_info['writein_str'] == '':
                    # format where no writein string will be included. Just accept the rois as writein.
                    # NOTE: This does not work well for 'use_ocr_based_genrois'
                    map_info[element]['cmpbool'], map_info[element]['metric'] = True, 1;

                else:
                    fuzzy_compare_element_lists_to_roislist(
                        argsdict,
                        rois_list, 
                        element_dict=element_dict, 
                        fuzzy_compare_mode=fuzzy_compare_mode, 
                        permute=element_dict['permute'])

            sts += utils.sts(f"{element} Match?:{element_dict['cmpbool']} ({element_dict['metric']})", 3)
            rois_used += element_dict['num']

    map_info['next_rois_idx'] = rois_idx + rois_used

    sts_str = "element  num   bool  metric   thres\n"
    for element in ['contest', 'options', 'descr', 'writeins']:
        element_dict = map_info[element]
        if element_dict['num']:
            sts_str += ("%8s %1.1u   %5s  %3.2f    %3.2f\n" %
                (element, 
                element_dict['num'], 
                element_dict['cmpbool'], 
                element_dict['metric'], 
                element_dict['thres']))

    sts += utils.sts(sts_str, 3)

    compare_contest_name = argsdict.get('compare_contest_name', False)
    contest_bool_qual = not compare_contest_name or map_info['contest']['cmpbool'] 
    map_info['match_bool'] = (
            # usually we need not have a contest match if options match
            (   map_info['options']['num'] > 0 and map_info['options']['cmpbool'] and 
                map_info['descr']['cmpbool'] and 
                contest_bool_qual)     
            or 
            # a strange case when there are no options except a writein
            (   map_info['options']['num'] == 0 and 
                map_info['contest']['cmpbool'] and 
                map_info['writeins']['cmpbool'])                  
        )
    if map_info['options']['cmpbool'] and not map_info['contest']['cmpbool']: 
        sts += utils.sts("Warning: Options matched but contest did not.")
    if map_info['writeins']['num'] and not map_info['writeins']['cmpbool']:
        sts += utils.sts("Warning: Options matched but writeins did not.")
        
    map_info['sts'] = sts
    return map_info


def match_contest_in_rois_range(argsdict, contest_dict, rois_list, rois_idx_range):

    """ Given a single contest_dict, compare with rois in given range.
    """

    for rois_idx in rois_idx_range:
        # this is the attempt window where we try to find the active rois, 
        # so that a certain number of "dead" rois can be skipped.
        # take each rois as starting point and try to match with contests
        # if not matched, slip to next offset up to maprois_max_slip_os
        
        map_info = \
            compare_rois_to_contest(
                argsdict,
                rois_list,              # list of ocr'd rois
                rois_idx,               # current offset into rois_list
                contest_dict,           # official contest to compare with
                )
                
        if map_info['match_bool'] or map_info['rois_exhausted']: 
            break
    return map_info
    
    
def maprois_discover_style(
        argsdict,
        style_num=None,                 # either 
                                        #   1. the key the style_to_contests_dol to lookup the style, or
                                        #   2. the value of the style designator from the barcode on the ballot 
                                        #      or pstyle_num, printed style num, if available.
        style_rois_list=None,           # if run right after genrois, this will be initialized.
        #rois_map_df=None,              # initialize this dataframe before entry, then append to it.    
        contests_dod=None,              # ballot information as provided in the EIF. If None, will be read
        style_to_contests_dol=None,     # contests in each style, if available, probably from CVR or manually generated. (optional)
    ):
    """
    This function processes a template with known style_num, 
    but without knowing the contests mapped to the style
    It determines the style based on OCR mapping.
    To use this method, the ballots must not have gray backgrounds and
    must be pretty clear so matching contests is feasible.
    
    There are three cases:
        1. The list of contests for this style is completely known. 
            In this case, this algorithm will work the same as map_one_style()
        2. The list of contests for each style is known, perhaps derived from CVR,
            but the contests on a given ballot card_code is not known. This occurs when
            the card_code cannot be used to look up the contests in the style without
            a large amount of reverse engineering. The style_to_contests_dol 
            is converted to the contest_tree_dol which can reduce the search space.
        3. The list of contests on any style is completely unknown, however we have
            the contests_dod which is the EIF describing all the contests, options,
            and how they will be found on the ballot. In this case, the algorithm
            searches across all contests, but once the first contest is found, it
            only searches later contests.
    
    
    returns rois_map_df, error_flag for this style    
    """
    """
    Algorithm Description:
        This is a sliding-window matching algorithm. input data:
            rois_list               These may be rois based on graphical decomposition or rois based on OCR extraction with region.
            style_to_contests_dol   Contests in each style
            contests_dod            provides contest names and options as found on actual printed ballots
            style_code              This the card_code or pstyle_num from the ballot.
            style_code_is_key       if the style code is the key, and we have style_to_contests_dol, then no discovery is necessary,
                                    as we know the exact contests on each ballot.
                                    otherwise, either
                                    1. we have style_to_contests_dol but can't index it, to provide contest_tree_dol to reduce the search space.
                                    2. we don't have style_to_contests_dol, so we have to search over all contests.
            
        # The sliding windows have an offset, a range, and a current slip_os
            # rois_window_os          start of the current rois window
            # rois_slip_os            where we are comparing
            # rois_max_slip_os        maximum slip of the window to try to find a match.
            # rois_last_match_os      window position at last match
            # contest_window_os       start of the current contest window
            # contest_slip_os         where we are comparing
            # contest_max_slip_os     where we will give up. = 0 if we know the contests exactly.
                                    # If not 0, then this is used only for the first match, and 
                                    # after that, the max_slip_os is the same as the number of contests left.
            # contest_last_match_os   window position at last match
            
        One contest record will expand to relate to multiple rois records.
        
        0. preprocess OCR strings by correcting common words found in ballot descriptions for common OCR mistakes.
        1. outer loop will search across contests.
            1a. If style_code_is_key, then we know the contests exactly, and no searching is required.
                then, we just step through the contests on that style. This is the same as the old search algorithm.
            1b. otherwise, if style_to_contests_dol, search according to search tree.
                if first contest is not found, then use full search until first contest is found.
                    then continue in tree search. This is necessary if the tree spans multiple sheets.
            1c. full search across all contests. On given ballot, start where we left off.
            2. search over available rois
                current method stops at first match. Could enhance to always included all options to make sure
                the algorithm chooses the best match.
                    If there are two matches within the range of consideration, then log an exception.
                    If there is one match, then 
                        add mapped rois, resolve targets
                    move rois window to just after the match
                    move to next contest

            if the rois_window is exhausted and no matches are found, then:
                if 1a, then error is logged.
                if 1b or 1c move to next contest
                    if all contests are exhausted,
                        if 1b, search over the rest of the contests not already searched.
                    if in full search, then log an error.
            probably need new EIF column num_lines, so we will know how many lines of text are expected.
                this will allow us to combine lines of text, particularly in contest headings and descriptions.

    """

    logs.sts(f"Begin maprois_discover_style, style:{style_num}, initializing", 3)
    #rois_list       = DB.load_rois(style_num=style_num)
    # read one rois structure
    #    styles/roislist/{style_num}-rois.csv                    
    # rois list provides location and ocr_text for each rois -- result of genrois

    if not style_rois_list:
        rois_list = DB.load_data(dirname='styles', subdir=style_num, name=f"{style_num}_rois.json")
    else:
        rois_list = style_rois_list
    
    if not rois_list:
        logs.exception_report(f"rois_list for style:{style_num} was found, but is empty")
        return None, True
    
    for roi in rois_list:
        roi['ocr_text'] = correct_ocr_mispellings_of_common_words_mixedcase(str(roi['ocr_text']))
        if 'ocr_option_text' in roi:
            roi['ocr_text'] = correct_ocr_mispellings_of_common_names_mixedcase(roi['ocr_option_text'])
            
    rois_report = format_rois_list_str(argsdict, rois_list, start_at=0)
    logs.sts(f"ROIs REPORT\n{rois_report}", 3)

    if contests_dod is None:
        # this is the result of parsing the EIF
        contests_dod = DB.load_data(dirname='styles', name='contests_dod.json')
        
    #logs.sts(f"contests_dod:\n{pprint.pformat(contests_dod)}", 3)
        
    style_to_contests_dol = DB.load_data(dirname='styles', name='CVR_STYLE_TO_CONTESTS_DICT.json', silent_error=True)
    
    rois_num            = len(rois_list)
    style_dict          = DB.load_data(dirname='styles', subdir=style_num, name=f'{style_num}_style')
    all_contest_list    = list(contests_dod.keys())     # list of all contests to be considered.
    all_contest_num     = len(all_contest_list)
    fixed_max_orphan_rois     = 2
    
    contest_tree_dol    = None
    prior_contest_str   = None
    style_rois_map_df   = pd.DataFrame(columns=ROISMAP_COLUMNS)
    

    rois_window_os      = 0     # current location in list of rois. Once a set of rois are mapped to a contest, this is moved to the first unused roi.
                                # if there are unused rois in between contests, then we may have to slip the matching window over these dead rois.
    rois_max_slip       = argsdict.get('maprois_max_slip_os', 3)           # how much further will algorithm search after non match.
    contest_max_slip_os = argsdict.get('contest_max_slip_os', 1000)         # how much further will algorithm search after non match.
                                # this should be set to the number of initial contests that need to be considered at first to get to the 
                                # first contest of this style. If -1, will search all contests.
                                # NOTE: if multiple page ballot, we may want an initial_os that relates to the subsequent pages.
    mapping_mode        = argsdict.get('mapping_mode', 'exact')                
                                # either:
                                #   'exact' - style_num is key to style_to_contests_dol
                                #               the exact list of contests is available.
                                #   'tree'  - style_num is not key to style_to_contests_dol.
                                #               but style_to_contests_dol exists. Search over tree of contests.
                                #   'full'  - style_to_contests_dol is missing.
                                #               search across all contests.
    
    logs.sts(f"maprois_discover_style initialized, style:{style_num} considering {all_contest_num} contests and {rois_num} rois using {mapping_mode} mode.", 3)
    sts = ''
    
    contest_idx = 0
    if style_to_contests_dol:
        if mapping_mode == 'exact':
            contest_list = style_to_contests_dol[style_num]
        elif mapping_mode == 'tree':
            # construct contest tree from style_to_contests_dol.
            # contest tree has structure where root of tree is at key==None.
            # each dictionary item provides a list of branches.
            # if None is included as a branch, it indicates termination.
            if not style_to_contests_dol:
                logs.exception_report("EXCEPTION: no style_to_contests_dol mapping is available."
                    " use 'mapping_mode' == 'full' to search for style mapping anyway."
                    " or add 'manual_styles_to_contests_filename' directive to input file. Aborting.")
                sys.exit(1)

            logs.sts(f"original style_to_contests_dol: {pprint.pformat(style_to_contests_dol)}", 3)
            contest_tree_dol = utils.get_next_item_dol(style_to_contests_dol)
            logs.sts(f"Style_to_contestcontest_tree_dol: {pprint.pformat(contest_tree_dol)}", 3)
    else: 
        mapping_mode = 'full'
        contest_list = all_contest_list

    #import pdb; pdb.set_trace() 
    
    fully_mapped = False
    while True:
        # at this point, contest has just been matched.
        # adjust contest_search_list and rois_window_os
        # deal with exhausting rois or contests in each case.
    
        if mapping_mode == 'exact':
            if contest_idx >= len(contest_list):
                # normal end to contest mapping in 'exact' mode
                # all contests have been matched.
                fully_mapped = True
                
                # @@TODO
                # could check to see if an inordinate number of rois exist
                # which could mean that the style is improperly defined.                
                
                break
            # create contest_search_list with one item
            contest_search_list = [contest_list[contest_idx]]
            contest_idx += 1
            
            max_orphan_rois = calc_max_orphan_rois(contest_search_list, contests_dod)
            # At least one more contest remains to be mapped.
            if rois_window_os >= len(rois_list) - max_orphan_rois:
                # but insufficient rois exist for this contest
                fully_mapped = False
                break

        elif mapping_mode == 'full':
            if prior_contest_str:
                # after successful match, matchable contests are only available
                # from the rest of the contest list, after this match.
                contest_idx = all_contest_list.index(prior_contest_str) + 1
                contest_search_list = all_contest_list[contest_idx:contest_idx+contest_max_slip_os]
            else:
                #contest_idx = 0
                contest_search_list = all_contest_list
        
            max_orphan_rois = calc_max_orphan_rois(contest_search_list, contests_dod)
            
            if rois_window_os >= len(rois_list) - max_orphan_rois:
                # insufficient rois exist to hold any prospective contests
                # this is a common situation, and it is not an error.
                # this is the normal loop exit for this mode.
                fully_mapped = True
                break
            logs.sts(f"rois_window_os:{rois_window_os} len(rois_list):{len(rois_list)}", 3)
                
            if contest_idx >= len(all_contest_list):
                if len(rois_list) - rois_window_os > fixed_max_orphan_rois:
                    logs.sts(f"WARN: full mode matching, contests depleted but {len(rois_list) - rois_window_os} rois remain", 3)
                # all contests have been matched.
                fully_mapped = True
                break

        else:   # mapping_mode == tree
            contest_search_list = contest_tree_dol[prior_contest_str]
            termination_okay = False
            if None in contest_search_list:
                termination_okay = True
                contest_search_list.remove(None)      # this will remove None from contest_search_list if it exists.
            if not contest_search_list:
                # there are no next_contests in the list.
                fully_mapped = True
                break
            utils.sts(f"Considering contests in contest_tree after matching contest {prior_contest_str}:\n{contest_search_list}", 3)
            max_orphan_rois = calc_max_orphan_rois(contest_search_list, contests_dod)

            if rois_window_os >= len(rois_list) - max_orphan_rois:
                # Not enough rois exist
                # this is a common situation, and it is not an error.
                # this is the normal loop exit for this mode.
                
                if termination_okay:
                    fully_mapped = True
                    break
                else:
                    logs.sts(f"WARN: tree mode matching, rois depleted but termination not okay after {prior_contest_str}, "
                             f"expected one of the following\n{contest_search_list}" , 3)
        
        rois_idx_range = range(rois_window_os, rois_window_os + rois_max_slip)
        
        
        # look through the available contest list and attempt to match to the rois window
        for contest_str in contest_search_list:

            contest_dict = contests_dod[contest_str]
           
            map_info = match_contest_in_rois_range(argsdict, contest_dict, rois_list, rois_idx_range)

            if map_info['match_bool']:
                # accept the first match. 
                # does not check all possibilities and accept the best.
                break
                
        if not map_info['match_bool']:
            # no match but one was expected.
            # in exact mode, it may be alright to assume the match exists, and 
            # then continue at the next contest to see if the rest will map.
            # this was used in the original algorithm and can help if the ballots
            # are very hard to read.
            if termination_okay:
                fully_mapped = True
                break
            logs.exception_report(f"mapping_mode:{mapping_mode} style {style_num} "
                f"failed to map at rois_windows_os {rois_window_os} and contest {contest_str}")
            fully_mapped = False
            break

        # one match has been identified. This algorithm maps the entire contest at one time.
        # Once a match has been confirmed, then we must process all the rois that are included.
        # order_list provides the indexes of the ballot_options that should be used for each rois.
        # update the rois with the official name and add to rois_map_dict
        # no need for layout parameters or targ_os_type
        
        prior_contest_str = contest_str
        
        err_flg, style_rois_map_df = \
            add_contest_to_rois_map(
                argsdict, 
                style_rois_map_df, 
                rois_list, 
                style_dict, 
                contest_dict, 
                map_info)
        
        rois_window_os = map_info['next_rois_idx']
        
        sts += map_info['sts']
        
           
    sumformat = "%1.1s|%30.30s | %30.30s | %-40.40s\n"
    
    summary_str = ( sumformat % (' ', '=' * 30, f"Style {style_num:10} Summary", '=' * 40) +
                    sumformat % ('?', 'contest name', 'option', 'ocr_name'))
                    
    for index in range(len(style_rois_map_df.index)):
        rois_map_dict = style_rois_map_df.iloc[index]
        contest = rois_map_dict['contest']
        option = rois_map_dict['option']
        ocr_text = rois_map_dict.get('ocr_text', '')
        ocr_text = re.sub('[\n\r]', ' ', ocr_text)
        match_chr = ' ' if rois_map_dict['match_bool'] else '?'
        summary_str += sumformat % (match_chr, contest[:50], option[:20], ocr_text[:60])
        
    if not fully_mapped:

        summary_str += (
            f"EXCEPTION: Style {style_num}: Unable to locate rois match starting at " +
            f"{rois_window_os} prior_contest_str: '{prior_contest_str}'\n" +
            format_rois_list_str(argsdict, rois_list, start_at=rois_window_os) + "\n"
            )
        if argsdict.get('save_failed_styles_to_assist_folder', False):
            logs.exception_report(summary_str + "\n" + sts)
            # copy templates that did not map to assist folder.
            # this copies both pages (if available) of templates and redlines to assist folder.
            DB.copy_template(style_num, 'assist')
        
        # add additional diagnostics to map_report only when an error is detected.
        logs.append_report(('=' * 50) + "\n" + sts + "\n", rootname='map_report')
        
        # this is somewhat hard to do, should probably just use the failed log file.
        DB.update_dict(dirname='styles', name=f'{style_num}_style', subdir=style_num, field='style_failed_to_map', value=(not fully_mapped))
        
    logs.sts(summary_str, 3)
    logs.append_report(summary_str + "\n\n", rootname='map_report')

    
    return style_rois_map_df, (not fully_mapped)
    

def add_contest_to_rois_map(argsdict, rois_map_df, rois_list, style_dict, contest_dict, map_info):

    contest_str = contest_dict['contest_str']
    vote_for    = contest_dict['vote_for']
    rois_os     = map_info['contest']['rois_os']
    style_num   = style_dict['style_num']
    
    logs.sts(f"Adding contest to rois_map_df: {contest_str}", 3)
    #logs.sts(f"map_info\n" + pprint.pformat(map_info), 3)    
    logs.sts(f"Style {style_num}, Contest '{contest_str}' matched at offset {rois_os}")
    rois_list[rois_os]['official_name'] = contest_str
    
    # add contest header
    rois_map_dict = create_rois_map_dict(
        argsdict,
        rois_list[rois_os], 
        style_dict,
        contest_str,
        option_name=f'#contest vote_for={vote_for}',
        map_info=map_info, 
        #layout_params={},
        #targ_os_type = 'norm_targ_os',
        )
    rois_map_df = rois_map_df.append(rois_map_dict, ignore_index=True)
    
    err_flg, rois_map_df = set_contest_targets(
        argsdict, 
        rois_list, 
        rois_map_df, 
        contest_dict, 
        style_dict, 
        map_info)

    return err_flg, rois_map_df
    
    
def calc_max_orphan_rois(contest_list, contests_dod):
    """ given list of contests being considered for 
        mapping to remaining rois, determine the 
        minimum number of rois required, and thus
        the max orpham rois is one less than that.
    """
    if not contest_list:
        return 0
    
    rois_num = []
    for contest_str in contest_list:
        contest_dict = contests_dod[contest_str]
        rois_num.append(int(contest_dict['min_rois_num']))
        
    min_rois_needed = min(rois_num)
    
    return max([0, min_rois_needed - 1])
        

def maprois(argsdict, chunk_name: str = '', style_num: str = ''):
    """
    This function is the width-first version, which is not used
    by lambdas. They use maprois_one_style() only, as each style
    is processed fully by one lambda.
    """

    dirname = 'styles'
    df_name = 'rois_map_df'
    utils.sts('Mapping rois', 3)
    if not style_num:
        # lists rois based on the files that exist.
        style_nums_list = DB.get_style_nums_with_templates(argsdict)
    # this loads and parses the EIF
    contests_dod = create_contests_dod(argsdict)
    #DB.save_style(name='contests_dod', style_data=contests_dod)
    DB.save_data(data_item=contests_dod, dirname='styles', name='contests_dod.json')

    # if the CVR is available, we can get a list of styles that are associated with a ballot_type_id.
    # this may be enough to know exactly what contests are on a given ballot, but only if the 
    # style which keys this list is also directly coupled with the card_code read from the ballot.
    # In some cases, such as Dane County, WI, this is a 1:1 correspondence. But SF has an complex
    # style conversion which is nontrivial to figure out. 
    # thus, this is still needed in style discovery.

    style_to_contests_dol = DB.load_data(dirname='styles', name='CVR_STYLE_TO_CONTESTS_DICT.json', silent_error=True)
    if not style_to_contests_dol:
        style_to_contests_dol = convert_cvr_to_styles(argsdict, silent_error=True)
        if not style_to_contests_dol:
            style_to_contests_dol = get_manual_styles_to_contests(argsdict, silent_error=True)
        if style_to_contests_dol:
            DB.save_data(data_item=style_to_contests_dol, dirname='styles', name='CVR_STYLE_TO_CONTESTS_DICT.json')    
        
    rois_map_df = pd.DataFrame(columns=ROISMAP_COLUMNS)
    
    # style overrides are used only when the contest name cannot be read and there are no options other than writeins
    style_overrides_dod = get_map_overrides(argsdict)
    included_style_nums = argsdict.get('include_style_num', [])
    excluded_style_nums = argsdict.get('exclude_style_num', [])
    
    total_mapping_errors = 0
    unmapped_styles = []
    for style_num in style_nums_list:
        if (style_num in excluded_style_nums or
            included_style_nums and not style_num in included_style_nums):
            #utils.sts(f'Excluding Style {style_num} as specified in input file.', 3)
            continue

        if not argsdict.get('use_style_discovery', False):
            # this is the conventional approach 
            # requires that we know the correspondence of styles to contests for each style prior to mapping.
            if not argsdict['all_styles_have_all_contests']:
                if False: #argsdict.get('election_name', '') == 'San Francisco Consolidated Presidential Primary 2020-03':
                
                    ballot_type_id = str(int(style_num[-3:]))                           # extract ballot_type_id, zap leading zeroes
                    multi_sheet_contest_list = style_to_contests_dol[ballot_type_id]         # this a unified contest list including both sheets
                    sheet0 = int(style_num[2:3]) - 1                                    # extract sheet0 number from style_num

                    # the following function splits the contest list based on the sheet0 attribute for each contest in original list.
                    grouped_dol = utils.group_list_by_dod_attrib(multi_sheet_contest_list, contests_dod, 'sheet0')
                    contest_list = grouped_dol[sheet0]
                else:
                    contest_list = style_to_contests_dol[style_num]
            
            style_rois_map_df, error_flag = maprois_one_style(
                argsdict, 
                style_num, 
                contest_list, 
                #rois_map_df, 
                contests_dod, 
                style_overrides_dod)
        else:
            # style_discovery means we don't know the contests assigned to a given style before it is is processed.
            #   contests are assigned to the style as it is processed.
            #   Style discovery is appropriate if the ballot will easily OCR and using 'use_ocr_based_genrois'
            #   Can be used in two situations:
            #       1. there is no cvr at all, and no style mapping.
            #       2. we have a style_to_contests_dol either from CVR or manual mapping, but we don't know the card_code map.
        
            style_rois_map_df, error_flag =  maprois_discover_style(
                argsdict,
                style_num,
                contests_dod=None,               # will read from file if this is None on first pass
                style_to_contests_dol=style_to_contests_dol,
                #rois_map_df=rois_map_df,
                )


        if error_flag:
            unmapped_styles.append(style_num)
            total_mapping_errors += 1
            
        create_redlined_images(argsdict, style_num, style_rois_map_df)
        
        rois_map_df = rois_map_df.append(style_rois_map_df)
        
    merged_styles = {}                      # dict with key of merged style, value is mapped style that is similar.
    unmerged_styles = []                    # list of style that failed and could not be merged.
    # try to find similar styles to adopt if the styles did not map.
    #import pdb; pdb.set_trace()
    
    for style_num in unmapped_styles:
        # similar styles
        similar_styles = find_similar_styles(style_num, style_to_contests_dol)
        for similar_style in similar_styles:
            if not similar_style in unmapped_styles and not get_style_fail_to_map(similar_style):
                # found a similar style that successfully mapped:
                merged_styles[style_num] = similar_style
                break
        else:
            # no similar style found
            unmerged_styles.append(style_num)

    #DB.save_df_csv(name=df_name, dirname=dirname, df=rois_map_df)
    DB.save_data(data_item=rois_map_df, dirname=dirname, name=df_name, format='.csv')

    num_styles = len(style_nums_list)
    summary_str = f"Total of {total_mapping_errors} errors in {num_styles} styles attempted." \
              f"{ round(100 * (num_styles - total_mapping_errors)/num_styles, 2) }% success rate.\n" \
              f" Unmapped styles: {unmapped_styles}\n" \
              f"Merged styles: {merged_styles}\n" \
              f"Failed and unmerged styles (these must still be fixed):{unmerged_styles}" 
    utils.append_report(summary_str + "\n\n", rootname='map_report')
    utils.sts(summary_str, 3)
    
          
def get_status_genmaprois(argsdict):            
    pass