import re
import os
import math
from tempfile import NamedTemporaryFile

import cv2
import fitz
import numpy as np
from pyzbar.pyzbar import decode as barcode_decode
import Levenshtein as lev 

from utilities.config_d import config_dict
from utilities import utils, logs
from utilities import ocr
from utilities.vendor import get_layout_params
from models.DB import DB
from utilities.utils import list_from_csv_str
#from utilities.analysis_utils import normalize_ev_coord_str            # results in circular imports


def images_similarity_flann(base_image, compared_image, features_number, margins, scale_factor, distance_ratio_thresh):
    """
    Function returning feature similarity of two images
    :param base_image: (np.array) array of base image
    :param compared_image: (np.array) array of compared image
    :param features_number: (int) number of features to find
    :param margins: (dict) dictionary with keys 't', 'b', 'l', 'r', which define how much of a margin should be ignored
    :param scale_factor: (float) float of a range from 1.0 to 2.0, declaring quality of searched features (the lower the worse, but also faster)
    :param distance_ratio_thresh: (float) float of a range from 0.0 to 1.0 declaring similarity distance ratio thresh (over 0.8 and bad matches are also chosen)
    :return len(good_matches): (int) number of a good matches found
    """
    # declaing constants
    flann_index_kdtree = 0
    flann_trees = 5
    flann_checks = 50

    # creating margin masks
    base_mask = base_image.copy()
    base_mask[:, :] = 0
    base_mask[margins['t']:-margins['b'], :] = 255
    base_mask[:, :margins['l']] = 0
    base_mask[:, -margins['r']:] = 0
    compared_mask = compared_image.copy()
    compared_mask[:, :] = 255
    compared_mask[margins['t']:-margins['b'], :] = 255
    compared_mask[:, :margins['l']] = 0
    compared_mask[:, -margins['r']:] = 0

    # creating oriented BRIEF keypoint detector and descriptor extractor
    # detecting keypoints and calculating descriptors
    orb = cv2.ORB_create(features_number, scale_factor, WTA_K=2)
    (base_keypoints, base_descriptors) = orb.detectAndCompute(base_image, base_mask)
    (compared_keypoints, compared_desriptors) = orb.detectAndCompute(compared_image, compared_mask)

    # declaring index and search parameter dictionaries
    # creating flann matcher
    index_params = dict(algorithm=flann_index_kdtree, trees=flann_trees)
    search_params = dict(checks=flann_checks)
    flann = cv2.FlannBasedMatcher(index_params, search_params)

    # filtering out good matches
    good_matches = []
    matches = flann.knnMatch(np.asarray(base_descriptors, np.float32), np.asarray(compared_desriptors, np.float32), k=2)
    for m, n in matches:
        if m.distance < distance_ratio_thresh * n.distance:
            good_matches.append(m)

    return len(good_matches)


def match_styles_flann(paths, similarity_thresh, features_number=500, margins={'t': 75, 'b': 75, 'l': 75, 'r': 75}, scale_factor=2.0, distance_ratio_thresh=0.7):
    """
    Function returning list of templates with list of templates similar to first one within
    :param paths: (list) list of paths to template images
    :param similarity_thresh: (int) thresh value of the number of mateched features we find sufficient to match a ballot (NEVER HIGHER THAN features_number)
    :param features_number: (int) number of features to find
    :param margins: (dict) dictionary with keys 't', 'b', 'l', 'r', which define how much of a margin should be ignored
    :param scale_factor: (float) float of a range from 1.0 to 2.0, declaring quality of searched features (the lower the worse, but also faster)
    :param distance_ratio_thresh: (float) float of a range from 0.0 to 1.0 declaring similarity distance ratio thresh (over 0.8 and bad matches are also chosen)
    :return templates (list of dicts): list of dictionaries with following keys: 'path', 'similar_templates'
    """

    # creating returned data basic layout
    utils.sts('Generating arrays of images based on provided paths', 3)
    templates = []
    for path in paths:
        templates.append({
            'path': path,
            'image': cv2.imread(path, 0),
            'similar_templates': []
        })

    # iterating through templetes on two levels
    # calculating similarity
    # appending template 'similar_templates' key if similarity is greater or equal than thresh
    utils.sts(f'Searching for similarities between {len(templates)} templates', 3)
    for base_index, base_template in enumerate(templates):
        utils.sts(f'Searching for template {base_index+1}/{len(templates)}', 3)
        for compared_index, compared_template in enumerate(templates):
            if base_index is not compared_index:
                similarity = images_similarity_flann(base_template['image'],
                                                     compared_template['image'],
                                                     features_number=features_number,
                                                     margins=margins,
                                                     scale_factor=scale_factor,
                                                     distance_ratio_thresh=distance_ratio_thresh)
                if similarity >= similarity_thresh:
                    base_template['similar_templates'].append({
                        'path': compared_template['path'],
                        'similarity': similarity
                    })

    # sorting similar templates by similarity
    # removing template image to free some memory
    for template in templates:
        template['similar_templates'].sort(key=lambda st: -st['similarity'])
        del template['image']

    return templates



def check_if_line_present(line_area, slice_length, line_value=90, thicker_than=0, thinner_than=20):
    """
    Function to check if there is any horizontal or vertical line of certain characteristics within given image.
    :param line_area: (np.array) array of an image to be analysed
    :param slice_length: (int) length of a slices to be analised
    :param line_value: (int) value of the range 1-99 defining how strict should the line deffinition be
                                Generally speaking, the lighter the line, the higher the line_value should be. (edited) 
    :param thicker_than: (int) exclusive minimal value of searched line width
    :param thinner_than: (int) exclusive maximal value of searched line width
    :return: (boolean, int/None) boolean value of line presence, int value of line index within given image/ None if boolean is False
    """
    # declaring line area shape variables
    area_h, area_w = line_area.shape

    # declaring empty lists
    means = []
    means_values = []
    line_begs = []
    line_ends = []
    line_widths = []
    line_diffs = []

    # if the line is supposed to be horizontal
    if area_h < area_w:

        # iterating through slices
        for mean_index, w in enumerate(range(area_w)[::slice_length]):

            # declaring slice end
            end_w = w + slice_length - 1
            if end_w >= area_w:
                end_w = area_w - 1

            # declaring empty list within means list
            means.append([])

            # iterating through whole height
            # filling the list within means list with means
            for h in range(area_h-1):
                line = line_area[h:h+1, w:end_w]
                mean = sum(cv2.mean(line))
                means[mean_index].append(mean)
                means_values.append(mean)

        # declaring minimal and maximal means values
        min_mean = min(means_values)
        max_mean = max(means_values)

        # iterating through all elements of everylist within means list
        # normalising values to 0-100 range
        for x in range(len(means)):
            for y in range(len(means[x])):
                if max_mean - min_mean != 0:
                    means[x][y] = round(100.0 * (float(means[x][y]) - min_mean) / (max_mean - min_mean), 2)
                else:
                    if min_mean == 0:
                        min_mean = 0.000001
                    means[x][y] = round(100.0 * float(means[x][y] / min_mean), 2)

    # if the line is supposed to be vertical
    else:

        # iterating through slices
        for mean_index, h in enumerate(range(area_h)[::slice_length]):

            # declaring slice end
            end_h = h + slice_length - 1
            if end_h >= area_h:
                end_h = area_h - 1

            # declaring empty list within means list
            means.append([])

            # iterating through whole height
            # filling the list within means list with means
            for w in range(area_w-1):
                line = line_area[h:end_h, w:w+1]
                mean = round(sum(cv2.mean(line)))
                means[mean_index].append(mean)
                means_values.append(mean)

        # declaring minimal and maximal means values
        min_mean = min(means_values)
        max_mean = max(means_values)

        # iterating through all elements of everylist within means list
        # normalising values to 0-100 range
        for x in range(len(means)):
            for y in range(len(means[x])):
                if max_mean - min_mean != 0:
                    means[x][y] = round(100.0 *(float(means[x][y]) - min_mean) / (max_mean - min_mean), 2)
                elif min_mean != 0:
                    means[x][y] = round(100.0 * float(means[x][y] / min_mean), 2)
                else:
                    means[x][y] = round(0.0, 2)

    # iterating through lists of means within means list
    for means_line in means:

        # declaring maximal and minimal values within list
        line_min_mean = min(means_line)
        line_max_mean = max(means_line)

        # declaring difference between maximal and minimal means
        diff = line_max_mean - line_min_mean

        # declaring line begining and ending indexes with dummy values
        line_beg = 222
        line_end = 222

        # iterating through means
        # calculating proper line begining and ending indexes
        for mean_index, value in enumerate(means_line):
            if value < line_value and line_beg == 222:
                line_beg = mean_index
            if value < line_value and line_beg != 222:
                line_end = mean_index

        # appending line begining and ending indexes, width and mean difference to corresponding lists
        line_begs.append(line_beg)
        line_ends.append(line_end)
        line_widths.append(line_end-line_beg)
        line_diffs.append(diff)

    # checking it caltulated values match the line properties
    if max(line_begs) - min(line_begs) < 8 and \
            max(line_ends) - min(line_ends) < 8 and \
            min(line_diffs) > 100 - line_value and \
            min(line_widths) > thicker_than and \
            max(line_widths) < thinner_than:
        return True, max(line_ends) - int(abs(max(line_ends)-min(line_begs))/2)
    else:
        return False, None


def add_line(image, x, y, s=1, **kwargs):
    """
    Function, adding a line to the image.
    :param image: (np.array) array of an image on which the line should be drawn
    :param x: (int) int value defining line begining x coord
    :param y: (int) int value defining line begining y coord
    :param s: (int) int value defining line thickness
    :param kwargs: (int) int value (w or h) defining line width or heigth
    :return modified_image: (np.array) array of an image on which the line was drawn
    """

    modified_image = image.copy()
    h = kwargs.get('h', None)
    w = kwargs.get('w', None)
    if w and h:
        return modified_image
    elif h:
        if s == 1:
            modified_image[y:y+h, x:x+s] = 0
        else:
            modified_image[y:y+h, x-math.floor(s/2):x+math.ceil(s/2)] = 0
    elif w:
        if s == 1:
            modified_image[y:y+s, x:x+w] = 0
        else:
            modified_image[y-math.floor(s/2):y+math.ceil(s/2), x:x+w] = 0
    return modified_image


def fuzzy_match_expressvote_lines(lines: list, sample_lines: list) -> bool:
    """Matches lines of potentially Expressvote ballot with the
    pattern to make sure it is correct.
    :param lines: List of lines from the ballot.
    :param sample_lines: List of lines from the user.
    :return: True if lines matches pattern.
    """
    treshold = 0.8
    # pylint: disable=no-member
    if lev.seqratio(lines[0], "ABSENTEE") > 0.7:
        lines.pop(0)
    ratio = lev.seqratio(lines[:3], sample_lines)
    return ratio >= treshold


def dominion_expressvote_conversion(image):
    """
    :param image: (np.array) array of an unaligned image of Dominion type ballot, which may be an BMD ballot summary
    :return both_columns.splitlines(): (list) list of lines OCRed from ballot results
    :return vertical_code: (str) string containing OCRed vertical code of the ballot
    :return qrcode[0]: qrcode of the ballot
    """

    # declaring image height and width
    height, width = image.shape

    # extracting possible barcodes
    barcodes = barcode_decode(image)

    # if any barcodes were found
    if barcodes:

        # if the first barcode is a qrcode
        if barcodes[0].type == 'QRCODE':

            # creating qrcode shape threshold
            qrcode_shape = np.zeros(image.shape)
            qrcode_poly = []
            for point in barcodes[0].polygon:
                qrcode_poly.append(tuple(point))
            qrcode_shape = cv2.drawContours(qrcode_shape, [np.array(qrcode_poly, dtype=np.int32)], 0, (255, 255, 255), -1)

            # calculating coords, angle and centre of rotation
            coords = np.column_stack(np.where(qrcode_shape > 0))
            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45:
                angle = -(90 + angle)
            else:
                angle = -angle
            center = (width // 2, height // 2)

            # creating rotation matrix
            matrix = cv2.getRotationMatrix2D(center, angle, 1.0)

            # rotating image and its shape representation
            rotated_image = cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_CUBIC,
                                           borderMode=cv2.BORDER_REPLICATE)

            # declaring kernel_line and creating cropping shapes image
            kernel_line = np.ones((1, 3), np.uint8)
            cropping_shapes = cv2.erode(rotated_image, kernel_line, iterations=1)
            kernel_line = np.ones((2, 8), np.uint8)
            cropping_shapes = cv2.dilate(cropping_shapes, kernel_line, iterations=1)

            # creating main threshold and finding contours
            _, thresh = cv2.threshold(cropping_shapes, 248, 255, cv2.THRESH_BINARY_INV)
            contours, _ = cv2.findContours(thresh, 1, cv2.CHAIN_APPROX_SIMPLE)

            # declaring auxiliary list
            boxes = []

            # iterating through contours to add their coords to the list
            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                boxes.append([x, y, x + w, y + h])

            # checking if any barcode-like shapes have been found
            if not boxes:
                utils.sts("Ballot is not of express vote type", 3)
                utils.sts("     Blank page", 3)
                return None, None, None

            # detecting extreme edges to allow cropping
            boxes = np.asarray(boxes)
            left_crop_edge = np.min(boxes[:, 0])
            top_crop_edge = np.min(boxes[:, 1])
            right_crop_edge = np.max(boxes[:, 2])
            bottom_crop_edge = np.max(boxes[:, 3])

            # croppig image
            rotated_image = rotated_image[top_crop_edge - 5:bottom_crop_edge + 5, left_crop_edge - 10:right_crop_edge + 10]

            # locating the qrcode after rotation
            qrcode = barcode_decode(rotated_image)

            # calculating first column border
            for column_end_x in range(30, 1000):
                if math.ceil(sum(cv2.mean(rotated_image[barcodes[0].rect.top + barcodes[0].rect.height + 5:1690, column_end_x:column_end_x + 25]))) == 255:
                    break

            # OCR and joining the text of both columns
            first_column_text = ocr.ocr_core_expressvote(rotated_image[barcodes[0].rect.top + barcodes[0].rect.height + 5:1690, :column_end_x + 5])
            second_column_text = ocr.ocr_core_expressvote(rotated_image[barcodes[0].rect.top + barcodes[0].rect.height + 5:1690, column_end_x + 5:1300])
            both_columns = first_column_text + second_column_text

            # OCR of vertical code
            vertical_code = ocr.ocr_core(cv2.rotate(rotated_image[barcodes[0].rect.top + barcodes[0].rect.height + 5:, -200:], cv2.ROTATE_90_CLOCKWISE))

            return both_columns.splitlines(), vertical_code, qrcode[0]

        # if the first barcode is not a qrcode
        else:
            print("The ballot is not of Dominion type")
            return None, None, None

    # if no barcodes were found
    else:
        print("The ballot is not of Dominion type")
        return None, None, None


def expressvote_conversion(image, ballot_id, expressvote_header: str = ''):
    """
    This conversion is specific to ES&S BMD ballots from ExpressVote machines.
    :param image: (np.array) array of an image of Express Vote ballot
    :param expressvote_header: First three lines of the expressvote ballot
        template separated by commas.
    :return ev_header_code -- str of digits providing precinct, logical style, etc.
    :       bottom_strlist -- list of strings at the bottom, not categorized into contests or options.
    :       ev_coord_str_list (list) of XXYYPS digits specifying ballot target
                from barcodes.
    """
    # declaring initial height and width
    height, width = image.shape

    # declaring auxiliary variables for manual noise reduction
    noise_begun = False
    noise_ended = False
    noise_length = 0
    noise_bottom_buffer = 0

    # iterating throught upper 350 lines to detect if there is any noise to be deleted
    for noise_h in range(350):
        line = image[noise_h:noise_h + 1, 300:width - 300]
        intensity = math.ceil(sum(cv2.mean(line)))
        if intensity != 255 and not noise_begun and not noise_ended:
            noise_begun = True
        elif intensity != 255 and noise_begun and not noise_ended:
            noise_length += 1
        elif intensity == 255 and noise_begun and not noise_ended:
            noise_ended = True
        elif intensity == 255 and noise_ended:
            noise_bottom_buffer += 1
        elif intensity != 255 and noise_ended:
            noise_bottom_buffer = 0
        if noise_bottom_buffer == 20:
            noise_bottom_buffer = noise_h
            break

    # if noise was found, paint it white from the upper edge to the 20px buffer
    if noise_bottom_buffer != 0:
        image[:noise_bottom_buffer, :] = 255

    # declaring kernel_line and creating cropping shapes image
    kernel_line = np.ones((1, 3), np.uint8)
    cropping_shapes = cv2.erode(image, kernel_line, iterations=1)
    kernel_line = np.ones((2, 8), np.uint8)
    cropping_shapes = cv2.dilate(cropping_shapes, kernel_line, iterations=1)

    # clearing fixed vertical margins and clearing bottom margin after detection
    cropping_shapes[:, :200] = 255
    cropping_shapes[:, width - 200:] = 255
    for bottom_clearing_border in range(500, height):
        if sum(cv2.mean(cropping_shapes[bottom_clearing_border:bottom_clearing_border + 100, 200:width - 200])) == 255.0:
            break
    cropping_shapes[bottom_clearing_border + 50:, :] = 255

    # declaring kernel_line and creating basic shapes image
    kernel_line = np.ones((1, 15), np.uint8)
    basic_shapes = cv2.erode(image, kernel_line, iterations=1)
    kernel_line = np.ones((40, 1), np.uint8)
    basic_shapes = cv2.dilate(basic_shapes, kernel_line, iterations=1)
    basic_shapes = cv2.erode(basic_shapes, kernel_line, iterations=1)
    kernel_line = np.ones((1, 20), np.uint8)
    basic_shapes = cv2.dilate(basic_shapes, kernel_line, iterations=1)
    basic_shapes = cv2.erode(basic_shapes, kernel_line, iterations=1)

    # creating rotation threshold, coordinates, angle, center and matrix
    _, rotation_thresh = cv2.threshold(basic_shapes, 50, 255, cv2.THRESH_BINARY_INV)
    coords = np.column_stack(np.where(rotation_thresh > 0))
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    center = (width // 2, height // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)

    # rotating image and its shape representation
    rotated_image = cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_CUBIC,
                                   borderMode=cv2.BORDER_REPLICATE)
    rotated_shapes = cv2.warpAffine(cropping_shapes, matrix, (width, height), flags=cv2.INTER_CUBIC,
                                    borderMode=cv2.BORDER_REPLICATE)

    # creating main threshold and finding contours
    _, thresh = cv2.threshold(rotated_shapes, 248, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, 1, cv2.CHAIN_APPROX_SIMPLE)

    # declaring auxiliary list
    boxes = []

    # iterating through contours to add their coords to the list
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        boxes.append([x, y, x + w, y + h])

    # checking if any barcode-like shapes have been found
    if not boxes:
        utils.sts("Ballot is not of express vote type", 3)
        utils.sts("     Blank page", 3)
        return None, None, None

    # detecting extreme edges to allow cropping
    boxes = np.asarray(boxes)
    left_crop_edge = np.min(boxes[:, 0])
    top_crop_edge = np.min(boxes[:, 1])
    right_crop_edge = np.max(boxes[:, 2])
    bottom_crop_edge = np.max(boxes[:, 3])

    # croppig image
    rotated_image = rotated_image[top_crop_edge - 5:bottom_crop_edge + 5, left_crop_edge - 10:right_crop_edge + 10]

    # declaring final height and width
    height, width = rotated_image.shape

    # declaring kernel_line and creating basic shapes image
    kernel_line = np.ones((1, 10), np.uint8)
    shapes = cv2.erode(rotated_image, kernel_line, iterations=3)
    shapes = cv2.dilate(shapes, kernel_line, iterations=3)

    # redeclaring main threshold and finding contours
    _, thresh = cv2.threshold(shapes, 254, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, 1, cv2.CHAIN_APPROX_SIMPLE)

    # extracting and sorting barcodes
    barcodes = barcode_decode(rotated_image)
    barcodes.sort(key=lambda barcode: (int(math.floor(barcode.rect.top / 30.0)) * 30, barcode.rect.left))

    # checking if any barcode-like shapes have been found
    if not barcodes:
        utils.sts("Ballot is not of express vote type", 3)
        utils.sts("     No barcodes found", 3)
        return None, None, None

    top_barcodes_edge = []
    bottom_barcodes_edge = []
    for barcode in barcodes:
        top_barcodes_edge.append(barcode.rect.top)
        bottom_barcodes_edge.append(barcode.rect.top + barcode.rect.height)

    top_barcodes_edge = min(top_barcodes_edge) - 5
    bottom_barcodes_edge = max(bottom_barcodes_edge) + 5

    # dividing image into top (title), middle (barcodes) and bottom (results) parts
    top = rotated_image[:top_barcodes_edge, :]
    bottom = rotated_image[bottom_barcodes_edge + 15:, :]

    # OCR of the text from the top part
    kernel_line = np.ones((1, 2), np.uint8)
    top = cv2.erode(top, kernel_line, iterations=1)
    rotated_image[:top_barcodes_edge, :] = top
    top_text = ocr.ocr_core_expressvote(top)

    # Replace '8' with '0'. That's due to the OCR issue. If we don't
    # have to replace these chars then remove function call.
    top_text = re.sub(r'\n+', '\n', top_text).replace('8', '0').splitlines()

    # checking if OCR resulted in 4 lines
    if len(top_text) != 4 and len(top_text) != 5:
        utils.sts("Ballot is not of express vote type", 3)
        utils.sts("     Number of first lines do not match", 3)
        return None, None, None

    # matching first three lines
    if expressvote_header:
        headers = list_from_csv_str(expressvote_header)
        if not (fuzzy_match_expressvote_lines(top_text, headers)):
            utils.sts("Ballot does not match express vote header", 3)
            utils.sts("     Probably not express vote type.", 3)
            return None, None, None
    else:
        string = "### EXCEPTION: expressvote_header not provided in input file and no default was provided."
        utils.sts(string)
        return None, None, None

    # extracting logical_style_number
    ev_coord_str_list = [code.data.decode() for code in barcodes]
    ev_header_code = ev_coord_str_list.pop(0)  # first barcode is header code.

    # OCR of the text from the bottom part
    kernel_line = np.ones((4, 1), np.uint8)
    bottom[-15:, :] = cv2.dilate(bottom[-15:, :], kernel_line, iterations=1)
    kernel_line = np.ones((3, 1), np.uint8)
    bottom[-15:, :] = cv2.erode(bottom[-15:, :], kernel_line, iterations=1)
    kernel_line = np.ones((1, 2), np.uint8)
    bottom = cv2.erode(bottom, kernel_line, iterations=1)
    rotated_image[bottom_barcodes_edge + 15:, :] = bottom
    bottom_text = ocr.ocr_core_expressvote(bottom)
    bottom_text = re.sub(r'\n[^A-Z]+(?=[A-Z])', '\n', bottom_text)
    bottom_text = re.sub(r'(?<=[A-Z])[^A-Z\-]+\n', '\n', bottom_text)

    bottom_strlist = bottom_text.splitlines()
    
    return ev_header_code, bottom_strlist, ev_coord_str_list

COLOR_DICT = {'red': (0, 0, 255), 'blue': (255, 0, 0), 'green': (0, 255, 0)}

def create_redlined_images(argsdict, style_num, rois_map_df):
    """ Given the rois map and style_num, access image and create 'redlined' images
        which have boxes drawn around contests, options, and targets, and text
        shown providing official names of contests and options.
    """


    style_template_images = DB.load_template_images(style_num=style_num)
    rois_map_df = rois_map_df.replace(np.nan, 0)
    contest_roi_outline_width = 2
    contest_text_x_os   = 5
    contest_text_y_os   = -5                # offset from bottom of contest box
    contest_font_scale  = 0.5
    
    option_roi_outline_width = 1
    #option_text_x_os    = 80
    #option_text_y_os    = -5                # offset from bottom of option box
    option_font_scale   = 0.5
    
    checkbox_outline_width = 1              # integer required
    
    target_side = argsdict.get('target_side', 'left')
    
    rgb_images = [None, None]

    # first convert the (up to two) template images to RGB.
    for pg, grayscale_image in enumerate(style_template_images):
        rgb_images[pg] = cv2.cvtColor(grayscale_image, cv2.COLOR_GRAY2RGB)

    # consider only the records with the style_num indicated. Note that the
    # rois_map_df includes all styles processed so far.
    # note that 'style_num' field in the rois_map is a str.
    style_rois_map_df = rois_map_df.loc[rois_map_df['style_num'] == style_num]

    layout_params = get_layout_params(argsdict)

    target_w_os = round(layout_params['target_area_w'] / 2)
    target_h_os = round(layout_params['target_area_h'] / 2)

    for idx in range(len(style_rois_map_df.index)):
        style_rois_dict = style_rois_map_df.iloc[idx]
        
        roi = {}
        page0, roi['x'], roi['y'], roi['w'], roi['h'], \
            roi['blk_x'], roi['blk_y'], roi['blk_w'], roi['blk_h'] \
            = [int(x) for x in list(style_rois_dict['roi_coord_csv'].split(r','))]

        contest     = style_rois_dict['contest']
        option      = style_rois_dict['option']
        target_x    = style_rois_dict['target_x']
        target_y    = style_rois_dict['target_y']

        if bool(re.match(r'#', option)):
            # contest header, draw red box around countest header, write in contest name
            draw_one_box(rgb_images[page0], roi, color='red', line_width=contest_roi_outline_width)

            text_x = roi['x'] + contest_text_x_os
            text_y = roi['y'] + roi['h'] + contest_text_y_os
            
            draw_text(rgb_images[page0], text_x, text_y, text=contest, color='red', font_scale=contest_font_scale)
            
        else:
            # option rois
            draw_one_box(rgb_images[page0], roi, color='blue', line_width=option_roi_outline_width)
            draw_checkbox(rgb_images[page0], target_x, target_y, layout_params, line_width=checkbox_outline_width)

            ev_coord_str = str(style_rois_dict['ev_coord_str'])
            text = option
            if ev_coord_str:
                text += ' [' + ev_coord_str + ']'
                
            target_w_os = round(layout_params['target_area_w'] / 2)
            target_h_os = round(layout_params['target_area_h'] / 2)
            
            if target_side == 'left':
                text_x = target_x - target_w_os
                text_y = target_y - target_h_os - 2
                ref = 'bl'
            else:
                text_x = target_x + target_w_os
                text_y = target_y - target_h_os - 2
                ref = 'br'
            
            draw_text(rgb_images[page0], text_x, text_y, text=text, color='blue', font_scale=option_font_scale, ref=ref)
            
    DB.save_template_images(style_num=style_num, images=rgb_images, file_type='redlined')
    
def draw_text(rgb_image, text_x, text_y, text, color='red', font_scale=1, line_width=1, ref='bl'):
    """ Draw text on given rgb_image at text_x, text_y coordinates.
        Modifies image in-situ
    """    
    if ref == 'br':
        text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, line_width)
        text_length = text_size[0][0]
        text_x = text_x - text_length    
    
    cv2.putText(rgb_image, text,
                (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                font_scale, 
                COLOR_DICT[color], 
                line_width)


def draw_boxes_on_image(image, boxlist, color=['red'], line_width=1, convert_to_RGB=True, prefix_list=['']):
    """ given an image, modify it to RGB and draw red boxes on it
        at the coordinates 'x','y','w','h' in each item of boxlist.
    """
    if convert_to_RGB:
        rgb_image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    else:
        rgb_image = image.copy()

    for idx, prefix in enumerate(prefix_list):
        for box in boxlist:
            draw_one_box(rgb_image, box, color=color[idx], line_width=line_width, prefix=prefix)
    
    return rgb_image

def draw_one_box(rgb_image, box, color='red', line_width=1, prefix=''):
    """ given an RGB image and draw color boxes on it
        at the coordinates 'x','y','w','h' in box.
        modifies in-situ
    """
    try:
        x = int(box[f"{prefix}x"])
        y = int(box[f"{prefix}y"])
        w = int(box[f"{prefix}w"])
        h = int(box[f"{prefix}h"])
    except KeyError:
        return
    box_contour = np.asarray([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=int)
    cv2.drawContours(rgb_image, [box_contour], 0, COLOR_DICT[color], line_width)

def draw_checkbox(rgb_image, target_x, target_y, layout_params, color='blue', line_width=1):
    """ draw checkbox at location target_x, target_y and with size according to layout parameters.
        image must already be converted to RGB
        modifies in-situ
    """
    target_w_os = round(layout_params['target_area_w'] / 2)
    target_h_os = round(layout_params['target_area_h'] / 2)
    box = {
        'y': int(target_y - target_h_os),
        'x': int(target_x - target_w_os),
        'h': int(layout_params['target_area_h']),
        'w': int(layout_params['target_area_w']),
        }
    
    draw_one_box(rgb_image, box, color=color, line_width=line_width)

    

def outlines(image, mode,
             roi_contour, roi_outline_width=1, roi_color='red',
             checkbox_contour=[], checkbox_outline_width=1, checkbox_color='blue',
             text_x=0, text_y=0, text='', text_color='red', font_scale=1.0) -> np.array:
    """
    :param image: (np.array) image on which outlines and text will be created
        NOTE THAT INPUT IMAGE SHOULD BE ALREADY IN RGB, WHICH CAN BE DONE IN SUCH WAY:
        rgb_image = cv2.cvtColor(grayscale_image, cv2.COLOR_GRAY2RGB)
    :param mode: (int) specyfying moode
        (1 - roi outline)
        (2 - roi outline and text)
        (3 - roi and checkbox outlines and text)
    :param roi_color: (str) 'red', 'blue'
    :param roi_contour: contour of a ROI
    :param roi_outline_width: (int) width of ROI outline in pixels
    :param checkbox_contour: contour of a checkbox within ROI
    :param checkbox_outline_width: (int) width of a checkbox outline in pixels
    :param checkbox_color: (str)
    :param text_x: (int) x coordinate of text beginning in pixels
    :param text_y: (int) y coordinate of text beginning in pixels
    :param text: (str) text to be added
    :param text_color: (str)
    :param font_scale: (float) scale of a font
    :return: (np.array) altered image with outline(s) and text
    """
    cv2.drawContours(image, roi_contour, 0, COLOR_DICT[roi_color], roi_outline_width)
    if 2 <= mode <= 3:
        cv2.putText(image, text,
                    (text_x, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    font_scale, COLOR_DICT[text_color], 2)
    if mode == 3:
        cv2.drawContours(image, checkbox_contour, 0, COLOR_DICT[checkbox_color], checkbox_outline_width)
    return image


def ess_gen_timing_marks(image) -> dict:
    """
    :param image: np.array of an image, 
    :return: one page of timing_marks list (dict)
    argsdict is global
    """

    left_vertical_marks = []
    right_vertical_marks = []
    top_marks = []
    height, width = image.shape
                

    # setting up copy of an image, its threshold and contours
    image_backup = image.copy()
    _, thresh = cv2.threshold(image_backup, 254, 255, 1)
    contours, _ = cv2.findContours(thresh, 1, cv2.CHAIN_APPROX_NONE)

    # selecting border bars contours
    chosen_contours = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        mean = sum(cv2.mean(image_backup[y:y + h, x:x + w]))
        size = float(w) * h
        area = cv2.contourArea(cnt)
        hull = cv2.convexHull(cnt)
        hull_area = cv2.contourArea(hull)
        if hull_area == 0:
            hull_area = 0.001
        solidity = float(area) / hull_area
        if not (w > 12 and size > 200 and solidity > 0.85 and mean < 100):
            cv2.drawContours(image_backup, [cnt], 0, (255, 255, 255), -1)
        else:
            chosen_contours.append(cnt)

    # selecting side border bars contours
    final_contours = []
    max_y = 0
    for cnt in chosen_contours:
        x, y, w, h = cv2.boundingRect(cnt)
        offset = 25 + h
        upper_mean = sum(cv2.mean(image_backup[y - offset:y - offset + h, x:x + w]))
        lower_mean = sum(cv2.mean(image_backup[y + offset:y + offset + h, x:x + w]))
        if upper_mean > 250 and lower_mean > 250:
            cv2.drawContours(image_backup, [cnt], 0, (255, 255, 255), -1)
        else:
            final_contours.append(cnt)
            max_y = max(max_y, y)

    # splitting side contours into left and right ones
    # for now we will use only the left timing marks.
    # they should be close enough
    
    #right_coord = []
    for cnt in final_contours:
        x, y, w, h = cv2.boundingRect(cnt)

        if x < 50:
            left_vertical_marks.append({'x':x, 'y':y, 'w':w, 'h':h})
        elif x > width - 50:
            right_vertical_marks.append({'x':x, 'y':y, 'w':w, 'h':h})
        elif y > max_y - 10:
            top_marks.append({'x':x, 'y':y, 'w':w, 'h':h})

    
    left_vertical_marks     = sorted(left_vertical_marks,   key=lambda x: x['y']) # sort by y
    right_vertical_marks    = sorted(right_vertical_marks,  key=lambda x: x['y']) # sort by y
    top_marks               = sorted(top_marks,             key=lambda x: x['x']) # sort by x

    return {'left_vertical_marks': left_vertical_marks, 'right_vertical_marks': right_vertical_marks, 'top_marks': top_marks}



def get_images_from_pdf(filedict):
    """Returns a list of grayscale images parsed from PDF byte array.
        filedict['bytes_array'] has the file data.
    """
    images = []
    # TODO: Cannot find reference 'open' in '__init__.py | __init__.py'
    doc = fitz.open('pdf', filedict.get('bytes_array'))
    for page in doc:
        zoom_x = page.getImageList()[0][2] / page.CropBox.width
        zoom_y = page.getImageList()[0][3] / page.CropBox.height
        mat = fitz.Matrix(zoom_x, zoom_y)
        pix = page.getPixmap(mat)
        images.append(cv2.imdecode(
            np.fromstring(pix.getImageData(), dtype=np.uint8),
            cv2.IMREAD_GRAYSCALE))
    return images


def get_images_from_pbm(filedict):
    """Returns a list of images from the PBM file."""
    images = [cv2.imdecode(np.fromstring(
        filedict['bytes_array'], dtype=np.uint8), cv2.IMREAD_GRAYSCALE)]
    return images
    
    
def get_images_from_png(filedict):
    """Returns a list of images from the PNG file."""
    images = [cv2.imdecode(np.fromstring(
        filedict['bytes_array'], dtype=np.uint8), cv2.IMREAD_GRAYSCALE)]
    return images
    
def get_images_from_tif(filedict):
    """ Returns a list of images from the TIF file.
        this function writs the bytes_array out to a file 
        and uses cv2.imreadmulti() to convert it. 
        This is inefficient since the data is already in memory.
    """
    temp = NamedTemporaryFile(delete=False)
    temp.write(filedict['bytes_array'])
    temp.close()
    _, images = cv2.imreadmulti(temp.name, np.ndarray(0), cv2.IMREAD_GRAYSCALE)
    os.unlink(temp.name)
    final_images = []
    if len(images) > 2:
        images = images[:-1]
    for image in images:
        if sum(cv2.mean(image[:, :200])) < 250 and sum(cv2.mean(image[:, -200:])) < 250:
            final_images.append(image)
            
    return final_images
    
def read_raw_ess_barcode(image, ballot_id=''):
    """ This function reads the timing marks on left edge and extracts binary code
        based on the width of the timing marks.
        image: np.array image using cv2 format.
        returns card_code: hex string expressing the binary code starting at the top.
        returns None if the length of binary is incorrect.
        
        @@TODO: read_raw_ess_barcode: calculate region based on page size rather than config values.
        @@TODO: read_raw_ess_barcode: improve robustness of conversion so it is more immune to stray marks.
    """
    
    code_img = image[
               config_dict['CODE_ROI']['y']:
               config_dict['CODE_ROI']['y\''],
               config_dict['CODE_ROI']['x']:
               config_dict['CODE_ROI']['x\'']
               ]

    inner_code = ''
    _, code_thresh = cv2.threshold(
        code_img, config_dict['THRESHOLD']['code-contours'], 255, 1)
    code_contours, _ = cv2.findContours(code_thresh, 1, cv2.CHAIN_APPROX_SIMPLE)

    for code_cnt in reversed(code_contours):
        code_area = cv2.contourArea(code_cnt)
        x_1, y_1, x_2, y_2 = cv2.boundingRect(code_cnt)
        mean = sum(cv2.mean(code_img[y_1:y_1 + y_2, x_1:x_1 + x_2]))
        factor = (255.0 - mean + config_dict['CODE_MEAN_OFFSET']) / 255.0

        if config_dict['CODE_ROI']['max-size'] > code_area * factor \
                >= config_dict['CODE_ROI']['min-size']:
            inner_code += '0' if code_area * factor \
                                 < config_dict['THRESHOLD']['code'] else '1'
    if not len(inner_code) == config_dict['CODE_CHECKSUM']:
        utils.exception_report(
            f"### EXCEPTION: style inner code '{inner_code}' has {len(inner_code)} bits, "
            f"expected {config_dict['CODE_CHECKSUM']}. ballot_id:{ballot_id}")
        return None
    card_code = hex(int(inner_code, 2))
    return card_code

    
    

    
