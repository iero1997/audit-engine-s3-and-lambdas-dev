import sys
import re
#import os
#import glob
#import time
#import concurrent.futures
#import json
#from json import load, loads, dump, dumps
# Had to catch ImportError because of the missing layer on the "extract_vote" lambda function.
try:
    import matplotlib.pyplot as plt
except ImportError:
    plt = None

import pandas as pd
#import boto3

from utilities import utils, logs
#from aws_lambda import s3utils
#from utilities import config_d
#from utilities.config_d import config_dict
#from utilities.cvr_comparator import compare_chunk_with_cvr
#from utilities.html_utils import create_html_string, write_html_summary
#from utilities.style_utils import get_replacement_cvr_header
# from utilities.zip_utils import open_archive, get_image_file_paths_from_archive, get_next_ballot_paths, \
                                # analyze_ballot_filepath, filter_image_file_paths, copy_ballot_pdfs_from_archive_to_report_folder, \
                                # get_precinct
from models.DB import DB
#from models.CVR import CVR
#from models.Job import Job
#from models.LambdaTracker import LambdaTracker



COUNTERS = {}


def load_one_marks_df(df_file):
    """
    prior operation creates a separate NNNNN_marks_df.csv file for each ballot.
    now creating .csv file
    This supports incremental operation.
    """
    #utils.sts(f"Loading df chunk {df_file}")
    #marks_df = DB.load_df(name=df_file, dirname='results')
    marks_df = DB.load_data(dirname='marks', name=df_file, format='.csv')
    return marks_df

def get_marks_df_list():
    return DB.get_object_list(dirname='marks', pattern=r'^marks_.*.csv$')
    
def get_ballot_id_from_marks_df_name(marks_df_name):
    match = re.search(r'marks_.*(\d+).csv$', marks_df_name)
    return match[1]

def get_marks_df_path_from_ballot_id(ballot_id):
    dirpath = DB.dirpath_from_dirname('marks')
    return f"{dirpath}marks_df_{ballot_id}.csv"

def get_marks_df_name_from_ballot_id(ballot_id):
    return f"marks_df_{ballot_id}.csv"


def load_all_marks_df():
    """
    load marks data frame from results and combines them
    returns combined dataframe.
    @TODO -- this can use general combine chunks 
    """
    combined_marks_df = pd.DataFrame()
    df_filename_list = get_marks_df_list()
    utils.sts(f"Total of {len(df_filename_list)} marks_df chunks detected.", 3)
    for df_file in df_filename_list:
        marks_df = load_one_marks_df(df_file)
        combined_marks_df = combined_marks_df.append(marks_df, sort=False, ignore_index=True)
        utils.sts(f"appended {df_file} chunk, {len(marks_df.index)} records, total of {len(combined_marks_df.index)} records.", 3)
    return combined_marks_df


def get_pixel_metric_value_from_marks_df(marks_df, ballot_id, contest, option):
    option_df = marks_df.loc[
        (marks_df['ballot_id'] == int(ballot_id)) &
        (marks_df['contest'] == contest) &
        (marks_df['option'] == option)]

    # this might wind up being a list, but we don't expect that.
    pmvs_list = list(option_df['pixel_metric_value'])
    if len(pmvs_list) > 1:
        utils.sts(f"Unexpected Condition: pixel_metric_values is multivalued for ballot_id {ballot_id}, "
                  f"contest {contest}, option {option}", 3)
    elif not pmvs_list:
        # note: this should never occur anymore. 
        # Express vote ballots will provide value of 100 for marks and 0 for nonmarks.
        # just accept the placeholder value 999 which means "not found" since 0 is a value value.
        # utils.sts(f"Unexpected Condition: no pixel_metric_value for ballot_id {ballot_id}, "
        #          f"contest {contest}, option {option}", 3)
        return 999

    pmv = pmvs_list[0]
    return pmv


def contests_to_results_dod(marks_df, contests_dod, contests_list):
    """ Provides the results over the ballots included in the marks_df provided.
        if a single ballot is provided, the the results are for that ballot.
        otherwise, can provide results over all ballots included in the marks_df
        results_dod {contest : {'overvotes':ovnum, 'undervotes':uvnum, 'num_ballots':num, 'tot_votes':total_votes,
                                'votes': {optionname: num, ... }
                                'writeins': num}...}
    """
    results_dod = {}

    for contest in contests_list:
        contest_df = marks_df.loc[marks_df['contest'] == contest]
        # return all rows where option starts with '#contest'
        contest_headers_df = contest_df[contest_df['option'].str.match('#contest')]
        results_dod[contest] = {
            'overvotes': contest_headers_df['overvotes'].sum(),
            'undervotes': contest_headers_df['undervotes'].sum(),
            'num_ballots': len(contest_headers_df.index),
            'tot_votes': contest_df['num_votes'].sum(),
            'writeins': 0,
            'votes': {},
            'unrecognized_selections': [],
        }
        options_list = contests_dod[contest]['official_options_list']
        for option in options_list:
            option_df = marks_df.loc[(marks_df['contest'] == contest) & (marks_df['option'] == option)]
            option_votes = option_df['num_votes'].sum()
            results_dod[contest]['votes'][option] = option_votes
        writein_df = marks_df.loc[(marks_df['contest'] == contest) & (marks_df['option'].str.match('writein'))]
        writein_votes = writein_df['num_votes'].sum()

        for writein_idx in range(writein_votes):
            writein_option_str = f"writein_{writein_idx}"
            results_dod[contest]['votes'][writein_option_str] = 1

        results_dod[contest]['writeins'] = writein_votes
    return results_dod


def genreport(argsdict):
    """
    This is a primary entry point from main.
    It processes all marks_df and creates a report
    no arguments.
    algorithm:
    initialize results_dod
    process each votes_df in auditcvr directory:
        get list of unique contests
            for each contest:
                get list of unique options listed (assumes NoMarks already removed)
                for each option:
                    get total of votes for records with contest and option
                    total num_votes for the contest/option combination.
                    record in results_dod
                    print to console.
    save resultsN_json for each archive
    save results_json for all ballots included in the run.

    Note: this does not include precinct level report but is per-archive
    TODO: This should be decomposed into two steps, first to access the results,
            and second to produce a report in a some format.
    """
    utils.sts("Creating Results", 3)

    contests_dod = DB.load_data('styles', 'contests_dod.json')
    utils.sts(f"Total of {len(contests_dod)} contests.", 3)
    results_dod = {}

    dtype = {'idx': int, 'ballot_id': int, 'style_num': str, 'precinct': str,
        'option': str, 'has_indication': str, 'writein_name': str,
        'num_marks': int, 'num_votes': int, 'pixel_metric_value': int,
        'overvotes': int, 'undervotes': int, 'ssidx': int, 'delta_y': int}

    # if argsdict.get('use_lambdas'):
        # try:
            # columns = ['idx', 'ballot_id', 'style_num', 'precinct', 'contest', 'option',
            # 'has_indication', 'num_marks', 'num_votes', 'pixel_metric_value',
            # 'writein_name', 'overvotes', 'undervotes', 'ssidx', 'delta_y',
            # 'ev_coord_str', 'ev_logical_style', 'ev_precinct_id']
            # dtype = {'idx': int, 'ballot_id': int, 'style_num': str, 'precinct': str,
            # 'option': str, 'has_indication': str, 'writein_name': str,
            # 'num_marks': int, 'num_votes': int, 'pixel_metric_value': int,
            # 'overvotes': int, 'undervotes': int, 'ssidx': int, 'delta_y': int}
            # marks_df = pd.read_csv(f"{config_dict['RESOURCES_PATH']}{config_dict['RESULTS_PATHFRAG']}ballot_marks_df.csv",
                                   # dtype=dtype, skiprows=1, names=columns)
        # except ValueError:
    marks_df = DB.load_data(dirname='marks', name='marks.csv', dtype=dtype)
    # else:
        # marks_df = load_all_marks_df()
    utils.sts(f"Total of {len(marks_df.index)} records in combined marks_df")

    contests_list = list(marks_df['contest'].unique())
    num_ballots = len(marks_df['ballot_id'].unique())
    num_styles = len(marks_df['style_num'].unique())
    utils.sts(f"Total of {len(contests_list)} contests on {num_ballots} ballots with {num_styles} styles.")
    for contest in contests_list:
        contest_df = marks_df.loc[marks_df['contest'] == contest]
        # return all rows where option starts with '#contest'
        contest_headers_df = contest_df[contest_df['option'].str.match('#contest')]
        overvotes = contest_headers_df['overvotes'].sum()
        undervotes = contest_headers_df['undervotes'].sum()
        totvotes = contest_df['num_votes'].sum()
        num_contest_ballots = len(contest_headers_df.index)
        results_dod[contest] = {'overvotes': overvotes, 'undervotes': undervotes}
        print(f"\n-----------------------------------------\n{contest}")
        options_list = contests_dod[contest]['official_options_list']
        for option in options_list:
            option_df = marks_df.loc[(marks_df['contest'] == contest) & (marks_df['option'] == option)]
            option_votes = option_df['num_votes'].sum()
            print("   %20s: %8.1u  %3.2f%%" % (option, option_votes, (option_votes / totvotes) * 100))
            results_dod[contest][option] = option_votes
        writein_df = marks_df.loc[(marks_df['contest'] == contest) & (marks_df['option'].str.match('writein'))]
        writein_votes = writein_df['num_votes'].sum()
        print("   %20s: %8.1u" % ('Write-ins', writein_votes))
        results_dod[contest]['writein'] = writein_votes

        print("   %20s: %8.1u" % ('Total votes', totvotes))
        print("   %20s: %8.1u" % ('Overvotes', overvotes))
        print("   %20s: %8.1u" % ('Undervotes', undervotes))
        print("   %20s: %8.1u" % ('Contest Ballots', num_contest_ballots))


def get_ballot_id_list(marks_df):
    return list(marks_df['ballot_id'].unique())



def plotmetrics():
    combined_marks_df = load_all_marks_df()
    utils.sts(f"Total of {len(combined_marks_df.index)} records in combined marks_df")
    only_marks_df = combined_marks_df[~combined_marks_df['option'].str.match('#contest')]

    # TODO: Where's this magic number(840) coming from?
    bins = list(range(840))[::10]
    only_marks_df[['pixel_metric_value']].plot(kind='hist', bins=bins, rwidth=0.8)
    plt.show()


def evalmarks():
    pass
    
    
def check_extraction(argsdict):
    # DEPRECATED BIF now used.
    print("This function is deprecated.")
    sys.exit(1)
    
    # utils.sts('Recovering cvr_ballotid_to_style_dict...', 3)
    # cvr_ballotid_to_style_dict = DB.load_style(name='CVR_BALLOTID_TO_STYLE_DICT', silent_error=True)
    # if not cvr_ballotid_to_style_dict:
        # utils.sts('Warning: cvr_ballotid_to_style_dict required to check_exraction...\n')
    # else:
        # check_mark_dfs_vs_ballotid_dict(argsdict, cvr_ballotid_to_style_dict)


def check_mark_dfs_vs_ballotid_dict(argsdict, cvr_ballotid_to_style_dict):
    """
    DEPRECATED. SHOULD USE BIF INSTEAD BUT REPLACEMENT IS NOT WRITTEN YET.
    Checks if ballot id from mark_dfs is in cvr_ballotid_to_style_dict.
    :param file_paths:
    """
    print("This function is deprecated.")
    sys.exit(1)
    
    utils.sts ("Checking all mark_dfs are in the CVR and the reverse...", 3)
    if not cvr_ballotid_to_style_dict:
        utils.sts ("Can't check if ballots are in the CVR, no cvr_ballotid_to_style_dict exists", 3)
        return 0
    
    # create a new dictionary with same keys, all False.
    found_ballotids = dict.fromkeys(cvr_ballotid_to_style_dict, False)

    missing_cvr_record_report_str = ''
    missing_marks_df_report_str = ''
    num_missing_cvr_records = 0
    
    marks_df_list = get_marks_df_list()
    
    num_marks_dfs = len(marks_df_list)
    utils.sts (f"{num_marks_dfs} extracted ballots found.", 3)

    for marks_df_name in marks_df_list:
        ballot_id = get_ballot_id_from_marks_df_name(marks_df_name)
        if ballot_id in cvr_ballotid_to_style_dict:
            found_ballotids[ballot_id] = True
        else:
            missing_cvr_record_report_str += f"Ballot marks_df_{ballot_id}.json extraction file exists but is not included in Cast Vote Records.\n"
            num_missing_cvr_records += 1

    total_missing_files = 0
    for key in found_ballotids:
        if not found_ballotids[key]:
            missing_marks_df_report_str += f"Ballot {key} exists in CVR files but no marks_df_{key}.json file found in the results folder.\n"
            total_missing_files += 1

    utils.sts (f"Total of {len(marks_df_list)} marks_df files found.\n"
                f"checked against {len(cvr_ballotid_to_style_dict)} CVR records.", 3)
    if missing_cvr_record_report_str:
        missing_cvr_record_report_str = f"### EXCEPTION: {num_missing_cvr_records} ballot image files exist that do not have matching marks_df files\n" + missing_cvr_record_report_str
        utils.exception_report(missing_cvr_record_report_str)
    if missing_marks_df_report_str:
        missing_marks_df_report_str = f"### EXCEPTION: {total_missing_files} CVR records exist that have no corresponding marks_df files.\n" + missing_marks_df_report_str
        utils.exception_report(missing_marks_df_report_str)


