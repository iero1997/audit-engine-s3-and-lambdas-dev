# test_tess.py -- test tesseract conversion

import os
import re
import sys

import numpy as np
import cv2
import pytesseract



def ocr_text(img: np.array) -> str:
    """
    :param img: an array containing analyzed image
    :return: OCRed text
    
    This mode works well with strings with multiple words or blocks of text
    Does not work reliably for single words.
    
    
    --psm is the page segmentation mode
        0    Orientation and script detection (OSD) only.
        1    Automatic page segmentation with OSD.
        2    Automatic page segmentation, but no OSD, or OCR.
        3    Fully automatic page segmentation, but no OSD. (Default)
        4    Assume a single column of text of variable sizes.
        5    Assume a single uniform block of vertically aligned text.
        6    Assume a single uniform block of text.
        7    Treat the image as a single text line.
        8    Treat the image as a single word.
        9    Treat the image as a single word in a circle.
        10   Treat the image as a single character.
        11   Sparse text. Find as much text as possible in no particular order.
        12   Sparse text with OSD.
        13   Raw line. Treat the image as a single text line,
                bypassing hacks that are Tesseract-specific.
                
    --oem is the ocr engine mode
        0 = Original Tesseract only.
        1 = Neural nets LSTM only.
        2 = Tesseract + LSTM.
        3 = Default, based on what is available.
        
    -l LANG provides the list of languages to be used in the conversion.
                
    """
    text = pytesseract.image_to_string(
        img,
        config='--psm 6 --oem 3 -l eng+spa'
    )
    
    return text

def ungray_area(area_of_interest):
    """ if the mean of a contest block is below 160, then it likely has 
        a gray background which will need addiitional processing to 
        clear it out.
        This also helps when the background is not gray to eliminate
        tesseract strange failures.
    """
    
    gray_background_max_mean = 160
    
    roi_mean = cv2.mean(area_of_interest)[0]
    if True: # roi_mean < gray_background_max_mean:
        # The following should be performed only when the roi has a gray background.
        # utils.sts(f"Larger roi detected. p{p} x{x} y{y} {w} h{h} mean({roi_mean[0]})", 3)
        
        # dilation followed by erosion removes black spots from white areas.
        wht_kernel = np.ones((3, 3), np.uint8)
        for i in range(3):
            area_of_interest = cv2.dilate(area_of_interest, wht_kernel)
            area_of_interest = cv2.erode(area_of_interest, wht_kernel)
            
        # area_of_interest = cv2.threshold(area_of_interest, 170, 255, cv2.THRESH_OTSU)
        ret1, area_of_interest = cv2.threshold(area_of_interest, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)    
    return area_of_interest

def unbold_area(area_of_interest):
    """ if the mean of a contest block is below 160, then it likely has 
        a gray background which will need addiitional processing to 
        clear it out.
    """
    
    wht_kernel = np.ones((3, 3), np.uint8)
    area_of_interest = cv2.dilate(area_of_interest, wht_kernel)
    ret1, area_of_interest = cv2.threshold(area_of_interest, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)    

    return area_of_interest


def main():

    filepath = sys.argv[1]
    
    image = cv2.imread(filepath, 0)
    
    image = ungray_area(image)
    
    text = ocr_text(image)
    
    print (f"OCR result: '{text}'")


if __name__ == '__main__':
    main()
