import sys
import re
#import os
import datetime
import collections
import json
#from json import loads #, load, dump, dumps

import pandas as pd

#from utilities.bif_utils import BIF, get_bif_dirpath
from utilities.cvr_utils import get_replacement_cvr_header, create_contests_dod
from utilities import utils, logs
from models.DB import DB
from utilities.zip_utils import open_archive
#from utilities.config_d import config_dict


'''
def save_ballot_styles_to_bif(cvr_ballotid_to_style_dict: dict):
    try:
        with open(f'{get_bif_dirpath()}source_to_ballot.json', 'r') as f:
            source_to_ballot = load(f)
    except FileNotFoundError:
        raise FileNotFoundError('Failed to load source_to_ballot.json')
    utils.sts('Loaded source_to_ballot.json')
    for source_name, ballots in source_to_ballot.items():
        ballots = [str(b) for b in ballots]
        BIF.load_bif(source_name)
        for ballot in ballots:
            style = cvr_ballotid_to_style_dict.get(int(ballot))
            if not style:
                print(f'Ballot {ballot} from archive {source_name} not found in CVR dict')
                style = 'missing in CVR'
            BIF.df.at[ballot, 'style_num'] = style_num
        BIF.save_bif()
'''

def cvr_to_ballotid_to_style_dict(cvr_data) -> dict:
    """
    To avoid loading all cvr files into one dataframe and risking memory overflow,
    styles_dict is generated from each CVR file and then merged.
    """
    utils.sts("creating ballotid to style lookup dict...", 3)
    if not 'Cast Vote Record' in cvr_data.columns:
        utils.sts("Expected column 'Cast Vote Record' in the CVR not found,"
                  " aborting ballotid_to_style_dict generation", 3)
        return None
    ballotid = cvr_data['Cast Vote Record'].to_list()
    if not 'Ballot Style' in cvr_data.columns:
        utils.sts("Expected column 'Ballot Style' in the CVR not found,"
                  " ballotid_to_style_dict only provides ballotids and not the style", 3)
        style = None
    else:
        style = cvr_data['Ballot Style'].to_list()
    ballotid_to_style_dict = dict(zip(ballotid, style))
    return ballotid_to_style_dict


def get_contests_per_style(data_frame: pd.DataFrame, ballot_styles: list) -> dict:
    """
    Builds a dictionary of contests per ballot style. For example,
    {"Ballot Style 204": ["Justice of the Supreme Court".. ]
    :param data_frame: a pandas data frame with CVR
    :param ballot_styles: a pandas object with all ballot styles
    """
    contests_per_style = collections.OrderedDict()
    for ballot_style in ballot_styles:
        df = data_frame[data_frame['Ballot Style'] == ballot_style].copy()
        df.drop('Ballot Style', axis=1, inplace=True)
        contests_per_style[ballot_style] = list(df.dropna(axis='columns', how='all'))
    return contests_per_style


def get_all_contests(data_frame) -> list:
    """
    Creates a list of all contests names for a given CVR.
    """
    return [contest for contest in data_frame.columns if contest != 'Ballot Style']


def drop_unused_columns(data_frame):
    return data_frame.drop(['Cast Vote Record', 'Precinct'], axis=1)


def cvr_to_styles_dict(argsdict: dict, cvr_df: pd.DataFrame) -> dict:
    """
    A driver method that encapsulates the entire logic for parsing a CVR
    file to a JSON style dictionary.
    :param cvr_data: a parsed Excel file to a pandas data frame
    style_dict {style_name : [list of contests]}
    """
    start = datetime.datetime.utcnow()
    utils.sts("Searching CVR chunk for styles...", 3)

    if 'Ballot Style' in list(cvr_df.columns):
        # in Dane County case, "Ballot Style" column contains strings like 'Ballot Style NNN'
        # convert 'Ballot Style NNN' to 'NNN' (must be a string for use as key in JSON)
        cvr_df['Ballot Style'] = cvr_df['Ballot Style'].apply(lambda x: re.sub(r'^\D+', '', x))
    else:
        # no 'Ballot Style' column
        style_from_precinct_regex = argsdict.get('style_from_precinct_regex', '')
        if style_from_precinct_regex:
            precinct_list = cvr_df['Precinct']
            style_list = []
            for precinct in precinct_list:
                style = re.search(style_from_precinct_regex, precinct)[1]
                style_list.append(style)
            cvr_df.insert(2, 'Ballot Style', style_list)
        else:
            utils.sts("No 'Ballot Style' column and no 'style_from_precinct_regex' was provided.", 0)
            sys.exit(1)
            
    filtered_data = drop_unused_columns(cvr_df)
    unique_ballot_styles = filtered_data['Ballot Style'].unique()
    utils.sts(f"Found {len(unique_ballot_styles)} unique style(s).\nMapping Contests per style...", 3)
    style_dict = get_contests_per_style(filtered_data, unique_ballot_styles)
    
    end = datetime.datetime.utcnow()
    time_taken = utils.show_time((end - start).total_seconds())
    utils.sts(f"Processed {len(filtered_data)} rows in {time_taken}", 3)

    return style_dict


def convert_cvr_to_styles(argsdict: dict = None, silent_error: bool = False):
    """ ENTRY POINT FROM main
    
        --op cvr2styles
        
    Given list of cvr files, generate two dicts:
    master_style_dict -- indexed by style, provides list of contests
    
    cvr_ballotids_to_style_dict -- indexed by ballotid, provde style.
    THIS DICT IS NOW DEPRECATED AND WILL USE BIF INSTEAD.
    
    :param argsdict: Dict of arguments passed on script input.
    :param silent_error: Flag saying if exceptions should not return a message.
    """
    utils.sts('Generating styles dict from cvr files', 3)
    
    if argsdict['vendor'] == 'Dominion':
        get_styles_to_contests_dominion(argsdict, 
            ballot_type_contest_manifest='BallotTypeContestManifest.json',
            contest_manifest='ContestManifest.json', 
            just_ids=False,
            silent_error=silent_error
            )
    else:
        convert_cvr_to_styles_ess(argsdict, silent_error=silent_error)
        
        
        
def convert_cvr_to_styles_ess(argsdict: dict = None, silent_error: bool = False):
    """ ACTIVE -- this is used to create BIF.
        open each of the ess cvr files and create cvr_ballotid_to_style_dict
        by reading Ballot Style column.
        returns the cvr_ballotid_to_style_dict
    """
    
    if not argsdict['cvr'] or argsdict['cvr'] == ['(not available)'] or argsdict['cvr'] == ['']:
        utils.sts("CVR file not specified")
        if silent_error:
            return {}
        else:
            sys.exit(1)
    cvr_replacement_header_list = get_replacement_cvr_header(argsdict)
    master_styles_dict = {}
    cvr_ballotid_to_style_dict = {}
    for cvr_file in argsdict['cvr']:
        utils.sts(f"Processing cvr file: {cvr_file}", 3)
        #cvr_df = pd.read_excel(cvr_file, engine='xlrd')
        cvr_df = DB.load_data(dirname='archives', name=cvr_file, user_format=False)
        
        # probably all of this jazz below should be encapsulated.

        if cvr_replacement_header_list:
            # use the official contest names for column headers instead of those provided.
            orig_col_names = cvr_df.columns
            if len(orig_col_names) != len(cvr_replacement_header_list):
                utils.sts("official contest names list not right length to replace header names in CVR")
                sys.exit(1)
            # we will replace any "blank" col names with "Unnamed: XXX" so we can remove them later.
            for i, orig_col_name in enumerate(orig_col_names):
                if re.match(r'^Unnamed:', orig_col_name):
                    cvr_replacement_header_list[i] = orig_col_name
            cvr_df.columns = cvr_replacement_header_list

        # remove columns that had no names. These are when vote_for is > 1.
        dup_col_names = []
        for column in list(cvr_df.columns):
            if re.match(r'^Unnamed:', column):
                dup_col_names.append(column)
        cvr_df.drop(columns=dup_col_names, inplace=True)

        # remove leading and trailing spaces.
        if argsdict.get('check_dup_contest_names', True):
            duplicates = utils.find_duplicates(cvr_df.columns)
            if duplicates:
                string = '\n'.join(duplicates)
                utils.sts(f'Duplicate columns detected in CVR. All contest names must be unique.\n'
                          f'{string}')
                sys.exit(1)
        utils.sts('Generating cvr_to_styles_dict', 3)
        styles_dict = cvr_to_styles_dict(argsdict, cvr_df)
        
        utils.sts('Generated cvr_to_styles_dict OK', 3)
        # combine with the master_styles_dict, discarding any duplicates that might span cvr blocks.
        master_styles_dict = {**master_styles_dict, **styles_dict}
        ballotid_to_style_dict = cvr_to_ballotid_to_style_dict(cvr_df)
        cvr_ballotid_to_style_dict = {**cvr_ballotid_to_style_dict, **ballotid_to_style_dict}

    total_styles = len(master_styles_dict)

    utils.sts(f"Total of {total_styles} unique styles detected.\nWriting styles to contests dict to JSON file...", 3)

    DB.save_data(master_styles_dict, dirname='styles', name='CVR_STYLE_TO_CONTESTS_DICT.json')
    
    return cvr_ballotid_to_style_dict
    

def get_styles_to_contests_dominion(argsdict, ballot_type_contest_manifest='BallotTypeContestManifest.json',
                                    contest_manifest='ContestManifest.json', just_ids=False, silent_error=False):
    """
    
    Builds a styles to contests dict, where styles are ballot type_id.
    It requires BIF files to work and "BallotTypeContestManifest.json",
    "ContestManifest.json" like files in the Dominion CVR ZIP.
    :just_ids: Set to True returns "styles_to_contests_dict.json" with
    "ballot_type_id > contest_ids" instead of "ballot_type_id > contest_names".
    
    Assumes the various manifest files are in a single cvr zip file.
    
    """
    contest_id_to_names = {}
    ballot_type_to_contests = {}
    cvr_file = argsdict.get('cvr')[0]
    utils.sts(f'Loading CVR {cvr_file}')
    cvr_archive = open_archive(argsdict, cvr_file, testzip=False, silent_error=silent_error)

    # First open contests manifest to build dict
    # contest id > contest name.
    try:
        with cvr_archive.open(contest_manifest) as manifest_file:
            utils.sts(f'Loaded {manifest_file}')
            data = json.loads(manifest_file.read()).get('List')
    except (FileNotFoundError, ValueError) as error:
        if not silent_error:
            logs.exception_report(f"Could not load {contest_manifest} from CVR archive {cvr_file} due to %s", error)
            sys.exit(1)
        else:
            return None
    
    utils.sts(f'Loaded manifest data, {len(data)} rows found')
    for row in data:
        contest_id = str(row.get('Id'))
        contest_name = row.get('Description')
        contest_id_to_names[contest_id] = contest_name
    utils.sts(f'Ballot type ids to contests dict built, {len(contest_id_to_names)} rows found')
    del data

    # Then open ballot type confest manifest to build dict
    # ballot type id > list of contest names/ids.
    try:
        with cvr_archive.open(ballot_type_contest_manifest) as manifest_file:
            utils.sts(f'Loaded {manifest_file}')
            data = json.loads(manifest_file.read()).get('List')
    except (FileNotFoundError, ValueError) as error:
        if not silent_error:
            logs.exception_report(f"Could not load {manifest_file} from CVR archive {cvr_file} due to %s", error)
            sys.exit(1)
        else:
            return None
            
    utils.sts(f'Loaded manifest data, {len(data)} rows found')
    for row in data:
        type_id = row.get('BallotTypeId')
        contest_id = str(row.get('ContestId'))
        contest_name = contest_id_to_names.get(contest_id) if not just_ids else contest_id
        if not ballot_type_to_contests.get(type_id):
            ballot_type_to_contests[type_id] = [contest_name]
        else:
            ballot_type_to_contests[type_id].append(contest_name)
    utils.sts(f'Ballot type ids to contests dict built, {len(ballot_type_to_contests)} rows found')
    del data

    #DB.save_json('styles', f"{config_dict['CVR_STYLE_TO_CONTESTS_DICT_FILENAME']}.json", ballot_type_to_contests)
    DB.save_data(ballot_type_to_contests, 'styles', name='CVR_STYLE_TO_CONTESTS_DICT.json')

    
    # at this point, the styles_to_contests dict of list is created, where the key is the ballot_type_id
    # for each style in this list, split it between pages.    

    if False: # this needs to be updated. Not currently used. argsdict['merge_similar_styles']:
    
        # NOTE: It is invalid to merge styles at this point, only based on the contests in them, due to language differences.
        
        # for a given sheet, we may be able to merge styles while still respecting language differences. 
        # given ballot_type_id, look up contests on ballot.
        # using EIF, split contest list into separate list for each sheet.
        # for this sheet, compare list of contests with sheet_based_style_list
       
        contests_dod = create_contests_dod(argsdict)    # this reads the EIF
        
        sheetstyle_dol = {}

        for type, contest_list in ballot_type_to_contests.items():
            
            grouped_dol = utils.group_list_by_dod_attrib(contest_list, contests_dod, 'sheet0')    
                # Access EIF to get the sheet information for each contest.
                # this produces a dict with groups names for each sheet value
                
                # input might be: contest_list = ['contest1', 'contest2', contest3,... ]
                #                 contests_dod = {'contest1': {'sheet0':0}, 'contest2', {'sheet0':0}, 'contest3': {'sheet0':1}, 'contest4': {'sheet0':1},... ]
                # output: grouped_dol {0: ['contest1', 'contest2'], 1: ['contest3', 'contest4'] }
                
            for sheet0, contest_list in grouped_dol.items():
                if not contest_list: continue
                
                sheetstyle_num = "%1.1u%3.3u" % (sheet0 + 1, type)
                sheetstyle_dol[sheetstyle_num] = contest_list
                
        # now each ballot_type_id, which includes the contests for all sheets, has been split 
        # into separate styles for each sheet, and with only those contests for that sheet included.
        
        reduced_sheetstyle_dict, sheetstyle_map_dict = utils.reduce_dict(sheetstyle_dol)
        
        # the reduced_sheetstyle_dict includes a minmal subset of those sheetstyles that are unique.
        # the sheetstyle_map_dict provides a way to find the same list using the redundant key.
        
        #DB.save_json('styles', 'reduced_sheetstyle_dict.json', reduced_sheetstyle_dict)
        DB.save_data(reduced_sheetstyle_dict, 'styles', name='reduced_sheetstyle_dict.json')
        #DB.save_json('styles', 'sheetstyle_map_dict.json', sheetstyle_map_dict)
        DB.save_data(sheetstyle_map_dict, 'styles', name='sheetstyle_map_dict.json')

def contests_for_style_on_sheet(contest_list, contests_dod, sheet0):
    """ Given a list of contests, provide sub-list for specified sheet.
        can also implement in line as follows:
            sheet_contest_list = utils.group_list_by_dod_attrib(contest_list, contests_dod, 'sheet0')[sheet0]
    
    """
    grouped_dol = utils.group_list_by_dod_attrib(contest_list, contests_dod, 'sheet0')
    return grouped_dol[sheet0]

                        
        
        
        
