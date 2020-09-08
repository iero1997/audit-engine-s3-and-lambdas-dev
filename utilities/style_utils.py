import os
#import re
#import sys
import string
#import logging

import cv2
import numpy as np
#import pandas as pd

from utilities import utils, logs
from utilities.utils import list_from_csv_str
from utilities.config_d import config_dict
from utilities.alignment_utils import choose_unstretched_ballot, stretch_fix_ballots
#from utilities.cvr_utils import get_replacement_cvr_header
from models.DB import DB
from models.Style import Style
#from models.Style import get_eif_model
#from models.CVR import CVR
#from . import ocr


def get_map_overrides(argsdict):
    """ In some cases, the contest name cannot be reliably read from the template
        and if there are no options to match (except write-in), then it is not
        normally possible to match these up. Therefore, the input directive
        'style_map_override' can be used for each such case. The value of this
        directive is a comma-separated list of three fields:
        style, official_contest_name, and rois_map_os
        The official_contest_name may be quoted, and if so, quotes are removed.

        multiple overrides may exist in the input file.
        
        In operation, if during mapping, the mapping would normally fail, then
        this information can be used to force the mapping to a specific offset
        where the contest name does not match but the write-in field does, and
        no options match.
        
        This function simply pre processes this file to get it ready if it exists.
    """
    style_overrides_dod = {}
    if argsdict.get('style_map_override'):
        for style_map_override in argsdict['style_map_override']:
            style_spec, off_contest_name, rois_os = list_from_csv_str(style_map_override)
            style_spec = str(style_spec)
            rois_os = int(rois_os)
            style_overrides_dod.update({style_spec: {off_contest_name: rois_os}})
    return style_overrides_dod


def is_style_exist(style_num):
    """
        APPARENTLY UNUSED FUNCTION
        Check the styles path whether style
        with provided id already exist.
    """
    return os.path.exists(f"{config_dict['STYLES_PATHFRAG']}{style_num}.json")


def get_ballot_number_area(image):
    """
        Return a cropped image which should contain a ballot decimal
        number within representing ballot code (ballot number ROI).
    """
    y_pos   = config_dict['NUMBER_ROI']['y']
    x_pos   = config_dict['NUMBER_ROI']['x']
    height  = config_dict['NUMBER_ROI']['h']
    width   = config_dict['NUMBER_ROI']['w']
    cropped_image = image[y_pos:y_pos + height, x_pos:x_pos + width]
    return cropped_image


def get_weighted_image(weighted, images):
    """
        Generate a weighted image based on one image passed as
        'weighted' and a list of similar 'images', then normalize.
    """
    for i, image in enumerate(images):
        weighted = cv2.addWeighted(
            weighted, 1.0 - (1.0/(2.0 + i)),
            image,
            1.0/(2.0 + i),
            0.0
        )
    weighted = cv2.normalize(weighted, weighted, 0, 255, cv2.NORM_MINMAX)
    return weighted


def get_number_from_string(_string: str) -> int:
    """
    THIS MAY BE UNUSED.
    Returns a number for a passed string object.
    For example: 'Vote for One' returns 1

    :param _string: The string to be processed.
    :return: An integer representation of the word e.g. one -> 1.
    """
    units = [
        "zero", "one", "two", "three", "four",
        "five", "six", "seven", "eight", "nine",
    ]
    # maps punctuation chars to ' ' string for easier removal
    punctuation_map = str.maketrans({p: ' ' for p in string.punctuation})
    for word in _string.translate(punctuation_map).split():
        word = word.lower()
        if word in units:
            return units.index(word)



def link_dashed_lines(image):
    new_image = image.copy()
    new_image = cv2.bitwise_not(new_image)
    kernel_line = np.ones((1, 30), np.uint8)
    kernel_line[0][0] = 0
    kernel_line3 = np.ones((1, 30), np.uint8)
    clean_lines = cv2.erode(new_image, kernel_line, iterations=6)
    clean_lines = cv2.dilate(clean_lines, kernel_line, iterations=6)
    _, clean_lines = cv2.threshold(clean_lines, 15, 255, cv2.THRESH_BINARY_INV)
    new_image =  cv2.bitwise_not(cv2.bitwise_and(cv2.bitwise_not(new_image), clean_lines))
    clean_lines = cv2.erode(new_image, kernel_line3, iterations=6)
    clean_lines = cv2.dilate(clean_lines, kernel_line3, iterations=6)
    _, clean_lines = cv2.threshold(clean_lines, 15, 255, cv2.THRESH_BINARY_INV)
    return cv2.bitwise_and(cv2.bitwise_not(new_image), clean_lines)


def get_weighted_image_from_page(page: int, ballots: list) -> np.ndarray:
    """Gets weighted image from the 'ballots' list of the specific 'page'.
    :param page: Number of page of which we want weighted image from.
    :param ballots: List of 'Ballot' instances from which pages are taken.
    :return: Image saved as 'np.ndarray'.
    """
    images = list(map(lambda ballot, p=page: ballot.ballotimgdict['images'][p], ballots))
    weighted_image = get_weighted_image(images.pop(), images)
    blurred_image = cv2.GaussianBlur(weighted_image, (0, 0), 3)
    weighted_image = cv2.addWeighted(weighted_image, 3.5, blurred_image, -2.5, 0.0)
    return weighted_image


def add_mask_to_image(image: np.ndarray) -> np.ndarray:
    """Runs few functions to put masking on passed 'image'.
    :param image: Image on which we want to put mask on.
    :return: Image saved as 'np.ndarray'.
    """
    _, mask = cv2.threshold(image, 190, 255, cv2.THRESH_BINARY_INV)
    bk = np.full(image.shape, 255, dtype=np.uint8)  # white bk
    fg_masked = cv2.bitwise_and(image, image, mask=mask)
    mask = cv2.bitwise_not(mask)
    bk_masked = cv2.bitwise_and(bk, bk, mask=mask)
    return cv2.bitwise_or(fg_masked, bk_masked)


def save_style_ballot_images(ballots: list, style_num):
    for ballot in ballots:
        utils.sts(f"Saving images for ballot {ballot.ballotdict['ballot_id']}", 3)
    
        DB.save_data_list(
            data_list=ballot.ballotimgdict['images'], 
            dirname='styles', 
            name=ballot.ballotdict['ballot_id'], 
            format='.png', 
            subdir=style_num
            )
        # DB.save_ballot_images(
            # ballot_id=ballot.ballotdict['ballot_id'],
             # images=ballot.ballotimgdict['images'],
             # dirname='styles',  #image_path=f"{config_dict['RESOURCES_PATH']}{config_dict['STYLES_PATHFRAG']}{style_num}/",
             # style_num=style_num,
        # )


def save_style_template_images(style_num, images: list):
    """ returns list of pathnames saved """
    return DB.save_template_images(**{'style_num': style_num, 'images': images})


def load_style_template_images(style_num):
    return DB.load_template_images(**{'style_num': style_num})


def in_boundary(number: int, min_val: int = None, max_val: int = None) -> bool:
    """Checks if 'number' is between 'min' and 'max' values.
    :param number: Number to check.
    :param min_val: Minimal value.
    :param max_val: Maximal value.
    :return: True if 'number' is between boundaries.
    """
    if min_val is not None and number < min_val:
        return False
    if max_val is not None and number > max_val:
        return False
    return True


def filter_contours(contours: list, min_w: int = None, max_w: int = None, min_h: int = None,
                    max_h: int = None) -> list:
    """Filters list of contours to passed dimensions.
    :param contours: List of contours to filter.
    :param min_w: Minimal width of the contour.
    :param max_w: Maximal width of the contour.
    :param min_h: Minimal height of the contour.
    :param max_h: Maximal height of the contour.
    :return: List of filtered contours.
    """
    filtered_contours = []
    for contour in contours:
        approximated_contour = cv2.approxPolyDP(
            contour,
            config_dict['SHAPE_APPROX_VALUE']['other'] * cv2.arcLength(contour, True),
            True,
        )
        _, _, width, height = cv2.boundingRect(approximated_contour)
        if in_boundary(width, min_val=min_w, max_val=max_w)\
                and in_boundary(height, min_val=min_h, max_val=max_h):
            filtered_contours.append(contour)
    return filtered_contours


def get_min_standard_deviation_index(numbers: list, index_range: int = 50) -> int:
    """Iterates over the indexes of 'numbers' and calculates the
    standard deviation. Then returns the index of minimal standard
    deviation.
    :param numbers: List with numbers to look standard deviation in.
    :param index_range: Range of the indexes which should be calculated
    from the 'numbers' list at a time.
    :return: Index of the minimal standard deviation.
    """
    if len(numbers) < index_range * 2:
        print('Length of the list with numbers is lower than twice the range')
        return 0
    standard_deviations = []
    for index in range(len(numbers)):
        if index + index_range < index_range * 2:
            standard_deviations.append(np.std(numbers[index:index + index_range - 1]))
    return standard_deviations.index(min(standard_deviations))


def sum_determinants(ballot, first=True):
    """Returns sum of 'determinants'.
    :param ballot: Instance of ballot to check determinants sum.
    :param first: Should first determinant be returned.
    """
    if ballot.ballotdict['determinants']:
        if first:
            return ballot.ballotdict['determinants'][0]
        return sum(ballot.ballotdict['determinants'])
    return 0


def generate_style_template(argsdict: dict, ballots: list, style_num, sheet0=0, omit_ballot_images=False):
    """
    ACTIVE 
    Function which takes a list of Ballot instances and generate
    a new style template with information like ballot code, number
    and regions of interests (ROI). To achieve that, function creates
    a weighted image of ballot based on a list of all passed 'ballots'
    (they should be in similar alignment and shape). Then function looks
    for ROIs and extract data contained within weighted image with OCR tool.
    
    TO MOVE THIS TOWARD IMPLMENTATION COMPATIBLE WITH LAMBDAS
    1. the caller this function should, instead of generating a list of Ballot instances
        with the image already extracted from the file, into just a list of pathnames
        to process. So the Queues.py class should be oriented to just keeping a single
        dict of list structure, where the key of the dict is the style_num, and the
        list containing the ballots pathnames that are of that style.
    2. We must add an intermediate function to make this conversion, which will
        take that list and for each ballot, open it and load the images for each file, 
        and then call this function. Let's assume we call that function
        'generate_style_template_from_paths(ballot_paths: list, style_num)'
        It will be the appropriate operation type that can be ported to work on lambdas.
    3. The result of this function will be only the combined template. It will be
        reasonable to continue with the subsequent steps for this style, such as
        genrois and maprois. Those functions take the combined template plus
        EIF file information to finally generate at roismap_df for the style.
        Each roismap_df is combined together after all lambdas are competed to 
        produce the roismap_df which is later used in the extraction process.
    4. Result of style generation lambda will be:
        1. list of pathnames actually used in the style generation, in cause some were
            inappropriate or unusable.
        2. roismap_df for that style.
        3. combined template with redlines of the rois that are mapped to it.
        
    sheet value is simply added to the style dict. The sheet is used for any later 
    drawing of lines which may only be appropriate for one of the sheets.
        
    """
    #use_sync_timing = True
    
    utils.sts(f"Generating ballot style templates for style {style_num} using {len(ballots)} ballots...", 3)
    if not ballots:
        utils.exception_report("generate_style_template: List of ballots is empty")
        return False
        
    #ballots.sort(key=sum_determinants)
    ballots = ballots[:config_dict['LAYERS_FOR_EMPTY_BALLOT']]  # consider first ballots. Maybe better to choose ballots with least stretch
    style = Style(style_num=style_num)
    style.sheet0 = sheet0
    style.target_side = argsdict['target_side']
    style.build_from_count = len(ballots)
    style.precinct = ballots[0].ballotdict['precinct']
    style.build_from_ballots = [ballot.ballotdict['ballot_id'] for ballot in ballots]
    weighted_images = []
    pages = range(len(ballots[0].ballotimgdict['images']))
    
    utils.sts("Generating the average timing marks for minimal corrections", 3)
    std_ballot_num = choose_unstretched_ballot(ballots)
    
    utils.sts("stretch_fix all ballots to std_timing_marks", 3)
    stretch_fix_ballots(argsdict, ballots, std_ballot_num)

    # first save them so we can diagnose any problem.
    if argsdict['save_checkpoint_images'] and not omit_ballot_images:
        utils.sts("Saving checkpoint images...", 3)
        #confirmed this is working to s3.
        save_style_ballot_images(ballots, style_num)

    utils.sts("Combining images to create template for each page...", 3)
    for page in pages:
    
        if not (page and (ballots[0].ballotdict.get('p1_blank', False) or
                            not ballots[0].ballotdict.get('timing_marks', []))):
            
            weighted_images.append(get_weighted_image_from_page(page, ballots))

    # image templates must be saved outside style
    utils.sts("Saving style template images...", 3)
    style.filepaths = save_style_template_images(style_num, weighted_images)
   
    style.timing_marks = ballots[std_ballot_num].ballotdict['timing_marks']

    utils.sts("Saving style object...", 3)
    #DB.save_style(name=style_num, style_data=vars(style))
    DB.save_data(data_item=vars(style), dirname='styles', subdir=style_num, name=f'{style_num}_style')
    
    """
    style_dict saved at this point:
        'build_from_count':     int number of ballots included in the generation of the template
        'precinct':             str precinct designation
        'build_from_ballots':   list of ballot_ids that were used to build the template.
        'filepaths':            list of template files produced
    """
    utils.sts("Saved combined image tamplates...", 3)
    return True


def gen_style_filepaths(style_num):
    #style_dict = DB.load_style(**{'name': style_num})
    style_dict = DB.load_data(dirname='styles', subdir=style_num, name=f'{style_num}_style', silent_error=True)
    
    try:
        return style_dict['filepaths']
    except TypeError:
        return None


def find_similar_styles(style_num, style_to_contests_dictoflist) -> list:
    """ In many cases, styles that cannot be built can adopt the roismap of other similar styles.
        That is valid if the styles have the same contests on the ballot and they do not differ
        in other respects, such as language.
        
        style_num -- the style that we want to find similar styles
        style_to_contests_dictoflist -- dictionary with style_num(str) as key and list of contests.
        
        No need to worry about processing time because this is rarely used, only when a style fails to map
        at the end of maprois.
    """
    
    target_contestlist = style_to_contests_dictoflist.get(style_num)
    similar_styles = []
    for style_key, style_contest_list in style_to_contests_dictoflist.items():    
        if style_key == style_num:
            # don't include self
            continue
        if style_contest_list == target_contestlist:
            similar_styles.append(style_key)

    return similar_styles

def get_style_fail_to_map(style_num):

    try:
        style_failed_to_map_dict
    except NameError:
        style_failed_to_map_dict = {}
        
    if not style_num in style_failed_to_map_dict:
        # we have not checked it before.
        
        #style_dict = DB.load_style(name=style_num, silent_error=True)
        style_dict = DB.load_data(dirname='styles', subdir=style_num, name=f'{style_num}_style', silent_error=True)
        if style_dict is None:
            style_failed_to_map_dict[style_num] = True
        else:
            style_failed_to_map_dict[style_num] = style_dict.get('style_failed_to_map', False)

    return style_failed_to_map_dict[style_num]
    

def get_manual_styles_to_contests(argsdict, save=True, silent_error=False) -> dict:
    """
    :manual_styles_to_contests_path str: Path to CSV file with contests and styles table.
    :return: Dict with keys of styles and values of contests list.
    
    @@TODO: This is a user-generated file and should NOT use load_data().
    """
    manual_styles_to_contests_filename = argsdict.get('manual_styles_to_contests_filename')
    if not manual_styles_to_contests_filename:
        return None
    
    manual_styles_to_contests = {}
    
    # check in both EIFs and config for this file.
    mstc_df = DB.load_data('EIFs', name=manual_styles_to_contests_filename, format='.csv', silent_error=silent_error)
    if mstc_df is None:
        mstc_df = DB.load_data('config', name=manual_styles_to_contests_filename, format='.csv', silent_error=silent_error)
        if mstc_df is None:
            return None
            
    for col in mstc_df.columns[1:]:
        stripped_col = col.strip(' ')
        # the following will only work if blank entries are not already changed to ''
        # would be better if we actually detected the '1' or 1 and '0' or 0 or blank.
        
        #manual_styles_to_contests[col] = mstc_df.dropna(subset={col})['contest'].tolist()
        
        manual_styles_to_contests[stripped_col] = mstc_df.loc[mstc_df[col].str.contains('1'), 'contest'].tolist()
        
    return manual_styles_to_contests


