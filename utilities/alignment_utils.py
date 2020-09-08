import math
import itertools
import cv2
import numpy as np
import statistics

from pyzbar.pyzbar import decode as barcode_decode

from utilities.config_d import config_dict
from utilities.images_utils import ess_gen_timing_marks
from utilities import ocr
from utilities import utils, logs
from models.DB import DB
from utilities import args

nominal_bar_width = 23  # pixels
nominal_full_bar_height = 58  # pixels
nominal_half_bar_height = 29  # pixels
nominal_bar_period = 46  # pixels

# the gap between the top data barcode and the timing marks is the same as they typical horizontal gap.
# then, we also extend above that the same amount plus a fudge factor.
region_height = (nominal_full_bar_height) * 2 + nominal_bar_period - nominal_bar_width

global dominion_barcode_area
dominion_barcode_area = {'x': 40, 'y': -region_height, 'w': 630, 'h': region_height}  # x,y,w,h location from lower lefthand corner

recent_cut_points_0 = []
recent_cut_points_1 = []
num_recent_cut_points = 256

# pylint: disable=too-many-locals
# Twenty six is reasonable in this case.
def ess_align_images(images) -> tuple:
    """
    This is specific to ES&S and should be renamed
    :param images: List of images to align.
    :return: Tuple of list with images and it's matrices determinants.
    """
    result_images = []
    determinants = []
    # pylint: disable=too-many-nested-blocks
    # Seven is reasonable in this case.
    for image in images:
        # defining threshold and reading contours
        _, thresh = cv2.threshold(
            image, config_dict['THRESHOLD']['frame-contours'], 255, 1)

        # preventive deletion of the lines overlying the edge bars
        kernel_line = np.ones((1, 6), np.uint8)
        thresh = cv2.erode(thresh, kernel_line, iterations=1)
        thresh = cv2.dilate(thresh, kernel_line, iterations=1)

        contours, _ = cv2.findContours(thresh, 1, cv2.CHAIN_APPROX_SIMPLE)

        # setting up points and lengths for further search
        left_top_point = (0, 0)
        right_top_point = (0, 0)
        left_bottom_point = (0, 0)
        right_bottom_point = (0, 0)
        left_top_length = config_dict['INITIAL_SEARCH_VALUES']
        right_top_length = config_dict['INITIAL_SEARCH_VALUES']
        left_bottom_length = config_dict['INITIAL_SEARCH_VALUES']
        # pylint: disable=too-many-locals
        right_bottom_length = config_dict['INITIAL_SEARCH_VALUES']
        # iterating through contours
        for cnt in contours:

            # approximating shape of contour, its area and its mean
            approx = cv2.approxPolyDP(cnt, config_dict['SHAPE_APPROX_VALUE']['code']
                                      * cv2.arcLength(cnt, True), True)
            area = cv2.contourArea(cnt)
            x, y, w, h = cv2.boundingRect(cnt)
            mean = sum(cv2.mean(image[y:y + h, x: x + w]))

            # checking if contour is rectangle over 300 pix
            # and less than 1000 pix and if mean intensity is less than 50
            if len(approx) == 4 and config_dict['CODE_ROI']['max-size'] > area \
                    >= config_dict['CODE_ROI']['min-size'] \
                    and mean < config_dict['CODE_ROI']['mean']:

                # checking if contour is within horizontal and vertical edges
                if cnt[0][0][0] > config_dict['EDGES_ROI']['right-border'] \
                        or cnt[0][0][0] < config_dict['EDGES_ROI']['left-border']:
                    if cnt[0][0][1] > config_dict['EDGES_ROI']['bottom-border'] \
                            or cnt[0][0][1] < config_dict['EDGES_ROI']['top-border']:

                        # iterating every n'th point of contour (for now n = 1)
                        for cnt_point in itertools.islice(cnt, None, None, 1):
                            # searching for left top point
                            if math.sqrt(
                                    pow(cnt_point[0][0] - 0, 2)
                                    + pow(cnt_point[0][1] - 0, 2)) \
                                    < left_top_length:
                                left_top_length = math.sqrt(
                                    pow(cnt_point[0][0] - 0, 2)
                                    + pow(cnt_point[0][1] - 0, 2))
                                left_top_point = cnt_point[0]

                            # searching for right top point
                            if math.sqrt(
                                    pow(cnt_point[0][0] - config_dict['ALIGNED_RESOLUTION']['x'], 2)
                                    + pow(cnt_point[0][1] - 0, 2)) \
                                    < right_top_length:
                                right_top_length = math.sqrt(
                                    pow(cnt_point[0][0]
                                        - config_dict['ALIGNED_RESOLUTION']['x'], 2)
                                    + pow(cnt_point[0][1] - 0, 2))
                                right_top_point = cnt_point[0]

                            # searching for left bottom point
                            if math.sqrt(
                                    pow(cnt_point[0][0] - 0, 2) + pow(cnt_point[0][1] -
                                                                      config_dict['ALIGNED_RESOLUTION']['y'], 2)) \
                                    < left_bottom_length:
                                left_bottom_length = math.sqrt(
                                    pow(cnt_point[0][0] - 0, 2)
                                    + pow(cnt_point[0][1] - config_dict['ALIGNED_RESOLUTION']['y'], 2))
                                left_bottom_point = cnt_point[0]

                            # searching for right bottom point
                            if math.sqrt(pow(cnt_point[0][0] - config_dict['ALIGNED_RESOLUTION']['x'], 2) + pow(
                                    cnt_point[0][1] - config_dict['ALIGNED_RESOLUTION']['y'], 2)) < right_bottom_length:
                                right_bottom_length = math.sqrt(
                                    pow(cnt_point[0][0]
                                        - config_dict['ALIGNED_RESOLUTION']['x'], 2)
                                    + pow(cnt_point[0][1]
                                          - config_dict['ALIGNED_RESOLUTION']['y'], 2))
                                right_bottom_point = cnt_point[0]

        # defining variables for current and desired points
        pts1 = np.float32([
            left_top_point,
            right_top_point,
            left_bottom_point,
            right_bottom_point,
        ])
        pts2 = np.float32([
            [0, 0],
            [config_dict['ALIGNED_RESOLUTION']['x'], 0],
            [0, config_dict['ALIGNED_RESOLUTION']['y']],
            [config_dict['ALIGNED_RESOLUTION']['x'], config_dict['ALIGNED_RESOLUTION']['y']],
        ])
        determinants.append(get_determinant_from_figure(pts1))

        # defining matrix for perspective transform and warping the perspective
        matrix = cv2.getPerspectiveTransform(pts1, pts2)
        image = cv2.warpPerspective(
            image, matrix, (
                config_dict['ALIGNED_RESOLUTION']['x'],
                config_dict['ALIGNED_RESOLUTION']['y'],
            ))

        # removing possible vertical lines on the timemarks
        image[:, :35] = cv2.dilate(image[:, :35], kernel_line, iterations=1)
        image[:, :35] = cv2.erode(image[:, :35], kernel_line, iterations=1)
        image[:, -35:] = cv2.dilate(image[:, -35:], kernel_line, iterations=1)
        image[:, -35:] = cv2.erode(image[:, -35:], kernel_line, iterations=1)

        # removing possible horizontal lines on the timemarks
        kernel_line = np.ones((6, 1), np.uint8)
        image[:30, :] = cv2.dilate(image[:30, :], kernel_line, iterations=1)
        image[:30, :] = cv2.erode(image[:30, :], kernel_line, iterations=1)
        image[-30:, :] = cv2.dilate(image[-30:, :], kernel_line, iterations=1)
        image[-30:, :] = cv2.erode(image[-30:, :], kernel_line, iterations=1)

        result_images.append(image)
    return result_images, determinants


def get_determinant_from_figure(figure: np.float32) -> float:
    """Calculates figure's x and y coordinates differences, side
    differences and sums them together as determinant.
    :param figure: An array of points indicating figure (ballot).
    :return: A float point sum of determinant based on differences.
    """
    y_top_diff = abs(figure[1, 1] - figure[0, 1])
    y_bot_diff = abs(figure[2, 1] - figure[3, 1])
    x_left_diff = abs(figure[0, 0] - figure[2, 0])
    x_right_diff = abs(figure[1, 0] - figure[3, 0])

    top_side_length = np.linalg.norm(figure[0] - figure[1])
    bot_side_length = np.linalg.norm(figure[2] - figure[3])
    left_side_length = np.linalg.norm(figure[0] - figure[2])
    right_side_length = np.linalg.norm(figure[1] - figure[3])

    top_bot_diff = abs(top_side_length - bot_side_length)
    left_right_diff = abs(left_side_length - right_side_length)

    determinant = sum([y_top_diff, y_bot_diff, x_left_diff, x_right_diff, top_bot_diff,
                       left_right_diff])
    return determinant


def dominion_erode_dilate_contours(page, page_height, page_width):
    """
    Remove imperfections.
    :param page: (np.array) array of an image of the page
    :param page_height: (int) height of the page in pix
    :param page_width: (int) width of the page in pix
    :return: (np.array) array of an image of the page with minor shapes removed
    """

    # clearing upper edge
    page[:50, :] = 255
    page[:, :30] = 255
    page[:, page_width - 30:] = 255

    # checking for right and left edge black stripes and deleting them
    if sum(cv2.mean(page[:, 0:1])) < 15:
        for edge_border in range(1, 50):
            if math.floor(sum(cv2.mean(page[:, edge_border - 1:edge_border]))) > 225:
                page[:, 0:edge_border] = 255
    if sum(cv2.mean(page[:, page_width - 1:])) < 15:
        for edge_border in range(1, 50):
            if math.floor(sum(cv2.mean(page[:, page_width - edge_border - 1:page_width - edge_border]))) > 225:
                page[:, page_width - edge_border:] = 255

    # eroding end diliting the image to get rid of white dots within timing marks
    kernel_line = np.ones((5, 5), np.uint8)
    bottom_basic_shapes = cv2.erode(page[page_height-200:, :], kernel_line, iterations=1)
    bottom_basic_shapes = cv2.dilate(bottom_basic_shapes, kernel_line, iterations=1)

    kernel_line = np.ones((1, 15), np.uint8)
    bottom_basic_shapes = cv2.dilate(bottom_basic_shapes, kernel_line, iterations=1)
    bottom_basic_shapes = cv2.erode(bottom_basic_shapes, kernel_line, iterations=1)

    kernel_line = np.ones((60, 1), np.uint8)
    bottom_basic_shapes = cv2.dilate(bottom_basic_shapes, kernel_line, iterations=1)
    bottom_basic_shapes = cv2.erode(bottom_basic_shapes, kernel_line, iterations=1)

    # horizontal and vertical eroding end dilating for final distortion removal
    kernel_line = np.ones((5, 5), np.uint8)
    basic_shapes = cv2.erode(page, kernel_line, iterations=1)
    basic_shapes = cv2.dilate(basic_shapes, kernel_line, iterations=1)

    # vertical dilating end eroding lines and text for only major marks to remain
    kernel_line = np.ones((1, 15), np.uint8)
    basic_shapes = cv2.dilate(basic_shapes, kernel_line, iterations=1)
    basic_shapes = cv2.erode(basic_shapes, kernel_line, iterations=1)

    # horizontal dilating end eroding lines and text for only major marks to remain
    kernel_line = np.ones((60, 1), np.uint8)
    basic_shapes = cv2.dilate(basic_shapes, kernel_line, iterations=1)
    basic_shapes = cv2.erode(basic_shapes, kernel_line, iterations=1)

    # clearing middle part of the image
    basic_shapes[400:page_height - 400, :] = 255
    basic_shapes[page_height-200:, :] = bottom_basic_shapes

    return basic_shapes


def dominion_get_points(basic_shapes, page_height, page_width):
    """
    Fine points so we can align this page properly
    :param basic_shapes: (np.array) array of an image of the page with minor shapes removed
    :param page_height: (int) height of the page in pix
    :param page_width: (int) width of the page in pix
    :return: (list) list of points out of which top and bottom contours are made
    """
    enable_diagnostic_messages = False

    # declaring auxiliary variables
    alignment_block_max_w = page_width / 8
    alignment_block_min_h = 55
    alignment_block_min_area = 3000
    alignment_block_max_area = 12000
    alignment_block_left_x_border = 100
    alignment_block_right_x_border = page_width - 250
    alignment_block_top_y_border = 225
    alignment_block_bottom_y_border = page_height - 400
    bottom_shapes_left_x_border = page_width - 600
    bottom_shapes_right_x_border = page_width - 75
    bottom_shapes_y_border = page_height - 400

    # declaring list of corner contours
    corner_contours = []
    corner_marks = []

    if enable_diagnostic_messages:
        utils.sts("    Clearing basic shapes, except for alignment block areas", 3)
    basic_shapes[alignment_block_top_y_border:alignment_block_bottom_y_border, :] = 255

    # searching for top contours
    _, thresh = cv2.threshold(basic_shapes[:alignment_block_top_y_border+75, :], 254, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, 1, cv2.CHAIN_APPROX_SIMPLE)

    # adding found top contours to the list of corner contours
    for cnt in contours:
        #area = cv2.contourArea(cnt)
        x, y, w, h = cv2.boundingRect(cnt)
        if alignment_block_min_h < h < w < alignment_block_max_w \
                and alignment_block_min_area < w*h < alignment_block_max_area \
                and not (alignment_block_left_x_border < x < alignment_block_right_x_border):
            corner_marks.append({
                'x': x,
                'w': w,
                'y': y,
                'h': h
            })

    # searching for bottom contours
    _, thresh = cv2.threshold(basic_shapes[alignment_block_bottom_y_border + 100:, :], 254, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, 1, cv2.CHAIN_APPROX_SIMPLE)

    # adding found bottom contours to the list of corner contours
    for cnt in contours:
        #area = cv2.contourArea(cnt)
        x, y, w, h = cv2.boundingRect(cnt)
        if alignment_block_min_h < h < w < alignment_block_max_w \
                and alignment_block_min_area < w * h < alignment_block_max_area \
                and not (alignment_block_left_x_border < x < alignment_block_right_x_border):
            corner_marks.append({
                'x': x,
                'w': w,
                'y': page_height - 300 + y,
                'h': h
            })

    # sorting corner marks smallest to biggest and choosing first three
    corner_marks = sorted(corner_marks, key=lambda corner_mark: corner_mark['w'] * corner_mark['h'])
    corner_marks = corner_marks[-3:]

    # sorting corner marks left to right and choosing first two
    corner_marks = sorted(corner_marks, key=lambda corner_mark: corner_mark['x'])
    corner_marks = corner_marks[:2]

    # in case two corner marks weren't found
    if len(corner_marks) != 2:
        return None, None

    if enable_diagnostic_messages:
        utils.sts("    Regenerating demaged left alignment blocks", 3)
    # compensating for horizontally demaged alignment blocks
    # via the horizontal comparison and modifying the shorter one
    if abs(corner_marks[0]['w'] - corner_marks[1]['w']) > 4:
        diff = abs(corner_marks[1]['w'] - corner_marks[0]['w'])
        if corner_marks[0]['w'] > corner_marks[1]['w']:
            corner_marks[1]['w'] = corner_marks[1]['w'] + diff
            corner_marks[1]['x'] = corner_marks[1]['x'] - diff
            basic_shapes[
            corner_marks[1]['y']:
            corner_marks[1]['y'] + corner_marks[1]['h'],
            corner_marks[1]['x']:
            corner_marks[1]['x'] + corner_marks[1]['w']] = 0
        else:
            corner_marks[0]['w'] = corner_marks[0]['w'] + diff
            corner_marks[0]['x'] = corner_marks[0]['x'] - diff
            basic_shapes[
            corner_marks[0]['y']:
            corner_marks[0]['y'] + corner_marks[0]['h'],
            corner_marks[0]['x']:
            corner_marks[0]['x'] + corner_marks[0]['w']] = 0

    # compensating for vertically demaged alignment blocks
    # via the vertical comparison and modifying the shorter one
    if abs(corner_marks[0]['h'] - corner_marks[1]['h']) > 4:
        diff = abs(corner_marks[1]['h'] - corner_marks[0]['h'])
        if corner_marks[0]['h'] > corner_marks[1]['h']:
            corner_marks[1]['h'] = corner_marks[1]['h'] + diff
            corner_marks[1]['y'] = corner_marks[1]['y'] - diff
            basic_shapes[
            corner_marks[1]['y']:
            corner_marks[1]['y'] + corner_marks[1]['h'],
            corner_marks[1]['x']:
            corner_marks[1]['x'] + corner_marks[1]['w']] = 0
        else:
            corner_marks[0]['h'] = corner_marks[0]['h'] + diff
            corner_marks[0]['y'] = corner_marks[0]['y'] - diff
            basic_shapes[
            corner_marks[0]['y']:
            corner_marks[0]['y'] + corner_marks[0]['h'],
            corner_marks[0]['x']:
            corner_marks[0]['x'] + corner_marks[0]['w']] = 0

    if enable_diagnostic_messages:
        utils.sts("    Finding the points of all alignemnt blocks", 3)
    # searching for contours containing alignment blocks
    _, thresh = cv2.threshold(basic_shapes, 254, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, 1, cv2.CHAIN_APPROX_SIMPLE)

    # adding suspected alignment blocks to the list of corner contours
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if alignment_block_min_h < h < w < alignment_block_max_w \
                and alignment_block_min_area < w * h < alignment_block_max_area \
                and not (alignment_block_left_x_border < x < alignment_block_right_x_border):
            corner_contours.append(cnt)

    # sorting corner marks smallest to biggest and choosing first three
    corner_contours = sorted(corner_contours, key=lambda corner_contour: cv2.contourArea(corner_contour))
    corner_contours = corner_contours[-3:]

    # declaring and filling list of points of which top and bottom contours consist
    points = []
    for cnt in corner_contours:
        for point in cnt:
            points.append(point[0])

    # clearing everything but the bottom right part of 'basic_spaes'
    basic_shapes[:bottom_shapes_y_border, :] = 255
    basic_shapes[:, :bottom_shapes_left_x_border] = 255

    # searching for bottom contours
    _, thresh = cv2.threshold(basic_shapes, 254, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, 1, cv2.CHAIN_APPROX_SIMPLE)

    bottom_contours = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if x < bottom_shapes_right_x_border:
            bottom_contours.append(cnt)

    return points, bottom_contours


def dominion_find_corner_points(points, bottom_contours, page_height, page_width):
    """
    This function does more than just sorting the points!
    :param points: (list) list of points out of which top and bottom contours are made
    :param bottom_contours: (list) list of contours of the bottom right corner marks
    :param page_height: (int) height of the page in pix
    :param page_width: (int) width of the page in pix
    :return: (4 x list) four points closest to the page corners

    """

    # Ray says: This function does not appear to very carefully discriminate what
    # the contours are that it is looking at. It assumes that whatever contours are closest
    # to the assumed corners based on the passed dimensions are the correct ones.
    # a more robust solution would be to carefully review the shape of either the corner
    # alignment blocks or the nearby timing marks.
    #
    # this will likely fail to produce good results when the timing marks are slightly
    # corrupted, say if a corner is folded over.


    # sorting points by range to bottom left corner and choosing the closest one
    points = sorted(
        points,
        key=lambda point: math.sqrt(
            pow(0 - point[0], 2) +
            pow(page_height - point[1], 2)
        ))
    bottom_left_point = points[0]

    # sorting points by range to top right corner and choosing the closest one
    points = sorted(
        points,
        key=lambda point: math.sqrt(
            pow(page_width - point[0], 2) +
            pow(0 - point[1], 2)
        ))
    top_right_point = points[0]

    # sorting points by range to top left corner and choosing the closest one
    points = sorted(
        points,
        key=lambda point: math.sqrt(
            pow(0 - point[0], 2) +
            pow(0 - point[1], 2)
        ))
    top_left_point = points[0]

    # sorting bottom contours by range to bottom right corner
    bottom_contours = sorted(
        bottom_contours,
        key=lambda point: math.sqrt(
            pow(page_width - point[0][0][0], 2) +
            pow(page_height - point[0][0][1], 2)
        ))

    try:
        # declaring x, y, w and h of first, secont and last contours
        last_x, last_y, last_w, last_h = cv2.boundingRect(bottom_contours[-1])
        mid_x, mid_y, mid_w, mid_h = cv2.boundingRect(bottom_contours[1])
        first_x, first_y, first_w, first_h = cv2.boundingRect(bottom_contours[0])
    except IndexError:
        return [None, None], [None, None], [None, None], [None, None]

    # declaring initial bottom right point
    bottom_right_point = [first_x + first_w, first_y + first_h]

    # calculating deltas of x and y changes between contours across the bottom
    delta_x1 = first_x + first_w - (last_x + last_w)
    delta_y1 = first_y + first_h - (last_y + last_h)

    # calculating the slope
    slope = delta_y1 / delta_x1

    # declaring the offset by which deltas should be calculated
    # offset is the distance from the last timing mark to the right side of the right timing mark.
    # for Leon county, the distance is 66.
    # Q: is the slope calculation needed?
    # A: Yes. The slope necessary to move it by one pixel is such that with round to a unit, it is moved by just over 0.5 unit.
    #    thus, slope * offset > 0.5
    #       slope > 0.5 / offset = 0.5 / 66 = 0.00757
    #    across the page width 1758 * 0.00757 = 13 pixels, or 0.065", about 2.72 degrees.
    #
    # correction was made to caculation below because it should use 'round' and not 'int', or it will require a full 0.13"
    #
    if first_x - mid_x - mid_w < 30:
        x_offset = 66
    else:
        x_offset = 112

    delta_y = round(x_offset * slope)

    # calculating bottom right point
    bottom_right_point = [int(bottom_right_point[0] + x_offset), int(bottom_right_point[1] + delta_y)]

    if False:
        utils.sts(   "dominion_find_corner_points\n" \
                    f"Nominal page H:{page_height}, W:{page_width}\n" \
                    f"Total number of points considered: {len(points)}\n" \
                    f"Bottom Contours: First XYWH {first_x, first_y, first_w, first_h}, Mid XYWH {mid_x, mid_y, mid_w, mid_h}, Last XYWH {last_x, last_y, last_w, last_h}\n" \
                    f"slope: {slope} delta_y: {delta_y}\n" \
                    f"Resolved Corners: BL_point {bottom_left_point}, TR_point {top_right_point}, TL_point {top_left_point}, BR_point: {bottom_right_point}" \
                    , 3)

    return bottom_left_point, top_right_point, top_left_point, bottom_right_point


def dominion_transform(page, bottom_left_point, top_right_point, top_left_point, bottom_right_point):
    """
    Align the image.
    :param page: (np.array) array of an image of the page
    :param bottom_left_point: (list) the point closest to bottom left page corner
    :param top_right_point: (list) the point closest to top right page corner
    :param top_left_point: (list) the point closest to top left page corner
    :param bottom_right_point: (list) the point closest to bottom right page corner
    :return: (np.array) array of an image of the page after perspective transform
    """

    # declaring list of destination points for perspective transform
    destination_points = np.array([
        [0, 0],
        [config_dict['ALIGNED_RESOLUTION']['x'] + 1, 0],
        [config_dict['ALIGNED_RESOLUTION']['x'] + 1, config_dict['ALIGNED_RESOLUTION']['y'] + 1],
        [0, config_dict['ALIGNED_RESOLUTION']['y'] + 1]], dtype="float32")

    # declaring list of source points for perspective transform
    source_points = np.array([
        top_left_point,
        top_right_point,
        bottom_right_point,
        bottom_left_point], dtype="float32")

    # declaring transformation matrix and transforming the page
    M = cv2.getPerspectiveTransform(source_points, destination_points)
    page = cv2.warpPerspective(page, M, (config_dict['ALIGNED_RESOLUTION']['x'], config_dict['ALIGNED_RESOLUTION']['y']))
    return page


def dominion_get_code(barcode_area, page0: int, ballot_id: str) -> tuple:
    """
    Decode the Dominion-specific barcode which is at the bottom of a HMPB.
    It is not a standard barcode. This produces card_code which must be further
    processed to get a reduced number of styles indicted by style_num

    :param barcode_area: (np.array) array of an image of the barcode area of the page
    :param page0: (int) 0 or 1 describing the side of the ballot sheet.
    :param ballot_id: (str) provided to allow diagnostic exception reports
    :return: (int) (card_code, page_sheet, diagnostic_str)
    """
    """
    Upon entry to this function should be the left-bottom fragment of the page.
    There are 10 data bars. The first 8 encode 16 bits of card_code and the other
    Four bits encode the page and sheet.
    This will look as follows:

             Bar #     0     1     2     3     4     5     6     7     8     9     10

                [#]   [0]   [2]   [4]   [6]   [8]   [A]   [C]   [E]   [S0]  [P0]  [#]
                [#]   [0]   [2]   [4]   [6]   [8]   [A]   [C]   [E]   [S0]  [P0]  [#]
                [#]   [1]   [3]   [5]   [7]   [9]   [B]   [D]   [F]   [S1]  [P1]  [#]
                [#]   [1]   [3]   [5]   [7]   [9]   [B]   [D]   [F]   [S1]  [P1]  [#]

    [#############]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]
    [#############]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]
    [#############]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]
    [#############]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]

    The bottom row of marks are the timing marks at the bottom edge of the page.
    These are important to provide the location of the expected barcode marks.
    Sn are the sheet number
    Pn is the page (side).

                                                  FEDC BA98 7654 3210
    For example, for style number 3369 = 0x0D29 = 0000 1101 0010 1001

                [#]   [0]                     [8]   [A]                           [#]
                [#]   [0]                     [8]   [A]                           [#]
                [#]         [3]   [5]               [B]                           [#]
                [#]         [3]   [5]               [B]                           [#]

    [#############]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]
    [#############]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]
    [#############]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]
    [#############]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]   [#]
    """

    diagnostic_mode = False

    """
    # declaring kernell and clearing bottom part of the barcode area
    kernel_line = np.ones((3, 3), np.uint8)
    barcode_area[70:, :] = cv2.erode(barcode_area[70:, :], kernel_line, iterations=1)
    barcode_area[70:, :] = cv2.dilate(barcode_area[70:, :], kernel_line, iterations=1)
    kernel_line = np.ones((50, 18), np.uint8)
    barcode_area[70:, :] = cv2.dilate(barcode_area[70:, :], kernel_line, iterations=1)
    barcode_area[70:, :] = cv2.erode(barcode_area[70:, :], kernel_line, iterations=1)
    barcode_area[139:, :] = 255
    """

    if False:  # ballot_id == '25032_00000_874738':
        diagnostic_mode = True
        import pdb;
        pdb.set_trace()

    diagnostic_str = f"barcode diagnostic info: ballot_id={ballot_id}\n"

    # general cleanup
    kernel_line = np.ones((3, 3), np.uint8)
    barcode_area = cv2.erode(barcode_area, kernel_line)  # , iterations=1)
    barcode_area = cv2.dilate(barcode_area, kernel_line)  # , iterations=1)

    if diagnostic_mode:
        DB.save_alignment_image(ballot_id=ballot_id, image=barcode_area, type=f"modified0_barcode_area_p{page0}")

    # this second step removes any text smaller than a small block
    kernel_line = np.ones((nominal_half_bar_height - 5, nominal_bar_width - 5), np.uint8)
    barcode_area = cv2.dilate(barcode_area, kernel_line)  # , iterations=1)
    barcode_area = cv2.erode(barcode_area, kernel_line)  # , iterations=1)

    # clear out the edge of the image so contours will be found that butt up to the edge.
    height, width = barcode_area.shape
    barcode_area[:2, :] = 255
    barcode_area[(height - 2):, :] = 255

    if diagnostic_mode:
        DB.save_alignment_image(ballot_id=ballot_id, image=barcode_area, type=f"modified1_barcode_area_p{page0}")

    # extracting contours and gathering bars x coordinates and width
    # contours, _ = cv2.findContours(barcode_area[70:, :], 1, cv2.CHAIN_APPROX_NONE)
    contours, _ = cv2.findContours(barcode_area, 1, cv2.CHAIN_APPROX_NONE)
    timing_bars = []
    data_bars = []

    bar_gap = nominal_bar_period - nominal_bar_width

    bar_w_margin = int((nominal_bar_period - nominal_bar_width) / 2) - 1  # bars can grow 25% on each side
    bar_min_w_thres = nominal_bar_width - bar_w_margin
    bar_max_w_thres = nominal_bar_width + bar_w_margin

    bar_h_margin = int((nominal_full_bar_height - nominal_half_bar_height) / 2) - 1
    full_bar_min_h_thres = nominal_full_bar_height - bar_h_margin
    full_bar_max_h_thres = nominal_full_bar_height + bar_h_margin
    half_bar_min_h_thres = nominal_half_bar_height - bar_h_margin
    half_bar_max_h_thres = nominal_half_bar_height + bar_h_margin

    timing_y_thres = height - nominal_full_bar_height - bar_gap - half_bar_min_h_thres  # further down barcode_area than this point are the timing marks.

    diagnostic_str += f"full_bar_min_h_thres = {full_bar_min_h_thres}\n" \
                      f"full_bar_min_h_thres  = {full_bar_min_h_thres}\n" \
                      f"full_bar_max_h_thres  = {full_bar_max_h_thres}\n" \
                      f"half_bar_min_h_thres  = {half_bar_min_h_thres}\n" \
                      f"half_bar_max_h_thres  = {half_bar_max_h_thres}\n" \
                      f"timing_y_thres        = {timing_y_thres}\n" \
                      f"bar_min_w_thres       = {bar_min_w_thres}\n" \
                      f"bar_max_w_thres       = {bar_max_w_thres}\n" \
                      f"bar_h_margin          = {bar_h_margin}\n" \
                      f"bar_w_margin          = {bar_w_margin}\n"

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        diagnostic_str += f"Contour found: {x, y, w, h}\n"

        if not (bar_min_w_thres < w < bar_max_w_thres):
            continue

        if y > timing_y_thres:
            if (full_bar_min_h_thres < h < full_bar_max_h_thres):
                timing_bars.append({'x': x, 'w': w})
        else:
            # above threshold means data bars
            if (full_bar_min_h_thres < h < full_bar_max_h_thres) or \
                    (half_bar_min_h_thres < h < half_bar_max_h_thres):
                data_bars.append({'x': x, 'y': y, 'w': w, 'h': h})

    # sort timing_bars by x coordinates and choosing first 10
    timing_bars = sorted(timing_bars, key=lambda bar: bar['x'])
    data_bars = sorted(data_bars, key=lambda bar: bar['x'])

    if not data_bars:
        diagnostic_str += "dominion_get_code failed to find any data bars; saving barcode area\n"
        utils.exception_report(diagnostic_str + f"saving barcode area for ballot_id: {ballot_id}")
        DB.save_alignment_image(ballot_id=ballot_id, image=barcode_area, type=f"modified1_barcode_area_p{page0}")
        return None, None, diagnostic_str

    timing_bars = timing_bars[:10]

    diagnostic_str += f"Reduced Timing Bars found: {timing_bars}\n"
    diagnostic_str += f"Data Bars found: {data_bars}\n"

    # first data bar is a full bar and it provides location of the rest.
    data_bar_top = data_bars[0]['y']
    data_bar_mid = data_bar_top + nominal_half_bar_height

    # declaring empty code string
    code = ""

    # iterating through bars and spaces ids
    for timing_bar in timing_bars:
        timing_x = timing_bar['x']
        diagnostic_str += f"Checking slot: {timing_x}\n"

        # look for data bar in this slot, skip bars to the left
        upper_bit = '0'
        lower_bit = '0'
        for data_bar in data_bars:
            if (timing_x - bar_w_margin) < data_bar['x'] < (timing_x + bar_w_margin):
                diagnostic_str += f"Data Bar Found : {data_bar}\n"
                # located data bar in this slot. Evaluate it.
                if data_bar_top - bar_h_margin < data_bar['y'] < data_bar_top + bar_h_margin:
                    upper_bit = '1'
                    if data_bar['h'] > full_bar_min_h_thres:
                        lower_bit = '1'
                elif data_bar_mid - bar_h_margin < data_bar['y'] < data_bar_mid + bar_h_margin:
                    lower_bit = '1'
                break

        # adding 0/1 to code dependent on upper bit (lsb)
        code += upper_bit
        code += lower_bit

        diagnostic_str += f"Code: {code}\n"

    try:
        revcode = int(code[::-1], 2)  # reversing the bit order
        card_code = revcode & 0xFFFF  # isolate just the style number.
        sheet_page = int(code, 2) & 0xF  # page and sheet are not reversed
        diagnostic_str += f"Card code: {card_code} sheet_page:{sheet_page}\n"
        if diagnostic_mode:
            utils.sts(diagnostic_str, 3)

        return card_code, sheet_page, diagnostic_str
    except ValueError:
        # the above may fail with "ValueError: invalid literal for int() with base 2: ''
        utils.exception_report(f"EXCEPTION: dominion_get_code failed to interpret style code; ballot_id: {ballot_id}\n" + diagnostic_str)
    return None, None, diagnostic_str


def list_stats (lst: list) -> tuple:
    """ returns set of stats for list as tuple
        0 avg, 1 min, 2 max, 3 median
    """
    num = len(lst)
    if num == 0:
        return (0,0,0,0)
    return (round(sum(lst)/num, 2), min(lst), max(lst), lst[int(num/2)])


def vertical_mark_stats_str(marks, location:str) -> str:
    num = len(marks)
    hlist = sorted([x['h'] for x in marks])
    wlist = sorted([x['w'] for x in marks])
    Tlist = sorted([marks[i]['y']-marks[i-1]['y'] for i in range(1,num)])

    hstats = list_stats(hlist)
    wstats = list_stats(wlist)
    Tstats = list_stats(Tlist)

    return  f"stats: {location}; num:{num}\n" \
            f"havg:{hstats[0]} hmin:{hstats[1]} hmax:{hstats[2]} hmed:{hstats[3]}\n" \
            f"wavg:{wstats[0]} wmin:{wstats[1]} wmax:{wstats[2]} wmed:{hstats[3]}\n" \
            f"Tavg:{Tstats[0]} Tmin:{Tstats[1]} Tmax:{Tstats[2]} Tmed:{Tstats[3]}\n"

def generic_get_timing_marks(images, ballot_id):
    """ Given set of images for ballot ballot_id, return timing marks structure for given vendor.
        returns None if timing marks encountered an exception, reporting done when the error is encountered.
    """

    timing_marks = [{},{}]

    for page_idx, image in enumerate(images):
        timing_marks[page_idx] = generic_get_timing_marks_one_p(image, ballot_id, page_idx)

        # note that some pages may not provide any timing marks. Okay to return only those
        # that were detected.
        #if not timing_marks[page_idx]:
        #    return None

    return timing_marks

def generic_get_timing_marks_one_p(image, ballot_id, page):
    """ return timing marks for one image for given vendor.
        uses args.argsdict to discover the vendor
        image, one side of a ballot
        ballot_id, page provided for status messages.
        If there is any error, return None.
    """

    timing_marks_one_p =  {}

    vendor = args.argsdict['vendor']

    if vendor == 'Dominion':
        timing_marks_one_p['left_vertical_marks'], \
        timing_marks_one_p['right_vertical_marks'], \
        timing_marks_one_p['top_marks'] = \
            dominion_get_timing_marks(image, ballot_id, page)

    elif vendor == 'ES&S':
        timing_marks_one_p = ess_gen_timing_marks(image)

    else:
        utils.exception_report(f"Vendor {vendor} not supported")

    if not (timing_marks_one_p['left_vertical_marks'] and \
            timing_marks_one_p['right_vertical_marks'] and \
            timing_marks_one_p['top_marks']):
        return None

    return timing_marks_one_p

def are_timing_marks_consistent(timing_marks):
    """ Review a set of timing marks and return False if they do not seem consistent.
        Timing marks must exist on page 1 but may be missing for page 2.
        However, if page 2 marks exist, then they also must be consistent.
    """

    if timing_marks is None:
        utils.sts("No timing marks found", 3)
        import pdb; pdb.set_trace()
        return False
    for page in range(2):
        try:
            page_marks = timing_marks[page]
            Ledge_marks = page_marks['left_vertical_marks']
            Redge_marks = page_marks['right_vertical_marks']
            #Tedge_marks = page_marks['top_marks']
        except:
            if page == 0:
                utils.sts("Timing Marks inconsistent on page 0", 3)
                return False
            else:
                # it is allowed for second page to be blank.
                return True
        if not len(Ledge_marks) == len(Redge_marks):
            utils.sts(f"Left edge timing marks inconsistent with right edge on page {page}", 3)
            return False
    return True

def analyze_failing_timing_marks(timing_marks, x_or_y):
    """ in the case when we are missing timing marks for some reason,
        analyze the marks and look for missing marks.
        produce error report suitable for inclusion in exception report file.
        and list of (gap offset, gap size)
        x_or_y is either 'x' or 'y', the coordinate to the analyzed.
    """
    if not timing_marks:
        str = "Vertical edge timing_marks list is empty."
        return str, []

    pos_list = sorted([t[x_or_y] for t in timing_marks])
    dif_list = [abs(pos_list[i] - pos_list[i-1]) for i in range(1, len(pos_list))]
    typ_dif  = statistics.median(dif_list)
    gap_list = []
    missing_marks = 0

    #import pdb; pdb.set_trace()

    for i in range(len(dif_list)):
        if dif_list[i] > typ_dif * 1.5:
            dif = dif_list[i]
            gap_size = int((dif + typ_dif/2) / typ_dif) - 1
            gap_list.append( (i, gap_size) )    # append one tuple per gap.
            missing_marks += gap_size

    str = f"{len(gap_list)} gaps found, total of {missing_marks} timing marks missing: gap_list:{gap_list}"
    return str, gap_list
    
def extract_contours_from_region(image, region, kernels={'blk':(3,3),'wht':(3,3)}, diagnostic_mode = False, find_contours=True):
    """ given an image, isolate region at x, y, w, h and find contours around black boxes.
        region is dict with 'x,' 'y', 'w', 'h' within image from top,left corner
        kernels is used in cleaning up the image.
            This removes small imperfections smaller than the dimensions of the kernel.
            But if the kernel is too large, it will join areas.
            kernels['wht'}: (x,y) tuple: dilation followed by erosion, removes black imperfections.
                this kernel should be smaller than the smallest black to be preserved.
            kernels['blk'}: (x,y) tuple: dilation followed by erosion, removes white imperfections.
                this kernel should normally be relatively small or black areas will combine.
        Returns list of boxes of first white rectangle round black regions.
    """

    working_image = utils.extract_region(image, region, mode='clear')

    # declaring kernel for erosion and dilation
    # dilation followed by erosion removes black spots from white areas.
    wht_kernel = np.ones(kernels['wht'], np.uint8)
    working_image = cv2.dilate(working_image, wht_kernel)
    working_image = cv2.erode(working_image, wht_kernel)

    # erosion followed by dilation removes spots from black areas.
    # this kernel should normally be relatively small or black areas will combine.
    blk_kernel = np.ones(kernels['blk'], np.uint8)
    working_image = cv2.erode(working_image, blk_kernel)
    working_image = cv2.dilate(working_image, blk_kernel)

    # clearing borderlines of images to allow propper mark contours search
    working_image[:, :1] = 255      # Clear leftmost column
    working_image[:, -1:] = 255     # Clear rightmost column
    working_image[:1, :] = 255      # Clear top row
    working_image[-1:, :] = 255     # Clear bottom row

    # creating binary 1 threshold images for safer usage
    _, working_image = cv2.threshold(working_image, 254, 255, cv2.THRESH_BINARY)

    # finding marks contours in the thresh images
    if find_contours:
        contours, _ = cv2.findContours(working_image, 1, cv2.CHAIN_APPROX_NONE)
    else:
        contours = None

    return contours, working_image

def find_boxes(contours, addl_attr={}):
    all_boxes = []
    for cnt in contours:
        cx, cy, cw, ch = cv2.boundingRect(cnt)
        ca = float(cv2.contourArea(cnt))
        box = {'x': cx, 'y': cy, 'w': cw, 'h': ch, 'a': ca}
        if addl_attr:
            box.update(addl_attr)
        all_boxes.append(box)

    return all_boxes

def select_boxes(box_size_list, all_boxes):
    """ given list of boxes, choose boxes that meet size criteria
        size criteria provides one or more dimensions that qualify
        box_size_list is list of dict with 'w_min', 'w_max', 'h_min', 'h_max'
        common calling scenario:
        all_contours, working_image = extract_contours_from_region(image, region, kernels={'blk'=(3,3),'wht'=(3,3)})
        find_boxes(all_contours)
        select_boxes(box_size_list, boxes)
    """
    selected_boxes = []
    for box in all_boxes:
        for box_size in box_size_list:
            if (    (box_size['h_min'] <= box['h'] <= box_size['h_max']) and
                    (box_size['w_min'] <= box['w'] <= box_size['w_max']) and
                    (not bool(box_size.get('area_min')) or (box_size['area_min'] < box['h'] * box['w'])) and
                    True # (not bool(box.get('a', 0)) or (float(box['a'] / (box['w'] * box['h']))) > 0.9)
                ):
                selected_boxes.append(box)
    return selected_boxes

def filter_boxes_by_region(region, all_boxes, tol=10):
    """ given list of boxes, choose boxes that lie within the region specified.
        If not extents are given, do not constrain in that direction.
    """
    if not region:
        return all_boxes    
    
    selected_boxes = []
    for box in all_boxes:
        if 'x' in region:
            if box['x'] + tol < region['x']: continue
            if 'w' in region and (box['x'] + box['w']) > (region['x'] + region['w'] + tol): continue

        if 'y' in region:
            if box['y'] + tol < region['y']: continue
            if 'h' in region and (box['y'] + box['h']) > (region['y'] + region['h'] + tol): continue

        selected_boxes.append(box)

    return selected_boxes

def remove_outer_boxes(boxes):
    initial_len = len(boxes)

    oidx = initial_len - 1
    while oidx > -1:
        # work through in reverse order so we can delete elements
        # the box in question at idx may be the outer box.
        obox = boxes[oidx]
        ox = obox['x']; oy = obox['y']; ow = obox['w']; oh = obox['h']

        # see if box at idx surrounds any of other boxes
        for iidx in range(oidx):
            ibox = boxes[iidx]
            ix = ibox['x']; iy = ibox['y']; iw = ibox['w']; ih = ibox['h']

            if ox <= ix and ox + ow >= ix + iw and oy <= iy and oy + oh >= iy + ih:
                boxes.pop(oidx)
                break
        oidx -= 1


    dif_len = initial_len - len(boxes)
    if (dif_len):
        utils.sts(f"removed {dif_len} boxes")

    return boxes

#assert (remove_outer_boxes([{'x':0,'y':0,'w':5,'h':5},{'x':0,'y':0,'w':10,'h':15},{'x':20,'y':20,'w':10,'h':10}])
#        == [{'x':0,'y':0,'w':5,'h':5},{'x':20,'y':20,'w':10,'h':10}]), "remove_outer_boxes() not working"

def find_features(image, region, kernels, sizes, diagnostic_mode):
    """ given image, inspect region and attempt to find rectangular features
        returns list of boxes, image of region
    """
    
    if not args.argsdict.get('use_template_matching', False):
        # use traditional contour recognition by OpenCV.
        feature_contours, feature_image = \
            extract_contours_from_region(image, region=region, kernels=kernels, diagnostic_mode=diagnostic_mode, find_contours=True)

        feature_boxes = find_boxes(feature_contours)

        feature_blocks = select_boxes(sizes, feature_boxes)
        
    else:
        # this performs all image enhancement and creates a working image, but does not search for contours
        _, feature_image = \
            extract_contours_from_region(image, region, kernels=kernels, diagnostic_mode=diagnostic_mode, find_contours=False)
            
        # All the 6 methods for comparison in a list
        methods = {'TM_CCOEFF':             cv2.TM_CCOEFF, 
                   'TM_CCOEFF_NORMED':      cv2.TM_CCOEFF_NORMED, 
                   'TM_CCORR':              cv2.TM_CCORR,
                   'TM_CCORR_NORMED':       cv2.TM_CCORR_NORMED, 
                   'TM_SQDIFF':             cv2.TM_SQDIFF, 
                   'TM_SQDIFF_NORMED':      cv2.TM_SQDIFF_NORMED,
                  }
                  
        method_str = args.argsdict.get('template_matching_method', 'TM_CCOEFF_NORMED')
        method = methods.get(method_str, cv2.TM_CCOEFF_NORMED)
        template_matching_thres = float(args.argsdict.get('template_matching_thres', '0.8'))
        
        feature_blocks = []
        for size_spec in sizes:
            # black template is template of all zeroes.
            template = np.zeros(size_spec['h_nom'], size_spec['w_nom'], dtype="int8")

            res = cv2.matchTemplate(feature_image, template, method)

            if method not in [cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED]:
                loc = np.where( res <= 1 - template_matching_thres)
            else:
                loc = np.where( res >= template_matching_thres)

            for pt in zip(*loc[::-1]):
                feature_blocks.append({'x': pt[0],  'y': pt[1], 'w':size_spec['w_nom'], 'h':size_spec['h_nom']})

    return feature_blocks, feature_image


def unstretch_top_edge(image, y_left, y_right, diagnostic_mode):
    """ given detected slant in the image, unstretch the top of the image to correct the slant.
        y_left, y_right - offsets in the image to be corrected to 0
        This function modifies image directly.
    """

    top_diff = y_left - y_right     # positive = right edge down, negative, left edge down.

    if abs(top_diff) > 2:

        height, width = image.shape

        if diagnostic_mode:
            utils.sts(f"unstretch_top_edge: slant dectected: y_left:{y_left} y_right:{y_right} top_diff={top_diff}")

        # declaring set of destination points for perspective transform
        source_points = np.array([
            # x,        y
            [0,         y_left],        # top left corner
            [width - 1, y_right],       # top right corner
            [width - 1, height - 1],    # bottom right corner
            [0,         height - 1]],   # botto left corner
            dtype="float32")

        # declaring set of source points for perspective transform
        destination_points = np.array([
            # x,        y
            [0,         0],
            [width - 1, 0],
            [width - 1, height - 1],
            [0,         height - 1]],
            dtype="float32")

        # declaring transformation matrix
        M = cv2.getPerspectiveTransform(source_points, destination_points)

        # returning transformed image
        image = cv2.warpPerspective(image, M, (width, height))


def dominion_get_timing_marks(image, ballot_id, page):
    """ this function analyzes an image and provides the timing marks
        dominion ballots that have already been split into separate pages and aligned.
        returns left_vertical_marks, right_vertical_marks, top_marks
    """
    error_flag = False
    diagnostic_mode = bool(ballot_id in args.argsdict.get('diagnose_ballotid', []))
    #if ballot_id == '00409_00000_007912':
    #    import pdb; pdb.set_trace()

    height, width = image.shape

    mark_tol = 25                           # plus and minus dimension
    kernels = {'blk':(3,3), 'wht':(15,15)}  # remove imperfections from black areas "blk" and clear out white areas "wht"

    top_marks_h = 60
    top_marks_w = 22
    top_marks_num = [32, 22]                # Dominion has two variants, one with fewer horizontal timing marks.
    top_left_align_mark_w = 110
    top_right_align_mark_w = 90

    # Leon County has text very close to the top timing marks and extends close to the right timing mark.
    # this will sometimes corrupt the right timing mark. Therefore, we cut the top rigth timing mark in half in the
    # region specification and in sizes as well
    effective_tr_align_mark_w = int(top_right_align_mark_w / 2)

    top_marks_bottom_vgap = 20      # gap below the top timing marks region
    top_tilt_adder = 50
    top_align_region_h  = top_marks_h + int(top_marks_bottom_vgap/2) + top_tilt_adder
    top_marks_region_h  = top_marks_h + int(top_marks_bottom_vgap/2)

    v_marks_h = 22
    v_marks_w = 26
    right_v_marks_w = 30
    right_v_marks_w_tol = 17
    v_marks_w_tol = 15
    v_marks_num = 59
    v_region_w = 60
    v_marks_area_min = 300

    #bottom_marks_region_h = 170


    align_region = {'tl': {'x':0, 'y':0, 'w':top_left_align_mark_w, 'h':top_align_region_h},
                    'tr': {'x':width - effective_tr_align_mark_w, 'y':0, 'w':effective_tr_align_mark_w, 'h':top_align_region_h}
                   }

    align_sizes = {
        'tl': [
            {
                'w_nom': top_left_align_mark_w,
                'h_nom': top_marks_h,
                'w_min': top_left_align_mark_w - mark_tol,
                'w_max': top_left_align_mark_w + mark_tol,
                'h_min': top_marks_h - mark_tol,
                'h_max': top_marks_h + mark_tol},
            ],
        'tr': [
            {
                'w_nom': top_right_align_mark_w,
                'h_nom': top_marks_h,
                'w_min': effective_tr_align_mark_w - mark_tol,
                'w_max': effective_tr_align_mark_w + mark_tol,
                'h_min': top_marks_h - mark_tol,
                'h_max': top_marks_h + mark_tol},
            ],
        }

    top_marks_region = {'x':0, 'y':0, 'w':width, 'h':top_marks_region_h}
    top_marks_box_sizes = [
            {
                'w_nom': top_marks_w,
                'h_nom': top_marks_h,
                'w_min': top_marks_w - mark_tol,
                'w_max': top_marks_w + mark_tol,
                'h_min': top_marks_h - mark_tol,
                'h_max': top_marks_h + mark_tol},
        ]

    edge_region = {
        'lft': {
            'x': 0,
            'y': top_marks_region_h,
            'w': v_region_w,
            'h': (height - top_marks_region_h) },
        'rgt': {
            'x':(width - v_region_w),
            'y':top_marks_region_h,
            'w':v_region_w,
            'h':(height-top_marks_region_h) },
        }

    edge_sizes = {
        'lft': [
            {
                'w_nom': v_marks_w,
                'h_nom': v_marks_h,
                'w_min': v_marks_w - v_marks_w_tol,
                'w_max': v_marks_w + v_marks_w_tol,
                'h_min': v_marks_h - mark_tol,
                'h_max': v_marks_h + mark_tol,
                'area_min': v_marks_area_min},
            ],
        'rgt': [
            {
                'w_nom': right_v_marks_w,
                'h_nom': v_marks_h,
                'w_min': right_v_marks_w - right_v_marks_w_tol,
                'w_max': right_v_marks_w + right_v_marks_w_tol,
                'h_min': v_marks_h - mark_tol,
                'h_max': v_marks_h + mark_tol,
                'area_min': v_marks_area_min},
            ],
        }

    # extract the top two alignment marks.
    # we do this in two operations because there is a lot of crud in the middle

    # align_boxes = {}
    # align_contours = {}
    align_images = {}
    align_blocks = {}

    error_flag = False
    for corner in ['tl', 'tr']:
        # align_contours[corner], align_images[corner] = \
            # extract_contours_from_region(image, region=align_region[corner], kernels=kernels, diagnostic_mode=diagnostic_mode)
        # align_boxes[corner] = find_boxes(align_contours[corner])
        # align_blocks[corner] = select_boxes(align_sizes[corner], align_boxes[corner])
        align_blocks[corner], align_images[corner] = \
            find_features(image, region=align_region[corner], kernels=kernels, sizes=align_sizes[corner], diagnostic_mode=diagnostic_mode)

        if len(align_blocks[corner]) != 1 :
            # if this is page 2, frequently, there are no timing marks on this page.
            # can't find all top alignment marks or top timing marks.
            error_flag = True
            if not page:
                utils.exception_report(
                    f"dominion_get_timing_marks failed: \n"
                    f"    found {len(align_blocks[corner])} {corner} align_blocks, expected 1.\n" \
                    f"Saving dominion_get_timing_marks {corner}_align_images for {ballot_id}_p{page}\n")
                DB.save_alignment_image(ballot_id=ballot_id, image=align_images[corner], type=f"dominion_get_timing_marks_top_right_align_image_p{page}")

    if error_flag:
        return None, None, None

    #---------------
    # if needed, adjust for any excessive tilt of the top timing marks.
    #  sorting top alignment marks by the bottom edge. (there are only two so we just swap them if they are out of order)


    # calculate the top edge based on the bottom edge of the alignment blocks minus the size, but not less than zero
    y_offset = {}
    for corner in ['tl', 'tr']:
        y_offset[corner] = max(align_blocks[corner][0]['y'] + align_blocks[corner][0]['h'] - top_marks_h, 0)

    unstretch_top_edge(image, y_offset['tl'], y_offset['tr'], diagnostic_mode)

    #---------------
    # with top bar now aligned, get the top marks.
    # top_bar_contours, top_bar_image = extract_contours_from_region(image, region=top_marks_region, kernels=kernels, diagnostic_mode=diagnostic_mode)
    # top_marks = select_boxes(top_marks_box_sizes, find_boxes(top_bar_contours))
    top_marks, top_bar_image = find_features(image, region=top_marks_region, kernels=kernels, sizes=top_marks_box_sizes, diagnostic_mode=diagnostic_mode)

    if not bool(top_marks_num.count(len(top_marks))):       # check to see if the len(top_marks) is in the list top_marks_num.
        # top_marks has wrong number of marks.
        err_str, gap_list = analyze_failing_timing_marks(top_marks, 'x')
        utils.exception_report(
            f"{len(top_marks)} of 32 or 22 top marks: {ballot_id}\n" + err_str + \
            f"Saving dominion_get_timing_marks_top_bar_image2_{ballot_id}_p{page}\n")
        DB.save_alignment_image(ballot_id=ballot_id, image=top_bar_image, type=f"dominion_get_timing_marks_top_bar_image2_p{page}")
        return None, None, None

    top_marks = sorted(top_marks, key=lambda mark: mark['x'])
    if diagnostic_mode:
        utils.sts(f"top_marks: {top_marks}")

    #---------------
    # get left and right vertical marks.

    # bar_contours = {}
    bar_images = {}
    bar_marks = {}
    # bar_boxes = {}

    for edge in ['lft', 'rgt']:
        # bar_contours[edge], bar_images[edge] = extract_contours_from_region(image, region=edge_region[edge], kernels=kernels, diagnostic_mode=diagnostic_mode)
        # bar_boxes[edge] = find_boxes(bar_contours[edge])
        # bar_marks[edge] = select_boxes(edge_sizes[edge], bar_boxes[edge])
        bar_marks[edge], bar_images[edge] = find_features(image, region=edge_region[edge], kernels=kernels, sizes=edge_sizes[edge], diagnostic_mode=diagnostic_mode)

        if not bar_marks[edge]:
            utils.exception_report(
                f"EXCEPTION: Timing marks empty {edge} expected {v_marks_num} " \
                f"on {ballot_id} page {page}\n")
            error_flag = True

        elif len(bar_marks[edge]) != v_marks_num:
            err_str, gap_list   = analyze_failing_timing_marks(bar_marks[edge], 'y')

            # here we may want to reinsert timing marks in gaps.

            utils.exception_report(
                f"EXCEPTION: Number of marks on {edge} ({len(bar_marks[edge])}) expected {v_marks_num} " \
                f"on {ballot_id} page {page}\n" + err_str +f"{gap_list}")
            error_flag = True

    if diagnostic_mode or error_flag:
        utils.sts(f"Saving dominion_get_timing_marks left & right_bar_image_{ballot_id}_p{page}", 3)
        for edge in ['lft', 'rgt']:
            DB.save_alignment_image(ballot_id=ballot_id, image=bar_images[edge],
                type=f"dominion_get_timing_marks_{edge}_bar_image_p{page}")

            utils.sts(f"dominion_get_timing_marks {edge}_marks: {bar_marks[edge]}\n" + \
                vertical_mark_stats_str(bar_marks[edge], edge), 3)
        if error_flag:
            return None, None, None

    bar_marks['lft'] = sorted(bar_marks['lft'], key=lambda mark: mark['y'])
    bar_marks['rgt'] = sorted(bar_marks['rgt'], key=lambda mark: mark['y'])

    return bar_marks['lft'], bar_marks['rgt'], top_marks


"""
    for i in range(2):
        # we may have to reprocess the top section if it must be realigned.

        alignment_marks_region =

        extract_contours_from_region(image, x, y, w, h, w_min, w_max, h_min, h_max, min_feature, desc_str):

        # creating several copies of image for marks finding, and non-destructive image usage
        top_marks_shapes = image.copy()

        # clearing up top vertical shapes image
        tilt_margin = 1     # tilt should be rectified in second pass
        if i == 0:
            tilt_margin = 50
        top_marks_shapes[top_marks_region_h+tilt_margin:, :] = 255    # clear out the rest of the page.
        #top_marks_shapes[:, 40:width - 40] = 255           # clear the middle of the marks. (No! we need the timing marks)

        if diagnostic_mode:
            utils.sts(   "Starting dominion_get_timing_marks\n" \
                        f"Saving dominion_get_timing_marks top_marks_shapes0_{ballot_id}_p{page}_pass({i}", 3)
            DB.save_alignment_image(ballot_id=ballot_id, image=top_marks_shapes, type=f"dominion_get_timing_marks_top_marks_shapes0_p{page}_pass({i}")

        # declaring kernel for erosion and dilation
        kernel_line = np.ones((5, 5), np.uint8)

        # eroding and dilating marks images to standardise the marks and delete imperfections
        top_marks_shapes = cv2.erode(top_marks_shapes, kernel_line, iterations=1)
        top_marks_shapes = cv2.dilate(top_marks_shapes, kernel_line, iterations=1)

        # declaring kernel for erosion and dilation
        kernel_line = np.ones((50, 1), np.uint8)

        # eroding and dilating marks images to standardise the marks and delete imperfections
        top_marks_shapes = cv2.dilate(top_marks_shapes, kernel_line, iterations=1)
        top_marks_shapes = cv2.erode(top_marks_shapes, kernel_line, iterations=1)

        if diagnostic_mode:
            utils.sts(f"Saving dominion_get_timing_marks_top_marks_shapes1_{ballot_id}_p{page}_pass({i}", 3)
            DB.save_alignment_image(ballot_id=ballot_id, image=top_marks_shapes, type=f"dominion_get_timing_marks_top_marks_shapes1_p{page}_pass({i}")

        # clearing borderlines of marks images to allow proper mark contours search
        # this is because the method used searches for white contours.
        top_marks_shapes[:, :1] = 255                       # Clear first left column
        top_marks_shapes[:, width - 1:] = 255               # Clear last right column
        top_marks_shapes[:1, :] = 255                       # Clear first top row

        # the following artificially clears areas near the main timing marks.
        # These seem wrong, at least in terms of preserving the timing marks.
        # We can discriminate between the alignment blocks and timing marks by size.
        #top_marks_shapes[:, 10:15] = 255
        #top_marks_shapes[:, width - 15:width - 10] = 255
        #top_marks_shapes[:, 20:25] = 255
        #top_marks_shapes[:, width - 25:width - 20] = 255
        #top_marks_shapes[:, 30:35] = 255
        #top_marks_shapes[:, width - 35:width - 30] = 255

        # creating binary 1 threshold images for safer usage
        _, top_marks_shapes = cv2.threshold(top_marks_shapes, 254, 255, cv2.THRESH_BINARY)

        if diagnostic_mode:
            utils.sts(f"Saving dominion_get_timing_marks_top_marks_shapes2_{ballot_id}_p{page}_pass({i}\n", 3)
            DB.save_alignment_image(ballot_id=ballot_id, image=top_marks_shapes, type=f"dominion_get_timing_marks_top_marks_shapes2_p{page}_pass({i}")

        # finding marks contours in the thresh images
        top_marks_contours, _ = cv2.findContours(top_marks_shapes, 1, cv2.CHAIN_APPROX_NONE)

        #top_marks_shapes = list(reversed(top_marks_shapes))[1:]        # Ray says : I don't understand this as they are sorted later.

        if i == 0:
            # this section un-tilts a tilted top alignment region
            # first pass only
            # locate top alignment marks.
            for cnt in top_marks_contours:
                x, y, w, h = cv2.boundingRect(cnt)

                if ((top_left_align_mark_w - mark_tol <= w <= top_left_align_mark_w + mark_tol) or \
                    (top_right_align_mark_w - mark_tol <= w <= top_right_align_mark_w + mark_tol)) and \
                    (top_marks_h - mark_tol <= h <= top_marks_h + mark_tol):

                    top_alignment_blocks.append({'x': x, 'y': y, 'w': w, 'h': h, 'bottom': y + h})

            if len(top_alignment_blocks) != 2:
                # can't find top alignment marks or top timing marks.
                utils.exception_report(
                    f"dominion_get_timing_marks failed: found {len(top_alignment_blocks)} of 2 alignment marks\n" \
                    f"Saving dominion_get_timing_marks_top_marks_shapes2_{ballot_id}_p{page}\n"
                DB.save_alignment_image(ballot_id=ballot_id, image=top_marks_shapes, type=f"dominion_get_timing_marks_top_marks_shapes2_p{page}")
                return None, None, None

            # sorting top alignment marks by the bottom edge. (there are only two so we just swap them if they are out of order)
            if top_alignment_blocks[0]['bottom'] > top_alignment_blocks[1]['bottom']:
                top_alignment_blocks[0], top_alignment_blocks[1] = top_alignment_blocks[1], top_alignment_blocks[0]
            #top_alignment_blocks = sorted(top_alignment_blocks, key=lambda top_alignment_block: top_alignment_block['height'])
            top_diff = abs(top_alignment_blocks[0]['bottom'] - top_alignment_blocks[1]['bottom'])

            if diagnostic_mode:
                utils.sts(f"top_alignment_blocks: {top_alignment_blocks}\ntop_marks: {top_marks}\ntop_diff={top_diff}")

            if top_diff > 2:
                if top_alignment_blocks[0]['x'] < top_alignment_blocks[1]['x']:

                    # declaring set of destination points for perspective transform
                    source_points = np.array([
                        [0, 0],
                        [width - 1, top_diff + 1],
                        [width - 1, height - 1],
                        [0, height - 1]], dtype="float32")
                else:

                    # declaring set of destination points for perspective transform
                    source_points = np.array([
                        [0, top_diff + 1],
                        [width - 1, 0],
                        [width - 1, height - 1],
                        [0, height - 1]], dtype="float32")

                # declaring set of source points for perspective transform
                destination_points = np.array([
                    [0, 0],
                    [width - 1, 0],
                    [width - 1, height - 1],
                    [0, height - 1]], dtype="float32")

                # declaring transformation matrix
                M = cv2.getPerspectiveTransform(source_points, destination_points)

                # returning transformed image
                image = cv2.warpPerspective(image, M, (width, height))

                if diagnostic_mode:
                    utils.sts(f"Top Marks: {top_marks}\ntop_diff={top_diff}\n" \
                        f"source_points: {source_points}\ndestination_points: {destination_points}\n" \
                        f"transforation Matrix M {M}\nSaving Transformed Image", 3)
                    DB.save_alignment_image(ballot_id=ballot_id, image=image, type=f"dominion_get_timing_marks_transformed_image_p{page}")

                # image has been modified based on the slant of the top alignment marks.
                # to straighten up the top
                # now reprocess the image (loop)
            else:
                # first pass but no need to straighten up any tilt.
                top_marks_shapes[top_marks_region_h:, :] = 255    # clear out the additional margin

                # regenerate the contours with cleared area left out.
                top_marks_contours, _ = cv2.findContours(top_marks_shapes, 1, cv2.CHAIN_APPROX_NONE)
                break

    # at this point, the top of the page was either already close enough, or has been straightened up.

    # filter out just the top_marks, the top timing marks.
    for cnt in top_marks_contours:
        x, y, w, h = cv2.boundingRect(cnt)

        if (top_marks_w - mark_tol < w < top_marks_w + mark_tol) and \
            (top_marks_h - mark_tol < h < top_marks_h + mark_tol):

            top_marks.append({'x': x, 'y': y, 'w': w, 'h': h})

    if len(top_marks) != top_marks_num:
        # top_marks has wrong number of marks.
        err_str, gap_list = analyze_failing_timing_marks(top_marks, 'x')
        utils.exception_report(
            f"{len(top_marks)} of 32 top marks: {ballot_id}\n" + "\n" + err_str)
            f"Saving dominion_get_timing_marks_top_marks_shapes3_{ballot_id}_p{page}\n"
            DB.save_alignment_image(ballot_id=ballot_id, image=top_marks_shapes, type=f"dominion_get_timing_marks_top_marks_shapes3_p{page}")
        return None, None, None

    # sorting top timing marks by y position
    top_marks = sorted(top_marks, key=lambda mark: mark['x'])

    if diagnostic_mode:
        utils.sts(f"top_marks: {top_marks}")

    # creating several copies of image for marks finding. and non-destructive image usage
    left_vertical_marks_shapes = image.copy()
    # clearing up left vertical shapes image
    left_vertical_marks_shapes[:top_marks_region_h, :] = 255
    left_vertical_marks_shapes[height - bottom_marks_region_h:, :] = 255
    left_vertical_marks_shapes[:, 60:] = 255

    # declaring kernel for erosion and dilation
    kernel_line = np.ones((15, 15), np.uint8)

    # eroding and dilating marks images to standardise the marks and delete imperfections
    left_vertical_marks_shapes = cv2.dilate(left_vertical_marks_shapes, kernel_line, iterations=1)
    left_vertical_marks_shapes = cv2.erode(left_vertical_marks_shapes, kernel_line, iterations=1)

    # clearing borderlines of marks images to allow propper mark contours search
    left_vertical_marks_shapes[:, :1] = 255

    # creating binary 1 threshold images for safer usage
    _, left_vertical_marks_shapes = cv2.threshold(left_vertical_marks_shapes, 254, 255, cv2.THRESH_BINARY)

    # finding marks contours in the thresh images
    left_vertical_marks_contours, _ = cv2.findContours(left_vertical_marks_shapes, 1, cv2.CHAIN_APPROX_NONE)

    for cnt in left_vertical_marks_contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if ((v_marks_h - mark_tol) <= h <= (v_marks_h + mark_tol + 5)) and \
           ((v_marks_w - v_marks_w_tol) <= w <= (v_marks_w + v_marks_w_tol + 5)):
            left_vertical_marks.append({'x': x, 'y': y, 'w': w, 'h': h})
        else:
            diag_str += f"left_vertical_marks: Omitted: x:{x} y:{y} w:{w} h:{h}\n"



    right_vertical_marks_shapes = image.copy()
    # clearing up right vertical shapes image
    right_vertical_marks_shapes[:top_marks_region_h, :] = 255
    right_vertical_marks_shapes[height - bottom_marks_region_h:, :] = 255
    right_vertical_marks_shapes[:, :width - 60] = 255

    # declaring kernel for erosion and dilation
    kernel_line = np.ones((15, 15), np.uint8)

    # eroding and dilating marks images to standardise the marks and delete imperfections
    right_vertical_marks_shapes = cv2.dilate(right_vertical_marks_shapes, kernel_line, iterations=1)
    right_vertical_marks_shapes = cv2.erode(right_vertical_marks_shapes, kernel_line, iterations=1)

    # clearing borderlines of marks images to allow propper mark contours search
    right_vertical_marks_shapes[:, width - 1:] = 255

    # creating binary 1 threshold images for safer usage
    _, right_vertical_marks_shapes = cv2.threshold(right_vertical_marks_shapes, 254, 255, cv2.THRESH_BINARY)

    # finding marks contours in the thresh images
    right_vertical_marks_contours, _ = cv2.findContours(right_vertical_marks_shapes, 1, cv2.CHAIN_APPROX_NONE)

#    left_vertical_marks_shapes2 = list(reversed(left_vertical_marks_shapes2))[1:]
#    right_vertical_marks_shapes2 = list(reversed(right_vertical_marks_shapes2))[1:]

    # iterating through vertical marks contours
    # filling the left vertical marks list with dictionaries of x, y coordinates and width, height values
    # setting adjustment required boolean to True if mark height is not 22
    #
    # Nominal size of vertical marks after this recognition process for ballot 12031_00000_000988
    #   h: average 26.38, min=25, max=28, median=26
    #   w: average 27.22, min=26, max=30, median=27
    #   T: average 43.74, min=43, max=45, median=44

    # iterating through vertical marks contours
    # filling the left vertical marks list with dictionaries of x, y coordinates and width, height values
    # setting adjustment required boolean to True if mark height is not 22
    for cnt in right_vertical_marks_contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if ((v_marks_h - mark_tol) <= h <= (v_marks_h + mark_tol + 5)) and \
           ((right_v_marks_w - right_v_marks_w_tol) <= w <= (right_v_marks_w + right_v_marks_w_tol + 5)):
            right_vertical_marks.append({'x': x, 'y': y, 'w': w, 'h': h})
        else:
            diag_str += f"right_vertical_marks: Omitted: x:{x} y:{y} w:{w} h:{h}\n"

    if (len(left_vertical_marks) != v_marks_num) or (len(right_vertical_marks) != v_marks_num):
        left_err_str, left_gap_list   = analyze_failing_timing_marks(left_vertical_marks, 'y')
        right_err_str, right_gap_list = analyze_failing_timing_marks(right_vertical_marks, 'y')
        utils.exception_report(
            f"EXCEPTION: Number of marks on left ({len(left_vertical_marks)}) and " \
            f"right ({len(right_vertical_marks)}) sides not equal {ballot_id} page {page}\n" + \
            diag_str + "\nleft: " + left_err_str + "\nright: " + right_err_str)
        error_flag = True

    if diagnostic_mode or error_flag:
        utils.sts(f"Saving dominion_get_timing_marks left & right_vertical_marks_shapes0_{ballot_id}_p{page}", 3)
        DB.save_alignment_image(ballot_id=ballot_id, image=left_vertical_marks_shapes, type=f"dominion_get_timing_marks_left_vertical_marks_shapes0_p{page}")
        DB.save_alignment_image(ballot_id=ballot_id, image=right_vertical_marks_shapes, type=f"dominion_get_timing_marks_right_vertical_marks_shapes0_p{page}")

        utils.sts(f"Saving dominion_get_timing_marks left & right_vertical_marks_shapes1_{ballot_id}_p{page}", 3)
        DB.save_alignment_image(ballot_id=ballot_id, image=left_vertical_marks_shapes1, type=f"dominion_get_timing_marks_left_vertical_marks_shapes1_p{page}")
        DB.save_alignment_image(ballot_id=ballot_id, image=right_vertical_marks_shapes1, type=f"dominion_get_timing_marks_right_vertical_marks_shapes1_p{page}")

        utils.sts(f"dominion_get_timing_marks left_vertical_marks: {left_vertical_marks}\n" \
            f"dominion_get_timing_marks right_vertical_marks: {right_vertical_marks}\n" + \
            vertical_mark_stats_str(left_vertical_marks, 'left_vertical_marks') + \
            vertical_mark_stats_str(right_vertical_marks, 'right_vertical_marks'), 3)
        if error_flag:
            return None, None, None

    return left_vertical_marks, right_vertical_marks, top_marks
"""

def stretch_fix_ballots(argsdict, ballots, std_ballot_num):
    """
    Normalize ballots to std_timing marks.
    ballots: list of ballot instances, each with images loaded, split, aligned, and std_timing_marks generated.
    std_timing_marks: list of dict for each page providing timing information in same shape as ballot.ballotdict['timing_marks'].
    Modifies images within the ballot instance.

    Algorithm
    1. iterate through ballots
    2. check if ballot deviates from timing_marks of std_ballot sufficiently to warrant fixing.
    3. call appropriate generic stretch fix function
    """
    if not argsdict.get('use_stretch_fix'):
        return
    
    vendor = argsdict.get('vendor', 'ES&S')
    #if not vendor in ['Dominion']: return       # only Dominion supported at this time.

    std_timing_marks = ballots[std_ballot_num].ballotdict['timing_marks']

    for ballot_idx, ballot in enumerate(ballots):

        if ballot_idx == std_ballot_num:
            # by definition, we need not unstretch the designated standard ballot
            continue
        for page_idx, image in enumerate(ballot.ballotimgdict['images']):
            dominion_stretch_fix(ballot, std_timing_marks, page_idx, vendor=vendor)


def is_image_stretched(ballot_timing_marks, std_timing_marks, page_idx):
    return True

    tolerances = [2, 2]  # x, y

    stretch_metrics = get_stretch_metrics(ballot_timing_marks, std_timing_marks, page_idx)

    for idx in range(2):
        if stretch_metrics[idx] > tolerances[idx]:
            return True
    return False

def get_stretch_metrics(ballot_timing_marks, std_timing_marks, page_idx) -> list:
    """ Compare timing marks are within tolerance
        This compares only vertical timing marks.
        and only x,y coordinates of those marks to
        avoid irrelevant variations in width and height of timing marks.
        Returns both maximium deviations and total deviations of x,y coordinate of vertical marks.

    """
    if (ballot_timing_marks is None or
        std_timing_marks is None or
        not ballot_timing_marks[page_idx] or
        not ballot_timing_marks[page_idx]['left_vertical_marks']):
        return None

    stretch_metrics = [0, 0, 0, 0] # max x, max y, tot x, tot y

    num = len(ballot_timing_marks[0]['left_vertical_marks'])
    numR = len(ballot_timing_marks[0]['right_vertical_marks'])

    if not num == numR:
        # both sides should have the same number of timing marks, otherwise, return None as error alert
        return None

    if not std_timing_marks[page_idx] == ballot_timing_marks[page_idx]:

        for side_idx, side_key in enumerate(['left_vertical_marks', 'right_vertical_marks']):
            for coord in ['x', 'y']:
                for x in ballot_timing_marks[page_idx][side_key]:
                    stretch_metrics[side_idx]   = max([abs(ballot_timing_marks[page_idx][side_key][idx][coord] - std_timing_marks[page_idx][side_key][idx][coord])
                                                        for idx in range(num)])
                    stretch_metrics[side_idx+2] = sum([abs(ballot_timing_marks[page_idx][side_key][idx][coord] - std_timing_marks[page_idx][side_key][idx][coord])
                                                        for idx in range(num)])

    return stretch_metrics

def gen_average_timing_marks(ballots) -> list:
    """ average the timing marks across all ballots in the set.
    """
    avg_marks = [{'left_vertical_marks':[], 'right_vertical_marks':[]}, \
                 {'left_vertical_marks':[], 'right_vertical_marks':[]}]

    num = len(ballots)
    if not num:
        return None
    try:
        num_marks = len(ballots[0].ballotdict['timing_marks'][0]['left_vertical_marks'])
    except IndexError:
        import pdb; pdb.set_trace()

    for page_idx in range(2):
        if page_idx and not ballots[0].ballotdict['timing_marks'][1]:
            # back of the ballot might be blank and this is not an error.
            break
        for vert_mark_idx in range(num_marks):
            for left_right in ['left_vertical_marks', 'right_vertical_marks']:
                t_avg_marks = {}
                for coord in ['x', 'y', 'w', 'h']:

                    timing_marks = []
                    for idx, b in enumerate(ballots):
                        try:
                            markval = b.ballotdict['timing_marks'][page_idx][left_right][vert_mark_idx][coord]
                        except: # (KeyError, IndexError):
                            utils.sts(f"Index Error on ballot idx:{idx} page_idx:{page_idx} {left_right} Mark Idx:{vert_mark_idx} coord:{coord}")
                            return None
                            #import pdb; pdb.set_trace()

                        timing_marks.append(markval)

                    t_avg_marks[coord] = sum(timing_marks)/num

                    #try:
                    #    t_avg_marks[coord] = sum([b.ballotdict['timing_marks'][page_idx][left_right][vert_mark_idx][coord] for b in ballots ])/num
                    #except IndexError:
                    #   import pdb; pdb.set_trace()
                avg_marks[page_idx][left_right].append(t_avg_marks)

        #for top_mark_idx in range(len(left_vertical_marks)):
        #    t_avg_marks = {}
        #    for coord in ['x', 'y', 'w', 'h']:
        #        t_avg_marks[coord] = sum([x[coord] for x in ballots.ballotdict['timing_marks']['top_marks'][top_mark_idx][coord]])/num
        #    avg_marks['top_marks'].append(t_avg_marks)

    return avg_marks

def gen_distortion_metrics(ballots, avg_marks) -> list:
    """ Compare ballots with avg_marks and create a distortion metric for each one.
    """

    distortion_metrics = []
    for ballot in ballots:
        ballot_total = 0
        for page_idx in range(2):
            stretch_metrics = get_stretch_metrics(ballot.ballotdict['timing_marks'], avg_marks, page_idx)
            if stretch_metrics is None:
                continue
            # sum total metrics of all pages
            ballot_total += stretch_metrics[2] + stretch_metrics[3]
        distortion_metrics.append(round(ballot_total, 2))

    return distortion_metrics

def remove_distorted_ballots(ballots, distortion_metrics, max=10) -> int:
    """ review ballots and remove those that exceed a threshold
    """

    distortion_threshold = 1000      # this is the sum of x,y distortions of vertical timing marks.

    num_removed = 0
    for i in range(len(ballots)-1, -1, -1):
        # process ballot list in reverse order so any deleted entries will not upset future iterations.
        if distortion_metrics[i] > distortion_threshold:
            utils.sts(f">>> Removing ballot {ballots[i].ballotdict['ballot_id']} with distortion metric {distortion_metrics[i]} from template", 3)
            del ballots[i]
            num_removed += 1
            if num_removed >= max:
                break

    return num_removed

def choose_unstretched_ballot(ballots) -> int:
    """ consider all the ballots being combined to create a template
        calculate the average value for each timing mark across all ballots.
        note that these values are float.
        choose one ballot which has most average timing marks.
        return index of this ballot in the ballots list.
        all ballots passed should be previously checked that left and right timing marks are equal in number

        NOTE: this may modify the ballots list.
    """

    num = len(ballots)
    if num < 3:
        #only two ballots. Can't use statistics, just pick one.
        return 0

    for i in range(2):
        avg_marks = gen_average_timing_marks(ballots)
        distortion_metrics = gen_distortion_metrics(ballots, avg_marks)
        min_metric = min(distortion_metrics)
        min_ballot_idx = distortion_metrics.index(min_metric)
        min_ballot_id = ballots[min_ballot_idx].ballotdict['ballot_id']

        if i == 0 and num > 40:
            num_removed = remove_distorted_ballots(ballots, distortion_metrics, max=10)

            if num_removed:
                utils.sts(  f"Initial min_metric {min_metric}, ballot:{min_ballot_id}\n" \
                            f"Removed {num_removed} extremely distorted ballots out of {num} ballots.", 3)
                # if we removed any extremely distorted ballots, then the average
                # and best choice might change. So loop if this is the case.
                continue
            break

    utils.sts(  f"choose_unstretched_ballot: Ballot Metrics: {distortion_metrics}\n" \
                f"min_metric={min_metric}; ballot:{min_ballot_id}", 3)

    return min_ballot_idx

def timing_mark_sts(page_timing_marks, kind_str):

    [left_vertical_marks, right_vertical_marks, top_marks] = [page_timing_marks[x] for x in ['left_vertical_marks', 'right_vertical_marks', 'top_marks']]

    utils.sts(f"stretch_fix: timing_marks for {kind_str}:\nleft_vertical_marks:\n{left_vertical_marks}\n" \
        f"right_vertical_marks:\n{right_vertical_marks}\nstats:" + \
        vertical_mark_stats_str(left_vertical_marks, 'left_vertical_marks') + \
        vertical_mark_stats_str(right_vertical_marks, 'right_vertical_marks'), 3)




def dominion_stretch_fix(ballot, std_timing_marks, page, vendor='Dominion'):
    """
    Function which unstretches Dominion images if possible
    :param ballot: instance od a ballot
    :param std_timing_marks: (list) list of the dictionaries cotaining destination timing marks
    :param page: (int) page number
    :param horizontal_offset: (int) value of horizontal stabilisation, based on distance from inner edges of timing marks (0 - disabled)
        If used, this measures the edge based on interior timing mark x value toward the edge. Not applicable to ES&S because those timing marks vary.
    :param second_layer: (bool) boolean value defining if the second layer should be applied
    """

    image = ballot.ballotimgdict['images'][page]
    ballot_id = ballot.ballotdict['ballot_id']
    height, width = image.shape
    image_copy = image.copy()
    canvas = image.copy()
    
    horizontal_offset = 20 if vendor == 'Dominion' else 0
    second_layer = False

    if page and not ballot.ballotdict['timing_marks'][page]:
        utils.sts(f"Aborting stretch fix for page 1, ballot_id:{ballot_id} -- no timing marks. Probably blank.")
        return canvas

    timing_mark_sts(ballot.ballotdict['timing_marks'][page], f"ballot_id:{ballot_id}")
    timing_mark_sts(std_timing_marks[page], 'std_timing_marks')

    [left_vertical_marks, right_vertical_marks, top_marks] = [ballot.ballotdict['timing_marks'][page][x] for x in ['left_vertical_marks', 'right_vertical_marks', 'top_marks']]
    [left_std_vertical_marks, right_std_vertical_marks, top_std_marks] = [std_timing_marks[page][x] for x in ['left_vertical_marks', 'right_vertical_marks', 'top_marks']]

    if not (left_vertical_marks and right_vertical_marks and top_marks and
            left_std_vertical_marks and right_std_vertical_marks and top_std_marks):
            utils.exception_report(f"WARN: timing marks missing from ballot {ballot.ballotdict['ballot_id']}, aborting stretchfix")
            return canvas

    if not (left_vertical_marks and right_vertical_marks and top_marks and
        left_std_vertical_marks and right_std_vertical_marks and top_std_marks):
        utils.exception_report(f"WARN: timing marks missing from ballot {ballot.ballotdict['ballot_id']}, aborting stretchfix")
        return canvas

    canvas[
        min(left_vertical_marks[0]['y'], right_vertical_marks[0]['y'], left_std_vertical_marks[0]['y'], right_std_vertical_marks[0]['y']):
        height - 150,
        :] = 255

    # iterating through range of vertical marks indexes beginning on the second
    for index in range(len(right_vertical_marks))[:-1]:

        if horizontal_offset:
            # declaring bar points of current mark strip right part
            bar_points = np.float32([
                [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - horizontal_offset, left_vertical_marks[index]['y']],
                [right_vertical_marks[index]['x'] + horizontal_offset, right_vertical_marks[index]['y']],
                [left_vertical_marks[index + 1]['x'] + left_vertical_marks[index + 1]['w'] - horizontal_offset, left_vertical_marks[index + 1]['y']]
            ])
        else:
            # declaring bar points of current mark strip right part
            bar_points = np.float32([
                [left_vertical_marks[index]['x'], left_vertical_marks[index]['y']],
                [right_vertical_marks[index]['x'] + right_vertical_marks[index]['w'], right_vertical_marks[index]['y']],
                [left_vertical_marks[index + 1]['x'], left_vertical_marks[index+1]['y']]
            ])

        # declaring final points of current mark strip right part
        final_points = np.float32([
            [0, 0],
            [width, 0],
            [0, abs(left_std_vertical_marks[index]['y']-left_std_vertical_marks[index+1]['y'])]
        ])

        # declaring affine transformation matrix for current mark strip right part
        matrix = cv2.getAffineTransform(bar_points, final_points)

        # declaring warped current mark strip right part
        warped_right_part = cv2.warpAffine(image_copy, matrix, (width, abs(left_std_vertical_marks[index]['y']-left_std_vertical_marks[index+1]['y']))).astype('int8')

        if horizontal_offset:
            # declaring bar points of current mark strip left part
            # based on offset from interior edge of timing mark to edge.
            bar_points = np.float32([
                [right_vertical_marks[index]['x'] + horizontal_offset, right_vertical_marks[index]['y']],
                [left_vertical_marks[index + 1]['x'] + left_vertical_marks[index + 1]['w'] - horizontal_offset, left_vertical_marks[index+1]['y']],
                [right_vertical_marks[index + 1]['x'] + horizontal_offset, left_vertical_marks[index + 1]['y']]
            ])
        else:
            # declaring bar points of current mark strip left part
            # based on exterior edge of timing mark.
            bar_points = np.float32([
                [right_vertical_marks[index]['x'] + right_vertical_marks[index]['w'], right_vertical_marks[index]['y']],
                [left_vertical_marks[index + 1]['x'], left_vertical_marks[index + 1]['y']],
                [right_vertical_marks[index + 1]['x'] + right_vertical_marks[index + 1]['w'], left_vertical_marks[index + 1]['y']]
            ])

        # declaring final points of current mark strip left part
        final_points = np.float32([
            [width, 0],
            [0, abs(left_std_vertical_marks[index]['y']-left_std_vertical_marks[index+1]['y'])],
            [width, abs(left_std_vertical_marks[index]['y']-left_std_vertical_marks[index+1]['y'])],
        ])

        # declaring affine transformation matrix for current mark strip left part
        matrix = cv2.getAffineTransform(bar_points, final_points)

        # declaring warped current mark strip left part
        warped_left_part = cv2.warpAffine(image_copy, matrix, (width, abs(left_std_vertical_marks[index]['y']-left_std_vertical_marks[index+1]['y']))).astype('int8')

        # declaring diagonal mask to join both parts
        mask = np.zeros((abs(left_std_vertical_marks[index]['y']-left_std_vertical_marks[index+1]['y']), width), dtype="int8")
        mask_points = np.array([
            [width, 0],
            [0, abs(left_std_vertical_marks[index]['y']-left_std_vertical_marks[index+1]['y'])-2],
            [width, abs(left_std_vertical_marks[index]['y']-left_std_vertical_marks[index+1]['y'])-2],
        ])
        cv2.fillPoly(mask, [mask_points], (255, 255, 255))

        # masking current mark strip right part
        warped_right_part = cv2.bitwise_or(warped_right_part, mask)

        # reversing the mask
        mask -= 255
        mask *= -1

        # masking current mark strip left part
        warped_left_part = cv2.bitwise_or(warped_left_part, mask)

        # joining current mark strip parts and aplying them to canvas
        canvas[left_std_vertical_marks[index]['y']:left_std_vertical_marks[index+1]['y'], :] = cv2.bitwise_and(
            cv2.bitwise_and(warped_left_part, warped_right_part).astype('int8'),
            canvas[left_std_vertical_marks[index]['y']:left_std_vertical_marks[index + 1]['y'], :].astype('int8')
        )

    if vendor == 'Dominion':
        index = len(right_vertical_marks) - 1
        if horizontal_offset:
            # declaring bar points of current mark strip right part
            bar_points = np.float32([
                [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - horizontal_offset, left_vertical_marks[index]['y']],
                [right_vertical_marks[index]['x'] + horizontal_offset, right_vertical_marks[index]['y']],
                [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - horizontal_offset, left_vertical_marks[index]['y'] + 2 * left_vertical_marks[index]['h']]
            ])
        else:
            # declaring bar points of current mark strip right part
            bar_points = np.float32([
                [left_vertical_marks[index]['x'], left_vertical_marks[index]['y']],
                [right_vertical_marks[index]['x'] + right_vertical_marks[index]['w'], right_vertical_marks[index]['y']],
                [left_vertical_marks[index]['x'], left_vertical_marks[index]['y']+2*left_vertical_marks[index]['h']]
            ])

        # declaring final points of current mark strip right part
        final_points = np.float32([
            [0, 0],
            [width, 0],
            [0, 2*left_std_vertical_marks[index]['h']]
        ])

        # declaring affine transformation matrix for current mark strip right part
        matrix = cv2.getAffineTransform(bar_points, final_points)

        # declaring warped current mark strip right part
        warped_right_part = cv2.warpAffine(image_copy, matrix, (width, 2*left_std_vertical_marks[index]['h'])).astype('int8')

        if horizontal_offset:
            # declaring bar points of current mark strip left part
            bar_points = np.float32([
                [right_vertical_marks[index]['x'] + horizontal_offset, right_vertical_marks[index]['y']],
                [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - horizontal_offset, left_vertical_marks[index]['y'] + 2*left_vertical_marks[index]['h']],
                [right_vertical_marks[index]['x'] + horizontal_offset, left_vertical_marks[index]['y'] + 2*left_vertical_marks[index]['h']]
            ])
        else:
            # declaring bar points of current mark strip left part
            bar_points = np.float32([
                [right_vertical_marks[index]['x'] + right_vertical_marks[index]['w'], right_vertical_marks[index]['y']],
                [left_vertical_marks[index]['x'], left_vertical_marks[index]['y'] + 2*left_vertical_marks[index]['h']],
                [right_vertical_marks[index]['x'] + right_vertical_marks[index]['w'], left_vertical_marks[index]['y'] + 2*left_vertical_marks[index]['h']]
            ])

        # declaring final points of current mark strip left part
        final_points = np.float32([
            [width, 0],
            [0, 2*left_std_vertical_marks[index]['h']],
            [width, 2*left_std_vertical_marks[index]['h']],
        ])

        # declaring affine transformation matrix for current mark strip left part
        matrix = cv2.getAffineTransform(bar_points, final_points)

        # declaring warped current mark strip left part
        warped_left_part = cv2.warpAffine(image_copy, matrix, (width, 2*left_std_vertical_marks[index]['h'])).astype('int8')

        # declaring diagonal mask to join both parts
        mask = np.zeros((2*left_std_vertical_marks[index]['h'], width), dtype="int8")
        mask_points = np.array([
            [width, 0],
            [0, 2*left_std_vertical_marks[index]['h']-2],
            [width, 2*left_std_vertical_marks[index]['h']-2],
        ])
        cv2.fillPoly(mask, [mask_points], (255, 255, 255))

        # masking current mark strip right part
        warped_right_part = cv2.bitwise_or(warped_right_part, mask)

        # reversing the mask
        mask -= 255
        mask *= -1

        # masking current mark strip left part
        warped_left_part = cv2.bitwise_or(warped_left_part, mask)

        # joining current mark strip parts and applying them to canvas
        canvas[left_std_vertical_marks[index]['y']:left_std_vertical_marks[index]['y'] + 2*left_std_vertical_marks[index]['h'], :] = cv2.bitwise_and(
            cv2.bitwise_and(warped_left_part, warped_right_part).astype('int8'),
            canvas[left_std_vertical_marks[index]['y']:left_std_vertical_marks[index]['y'] + 2 * left_std_vertical_marks[index]['h'], :].astype('int8')
            )

        # now dealing with the top

        index = 0
        if horizontal_offset:
            # declaring bar points of current mark strip right part
            bar_points = np.float32([
                [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - horizontal_offset, 0],
                [right_vertical_marks[index]['x'] + horizontal_offset, 0],
                [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - horizontal_offset, left_vertical_marks[index]['y']]
            ])
        else:
            # declaring bar points of current mark strip right part
            bar_points = np.float32([
                [left_vertical_marks[index]['x'], 0],
                [right_vertical_marks[index]['x'] + right_vertical_marks[index]['w'], 0],
                [left_vertical_marks[index]['x'], left_vertical_marks[index]['y']]
            ])

        # declaring final points of current mark strip right part
        final_points = np.float32([
            [0, 0],
            [width, 0],
            [0, left_vertical_marks[index]['y']]
        ])

        # declaring affine transformation matrix for current mark strip right part
        matrix = cv2.getAffineTransform(bar_points, final_points)

        # declaring warped current mark strip right part
        warped_right_part = cv2.warpAffine(image_copy, matrix, (width, left_vertical_marks[index]['y'])).astype('int8')

        if horizontal_offset:
            # declaring bar points of current mark strip left part
            bar_points = np.float32([
                [right_vertical_marks[index]['x'] + horizontal_offset, 0],
                [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - horizontal_offset, left_vertical_marks[index]['y']],
                [right_vertical_marks[index]['x'] + horizontal_offset, left_vertical_marks[index]['y']]
            ])
        else:
            # declaring bar points of current mark strip left part
            bar_points = np.float32([
                [right_vertical_marks[index]['x'] + right_vertical_marks[index]['w'], 0],
                [left_vertical_marks[index]['x'], left_vertical_marks[index]['y']],
                [right_vertical_marks[index]['x'] + right_vertical_marks[index]['w'], left_vertical_marks[index]['y']]
            ])

        # declaring final points of current mark strip left part
        final_points = np.float32([
            [width, 0],
            [0, left_vertical_marks[index]['y']],
            [width, left_vertical_marks[index]['y']],
        ])

        # declaring affine transformation matrix for current mark strip left part
        matrix = cv2.getAffineTransform(bar_points, final_points)

        # declaring warped current mark strip left part
        warped_left_part = cv2.warpAffine(image_copy, matrix, (width, left_vertical_marks[index]['y'])).astype('int8')

        # declaring diagonal mask to join both parts
        mask = np.zeros((left_vertical_marks[index]['y'], width), dtype="int8")
        mask_points = np.array([
            [width, 0],
            [0, left_vertical_marks[index]['y'] - 2],
            [width, left_vertical_marks[index]['y'] - 2],
        ])
        cv2.fillPoly(mask, [mask_points], (255, 255, 255))

        # masking current mark strip right part
        warped_right_part = cv2.bitwise_or(warped_right_part, mask)

        # reversing the mask
        mask -= 255
        mask *= -1

        # masking current mark strip left part
        warped_left_part = cv2.bitwise_or(warped_left_part, mask)

        # joining current mark strip parts and aplying them to canvas
        canvas[0:warped_left_part.shape[0], :] = cv2.bitwise_and(
            cv2.bitwise_and(warped_left_part, warped_right_part).astype('int8'),
            canvas[0:warped_left_part.shape[0], :].astype('int8')
        )

    if second_layer:
        # this is currently unused.

        # iterating through range of vertical marks indexes beginning on the second
        for index in range(len(right_vertical_marks))[1:]:

            if horizontal_offset:
                # declaring bar points of current mark strip right part
                bar_points = np.float32([
                    [left_vertical_marks[index - 1]['x'] + left_vertical_marks[index - 1]['w'] - horizontal_offset, left_vertical_marks[index - 1]['y'] + left_vertical_marks[index - 1]['h']],
                    [right_vertical_marks[index - 1]['x'] + horizontal_offset, right_vertical_marks[index - 1]['y'] + right_vertical_marks[index - 1]['h']],
                    [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - horizontal_offset, left_vertical_marks[index]['y'] + left_vertical_marks[index]['h']]
                ])
            else:
                # declaring bar points of current mark strip right part
                bar_points = np.float32([
                    [left_vertical_marks[index - 1]['x'], left_vertical_marks[index - 1]['y'] + left_vertical_marks[index - 1]['h']],
                    [right_vertical_marks[index - 1]['x'] + right_vertical_marks[index - 1]['w'], right_vertical_marks[index - 1]['y'] + right_vertical_marks[index - 1]['h']],
                    [left_vertical_marks[index]['x'], left_vertical_marks[index]['y'] + left_vertical_marks[index]['h']]
                ])

            # declaring final points of current mark strip right part
            final_points = np.float32([
                [0, 0],
                [width, 0],
                [0, abs((left_std_vertical_marks[index-1]['y'] + left_std_vertical_marks[index-1]['h']) - (left_std_vertical_marks[index]['y'] + left_std_vertical_marks[index]['h']))]
            ])

            # declaring affine transformation matrix for current mark strip right part
            matrix = cv2.getAffineTransform(bar_points, final_points)

            # declaring warped current mark strip right part
            warped_right_part = cv2.warpAffine(image_copy, matrix, (width, abs((left_std_vertical_marks[index-1]['y'] + left_std_vertical_marks[index-1]['h']) - (left_std_vertical_marks[index]['y'] + left_std_vertical_marks[index]['h'])))).astype('int8')

            if horizontal_offset:
                # declaring bar points of current mark strip left part
                bar_points = np.float32([
                    [right_vertical_marks[index - 1]['x'] + horizontal_offset, right_vertical_marks[index - 1]['y'] + right_vertical_marks[index - 1]['h']],
                    [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - horizontal_offset, left_vertical_marks[index]['y'] + left_vertical_marks[index]['h']],
                    [right_vertical_marks[index]['x'] + horizontal_offset, right_vertical_marks[index]['y'] + right_vertical_marks[index]['h']]
                ])
            else:
                # declaring bar points of current mark strip left part
                bar_points = np.float32([
                    [right_vertical_marks[index - 1]['x'] + right_vertical_marks[index - 1]['w'], right_vertical_marks[index-1]['y'] + right_vertical_marks[index-1]['h']],
                    [left_vertical_marks[index]['x'], left_vertical_marks[index]['y'] + left_vertical_marks[index]['h']],
                    [right_vertical_marks[index]['x'] + right_vertical_marks[index]['w'], right_vertical_marks[index]['y'] + right_vertical_marks[index]['h']]
                ])

            # declaring final points of current mark strip left part
            final_points = np.float32([
                [width, 0],
                [0, abs((left_std_vertical_marks[index-1]['y'] + left_std_vertical_marks[index-1]['h']) - (left_std_vertical_marks[index]['y'] + left_std_vertical_marks[index]['h']))],
                [width, abs((left_std_vertical_marks[index-1]['y'] + left_std_vertical_marks[index-1]['h']) - (left_std_vertical_marks[index]['y'] + left_std_vertical_marks[index]['h']))],
            ])

            # declaring affine transformation matrix for current mark strip left part
            matrix = cv2.getAffineTransform(bar_points, final_points)

            # declaring warped current mark strip left part
            warped_left_part = cv2.warpAffine(image_copy, matrix, (width, abs((left_std_vertical_marks[index-1]['y'] + left_std_vertical_marks[index-1]['h']) - (left_std_vertical_marks[index]['y'] + left_std_vertical_marks[index]['h'])))).astype('int8')

            # declaring diagonal mask to join both parts
            mask = np.zeros((abs((left_std_vertical_marks[index-1]['y'] + left_std_vertical_marks[index-1]['h']) - (left_std_vertical_marks[index]['y'] + left_std_vertical_marks[index]['h'])), width), dtype="int8")
            mask_points = np.array([
                [width, 0],
                [0, abs((left_std_vertical_marks[index-1]['y'] + left_std_vertical_marks[index-1]['h']) - (left_std_vertical_marks[index]['y'] + left_std_vertical_marks[index]['h'])) - 2],
                [width, abs((left_std_vertical_marks[index-1]['y'] + left_std_vertical_marks[index-1]['h']) - (left_std_vertical_marks[index]['y'] + left_std_vertical_marks[index]['h'])) - 2],
            ])
            cv2.fillPoly(mask, [mask_points], (255, 255, 255))

            # masking current mark strip right part
            warped_right_part = cv2.bitwise_or(warped_right_part, mask)

            # reversing the mask
            mask -= 255
            mask *= -1

            # masking current mark strip left part
            warped_left_part = cv2.bitwise_or(warped_left_part, mask)

            # joining current mark strip parts and aplying them to canvas
            canvas[left_std_vertical_marks[index-1]['y']+left_std_vertical_marks[index-1]['h']:left_std_vertical_marks[index]['y'] + left_std_vertical_marks[index]['h'], :] = cv2.bitwise_and(
                cv2.bitwise_and(warped_left_part, warped_right_part).astype('int8'),
                canvas[left_std_vertical_marks[index-1]['y']+left_std_vertical_marks[index-1]['h']:left_std_vertical_marks[index]['y'] + left_std_vertical_marks[index]['h'], :].astype('int8')
            )

    ballot.ballotimgdict['images'][page] = canvas


def dominion_stretch_fix_old(ballot, std_timing_marks, page):
    """
    DEPRECATED
    Function which unstretches Dominion images if possible
    :param image: (np.array) array of an image, which might need unstretching
    :return canvas: (np.array) array of an image after unstretching, or it's copy if it not required
    """

    image = ballot.ballotimgdict['images'][page]
    ballot_id = ballot.ballotdict['ballot_id']
    height, width = image.shape
    image_copy = image.copy()
    canvas = image.copy()
    canvas[80:height - 150, :] = 255


    [left_vertical_marks, right_vertical_marks, top_marks] = [ballot.ballotdict['timing_marks'][page][x] for x in ['left_vertical_marks', 'right_vertical_marks', 'top_marks']]

    # if number of marks on both side matches and adjustment required is se to true
    if len(left_vertical_marks) == len(right_vertical_marks):

        # declaring index as last index of marks lists
        index = len(left_vertical_marks) - 1

        # declaring top offset as 80 to set up fixed starting point
        top_offset = 80

        # declaring bar points of below marks strip right part
        bar_points = np.float32([
            [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - 20, left_vertical_marks[index]['y'] + 20 - 2],
            [right_vertical_marks[index]['x'] + 20, right_vertical_marks[index]['y'] + 20 - 2],
            [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - 20, left_vertical_marks[index]['y'] + 20 + left_vertical_marks[index]['h'] + 2]
        ])

        # declaring final points of below marks strip right part
        final_points = np.float32([
            [0, 0],
            [width, 0],
            [0, 24]
        ])

        # declaring affine transformation matrix for below marks strip right part
        matrix = cv2.getAffineTransform(bar_points, final_points)

        # declaring warped below marks strip right part
        warped_right_part = cv2.warpAffine(image_copy, matrix, (width, 24)).astype('int8')

        # declaring bar points of below marks strip left part
        bar_points = np.float32([
            [right_vertical_marks[index]['x'] + 20, right_vertical_marks[index]['y'] + 20 - 2],
            [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - 20, left_vertical_marks[index]['y'] + 20 + left_vertical_marks[index]['h'] + 2],
            [right_vertical_marks[index]['x'] + 20, left_vertical_marks[index]['y'] + 20 + left_vertical_marks[index]['h'] + 2]
        ])

        # declaring final points of below marks strip left part
        final_points = np.float32([
            [width, 0],
            [0, 24],
            [width, 24],
        ])

        # declaring affine transformation matrix for below marks strip left part
        matrix = cv2.getAffineTransform(bar_points, final_points)

        # declaring warped below marks strip left part
        warped_left_part = cv2.warpAffine(image_copy, matrix, (width, 24)).astype('int8')

        # declaring diagonal mask to join both parts
        mask = np.zeros((24, width), dtype="int8")
        mask_points = np.array([
            [width, 0],
            [0, 24],
            [width, 24],
        ])
        cv2.fillPoly(mask, [mask_points], (255, 255, 255))

        # masking below marks strip right part
        warped_right_part = cv2.bitwise_or(warped_right_part, mask)

        # reversing the mask
        mask -= 255
        mask *= -1

        # masking below marks strip left part
        warped_left_part = cv2.bitwise_or(warped_left_part, mask)

        # joining below marks strip parts and aplying them to canvas
        canvas[top_offset + index * 44 + 19 - 2: top_offset + (index + 1) * 44 - 5 + 2, :] = cv2.bitwise_and(
            canvas[top_offset + index * 44 + 19 - 2: top_offset + (index + 1) * 44 - 5 + 2, :].astype('int8'),
            cv2.bitwise_and(warped_left_part, warped_right_part).astype('int8')
        )

        # declaring index as zero
        index = 0

        # declaring bar points of first mark strip right part
        bar_points = np.float32([
            [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - 20, left_vertical_marks[index]['y'] - 2],
            [right_vertical_marks[index]['x'] + 20, right_vertical_marks[index]['y'] - 2],
            [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - 20, left_vertical_marks[index]['y'] + left_vertical_marks[index]['h'] + 2]
        ])

        # declaring final points of first mark strip right part
        final_points = np.float32([
            [0, 0],
            [width, 0],
            [0, 28]
        ])

        # declaring affine transformation matrix for first mark strip left part
        matrix = cv2.getAffineTransform(bar_points, final_points)

        # declaring warped first mark strip right part
        warped_right_part = cv2.warpAffine(image_copy, matrix, (width, 28)).astype('int8')

        # declaring bar points of first mark strip left part
        bar_points = np.float32([
            [right_vertical_marks[index]['x'] + 20, right_vertical_marks[index]['y'] - 2],
            [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - 20, left_vertical_marks[index]['y'] + left_vertical_marks[index]['h'] + 2],
            [right_vertical_marks[index]['x'] + 20, left_vertical_marks[index]['y'] + left_vertical_marks[index]['h'] + 2]
        ])

        # declaring final points of first mark strip left part
        final_points = np.float32([
            [width, 0],
            [0, 28],
            [width, 28],
        ])

        # declaring affine transformation matrix for first mark strip right part
        matrix = cv2.getAffineTransform(bar_points, final_points)

        # declaring warped first mark strip left part
        warped_left_part = cv2.warpAffine(image_copy, matrix, (width, 28)).astype('int8')

        # declaring diagonal mask to join both parts
        mask = np.zeros((28, width), dtype="int8")
        mask_points = np.array([
            [width, 0],
            [0, 24],
            [width, 24],
        ])
        cv2.fillPoly(mask, [mask_points], (255, 255, 255))

        # masking first mark strip right part
        warped_right_part = cv2.bitwise_or(warped_right_part, mask)

        # reversing the mask
        mask -= 255
        mask *= -1

        # masking first mark strip left part
        warped_left_part = cv2.bitwise_or(warped_left_part, mask)

        # joining first mark strip parts and aplying them to canvas
        canvas[top_offset + index * 44 - 2:top_offset + index * 44 + 24 + 2, :] = cv2.bitwise_and(
            canvas[top_offset + index * 44 - 2:top_offset + index * 44 + 24 + 2, :].astype('int8'),
            cv2.bitwise_and(warped_left_part, warped_right_part).astype('int8')
        )
        # iterating through range of vertical marks indexes beginning on the second
        for index in range(len(right_vertical_marks))[1:]:
            # declaring bar points of current mark strip right part
            bar_points = np.float32([
                [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - 20, left_vertical_marks[index]['y'] - 2],
                [right_vertical_marks[index]['x'] + 20, right_vertical_marks[index]['y'] - 2],
                [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - 20, left_vertical_marks[index]['y'] + left_vertical_marks[index]['h'] + 2]
            ])

            # declaring final points of current mark strip right part
            final_points = np.float32([
                [0, 0],
                [width, 0],
                [0, 28]
            ])

            # declaring affine transformation matrix for current mark strip right part
            matrix = cv2.getAffineTransform(bar_points, final_points)

            # declaring warped current mark strip right part
            warped_right_part = cv2.warpAffine(image_copy, matrix, (width, 28)).astype('int8')

            # declaring bar points of current mark strip left part
            bar_points = np.float32([
                [right_vertical_marks[index]['x'] + 20, right_vertical_marks[index]['y'] - 2],
                [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - 20, left_vertical_marks[index]['y'] + left_vertical_marks[index]['h'] + 2],
                [right_vertical_marks[index]['x'] + 20, left_vertical_marks[index]['y'] + left_vertical_marks[index]['h'] + 2]
            ])

            # declaring final points of current mark strip left part
            final_points = np.float32([
                [width, 0],
                [0, 28],
                [width, 28],
            ])

            # declaring affine transformation matrix for current mark strip left part
            matrix = cv2.getAffineTransform(bar_points, final_points)

            # declaring warped current mark strip left part
            warped_left_part = cv2.warpAffine(image_copy, matrix, (width, 28)).astype('int8')

            # declaring diagonal mask to join both parts
            mask = np.zeros((28, width), dtype="int8")
            mask_points = np.array([
                [width, 0],
                [0, 24],
                [width, 24],
            ])
            cv2.fillPoly(mask, [mask_points], (255, 255, 255))

            # masking current mark strip right part
            warped_right_part = cv2.bitwise_or(warped_right_part, mask)

            # reversing the mask
            mask -= 255
            mask *= -1

            # masking current mark strip left part
            warped_left_part = cv2.bitwise_or(warped_left_part, mask)

            # joining current mark strip parts and aplying them to canvas
            canvas[top_offset + index * 44 - 2:top_offset + index * 44 + 24 + 2, :] = cv2.bitwise_and(
                canvas[top_offset + index * 44 - 2:top_offset + index * 44 + 24 + 2, :].astype('int8'),
                cv2.bitwise_and(warped_left_part, warped_right_part).astype('int8')
            )

            # declaring bar points of above current mark strip right part
            bar_points = np.float32([
                [left_vertical_marks[index - 1]['x'] + left_vertical_marks[index - 1]['w'] - 20, left_vertical_marks[index - 1]['y'] + left_vertical_marks[index - 1]['h'] + 1 - 2],
                [right_vertical_marks[index - 1]['x'] + 20, right_vertical_marks[index - 1]['y'] + right_vertical_marks[index - 1]['h'] + 1 - 2],
                [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - 20, left_vertical_marks[index]['y'] - 1 + 2]
            ])

            # declaring final points of above current mark strip right part
            final_points = np.float32([
                [0, 0],
                [width, 0],
                [0, 24]
            ])

            # declaring affine transformation matrix for above current mark strip right part
            matrix = cv2.getAffineTransform(bar_points, final_points)

            # declaring warped above current mark strip right part
            warped_right_part = cv2.warpAffine(image_copy, matrix, (width, 24)).astype('int8')

            # declaring bar points of above current mark strip left part
            bar_points = np.float32([
                [right_vertical_marks[index - 1]['x'] + 20, right_vertical_marks[index - 1]['y'] + right_vertical_marks[index - 1]['h'] + 1 - 2],
                [left_vertical_marks[index]['x'] + left_vertical_marks[index]['w'] - 20, left_vertical_marks[index]['y'] - 1 + 2],
                [right_vertical_marks[index]['x'] + 20, left_vertical_marks[index]['y'] - 1 + 2]
            ])

            # declaring final points of above current mark strip left part
            final_points = np.float32([
                [width, 0],
                [0, 24],
                [width, 24],
            ])

            # declaring affine transformation matrix for above current mark strip left part
            matrix = cv2.getAffineTransform(bar_points, final_points)

            # declaring warped above current mark strip left part
            warped_left_part = cv2.warpAffine(image_copy, matrix, (width, 24)).astype('int8')

            # declaring diagonal mask to join both parts
            mask = np.zeros((24, width), dtype="int8")
            mask_points = np.array([
                [width, 0],
                [0, 20],
                [width, 20],
            ])
            cv2.fillPoly(mask, [mask_points], (255, 255, 255))

            # masking above current mark strip right part
            warped_right_part = cv2.bitwise_or(warped_right_part, mask)
            mask -= 255
            mask *= -1

            # masking above current mark strip left part
            warped_left_part = cv2.bitwise_or(warped_left_part, mask)

            # joining above current mark strip parts and aplying them to canvas
            canvas[top_offset + (index - 1) * 44 + 24 - 2:top_offset + index * 44 + 2, :] = cv2.bitwise_and(
                canvas[top_offset + (index - 1) * 44 + 24 - 2:top_offset + index * 44 + 2, :].astype('int8'),
                cv2.bitwise_and(warped_left_part, warped_right_part).astype('int8')
            )
    else:
        utils.exception_report(f"number of left_vertical_marks {len(left_vertical_marks)} does not match right_vertical_marks {len(right_vertical_marks)} ballot_id:{ballot_id} page:{page}")


    return canvas

def is_archived_file_BMD_type_dominion(ballot):
    """ This does not work.
    """

    if len(ballot.ballotimgdict['images']) > 1:
        return False

    # if only one image, examine the aspect ratio:
    try:
        height, width = ballot.ballotimgdict['images'][0].shape
    except IndexError:
        utils.exception_report("Could not determine aspect ratio in attempt to determine BMD status.")
        return False

    aspect_ratio = height / width

    if aspect_ratio > 5:
        return False

    return True

def dominion_page_split(image, ballot_id):
    """
    given 3-up dominion image, split and return two ballot images.

    This algorithm looks for the alignment blocks on the left edge of the combined page.
    There are normally four of these blocks, two on each ballot page, and none on the last AuditMark page.
    The split will be done halfway between marks 2 and three, and then after mark 4, using the same spacing.
    Note that this does not attempt to align each page or crop to the alignment blocks.

    :param image: (np.array) array of an unaligned image of Dominion type ballot
    :param ballot_id: (str) provided to allow diagnostic exception reports
    :return pages: (list) list of images of aligned Dominion type ballot pages
    :return summary: (np.array) array of an unaligned image of Dominion type ballot summary
                        This is the image only, not OCR'd
    """

    diagnostic_mode = bool(args.argsdict.get('job','') == 'resources/SF_Pri_2020')

    # declaring image height and width
    height, width = image.shape

    # the ratio of image is at least 5 to 1
    # this section deals with splitting combined image type.
    # At present this is hardcoded for the page size found in Leon County 2018 (3450)

    aspect_ratio = height / width
    if aspect_ratio > 5:
        utils.sts(f"dominion_page_split aspect ratio indicates combined page format: {round(aspect_ratio, 2)}. Splitting...", 3)

        # declaring division shapes as a copy of image
        division_shapes0 = image.copy()

        #        division_shapes[:50, :] = 255
        #        division_shapes[:, :30] = 255

        # preparing kernel for erosion and dilation
        kernel_line = np.ones((5, 5), np.uint8)

        # eroding and dilating to remove imperfections from division marks
        division_shapes1 = cv2.erode(division_shapes0, kernel_line, iterations=1)
        division_shapes2 = cv2.dilate(division_shapes1, kernel_line, iterations=1)

        # preparing kernel for erosion and dilation
        kernel_line = np.ones((50, 60), np.uint8)

        # eroding to clear everything but division marks
        division_shapes3 = cv2.dilate(division_shapes2, kernel_line, iterations=1)

        # between erosion-dilation removing of contours 50px or closer to the vertical edges
        division_shapes3 = cv2.bitwise_not(division_shapes3)
        division_shapes_contours, _ = cv2.findContours(division_shapes3, 1, cv2.CHAIN_APPROX_NONE)
        for cnt in division_shapes_contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if (x <= 50 or width - 50 <= x ) and w < width/2:
                cv2.drawContours(division_shapes3, [cnt], -1, (0, 0, 0), -1)
        division_shapes3 = cv2.bitwise_not(division_shapes3)

        # dilating to clear everything but division marks
        division_shapes4 = cv2.erode(division_shapes3, kernel_line, iterations=1)

        # cutting division shapes after 300 pix
        # division_shapes5 = cv2.bitwise_not(division_shapes4)[:, :300]
        division_shapes5 = division_shapes4[:, :300]

        # finding division shapes contours out of division shapes
        division_shapes_contours, _ = cv2.findContours(division_shapes5, 1, cv2.CHAIN_APPROX_NONE)

        # declaring empty division marks list
        division_marks = []

        # iterating through division shapes contours
        # masking contours touching the borders
        for cnt in division_shapes_contours:
            x, y, w, h = cv2.boundingRect(cnt)
            # utils.sts(f"division shapes_contours: x={x} y={y} w={w} h={h}", 3)
            if x <= 1 or y <= 1 or y + h >= height - 2:
                # utils.sts("removing contour", 3)
                continue
            division_marks.append({
                'x': x,
                'y': y,
                'w': w,
                'h': h,
            })

        # we should find exactly 4 contours.
        if len(division_marks) == 4:

            # sorting division marks top to bottom
            division_marks = sorted(division_marks, key=lambda vertical_mark: vertical_mark['y'])

            if diagnostic_mode:
                for idx, mark in enumerate(division_marks):
                    utils.sts(f"Mark {idx}: x={mark['x']} y={mark['y']} w={mark['w']} h={mark['h']}", 3)

            # declaring h dividing points for both pages
            # page0_cut = division_marks[1]['y'] + division_marks[1]['h'] + int((division_marks[2]['y'] - division_marks[1]['y'] - division_marks[1]['h'])/2)

            # first cut is halfway between second and third mark.
            # this can be easily found by adding the offsets to those blocks and the height of one of the blocks and dividing by 2.
            page0_cut = round((division_marks[1]['y'] + division_marks[1]['h'] + division_marks[2]['y']) / 2)

            half_gap = division_marks[2]['y'] - page0_cut

            page1_cut = division_marks[3]['y'] + division_marks[3]['h'] + half_gap

            if len(recent_cut_points_0) < num_recent_cut_points:
                recent_cut_points_0.append(page0_cut)
                recent_cut_points_1.append(page1_cut)

            page_size_0 = division_marks[1]['y'] + division_marks[1]['h'] - division_marks[0]['y']
            page_size_1 = division_marks[3]['y'] + division_marks[3]['h'] - division_marks[2]['y']
            page_size_2 = height - (division_marks[3]['y'] + division_marks[3]['h'])

            if diagnostic_mode:
                utils.sts(f"dominion_page_split successful -- used alignment marks\n" \
                          f"    page sizes 0:{page_size_0} 1:{page_size_1} 2:{page_size_2}", 3)

        else:
            # unable to divide the image based on alignment marks.
            # record the images for diagnostics.
            utils.exception_report(f"dominion_page_split failed: expected contours not found. Saving images for ballot_id {ballot_id}")
            for idx, mark in enumerate(division_marks):
                utils.sts(f"Mark {idx}: x={mark['x']} y={mark['y']} w={mark['w']} h={mark['h']}", 3)

            DB.save_alignment_image(ballot_id=ballot_id, image=image, type='original_image')
            DB.save_alignment_image(ballot_id=ballot_id, image=division_shapes0, type='division_shapes0')
            DB.save_alignment_image(ballot_id=ballot_id, image=division_shapes1, type='division_shapes1')
            DB.save_alignment_image(ballot_id=ballot_id, image=division_shapes2, type='division_shapes2')
            DB.save_alignment_image(ballot_id=ballot_id, image=division_shapes3, type='division_shapes3')
            DB.save_alignment_image(ballot_id=ballot_id, image=division_shapes4, type='division_shapes4')

            if len(recent_cut_points_0):
                # insufficient contours have been found.
                # This can happen if:
                #   page 2 is offset to the right causing a large stripe on the left.
                #   corners are folded over causing black triangles which may corrupt the alignment marks.
                # if we have done at least one page prior to this one, use that page as the guide.
                # Use average of recent cut points.
                utils.sts(f"dominion_page_split -- failed to find alignment marks. Using prior cut points for ballot_id {ballot_id}")

                page0_cut = int(sum(recent_cut_points_0) / len(recent_cut_points_0))
                page1_cut = int(sum(recent_cut_points_1) / len(recent_cut_points_1))

            else:
                # try hardcoded cut points:
                # these set for Leon County
                #
                page0_cut = 3453
                page1_cut = 6869

        # At this point, either custom cut points have been calculated, or we are using
        # recently derived cut points from other pages.

        # declaring pages list and filling it with first two parts of image
        pages = [image[:page0_cut, :], image[page0_cut:page1_cut, :]]

        # declaring summary as third part of the image
        summary = image[page1_cut + 1:, :]

        if diagnostic_mode:
            utils.sts(f"dominion_page_split successful\n" \
                      f"    cut points: 0:{page0_cut} 1:{page1_cut} 2:{height - page1_cut}", 3)


    # the aspect ratio of image is around 2 (single Domminion page)
    elif 1.7 < aspect_ratio < 2.3:
        #utils.sts(f"dominion_page_split aspect ratio indicates single page format: {round(aspect_ratio, 2)}")

        # declaring pages list and filling it with first whole image
        pages = [image]

        # declaring summary as None
        summary = None

    # the ratio of image is any other then two above
    else:
        utils.exception_report(f"dominion_page_split failure: Page aspect ratio is unusual: {round(aspect_ratio, 2)}")
        return None, None

    return pages, summary
    #---- end of dominion_page_split()

def dominion_alignment(image, ballot_id):
    """
    This function performs:
        1. splitting of single-image type (3-up) Dominion format ballot images.
        2. basic alignment to alignment marks and best estimate of lower-right corner.
        3. extraction of barcode.
    returns the aligned pages, summary, style_num

    Note that this function no longer does stretch-fixing.
    This function does not extract timing marks.

    :param image: (np.array) array of an unaligned image of Dominion type ballot
    :param ballot_id: (str) provided to allow diagnostic exception reports
    :return pages: (list) list of images of aligned Dominion type ballot pages
    :return summary: (np.array) array of an unaligned image of Dominion type ballot summary
                        This is the image only, not OCR'd
    :return codes: (list) list of codes of the ballot pages
    """

    # first step is to split the three-up page into separate pages.
    # This step is note necessary if the dominion page is already split using
    # multi-page TIF format.

    pages, summary = dominion_page_split(image, ballot_id)

    if pages is None:
        return None, None, None

    # declaring codes list
    codes = []
    barcode_area = []
    save_diagnostic_images = bool(args.argsdict.get('job','') == 'resources/SF_Pri_2020')
    #save_diagnostic_images = False

    # iterating through enumerated pages
    for index, page in enumerate(pages):
        # declaring page height and width
        page_height, page_width = page.shape

        # vertical and horizontal dilating end eroding lines and text for only major marks to remain
        basic_shapes = dominion_erode_dilate_contours(page, page_height, page_width)

        # saving basic shapes for diagnosis
        if save_diagnostic_images:
            DB.save_alignment_image(ballot_id=ballot_id, image=basic_shapes, type=f"basic_shapes1_p{index}")

        # inverting basic shapes
        basic_shapes = cv2.bitwise_not(basic_shapes)

        # finding basic shapes contours out of basic shapes
        basic_shapes_contours, _ = cv2.findContours(basic_shapes, 1, cv2.CHAIN_APPROX_NONE)

        # iterating through basic shapes contours
        # masking contours touching the borders
        # Ray says: I don't fully understand what this is doing.
        for cnt in basic_shapes_contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if x <= 1 or x + w >= page_width - 2 or y <= 1 or y + h >= page_height - 2:
                cv2.drawContours(basic_shapes, [cnt], -1, (0, 0, 0), -1)

        # inverting basic shapes
        basic_shapes = cv2.bitwise_not(basic_shapes)
        if save_diagnostic_images:
            DB.save_alignment_image(ballot_id=ballot_id, image=basic_shapes, type=f"basic_shapes2_p{index}")
        # cv2.imwrite('test2.png', basic_shapes)

        # checking if any shapes are present
        if round(sum(cv2.mean(basic_shapes))) == 255:
            #utils.exception_report(f"dominion_align failure: basic_shapes not found, ballot:{ballot_id}")
            # when p1 is blank, this is normal.
            return None, None, None

        # filling list of points of which top and bottom contours consist
        if save_diagnostic_images:
            utils.sts(f"Extracting ballot {ballot_id} potential corner points", 3)
        points, bottom_contours = dominion_get_points(basic_shapes, page_height, page_width)

        if points is None:
            # failed to get the points
            utils.exception_report(f"dominion_get_points failure: not all alignment blocks were found, ballot:{ballot_id}")
            DB.save_alignment_image(ballot_id=ballot_id, image=basic_shapes, type='basic_shapes')
            return None, None, None


        # find our best estimate of the correct corner points.
        if save_diagnostic_images:
            utils.sts(f"Choosing ballot {ballot_id} corner points", 3)

        bottom_left_point, top_right_point, top_left_point, bottom_right_point = dominion_find_corner_points(points, bottom_contours, page_height, page_width)

        if not any(bottom_left_point):
            # failed to convert
            utils.exception_report(f"dominion_align failure: alignment targets not found, ballot:{ballot_id}")
            DB.save_alignment_image(ballot_id=ballot_id, image=basic_shapes, type='basic_shapes')
            return None, None, None

        # perspective transforming the page
        if save_diagnostic_images:
            utils.sts(f"Aligning ballot {ballot_id} via perspective transform", 3)
        page_xfm = dominion_transform(page, bottom_left_point, top_right_point, top_left_point, bottom_right_point)
        if save_diagnostic_images:
            DB.save_alignment_image(ballot_id=ballot_id, image=page_xfm, type=f"transformed_p{index}")

        # note that the height and width of the page is changed above
        page_height, page_width = page_xfm.shape

        # utils.sts(f"page area, p{index}: h={page_height} w={page_width}", 3)

        # ---- dominion_style_barcode
        # declaring barcodes area and getting the code
        barcode_area_y1 = page_height + dominion_barcode_area['y']  # dominion_barcode_area['y'] is negative
        barcode_area_y2 = barcode_area_y1 + dominion_barcode_area['h']
        barcode_area_x1 = dominion_barcode_area['x']
        barcode_area_x2 = barcode_area_x1 + dominion_barcode_area['w']

        # utils.sts(f"barcode area, p{index}: y={barcode_area_y1}:{barcode_area_y2} x={barcode_area_x1}:{barcode_area_x2}", 3)
        barcode_area.append(page_xfm[barcode_area_y1:barcode_area_y2, barcode_area_x1:barcode_area_x2].copy())
        if save_diagnostic_images:
            DB.save_alignment_image(ballot_id=ballot_id, image=barcode_area[index], type=f"barcode_area_p{index}")

        card_code, sheet_page, diagnostic_str = dominion_get_code(barcode_area[index], index, ballot_id)
        if not card_code:
            # failed to convert bar code. This also likely means the alignment is screwed up.
            utils.exception_report(f"Failed to convert style barcode, Saving barcode area for diagnosis, ballot:{ballot_id}.\n" + diagnostic_str)
            DB.save_alignment_image(ballot_id=ballot_id, image=image, type='original_image')
            DB.save_alignment_image(ballot_id=ballot_id, image=basic_shapes, type=f"basic_shapes_p{index}")
            DB.save_alignment_image(ballot_id=ballot_id, image=page_xfm, type=f"page_xfm_p{index}")
            DB.save_alignment_image(ballot_id=ballot_id, image=barcode_area[index], type=f"barcode_area_p{index}")
            return None, None, None

        # adding code to codes list
        codes.append(str(card_code))

        # replacing page with transformed page
        pages[index] = page_xfm

    # if all the codes in the list are the same
    # this section only applies to the case where the page was split from one image.
    if len(codes) > 1 and not codes[0] == codes[1]:
        # if all the codes in the list are not the same
        # the style num can be taken from front of the page only.
        utils.exception_report(f"Ballot page codes are not equal p0:{codes[0]} p1:{codes[1]}, ballot:{ballot_id}, Saving barcode area for diagnosis.")
        DB.save_alignment_image(ballot_id=ballot_id, image=image, type='original_image')
        for index in range(len(pages)):
            # utils.sts(f"index = {index}")
            DB.save_alignment_image(ballot_id=ballot_id, image=pages[index], type=f"page_p{index}")
            DB.save_alignment_image(ballot_id=ballot_id, image=barcode_area[index], type=f"barcode_area_p{index}")

    # replacing the list with its every elements value but keep it as a list.
    card_code = codes[0]

    # returning aligned pages and summary
    return pages, summary, card_code


def dominion_bmd_conversion(image):
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

            '''
            # creating qrcode shape threshold
            qrcode_shape = np.zeros(image.shape)
            qrcode_poly = []
            for point in barcodes[0].polygon:
                qrcode_poly.append(tuple(point))
            qrcode_shape = cv2.drawContours(qrcode_shape, [np.array(qrcode_poly, dtype=np.int8)], 0, (255, 255, 255), -1)

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
            '''

            # locating the qrcode after rotation
            #qrcode = barcode_decode(rotated_image)

            working_image = image.copy()
            #
            # barcodes_decode returns data like the following:
            #
            # { Decoded(data=b'',
            #   type='QRCODE',
            #   rect=Rect(left=59, top=706, width=270, height=269),
            #   polygon=[Point(x=59, y=706), Point(x=61, y=974), Point(x=329, y=975), Point(x=327, y=710)])
            # ]
            # Text left edge is lined up with left edge of barcode.

            margin = 5
            num_cols = 3
            b_margin = 300

            text_x = barcodes[0].rect.left
            text_y = barcodes[0].rect.barcodes[0].rect.top + barcodes[0].rect.height
            text_w = width - barcodes[0].rect.left * 2
            col_w = text_w // num_cols
            col_h = height - b_margin - text_x

            ## calculating first column (right) border
            #for column_end_x in range(30, 1000):
            #    if math.ceil(sum(cv2.mean(working_image[barcodes[0].rect.top + barcodes[0].rect.height + 5:1690, column_end_x:column_end_x + 25]))) == 255:
            #        break

            text_regions = [
                {   'x': text_x - margin,
                    'y': text_y + margin,
                    'w': text_w + margin,
                    'h': col_h,
                },
                {   'x': text_x + col_w,
                    'y': text_y + margin,
                    'w': text_w + margin,
                    'h': col_h,
                },
                {   'x': text_x + col_w * 2,
                    'y': text_y + margin,
                    'w': text_w + margin,
                    'h': col_h,
                },
            ]

            col_text = [None, None, None]
            for i, region in enumerate(text_regions):
                # should probably split the column based on white space to separate each contest.

                region_image = utils.extract_region(working_image, region)
                col_text[i] = ocr.ocr_text(region_image)

            all_text = r'\n'.join(col_text)

            # OCR of vertical code
            vertical_code = '' #ocr.ocr_core(cv2.rotate(working_image[barcodes[0].rect.top + barcodes[0].rect.height + 5:, -200:], cv2.ROTATE_90_CLOCKWISE))

            import pdb; pdb.set_trace()
            return all_text.splitlines(), vertical_code, barcodes[0]

        # if the first barcode is not a qrcode
        else:
            utils.exception_report("Barcodes not found although record is marked as QRCODE ballot")
            return None, None, None

    # if no barcodes were found
    else:
        utils.exception_report("Barcodes not found although record is marked as QRCODE ballot")
        return None, None, None


def dane2016_alignment(image):
    """
    PROBABLY NOT USED. This was an initial try on Dominion type.
    This should work on "older" dane images (.pbm type)
    :param image: (np.array) array of an unaligned image of Dominion type ballot
    :return: (np.array) array of an image of aligned Dominion type ballot
    """

    # declaring image height and width
    height, width = image.shape

    # vertical dilating end eroding lines and text for only marks to remain
    kernel_line = np.ones((1, 10), np.uint8)
    basic_shapes = cv2.dilate(image, kernel_line, iterations=3)
    basic_shapes = cv2.erode(basic_shapes, kernel_line, iterations=3)

    # horizontal dilating end eroding lines and text for only marks to remain
    kernel_line = np.ones((10, 1), np.uint8)
    basic_shapes = cv2.dilate(basic_shapes, kernel_line, iterations=3)
    basic_shapes = cv2.erode(basic_shapes, kernel_line, iterations=3)

    # checking if the image if front or back page of the ballot based on
    # mean of left and right halfs dependent on location of timing marks
    front_page = sum(cv2.mean(basic_shapes[:, :round(width / 2)])) < sum(cv2.mean(basic_shapes[:, round(width / 2):]))

    # declaring list of corner contours
    corner_contours = []

    # searching for 4 top marks
    for bottom_border in range(500):
        _, thresh = cv2.threshold(basic_shapes[:bottom_border, :], 254, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(thresh, 1, cv2.CHAIN_APPROX_SIMPLE)
        if len(contours) == 4 and sum(cv2.mean(basic_shapes[bottom_border - 1:bottom_border, :])) == 255:
            break

    # sorting found marks left to right
    contours = sorted(contours, key=lambda cnt: cnt[0][0][0])

    # adding horizontally extreme top marks to the list of corner contours
    corner_contours.append(contours[0])
    corner_contours.append(contours[3])

    # calculating mean changes in x and y coordinates between neighbouring top marks
    x, y, w, h = cv2.boundingRect(contours[1])
    x2, y2, w2, h2 = cv2.boundingRect(contours[2])
    upper_delta_x = x2 - (x + w)
    upper_delta_y = y2 - y
    x, y, w, h = cv2.boundingRect(contours[2])
    x2, y2, w2, h2 = cv2.boundingRect(contours[3])
    upper_delta_x = int((upper_delta_x + x2 - (x + w)) / 2)
    upper_delta_y = int((upper_delta_y + y2 - y) / 2)

    # searching for 4 bottom marks
    for upper_border in range(500):
        _, thresh = cv2.threshold(basic_shapes[height - upper_border:, :], 254, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(thresh, 1, cv2.CHAIN_APPROX_SIMPLE)
        if len(contours) == 4 and sum(cv2.mean(basic_shapes[height - upper_border:height - upper_border + 1, :])) == 255:
            break

    # sorting found marks left to right
    contours = sorted(contours, key=lambda cnt: cnt[0][0][0])

    # adding horizontally extreme bottom marks to the list of corner contours
    corner_contours.append(contours[0] + [0, height - upper_border])
    corner_contours.append(contours[3] + [0, height - upper_border])

    # calculating mean changes in x and y coordinates between neighbouring bottom marks
    x, y, w, h = cv2.boundingRect(contours[1])
    x2, y2, w2, h2 = cv2.boundingRect(contours[2])
    lower_delta_x = x2 - (x + w)
    lower_delta_y = y2 - y
    x, y, w, h = cv2.boundingRect(contours[2])
    x2, y2, w2, h2 = cv2.boundingRect(contours[3])
    lower_delta_x = int((lower_delta_x + x2 - (x + w)) / 2)
    lower_delta_y = int((lower_delta_y + y2 - y) / 2)

    # declaring and filling list of points of which top and bottom barks consist
    points = []
    for cnt in corner_contours:
        for point in cnt:
            points.append(point[0])

    # sorting points by range to bottom right corner and choosing the closest one
    points = sorted(
        points,
        key=lambda point: math.sqrt(
            pow(width - point[0], 2) +
            pow(height - point[1], 2)
        ))
    bottom_right_point = points[0]

    # sorting points by range to bottom left corner and choosing the closest one
    points = sorted(
        points,
        key=lambda point: math.sqrt(
            pow(0 - point[0], 2) +
            pow(height - point[1], 2)
        ))
    bottom_left_point = points[0]

    # sorting points by range to top right corner and choosing the closest one
    points = sorted(
        points,
        key=lambda point: math.sqrt(
            pow(width - point[0], 2) +
            pow(0 - point[1], 2)
        ))
    top_right_point = points[0]

    # sorting points by range to top left corner and choosing the closest one
    points = sorted(
        points,
        key=lambda point: math.sqrt(
            pow(0 - point[0], 2) +
            pow(0 - point[1], 2)
        ))
    top_left_point = points[0]

    # if the image is front page of the ballot
    print(front_page)
    if front_page:

        # adjusting right points to match ballot edge
        bottom_right_point = bottom_right_point + [lower_delta_x, lower_delta_y]
        top_right_point = top_right_point + [upper_delta_x, upper_delta_y]

        # declaring list of destination points for perspective transform
        destination_points = np.array([
            [0, 0],
            [config_dict['ALIGNED_RESOLUTION']['x'] + 34 - 1, 0],
            [config_dict['ALIGNED_RESOLUTION']['x'] + 34 - 1, config_dict['ALIGNED_RESOLUTION']['y'] + 4 - 1],
            [0, config_dict['ALIGNED_RESOLUTION']['y'] + 4 - 1]], dtype="float32")

    # if the image is back page of the ballot
    else:
        # adjusting left points to match ballot edge
        bottom_coefficient = 30 / math.sqrt(pow(lower_delta_x, 2) + pow(lower_delta_y, 2))
        top_coefficient = 30 / math.sqrt(pow(upper_delta_x, 2) + pow(upper_delta_y, 2))
        bottom_left_point = bottom_left_point - [round(lower_delta_x * bottom_coefficient), round(lower_delta_y * bottom_coefficient)]
        top_left_point = top_left_point - [round(upper_delta_x * top_coefficient), round(upper_delta_y * top_coefficient)]

        # adjusting right points to match ballot edge
        bottom_right_point = bottom_right_point - [1, 0]
        top_right_point = top_right_point - [1, 0]

        # declaring list of destination points for perspective transform
        destination_points = np.array([
            [0, 0],
            [config_dict['ALIGNED_RESOLUTION']['x'] - 1, 0],
            [config_dict['ALIGNED_RESOLUTION']['x'] - 1, config_dict['ALIGNED_RESOLUTION']['y'] + 4 - 1],
            [0, config_dict['ALIGNED_RESOLUTION']['y'] + 4 - 1]], dtype="float32")

    # declaring set of destination points for perspective transform
    source_points = np.array([
        top_left_point,
        top_right_point,
        bottom_right_point,
        bottom_left_point], dtype="float32")

    # declaring transformation matrix
    M = cv2.getPerspectiveTransform(source_points, destination_points)

    # returning transformed image
    return cv2.warpPerspective(image, M, (config_dict['ALIGNED_RESOLUTION']['x'], config_dict['ALIGNED_RESOLUTION']['y']))
