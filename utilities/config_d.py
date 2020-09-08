import os
from string import Template


#UPLOAD_BUCKET   = "co-audit-engine"
#UNZIPPED_BUCKET = "co-audit-engine-input"

MOCK_LAMBDA = False

config_dict = {
    'STORE_TYPE': 'local',
    # 'RESOURCES_PATH': 'resources/',
    # 'STYLES_PATHFRAG': 'styles/',
    # 'RESULTS_PATHFRAG': 'results/',
    # 'AUDITCVR_PATHFRAG': 'auditcvr/',
    # 'SUMMARY_PATHFRAG': 'summary/',
    # 'ASSIST_PATHFRAG': 'assist/',
    # 'TEMPLATE_TASKS_PATHFRAG': 'template_tasks/',
    # 'EXTRACTION_TASKS_PATHFRAG': 'extraction_tasks/',
    # 'BIF_TASKS_PATHFRAG': 'bif_tasks/',
    # 'REPORTS_PATHFRAG': 'reports/',
    # 'DISAGREEMENTS_PATHFRAG': 'disagreements/',
    # 'OVERVOTES_PATHFRAG': 'overvotes/',
    # 'BLANK_BALLOTS_PATHFRAG': 'blank_ballots/',
    # 'FUZZY_MATCH_PATHFRAG': 'fuzzy matches/',
    # 'ROIS_PATHFRAG': 'rois/',
    # 'BIF_PATHFRAG': 'bif/',
    # 'TMP_PATHFRAG': 'tmp/',
    
    'CVR_STYLE_TO_CONTESTS_DICT_FILENAME' : 'CVR_STYLE_TO_CONTESTS_DICT',
    'CVR_BALLOTID_TO_STYLE_DICT_FILENAME' : 'CVR_BALLOTID_TO_STYLE_DICT',

    'SCRAPER_PATHFRAG': 'scraper/',
    'STYLE_DICT_PATHFRAG': 'style_dict/',
    'MAJOR_RELEASE': '1',
    'MINOR_RELEASE': '4',
    'PRECINCT_FOLDER': 0,
    'PARTY_FOLDER': 1,
    'EIF_PATH': '',
    'CODE_CHECKSUM': 50,

    'VERBOSE': 1,

    'SKIPPED_NUM': 0,
    'LIMITED_NUM': 0,

    'CHECKBOX_BORDER_WIDTH': 2,
    'LAYERS_FOR_EMPTY_BALLOT': 50,
    'INITIAL_SEARCH_VALUES': 10000,
    'CODE_MEAN_OFFSET': 40.0,
    'BALLOT_LEFT_PART_BORDER': 1700,
    'CHECK_EVERY_NTH_POINT': 1,
    'STD_RANGE': 50,
    'THRESHOLD_MULTIPLIER': 1,
    
    'EXPRESSVOTE_BALLOT_FILESIZE_THRESHOLD': 25_000,

    'ALIGNED_RESOLUTION': {"x": 1728, "y": 2832},

    'THRESHOLD': {
        "code-contours": 250,
        "frame-contours": 250,
        "code": 700,
        "result-contours": 170,
        "ballot-contours": 150,
        "option-contours": 254,
        "contest-contours": 170,
        "checkbox-filled": 115.12,
        },

    'MARK_THRESHOLD': {
        "marginal": 10,
        "definite": 15,
        },
        
    'fuzzy_thres': {
        'contest':  0.60,   # this threshold used only when contests have no options except writeins
        'options':  0.75,
        'descr':    0.80,
        'writeins': 0.80,
        },

    'PIXEL_THRESHOLD': {
        "marginal": 220,
        "definite": 245,
        },

    'SHAPE_APPROX_VALUE': {
        "code": 0.1,
        "other": 0.01
        },

    'NUMBER_ROI': {
        "y": 40,
        "x": 1500,
        "h": 100,
        "w": 200
        },

    'CODE_ROI': {
        "y": 40,
        "x": 0,
        "y'": 2800,
        "x'": 35,
        "min-size": 250,
        "max-size": 1200,
        "mean": 70,
        },

    'EDGES_ROI': {
        "left-border": 250,
        "right-border": 1450,
        "top-border": 250,
        "bottom-border": 2250
        },

    'CONTEST_ROI': {
        "ratio-min": 2,
        "ratio-max": 14,
        "mean": 180,
        },

    'QUESTION_ROI': {
        "ratio-min": 0.1,
        "ratio-max": 2.5,
        "mean": 180,
        },

    # total height of option area (ES&S) is 54 (Dane County)
    # min checkbox dimensions will allow capture of rectagular area
    # when contours fail to find a checkbox area.
    # w,h dimensions of the rectangle of interest is 35 x 24 = 840 pixels
    # minimum-width printed oval is 72 pixels.

    'RESULT_ROI': {
        "ratio-min": 7,
        "mean": 200,
        "checkbox-mean": 243,
        "checkbox-x": 5,
        "checkbox-y": 5,
        "checkbox-x'": 60,
        "checkbox-y'": 40,
        "min-target-x1": 16,
        "min-target-y1": 15,
        "min-target-x2": 16+35,
        "min-target-y2": 15+24,
        "min-ellipse-sides": 8,
        },
    'TESSERACT_PATH': os.environ.get('TESSERACT_PATH', 'HOME')
    }
    
config_dict['LOGO'] = Template("""
citizens oversight_ _ _
                 | (_) |
   __ _ _   _  __| |_| |_
  / _` | | | |/ _` | | __|
 | (_| | |_| | (_| | | |_
  \\__,_|\\__,_|\\__,_|_|\\__|
                  (_)
   ___ _ __   __ _ _ _ __   ___
  / _ \\ '_ \\ / _` | | '_ \\ / _ \\
 |  __/ | | | (_| | | | | |  __/
  \\___|_| |_|\\__, |_|_| |_|\\___|
              __/ |
             |___/  version: 0.$MAJOR.$MINOR
""").substitute(MAJOR=config_dict['MAJOR_RELEASE'], MINOR=config_dict['MINOR_RELEASE'])


config_dict['STYLE_LEFTOVER'] = Template("""
-------------------------------------------------------------------------------
Found $STYLE_COUNT unrecognized style(s) for $STYLE_ID
Generating new style from discovery queue... OK
Moving discovery queue to process queue... OK
-------------------------------------------------------------------------------
""")

config_dict['SUMMARY_SCREEN'] = Template("""
-------------------------------------------------------------------------------
Generating the HTML Summary file... Done!
Summary file path:
$SUMMARY_FILE_PATH
-------------------------------------------------------------------------------
Run status: OK
Execution time: $TIME_TAKEN
""")

global LAYOUT_PARAMS_DICT
LAYOUT_PARAMS_DICT = {}




def refresh_resources_paths(self, resources_path):
    """
    Takes a new 'resources_path' and rewrites
    all file paths related to the resources.
    """
    resources_path = resources_path if resources_path.endswith('/') else f'{resources_path}/'

    self.STYLES_PATH = f'{resources_path}styles/'
    self.ROIS_PATH = f'{resources_path}rois/'
    self.RESULTS_PATH = f'{resources_path}results/'
    self.SUMMARY_PATH = f'{resources_path}summary/'
    self.DISAGREEMENTS_PATH = f'{resources_path}disagreements/'
    self.FUZZY_MATCH_PATH = f'{resources_path}fuzzy matches/'
    self.SCRAPER = f'{resources_path}scraper/'
    self.STYLE_DICT = f'{resources_path}style_dict/'
