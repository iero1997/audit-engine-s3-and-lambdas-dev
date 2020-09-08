import re
#import os
import posixpath
import traceback
from pathlib import Path
from string import Template
import json

import numpy as np
import pandas as pd

from utilities import utils, logs
from aws_lambda import s3utils



VOTE_FOR_REG = r'#contest vote_for=(\d+)'
CMP_FAIL = Template("""
COMPARISION FAILURE: Ballot $BALLOT_ID contests included in the comparison do not match
Audit contests:\t\t'$AUDIT_CONTESTS'
CVR contests:\t\t'$CVR_CONTESTS'
Excluded contests:\t'$EXCLUDED_CONTESTS'
""")

CMP_CONTESTS_FAIL = Template("""------------------------------------------------------------
Ballot: $BALLOT_ID  Precinct: $PRECINCT Contest: $CONTEST
\t\t\tCVR\t\tAUDIT
Total votes:\t\t$CVR_TOT_VOTES\t$AUDIT_TOT_VOTES
Overvotes:\t\t$CVR_OVERVOTES\t$AUDIT_OVERVOTES
Undervotes:\t\t$CVR_UNDERVOTES\t$AUDIT_UNDERVOTES
Num Ballots:\t\t$CVR_NUM_BALLOTS\t$AUDIT_NUM_BALLOTS
Write-ins:\t\t$CVR_WRITEINS\t$AUDIT_WRITEINS
""")

CMP_OPTION_FAIL = Template("""   $OPTION:
\t\t\t\t$CVR_OPTION\t$AUDIT_OPTION\tPMV:$PMV\n""")


def value_or_previous(iterator: list, regex_match, default=None):
    """
    A generator that produces either a current column name or
    a swapped name based on a passed regex match pattern. This
    method is used in conjunction with rename_unnamed()
    """
    previous_item = default
    for item in iterator:
        if not regex_match(item):
            previous_item = item
        yield previous_item


def rename_unnamed(columns):
    """
    Takes a list of column names and iterates through them, changing
    'Unnamed' columns to the last valid header. For example:
    Input:
    ['Constable T Rutland', 'Unnamed: 245', 'Town Board Chairperson']
    Output:
    ['Constable T Rutland', 'Constable T Rutland','Town Board Chairperson']
    """
    pattern = re.compile(r'^Unnamed:\s\d+$').match
    return list(value_or_previous(columns, pattern))


def cvr_from_s3(argsdict, **kwargs) -> pd.DataFrame:
    """Loads result chunk from the S3 bucket and returns it as Pandas
    DataFrame.
    :param cvr_replacement_header: Headers to replace with the chunk
    file headers.
    :param chunk_name: Name of the chunk with results saved on the
    bucket.
    :param job_name: Name of the current job.
    :param bucket: Bucket where chunks are saved.
    """
    job_s3path = argsdict['job_folder_s3path']
    s3path = posixpath.join(job_s3path, 'cvr_chunks', f"{kwargs.get('chunk_name')}-cvr.csv")
    chunk_cvr = s3utils.read_csv_from_s3path(s3path)
    cvr_replacement_header = kwargs.get('cvr_replacement_header')
    if cvr_replacement_header:
        orig_col_names = chunk_cvr.columns
        assert len(orig_col_names) == len(cvr_replacement_header),\
            "replacement column headers not right length to replace header names in CVR"
        for i, orig_col_name in enumerate(orig_col_names):
            if re.match(r'Unnamed:', orig_col_name):
                cvr_replacement_header[i] = orig_col_name
        chunk_cvr.columns = cvr_replacement_header
    return chunk_cvr


def load_cvr_df(argsdict, mode: str, **kwargs) -> pd.DataFrame:
    """Loads CVR data frame based on mode."""
    if mode == 's3':
        return cvr_from_s3(argsdict, **kwargs)
    raise ValueError(f'Loading mode {mode} not found')


def contests_dod_from_s3(argsdict) -> pd.DataFrame:
    """Loads contests_dod from S3 bucket."""
    
    job_s3path = argsdict['job_folder_s3path']
    s3path = posixpath.join(job_s3path, "config/contests_dod.json")
    buff = s3utils.read_buff_from_s3path(s3path)    
    return json.loads(buff)


def load_contests_dod(mode: str, **kwargs) -> pd.DataFrame:
    """Loads CVR data frame based on mode."""
    if mode == 's3':
        return contests_dod_from_s3(**kwargs)
    raise ValueError(f'Loading mode {mode} not found')


def results_for_dominion(ballot_id: str, argsdict: dict, contests_dod: dict,
                         cvr_df: pd.DataFrame) -> dict:
    # Step 1: Get dict with keys of contest names and values of selected options
    row = cvr_df.loc[cvr_df['Cast Vote Record'] == int(ballot_id)].copy()
    assert not row.empty, f'Ballot {ballot_id} not found in CVR data frame'
    # Remove all columns that do not apply to this ballot_id.
    row.replace(r'^\s*$', np.nan, regex=True, inplace=True)
    row.dropna(axis='columns', how='all', inplace=True)
    cvr_contests = {}
    for contest in list(row.columns)[len(argsdict['initial_cvr_cols']):]:
        if row[contest]._typ == 'dataframe':
            cvr_contests[contest] = row[contest].iloc[0].tolist()
        elif row[contest]._typ == 'series':
            cvr_contests[contest] = row[contest].tolist()
        else:
            raise ValueError('Unrecognized data frame type')
    assert cvr_contests, f'No CVR contests found for ballot {ballot_id}'

    # Step 2: Get dict with keys of contest names and values of contest details.
    cvr_option_regex = argsdict.get('cvr_option_regex')
    cvr_unified_results = {}
    for cvr_contest, cvr_selections in cvr_contests.items():
        official_options_list = contests_dod[cvr_contest]['official_options_list']
        cvr_unified_results[cvr_contest] = {
            'overvotes': 0, 'undervotes': 0, 'num_ballots': 1, 'tot_votes': 0, 'writeins': 0,
            'unrecognized_selections': [], 'votes': dict.fromkeys(official_options_list, 0)
        }
        if cvr_selections[0] == 'overvote':
            # contest is overvoted, set overvote=1 and leave it at that.
            cvr_unified_results[cvr_contest]['overvotes'] = 1
            if cvr_selections.count('overvote') != len(cvr_selections):
                raise ValueError("Unexpected condition. 'overvote' should be repeated for all selections")
            continue  # No more to do if this is an overvote condition.
        for selection in cvr_selections:
            if selection == 'undervote':
                cvr_unified_results[cvr_contest]['undervotes'] += 1
                continue
            if selection == 'write-in:':
                cvr_unified_results[cvr_contest]['writeins'] += 1
                cvr_unified_results[cvr_contest]['tot_votes'] += 1
                continue
            if cvr_option_regex:
                match = re.search(cvr_option_regex, selection)
                if match:
                    selection = match[1]

            # For now, assume CVR entry might be formatted as PTY first last (NNNNN)
            # remove party and number
            selection = re.sub(r'^(DEM|REP|REF|NPA|GRN|PNF|LIB)\s*', '', selection)
            selection = re.sub(r'\(\d+\)$', '', selection)
            selection = selection.strip()

            # Try to find the option in the official options list.
            # If this does not work very well, we may have to add a column to BOF
            # file to provide a conversion.
            # Return zero-based index in the list of first item whose value is x.
            # If not found, it raises a ValueError exception
            if selection not in official_options_list:
                cvr_unified_results[cvr_contest]['unrecognized_selections'].append(selection)
                utils.exception_report(f"EXCEPTION: selection {selection} unrecognized for {cvr_contest}")
            else:
                # Can vote only one time for any one option.
                cvr_unified_results[cvr_contest]['votes'][selection] = 1
                cvr_unified_results[cvr_contest]['tot_votes'] += 1

    return cvr_unified_results


def get_cvr_unified_results(vendor: str, ballot_id: str, argsdict: dict,
                            contests_dod: dict, cvr_df: pd.DataFrame) -> dict:
    """Returns unified object with CVR results form data frame based
    on a vendor.
    """
    assert vendor, 'Vendor not specified'
    if vendor.lower() in ['dominion', 'es&s']:
        return results_for_dominion(ballot_id=ballot_id, argsdict=argsdict,
                                    contests_dod=contests_dod, cvr_df=cvr_df)
    raise ValueError(f'Vendor {vendor} not found')


def get_audit_unified_results(ballot_id: str, contests_dod: dict, audit_df: pd.DataFrame) -> dict:
    ballot_df = audit_df.loc[audit_df['ballot_id'] == int(ballot_id)]
    audit_unified_results = {}

    contests = list(ballot_df['contest'].unique())
    for contest in contests:
        contest_df = ballot_df.loc[ballot_df['contest'] == contest]
        # Return all rows where option starts with '#contest'
        contest_headers_df = contest_df[contest_df['option'].str.match('#contest')]
        audit_unified_results[contest] = {
            'overvotes': contest_headers_df['overvotes'].sum(),
            'undervotes': contest_headers_df['undervotes'].sum(),
            'num_ballots': len(contest_headers_df.index),
            'tot_votes': contest_df['num_votes'].sum(),
            'writeins': 0,
            'votes': {},
            'unrecognized_selections': [],
        }

        options = contests_dod[contest]['official_options_list']
        for option in options:
            option_df = contest_df.loc[contest_df['option'] == option]
            option_votes = option_df['num_votes'].sum()
            audit_unified_results[contest]['votes'][option] = option_votes

        writein_df = contest_df.loc[contest_df['option'].str.match('writein')]
        writein_votes = writein_df['num_votes'].sum()
        for writein_idx in range(writein_votes):
            writein_option_str = f"writein_{writein_idx}"
            audit_unified_results[contest]['votes'][writein_option_str] = 1
        audit_unified_results[contest]['writeins'] = writein_votes

    return audit_unified_results


def compare_votes(audit_votes: dict, cvr_votes: dict) -> bool:
    """ Here we deal with the fact that the cvr does not provide actual write-ins but we want to track the
        individual marks of write-ins on the ballot. So the votes dict is incomplete in the cvr votes dict.
        the entries in the votes dict will be the same except for the presence of writein_x entries in the audit dict.
    """
    for key in audit_votes:
        if key.startswith('writein'):
            # skip over writeins that are broken out by audit dict only
            continue
        if audit_votes[key] != cvr_votes[key]:
            return False
    return True


def compare_single_contests(audit_results_contest: dict, cvr_results_contest: dict) -> bool:
    for key in ['tot_votes', 'overvotes', 'undervotes', 'writeins']:
        if audit_results_contest[key] != cvr_results_contest[key]:
            return False
    return compare_votes(audit_results_contest['votes'], cvr_results_contest['votes'])


def get_precinct(audit_df: pd.DataFrame, ballot_id: str) -> int:
    option_df = audit_df.loc[audit_df['ballot_id'] == int(ballot_id)]
    precinct = option_df['precinct'].unique().tolist()
    return precinct[0]


def get_pmv_from_df(audit_df: pd.DataFrame, ballot_id: str, contest: str, option: str) -> int:
    option_df = audit_df.loc[
        (audit_df['ballot_id'] == int(ballot_id)) &
        (audit_df['contest'] == contest) &
        (audit_df['option'] == option)
    ]
    pmvs_list = list(option_df['pixel_metric_value'])
    if len(pmvs_list) > 1:
        utils.sts(f"Unexpected Condition: pixel_metric_values is multivalued for ballot_id {ballot_id}, "
                  f"contest {contest}, option {option}", 3)
    elif not pmvs_list:
        return 999

    return pmvs_list[0]


def compare_chunk_with_cvr(argsdict: dict, contests_dod: dict, cvr_df: pd.DataFrame,
                           audit_df: pd.DataFrame, chunk_name: str) -> tuple:
    """Iterates over ballot ids in data frame and compares them with CVR file.
    :param argsdict:
    :param cvr_df: DataFrame with CVR results.
    :param audit_df: DataFrame with Audit results.
    :param chunk_name: Name of the chunk with results saved on the bucket.
    :return: Tuple of lists. First is a list of dicts for agreed
    results. Second a list of disagreed results.
    """
    agreed_results = []
    disagreed_results = []
    blank_results = []
    ballot_ids = [int(b) for b in audit_df['ballot_id'].unique()]
    for ballot_id in ballot_ids:
        cvr_unified_results = get_cvr_unified_results(
            vendor=argsdict.get('vendor'),
            ballot_id=ballot_id,
            argsdict=argsdict,
            contests_dod=contests_dod,
            cvr_df=cvr_df,
        )
        audit_unified_results = get_audit_unified_results(
            ballot_id=ballot_id,
            contests_dod=contests_dod,
            audit_df=audit_df
        )
        style = audit_df.loc[audit_df['ballot_id'] == int(ballot_id)]['style'].tolist()
        print(f"Comparing ballot_id: {ballot_id}... ")
        comparison_row = {
            'ballot_id': ballot_id,
            'style': style[0],
            'precinct': get_precinct(audit_df=audit_df, ballot_id=ballot_id),
            'contest': '',
            'agreed': 1,
            'blank': 0,
            'chunk_name': chunk_name,
            'contests_mismatch': '',
        }
        if not audit_df.loc[audit_df['ballot_id'] == int(ballot_id), 'num_marks'].sum():
            comparison_row['blank'] = 1
            blank_results.append(comparison_row.copy())
        if cvr_unified_results == audit_unified_results:
            agreed_results.append(comparison_row.copy())
            continue

        cvr_contests = sorted(cvr_unified_results.keys())
        audit_contests = sorted(audit_unified_results.keys())
        if cvr_contests != audit_contests:
            comparison_row['agreed'] = 0
            excluded_contests = [c for c in cvr_contests if c not in audit_contests]
            comparison_row['contests_mismatch'] = json.dumps({
                'audit_contests': ', '.join(audit_contests),
                'cvr_contests': ', '.join(cvr_contests),
                'excluded_contests': ', '.join(excluded_contests),
            })
            disagreed_results.append(comparison_row.copy())
            continue

        for audit_contest in audit_contests:
            comparison_row['contest'] = audit_contest
            cvr_results_dict = cvr_unified_results[audit_contest]
            audit_result_dict = audit_unified_results[audit_contest]
            if compare_single_contests(audit_result_dict, cvr_results_dict):
                continue
            comparison_row['agreed'] = 0
            comparison_row['vote_difference'] = vote_difference = {}
            comparison_row['audit_info'] = audit_contest_info = {}
            comparison_row['cvr_info'] = cvr_contest_info = {}
            for key in ['tot_votes', 'overvotes', 'undervotes', 'num_ballots', 'writeins']:
                cvr_contest_info[key] = int(cvr_results_dict[key])
                audit_contest_info[key] = int(audit_result_dict[key])

            cvr_contest_info['options'] = cvr_options = {}
            audit_contest_info['options'] = audit_options = {}
            for option in contests_dod[audit_contest]['official_options_list']:
                cvr_options[option] = {}
                audit_options[option] = {}
                cvr_options[option]['vote'] = int(cvr_results_dict['votes'][option])
                cvr_options[option]['PMV'] = None
                audit_options[option]['vote'] = int(audit_result_dict['votes'][option])
                audit_options[option]['PMV'] = get_pmv_from_df(audit_df=audit_df, ballot_id=ballot_id, contest=audit_contest, option=option)
                vote_difference[option] = audit_options[option]['vote'] - cvr_options[option]['vote']

            for writein in range(audit_unified_results[audit_contest]['writeins']):
                option = f"writein_{writein}"
                cvr_options[option] = {}
                audit_options[option] = {}
                cvr_options[option]['vote'] = 1 if cvr_unified_results[audit_contest]['writeins'] > writein else 0
                audit_options[option]['vote'] = int(audit_result_dict['votes'][option])
                audit_options[option]['PMV'] = get_pmv_from_df(audit_df=audit_df, ballot_id=ballot_id, contest=audit_contest, option=option)
                vote_difference[option] = audit_options[option]['vote'] - cvr_options[option]['vote']

                if cvr_unified_results[audit_contest]['unrecognized_selections']:
                    unrecognized_selection = ' ,'.join(cvr_unified_results[audit_contest]['unrecognized_selections'])
                    utils.sts(f"The following options were not recognized: {unrecognized_selection}")

            for key in ['audit_info', 'cvr_info', 'vote_difference']:
                if comparison_row[key]:
                    comparison_row[key] = json.dumps(comparison_row[key])
                else:
                    comparison_row[key] = ''
            disagreed_results.append(comparison_row.copy())
    return agreed_results, disagreed_results


def lambda_handler(event, context):
    """This handles new instance of lambda 'audit_votes' function."""
    utils.LOG_LAMBDA = True
    argsdict = event['argsdict']
    job_folder_s3path = argsdict['job_folder_s3path']
    
    chunk_name = event['chunk_name']
    request_id = context.aws_request_id
    Path('/tmp/logfile.txt').touch(mode=0o777, exist_ok=True)
    
    log_s3path = posixpath.join(job_folder_s3path, f"/lambda_logs/{event['chunk_name']}-cmpcvr_logfile.txt")

    tracker_s3path = f"{job_folder_s3path}/lambda_tracker/{chunk_name}-cmpcvr.json"
    buff = json.dumps({
        "chunk_name": chunk_name,
        "request_id": request_id,
        "status": "Running",
    })
    s3utils.write_buff_to_s3path(tracker_s3path, buff)

    chunk_s3path = f"{job_folder_s3path}/results/{chunk_name}.csv"
    audit_df = s3utils.read_csv_from_s3path(chunk_s3path)

    cvr_df = load_cvr_df(argsdict, job_path=job_folder_s3path, chunk_name=chunk_name, 
                         cvr_replacement_header=event['cvr_replacement_header'])

    contests_dod = load_contests_dod(job_path=job_folder_s3path)

    try:
        agreed_results, disagreed_results = compare_chunk_with_cvr(
            argsdict=argsdict,
            cvr_df=cvr_df,
            audit_df=audit_df,
            chunk_name=chunk_name,
            contests_dod=contests_dod
        )
        agreed_s3path = posixpath.join(argsdict['job_folder_s3path'], f"cmpcvr/{chunk_name}-agreed-cmpcvr.json")
        agreed_buff = json.dumps(agreed_results)
        s3utils.write_buff_to_s3path(agreed_s3path, agreed_buff)
        
        disagreed_s3path = posixpath.join(argsdict['job_folder_s3path'], f"cmpcvr/{chunk_name}-disagreed-cmpcvr.json")
        disagreed_buff = json.dumps(disagreed_results)
        s3utils.write_buff_to_s3path(disagreed_s3path, disagreed_buff)
        
    # pylint: disable=broad-except
    # We need to catch broad exception.
    except Exception as err:
        error_type = err.__class__.__name__
        error_message = str(err)
        error_stack = traceback.format_tb(err.__traceback__)
        buff = json.dumps({
            "chunk_name": chunk_name,
            "request_id": request_id,
            "status": "Failed",
            "error_type": error_type,
            "error_message": error_message,
            "error_stack": error_stack,
        })
        s3utils.write_buff_to_s3path(tracker_s3path, buff)
        
        s3utils.write_buff_to_s3path(log_s3path, buff=utils.read_logfile("/tmp/logfile.txt"))
        return {
            'body': json.dumps({
                'msg': 'Votes extraction failed',
                'error_type': error_type,
                'error_message': error_message,
                "error_stack": error_stack,
                'event': event,
            })
        }

    buff = json.dumps({
        "chunk_name": chunk_name,
        "request_id": request_id,
        "status": "Done",
    })
    s3utils.write_buff_to_s3path(tracker_s3path, buff)
    s3utils.write_buff_to_s3path(log_s3path, buff=utils.read_logfile("/tmp/logfile.txt"))
    return {
        'body': json.dumps({
            'msg': 'Votes extraction finished',
            'event': event
        })
    }

if __name__ == "__main__":
    event = {
        "argsdict": {
            "job_name": "Dane2020-Full-Set",
            "vendor": "ES&S",
            "initial_cvr_cols": ['Cast Vote Record', 'Precinct', 'Ballot Style']
        },
        "chunk_name": "Dane2020-Full-Set-0027-0163",
        "bucket": "co-audit-engine",
        "cvr_replacement_header": ["Cast Vote Record", "Precinct", "Ballot Style", "Justice of the Supreme Court", "Court of Appeals Judge District IV", "Circuit Court Judge Branch 16", "Circuit Court Judge, Branch 1 Jefferson County", "Circuit Court Judge, Branch 2 Jefferson County", "County Supervisor District 14 (1-year term)", "County Supervisor District 36 (1-year term)", "Municipal Judge - Twns of Blooming Grove Bristol etc.", "Municipal Judge - Towns of Madison Middleton Verona", "Municipal Judge - Twn of Roxbury Vil. of Sauk City etc", "Municipal Judge - Town and Village of Oregon", "Municipal Judge - Villages of Black Earth and Mazomanie", "Municipal Judge - Villages of Cambridge Deerfield etc.", "Municipal Judge - Villages of DeForest and Windsor", "Edgerton Alderperson District 1", "Fitchburg Mayor (1-year term)", "Fitchburg Alderperson District 1 Seat 1", "Fitchburg Alderperson District 1 Seat 2 (1-year term)", "Fitchburg Alderperson District 2 Seat 3", "Fitchburg Alderperson District 2 Seat 4 (1-year term)", "Fitchburg Alderperson District 3 Seat 5", "Fitchburg Alderperson District 3 Seat 6 (1-year term)", "Fitchburg Alderperson District 4 Seat 7", "Fitchburg Alderperson District 4 Seat 8 (1-year term)", "Fitchburg Municipal Judge", "Mayor C Madison", "Madison Alderperson District 1", "Madison Alderperson District 2", "Madison Alderperson District 3", "Madison Alderperson District 4", "Madison Alderperson District 5", "Madison Alderperson District 6", "Madison Alderperson District 7", "Madison Alderperson District 8", "Madison Alderperson District 9", "Madison Alderperson District 10", "Madison Alderperson District 11", "Madison Alderperson District 12", "Madison Alderperson District 13", "Madison Alderperson District 14", "Madison Alderperson District 15", "Madison Alderperson District 16", "Madison Alderperson District 17", "Madison Alderperson District 18", "Madison Alderperson District 19", "Madison Alderperson District 20", "Middleton Alderperson District 1", "Middleton Alderperson District 3", "Middleton Alderperson District 5", "Middleton Alderperson District 7", "Monona Mayor", "Monona Alderperson (3)", "Monona Alderperson (3)", "Monona Alderperson (3)", "Stoughton Alderperson District 1", "Stoughton Alderperson District 1 (1-year term)", "Stoughton Alderperson District 2", "Stoughton Alderperson District 3", "Stoughton Alderperson District 4", "Sun Prairie Mayor", "Sun Prairie Alderperson District 1", "Sun Prairie Alderperson District 2", "Sun Prairie Alderperson District 3", "Sun Prairie Alderperson District 4", "Sun Prairie Municipal Judge", "Verona Alderperson District 1", "Verona Alderperson District 2", "Verona Alderperson District 3", "Verona Alderperson District 4", "Belleville Village President", "Belleville Village Trustee (3)", "Belleville Village Trustee (3)", "Belleville Village Trustee (3)", "Black Earth Village President", "Black Earth Village Trustee (3)", "Black Earth Village Trustee (3)", "Black Earth Village Trustee (3)", "Blue Mounds Village President", "Blue Mounds Village Trustee (2)", "Blue Mounds Village Trustee (2)", "Blue Mounds Municipal Judge", "Brooklyn Village President", "Brooklyn Village Trustee (3)", "Brooklyn Village Trustee (3)", "Brooklyn Village Trustee (3)", "Cambridge Village President", "Cambridge Village Trustee (3)", "Cambridge Village Trustee (3)", "Cambridge Village Trustee (3)", "Cottage Grove Village President", "Cottage Grove Village Trustee (3)", "Cottage Grove Village Trustee (3)", "Cottage Grove Village Trustee (3)", "Cross Plains Village President", "Cross Plains Village Trustee (3)", "Cross Plains Village Trustee (3)", "Cross Plains Village Trustee (3)", "Dane Village Trustee (2)", "Dane Village Trustee (2)", "Deerfield Village President", "Deerfield Village Trustee (3)", "Deerfield Village Trustee (3)", "Deerfield Village Trustee (3)", "DeForest Village President", "DeForest Village Trustee (3)", "DeForest Village Trustee (3)", "DeForest Village Trustee (3)", "Maple Bluff Village President", "Maple Bluff Village Trustee (3)", "Maple Bluff Village Trustee (3)", "Maple Bluff Village Trustee (3)", "Marshall Village Trustee (2)", "Marshall Village Trustee (2)", "Marshall Municipal Judge", "Mazomanie Village President", "Mazomanie Village Trustee (3)", "Mazomanie Village Trustee (3)", "Mazomanie Village Trustee (3)", "McFarland Village President", "McFarland Village Trustee (3)", "McFarland Village Trustee (3)", "McFarland Village Trustee (3)", "Mount Horeb Village President", "Mount Horeb Village Trustee (3)", "Mount Horeb Village Trustee (3)", "Mount Horeb Village Trustee (3)", "Oregon Village President", "Oregon Village Trustee (3)", "Oregon Village Trustee (3)", "Oregon Village Trustee (3)", "Rockdale Village President", "Rockdale Village Trustee (2)", "Rockdale Village Trustee (2)", "Shorewood Hills Village President", "Shorewood Hills Village Trustee (3)", "Shorewood Hills Village Trustee (3)", "Shorewood Hills Village Trustee (3)", "Waunakee Village President", "Waunakee Village Trustee (3)", "Waunakee Village Trustee (3)", "Waunakee Village Trustee (3)", "Windsor Village President", "Windsor Village Trustee (2)", "Windsor Village Trustee (2)", "Albion Town Board Chairperson", "Albion Town Board Supervisor (2)", "Albion Town Board Supervisor (2)", "Berry Town Board Chairperson", "Berry Town Board Supervisor 1", "Berry Town Board Supervisor 2", "Black Earth Town Board Chairperson", "Black Earth Town Board Supervisor 1", "Black Earth Town Board Supervisor 2", "Black Earth Town Treasurer", "Blooming Grove Town Board Chairperson", "Blooming Grove Town Board Supervisor (2)", "Blooming Grove Town Board Supervisor (2)", "Blue Mounds Town Board Chairperson", "Blue Mounds Town Board Supervisor 1", "Blue Mounds Town Board Supervisor 2", "Blue Mounds Constable", "Bristol Town Board Chairperson", "Bristol Town Board Supervisor 1", "Bristol Town Board Supervisor 2", "Burke Town Board Chairperson", "Burke Town Board Supervisor 2", "Burke Town Board Supervisor 3", "Christiana Town Board Chairperson", "Christiana Town Board Supervisor 1", "Christiana Town Board Supervisor 2", "Cottage Grove Town Board Chairperson", "Cottage Grove Town Board Supervisor 1", "Cottage Grove Town Board Supervisor 2", "Cottage Grove Municipal Judge", "Cross Plains Town Board Chairperson", "Cross Plains Town Board Supervisor 1", "Cross Plains Town Board Supervisor 2", "Cross Plains Town Clerk", "Cross Plains Town Treasurer", "Dane Town Board Chairperson", "Dane Town Board Supervisor 1", "Dane Town Board Supervisor 2", "Deerfield Town Board Chairperson", "Deerfield Town Board Supervisor (2)", "Deerfield Town Board Supervisor (2)", "Deerfield Town Treasurer", "Dunkirk Town Board Chairperson", "Dunkirk Town Board Supervisor 1", "Dunkirk Town Board Supervisor 2", "Dunkirk Town Treasurer", "Dunkirk Constable", "Dunn Town Board Chairperson", "Dunn Town Board Supervisor 1", "Dunn Town Board Supervisor 2", "Dunn Municipal Judge", "Madison Town Board Chairperson", "Madison Town Board Supervisor (2)", "Madison Town Board Supervisor (2)", "Mazomanie Town Board Chairperson", "Mazomanie Town Board Supervisor (2)", "Mazomanie Town Board Supervisor (2)", "Mazomanie Town Clerk", "Mazomanie Town Treasurer", "Medina Town Board Chairperson", "Medina Town Board Supervisor (2)", "Medina Town Board Supervisor (2)", "Medina Town Treasurer", "Middleton Town Board Chairperson", "Middleton Town Board Supervisor 1", "Middleton Town Board Supervisor 2", "Montrose Town Board Chairperson", "Montrose Town Board Supervisor 1", "Montrose Town Board Supervisor 2", "Montrose Town Clerk", "Montrose Town Treasurer", "Montrose Constable", "Oregon Town Board Chairperson", "Oregon Town Board Supervisor (2)", "Oregon Town Board Supervisor (2)", "Oregon Constable", "Perry Town Board Chairperson", "Perry Town Board Supervisor 1", "Perry Town Board Supervisor 2", "Perry Town Clerk", "Perry Town Treasurer", "Pleasant Springs Town Board Chairperson", "Pleasant Springs Town Board Supervisor 1", "Pleasant Springs Town Board Supervisor 2", "Primrose Town Board Chairperson", "Primrose Town Board Supervisor 1", "Primrose Town Board Supervisor 2", "Primrose Town Treasurer", "Roxbury Town Board Chairperson", "Roxbury Town Board Supervisor 1", "Roxbury Town Board Supervisor 2", "Roxbury Town Clerk", "Roxbury Town Treasurer", "Rutland Town Board Chairperson", "Rutland Town Board Supervisor", "Rutland Town Clerk", "Rutland Town Treasurer", "Rutland Constable (2)", "Rutland Constable (2)", "Springdale Town Board Chairperson", "Springdale Town Board Supervisor 1", "Springdale Town Board Supervisor 2", "Springfield Town Board Chairperson", "Springfield Town Board Supervisor 1", "Springfield Town Board Supervisor 2", "Sun Prairie Town Board Chairperson", "Sun Prairie Town Board Supervisor (2)", "Sun Prairie Town Board Supervisor (2)", "Sun Prairie Town Treasurer", "Sun Prairie Constable", "Vermont Town Board Chairperson", "Vermont Town Board Supervisor 1", "Vermont Town Board Supervisor 3", "Verona Town Board Chairperson", "Verona Town Board Supervisor 1", "Verona Town Board Supervisor 2", "Vienna Town Board Chairperson", "Vienna Town Board Supervisor 1", "Vienna Town Board Supervisor 2", "Vienna Town Treasurer", "Westport Town Board Chairperson", "Westport Town Board Supervisor 2", "Westport Town Board Supervisor 4", "York Town Board Chairperson", "York Town Board Supervisor 1", "York Town Board Supervisor 2", "York Town Clerk", "York Town Treasurer", "Barneveld School Board Member Town of Brigham", "Barneveld School Board Member Village of Barneveld", "Barneveld School Board Member At Large", "Belleville School Board Member (3)", "Belleville School Board Member (3)", "Belleville School Board Member (3)", "Cambridge School Board Member (2)", "Cambridge School Board Member (2)", "Columbus School Board Member (2)", "Columbus School Board Member (2)", "Deerfield School Board Member (2)", "Deerfield School Board Member (2)", "DeForest School Board Member Village of DeForest (2)", "DeForest School Board Member Village of DeForest (2)", "DeForest School Board Member Village of Windsor (2)", "DeForest School Board Member Village of Windsor (2)", "Edgerton School Board Member (3)", "Edgerton School Board Member (3)", "Edgerton School Board Member (3)", "Evansville School Board Member (2)", "Evansville School Board Member (2)", "Lodi School Board Member (2)", "Lodi School Board Member (2)", "Madison Metropolitan Board Member Seat 3", "Madison Metropolitan Board Member Seat 4", "Madison Metropolitan Board Member Seat 5", "Marshall School Board Member (2)", "Marshall School Board Member (2)", "McFarland School Board Member (2)", "McFarland School Board Member (2)", "Middleton Cross Plains School Board Member Area I", "Middleton Cross Plains School Board Member Area III", "Middleton Cross Plains School Board Member Area IV (2)", "Middleton Cross Plains School Board Member Area IV (2)", "Monona Grove School Board Member (2)", "Monona Grove School Board Member (2)", "Mount Horeb School Board Member (3)", "Mount Horeb School Board Member (3)", "Mount Horeb School Board Member (3)", "New Glarus School Board Member (2)", "New Glarus School Board Member (2)", "Oregon School Board Member Area 1 (2)", "Oregon School Board Member Area 1 (2)", "Pecatonica School Board Member (2)", "Pecatonica School Board Member (2)", "Poynette School Board Member (2)", "Poynette School Board Member (2)", "River Valley School Board Member Area 3", "River Valley School Board Member Area 6", "River Valley School Board Member Area 9", "Sauk Prairie Sch. Brd. Mbr. Twns Prairie du Sac Sumpter", "Sauk Prairie Sch. Brd. Mbr. Vil. of Prairie du sac Sauk", "Stoughton School Board Member (3)", "Stoughton School Board Member (3)", "Stoughton School Board Member (3)", "Sun Prairie School Board Member (3)", "Sun Prairie School Board Member (3)", "Sun Prairie School Board Member (3)", "Verona School Board Member Portion 2", "Verona School Board Member At Large (2)", "Verona School Board Member At Large (2)", "Waterloo School Board Member Area 3", "Waterloo School Board Member Area 4", "Waunakee School Board Member Towns of Springfield Dane", "Waunakee School Board Member Village of Waunakee (2)", "Waunakee School Board Member Village of Waunakee (2)", "Wisconsin Heights School Board Member (2)", "Wisconsin Heights School Board Member (2)", "Town of Dunkirk Ref re: rural preservation", "Town of Mazomanie Ref re: ATV/UTV use of roads", "City of Middleton Ref re: storm water utility charge", "DeForest School Dist. Ref Q1 re: $125000000 in bonds", "DeForest School Dist. Ref Q2 re: exceed revenue limit", "Marshall Public Schools Ref re: exceed revenue limit", "River Valley School Dist. Ref re: exceed revenue limit", "Sun Prairie Schl. Dist. Ref Q1 re: $164000000 in bonds", "Sun Prairie Schl. Dist. Ref Q2 re: exceed revenue limit", "Wisconsin Heights Schl Dist. Ref re exceed revenue limit"]
    }
    lambda_handler(event, {})