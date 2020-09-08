import os
import io
import numpy as np
import pandas as pd
from unidecode import unidecode

import pytesseract
#from utilities.config_d import config_dict



pytesseract.pytesseract.tesseract_cmd = os.environ.get('TESSERACT_PATH', 'HOME')

enable_word_logging = False
misspelled_words_set = set()

'''

# comment out the following for lambdas or to disable misspelled word analysis
#from spellchecker import SpellChecker
#spell = SpellChecker()
#spell.word_frequency.load_words(['vaping', 'supermajority', 'cannot', 'counterterrorism', 'vapor-generating', 'wagering', '2nd'])

def log_unknown_words(text: str):
    """ Given a string of text, break it into words
        look up each one and if not found in 50K common words, log it.
        This will help us build OCR spelling corrections.
    """    

    # find those words that may be misspelled
    text = re.sub(r"[^\w\s\-]", '', text, flags=re.S)                      # remove non-word characters
    split_text = re.split(r'\s+', text, flags=re.S)
    for word in split_text:
        if len(word) < 2: continue
        unknown_list = spell.unknown([word])
        if unknown_list:
            misspelled_words_set.add(word)
'''
def log_unknown_words(text: str):
    pass

def log_misspelled_words():
    if enable_word_logging and misspelled_words_set:
        fh = open('resources/misspelled_words.txt', mode='w')
        print( '\n'.join(sorted(list(misspelled_words_set))), sep='\n', end='\n', file=fh)
        fh.close()


pytesseract.pytesseract.tesseract_cmd = os.environ.get('TESSERACT_PATH', 'HOME')

'''
def ocr_core(img: np.array) -> str:
    """
    :param img: an array containing analyzed image
    :return: OCRed text
    Handles the single line core OCR image processing consisting of strings.
    Using Pillow's Image class to open the image and pytesseract to detect
    the string in the image.
    """
    text = pytesseract.image_to_string(img, lang='eng')
    return sanitize_string(text)
'''

def ocr_text(img: np.array, mode: int = 6, tsv: str = '') -> str:
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
        config = f"--psm {mode} --oem 3 -l eng+spa {tsv}"
    )
    text = sanitize_string(text)
    
    if enable_word_logging:
        log_unknown_words(text)
    
    return text
    
def ocr_various_modes(img: np.array) -> dict:
    """ apply various modes to the same image and return list of results
    """
    
    modes = [3, 4, 6]

    result_dict = {}

    for mode in modes:
        text = ocr_text(img, mode)
        result_dict[mode] = text
        
    return result_dict


def ocr_word(img: np.array) -> str:
    """
    :param img: an array containing analyzed image
    :return: OCRed text
    
    This mode works well with single words.
    """
    text = pytesseract.image_to_string(
        img,
        config='--psm 8 --oem 3 -l eng+spa'
    )
    return sanitize_string(text)


def ocr_to_tsv(img):    
    """ given image and region spec, isolate the region and ocr
        return tsv table
        all values are 1-based
        columns:
            level       1-5, allows separate dimensions for each level, page, block, par, line, word
            page_num    always 1 in this application
            block_num   provides text in obvious blocks.
            par_num     tesseract guess at paragraphs 
            line_num    within paragraphs
            word_num    within line
            left        x pixel offset, 0-based. reference point left edge of word
            top         y pixel offset, 0-based. reference point centerline of surrounding box?
            width       w pixel dimension of word, line, par, block, page as indicated.
            height      h pixel dimension of ...
            conf        confidence 0-100
            text        text
            
        example:
        
        level   
            page_num    
                block_num   
                    par_num 
                        line_num    
                            word_num    
                                left    top     width   height  conf    text
        1   1   0   0   0   0   0       0       1728    2832    -1      
        2   1   1   0   0   0   0       54      1337    158     -1  
        3   1   1   1   0   0   0       54      1322    54      -1  
        4   1   1   1   1   0   0       54      1322    54      -1  
        5   1   1   1   1   1   0       54      55      54      44  anil
        5   1   1   1   1   2   407     67      118     29      96  Official
        5   1   1   1   1   3   537     67      197     28      96  Presidential
        5   1   1   1   1   4   746     67      181     28      96  Preference
        5   1   1   1   1   5   938     67      131     36      96  Primary
        5   1   1   1   1   6   1078    67      135     28      96  Election
        5   1   1   1   1   7   1225    67      97      28      96  Ballot
        3   1   1   2   0   0   0       104     1337    70      -1  
        4   1   1   2   1   0   0       104     1337    38      -1  
        5   1   1   2   1   1   0       115     58      27      26  m2
        5   1   1   2   1   2   392     104     105     28      92  Boleta
        5   1   1   2   1   3   508     104     105     28      93  Oficial
        5   1   1   2   1   4   625     104     143     28      92  Eleccion

            
            
        Note:
            requires oem 3
            works with psm 3, 4, 11, 12 -- does not work at all with the other psm modes.
            psm 6 - leaves out some text at the start of the block
            psm 11,12 - sometimes omits lines that are very closely spaced vertically
                        but other times, it includes them, when modes 3,4 do not.
                        performs poorly on words like 'Buttigieg', converted correctly by psm 6, provides 'Buitigi'
                        
                        
            sample: '23042-ocr region_2.png'
                3,4 provides:       'President\n(Vote for One)\n(Vote por Uno)'     [Missing one line!]
                6,11,12 provides:   'President\n(Voie for One)\nPresidente\n(Vote por Uno)'
                
            sample: '23043-ocr region_2.png'
                6 provides:         'Michael Bennet, Michael R. Bloomberg, Cory Booker...'  [Missing Joe Biden]
                3, 11, 12 provides: 'Michael Bennet, Joe Biden, Michael R. Bloomberg, Cory Booker...'
                4 provides:         'Michael Bennet, ode Biden, Michael R. Bloomberg, Cory Booker...' [Joe -> ode]
                
            sample: '13041-ocr region_2.png'
                6       drops first word 'President'
                3, 4, 11, 12       includes first word
            
            does not sanitize ocr strings. See sanitize_ocr_text and sanitize_ocr_text_in_rois_list()


    """
    try:
        tsv_result = pytesseract.image_to_data(img, config='--psm 6 --oem 3 -l eng+spa tsv')
    except Exception as err:
        from utilities import logs
        logs.exception_report(f"Exception encountered in pytesseract.image_to_data() function: {err}")
        return None
    return tsv_result


def ocr_tsv_to_ocrdf(tsv_result):
    """ We may be better served to parse this more simply using split on \t.
    """
    
    if tsv_result:
        try:    
            df_result = pd.read_csv(io.StringIO(tsv_result), sep='\t', quotechar='', quoting=3) # no quoting
        except Exception as err:
            from utilities import logs
            logs.exception_report(f"Exception encountered in converting tsv_result from pytesseract: {err}\n"
                f"pytesseract result:\n {tsv_result}")
            import pdb; pdb.set_trace()
            return None    
        return df_result
    return None


def ocr_core(img):
    """
    Handles the default core OCR image processing by using Pillow's Image
    class to open the image and pytesseract to detect the string in the image.
    """
    return pytesseract.image_to_string(img, lang='eng')


def ocr_core_single(img):
    """
    Handles the single line core OCR image processing consisting of numbers.
    Using Pillow's Image class to open the image and pytesseract to detect
    the string in the image.
    """
    text = pytesseract.image_to_string(
        img,
        lang='eng',
        config='--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789'
    )
    return text


def ocr_core_names(img):
    """
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


def ocr_core_questions(img):
    """
    Handles the single line core OCR image processing consisting of strings.
    Using Pillow's Image class to open the image and pytesseract to detect
    the string in the image.
    """
    text = pytesseract.image_to_string(
        img,
        config='--psm 12 --oem 3'
    )
    return text


def ocr_core_expressvote(img):
    """
    Handles the single line core OCR image processing consisting of strings.
    Using Pillow's Image class to open the image and pytesseract to detect
    the string in the image.
    """
    text = pytesseract.image_to_string(
        img,
        config='--psm 6 --oem 3'
    )
    return text

def sanitize_string(unclean_string: str) -> str:
    """
    Processes string and tries to decode any occurrence of Unicode to ASCII.
    This goes a bit too far in trying to make the string readable, rather than 
    getting rid of unusual characters produced by OCR conversion.
    :param unclean_string: The raw string to be processed.
    :return: Processed clean string.
    """
    return unidecode(unclean_string)
    

if __name__ == '__main__':

    import sys
    import cv2
    
    filepath = sys.argv[1]
    
    image = cv2.imread(filepath, 0)
    
    #image = ungray_area(image)
    
    tsv_str = ocr_to_tsv(image)
    
    print (tsv_str)
    
    #lod = df.to_dict(orient="records")
    #
    #for ocr_dict in lod:
    #    if ocr_dict['conf'] > -1:
    #        print (f"text: {ocr_dict['text']}")


