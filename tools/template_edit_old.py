import cv2
import numpy as np
import json
import argparse
import sys
import os
import warnings
import glob
import ctypes
from pathlib import Path


def read_and_resize(image_path, resized_height):
    '''
    Reads path from original image.
    Returns original image, resized image and the calculated scale.
    '''
    img = cv2.imread(image_path, 1)
    height, width, depth = img.shape
    im_scale = resized_height / height
    new_x,new_y = img.shape[1]*im_scale, img.shape[0]*im_scale
    newimg = cv2.resize(img, (int(new_x),int(new_y)))
    return img, newimg, im_scale


def draw(action, x, y, flags, userdata):
    '''
    Draws ROIs (rectangles and lines) on the image shown to the user.
    '''
    # Referencing global variables 
    global drawing, img_resized, scale, image_clear_all, image_without_last_element, last_element_type
    global rectangles_in_img, rectangle_points, end_point_rect_temp, rect
    global ver_lines_in_img, ver_line_points, end_point_v_line_temp, vertical
    global hor_lines_in_img, hor_line_points, end_point_h_line_temp, horizontal

    # Action to be taken when mouse moves and the user is drawing
    if action==cv2.EVENT_MOUSEMOVE and drawing:
        end_point_rect_temp = [(x, y)]
        end_point_v_line_temp = [(x, y)]
        end_point_h_line_temp = [(x, y)]
    
    # Action to be taken when left button is pressed while holding SHIFT: start drawing rectangle area
    elif flags == cv2.EVENT_FLAG_LBUTTON + cv2.EVENT_FLAG_SHIFTKEY:
        drawing = 1
        rect = True
        rectangle_points = [(x, y)]
        end_point_rect_temp = []
    
    elif flags == cv2.EVENT_FLAG_RBUTTON + cv2.EVENT_FLAG_CTRLKEY:
        current_click_point = (x,y)
        min_distance = np.inf
        element_to_be_deleted = {}
        for i, rectangle in enumerate(rectangles_in_img):
            dist = np.sqrt((rectangle['x']*scale - x)**2 + (rectangle['y']*scale - y)**2)
            if dist < min_distance:
                min_distance = dist
                element_to_be_deleted = {'rectangle':i}
        for i, v_line in enumerate(ver_lines_in_img):
            dist = np.sqrt((v_line['x']*scale - x)**2 + (v_line['y']*scale - y)**2)
            if dist < min_distance:
                min_distance = dist
                element_to_be_deleted = {'v_line':i}
        for i, h_line in enumerate(hor_lines_in_img):
            dist = np.sqrt((h_line['x']*scale - x)**2 + (h_line['y']*scale - y)**2)
            if dist < min_distance:
                min_distance = dist
                element_to_be_deleted = {'h_line':i}
        # Delete closest element to point clicked
        for element, position in element_to_be_deleted.items():
            if element == 'rectangle':
                del(rectangles_in_img[position])
                print('Deleted a rectangle.')
            elif element == 'v_line':
                del(ver_lines_in_img[position])
                print('Deleted a vertical line.')
            elif element == 'h_line':
                del(hor_lines_in_img[position])
                print('Deleted a horizontal line.')
        # Re-create image from scratch without deleted element
        img_resized = image_clear_all.copy()
        for rectangle in rectangles_in_img:
            p1 = int(rectangle['x']*scale), int(rectangle['y']*scale)
            p2 = int((rectangle['x'] + rectangle['w'])*scale), int((rectangle['y'] + rectangle['h'])*scale)
            cv2.rectangle(img_resized, p1, p2, color=(0, 255, 0), thickness=2)
        for v_line in ver_lines_in_img:
            p1 = int(v_line['x']*scale), int(v_line['y']*scale)
            p2 = int(v_line['x']*scale), int((v_line['y'] + v_line['h'])*scale)
            cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
        for h_line in hor_lines_in_img:
            p1 = int(h_line['x']*scale), int(h_line['y']*scale)
            p2 = int((h_line['x'] + h_line['w'])*scale), int(h_line['y']*scale)
            cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
        image_without_last_element = img_resized.copy()
        cv2.imshow(image_name, img_resized)

    # Action to be taken when left mouse button is pressed: start drawing horizontal lines
    elif action==cv2.EVENT_LBUTTONDOWN:
        drawing = 3
        horizontal = True
        hor_line_points = [(x, y)]
        end_point_h_line_temp = []

    # Action to be taken when left mouse button is released
    elif action==cv2.EVENT_LBUTTONUP:
        if rect:
            # record the ending (x, y) coordinates and indicate that drawing operation is finished
            rectangle_points.append((x, y))
            drawing = False
            rect = False
            p1, p2 = rectangle_points
            p1_img = np.array(p1)//scale
            p2_img = np.array(p2)//scale
            rectangle_x = int(p1_img[0])
            rectangle_y = int(p1_img[1])
            rectangle_w = int(p2_img[0] - p1_img[0])
            rectangle_h = int(p2_img[1] - p1_img[1])
            print(f'Rectangle: x={rectangle_x}, y={rectangle_y}, w={rectangle_w}, h={rectangle_h}')
            rectangles_in_img.append({'s':sheet, 'p':page, 'x':rectangle_x, 'y':rectangle_y, 'h':rectangle_h, 'w':rectangle_w})
            last_element_type = 'rectangle'
            image_without_last_element = img_resized.copy()
            cv2.rectangle(img_resized, p1, p2, color=(0, 255, 0), thickness=2)
            cv2.imshow(image_name, img_resized)
        
        elif horizontal:
            # record the ending (x, y) coordinates and indicate that drawing operation is finished
            hor_line_points.append((x, hor_line_points[0][1]))
            drawing = False
            horizontal = False
            p1, p2 = hor_line_points
            p1_img = np.array(p1)//scale
            p2_img = np.array(p2)//scale
            line_x = int(p1_img[0])
            line_y = int(p1_img[1])
            line_w = int(p2_img[0] - p1_img[0])
            line_h = line_width
            print(f'Horizontal line: x={line_x}, y={line_y}, w={line_w}, h={line_h}')
            hor_lines_in_img.append({'s':sheet, 'p':page, 'x':line_x, 'y':line_y, 'h':line_h, 'w':line_w})
            image_without_last_element = img_resized.copy()
            cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
            last_element_type = 'horizontal'
            cv2.imshow(image_name, img_resized)

    # Action to be taken when right right button is pressed: start drawing vertical line
    elif action==cv2.EVENT_RBUTTONDOWN:
        drawing = 2
        vertical = True
        ver_line_points = [(x, y)]
        end_point_v_line_temp = []
    
    # Action to be taken when left right button is released
    elif action==cv2.EVENT_RBUTTONUP:
        if vertical:
            # record the ending (x, y) coordinates and indicate that drawing operation is finished
            ver_line_points.append((ver_line_points[0][0], y))
            drawing = False
            vertical = False
            p1, p2 = ver_line_points
            p1_img = np.array(p1)//scale
            p2_img = np.array(p2)//scale
            line_x = int(p1_img[0])
            line_y = int(p1_img[1])
            line_w = line_width
            line_h = int(p2_img[1] - p1_img[1])
            print(f'Vertical line: x={line_x}, y={line_y}, w={line_w}, h={line_h}')
            ver_lines_in_img.append({'s':sheet, 'p':page, 'x':line_x, 'y':line_y, 'h':line_h, 'w':line_w})
            image_without_last_element = img_resized.copy()
            cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
            last_element_type = 'vertical'
            cv2.imshow(image_name, img_resized)
    
def parse_args():
    parser=argparse.ArgumentParser()
    parser.add_argument('-f', '--filepath', type=str,
                    help='(Required* arg) Image path. Use "/" to indicate subfolders. If not used, must use -d argument.')
    parser.add_argument('-d', '--dir', type=str,
                    help="(Required* arg) Choose a directory to go through all files ordered by name. If not used, must use -f argument.")
    parser.add_argument('-p', '--page', type=int, help="(Optional arg) Document page.")
    parser.add_argument('-s', '--sheet', type=int, help="(Optional arg) Sheet number.")
    parser.add_argument('-b', '--basedon', type=str,
                    help="(Optional arg) Based on other json file. Parameter to import elements from other json files. Use name of json file.")
    parser.add_argument('-rh', '--resized_height', type=int, default=600,
                    help='(Optional arg) Height of the resized picture that will be drawn to the screen. Default value is 600.')
    parser.add_argument('-lw', '--line_width', type=int, default=3,
                    help='(Optional arg) Width of the lines. Default value is 3.')
    parser.add_argument('-fe', '--file_expression', type=str, default='template',
                    help='(Optional arg) Part of file name that filters files to be shown with left/right arrows. Example: \
                    "template" only searches for files which contains in the file name.')

    if len(sys.argv)==1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args=parser.parse_args()

    return args

def initialize(args, welcome=False):
    if welcome:
        print('Audit Engine -- template_edit.py')
        print('Rectangle boxes: left mouse button + SHIFT.')
        print('Horizontal lines: left mouse button.')
        print('Vertical lines: right mouse button.')
        print('Always draw from top to bottom and left to right.')
        print("Delete closest element by holding CTRL and clicking with right button. Element's origin is used to calculate distance.")
        print("Press 'backspace' to remove last element drawn.")
        print("Press 'c' to remove all elements from image.")
        print("Press 'w' to save a json file or ESC to quit.")
        print("Press 'f' to open another image file using its own elements, if json file exists, or elements from current image.")
        print("Press 'b' to choose a json file and loads its elements to current image.")
        print('Press left and right arrows to navigate through images from a directory. Must use -d parameter.')
        print('Press up and down arrows to navigate through json files from a directory and find templates for images. Must use -d parameter.')
        print("Press '-' to reduce image zoom.")
        print("Press '+' to increase image zoom.")

    # Check if user wants to use a whole directory of images or just a single image
    if args.dir is not None and args.filepath is None:
        dir_files = sorted([os.path.normpath(f) for f in glob.glob(f'{args.dir}/*.png') if expression in f])
        image_path = dir_files[0]
        image_name = os.path.normpath(image_path).split(os.sep)[-1]
        json_name = image_name.split('.')[0] + '.json'
    elif args.dir is not None:
        dir_files = sorted([os.path.normpath(f) for f in glob.glob(f'{args.dir}/*.png') if expression in f])
        image_path = r'{}'.format(args.filepath)
        image_name = os.path.normpath(image_path).split(os.sep)[-1]
        json_name = image_name.split('.')[0] + '.json'
    else:
        # Path to your image
        # image_path = "./00030_00500_000094-1.png"
        image_path = r'{}'.format(args.filepath)
        image_name = os.path.normpath(image_path).split(os.sep)[-1]
        json_name = image_name.split('.')[0] + '.json'
        dir_files = None

    # Document page that will be passed to json file (located on the last digit of json name)
    if args.page is not None:
        page = args.page
    else:
        try:
            page = int(image_name[-1])
            if page > 0:
                page -= 1
        except:
            page = 0
    
    # Sheet number that will be passed to json file (located on the third digit of json name)
    if args.sheet is not None:
        sheet = args.sheet
    else:
        try:
            sheet = int(image_name[2])
            if sheet > 0:
                sheet -= 1
        except:
            sheet = 0
    
    # Sheet number that will be passed to json file (located on the third digit of json name)
    if args.basedon is not None:
        json_name = args.basedon
        json_name = os.path.normpath(json_name).split(os.sep)[-1].split('.')[0]+'.json'

    # Get original image, resized image and the calculated scale
    img, img_resized, scale = read_and_resize(image_path, resized_height)

    return image_name, json_name, page, sheet, dir_files, img, img_resized, scale

def save_json(dir_path, json_name, rects, v_lines, h_lines):
    with open(dir_path+'/'+json_name, 'w', encoding='utf-8') as f:
        data = {
            'rectangles':rectangles_in_img,
            'vertical_lines':ver_lines_in_img,
            'horizontal_lines':hor_lines_in_img
        }
        json.dump(data, f, ensure_ascii=False, indent=4)
    num_elements = len(rectangles_in_img) + len(ver_lines_in_img) + len(hor_lines_in_img)
    print(f'File {json_name} has been saved with {num_elements} elements.')

if __name__ == '__main__':
    # Get screen size
    user32 = ctypes.windll.user32
    screensize = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    print('Screen size: ', screensize)
    resized_height = screensize[1] - 75 # The image will be loaded based on the screen height

    args = parse_args()

    expression = args.file_expression # use 'template' or 'redline' to change the file you want to look for in the folder

    # Value that will be written on json files for vertical and horizontal lines
    line_width = args.line_width
    
    image_name, json_name, page, sheet, dir_files, img, img_resized, scale = initialize(args, welcome=True)

    if args.dir is not None:
        dir_path = args.dir
    else:
        dir_path = str(Path(args.filepath).parent)

    if dir_files is not None:
        dir_position = 0 # Flag to start reading first element from dir_files

    rectangles_in_img = [] # All the rectangles converted to the original image points
    ver_lines_in_img = [] # All the vertical lines converted to the original image points
    hor_lines_in_img = [] # All the horizontal lines converted to the original image points
    end_point_rect_temp = [] # Temporary point to draw rectangle moving the mouse
    end_point_v_line_temp = [] # Temporary point to draw vertical line moving the mouse
    end_point_h_line_temp = [] # Temporary point to draw horizontal line moving the mouse
    rectangle_points = [] # Stores points of newest rectangle
    ver_line_points = [] # Stores points of newest vertical line
    hor_line_points = [] # Stores points of newest horizontal line
    drawing = False # Indicates whether the user is drawing on the picture
    vertical = False # Flag to indicate vertical line is being drawn
    horizontal = False # Flag to indicate horizontal line is being drawn
    rect = False # Flag to indicate rectangle is being drawn
    image_without_last_element = img_resized.copy() # Copy of the image without last element added
    image_clear_all = img_resized.copy() # Holds copy of a clear image to load if user wants to clear all elements
    last_element_type = None # Type of last element added
    arrow_key_counter = 0 # +1 for up arrow and -1 for down arrow
    json_files = sorted(glob.glob(os.path.normpath(f'{dir_path}/*.json'))) # Sorted list of json files in the folder

    if glob.glob(dir_path+'/'+json_name): # Checking if json already exists
        with open(dir_path+'/'+json_name, 'r', encoding='utf-8') as f:
            data = json.load(f)
        rectangles_in_img = data['rectangles']
        ver_lines_in_img = data['vertical_lines']
        hor_lines_in_img = data['horizontal_lines']
    for rectangle in rectangles_in_img:
        rectangle['p'] = page
        rectangle['s'] = sheet
        p1 = int(rectangle['x']*scale), int(rectangle['y']*scale)
        p2 = int((rectangle['x'] + rectangle['w'])*scale), int((rectangle['y'] + rectangle['h'])*scale)
        cv2.rectangle(img_resized, p1, p2, color=(0, 255, 0), thickness=2)
    for v_line in ver_lines_in_img:
        v_line['p'] = page
        v_line['s'] = sheet
        p1 = int(v_line['x']*scale), int(v_line['y']*scale)
        p2 = int(v_line['x']*scale), int((v_line['y'] + v_line['h'])*scale)
        cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
    for h_line in hor_lines_in_img:
        h_line['p'] = page
        h_line['s'] = sheet
        p1 = int(h_line['x']*scale), int(h_line['y']*scale)
        p2 = int((h_line['x'] + h_line['w'])*scale), int(h_line['y']*scale)
        cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)

    image_without_last_element = img_resized.copy()

    # If -b parameter was used, update json_name to refer to right image and delete args.baseon
    if image_name != json_name[:-5]:
        json_name = image_name.split('.')[0] + '.json'
        args.basedon = None

    # highgui function called when mouse events occur
    cv2.namedWindow(image_name)
    window_position = cv2.getWindowImageRect(image_name)
    cv2.setMouseCallback(image_name, draw)
    
    # loop until ESC is pressed
    k = 0
    while k != 27 and cv2.getWindowProperty(image_name, 0) >= 0:
        if not drawing:
            cv2.imshow(image_name, img_resized)
            window_position = list(cv2.getWindowImageRect(image_name))
            window_position[0] -= 9
            window_position[1] -= 30

        # Drawing rectangle while the mouse is being moved 
        elif drawing == 1 and end_point_rect_temp:
            dummy = img_resized.copy()
            start_point_rect = rectangle_points[0]
            end_point_rect = end_point_rect_temp[0]
            cv2.rectangle(dummy, start_point_rect, end_point_rect, (0,255,0), 1)
            cv2.imshow(image_name, dummy)

        # Drawing vertical line while the mouse is being moved
        elif drawing == 2 and end_point_v_line_temp:
            dummy = img_resized.copy()
            start_point_v_line = ver_line_points[0]
            end_point_v_line = end_point_v_line_temp[0]
            cv2.line(dummy, start_point_v_line, end_point_v_line, (255,0,0), 1)
            cv2.imshow(image_name, dummy)
        
        # Drawing horizontal line while the mouse is being moved
        elif drawing == 3 and end_point_h_line_temp:
            dummy = img_resized.copy()
            start_point_h_line = hor_line_points[0]
            end_point_h_line = end_point_h_line_temp[0]
            cv2.line(dummy, start_point_h_line, end_point_h_line, (255,0,0), 1)
            cv2.imshow(image_name, dummy)

        k = cv2.waitKeyEx(20)

        # 'W' key to generate json file
        if k == 119:
            save_json(dir_path, json_name, rectangles_in_img, ver_lines_in_img, hor_lines_in_img)
                
        # BACKSPACE key to exclude last element
        elif k == 8:
            num_elements = len(rectangles_in_img) + len(ver_lines_in_img) + len(hor_lines_in_img)
            if num_elements > 0:
                img_resized = image_without_last_element.copy()
                if last_element_type == 'rectangle':
                    rectangles_in_img.pop()
                    last_element_type = 0
                    print(f'Removed last rectangle.')
                elif last_element_type == 'vertical':
                    ver_lines_in_img.pop()
                    last_element_type = 0
                    print(f'Removed last vertical line.')
                elif last_element_type == 'horizontal':
                    hor_lines_in_img.pop()
                    last_element_type = 0
                    print(f'Removed last horizontal line.')
                elif last_element_type is None: # Initial case
                    print('It is not possible to delete imported elements from json files.')
                else:
                    print("It is only allowed to go back 1 step. To clear all elements press 'c'.")
                    warnings.warn("It is only allowed to go back 1 step. To clear all elements press 'c'.")
            else:
                print('There is no element to be deleted.')
            cv2.imshow(image_name, img_resized)
        
        # 'b' key to choose a json file and load its elements to current image
        elif k == 98:
            new_json = input('Choose json file to load its elements: ')
            if glob.glob(new_json): # Checking if json already exists
                img_resized = image_clear_all.copy()
                with open(new_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    rectangles_in_img = data['rectangles']
                    ver_lines_in_img = data['vertical_lines']
                    hor_lines_in_img = data['horizontal_lines']
                for rectangle in rectangles_in_img:
                    rectangle['p'] = page
                    rectangle['s'] = sheet
                    p1 = int(rectangle['x']*scale), int(rectangle['y']*scale)
                    p2 = int((rectangle['x'] + rectangle['w'])*scale), int((rectangle['y'] + rectangle['h'])*scale)
                    cv2.rectangle(img_resized, p1, p2, color=(0, 255, 0), thickness=2)
                for v_line in ver_lines_in_img:
                    v_line['p'] = page
                    v_line['s'] = sheet
                    p1 = int(v_line['x']*scale), int(v_line['y']*scale)
                    p2 = int(v_line['x']*scale), int((v_line['y'] + v_line['h'])*scale)
                    cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
                for h_line in hor_lines_in_img:
                    h_line['p'] = page
                    h_line['s'] = sheet
                    p1 = int(h_line['x']*scale), int(h_line['y']*scale)
                    p2 = int((h_line['x'] + h_line['w'])*scale), int(h_line['y']*scale)
                    cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
            else:
                print(f"Couldn't find file {new_json}.")
            cv2.imshow(image_name, img_resized)
            image_without_last_element = img_resized.copy()

        # 'c' key to clear all elements from the image
        elif k == 99:
            img_resized = image_clear_all.copy()
            rectangles_in_img = []
            ver_lines_in_img = []
            hor_lines_in_img = []
            cv2.imshow(image_name, img_resized)
        
        # 'f' key to open a new image and use elements from its json file, if found, or elements from previous image
        elif k == 102:
            new_image_path = input('Choose new image: ')
            cv2.destroyWindow(image_name) # Uncomment line to automatically destroy old image window
            args.filepath = new_image_path
            image_name, json_name, page, sheet, dir_files, img, img_resized, scale = initialize(args)
            image_without_last_element = img_resized.copy()
            image_clear_all = img_resized.copy()
            cv2.namedWindow(image_name)
            cv2.setMouseCallback(image_name, draw)
            if glob.glob(dir_path+'/'+json_name): # Checking if json already exists
                with open(dir_path+'/'+json_name, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                rectangles_in_img = data['rectangles']
                ver_lines_in_img = data['vertical_lines']
                hor_lines_in_img = data['horizontal_lines']
            for rectangle in rectangles_in_img:
                rectangle['p'] = page
                rectangle['s'] = sheet
                p1 = int(rectangle['x']*scale), int(rectangle['y']*scale)
                p2 = int((rectangle['x'] + rectangle['w'])*scale), int((rectangle['y'] + rectangle['h'])*scale)
                cv2.rectangle(img_resized, p1, p2, color=(0, 255, 0), thickness=2)
            for v_line in ver_lines_in_img:
                v_line['p'] = page
                v_line['s'] = sheet
                p1 = int(v_line['x']*scale), int(v_line['y']*scale)
                p2 = int(v_line['x']*scale), int((v_line['y'] + v_line['h'])*scale)
                cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
            for h_line in hor_lines_in_img:
                h_line['p'] = page
                h_line['s'] = sheet
                p1 = int(h_line['x']*scale), int(h_line['y']*scale)
                p2 = int((h_line['x'] + h_line['w'])*scale), int(h_line['y']*scale)
                cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
            cv2.imshow(image_name, img_resized)
            cv2.moveWindow(image_name, window_position[0], window_position[1])
        
        # Right arrow key to go to the next image in a directory. Must use -d argument.
        elif k == 2555904 and dir_files is not None:
            # Save json of current file after pressing right arrow
            # save_json(dir_path, json_name, rectangles_in_img, ver_lines_in_img, hor_lines_in_img)

            # Update list of json files
            json_files = sorted(glob.glob(os.path.normpath(f'{dir_path}/*.json')))

            # Reset arrow_key_counter
            arrow_key_counter = 0

            if dir_position < len(dir_files) - 1:
                dir_position += 1
                args.filepath = dir_files[dir_position]
            else:
                warnings.warn("This is the last file of this directory.")
                print("This is the last file of this directory.")
                continue
            
            cv2.destroyWindow(image_name) # Uncomment line to automatically destroy old image window
            image_name, json_name, page, sheet, dir_files, img, img_resized, scale = initialize(args)
            image_without_last_element = img_resized.copy()
            image_clear_all = img_resized.copy()
            cv2.namedWindow(image_name)
            cv2.setMouseCallback(image_name, draw)
            if glob.glob(dir_path+'/'+json_name): # Checking if json already exists
                with open(dir_path+'/'+json_name, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                rectangles_in_img = data['rectangles']
                ver_lines_in_img = data['vertical_lines']
                hor_lines_in_img = data['horizontal_lines']
            else:
                print(f'{json_name} not found. Using settings from prior file.')
            for rectangle in rectangles_in_img:
                rectangle['p'] = page
                rectangle['s'] = sheet
                p1 = int(rectangle['x']*scale), int(rectangle['y']*scale)
                p2 = int((rectangle['x'] + rectangle['w'])*scale), int((rectangle['y'] + rectangle['h'])*scale)
                cv2.rectangle(img_resized, p1, p2, color=(0, 255, 0), thickness=2)
            for v_line in ver_lines_in_img:
                v_line['p'] = page
                v_line['s'] = sheet
                p1 = int(v_line['x']*scale), int(v_line['y']*scale)
                p2 = int(v_line['x']*scale), int((v_line['y'] + v_line['h'])*scale)
                cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
            for h_line in hor_lines_in_img:
                h_line['p'] = page
                h_line['s'] = sheet
                p1 = int(h_line['x']*scale), int(h_line['y']*scale)
                p2 = int((h_line['x'] + h_line['w'])*scale), int(h_line['y']*scale)
                cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
            cv2.imshow(image_name, img_resized)
            cv2.moveWindow(image_name, window_position[0], window_position[1])
        
        # Left arrow key to go to the previous image in a directory. Must use -d argument.
        elif k == 2424832 and dir_files is not None:
            # Save json of current file after pressing left arrow
            # save_json(dir_path, json_name, rectangles_in_img, ver_lines_in_img, hor_lines_in_img)

            # Update list of json files
            json_files = sorted(glob.glob(os.path.normpath(f'{dir_path}/*.json')))

            # Reset arrow_key_counter
            arrow_key_counter = 0

            if dir_position > 0:
                dir_position -= 1
                args.filepath = dir_files[dir_position]
            else:
                warnings.warn("This is the first file of this directory.")
                print("This is the first file of this directory.")
                continue

            cv2.destroyWindow(image_name) # Uncomment line to automatically destroy old image window
            image_name, json_name, page, sheet, dir_files, img, img_resized, scale = initialize(args)
            image_without_last_element = img_resized.copy()
            image_clear_all = img_resized.copy()
            cv2.namedWindow(image_name)
            cv2.setMouseCallback(image_name, draw)
            if glob.glob(dir_path+'/'+json_name): # Checking if json already exists
                with open(dir_path+'/'+json_name, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                rectangles_in_img = data['rectangles']
                ver_lines_in_img = data['vertical_lines']
                hor_lines_in_img = data['horizontal_lines']
            for rectangle in rectangles_in_img:
                rectangle['p'] = page
                rectangle['s'] = sheet
                p1 = int(rectangle['x']*scale), int(rectangle['y']*scale)
                p2 = int((rectangle['x'] + rectangle['w'])*scale), int((rectangle['y'] + rectangle['h'])*scale)
                cv2.rectangle(img_resized, p1, p2, color=(0, 255, 0), thickness=2)
            for v_line in ver_lines_in_img:
                v_line['p'] = page
                v_line['s'] = sheet
                p1 = int(v_line['x']*scale), int(v_line['y']*scale)
                p2 = int(v_line['x']*scale), int((v_line['y'] + v_line['h'])*scale)
                cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
            for h_line in hor_lines_in_img:
                h_line['p'] = page
                h_line['s'] = sheet
                p1 = int(h_line['x']*scale), int(h_line['y']*scale)
                p2 = int((h_line['x'] + h_line['w'])*scale), int(h_line['y']*scale)
                cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
            cv2.imshow(image_name, img_resized)
            cv2.moveWindow(image_name, window_position[0], window_position[1])

        # Up arrow key to go to choose previous json file in the directory. Must use -d argument.
        elif k == 2490368 and dir_files is not None:
            if len(json_files) >= 1:
                # Checking if json file associated with current image already exists
                json_for_image = os.path.normpath(f'{dir_path}/{image_name.split(".")[0]}.json')
                if json_for_image in json_files:
                    current_json_index = json_files.index(json_for_image)
                    if current_json_index == 0 and arrow_key_counter >= 0:
                        warnings.warn('You are already using the first json file of this folder.')
                        print("You are already using the first json file of this folder.")
                        continue
                    else:
                        if current_json_index - arrow_key_counter == 0:
                            warnings.warn('You are already using the first json file of this folder.')
                            print("You are already using the first json file of this folder.")
                            continue
                        else:
                            arrow_key_counter += 1
                            json_path = json_files[current_json_index - arrow_key_counter]
                else:
                    current_image_index = dir_files.index(os.path.normpath(f'{dir_path}/{image_name}'))

                    # Edge condition: image without json to the start of the folder. This 'if' allows to go back to previous after going to next.
                    if current_image_index == 0 and arrow_key_counter < -1:
                        edge_condition = True
                        json_path = json_files[-arrow_key_counter-2]
                        arrow_key_counter += 1
                    else:
                        for image_path in sorted(dir_files[:current_image_index], reverse=True):
                            previous_json = f'{image_path.split(".")[0]}.json'
                            # print(previous_json)
                            edge_condition = False
                            if previous_json in json_files:
                                previous_json_index = json_files.index(previous_json)
                                # print(previous_json_index)
                                break

                        else: # If for loop ends without finding previous json or hitting edge condition, it means we are seeing the first json.
                            warnings.warn('You are already using the first json file of this folder.')
                            print("You are already using the first json file of this folder.")
                            continue
                        
                        if not edge_condition:
                            if previous_json_index - arrow_key_counter == 0:
                                warnings.warn('You are already using the first json file of this folder.')
                                print("You are already using the first json file of this folder.")
                                continue
                            else:
                                arrow_key_counter += 1
                                json_path = json_files[previous_json_index - arrow_key_counter]

                img_resized = image_clear_all.copy()

                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    rectangles_in_img = data['rectangles']
                    ver_lines_in_img = data['vertical_lines']
                    hor_lines_in_img = data['horizontal_lines']

                for rectangle in rectangles_in_img:
                    rectangle['p'] = page
                    rectangle['s'] = sheet
                    p1 = int(rectangle['x']*scale), int(rectangle['y']*scale)
                    p2 = int((rectangle['x'] + rectangle['w'])*scale), int((rectangle['y'] + rectangle['h'])*scale)
                    cv2.rectangle(img_resized, p1, p2, color=(0, 255, 0), thickness=2)

                for v_line in ver_lines_in_img:
                    v_line['p'] = page
                    v_line['s'] = sheet
                    p1 = int(v_line['x']*scale), int(v_line['y']*scale)
                    p2 = int(v_line['x']*scale), int((v_line['y'] + v_line['h'])*scale)
                    cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)

                for h_line in hor_lines_in_img:
                    h_line['p'] = page
                    h_line['s'] = sheet
                    p1 = int(h_line['x']*scale), int(h_line['y']*scale)
                    p2 = int((h_line['x'] + h_line['w'])*scale), int(h_line['y']*scale)
                    cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)

                cv2.imshow(image_name, img_resized)
                image_without_last_element = img_resized.copy()

            else:
                print('No json files were found.')

        # Down arrow key to go to choose next json file in the directory. Must use -d argument.
        elif k == 2621440 and dir_files is not None:
            if len(json_files) >= 1:
                # Checking if json file associated with current image already exists
                json_for_image = os.path.normpath(f'{dir_path}/{image_name.split(".")[0]}.json')
                if json_for_image in json_files:
                    current_json_index = json_files.index(json_for_image)
                    if current_json_index == len(json_files) - 1 and arrow_key_counter <= 0:
                        warnings.warn('You are already using the last json file of this folder.')
                        print("You are already using the last json file of this folder.")
                        continue
                    else:
                        if current_json_index - arrow_key_counter == len(json_files) - 1:
                            warnings.warn('You are already using the last json file of this folder.')
                            print("You are already using the last json file of this folder.")
                            continue
                        else:
                            arrow_key_counter -= 1
                            json_path = json_files[current_json_index - arrow_key_counter]
                else:
                    current_image_index = dir_files.index(os.path.normpath(f'{dir_path}/{image_name}'))

                    # Edge condition: image without json added at the end of folder. This 'if' allows to go back to next after going to previous.
                    if arrow_key_counter >= 1:
                        edge_condition = True
                        json_path = json_files[-arrow_key_counter]
                        arrow_key_counter -= 1
                    else:
                        for image_path in dir_files[current_image_index+1:]:
                            next_json = f'{image_path.split(".")[0]}.json'
                            edge_condition = False
                            if next_json in json_files:
                                next_json_index = json_files.index(next_json)
                                break
                        else: # If for loop ends without finding next jsonm it means we are seeing the last json.
                            warnings.warn('You are already using the last json file of this folder.')
                            print("You are already using the last json file of this folder.")
                            continue
                        
                        if not edge_condition:
                            if next_json_index - arrow_key_counter == len(json_files):
                                warnings.warn('You are already using the last json file of this folder.')
                                print("You are already using the last json file of this folder.")
                                continue
                            else:
                                json_path = json_files[next_json_index - arrow_key_counter]
                                arrow_key_counter -= 1

                img_resized = image_clear_all.copy()

                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    rectangles_in_img = data['rectangles']
                    ver_lines_in_img = data['vertical_lines']
                    hor_lines_in_img = data['horizontal_lines']

                for rectangle in rectangles_in_img:
                    rectangle['p'] = page
                    rectangle['s'] = sheet
                    p1 = int(rectangle['x']*scale), int(rectangle['y']*scale)
                    p2 = int((rectangle['x'] + rectangle['w'])*scale), int((rectangle['y'] + rectangle['h'])*scale)
                    cv2.rectangle(img_resized, p1, p2, color=(0, 255, 0), thickness=2)

                for v_line in ver_lines_in_img:
                    v_line['p'] = page
                    v_line['s'] = sheet
                    p1 = int(v_line['x']*scale), int(v_line['y']*scale)
                    p2 = int(v_line['x']*scale), int((v_line['y'] + v_line['h'])*scale)
                    cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)

                for h_line in hor_lines_in_img:
                    h_line['p'] = page
                    h_line['s'] = sheet
                    p1 = int(h_line['x']*scale), int(h_line['y']*scale)
                    p2 = int((h_line['x'] + h_line['w'])*scale), int(h_line['y']*scale)
                    cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
            else:
                print('No json files were found.')
            cv2.imshow(image_name, img_resized)
            image_without_last_element = img_resized.copy()

        
        # '-' key to decrease image size.
        elif k == 45:
            cv2.destroyWindow(image_name) # Uncomment line to automatically destroy old image window
            resized_height *= 0.9
            image_name, _, page, sheet, dir_files, img, img_resized, scale = initialize(args)
            image_without_last_element = img_resized.copy()
            image_clear_all = img_resized.copy()
            cv2.namedWindow(image_name)
            cv2.setMouseCallback(image_name, draw)
            if glob.glob(dir_path+'/'+json_name): # Checking if json already exists
                with open(dir_path+'/'+json_name, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                rectangles_in_img = data['rectangles']
                ver_lines_in_img = data['vertical_lines']
                hor_lines_in_img = data['horizontal_lines']
            for rectangle in rectangles_in_img:
                rectangle['p'] = page
                rectangle['s'] = sheet
                p1 = int(rectangle['x']*scale), int(rectangle['y']*scale)
                p2 = int((rectangle['x'] + rectangle['w'])*scale), int((rectangle['y'] + rectangle['h'])*scale)
                cv2.rectangle(img_resized, p1, p2, color=(0, 255, 0), thickness=2)
            for v_line in ver_lines_in_img:
                v_line['p'] = page
                v_line['s'] = sheet
                p1 = int(v_line['x']*scale), int(v_line['y']*scale)
                p2 = int(v_line['x']*scale), int((v_line['y'] + v_line['h'])*scale)
                cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
            for h_line in hor_lines_in_img:
                h_line['p'] = page
                h_line['s'] = sheet
                p1 = int(h_line['x']*scale), int(h_line['y']*scale)
                p2 = int((h_line['x'] + h_line['w'])*scale), int(h_line['y']*scale)
                cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
            cv2.imshow(image_name, img_resized)
            cv2.moveWindow(image_name, window_position[0], window_position[1])

        # '+' key to increase image size.
        elif k == 43:
            cv2.destroyWindow(image_name) # Uncomment line to automatically destroy old image window
            resized_height /= 0.9
            image_name, _, page, sheet, dir_files, img, img_resized, scale = initialize(args)
            image_without_last_element = img_resized.copy()
            image_clear_all = img_resized.copy()
            cv2.namedWindow(image_name)
            cv2.setMouseCallback(image_name, draw)
            if glob.glob(dir_path+'/'+json_name): # Checking if json already exists
                with open(dir_path+'/'+json_name, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                rectangles_in_img = data['rectangles']
                ver_lines_in_img = data['vertical_lines']
                hor_lines_in_img = data['horizontal_lines']
            for rectangle in rectangles_in_img:
                rectangle['p'] = page
                rectangle['s'] = sheet
                p1 = int(rectangle['x']*scale), int(rectangle['y']*scale)
                p2 = int((rectangle['x'] + rectangle['w'])*scale), int((rectangle['y'] + rectangle['h'])*scale)
                cv2.rectangle(img_resized, p1, p2, color=(0, 255, 0), thickness=2)
            for v_line in ver_lines_in_img:
                v_line['p'] = page
                v_line['s'] = sheet
                p1 = int(v_line['x']*scale), int(v_line['y']*scale)
                p2 = int(v_line['x']*scale), int((v_line['y'] + v_line['h'])*scale)
                cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
            for h_line in hor_lines_in_img:
                h_line['p'] = page
                h_line['s'] = sheet
                p1 = int(h_line['x']*scale), int(h_line['y']*scale)
                p2 = int((h_line['x'] + h_line['w'])*scale), int(h_line['y']*scale)
                cv2.line(img_resized, p1, p2, color=(255, 0, 0), thickness=2)
            cv2.imshow(image_name, img_resized)
            cv2.moveWindow(image_name, window_position[0], window_position[1])
            
    cv2.destroyAllWindows()
    print('Goodbye! Have an awesome day!')