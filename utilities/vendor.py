# vendor.py

import sys

from utilities import utils, logs
from models.DB import DB


def get_layout_params(argsdict: dict):
    """ get the page_layout
        returns list of box sizes. First size will have narrowist columns
        sheet0 and page0 only needed for box_sizes to be correct.
    """
    global LAYOUT_PARAMS_DICT
    
    try:
        if LAYOUT_PARAMS_DICT:
            return LAYOUT_PARAMS_DICT
    except NameError:
        pass
    
    vendor = argsdict['vendor']
    layout_params = {}
    
    # target area should be even so we can divide by two from center.
    layout_params['target_area_w'] = 36
    layout_params['target_area_h'] = 26

    
    if vendor == 'ES&S':
    
        # for ocr_based_genrois,
        # we have the box surrounding the text, and the larger blk_region
        # where this text is found. For each roi, we can modify the blk
        # by accepting the x and w parameters, and setting the y and h
        # parameters according to typical offsets.
        
        # ES&S has nominal timing mark period of 55 pixels, and nom. space of 27
        # thus centerline of timing mark to first gap is 27
        
        layout_params['blk_y_os']   = 27
        layout_params['blk_h_nom']  = 110
    
    
        # the following parameters are related to graphics-first segmentation
        layout_params['h_max_option'] = 105        
        # largest roi that could be an option block
        # this determines if the box will be cropped as option
        # (to exclude target graphic)
        
        layout_params['h_min_option'] = 60
        # option blocks below this are "one-liners" and could be single words
        # that should be converted with tessearact as single words.

        layout_params['v3col'] = {   'w_col': 530,   'w_min': 510,   'w_max': 550,   'h_min': 45,    'h_max': 2500}
        layout_params['v2col'] = {   'w_col': 795,   'w_min': 760,   'w_max': 815,   'h_min': 45,    'h_max': 2500}
        layout_params['v1col'] = {   'w_col': 1590,  'w_min': 1570,  'w_max': 1610,  'h_min': 45,    'h_max':  500}

        if argsdict['target_side'] == 'left':
            # example Dane County 2018
            layout_params['option_crop'] = {
                'top_margin': 5, 
                'btm_margin': 5, 
                'lft_margin': 50, 
                'rgt_margin': 10,
                }
            layout_params['full_crop'] = {  
                'top_margin': 5, 
                'btm_margin': 5, 
                'lft_margin': 5, 
                'rgt_margin': 5,
                }
            # best-guess of target location, based on Dane County
            # for ES&S, analyzed typical roi. 1.5" tall on screen = 54 pixels
            # this is the offset from Top-left corner of the ROI
            # x_os = 0.9" => 32
            # y_os = 0.7" => 26
            layout_params['norm_targ_os'] = {'ref': 'tl', 'x': 32, 'y': 26}
            layout_params['adjust_target_x']  = True
        else:
            utils.exception_report("get_layout_params: target_side: right not defined for ES&S")
            sys.exit(1)

    elif vendor == 'Dominion':
        layout_params['h_max_option'] = 105        
        # largest roi that could be an option block
        # this determines if the box will be cropped as option
        # (to exclude target graphic)
        
        layout_params['h_min_option'] = 60
        # option blocks below this size are "one-liners" 

        layout_params['v3col'] = {   'w_col': 520,   'w_min': 500,   'w_max': 540,   'h_min': 45,    'h_max': 1600}
        layout_params['v2col'] = {   'w_col': 778,   'w_min': 758,   'w_max': 798,   'h_min': 45,    'h_max': 1000}
        layout_params['v1col'] = {   'w_col': 1557,  'w_min': 1537,  'w_max': 1577,  'h_min': 45,    'h_max':  500}
        
        if argsdict['target_side'] == 'left':
            # example Leon County 2018
            layout_params['option_crop'] = {
                'top_margin': 2, 
                'btm_margin': 5, 
                'lft_margin': 60, 
                'rgt_margin': 75,
                }
            layout_params['full_crop'] = {  
                'top_margin': 2, 
                'btm_margin': 2, 
                'lft_margin': 2, 
                'rgt_margin': 5,
                }
            layout_params['norm_targ_os'] = {'ref': 'tl', 'x': 32, 'y': 26}
            layout_params['adjust_target_x']  = True

        else:   
            # 'target_side' == 'right' -- example is SF.
            layout_params['option_crop'] = {
                'top_margin': 2, 
                'btm_margin': 2, 
                'lft_margin': 2, 
                'rgt_margin': 70,
                }
            layout_params['full_crop'] = {  
                'top_margin': 2, 
                'btm_margin': 2, 
                'lft_margin': 2, 
                'rgt_margin': 5,
                }

            layout_params['norm_targ_os'] = {'ref': 'tr', 'x': -45, 'y': 22}
        
            # when yes_no_in_descr == True
            layout_params['comb_yes_targ_os'] = {'ref': 'br', 'x': -45, 'y': -62}
            layout_params['comb_no_targ_os']  = {'ref': 'br', 'x': -45, 'y': -22}
            layout_params['adjust_target_x']  = False

            layout_params['h_max_option'] = 160
            # largest roi that could be an option block
            # this determines if the box will be cropped as option
            # (to exclude target graphic)
        
        
    if argsdict.get('h_max_option'):
        layout_params['h_max_option'] = argsdict['h_max_option']
        
    LAYOUT_PARAMS_DICT = layout_params
    return layout_params

def get_box_sizes_list(argsdict, sheet0: int=0, page0:int=0):

    layout_params = get_layout_params(argsdict)
    
    # this list is universal
    box_sizes_lists_by_layout_type = {
        '3col':     [layout_params['v3col']],
        '2col':     [layout_params['v2col']],
        '1&2col':   [layout_params['v2col'], layout_params['v1col']],     # note: list format with narrower columns first
        '1col':     [layout_params['v1col']],
        }
            
    page_layout_type = get_page_layout_type(argsdict, sheet0, page0)
    if not page_layout_type in box_sizes_lists_by_layout_type:
        utils.exception_report(
            f"Page layout specified ('{page_layout_type}') for sheet0 {sheet0} and page0 {page0} not recognized.\n" 
            f"Must be one of: {box_sizes_lists_by_layout_type.keys()}")
        sys.exit()
        
    box_sizes_list = box_sizes_lists_by_layout_type[page_layout_type]

    return box_sizes_list
    
def get_page_layout_type(argsdict: dict, sheet0=0, page0=0):
    """ get JSON formatted list of layout strings, one per page of each sheet.
        return the layout type for this sheet and page.
    """
    page_layout_specstr = argsdict.get('page_layout', [])
    try:
        # TODO: Dangerous usage of eval. Better approach 'json.loads()'
        # could not get json.loads to work reliably.
        
        page_layout_spec = eval(page_layout_specstr)
        page_layout_type = page_layout_spec[sheet0][page0]
    except (KeyError, TypeError):
        page_layout_type = '3col'
    return page_layout_type
    
global CONV_card_code_TO_ballot_type_id_DICT
CONV_card_code_TO_ballot_type_id_DICT = {}

def get_ballot_type_id_from_card_code(card_code):

    global CONV_card_code_TO_ballot_type_id_DICT
    
    if not CONV_card_code_TO_ballot_type_id_DICT:
        utils.sts("Recovering card_code_to_ballot_type_id_dict")
        #CONV_card_code_TO_ballot_type_id_DICT = DB.load_style(name='CONV_card_code_TO_ballot_type_id_DICT')
        CONV_card_code_TO_ballot_type_id_DICT = DB.load_data(dirname='styles', name='CONV_card_code_TO_ballot_type_id_DICT.json', silent_error=True)
        # if the file does not exist, then None is returned.
        
    try:    
        ballot_type_id = CONV_card_code_TO_ballot_type_id_DICT[card_code]
    except (KeyError, TypeError):
        utils.exception_report("get_ballot_type_id_from_card_code() Logic error: Could not find card_code in conv_dict")
        return None
        
    return ballot_type_id


def dominion_build_effective_style_num(argsdict, card_code, ballot_type_id=None) -> (str, int):
    """ Dominion Ballots from SF 2020-03 use a complex style system.
        The card_code is the value on teh ballot and the balot_type_id
        is derived from the CVR JSON file and identifies broad categories 
        that may indicate different contest option ordering.
        
        Convert the card_code and ballot_type_id to an internally used
        style_num and sheet0 number.
        
        The style_block cannot be used to generate the ballot_type_id.
        BIF files can be scanned to generate conversion from card_code to ballot_type_id.
        
    """        
    style_num = card_code
    sheet0 = 0
    if not argsdict['conv_card_code_to_style_num']:
        return style_num, sheet0
        
    if not ballot_type_id:
        ballot_type_id = get_ballot_type_id_from_card_code(card_code)
        
    if not ballot_type_id:
        return None, None

    election_name = argsdict.get('election_name', '')

    if election_name == 'CA_San_Francisco_2020_Pri':
    
        if (ballot_type_id > 999):
            utils.exception_report(f"dominion_build_effective_style_num -- Type code out of range:{ballot_type_id}")


        # dominion constructs the card_code (code on the ballot) based on the 
        # party, type of ballot NP or regular), language, and sheet.
        # Also, the ballot_type_id provides different option ordering 
        # the core type value is one of the following 57 combinations.
        
        # Lang & Sheet | Party and type (NP or not)  -- core style num is card_code % 57
        #   SP  CH  FI |DEM NPDEM   REP     AI      NPAI    PF      LIB     NPLIB   GRN     NP    sheet_lang
        #   --  --  -- |--- ------  ---     ---     ----    ---     ---     -----   ---     ---   ----------
        #   S1         |1   7       13      19      25      31      37      43      49                 0
        #   S2         |2   8       14      20      26      32      38      44      50      55         1
        #       S1     |3   9       15      21      27      33      39      45      51                 2
        #       S2     |4   10      16      22      28      34      40      46      52      56         3
        #           S1 |5   11      17      23      29      35      41      47      53                 4
        #           S2 |6   12      18      24      30      36      42      48      54      57         5
        #   --  --  -- |--- ------  ---     ---     ----    ---     ---     -----   ---     ---   ----------
        #       party->|1   2       3       4       5       6       7       8       9       0            
        #   1   2   3  <-- lang
        
        # Note that NP ballots do not have sheet 1.
        # S2 of the same language seems to always be the same.
        #
        # For example, card_code = 22454
        # 22545 % 57 = 53. This is GRN party S1 in Tagalog (FI) language.
        #
        # ExternalId in BallotTypeManifest.json appears to be sufficient to discriminate for other reasons.
        #   Later discovered this is not true. There was a thought that the style_block i.e. card_code // 57
        #   would be the same as the ballot_type_id, but it is not, as we proved that multiple style_blocks
        #   are mapped to the same ballot_type_code. 
        # Because ballot_type_id helps discrimnate between option ordering, we also need to include that.
        # ballot_type_id range is 1 to 180. We multiply that by 100 and add the core code.
        # The ballot_type_id applies to both sheets.
        # This is an internal style number used to refer to ballot styles and templates.
        # contests in each style is based on the ballot_type_id, which can be derived from this 
        # style_num by dividing by 100.
        #
        # sheet1 value used in style_num is 1-based but internal sheet0 is 0-based.
            
        try:
            core_style = int(card_code) % 57
            #style_block = int(card_code) // 57
            
            sheet_lang = (core_style - 1) % 6
            if core_style > 54:
                sheet1 = 2
                lang  = core_style - 54
                party = 0
            else:
                sheet1 = sheet_lang % 2 + 1
                lang  = sheet_lang // 2 + 1
                party = (core_style - 1) // 6 + 1
        except:
            utils.exception_report(f"Could not construct effective style_num from card_code:{card_code} and ballot_type_id:{ballot_type_id}")
            
        variety = dominion_ballot_type_to_external_id(ballot_type_id)   
        sheet0 = sheet1 - 1
            
        if str(sheet0) in argsdict.get('non_partisan_sheet0s', []):
            style_num = "%1.1u%1.1u%1.1u%1.1u%3.3u" % (lang, 0, sheet1, variety, ballot_type_id)
        else:
            style_num = "%1.1u%1.1u%1.1u%1.1u%3.3u" % (lang, party, sheet1, variety, ballot_type_id)
            
        #utils.sts(f"style_block:{style_block} ballot_type_id:{ballot_type_id}", 3)
            
        return str(style_num), sheet0
    elif election_name == 'FL_Leon_2018':
        pass    # use style_num and sheet0 as defined.
    else:
        utils.exception_report(f"dominion_build_effective_style_num not defined for this election: {election_name}.")
        sys.exit(1)

    return str(style_num), sheet0


def test_dominion_build_effective_style_num(argsdict):
    return # disabled for now.
    if argsdict['vendor'] != 'Dominion':
        return
    utils.sts("Testing test_dominion_build_effective_style_num(): ", 3, end='')
    errors = 0
    local_argsdict = argsdict
    local_argsdict['non_partisan_sheets'] = []
    result = dominion_build_effective_style_num(local_argsdict, 22454, 3)
    expected = ('3914003', 0)
    if result != expected:
        utils.sts(f"\ndominion_build_effective_style_num(argdict, 22454, 3) should be {expected} was {result}")
        errors += 1
        
    local_argsdict['non_partisan_sheets'] = ['0']
    result = dominion_build_effective_style_num(local_argsdict, 22454, 3)
    expected = ('3914003', 0)
    if result != expected:
        utils.sts(f"\ndominion_build_effective_style_num(argsdict, 22454, 3) should be {expected} was {result}")
        errors += 1

    result = dominion_build_effective_style_num(local_argsdict, 22455, 5)
    expected = ('3921005', 1)
    if result != expected:
        utils.sts(f"\ndominion_build_effective_style_num({'non_partisan_sheets': ['0']}, 22455, 5) should be {expected} was" 
            + f"{result}")
        errors += 1
    
    local_argsdict['non_partisan_sheets'] = ['1']
    result = dominion_build_effective_style_num(local_argsdict, 22402, 6)
    expected = ('1014006', 0)
    if result != expected:   # sheet 0, lang 1 (SP), party 1 (DEM), type 6
        utils.sts(f"\ndominion_build_effective_style_num(argsdict, 22402, 6) should be {expected} = {result}")
        errors += 1

    utils.sts(f"{errors} errors", 3)      

CONV_external_id_TO_ballot_type_id_DOL = {
    1:  [  2,   4,   5,   8,   9,  11,  13,  15,  17,  19,  21,  23,  26,  27,  30,  32,  34,  35,  37,  39],
    2:  [ 41,  43,  45,  48,  49,  51,  53,  55,  57,  59,  62,  64,  65,  67,  69,  71,  73,  76,  78,  80],
    3:  [ 42,  44,  46,  47,  50,  52,  54,  56,  58,  60,  61,  63,  66,  68,  70,  72,  74,  75,  77,  79],
    4:  [  1,   3,   6,   7,  10,  12,  14,  16,  18,  20,  22,  24,  25,  28,  29,  31,  33,  36,  38,  40],
    5:  [ 82,  83,  86,  87,  90,  92,  93,  95,  97, 100, 102, 103, 106, 108, 109, 111, 114, 115, 117, 120],
    6:  [ 81,  84,  85,  88,  89,  91,  94,  96,  98,  99, 101, 104, 105, 107, 110, 112, 113, 116, 118, 119],
    7:  [121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140],
    8:  [142, 143, 146, 147, 149, 152, 153, 155, 157, 159, 161, 163, 165, 168, 169, 171, 173, 175, 177, 180],
    9:  [141, 144, 145, 148, 150, 151, 154, 156, 158, 160, 162, 164, 166, 167, 170, 172, 174, 176, 178, 179],
}

global CONV_ballot_type_id_TO_external_id_DICT
CONV_ballot_type_id_TO_external_id_DICT = {}

def update_CONV_card_code_TO_ballot_type_id_DICT(card_code, ballot_type_id):

    if card_code in CONV_card_code_TO_ballot_type_id_DICT:
        if CONV_card_code_TO_ballot_type_id_DICT[card_code] != ballot_type_id:
            utils.exception_report(f"CONV_card_code_TO_ballot_type_id_DICT is inconsistent. "
            f"card_code:{card_code} provides {CONV_card_code_TO_ballot_type_id_DICT[card_code]} instead of ballot_type_id:{ballot_type_id}")
    else:
        CONV_card_code_TO_ballot_type_id_DICT[card_code] = ballot_type_id



def dominion_ballot_type_to_external_id(ballot_type_id) -> int:
    """ The following converts from the BallotTypeId found in the CVR JSON file into ExternalId 
        This conversion is available in the file BallotTypeManifest.json but was hardcoded here for now.
    """
    global CONV_ballot_type_id_TO_external_id_DICT

    
    if not CONV_ballot_type_id_TO_external_id_DICT:
        # create a straight lookup table for speed.
        CONV_ballot_type_id_TO_external_id_DICT = utils.invert_dol_to_dict(CONV_external_id_TO_ballot_type_id_DOL)
        
    try:    
        external_id = CONV_ballot_type_id_TO_external_id_DICT[ballot_type_id]
    except KeyError:
        utils.exception_report("dominion_ballot_type_to_external_id() Logic error: Could not find ballot_type_id in conv_dict")
        sys.exit(1)
        
    return external_id
    
#    for key, ballot_type_list in CONV_ballot_type_id_TO_external_id_DICT.items():
#        if int(ballot_type_id) in ballot_type_list:
#            return key
          
