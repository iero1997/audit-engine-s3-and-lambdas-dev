# image_compare.py image1 image2

import sys
import cv2
import numpy as np

def mse(imageA, imageB):
    # the 'Mean Squared Error' between the two images is the
    # sum of the squared difference between the two images;
    # NOTE: the two images must have the same dimension
    err = np.sum((imageA.astype("float") - imageB.astype("float")) ** 2)
    err /= float(imageA.shape[0] * imageA.shape[1])

    # return the MSE, the lower the error, the more "similar"
    # the two images are
    return err
    

#import pdb; pdb.set_trace()

img1_filename = sys.argv[1]
img2_filename = sys.argv[2]

img1 = cv2.imread(img1_filename, 0)
img2 = cv2.imread(img2_filename, 0)

contours1, _ = cv2.findContours(img1, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
contours2, _ = cv2.findContours(img2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

x_1, y_1, w_1, h_1 = cv2.boundingRect(contours1)
x_2, y_2, w_2, h_2 = cv2.boundingRect(contours2)

print(f"Rect1 = {x_1, y_1, w_1, h_1}")
print(f"Rect2 = {x_2, y_2, w_2, h_2}")

h1, w1 = img1.shape
h2, w2 = img2.shape

max_h = max(h1, h2)
max_w = max(w1, w2)
    
img1_padded = np.pad(img1, pad_width = ((0,max_h - h1), (0,max_w - w1)), constant_values=255)
img2_padded = np.pad(img2, pad_width = ((0,max_h - h2), (0,max_w - w2)), constant_values=255)

metric = mse(img1_padded, img2_padded)

print(f"metric = {metric}")

