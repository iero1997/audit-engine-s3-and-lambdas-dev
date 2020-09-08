"""Main file to run 'style_generator' module."""

import cv2
import json
import os
import pytesseract
import re
import argparse
import numpy as np

pytesseract.pytesseract.tesseract_cmd = os.environ.get('TESSERACT_PATH', 'HOME')


def ocr_core(img: np.array) -> str:
    """
    :param img: an array containing analyzed image
    :return: OCRed text
    Handles the single line core OCR image processing consisting of strings.
    Using Pillow's Image class to open the image and pytesseract to detect
    the string in the image.
    """
    return pytesseract.image_to_string(img, lang='eng')


def ocr_core_names(img: np.array) -> str:
    """
    :param img: an array containing analyzed image
    :return: OCRed text
    Handles the single line core OCR image processing consisting of strings.
    Using Pillow's Image class to open the image and pytesseract to detect
    the string in the image.
    """
    text = pytesseract.image_to_string(
        img,
        lang='eng',
        config='--psm 7 --oem 3'
    )
    return text


def ocr_core_questions(img: np.array) -> str:
    """
    :param img: an array containing analyzed image
    :return: OCRed text
    Handles the single line core OCR image processing consisting of strings.
    Using Pillow's Image class to open the image and pytesseract to detect
    the string in the image.
    """
    text = pytesseract.image_to_string(
        img,
        config='--psm 12 --oem 3'
    )
    return text


def link_faulty_lines(image: np.array) -> np.array:
    '''
    :param image: an array containing base image
    :return: an array containing image with horizontal lines filled
    Filles horizontal lines within provided image to ensure smooth
    contour analysis further.
    '''
    image = cv2.bitwise_not(image)
    kernel_line = np.ones((1, 30), np.uint8)
    kernel_line[0][0] = 0

    clean_lines = cv2.erode(image, kernel_line, iterations=6)
    clean_lines = cv2.dilate(clean_lines, kernel_line, iterations=6)
    _, clean_lines = cv2.threshold(clean_lines, 15, 255, cv2.THRESH_BINARY_INV)

    kernel_line = np.ones((1, 30), np.uint8)
    image = cv2.bitwise_not(cv2.bitwise_and(cv2.bitwise_not(image), clean_lines))
    clean_lines = cv2.erode(image, kernel_line, iterations=6)
    clean_lines = cv2.dilate(clean_lines, kernel_line, iterations=6)
    _, clean_lines = cv2.threshold(clean_lines, 15, 255, cv2.THRESH_BINARY_INV)

    return cv2.bitwise_and(cv2.bitwise_not(image), clean_lines)


def clean_candidate_name(raw_name: str) -> str:
    """
    :param raw_name: string containing candidates name
    :return: cleaned candidates name string
    Cleans candidate string name value.
    """

    if re.search(r"ite-in", raw_name):

        return 'write-in:'
    clean_name = sanitize_string(raw_name)
    return clean_name


def sanitize_string(raw_string: str) -> str:
    """
    :param raw_string: the raw string to be processed
    :return: processed clean string
    Regex function that sanitizes raw strings based on a Regex pattern.
    """
    replacements = [
        ("[\u0022\u201C\u201D\u2033\u02BA\u3003\u02EE\u02F5\u02F6\u02DD\u0027\u0060\u2018\u2019"
         "\u2032\u0301\u0300]",
            "'"),
        ("[\u002D\u2010\u2013\u2014\u2212\u00AD\u2011\u2043]", "-"),
        ("[\u0020\u00A0\u2003\u2002]", " ")
    ]
    if not isinstance(raw_string, str):
        raise TypeError
    for pattern, replacement in replacements:
        raw_string = re.sub(pattern, replacement, raw_string)
    return raw_string


def clean_candidate_name_area(image: np.array, y_pos: int, x_pos: int, width:int, height: int) -> np.array:
    """
    :param image: an array containing candidate name area
    :param y_pos: vertical coordinate
    :param x_pos: horizontal coordinate
    :param width: width
    :param height: height
    :return: an array containing cleaned candidate name area
    Cleans candidate name ROI from borders and horizontal line.
    """
    cleaned_candidate_name_area = image[y_pos:y_pos + height + 10, x_pos + 50:x_pos + width].copy()
    cv2.rectangle(
        cleaned_candidate_name_area,
        (0, 0),
        (width - 50, height),
        (255, 255, 255),
        6,
    )
    cv2.rectangle(
        cleaned_candidate_name_area,
        (0, 0),
        (width - 50, height + 10),
        (255, 255, 255),
        6,
    )
    return cleaned_candidate_name_area


def get_checkbox_contours(contours: np.array) -> np.array:
    """
    :param contours: an array containing contours
    :return: an array containing selected contour
    Returns a list of checkbox contours from 'image'.
    """
    checkbox_cnt = np.ones((1, 1))
    result_size = 0
    for cnt in contours:
        approx = cv2.approxPolyDP(
            cnt,
            0.01 * cv2.arcLength(cnt, True),
            True,
        )
        cnt_x, cnt_y, cnt_w, cnt_h = cv2.boundingRect(cnt)
        del cnt_x
        del cnt_y
        size = float(cnt_w) * cnt_h
        area = cv2.contourArea(cnt)
        extent = float(area) / size
        if len(approx) >= 8\
                and size > 150 and extent > 0.6:
            if size > result_size:
                result_size = size
                checkbox_cnt = cnt
    return checkbox_cnt


def roi_ocr_generator(args: dict):
    """
    Generates ROIs based on JSON and PNG files within
    the folder selected by input path.
    :param args: arguments parsed by parser
    """

    # saving provided arguments into auxiliary variables
    # TODO add global default path in case 'spath' is not provided
    #  (willbe probably anabled later on)
    styles_path = args["spath"][0] if args["spath"] else ''
    save_roi_images = True if args["save_roi_images"] else False

    # extracting list of the files within style directory
    # looking for JSON style files within style directory
    files = [f for f in os.listdir(styles_path) if os.path.isfile(styles_path + f)]
    style_files = filter(lambda f: f.endswith(('.json', '.JSON')), files)

    # iterating through 'style_files'
    for style_file in style_files:

        # reading style file and saving its JSON to auxiliary variable
        with open(styles_path+style_file, 'r') as f:
            style_data = json.load(f)

        # looking for corresponding PNG style images within files within style directory
        style_images = filter(lambda fname: re.sub(r'\.json$', '', style_file) in fname and fname.endswith(('.png', '.PNG')), files)

        # declaring 'rois_list' list
        rois_list = []

        # iterating through enumerated 'style_images'
        for image_num, style_image in enumerate(style_images):

            # reading image from selected file
            cv_style_image = cv2.imread(styles_path+style_image, 0)

            # saving copy of the image with filled horizontal lines
            cv_style_image_adjusted = link_faulty_lines(cv_style_image).copy()

            # looking for contours within adjusted image
            _, thresh = cv2.threshold(cv_style_image_adjusted, 254, 255, 1)
            contours, _ = cv2.findContours(thresh, 1, cv2.CHAIN_APPROX_SIMPLE)

            # declaring 'selected_contours' list
            # declaring 'page_rois_list' list
            selected_contours = []
            page_rois_list = []

            # iterating through 'contours'
            for contour in contours:

                # declaring auxialiary variables containing contours
                # bounding rectange coords and shape
                x, y, w, h = cv2.boundingRect(contour)

                # if width is within range 500-600;
                #   width is proper to be a ROI
                # if height is within range 45-1600;
                #   height is proper to be a ROI
                # if extent is over 0.9;
                #   contour is rectangle-like
                if 500 < w < 600 and 45 < h < 1600 and float(cv2.contourArea(contour)) / (w * h) > 0.9:

                    # setting 'append_selected_contours' bool to True
                    append_selected_contours = True

                    # iterating through enumerated 'selected_contours'
                    for index, selected_contour in enumerate(selected_contours):

                        # declaring auxialiary variables containing selected contours
                        # bounding rectange coords and shape
                        sel_x, sel_y, sel_w, sel_h = cv2.boundingRect(selected_contour)

                        # if one of contous is within the other
                        if (sel_x < x and x + w < sel_x + sel_w and sel_y < y and y + h < sel_y + sel_h) or \
                                (x < sel_x and sel_x + sel_w < x + w and y < sel_y and sel_y + sel_h < y + h):

                            # copying interior contours coords, shape and contour array
                            # setting 'append_selected_contours' bool to False
                            # breaking the iteration
                            selected_contours[index] = contour
                            page_rois_list[index]['x'] = x
                            page_rois_list[index]['y'] = y
                            page_rois_list[index]['w'] = w
                            page_rois_list[index]['h'] = h
                            append_selected_contours = False
                            break

                    # if 'append_selected_contours' bool is still set to True
                    if append_selected_contours:

                        # appending 'selected_contours' list
                        # appending 'page_rois_list' list
                        selected_contours.append(contour)
                        page_rois_list.append({
                            'x': x,
                            'y': y,
                            'w': w,
                            'h': h
                        })

            # sorting 'page_rois_list' by rounded horizontal and exact vertical coordinates
            page_rois_list.sort(key=lambda lmb: (
                lmb['x'] if lmb['x'] % 100 == 0 else lmb['x'] + 100 - lmb['x'] % 100,
                lmb['y']))

            # iterating through enumerated 'page_rois_list'
            for index, roi in enumerate(page_rois_list):

                # declaring auxiliary variables containing coords and shape
                x = roi["x"]
                y = roi["y"]
                w = roi["w"]
                h = roi["h"]

                # if height is lass than 60;
                #   ROI is probably a option
                if h < 60:

                    # declaring 'candidate_name_area' and cleaning it
                    candidate_name_area = cv_style_image[y:y + h, x:x + w]
                    cleaned_candidate_name_area = clean_candidate_name_area(
                        cv_style_image, y, x, w, h)

                    # OCRing text within and saving it
                    name = ocr_core_names(cleaned_candidate_name_area)
                    if name == "":
                        name = "not found"
                    name = clean_candidate_name(name)
                    roi['ocr_name'] = name

                    # declaring 'checkbox_area'
                    checkbox_area = candidate_name_area[
                                    5:
                                    40,
                                    5:
                                    60
                                    ]

                    # applying exponential transform on 'checkbox_area' if
                    # the base image was created from more than 15 ballots
                    if style_data["created_from"] > 15:
                        base = 1.02
                        coefficient = 255.0 / (pow(base, 230) - 1)
                        for z in range(checkbox_area.shape[0]):
                            for x in range(checkbox_area.shape[1]):
                                if checkbox_area[z][x] <= 204:
                                    checkbox_area[z][x] = int(round(coefficient * (pow(base, checkbox_area[z][x]) - 1)))
                                else:
                                    checkbox_area[z][x] = 255

                    # looking for contours within checkbox area
                    # selecting checkbox contour and saving it
                    _, roi_thresh = cv2.threshold(checkbox_area, 170, 255, 1)
                    roi_contours, _ = cv2.findContours(roi_thresh, 1, cv2.CHAIN_APPROX_NONE)
                    roi['mark_contours'] = get_checkbox_contours(roi_contours).tolist()

                    # deleting the selected contour if it is a biased '1' array
                    if roi['mark_contours'] == [1]:
                        del roi['mark_contours']

                # height is over 60;
                # ROI is a question or contestname
                else:

                    # declaring 'checkbox_area'
                    contest_area = cv_style_image[
                                   y:
                                   y + h,
                                   x:
                                   x + w]

                    # OCRing text within, sanitizing and and saving it
                    name = ocr_core(contest_area)
                    if name == "":
                        name = ocr_core_questions(contest_area)
                        name = name.rstrip()
                    roi['ocr_name'] = sanitize_string(name)

                # appending 'rois_list' with 'page_rois_list'
                rois_list.append(page_rois_list)

            # if '-s' parameter was provided, ROI images will be saved
            if save_roi_images:

                # declaring path directory to save images within
                roi_images_save_dir = styles_path + re.sub(r'\.json$', '', style_file) + '/'

                # creating directory if it dosen';'t exist
                if not os.path.isdir(roi_images_save_dir):
                    os.mkdir(roi_images_save_dir)

                # iterating through enumerated 'page_rois_list'
                for index, roi in enumerate(page_rois_list):

                    # declaring path to image about to be saved
                    roi_image_save_path = roi_images_save_dir + f'roi({image_num}_{index}).png'

                    # deleting the image if it alreade exists
                    if os.path.exists(roi_image_save_path):
                        os.remove(roi_image_save_path)

                    # saving the image
                    cv2.imwrite(roi_image_save_path, cv_style_image[
                                                     roi["y"]:roi["y"] + roi["h"],
                                                     roi["x"]:roi["x"] + roi["w"]
                                                     ])

        # saving 'rois_list'
        style_data["rois"] = rois_list

        # saving JSON style file
        with open(styles_path+style_file, 'w') as f:
            json.dump(style_data, f)


def get_parser():
    parser = argparse.ArgumentParser(description='CVR to JSON schema parser')
    parser.add_argument('spath', metavar='STYLE DIR PATH', type=str, nargs=1,
                        help='style directory path')
    parser.add_argument('-s', '--save-roi-images', action="store_true",
                        help='save ROIs images')
    return parser


def command_line_runner():
    parser = get_parser()
    args = vars(parser.parse_args())

    if not args['spath']:
        parser.print_help()
        return

    roi_ocr_generator(args)


if __name__ == "__main__":
    command_line_runner()
