import os
import re
import pprint

import numpy as np
import cv2
import json
import sys
#import statistics

from utilities import utils, args, images_utils, logs
from utilities.config_d import config_dict
from utilities.vendor import get_layout_params, get_page_layout_type, get_box_sizes_list
#from utilities.images_utils import 
#from utilities.style_utils import clean_candidate_name
from utilities.images_utils import draw_boxes_on_image
from utilities.alignment_utils import find_boxes, select_boxes, filter_boxes_by_region
from utilities.analysis_utils import create_midgap_list
from models.DB import DB
from utilities.ocr import ocr_text, ocr_to_tsv, ocr_tsv_to_ocrdf, ocr_various_modes, ocr_word, log_misspelled_words


def clean_candidate_name(raw_name):
    """function cleaning candidate string name value"""
    if re.search(r"(write-in)|(witeing)|(wnte-in)|W[rha]ite In", raw_name, flags=re.I):
        raw_name = args.argsdict.get('writein_str','write-in:')
    #clean_name = sanitize_string(raw_name)
    clean_name = re.sub(r'^\s*(\@|\([cr]\))*\s*', '', raw_name)
    clean_name = re.sub(r'\s*(REP|DEM|NPA|LIB|GRN|REF|.EP|.EM|.PA|.IB|.RN|.EF|R.P|D.M|N.A|L.B|G.N|R.F|RE.|DE.|NP.|LI.|GR.)$', '', clean_name)
    clean_name = re.sub(r'^[YV][ea]s$', 'Yes', clean_name)
    
    return clean_name



def link_faulty_h_lines(image: np.array) -> np.array:
    """
    :param image: an array containing base image
    :return: an array containing image with horizontal & vertical lines filled
    Fills horizontal lines within provided image.
    """
    return link_by_kernel(image, np.ones((1, 30), np.uint8))
    
def link_faulty_v_lines(image: np.array) -> np.array:
    """
    :param image: an array containing base image
    :return: an array containing image with horizontal & vertical lines filled
    Fills vertical lines within provided image.
    """
    return link_by_kernel(image, np.ones((30, 1), np.uint8))
    
def link_by_kernel(image, kernel):
    """ apply a kernel to image in both negative and positive.
        returns modified image.
        typically called to link faulty h and v lines
        h_kernel_line = np.ones((1, 30), np.uint8)
    """
    mod_kernel = kernel.copy()
    mod_kernel[0][0] = 0

    image = cv2.bitwise_not(image)

    clean_lines = cv2.erode(image, mod_kernel, iterations=6)
    clean_lines = cv2.dilate(clean_lines, mod_kernel, iterations=6)
    _, clean_lines = cv2.threshold(clean_lines, 15, 255, cv2.THRESH_BINARY_INV)

    image = cv2.bitwise_not(cv2.bitwise_and(cv2.bitwise_not(image), clean_lines))
    clean_lines = cv2.erode(image, kernel, iterations=6)
    clean_lines = cv2.dilate(clean_lines, kernel, iterations=6)
    _, clean_lines = cv2.threshold(clean_lines, 15, 255, cv2.THRESH_BINARY_INV)

    return cv2.bitwise_and(cv2.bitwise_not(image), clean_lines)


def is_in_regex_list(regex_list: str, search_str: str, empty_list_result:bool = True) -> bool:
    """ search for seach_str in list of regexes and return True if found.
        if the list is None or empty, will return the empty_list_result, defaults to True.
        Non-regex items will be matched as fullmatch
    """
    
    if not regex_list:
        return empty_list_result

    for regex in regex_list:
        regex = str(regex)          # make sure it is a str
        if bool(re.fullmatch(regex, search_str)):
            return True
    
    return False
    
    
def parse_region_spec(argsdict, directive_str: str, style_dict: dict, style_num, sheet0, page0, h_max=2800, w_max=1785, midgaps=[]) -> list:
    """ Parse given region_spec_list.

        return list of dicts which are found to be valid
        and apply to this style, page and sheet.
        
    """
    parsed_region_list = []
    region_spec_list = argsdict.get(directive_str, [])
    if not region_spec_list:
        return []
    
    if not midgaps:
        midgaps = create_midgap_list(style_dict, page0)
    num_gaps = len(midgaps)
    if not midgaps:
        return []
    period = midgaps[1] - midgaps[0]
    
    for region_specstr in region_spec_list:
        try:
            region_spec = eval(region_specstr)      # dangerous! but json.loads() is too finicky over syntax.
            reg_y_spec = int(region_spec['y'])      # required spec must parse.
        except:
            utils.exception_report(f"EXCEPTION: region spec {directive_str} '{region_specstr}' did not parse.")
            continue
            
        reg = {}
            
        reg['styles'] = region_spec.get('styles', [])
        reg['exstyles'] = region_spec.get('exstyles', [])
        reg['s'] = int(region_spec.get('s', 0))
        reg['p'] = int(region_spec.get('p', 0))

        if (reg['p'] != page0 or
            reg['s'] != sheet0 or
            not is_in_regex_list(reg['styles'], str(style_num)) or 
            is_in_regex_list(reg['exstyles'], str(style_num), empty_list_result=False)):
            continue

        
        reg_h_min_spec = region_spec.get('h_min', 0)

        reg['x'] = int(region_spec.get('x', 0))
        reg['w'] = int(region_spec.get('w', w_max - reg['x']))
        
        reg['h_or_v'] = region_spec.get('h_or_v', 'h')
        reg['r'] = int(region_spec.get('r', 1))
        reg['ox'] = int(region_spec.get('ox', 0))
        reg['oy'] = int(region_spec.get('oy', 0))

        if (0 <= reg_y_spec < num_gaps):
            # use gap indexes for vertical extents if they are less than num gaps.
            reg['y'] = midgaps[reg_y_spec]
            reg_h_spec = int(region_spec.get('h', num_gaps - reg_y_spec - 1))    # this default not perfect in case of gaps specified
            reg_h_spec = min(reg_h_spec, num_gaps - reg_y_spec - 1)                       # make sure in bounds.
            try:
                reg_b = midgaps[reg_y_spec + reg_h_spec]
            except:
                import pdb; pdb.set_trace()
            reg['h'] = reg_b - reg['y']
            reg['h_min'] = (reg_h_min_spec * period) - period / 2
        else:
            # otherwise, use pixel dimension but snap to midgap grid.
            reg['y'] = min(midgaps, key=lambda x:abs(x-reg_y_spec))
            reg_h_spec = int(region_spec.get('h', h_max - reg['y']))    # this default not perfect in case of gaps specified
            reg_h_spec = min(reg_h_spec, h_max - reg['y'])                       # make sure in bounds.
            reg_b = reg['y'] + reg_h_spec
            reg_b_snap = min(midgaps, key=lambda x:abs(x-reg_b))
            reg['h'] = reg_b_snap - reg['y']
            reg['h_min'] = reg_h_min_spec
            
        # at this point, all region specs are converted to snapped pixels.

        if (reg['x'] + reg['w'] > w_max) or (reg['y'] + reg['h'] > h_max):
            utils.exception_report(f"EXCEPTION: region spec {directive_str} '{region_specstr}' dimensions out of range.")
            continue
        parsed_region_list.append(reg)
    return parsed_region_list
    
    
def apply_human_assisted_lines(argsdict, style_dict, style_num, image, page0=0, sheet0=0, draw_lines=True):
    """ this function applies lines as specified from the directory 'assist' which are generated
        by the helper app which can draw lines on templates and provide the location of those lines as JSON.
        
        Algorithm:
        1. make list of .json files in assist directory.
        2. look for files that match style_num exactly.
        3. parse JSON file and draw lines according to the list.
        4. Return (num_lines_added, first rectangle as active region)
        
    """
    
    utils.sts(f"Processing assist files for {style_num}", 3)
    assist_file_pat = fr"{style_num}-template\d+\.json"
    
    json_file_list = DB.list_files_in_dirname_filtered(dirname='assist', file_pat=assist_file_pat)
    
    # assist_dir = DB.dirpath_from_dirname('assist')
    # if not os.path.isdir(assist_dir):
        # return {}
    # assist_files = os.listdir(assist_dir)
    # json_file_list = [x for x in assist_files if x == assist_filename]
    
    if json_file_list and len(json_file_list) > 1:
        logs.sts(f"LOGIC ERROR: More than one assist file for style:{style_num}, page0:{page0}, sheet0:{sheet0}")
        sys.exit(1)

        assist_file_name = json_file_list[0]
        assist_info_dict = DB.load_data(dirname='assist', name=assist_file_name)
        if assist_info_dict:
        
            lines_list = []
            if draw_lines:
                lines_list = assist_info_dict.get('horizontal_lines', [])
                lines_list.extend(assist_info_dict.get('vertical_lines',[]))
                draw_line_list(style_dict, style_num, lines_list, page0, image)     # modifies image.
        
            rectangle_list = assist_info_dict.get('rectangles', [])
            if rectangle_list:
                return (len(lines_list), rectangle_list[0])     # only one region allowed right now.
            
            return (len(lines_list), {})     # return no constraints in active region.
    
    return (0, {})     # no lines added, no active region specified.

    
def get_active_region_from_assist(argsdict, style_dict, style_num, page0=0):
    """ this function applies lines as specified from the directory 'assist' which are generated
        by the helper app which can draw lines on templates and provide the location of those lines as JSON.
        
        Algorithm:
        1. make list of .json files in assist directory.
        2. look for files that match style_num exactly.
        3. parse JSON file and draw lines according to the list.
        4. Return first rectangle as active region.
        
    """
    
    utils.sts(f"Getting Active Region if available from assist files for {style_num}", 3)
    assist_filename = f"{style_num}-template{page0+1}.json"
    
    assist_dir = DB.dirpath_from_dirname('assist')
    if not os.path.isdir(assist_dir):
        return {}
    assist_files = os.listdir(assist_dir)
    json_file_list = [x for x in assist_files if x == assist_filename]

    if json_file_list:
        assist_file_name = json_file_list[0]
        assist_file_path = f"{assist_dir}{assist_file_name}"
        utils.sts(f"Loading assist file: {assist_file_path}", 3)
        fh = open(assist_file_path, mode='r')
        assist_info_dict = json.load(fh)
        fh.close()
        rectangle_list = assist_info_dict.get('rectangles', [])
        if rectangle_list:
            active_region = rectangle_list[0]
            utils.sts(f"Active Region provided in Assist Files: {active_region}", 3)
            return rectangle_list[0]     # only one region allowed right now.
            
        return {}
    
def add_specified_lines(argsdict: dict, style_dict, style_num, page0, sheet0, image, midgaps=[]):
    """ add lines as specified by input file directives.
        'add_line' directive provides a JSON structures in a list.
        each specification has the following format:
        
        # each entry is JSON dict like {'styles':[set of styles], 's':s, 'p':p, 'x':x, 'y':y, 'h':h, 'w':w, 'r':rep, 'ox':offset_x, 'oy':offset_y}
        # add black boxes (typically lines) based on JSON formatted data.
        # draw on styles listed, on page p of sheet s, starting at x, y and with dimensions h, w
        # if provided, repeat rep times (default is 1) with offset_x, and offset_y as provided as ox, oy
        # x, y required. h, w default to 2. s, p default to 0, rep defaults to 1. ox, oy default to 0
                                    
    """
    
    imgh, imgw = image.shape
    lines_list = parse_region_spec(argsdict, 'add_line', style_dict, style_num, sheet0, page0, imgh, imgw, midgaps=midgaps)
    draw_line_list(style_dict, style_num, lines_list, page0, image, midgaps=midgaps)
    
    
def draw_line_list(style_dict, style_num, lines_list, page0, image, midgaps=[]):
    """ given list of lines, draw them on the page snapped to midgaps
    """
    
    draw_lines_mode = 'above_midgap'
    max_width = 2

    if not midgaps:
        midgaps = create_midgap_list(style_dict, page0)

    imgh, imgw = image.shape
    
    for line_spec in lines_list:
            
        utils.sts(f"Drawing black line for style:{style_num}; {line_spec}", 3)
        
        repeat_num = line_spec.get('r', 1)
               
        for rep in range(repeat_num):
            eff_y = line_spec['y'] + rep * line_spec.get('oy', 0)
            eff_x = line_spec['x'] + rep * line_spec.get('ox', 0)
            
            # snap calculated line to midgaps
            eff_y = min(midgaps, key=lambda x:abs(x-eff_y))
            
            bot = eff_y + line_spec['h']
            top = eff_y 
            if line_spec['h'] > midgaps[1] - midgaps[0]:
                # this is a vertical line
                # will want to snap bottom as well.
                bot = min(midgaps, key=lambda x:abs(x-bot))
                w = min(max_width, line_spec['w'])

            else:
                # it is a horizontal line. draw according to settings.
                h = max(min(max_width, line_spec['h']), 1)

                if draw_lines_mode == 'at_midgap':
                    above = round(h / 1.9)              # bias lines above, min 1.
                    below = line_spec['h'] - above      # this extends one past bottom per range syntax
                elif draw_lines_mode == 'above_midgap':
                    above = h
                    below = 0
                elif draw_lines_mode == 'below_midgap':
                    above = 0
                    below = h
               
                w = line_spec['w']
                bot = eff_y + below
                top = eff_y - above
            
            image[top:bot, eff_x:(w + eff_x)] = 0
        
    return image
    
       
    
    
def find_and_draw_lines_in_regions(argsdict: dict, style_dict, style_num, page0, sheet0, image):
    """ Check to see if there is any find_lines_region directive that apply
        to this style, page, sheet. More than one allowed per image.
        add lines as specified by input file directives.
        
        'find_lines_region',        # Provides a region where lines (either h or v) will be searched for and then drawn
                                    #   {'styles':[set of styles], 's':s, 'p':p, 'x':x, 'y':y, 'h':h, 'w':w, 'h_or_v':'h'or'v', 'snap':'midgap'}
                                    
        y,h coordinates can be in either pixels, with y in range of 59 or higher OR
        gap indexes, where y,h are 58 or lower. This is determined by the number of gaps on the page.
                                    
    """
    diagdisp = False

    midgaps = create_midgap_list(style_dict, page0)

    imgh, imgw = image.shape
    region_list = parse_region_spec(argsdict, 'find_lines_region', style_dict, style_num, sheet0, page0, imgh, imgw, midgaps=midgaps)
    
    tol = 10
    
    for reg in region_list:

        #import pdb; pdb.set_trace()
        utils.sts(f"Finding lines for style:{style_num}; {reg}", 3)
               
        last_line_drawn_y = 0
        if reg['h_or_v'] == 'h':
        
            y_reg_mod = reg['y'] - tol
        
            # get list of midgaps within the region specified
            y_locs = [mg for mg in midgaps if mg >= y_reg_mod and mg <= reg['y'] + reg['h'] + tol]

            for y_loc in y_locs:
            
                # don't try to find lines that are too close together.
                if y_loc < last_line_drawn_y + reg['h_min']: continue
                
                reg_x, reg_w = reg['x'], reg['w']
                utils.sts(f"Checking for line at x:{reg_x}, y:{y_loc}, w:{reg_w}", 3)
                core_line = image[(y_loc-1):(y_loc+2), (reg_x + 10):(reg_x + reg_w - 10)].copy()
                metric = sum(cv2.mean(core_line))
                if metric < 20:
                    # line is completely black
                    utils.sts(f">>>> found existing black line at s:{reg['s']} p:{reg['p']}, x:{reg_x} ,y:{y_loc}, w:{reg_w}", 3)
                    
                    # now look to see if the next region has white background
                    for i in range(8):
                        next_region = image[(y_loc+3+i):(y_loc+4+i), (reg_x + 10):(reg_x + reg_w - 10)].copy()
                        metric = sum(cv2.mean(next_region))
                        # if white, then trigger size limit check
                        if metric > 250:
                            last_line_drawn_y = y_loc
                            break
                    continue
                    
                # the slice includes a bit more so it will include some white bit lines above and below.
                slice = image[(y_loc-4):(y_loc+4), (reg_x + 10):(reg_x + reg_w - 10)].copy()
                if diagdisp:
                    disp_slice(slice)
                    #if y_loc == 1179 and reg_x == 98:
                    #    cv2.imwrite('slice_image.png', slice)
                is_line_present_bool, pixel_location_within_image = \
                    images_utils.check_if_line_present(slice, slice_length=200, line_value=99) #, thicker_than=0, thinner_than=20)
                if is_line_present_bool:
                    utils.sts(f">>>> found line to be darkened at s:{reg['s']} p:{reg['p']}, x:{reg_x} ,y:{y_loc}, w:{reg_w}", 3)
                    image = images_utils.add_line(image, reg_x, y_loc-1, s=3, w=reg_w)
                    if diagdisp:
                        slice = image[(y_loc-4):(y_loc+4), (reg_x + 10):(reg_x + reg_w - 10)].copy()
                        disp_slice(slice)
                        #if y_loc == 1179 and reg_x == 98:
                        #    cv2.imwrite('slice_image.png', slice)
                    last_line_drawn_y = y_loc
        else:
            utils.sts("find_lines_region h_or_v option as 'v' is not yet supported.", 3)
       
    return image
    
def disp_slice(slice):

    slice_h, slice_w = slice.shape    
    
    utils.sts(f"slice h:{slice_h}, w:{slice_w}", 3)
    for i in range(slice_h):
        linestr = ''
        for bit in slice[i][-150:]:
            if bit >= 254:
                linestr += '.'
            else:
                linestr += '#'
        utils.sts(f"{linestr}", 3)
    
    
def gen_page_rois_list(argsdict: dict, style_dict: dict, box_size_list, style_num, page0, sheet0, image):
    """ given an image which is page p, process contours and find
        boxes that make up the ballot, surrounding contests and options
    """

    image_copy = image.copy()
    
    #import pdb; pdb.set_trace()
    num_lines_added = 0
    if argsdict.get('apply_human_assisted_lines', False):
        num_lines_added, active_region = apply_human_assisted_lines(argsdict, style_dict, style_num, page0=page0, sheet0=sheet0, image=image_copy, draw_lines=True)
    else:
        # this only returns the region, if available.
        num_lines_added, active_region = apply_human_assisted_lines(argsdict, style_dict, style_num, page0=page0, sheet0=sheet0, image=image_copy, draw_lines=False)
    
    if not active_region:
        active_region = get_active_region_from_settings(argsdict, style_dict, style_num, sheet0, page0=page0)
    

    if num_lines_added == 0:
        # add manually specified from settings file only if human assisted lines were not added
        
        # if human_assisted_lines are provided, then the active region will be defined.
        # if so, do not process lines specified in the job file.
        image_copy = find_and_draw_lines_in_regions(argsdict, style_dict, style_num, page0, sheet0, image_copy)
        add_specified_lines(argsdict, style_dict, style_num, page0=page0, sheet0=sheet0, image=image_copy)
    
        # saving copy of the image with filled horizontal lines
        # This does not work very well with gray scale "Copy" in the background.
        
        if argsdict.get('link_faulty_lines'):
            cv_style_image_adjusted = link_faulty_h_lines(image_copy)
            cv_style_image_adjusted = link_faulty_v_lines(cv_style_image_adjusted)

    if argsdict['save_checkpoint_images']:
        DB.save_one_image_area_dirname(
            dirname     = 'styles', 
            subdir      = f"{style_num}/rois_parts", 
            style_num   = style_num, idx='', 
            type_str    = f"lines_improved{page0}", 
            image       = cv_style_image_adjusted)

    
    # the following section finds at least the large outlining boxes, but may also find smaller
    # boxes around each contest and each option.
    
    # looking for contours within adjusted image
    _, thresh = cv2.threshold(cv_style_image_adjusted, 
            config_dict['THRESHOLD']['ballot-contours'], 255, 1)
    contours, _ = cv2.findContours(thresh, 1, cv2.CHAIN_APPROX_SIMPLE)
    utils.sts(f'Total of {len(contours)} contours detected', 3)
    
    rois_boxes = find_boxes(contours, addl_attr={'p':page0,'sheet':sheet0})
    utils.sts(f'Total of {len(rois_boxes)} boxes detected', 3)
    
    rois_boxes = select_boxes(box_size_list, rois_boxes)
    utils.sts(f'Total of {len(rois_boxes)} boxes selected after being filtered for size.', 3)

    # reduce selected boxes if active_region is provided.
    page_rois_list = filter_boxes_by_region(active_region, rois_boxes, tol=30)
    utils.sts(f'Total of {len(page_rois_list)} boxes selected in active region.', 3)

    #page_rois_list = remove_outer_boxes(rois_boxes)
    
    utils.sts(f'Filtered to {len(page_rois_list)} rois on sheet {sheet0} page {page0}', 3)

    if argsdict.get('use_ocr_based_genrois'):
        page_rois_list = page_rois_list_by_ocr(argsdict, image_copy, page_rois_list, style_num=style_num, page0=page0)
        
        page_rois_list = sanitize_ocr_text_in_rois_list(page_rois_list)

        utils.sts(f'use_ocr_based_genrois: {len(page_rois_list)} rois on sheet {sheet0} page {page0}', 3)

    return page_rois_list

def page_rois_list_by_ocr(argsdict, image, page_rois_list, style_num, page0=0):
    """
    Given page_rois_list which is a high-level decomposition into blocks, decode each block
    by using OCR_based roi determination.
    """
    utils.sts("Analyzing page_rois_list by ocr", 3)
    new_page_rois_list = []
    for index, blk_region in enumerate(page_rois_list):
        utils.sts(f"Processing block_roi {index}: {blk_region}", 3)
        # use clear method to extract the region so coordinates are unaltered.
        working_image = utils.extract_region(image, blk_region, mode='clear')
        DB.save_one_image_area_dirname(
            dirname     = 'styles', 
            subdir      = f"{style_num}/rois_parts", 
            style_num   = style_num, idx='', 
            type_str    = f"ocr region_{index}", 
            image       = working_image)
        
        # ocr the region and return df of words and coordinates.
        tsv_str = ocr_to_tsv(working_image)
        ocrdf = ocr_tsv_to_ocrdf(tsv_str)
        DB.save_data(tsv_str, dirname='styles', name=f"ocr_result region_{index}.tsv", format='.txt', subdir = f"{style_num}/rois_parts")
        
        initial_ocr_rois_checkpoint_image(argsdict, style_num, image, ocrdf, page0=page0)
        
        # convert the df to rois_list format
        # this includes the surrounding blk_region dimensions
        new_rois = ocrdf_to_rois(argsdict, ocrdf, blk_region, page0=page0)
        logs.sts(f"Decomposed into {len(new_rois)} rois by ocr", 3)
        
        utils.sts(format_rois_list_str(argsdict, new_rois), 3)

        new_page_rois_list.extend(list(new_rois.values()))

    return new_page_rois_list
    
def initial_ocr_rois_checkpoint_image(argsdict, style_num, image, ocrdf, page0=0):
    
    if argsdict['save_checkpoint_images']:

        df_words = ocrdf.loc[ocrdf['level'] == 5]     # select set of rows with level==5, i.e. words.
        
        words_lod = df_words.to_dict(orient='records')
        
        for words_dict in words_lod:
            translate_keys(words_dict)
         
        checkpoint_image = draw_boxes_on_image(image, words_lod, color=['red'], line_width=2, convert_to_RGB=True, prefix_list=[''])
        
        DB.save_one_image_area_dirname(
            dirname     = 'styles', 
            subdir      = f"{style_num}/rois_parts", 
            style_num   = style_num, idx='', 
            type_str    = f"ocr_rois{page0}", 
            image       = checkpoint_image)
            

def translate_keys(ocr_dict):
    ocr_dict['ocr_text']  = str(ocr_dict['text'])           # sometimes numerics will not be interpreted as str.
    ocr_dict['x'] = int(ocr_dict['left'])
    ocr_dict['y'] = int(ocr_dict['top'])
    ocr_dict['w'] = int(ocr_dict['width'])
    ocr_dict['h'] = int(ocr_dict['height'])
    ocr_dict['n'] = 1

    return ocr_dict
    
    
def combine_words(cur_line_d, word_d):
    """ translate keys first """

    cur_line_d['ocr_text']  += ' ' + str(word_d['text'])    # sometimes numerics will not be interpreted as str.
    #cur_line_d['x']         = min(cur_line_d['x'], word_d['x'])     #words are provided left to right
    cur_line_d['y']         = min(cur_line_d['y'], word_d['y'])
    word_d_right            = word_d['x'] + word_d['w']
    cur_line_d['w']         = word_d_right - cur_line_d['x']
    cur_line_d['h']         = max(cur_line_d['h'], word_d['h'])
    cur_line_d['n']         += word_d['n']
    return cur_line_d
    
    
def set_blk(cur_line_d, blk_region, layout_params):
    
    cur_line_d['blk_x'] = blk_region['x']
    cur_line_d['blk_y'] = cur_line_d['y'] - layout_params['blk_y_os']
    cur_line_d['blk_w'] = blk_region['w']
    cur_line_d['blk_h'] = layout_params['blk_h_nom']

    return cur_line_d

def sanitize_ocr_text(ocr_text):
    """ OCR convertion frequently provides special characters 
        particularly when attempting to convert the bubble target,
        and and may provide other characters with accents or other
        marks. This function is tailored for use with the tsv
        mode of Tesseract, and provide very plain characters suitable
        for comparision.
    """
    ocr_text = str(ocr_text)
    
    ocr_text = ocr_text.replace('é', 'e')
    ocr_text = ocr_text.replace(u'\u201c', '"').replace(u'\u201d', '"')     # replace curly quotes with straight quotes.
    ocr_text = re.sub(r'[^a-zA-Z0-9\s\."\(\)]', '', ocr_text)    # remove all non-plain text
    ocr_text = re.sub(r'^.?[O0]\s?', '', ocr_text)           # remove target as O or 0
    ocr_text = ocr_text.strip(' ')                           # remove spaces and start and end
          
    return ocr_text
    
def sanitize_ocr_text_in_rois_list(rois_list):
    """ review rois_list and remove rois that qualify as "empty"
        make sure ocr_text is a str.
    """
    
    new_rois_list = []
    for roi in rois_list:
        roi['ocr_text'] = sanitize_ocr_text(roi['ocr_text'])
        if not roi['ocr_text']:
            continue
        ocr_text_lc = roi['ocr_text'].lower
        if len(roi['ocr_text']) < 4 and ocr_text_lc != 'yes' and ocr_text_lc != 'no':
            logs.sts(f"Omitting short roi with this text: '{roi['ocr_text']}'", 3)
            continue
        new_rois_list.append(roi)
        
    return new_rois_list
    

def ocrdf_to_rois(argsdict, ocrdf, blk_region, page0=0) -> dict:
    """ given ocr df 
        return indexed dict of lines with area of region specified.
            Key of dict is index number.
            Value is dict {'ocr_text': string, 'x':x, 'y':y, 'w':w, 'h':h, 'n':(number of words), blk_x, blk_y, blk_w, blk_h}
                where x,y,w,h are coords and dimensions of text, n is total number of words.
                blk_x,y,w,h are dimensions of the surrounding region originally captured.
    """

    layout_params = get_layout_params(argsdict)


    df_words = ocrdf.loc[ocrdf['level'] >= 4]     # select set of rows with level>=5, i.e. lines and words.
    
    words_id = df_words.to_dict(orient='index')
    
    line_idx = -1
    result_id = {}
    cur_line_d = {'ocr_text':'', 'n':0}
    
    for index in words_id.keys():
        word_d = words_id[index]
    
        if word_d['level'] == 4:
            # finished a line.
            if line_idx > -1:   # not first time through
                cur_line_d['p']     = page0
                set_blk(cur_line_d, blk_region, layout_params)
                result_id[line_idx] = cur_line_d
            line_idx += 1
            continue
        
        if word_d['word_num'] == 1:
            # first word on this line.
            cur_line_d = translate_keys(word_d)
        else:
            translate_keys(word_d)
            combine_words(cur_line_d, word_d)
            
    if line_idx > -1:
        # finished a line.
        cur_line_d['p']     = page0
        set_blk(cur_line_d, blk_region, layout_params)
        result_id[line_idx] = cur_line_d

    return result_id
        
     
    '''
    the following is kept for now for reference.
    The above code which utilizes the functions "find_boxes" and "select_boxes"
    does not include the removal of rois within other rois.

    selected_contours = []
    page_rois_list = []
    for contour in contours:
        # This loop first filters the contours based on size criteria for rectangles
        # then, adds each to the selected_contours list, and the page_rois_list
        # If it finds a that a rectangular rois is inside another one, it discards the outer
        # rectangle and uses the inner one until it finds the innermost rectangles.

        # declaring auxialiary variables containing contours
        # bounding rectange coords and shape
        x, y, w, h = cv2.boundingRect(contour)

        # if width is within range 500-600;
        #   width is proper to be a ROI
        # if height is within range 45-1600;
        #   height is proper to be a ROI
        # if extent is over 0.9;
        #   contour is rectangle-like
        if not (500 < w < 600 and 45 < h < 1600 and float(cv2.contourArea(contour)) / (w * h) > 0.9):
            # contour does not meet minimum criteria -- disregard it.
            continue

        # the first time through the contour loop, this loop is not executed 
        # because selected_contours list is empty.
        for index, selected_contour in enumerate(selected_contours):
            # declaring auxialiary variables containing selected contours
            # bounding rectange coords and shape
            sel_x, sel_y, sel_w, sel_h = cv2.boundingRect(selected_contour)

            # if new contour x,y,w,h is within the other
            if x >= sel_x and x + w <= sel_x + sel_w and y >= sel_y and y + h <= sel_y + sel_h:
                # overwrite over the outer roi.
                # copying interior contours coords, shape and contour array
                # setting 'append_selected_contours' bool to False
                # breaking the iteration
                selected_contours[index] = contour
                page_rois_list[index]['p'] = p
                page_rois_list[index]['x'] = x
                page_rois_list[index]['y'] = y
                page_rois_list[index]['w'] = w
                page_rois_list[index]['h'] = h
                break
        else:
            # appending 'selected_contours' list
            # appending 'page_rois_list' list
            selected_contours.append(contour)
            page_rois_list.append({
                'p': p,
                'x': x,
                'y': y,
                'w': w,
                'h': h
            })
    utils.sts(f'Total of {len(page_rois_list)} rois meet selection criteria', 3)
    return page_rois_list
    '''

def get_active_region_from_settings(argsdict, style_dict, style_num, sheet0, page0):
    """ region specs do not need to be complete. Any missing extends (x, y, w, h) will 
        cause box list not to be trimmed in that direction, whereas those constraints that
        exist will cause the box list to be trimmed if they extend beyond the region.
        The active region defines the area of the page where contests and options may be found.
        Generally, only the y offset is needed.
    """

    active_region_list = parse_region_spec(argsdict, 'active_region', style_dict, style_num, sheet0, page0=page0)
    
    reg = {}
    if len(active_region_list) > 1:
        utils.exception_report(f"EXCEPTION: only one active_region allowed per page. "
            f"{len(active_region_list)} regions were specified for style_num:{style_num}, sheet:{sheet0}, page:{page0}.")
        return reg
    if active_region_list:
        reg['y'] = int(active_region_list[0]['y'])
        utils.sts(f"Region specified in settings for sheet:{sheet0} page:{page0}, y_offset:{reg['y']}", 3)
    return reg
    
def insert_rois_in_gaps(argsdict, style_dict, style_num, sheet0, p, page_rois_list, column_width):
    """ scan rois and look for gaps due to incomplete parsing of the image
        and insert additional rois in those gaps. 
        Return completed_list, added_rois_list
    """
    """ The boxes on the page are recognized using image processing and normally
        finds white contours just inside blank boundaries. However, in contest
        headers with grayscale backgrounds, these may turn out black when they are
        processed. Although it is feasible to use image processing to find these
        contest headers, it is quicker and easier just to look for missing boxes
        on the page and fill them in, given that we generally know the layout of the
        page.
    
        For ES&S in Dane, the first (reversed text) headers are general headers like 
        "Judicial", "Municipal", etc and these can be left out. For Dominion format
        in Leon County, the first boxes are the contest names. These should be
        included in the rois list.
        
        To deal with this issue, new layout values will be introduced to provide
        the approximate y offset from the top of the page as defined by the top 
        alignment blocks to the top of the 
        columns. Additional rois will be inserted if they do not start at that point.
        
        In the future, we may want to see if image processing can always provide the
        top without providing the input values. Two variables will be introduced:
    """
    if not argsdict.get('insert_rois_in_gaps', False) or \
        argsdict.get('use_ocr_based_genrois', False):
        return page_rois_list, []
    
    
    page_layout_type = get_page_layout_type(argsdict, sheet0, p)
    if page_layout_type == '1&2col':
        return page_rois_list, []
    
    utils.sts("Inserting rois in gaps...", 3)
        
    col_prior_roi = 0   # included here only to satisfy pylint
    page_top = 0        # included here only to satisfy pylint
    
    added_rois_list = []

    nearly_equal_dif = 10
    idx = 0
    
    active_region = get_active_region_from_settings(argsdict, style_dict, style_num, sheet0, p)
    reg_y = active_region.get('y', 0)
    
    while idx < len(page_rois_list):
        # we can't use 'for index in range(len(page_rois_list))' above because the list will be potentially growing.
        roi = page_rois_list[idx]

        # declaring auxiliary variables containing coords and shape
        x = roi["x"]; y = roi["y"]; w = roi["w"]; h = roi["h"]
        b = y + h
        column = x // column_width
        
        utils.sts(f"roi {idx} at x:{x} y:{y} w:{w} h:{h}", 3)
            
        if not idx:
            # first time through. Set page_top.
            # if no args.argsdict['y_offset_page_X'], then use first roi as page top.
            
            page_top = reg_y if reg_y else y
            page_top = int(page_top)

            col_prior_roi = column
            b_prior_roi = page_top
            
        if not column == col_prior_roi:
            b_prior_roi = page_top
            col_prior_roi = column

        if b_prior_roi + nearly_equal_dif > y:
            # the prior roi considered "adjacent"
            # did not find a gap.
            b_prior_roi = b
            idx += 1
            continue
            
        # rois are not adjacent, add additional roi to fill the gap.
        new_roi = {
                'p': p,
                'x': x,
                'y': b_prior_roi,
                'w': w,
                'h': y - b_prior_roi
            }
        
        page_rois_list.insert(idx, new_roi)
        added_rois_list.append(new_roi)
        
        b_prior_roi = b
        utils.sts(f'ROI {idx}:Inserted Roi in the gap', 3)
        # skip the current roi which now has idx+1 index.
        # note this manipulation of idx requires a 'while' loop
        idx += 2
        continue
        
    return page_rois_list, added_rois_list


def sort_rois(page_rois_list, column_width):
    # sorting 'page_rois_list' by rounding to the column and exact vertical coordinates
    return sorted(page_rois_list, key=lambda lmb: (lmb['x'] // column_width, lmb['y']))


def is_line_white(image, line_num, cnt_y, cnt_x, cnt_w, lft_mgn=5) -> tuple:
    rgt_mgn = 5

    line = image[
           cnt_y + line_num:cnt_y + line_num + 2,
           cnt_x + lft_mgn: cnt_x + cnt_w - rgt_mgn
           ]
    # checking if the mean of currently analyzed line is below 250
    return sum(cv2.mean(line)), line


def split_roi_at_first_white_gap(image, roi, lft_mgn, min_gap, gap_split_offset, combine_large_text_blocks=False, min_item=35):
    """ Given a roi which is joined, split it up at first white gap
        after non-white content is encountered.
        States:
        -1 - looking for non-white lines
        0 - looking for white lines, num_white_lines < min_gap
        1 - found white lines, num_white_lines < min_gap
        2 - found min_gap, lookign for non-white.
        3 - found gap, detected non-white, num_non_white < min_non_gap
        4 - gap confirmed, detected non-white
                second text < max_item, declare break
                else back to 0, combine larger paragraphs
                
        ES&S Walulla has period of about 60 pixels
        Note: min_item is critical in Wakulla case at 35 vs 36.
        This may be solvable by checking the size of the split regions.
        
    """
    never_combine_large_text_blocks = False
    log_split_details = False   # if true, show the first part of each image line as text graphics
    
    cnt_x = roi["x"]; cnt_y = roi["y"]; cnt_w = roi["w"]; cnt_h = roi["h"]
    utils.sts(f'p:{roi["p"]} x:{cnt_x} y:{cnt_y} w:{cnt_w} h:{cnt_h} min_gap:{min_gap} ', 3, end='')


    #min_line = 54
    num_white = 0
    num_non_white = 0
    min_non_gap = 2
    gap_start = 0
    gap_end = 0
    state = -1
    max_item = 90
    #min_item = 15
    max_line_gaps = 3
    
    #white_metric_threshold = 254.5      # was the value for ES&S
    #white_metric_threshold = 254         # attempting to allow random vertical scratch
    
    for cur_line in range(min_item, cnt_h - min_item):
        metric, line = is_line_white(image, cur_line, cnt_y, cnt_x, cnt_w, lft_mgn)
        if metric > 254.5:
            # white line detected
            num_white += 1
            if state == 0:        # state0 -- looking for gap
                gap_start = cur_line
                num_non_white = 0
                state = 1   # transition to possible gap
            elif state == 1 and num_white >= min_gap:
                state = 2   # transition to find gap end
            elif state == 3:
                # verifying the gap.
                # oops, did not confirm end.
                state = 2
            elif state == 4:
                # verifying the second text block. 
                # small gaps are okay.
                if num_white > max_line_gaps:
                    state = 5
                    break
                
        else:
            num_non_white += 1
            if state == -1:
                # initial non-white dectected, now look for the gap
                state = 0
                num_white = 0
                num_non_white = 1
                #text_start = cur_line
            if state == 1:
                # black line found, not a gap after all
                num_white = 0
                state = 0
            elif state == 2:
                # possible end of the gap
                gap_end = cur_line
                num_non_white = 1
                state = 3   # confirm it
            elif state == 3 and num_non_white > min_non_gap:
                if never_combine_large_text_blocks or not combine_large_text_blocks:
                    break
                state = 4
            elif state == 4 and num_non_white > max_item:
                # option item is too large
                # it should not be split as it is
                # the second paragraph in question item
                # do not declare a split.
                state = 0
                num_white = 0

        # The following code is for debugging.
        if log_split_details:
            # for debugging. This prints the info and pixels as . or #
            utils.sts(f"y:{cnt_y} line:{cur_line} metric:{round(metric, 4)} white:{num_white} nonwhite:{num_non_white} state:{state}", 3)

            linestr = ''
            #import pdb;pdb.set_trace()
            for bit in line[0][:200]:
                if bit >= 250:
                    linestr += '.'
                else:
                    linestr += '#'
            utils.sts(f"{linestr}", 3)

    else:
        if state == 2:
            # normal case with text.
            # limit size of rois to have min_gap of white after last text line.
            roi['h'] = gap_start + min_gap
        if state != 4:
            # did not find a gap.
            utils.sts("Not split")
            return [roi]
        # otherwise, the text hit the bottom
        
    # did find a gap meeting the criteria
    # now modify the existing roi and create a new one.
    #gap_h = gap_end - gap_start
    split_point = gap_end - 15
    #utils.sts(f"top mgn_h:{text_start} text_h:{gap_start-text_start} gap_h:{gap_h} split_point:{split_point}")

    new_roi = roi.copy()
    roi['h'] = split_point
    new_roi['h'] = cnt_h - split_point
    new_roi['y'] = cnt_y + split_point
    
    return [roi, new_roi]
    
   
def split_roi_at_white_gaps(image, roi):
    """ Given a roi which is joined, split it up at white gaps.
        return list of resulting rois.
        The initial roi is a complete contest with options.
    """
    result_rois = [roi]
    
    cur_roi = 0
    while True:
        #ES&S Wakulla min_gap = 28
        min_gap = 12
        combine_large_text_blocks = False
        if cur_roi: 
            # for fully_joined layout, do not allow combination of contest header.
            combine_large_text_blocks = True
            min_gap = 12                            # ES&S Wakulla was 15
        
        roi_list = split_roi_at_first_white_gap(
            image, result_rois[cur_roi], 
            lft_mgn=5, min_gap=min_gap, 
            gap_split_offset=min_gap//2,
            combine_large_text_blocks=combine_large_text_blocks
            )
        # the call above modifies roi and returns another one in the list.
        if len(roi_list) > 1:
            # roi was split append the new child, parent modified by reference
            result_rois.append(roi_list[1])
            utils.sts(f" roi {cur_roi} split at {roi_list[1]['y']}", 3)
            cur_roi += 1
        else:
            break

    # if the function split_roi_at_first_white_gap() does not 
    # combine_large_text_blocks (which it may do now), then 
    # at this point, the original roi has been fully split up.
    # It is a better design to 
    # analyze here to combine rois appropriately, such as for large
    # text paragraphs that may have a gap but comprise a single
    # description of a question-type contest.
    
    # it will be more efficient and a bit easier to deal with combining
    # large text blocks at this level. This will be an enhancement for the
    # future because the existing code is currently working.
    


    return result_rois


def split_rois_list_at_white_gaps(argsdict, template_image, rois_list):
    """ called with a list of rois that need to be each split.
        each rois is one complete contests typically and needs
        to be split into contest name and options.
    """
    
    if not argsdict.get('split_rois_at_white_gaps', False):
        return rois_list
    
    # looking for contours within adjusted image
    _, image = cv2.threshold(template_image, 170, 255, cv2.THRESH_BINARY)

    idx = 0
    while idx < len(rois_list):
        # we can't use iterator above because the list will be potentially growing.

        utils.sts (f"========== roi {idx} ==============", 3)
        roi = rois_list[idx]
        new_rois = split_roi_at_white_gaps(image, roi)
        
        if len(new_rois) > 1:
            rois_list[idx+1:idx+1] = new_rois[1:]

        idx += len(new_rois)
    return rois_list
    
    
def crop_to_area(margins, image, roi):
    """ extract area from full image to option area or full area based on vendor
        return area
        margins = layout_params[crop]
        crop can be either 
            'full_crop' - reduce area slightly to avoid surrounding lines.
            'option_crop' -- further reduction in left and right margins to exclude
                        the target and possibly the party affiliation on the right.
        Cropping the area prior to using tesseract to do OCR is extremely important.
        No portions of borders or lines should be included in the image.
        
    """
    
    #p = roi["p"]
    x = roi["x"]
    y = roi["y"]
    w = roi["w"]
    h = roi["h"]

    tm, lm, rm, bm = margins['top_margin'], margins['lft_margin'], margins['rgt_margin'], margins['btm_margin']
 
    y_crop = y + tm
    x_crop = x + lm
    b_crop = y + h - bm
    r_crop = x + w - rm
    #h_crop = h - bm - tm
    #w_crop = w - lm - rm

    #utils.sts((' p:%1.1u x:%4.1u y:%4.1u w:%4.1u h:%4.1u: ' % (p, x_crop, y_crop, w_crop, h_crop)), 3, end='')
    area_of_interest = image[ y_crop: b_crop, x_crop: r_crop ].copy()
    return area_of_interest
    
    
def clear_margins(margins, image, roi):
    """ Instead of cropping the region of interest to exclude the margins,
        this function instead clears the region outside the margins and does not
        alter the dimensions of the ROI.
        However, the image which is passed is the full image, so the first step
        is to extract just the rois area as initially defined.
    """
    
    #p = roi["p"]
    x = roi["x"]
    y = roi["y"]
    w = roi["w"]
    h = roi["h"]

    tm, lm, rm, bm = margins['top_margin'], margins['lft_margin'], margins['rgt_margin'], margins['btm_margin']
 
    y_crop = y
    x_crop = x
    b_crop = y + h
    r_crop = x + w

    #utils.sts(('Cropping out RIO: p:%1.1u x:%4.1u y:%4.1u b:%4.1u r:%4.1u: ' % (p, x_crop, y_crop, b_crop, r_crop)), 3, end='')
    area_of_interest = image[ y_crop: b_crop, x_crop: r_crop ].copy()

    #utils.sts(('Clearing ROI Margins: tm:%1.1u lm:%1.1u rm:%1.1u bm:%1.1u ' % (tm, lm, rm, bm)), 3)
    # now clear margins
    area_of_interest[ : tm,  : ] = 255      # top
    area_of_interest[-bm : , : ] = 255      # bottom
    area_of_interest[ : ,  :lm ] = 255      # left
    area_of_interest[ : , -rm: ] = 255      # right
    
    return area_of_interest


def clear_image_borders(area_of_interest, border_width=1):
    """ erase borders in area of interest """
    
    area_of_interest[ : border_width,  : ] = 255      # top
    area_of_interest[-border_width : , : ] = 255      # bottom
    area_of_interest[ : ,  :border_width ] = 255      # left
    area_of_interest[ : , -border_width: ] = 255      # right


def ungray_area(area_of_interest, force:bool = False):
    """ if the mean of a contest block is below 160, then it likely has 
        a gray background which will need addiitional processing to 
        clear it out. This also works to clear out the background in the
        case of cropped snippets to improve tesseract convertion.
        Therefore, it is used for all cases.
    """
    
    gray_background_max_mean = 160
    
    roi_mean = cv2.mean(area_of_interest)[0]
    if force or roi_mean < gray_background_max_mean:
        # The following should be performed only when the roi has a gray background.
        utils.sts(f"Darker roi detected: mean:({round(roi_mean, 2)} < {gray_background_max_mean} threshold. Ungraying the region.", 3)
        
        # dilation followed by erosion removes black spots from white areas.
        wht_kernel = np.ones((3, 3), np.uint8)
        for i in range(3):
            area_of_interest = cv2.dilate(area_of_interest, wht_kernel)
            area_of_interest = cv2.erode(area_of_interest, wht_kernel)
            
    # area_of_interest = cv2.threshold(area_of_interest, 170, 255, cv2.THRESH_OTSU)
    ret1, area_of_interest = cv2.threshold(area_of_interest, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)    
    return area_of_interest

def analyze_one_roi(argsdict: dict, image, roi, style_dict):
    """ analyze one roi and update it.
        first crops the image to option area if appropriate.
        updates:
            ocr_option_word     if one-liner (cropped)
            ocr_option_text     (cropped)
            ocr_word            if one-liner (uncropped)
            ocr_text            (uncropped)
    """
    layout_params = get_layout_params(argsdict)
    diagnose_ocr = bool(style_dict['style_num'] in argsdict['diagnose_ocr_styles'])
    
    h = roi['h']

    option_area_of_interest = None
    if h < layout_params['h_max_option']:
        # first crop it as if it is an option.
        margins_dict = layout_params['option_crop']
        option_area_of_interest = clear_margins(margins_dict, image, roi)
        
        if diagnose_ocr:
            option_aoi_1 = option_area_of_interest.copy()
            utils.sts("diagnose_ocr enabled for this style", 3)
            result_ocr_dict = ocr_various_modes(option_aoi_1)
            utils.sts(f"prep1: no additional image processing\n{pprint.pformat(result_ocr_dict)}", 3)

            option_aoi_2 = option_area_of_interest.copy()
            option_aoi_2 = ungray_area(option_aoi_2, force=True)
            result_ocr_dict = ocr_various_modes(option_aoi_2)
            utils.sts(f"prep2: full ungray\n{pprint.pformat(result_ocr_dict)}", 3)
            
            option_aoi_3 = option_area_of_interest.copy()
            option_aoi_3 = ungray_area(option_aoi_3, force=False)
            result_ocr_dict = ocr_various_modes(option_aoi_3)
            utils.sts(f"prep3: threshold only\n{pprint.pformat(result_ocr_dict)}", 3)
            
        #option_area_of_interest = ungray_area(option_area_of_interest, force=False)
        text = ocr_text(option_area_of_interest, mode=3)
        text = clean_candidate_name(text)
        roi['ocr_option_text'] = text
        utils.sts(f'OT: "{utils.sane_str(text[:40])}" ', 3, end='')
            
        if False:  # never generate this for now.  h < h_min_option:
            # if the option is a one-liner, convert also as if it might be a single word.
            word = ocr_word(option_area_of_interest)
            roi['ocr_option_word'] = word
            utils.sts(f'OW: "{utils.sane_str(word[:40])}" ', 3, end='')

        # calc_roi_target(roi, style_dict, layout_params)
        
        utils.sts(f"\n{' '*19}", 3, end="")
        
    # second convert as if it is a contest header
    # contest headers can be of any size
    margins_dict = layout_params['full_crop']
    full_area_of_interest = clear_margins(margins_dict, image, roi)
    
    #full_area_of_interest = crop_to_area(margins_dict, image, roi)
    #clear_image_borders(full_area_of_interest)

    # clear out gray area, if the roi seems too dark
    full_area_of_interest = ungray_area(full_area_of_interest)
    
    # OCRing text within and saving it
    text = ocr_text(full_area_of_interest)
    roi['ocr_text'] = text
    utils.sts(f'CT: "{utils.sane_str(text[:80])}"', 3, end='')

    if False:  # never do this for now. h < h_min_option:
        # if the option is a one-liner, convert also as if it might be a single word.
        word = ocr_word(option_area_of_interest)
        roi['ocr_word'] = word
        utils.sts(f' CW: "{utils.sane_str(word[:40])}" ', 3, end='')
    
    utils.sts("")
    
    # return roi image and roi.
    return option_area_of_interest, full_area_of_interest, roi


def genrois_one_p(argsdict: dict, style_dict, p, image):
    """ given the page number (0,1) and image of one page side
        return rois_list, rois_images
        This is the Dane County type layout with contest name
        and each option in a separate box.
    """
    working_image = image.copy()
    
    layout = args.argsdict['layout']
    #vendor = args.argsdict['vendor']
    style_num = style_dict['style_num']
    sheet0 = style_dict.get('sheet0', 0)
    target_side = style_dict['target_side'] = argsdict.get('target_side', 'left')
    
    logs.sts(f"genrois for style:{style_num} layout:{layout} sheet0:{sheet0} page0:{p} target_side:{target_side}", 3)
    
    rois_images = []
    
    box_sizes_list = get_box_sizes_list(argsdict, sheet0=sheet0, page0=p)
    column_width = box_sizes_list[0]['w_col']

    style_timing_marks = style_dict.get('timing_marks', [])

    if not style_timing_marks and not p:
        utils.sts(f"expected timing marks not found for style {style_num} page {p}")
        return None, None
        
    logs.sts(f"style_timing_marks\n{style_timing_marks}", 3)
        
    # process the image and find boxes on the page.
    # for ocr_baed_genrois, this ocrs the region and returns all text as separate rois.
    page_rois_list = gen_page_rois_list(argsdict, style_dict, box_sizes_list, style_num, p, sheet0, image)
        
    if argsdict['save_checkpoint_images']:
        checkpoint_image = draw_boxes_on_image(image, page_rois_list, color=['red', 'blue'], line_width=2, convert_to_RGB=True, prefix_list=['', 'blk_'])
        DB.save_one_image_area_dirname(
            dirname     = 'styles', 
            subdir      = f"{style_dict['style_num']}/rois_parts", 
            style_num   = style_dict['style_num'], idx='', 
            type_str    = f"initial_rois{p}", 
            image       = checkpoint_image)

    # sort the rois in columns top to bottom, then left to right
    page_rois_list = sort_rois(page_rois_list, column_width)

    if argsdict.get('use_ocr_based_genrois'):
        # no more graphic manipulation if using ocr_based_genrois
        return page_rois_list, rois_images


    # for some reason, some regions of the page are skipped, and we fill those in.
    page_rois_list, added_rois_list = insert_rois_in_gaps(argsdict, style_dict, style_num, sheet0, p, page_rois_list, column_width, prefix_list=[''])
    
    if argsdict['save_checkpoint_images']:
        checkpoint_image = draw_boxes_on_image(checkpoint_image, added_rois_list, color=['blue'], line_width=2, convert_to_RGB=False)
        DB.save_one_image_area_dirname(
            dirname     = 'styles', 
            subdir      = f"{style_dict['style_num']}/rois_parts", 
            style_num   = style_dict['style_num'], idx='', 
            type_str    = f"inserted_rois{p}", 
            image       = checkpoint_image)

    if layout == 'fully_joined':
        page_rois_list = split_rois_list_at_white_gaps(argsdict, image, page_rois_list)     # no effect unless argsdict['split_rois_at_white_gaps']

        if True: #argsdict['save_checkpoint_images']:
            checkpoint_image = draw_boxes_on_image(image, page_rois_list, color=['red'], line_width=2, convert_to_RGB=True, prefix_list=[''])
            DB.save_one_image_area_dirname(
                dirname     = 'styles', 
                subdir      = f"{style_dict['style_num']}/rois_parts", 
                style_num   = style_dict['style_num'], idx='', 
                type_str    = f"split_rois{p}", 
                image       = checkpoint_image)

    # process rois based on likely use by size and ocr.
    for index, roi in enumerate(page_rois_list):

        utils.sts(('Style:%4.1u ROI:%3.1u ' % (int(style_num), index)), 3, end='')
        
        #if style_num == '2822076' and index == 57:

        option_roi_image, contest_roi_image, roi = \
            analyze_one_roi(argsdict, working_image, roi, style_dict)    
            # style_dict contains the timing_marks information.
            # this function accesses layout_params for cropping specs.

        if not option_roi_image is None:
            rois_images.append(option_roi_image)
        rois_images.append(contest_roi_image)
        
    return page_rois_list, rois_images


def format_rois_list_str(argsdict, rois_list, start_at=0):
    string = "idx P  X    Y    W    H   blkx blky blkw blkh RGT  BTM  Description\n" \
           + "--- - ---- ---- ---- ---- ---- ---- ---- ---- ---- ---- ---------------------------------------------------\n"
    for idx in range(start_at, len(rois_list)):
        roi = rois_list[idx]
        string += "%3.1u %1.1u %4.1u %4.1u %4.1u %4.1u %4.1u %4.1u %4.1u %4.1u %4.1u %4.1u" % \
            (idx, roi['p'], roi['x'], roi['y'], roi['w'], roi['h'],
            roi['blk_x'], roi['blk_y'], roi['blk_w'], roi['blk_h'],
            int(roi['x']) + int(roi['w']), int(roi['y']) + int(roi['h']))
            
        #if 'ocr_option_word' in roi and roi['ocr_option_word']:
        #    string += " W:'" + roi['ocr_option_word'] + "'"
            
        if not argsdict.get('use_ocr_based_genrois'):
            if 'ocr_option_text' in roi and roi['ocr_option_text']:
                string += " O:'" + re.sub(r'[\n\r]+', ' ', str(roi['ocr_option_text'])) + "'"
            
        try:
            string += " C:'" + re.sub(r'[\n\r]+', ' ', str(roi['ocr_text'])) + "'\n"
        except:
            import pdb; pdb.set_trace()
    return string


def genrois_one_style(argsdict: dict, style_num):
    """
    Given list of template images (usually two, one for each side) and style data,
    generate list of rois and associated images that are candidates for linkage to
    contests and options.
    saves the rois_list, rois_images
    rois_list is a list of dicts, as follows:
        'p': page number        side of the ballot
        'x': (x coordinate)     location of the roi
        'y': (y coordinate)
        'w': (width)            size of the roi
        'h': (height)
        'blk_x', blk_y, blk_w, blk_h:   size of surrounding block, if in ocr_based_genrois.
        'ocr_text':             converted text inside the roi
        'checkbox_contour_list':    contours of a checkbox if it seems to exist.
    """
    
    logs.sts(f"Generating roislist for style:{style_num}", 3)
    style_template_images = DB.load_template_images(style_num = style_num)
    if not style_template_images:
        logs.exception_report(f"genrois_one_style: Template images missing for style:{style_num}")
    
    # mainly we need the timing_marks, and 'sheet0' from this data.
    style_dict = DB.load_data(dirname='styles', subdir=style_num, name=f'{style_num}_style')

    style_rois_images = []
    style_rois_list = []
    
    # iterating through enumerated 'style_images', these are the pages (sides) of a ballot
    for p, image in enumerate(style_template_images):

        utils.sts(f'Page {p}', 3)
        
        rois_list_one_p, rois_images_one_p = genrois_one_p(argsdict, style_dict, p, image)
        if rois_list_one_p is None:
            # error condition, exception should be logged at a lower level.
            continue
        
        style_rois_images.extend(rois_images_one_p)
        style_rois_list.extend(rois_list_one_p)

    #DB.save_rois(style_num = style_num, rois_data=style_rois_list)
    DB.save_data(data_item=style_rois_list, dirname='styles', name=f"{style_num}_rois.json", subdir=style_num)
    if argsdict.get('save_checkpoint_images', False):
        DB.save_rois_images(style_num = style_num, images = style_rois_images)
    utils.sts(format_rois_list_str(argsdict, style_rois_list), 3)
    return style_rois_list


def genrois_lambda(argsdict: dict, style_num: str):
    if style_num in argsdict.get('exclude_style_num', []):
        utils.sts(f'Excluding Style {style_num} as specified in input file.', 3)
    else:
        utils.sts(f'Style {style_num}', 3)
        genrois_one_style(argsdict, style_num)
    utils.sts('Rois generation complete.', 3)


def genrois_local(argsdict):
    style_nums_list = DB.get_style_nums_with_templates(argsdict)
    layout = argsdict.get('layout', 'separated')
    vendor = argsdict.get('vendor', 'ES&S')
    utils.sts(f"Found {len(style_nums_list)} styles of {vendor} with layout:'{layout}'.")
    included_style_nums = argsdict.get('include_style_num', [])
    excluded_style_nums = argsdict.get('exclude_style_num', [])

    for style_num in style_nums_list:
        if style_num in excluded_style_nums or \
            included_style_nums and not style_num in included_style_nums:
            #utils.sts(f'Excluding Style {style_num} as specified in input file.', 3)
            continue
        utils.sts(f'Style {style_num}', 3)
        genrois_one_style(argsdict, style_num)

    utils.sts('Rois generation complete.', 3)
    
    log_misspelled_words()


def genrois(argsdict, style_num: str = ''):
    """
    Style templates must be generated at this point to allow further analysis and generation of rois
    The json list of rois and the image for each result.
    """
    utils.sts('Generating rois', 3)
    if argsdict.get('use_lambdas') and style_num:
        genrois_lambda(argsdict, style_num)
    elif not argsdict.get('use_lambdas'):
        genrois_local(argsdict)
    else:
        utils.sts('Omitting local genrois')
        