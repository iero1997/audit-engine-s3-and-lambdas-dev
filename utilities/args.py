""" args.py 

This module parses job settings from .csv file based on arg_specs.csv

arg_specs.csv has the following columns:

    name:       The name of the setting. Although these are set to be program-identifier compatible strings, the 
                    code universally references these using the more general argsdict['name'] approach. Nevertheless,
                    it reduces error to eliminate spaces and generally avoid cases, but they are case sensitive.
    type:       provides the type as allowed in argparse, with some variation, as follows:
                    str         arbitrary string
                    list        a list of string, but these formed with multiple entries.
                    int         integer
                    bool        boolean, can be True, False, Yes, No, 0, 1 when parsing from CSV file.
    format:     additional formatting options typically applied to str type, as follows:
                    localpath   path on local machine in either windows or posix format.
                    s3path      path to s3 resource using s3://bucket/prefix/basename format.
                    filename    string with extension.
                    regex       regular expression typically where Group[1] will provide the result.
                    json        json format in non-strict format.
                    url         conventional url format
                    csv_list    value is a list of values separated by commas in non-strict format.
    required:   boolean whether parameter is required, default FALSE.
    multi:      boolean, if true, then multiple lines in the settings file can 
                refer to the same name and they will be combined into a list.
                default FALSE
    internal:   not expected to be used in frontend application but still honored in file, for internal use.
                default FALSE
    choices:    list of csv strings, in lenient csv format.
    default:    If not provided, then this is the default. If no default is provided, 
                then argsdict will contain None
                except if the type is 'list', then the default is empty list [].
    help:       the help string that can be displayed in the user interface or via -h CLI request.

    arg_specs.csv will be in the sys_config/ folder of the repo, not in specific job.

"""

#import io
import re
import sys
import argparse
import json
from utilities import utils, logs
from models.DB import DB

#import pandas as pd
#import numpy as np          # only to get np.nan

ARG_SPECS_PATH = 'sys_config/arg_specs.csv'
DESCRIPTION = "Citizens' Oversight: Audit Engine"

argsdict = {}


def get_args():
    """ This function gets settings based on arg_specs.csv
        'schema' file and input file as specified in CLI.
    """
  
    # should probably read system configuration settings here
    
    # get CLI arguments
    argspecs_df     = DB.read_local_csv_to_df(file_path=ARG_SPECS_PATH, user_format=True, silent_error=False)
    argspecs_dod    = utils.df_to_dod(argspecs_df, field='name')    
    cli_argsdict    = get_cli_args_per_argspecs_dod(argspecs_dod, description=DESCRIPTION)

    # job configuration settings
    # input file can be from CLI OR might be provided per API in job folder.
    settings_file_name =  cli_argsdict.get('input')
    
    if settings_file_name:
        # read the settings file and set the value according to the type specified in argspecs_dod.
        inputdict = read_settings_csv_file(
            dirname='input_files', 
            name=settings_file_name, 
            argspecs_dod=argspecs_dod, 
            name_field='argument', 
            value_field='value'
            )
    
        # at this point, inputdict contains arguments passed in input file.
        # cli_argsdict will overwrite those in input file.
        argsdict = {**inputdict, **cli_argsdict}
    else:
        argsdict = cli_argsdict
    
    # now review argspecs to make sure all required records exist and are valid.
    if (not check_args(argsdict, argspecs_dod) or  
        not custom_argsdict_checks(argsdict)):
        sys.exit(1)
    
    return argsdict
    

def read_argspecs_dod(file_path, field='name', user_format=False, silent_error=False):
    """ read csv file and return dod with primary key being field. 
    """
    df      = DB.read_local_csv_to_df(file_path, user_format=False, silent_error=False)
    dod     = utils.df_to_dod(df, field)    
    return dod

    
def get_cli_args_per_argspecs_dod(argspecs_dod, description=None):
    """Get arguments and return them parsed as dict 
        Note: defaults are handled later in the process.
        processes the possible arguments from command line interface
        and does not deal with multi entries.
    """
    
    parser = argparse.ArgumentParser(description=description)
    
    error_flag = False
    for spec_dict in argspecs_dod.values():
        name = spec_dict['name']
        spectype = spec_dict['type']
        if spectype in ['str', 'list']:
            parser_type = str
        elif spec_dict['type'] == 'int':
            parser_type = int
        elif spec_dict['type'] == 'bool':
            parser_type = bool
        else:
            print(f"arg_spec type '{spectype} not recognized for parameter:{name}")
            error_flag = True
        if spec_dict['abbr']:
            parser.add_argument(
                f"-{spec_dict['abbr']}",
                f"--{name}", 
                help=spec_dict['help'],
                type=parser_type,
                )
        else:
            parser.add_argument(
                f"--{name}", 
                help=spec_dict['help'],
                type=parser_type,
                )
    if error_flag:
        sys.exit(1)            
            
    parsed_dict = vars(parser.parse_args())
    cli_dict = {}
    for key, value in parsed_dict.items():
        if value is not None:
            cli_dict[key] = value
            
    return cli_dict


def add_value_of_type(inputdict, name, spec_type, valstr):
    """ given dict of name, value pairs, add valstr of type spec_type at key name """

    if spec_type == 'str':
        inputdict[name] = valstr
        
    elif spec_type == 'int':
        if valstr is None:
            valstr = '0'
        valstr = re.sub(r'[^\+\-\d]', '', valstr)      #remove all non-digits + or -
        if valstr == '': 
            valstr = '0'
        inputdict[name] = int(valstr)
        
    elif spec_type == 'bool':
        try:
            inputdict[name] = utils.str2bool(valstr)
        except Exception as err:
            print(f"parameter {name} not right type, expected bool: {err}")
    elif spec_type == 'list':
        # possibly allow adding csv_list, etc instead of just str.
        if name in inputdict:
            inputdict[name].append(valstr)
        else:
            inputdict[name] = [valstr]
            

def read_settings_csv_file(dirname, name, argspecs_dod, name_field='name', value_field='value'):
    """ reads settings with columns name_field and value_field into dict[name] = value
    """

    inputdict = {}  
    error_flag = False
    if not name:
        return {}

    print(f"Input file specified. Reading input from file '{name}'...")
    
    # need to be able to load from s3 or local.
    settings_df = DB.load_data(dirname='input_files', name=name, format='.csv', user_format=True, s3flag=False)
    
    settings_lod = settings_df.to_dict(orient='records')
    
    for setting_dict in settings_lod:
        name = setting_dict[name_field].strip(' ')
        
        if name not in argspecs_dod:
            print (f"{name_field} '{name}' not supported.")
            error_flag = True
            continue
            
        add_value_of_type(
            inputdict, 
            name=name, 
            spec_type=argspecs_dod[name]['type'], 
            valstr=setting_dict[value_field]
            )
            
    if error_flag:
        sys.exit(1)
            
    return inputdict
    
url_regex = re.compile(
    r'^(?:http|ftp)s?://' # http:// or https://
    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' #domain...
    r'localhost|' #localhost...
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' # ...or ip
    r'(?::\d+)?' # optional port
    r'(?:/?|[/?]\S+)$', re.IGNORECASE)    


def check_one_value(name, val, format):
    """ given one value and format, check format.
        return bool, retval
        bool is False if value violates format.
        else retval is standized value.
    """
    
    retval = val
    format_error = False
    helpstr = ''
    
    if format == 'localpath':
        format_error = bool(val.startswith('s3:') or val.startswith('http'))
        retval = utils.path_sep_per_os(val, sep='/')     # standardize to / no matter what platform
        
    elif format == 's3path':
        format_error = bool(not val.startswith('s3:'))
        
    elif format == 'filename':
        format_error = bool(re.search(r'[\\/]', val))

    elif format == 'csv_list':
        try:
            retval = utils.list_from_csv_str(val)
        except:
            format_error = True
    elif format == 'json':
        try:
            retval = json.loads(val)
        except:
            format_error = True

    elif format == 'url':
        format_error = not bool(re.match(url_regex, val))
        
    elif format == 'regex':
        retval = val.strip('"')
        if not re.search(r'\(.+\)', retval):
            format_error = True
            helpstr = "regex must have parenthesis in the expression."
        pass
    elif format == '':
        pass
    else:
        print (f"format parameter '{format}' invalid. ")
        format_error = True
    
    if format_error:
        print(f"parameter '{name}' not valid {format}: '{val}'. " + helpstr)
        return False, retval
     
    return True, retval


    
def check_args(argsdict, argspecs_dod):
    """ check argsdict against argspecs_dod.
            check required parameters exist.
            insert defaults.
            check format
            convert csv_list, json
            check regexs valid.
        return True if no error
    """

    no_error = True
    
    diganostic_output = False
    
    for argspec in argspecs_dod.values():
        name    = argspec['name']
        dtype   = argspec['type']
        format  = argspec['format']
        
        if diganostic_output:
            print(f"checking name:'{name}' dtype:{dtype} format:'{format}' ", end='') 
        if not name in argsdict:
            if utils.str2bool(argspec['required']):
                print(f"parameter '{name}' is required but was not provided in settings file.")
                no_error = False
                continue
            if argspec['default'] is not None and str(argspec['default']) != '':
                add_value_of_type(argsdict, name, argspec['type'], argspec['default'])
                if diganostic_output:
                    print(f"Added default:{argspec['default']}.")
            else:
                argsdict[name] = None if argspec['type'] != 'list' else []
                if diganostic_output:
                    print('not provided, no default')
            continue
                
        # name is in argsdict.
        value = argsdict[name]

         
        if isinstance(value, list):
            for idx, val in enumerate(value):    
                if diganostic_output:
                    print(f"value:{val} ")
                no_error_1val, value[idx] = check_one_value(f"{name}[{idx}]", val, format)
                if not no_error_1val:
                    no_error = False
            argsdict[name] = value
        else:
            if diganostic_output:
                print(f"value:{val} ")
 
            no_error_1val, argsdict[name] = check_one_value(name, value, format)
            if not no_error_1val:
                no_error = False

        if no_error and argspec['choices']:
            valid_choices = utils.list_from_csv_str(argspec['choices'])
            if str(value) not in valid_choices:
                print(f"parameter '{name}' has value '{value}', not in valid choices list: {valid_choices}.")
                no_error = False
                continue
                
    return no_error


def custom_argsdict_checks(argsdict):

    # Get job name as the last sub-dir of the job_folder_path or job_folder_s3path.
    if not argsdict.get('job_name'):
        if argsdict.get('job_folder_path'):
            job_folder_path = argsdict['job_folder_path'].rstrip('/\\') 
            argsdict['job_name'] = utils.safe_path_split(job_folder_path)[1]
        elif argsdict.get('job_folder_s3path'):
            job_folder_s3path = argsdict['job_folder_s3path'].rstrip('/\\') 
            argsdict['job_name'] = utils.safe_path_split(job_folder_s3path)[1]
        else:
            print ("job_folder_path or job_folder_s3path is required.")


    dependencies = {
        'use_s3_archives': {'requires':['archives_folder_s3path']},
        'use_s3_results':  {'requires':['job_folder_s3path']},
        'use_lambdas':     {'requires':['archives_folder_s3path', 'job_folder_s3path']},
        }
        
    error_flag = False
    for setting, item_dict in dependencies.items():
        if argsdict[setting]:
            requires_list = item_dict['requires']
            for required_setting in requires_list:
                if not argsdict.get(required_setting):
                    error_flag = True
                    print (f"setting {setting} requires the setting {required_setting} but it was not set.")

    if not argsdict['election_name']:
        if argsdict['archives_folder_path']:
            argsdict['election_name'] = utils.safe_path_split(argsdict['archives_folder_path'].rstrip('\\/'))[1]
        elif argsdict['archives_folder_s3path']:
            argsdict['election_name'] = utils.safe_path_split(argsdict['archives_folder_s3path'].rstrip('\\/'))[1]
        else:
            print("Could not derive the 'election_name' from 'archives_folder_path' or 'source' specifications")
            error_flag = True

    return not error_flag


def get_ballot_style_overrides(argsdict):
    """ In some cases, the style cannot be reliably read from a ballot due to
        corrpution of the barcode. In those cases, an overridge can be provided
        in the input file.
        The format in the file is
        argument: value
        ballot_style_override: ballot_id,style_num
        multiple overrides may exist in the input file.
    """
    ballot_style_overrides_dict = {}
    if argsdict.get('ballot_style_override'):
        for ballot_style_override in argsdict['ballot_style_override']:
            ballot_id, style_num = utils.list_from_csv_str(ballot_style_override)
            ballot_style_overrides_dict[ballot_id] = style_num
    return ballot_style_overrides_dict


        
""" PRIOR CODE FOR REFERENCE ONLY
        
    inputdirectives = (
        'ElectionId',               # human readable string that describes the election, like "San Francisco Consolidated Presidential Primary"
        
        'archives_folder_path',     # path to archives folder using standard election naming convention: 
                                    # like: ST_County_YYYY_Type, like "CA_San_Francisco_2020_Pri"
                                    #   Use '/' and not '\' in paths
                                    
        'archives_folder_s3path',   # path to archives folder on s3 file system, 
                                    #   using s3://bucket/prefix/ format
        'source',                   # bia - ballot image archives -- ZIP archives. 
                                    #   (multiple okay). basename only of archives.
                                    # These should be explicitly provided and are 
                                    # appended to either archives folder path or 
                                    # archives_folder_s3path to create the full path.
                                    
        'job_folder_path',          # path to results and input files folder on local system
        'job_folder_s3path',        # path to results and input files folder on s3 for lambdas coordination
                                    
        'election_name',            # derived from archives_folder_path if not otherwise provided.
        'include_archives',         # list of archive names (w/ .zip) to include in run
        'exclude_archives',         # list of archive names (w/ .zip) to exclude from run
        'verbose',                  # set verbosity level. 0 = no messages, 1 = urgent messages only, 2 = high-level tacking, 3 = all messages. (default: 0)
        'remove',                   # start over and delete all generated data.
        #'refresh',                  # deprecated
        'job',                      # deprecated. path to job folder, where all results will be produced, typically resources/(job_name). THIS NO LONGER INCLUDES 'resources/' PREFIX
        'job_name',                 # job_name is the leaf of the job path above and is calculated if not provided. Used in Lambdas processing.
        'vendor',                   # valid values: 'ES&S', 'Dominion', default is ES&S

        'precinct-folder',          # offset within the source bia zip files to precinct subfolder (default 0, -1 indicates no folder)
        'party-folder',             # offset within the source bia zip files to party subfolder (default 1, -1 indicates no folder)
        'group-folder',             # offset within the source bia zip files to group subfolder (default 1, -1 indicates no folder)
        'precinct_pattern',         # regex to extract precinct from filename
        'precinct_folder_pattern',  # regex to extract precinct from precinct folder name

        'cvr',                      # cast-vote-record -- ZIP file each of a single .xlsx file. (optional, multiple okay)
                                    #   use '(not available)' if the cvr is not available.
        'check_ballots',            # during cvr processing, check bia files to verify that all ballot files exist and all are represented in cvr file.
        'use_cvr_columns_without_replacement',  # In theory, the EIF needs only to have the official_contest_name
                                                # column and not original_contest_name column.
                                                # and then we do not need to substitute the columns names before
                                                # processing. However, to date, the column names
                                                # have not been reliably unique and sufficiently descriptive.
        'incremental_genbif',       # during gentemplate, code will look for already built nonBMD template and not build it again. Does not affect BMD analysis.
        'genbif_ballots_per_chunk', # number of ballots per chunk when generating bif table.
        'genbif_chunk_limit',       # instead of processing all chunks, if this is specified, it will limit the number of chunks artificially. Used for testing.

        # template generation directives
        'eif',                      # Election Information file -- .xlsx file to provide contest name equivalencies (required, 1 only)
        'initial_cvr_cols',         # specify the initial CVR columns, default is 'Cast Vote Record','Precinct','Style'
                                    # TODO: (currently multiple specifications, change to csv_str)
        'bof',                      # Ballot Options File -- .xlsx file provides option name equivalencies (optional)
        'precinct',                 # precinct names to include (optional, multiple okay, default is all precincts)
        'exclude_ballotid',         # list ballots that should be excluded from gentemplates phase (optional, multiple OK, default = include all ballots)
        'threshold',                # the number of ballots of each style to combine to create ballot templates (int, default 50)
        'allow_style_from_cvr',     # when producing templates, if ballotid to style information is known,
                                    # rely on it instead of reading style info from ballot.
        'all_styles_have_all_contests',             # when no "Style" column exists in cvr, sometimes all ballots have all contests
                                                    # and then this is a shortcut to specify the style for each ballot.
        'use_built_ballotid_to_style_dict',         # if no cvr is provided or if the cvr does not have 'Style' column,
                                                    # once all ballots have been processed one time,
                                                    # a BUILT_BALLOTID_TO_STYLES dict is created. if it exists, this allows it to be used.
        'style_map_override',       # if a contest cannot be mapped in a style, this provides override information. csv_str format, multiple okay
                                    # entries should be style_num,contest_name_str,roi_number.
                                    # The roi number can be derived by inspecting the log and is the first roi where the contest should be mapped.
        'style_from_party',         # DEPRECATED (JSON) dict which provides mapping of party name to style_num [use style lookup table]
        'style_lookup_table_path',  # Path of lookup table to derive style from the party, precinct, and sheet. .xlsx or csv.
                                    #   columns are 'precinct','party','card_code','style_num'. precinct and party should match path strings
                                    
        'incremental_gentemplate',  # during gentemplate, code will look for already built nonBMD template and not build it again. Does not affect BMD analysis.
        'min_ballots_required',     # during gentemplate, require that any style have at least this number of ballots.
        'style_from_precinct_regex',# use this regex to extract the style from the precinct string, when they are munged together.
        'style_num_low_limit',      # lowest valid style number
        'style_num_high_limit',     # highest valid style number
        'include_style_num',        # style_num to include in genrois. Okay to have multiple declarations. Empty list means include all styles.
        'exclude_style_num',        # style_num to exclude from attempt to generate in genrois. Okay to have multiple declarations.
        'diagnose_ocr_styles',      # style_nums to subject to extensive variations of ocr generation and reporting. Multiple ok.
        'diagnose_ballotid',        # ballot_id of ballot to produce additional diagnostic information. Multiple declarations OK.

        'manual_styles_to_contests_path',   # path to CSV file with manually generated contest map. 
                                            # First column should be contest names. Columns should be headed with style_num.
                                            # each cell has '1' in it if the style has that contest.
        'writein_str',              # string used in indicate a write-in.

        'merge_similar_styles',     # if a style is known to be identical to another style, merge them.

        'merged_styles',            # single entry is JSON dict like {merged_style_num: merged_to_style_num, ...}
                                    # when styles do not map, then during extractvote, this dict will be consulted for any merged styles.
        'non_partisan_sheet0s',     # list of sheet0 numbers (0,1,...) that are the same across all parties.

        'question_contests_have_no_contest_name',   # In some layouts, the description of the contest is essentially the contest name for question type contests.
        'layout',                   # type of layout for roi mapping. 'separated','fully_joined','partially_joined'
        'page_layout',              # JSON list of list of layout types in sheet, page order. Default is [['3col','3col'],...] Valid keys are '3col', '2col', '1col'
        'target_side',              # either 'left' (default) or 'right'
        'yes_no_in_descr',          # yes and no are in the description box usually when target_side = 'right'
                                    # at a specific location.
        'add_line',                 # each entry is JSON dict in the following format:
                                    #   {'styles':[set of styles], 's':s, 'p':p, 'x':x, 'y':y, 'h':h, 'w':w, 'r':, 'ox':offset_x, 'oy':offset_y}
                                    # add black boxes (typically lines) based on JSON formatted data.
                                    # draw on styles listed, on page p of sheet s, starting at x, y and with dimensions h, w
                                    # if provided, repeat r times (default is 1) with offset_x, and offset_y as provided as ox, oy
                                    # x, y required. h, w default to 2. s, p default to 0, rep defaults to 1. ox, oy default to 0
                                    # Entries in list of styles are treated as regular expressions.
        'active_region',            # each entry is for a given set of styles, sheet, and page. Format similar to add_line. Multiple entries are OK.
                                    #   {'styles':[set of styles], 's':s, 'p':p, 'x':x, 'y':y, 'h':h, 'w':w}
                                    # This replaces the y_offset_page_x directives. Generally, all parameters are optional except for y.
                                    # The active region defines where ROIS will be searched for, and will be potentially inserted up to that boundary.'
                                    # only one region is currently supported per page and only y parameter is honored.
                                    # Entries in list of styles are treated as regular expressions.

        'find_lines_region',        # Provides a region where lines (either h or v) will be searched for and then drawn
                                    #   {'styles':[set of styles], 's':s, 'p':p, 'x':x, 'y':y, 'h':h, 'w':w, 'h_or_v':'h'or'v', 'h_min':h_min, 'snap':'midgap'}
                                    # In the specified styles (default is all styles), on page p of sheet s, in region x,y,w,h,
                                    #   search for lines and draw them in, but no closer than h_min from the prior line drawn.
                                    # Unspecified h_min defaults to 0. Use 60 to force at least two timing mark gaps.
                                    # Entries in list of styles are treated as regular expressions.
        'maprois_max_slip_os',      # if a match between expected contests and rois does not occur, how far ahead should it search for the
                                    # next match. This should be at least 1 greater than the number of blank or filler rois.
        'max_additional_descr_rois',# If there are gaps included in description of question type contests, how many additional
                                    # paragraphs should be included after splitting due to splitting on gaps. If splitting on
                                    # gaps is not performed, this has no operational effect.
        'fuzzy_compare_mode',       # one of the following: 'left_only', 'right_only', 'full_only', 'best_of_all' which controls how strings are compared
                                    # during fuzzy matching. 'left_only' should be used if the match is likely found in the first left characters.
                                    # use 'best_of_all' (default) if it is unknown, but mapping is 1/3 the time if only one of the three modes is used.
                                    # of characters in the correct string, and disregard the rest.
        'split_rois_at_white_gaps', # if true, rois will be split in at white gaps.
        'initial_white_gap',        # number of rows of white required for the initial white gap, typically after a contest header.
        'subsequent_white_gaps',    # number of rows of white required for the subsequent white gaps, typically between options.
        'save_checkpoint_images',   # save checkpoint images during template and rois generation
        'unused_trailing_rois',     # number of "blank" rois that may exist and are not considered an error. This occurs at end of rois for a sheet.
        'conv_card_code_to_style_num',  # (bool) use an additional conversion of card_code to style_num. Default True.
                                    # if False, style_num <- card_code
                                    # for ES&S, if False, this will use the card_code directly instead of extracting the style_number from the barcode.
                                    # This is useful if we don't yet understand the code and do not need to index into any cvr style_num
        'use_stretch_fix',          # if true (default), enable the stretch-fix algorithm
        'h_max_option',             # maximum vertical dimension of block to be considered option (vendor specific default if not set)
        'pstyle_region',            # json dict of region where printed style_num can be found, like {"s": 0, "p": 0, "x": 1284, "y": 2641, "h": 126, "w": 219 }
        'pstyle_pattern',           # regex to extract pstyle from OCR region
        'use_ocr_based_genrois',    # if true, do not rely on breaking down rois into individual blocks, and instead use OCR-based extraction techniques
        'insert_rois_in_gaps',      # if true, then additional rois will be inserted between rois on the page. Missing rois are due to black areas.
                                    #   not needed for OCR-based rois generation
        'use_style_discovery',      # This mode of operation works with use_ocr_based_genrois, and requires clear ballots without gray backgrounds.
                                    #   It is not necessary to understand the style system being used as the contests are assigned to the style based on
                                    #   what is found on the ballot. May not work if contest names are not unambiguous and options do not exist.
        'compare_contest_name',     # If contest name exists, it must match to declare a contest match
        'permute_option_list',      # (bool) if True (default) compare ocr option list with all permutations of ballot_option_list in EIF.
                                    #   otherwise, only compare with the options and order provided in the EIF.
                                    #   depends on state law if ballot options are shuffled on different styles.
        'rem_target_from_ocr_str',  # When working with 'use_ocr_based_genrois', and if targets are on the left, then
                                    #   frequently the ocr string will be preceeded by '@ ' or '(c) ', a single character and space.
                                    #   this control strips this when options are compared.
        'include_gentemplate_tasks',    # sub tasks in gentemplate action - generate base templates
        'include_gentemplate',      # sub tasks in gentemplate action - generate base templates
        'include_genrois',          # sub tasks in gentemplate action - generate rois.
        'include_maprois',          # sub tasks in gentemplate action - map rois.

        # vote extraction directives
        #'precinct'                 # this directive is also respected during this phase.
        'limit',                    # only process this many ballots in extraction mode. (int, optional, default is no limit)
        'skip',                     # continue current extraction but start at nth ballot (int, optional, default is 0)
        'ballotid',                 # ballot numbers to include (optional, multiple okay, default is all ballots)
        #'exclude_ballotid',         # list ballots that should be excluded from extraction phase (optional, multiple OK, default = include all ballots)
        'include_bmd_ballot_type',  # include BMD ballots (expressvote) in the extraction, (Yes/No, default Yes)
        'include_nonbmd_ballot_type',   # include nonBMD ballots (non expressvote) in the extraction, (Yes/No, default Yes)
        'BMDs_exist',               # if BMDs_exist is False, then no attempt will be made to identify bmd vs nonbmd
        'BMD_det_method',           # method by which BMDs will be discriminated from nonBMDs.
        'BMD_filesize_threshold',   # if set, then this will be used instead of the default. This works for ES&S ballots that have a big difference between
                                    #   nonBMD and BMD ballots, but it varies based on the complexity of the ballots. This could be determined using
                                    #   adaptive thresholding.

        'expressvote_header',       # the header expected in expressvote ballots to check whether they appear valid. csv_str, single-value only. (no default, required for expressvote ballots)
        'ballot_style_override',    # when the style cannot be read from the ballot, this entry provides the style (optional, multiple OK, csv_str: "ballotid","style_num")
        'save_mark_images',         # if enabled, save every mark image in the folder results/NNNNNN where NNNNN is the ballotid.
        'incremental_extraction',   # if enabled, skip ballots that already have been extracted (i.e. marks_df record exists)
        'remove_unmarked_records',  # to allow adaptive thresholding to work properly, we maintain all records in the marks_df. When creating the combined_marks_df these are normally removed.
        'enable_per_ballot_csv_results',    # if enabled, marks_df's are output on per-ballot basis. Unmarked records are only removed if 'remove_unmarked_records" is provided.
        'enable_combined_csv_results',      # if enabled, marks_df's are combined into single csv file by appending the file for each ballot processed. Unmarked records are always removed in this case.
        'genmarks_ballots_per_chunk',       # the number of ballots to include in a chunk for a single lambda to process. Limited by the max lambda processing time.
        'upload_extraction_tasks_to_s3',    # if true, upload extraction task chunks to s3 bucket: co-audit-engine-extraction-tasks

        # comparison and reporting
        'url',                      # url to official summary report for scraping operation to get all contest names and official summary vote counts.
        'cvr_option_regex',         # regular expression to use to extract options from decorated CVR values.
                                    # this currently doesn't work very well, and instead decoration such as three-character party desigations and option numbers '(NNNNN)' are removed.
        'convert_cvr_image_cells_to_writein',       # sometimes CVR is created with writein images in cells. Convert these to 'writein:'. True for Wakulla 2018 set.


        'lambda_function',          # name of a Lambda function to update. It should be a string with function name like 'generate_template' or 'all' if you want to update all the functions.
        'update_branch',            # branch name from which we want to update Lambda function. It should be a string with branch name like 'width-first-reorg'.
        'save_lambda_task_args',     # if enabled, it will save task_args in a file so that when lambda is debugged locally it automatically read that file and we don't have to copy past lambda event data.
        'use_lambdas',              # if enabled, use AWS lambdas for vote extraction, building bif from ballots, and creating templates.
                                    #    use_lambdas forces use_s3_archives and use_s3_results.
        'one_lambda_first',         # complete processing of one chunk by one lambda first before launching up to 1000. Prudent and cautious.                            
        'use_s3_archives',          # use s3 to access archives even if lambdas is not enabled. Useful for debugging interface with s3 without using lambdas
        'use_s3_results',           # use s3 to for results even if lambdas is not enabled. Useful for debugging interface with s3 without using lambdas
        'max_lambda_concurrency',   # set to 1000 based on availabilty of concurrency

        )
    inputints = ('limit', 'verbose', 'threshold', 'skip',
        'precinct-folder',
        'party-folder',
        'group-folder',
        'style_num_low_limit',
        'style_num_high_limit',
        'maprois_max_slip_os',
        'max_additional_descr_rois',
        'initial_white_gap',
        'subsequent_white_gaps',
        'unused_trailing_rois',
        'min_ballots_required',
        'h_max_option',
        'genbif_ballots_per_chunk',
        'genmarks_ballots_per_chunk',
        'genbif_chunk_limit',
        'max_lambda_concurrency',
        )
    inputbools = (
        'refresh', 'remove', 'check_ballots',
        'allow_style_from_cvr', 'all_styles_have_all_contests',
        'question_contests_have_no_contest_name',
        'use_cvr_columns_without_replacement',
        'use_built_ballotid_to_style_dict',
        #'check_built_ballotid_to_style_dict_for_missing_ballots',
        'include_bmd_ballot_type',
        'include_nonbmd_ballot_type',
        'BMDs_exist',
        'save_mark_images',
        'convert_cvr_image_cells_to_writein',
        'incremental_genbif',
        'incremental_gentemplate',
        'use_lambdas',
        'one_lambda_first',
        'use_s3_archives',
        'use_s3_results',
        'use_stretch_fix',
        'incremental_extraction',
        'remove_unmarked_records',
        'enable_per_ballot_csv_results',
        'enable_combined_csv_results',
        'merge_similar_styles',
        'yes_no_in_descr',
        'split_rois_at_white_gaps',
        'save_checkpoint_images',
        'upload_extraction_tasks_to_s3',
        'conv_card_code_to_style_num',
        'use_ocr_based_genrois',
        'insert_rois_in_gaps',
        'use_style_discovery',
        'compare_contest_name',
        'permute_option_list',
        'rem_target_from_ocr_str',
        'include_gentemplate_tasks',    # sub tasks in gentemplate action - generate base templates
        'include_gentemplate',          # sub tasks in gentemplate action - generate base templates
        'include_genrois',              # sub tasks in gentemplate action - generate rois.
        'include_maprois',              # sub tasks in gentemplate action - map rois.
    )
    inputlists = (
        'source',
        'include_archives',
        'exclude_archives',
        'cvr',
        'precinct',
        'initial_cvr_cols',
        'ballotid',
        'style_map_override',
        'ballot_style_override',
        'exclude_ballotid',
        'exclude_style_num',
        'include_style_num',
        'diagnose_ballotid',
        'add_line',
        'active_region',
        'find_lines_region',
        'non_partisan_sheet0s',
        'diagnose_ocr_styles',
    )
    inputscalars = (
        'ElectionId',
        'election_name',
        'archives_folder_path',
        'archives_folder_s3path',
        'job_folder_path',
        'job_folder_s3path',
        'vendor',
        'eif',
        'bof',
        'job',
        'job_name',
        'url',
        'cvr_option_regex',
        'layout',
        'BMD_filesize_threshold',
        'expressvote_header',
        'style_from_precinct_regex',
        'style_from_party',         # DEPRECATED use style_lookup_table
        'style_lookup_table_path',
        'precinct_pattern',
        'precinct_folder_pattern',
        'pstyle_pattern',
        'manual_styles_to_contests_path',
        'writein_str',
        'merged_styles',
        'page_layout',
        'target_side',
        'lambda_function',
        'update_branch',
        'fuzzy_compare_mode',
        'genmarks_ballots_per_chunk',
        'pstyle_region',
    )
    # the following allowed_values are defined for input scalars. Other values cause fatal exception.
    allowed_values = {
        'vendor':               ['ES&S', 'Dominion'],
        'layout':               ['separated', 'fully_joined'],
        'target_side':          ['left', 'right'],
        'fuzzy_compare_mode':   ['left_only', 'right_only', 'full_only', 'best_of_all'],
        }
        
    # regex extraction patterns
    inputregexes = (
        'precinct_folder_pattern', 
        'precinct_pattern',
        'pstyle_pattern',
    )

    defaultsdict = {
        'ElectionId': '',
        'election_name': '',
        'archives_folder_path': '',
        'archives_folder_s3path': '',
        'job_folder_path': '',
        'job_folder_s3path': '',
        'include_archives': [],
        'exclude_archives': [],
        'vendor': 'ES&S',
        'threshold': 50,
        'skip': 0,
        'refresh': False,
        'remove': False,
        'precinct-folder': 0,
        'precinct_pattern': '',
        'precinct_folder_pattern': '',
        'party-folder': -1,
        'group-folder': -1,
        'check_ballots': True,
        'allow_style_from_cvr': False,
        'initial_cvr_cols': ['Cast Vote Record', 'Precinct', 'Style'],
        'all_styles_have_all_contests': False,
        'question_contests_have_no_contest_name': False,
        'use_cvr_columns_without_replacement': False,
        'use_built_ballotid_to_style_dict': False,
        #'check_built_ballotid_to_style_dict_for_missing_ballots': False,
        'cvr_option_regex': '',
        'eif': '',
        'bof': '',
        'ballotid': [],
        'exclude_ballotid': [],
        'diagnose_ballotid': [],
        'include_style_num': [],
        'exclude_style_num': [],
        'diagnose_ocr_styles': [],
        'style_map_override': [],       # each style_map_override is style,"official_contest_name",rois_map_os
        'layout' : 'separated',         # layout can be 'separated', 'options_joined', or 'fully_joined'
        'ballot_style_override': [],    # when the style cannot be read from the ballot, this provides ballot_id,style_num
        'include_nonbmd_ballot_type': True,
        'include_bmd_ballot_type': True,
        'BMDs_exist' : True,
        'BMD_filesize_threshold': 0,
        'expressvote_header': '',
        'incremental_genbif': False,
        'genbif_ballots_per_chunk': 200,
        'genmarks_ballots_per_chunk': 200,
        'genbif_chunk_limit': 0,     # 0 indicates that no limit will be imposed.
        
        'incremental_gentemplate': False,
        'min_ballots_required' : 1,
        'style_from_precinct_regex': '',
        'style_from_party': '' ,         # (JSON) dict which provides mapping of party name to style_num
        'style_lookup_table_path': '',
        'use_lambdas': False,
        'one_lambda_first': True,
        'use_s3_archives': False,
        'use_s3_results': False,
        'incremental_extraction': False,
        'remove_unmarked_records': False,
        'enable_per_ballot_csv_results': True,
        'enable_combined_csv_results': True,
        'style_num_low_limit': None,
        'style_num_high_limit': None,
        'writein_str': 'write-in',
        'merge_similar_styles': False,
        'merged_styles': '',
        'target_side' : 'left',
        'yes_no_in_descr' : False,
        'non_partisan_sheet0s' : [],
        'maprois_max_slip_os': 3,
        'max_additional_descr_rois': 1,
        'fuzzy_compare_mode': 'best_of_all',
        'split_rois_at_white_gaps': False,
        'initial_white_gap': 12,        #ES&S Wakulla min_gap = 28; Leon 12
        'subsequent_white_gaps': 12,    #same for all ES&S that uses white gap splits.
        'save_checkpoint_images': False,
        'unused_trailing_rois': 10,
        'conv_card_code_to_style_num': True,
        'use_stretch_fix': True,
        'h_max_option': None,
        'pstyle_region': None,
        'pstyle_pattern': '',
        'use_ocr_based_genrois': False,
        'insert_rois_in_gaps': True,
        'use_style_discovery': False,
        'compare_contest_name': False,
        'permute_option_list': True,
        'rem_target_from_ocr_str': True,
        'include_gentemplate_tasks': True,
        'include_gentemplate': True,      # sub tasks in gentemplate action - generate base templates
        'include_genrois': True,          # sub tasks in gentemplate action - generate rois.
        'include_maprois': True,          # sub tasks in gentemplate action - map rois.

        'lambda_function': 'all',
        'update_branch': 'master',
        'upload_extraction_tasks_to_s3': False,
        'max_lambda_concurrency': 1000,

        # the following use standard region specification format
        'add_line': [],
        'active_region': [],
        'find_lines_region': [],
    }

"""

