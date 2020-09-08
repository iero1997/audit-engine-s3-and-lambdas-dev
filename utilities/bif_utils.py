"""
BIF (Ballot Information File) is a CSV table designed to keep track
of ballots per ZIP source file.
"""

import os
#import posixpath
import re
import sys
#import traceback
import json
from pyzbar.pyzbar import decode as barcode_decode
import pprint

import pandas as pd

#from models.Job import Job
from utilities import utils, args, logs
from utilities.zip_utils import open_archive, get_image_file_paths_from_archive,\
    get_next_ballot_paths, analyze_ballot_filepath, get_precinct, get_party, \
    is_archived_file_BMD_type_ess, open_zip_archive, extract_file, get_file_paths
from utilities.styles_from_cvr_converter import convert_cvr_to_styles_ess
from utilities.vendor import dominion_build_effective_style_num, update_CONV_card_code_TO_ballot_type_id_DICT
from utilities import config_d
from utilities.ocr import ocr_text
#from aws_lambda.core import invoke_lambda
from utilities.barcode_parser import get_parsed_barcode
from utilities import launcher
from aws_lambda import s3utils
from models.DB import DB
from models.Ballot import Ballot
from models.BIF import BIF
from models.LambdaTracker import LambdaTracker, wait_for_lambdas

def get_biflist(fullpaths=False, no_ext=False):
    bifnameslist = DB.list_files_in_dirname_filtered('bif', subdir=None, file_pat=r'bif\.csv$', fullpaths=fullpaths)
    if no_ext:
        bifnameslist = [os.path.splitext(f)[0] for f in bifnameslist]
    return bifnameslist

# the following does not appear to be used.
def save_dirname_chunk_by_idx(dirname, group_name, chunk_idx: int, chunk_df, s3flag=None):
    file_name = create_dirname_chunk_filename(dirname, group_name, chunk_idx)
    DB.save_data(data_item=chunk_df, dirname=dirname, name=file_name, format='.csv', s3flag=s3flag)


# def save_dirname_chunk_by_chunkname(dirname, chunk_name: str, chunk_df, s3flag=None):
    # DB.save_data(data_item=chunk_df, dirname=dirname, name=chunk_name, format='.csv', s3flag=s3flag)


def create_dirname_chunk_filename(dirname, group_name, chunk_idx: int):
    chunk_name = create_dirname_chunk_name(dirname, group_name, chunk_idx)
    return f"{chunk_name}.csv"


def create_dirname_chunk_name(dirname, group_name, chunk_idx: int):
    """ 
        generate standard chunk name 
    
            f"{group_root}_{dirname}_chunk_{str(chunk_idx)}"

        group name is normally the archive_rootname
        dirname indicates the task (indirectly)
        chunk_idx is the chunk number
    """
    
    
    group_root = os.path.splitext(group_name)[0]
    return f"{group_root}_{dirname}_chunk_{str(chunk_idx)}"


def is_dirname_chunk_built(dirname, group_name, chunk_idx: int, s3flag=None):
    file_name = create_dirname_chunk_filename(dirname, group_name, chunk_idx)
    return DB.file_exists(file_name, dirname, subdir='chunks', s3flag=s3flag)


def filter_extraction_ballots(argsdict, reduced_df):
    """ given df including a reduced set of ballots from BIF,
        further reduce these ballots to those that have styles
        mapped and meet input parameter specifications.
    """

    logs.sts(f"Total number of ballots in BIF: {len(reduced_df.index)}", 3)

    all_mapped_styles = DB.get_style_nums_with_templates(argsdict)
    utils.sts(f"There are a total of {len(all_mapped_styles)} styles mapped.", 3)
    
    included_styles = argsdict.get('include_style_num')
    if included_styles:
        filtered_styles = [i for i in all_mapped_styles if i in included_styles]
        utils.sts(f"The settings file includes list of styles to include. Filtered to {len(filtered_styles)} styles.", 3)
    else:
        filtered_styles = all_mapped_styles

    excluded_styles = argsdict.get('exclude_style_num')
    if excluded_styles:
        filtered_styles = [i for i in filtered_styles if not i in excluded_styles]
        utils.sts(f"The settings file includes list of styles to exclude. Filtered to {len(filtered_styles)} styles.", 3)

    if excluded_styles or included_styles:
        reduced_df = reduced_df[reduced_df['style_num'].isin(filtered_styles)]

    if not argsdict['include_bmd_ballot_type']:
        reduced_df = reduced_df.loc[reduced_df['is_bmd'] != 1]
        utils.sts(f"The settings file excludes BMD ballots. Filtered to {len(reduced_df.index)} styles.", 3)
    if not argsdict['include_nonbmd_ballot_type']:
        reduced_df = reduced_df.loc[reduced_df['is_bmd'] == 1]
        utils.sts(f"The settings file excludes nonBMD ballots. Filtered to {len(reduced_df.index)} styles.", 3)

    logs.sts(f"Total number of ballots after filters applied for extraction: {len(reduced_df.index)}", 3)


    return reduced_df


def get_dirname_results(dirname, s3flag=None):
    """ return list of s3paths or file_paths to result files, one per archive.
    """

    file_pat=f".*_{dirname}\\.csv"
    file_paths = DB.list_filepaths_in_dirname_filtered(dirname, file_pat=file_pat, s3flag=s3flag)
    return file_paths
    
def get_style_lookup_table(argsdict: dict, s3=False):
    """
    :manual_styles_to_contests_filename str: filename to CSV file with contests and styles table.
    :return: pandas df suitable for lookup of precinct, party, and provide style_num
    """
    
    style_lookup_table_filename = argsdict.get('style_lookup_table_filename')
    if not style_lookup_table_filename:
        return None
    
    utils.sts("style lookup table specified. Loading...", 3, end='')

    style_lookup_table_df = DB.load_data('config', style_lookup_table_filename, user_format=True)
        
    utils.sts("completed", 3)
    
    return style_lookup_table_df


def get_cvr_info(argsdict):
    """ returns ballotid_to_style_dict and parsed_dominion_cvr, if available.
        THIS IS USED FOR BIF CREATION, NOT DEPRECATED.
        But 'BUILT_BALLOTID_TO_STYLE_DICT.json' is not needed.
    """

    vendor = argsdict.get('vendor')
    parsed_dominion_cvr = {}
    ballotid_to_style_dict = {}

    # first get the information ready from the CVR
    # the cvrs are not synchronized with the file archives so we need to load the entire cvr data.

    if vendor == 'Dominion' and not parsed_dominion_cvr:
        cvr_list = argsdict.get('cvr')
        if cvr_list and cvr_list[0] != '(not available)':
            utils.sts('Parsing Dominion CVRs')
            for cvr_path in [c for c in argsdict.get('cvr') if c != '(not available)']:
                # The following parses all the CVR chunks and produces a single dominion CVR.
                parsed_dominion_cvr.update(parse_dominion_cvr_chunks_to_dict(argsdict, cvr_path))
        elif argsdict.get('use_built_ballotid_to_style_dict'):
            #ballotid_to_style_dict = DB.load_style(name='BUILT_BALLOTID_TO_STYLE_DICT', silent_error=False)
            ballotid_to_style_dict = DB.load_data(dirname='styles', name='BUILT_BALLOTID_TO_STYLE_DICT.json')
           

    elif vendor == 'ES&S' and not ballotid_to_style_dict:
        utils.sts('Parsing ES&S CVRs')
        """
        To avoid loading all cvr files into one dataframe and risking memory overflow,
        styles_dict is generated from each CVR file and then merged.
        """
        utils.sts("creating ballotid to style lookup dict...", 3)

        # if no CVRs exist, this just returns empty dict.
        ballotid_to_style_dict = convert_cvr_to_styles_ess(argsdict, silent_error=True)
        
    return ballotid_to_style_dict, parsed_dominion_cvr
            

def genbif_from_cvr(argsdict: dict):
    """
        If CVR files are available with style information, this 
        function can be used to generate the BIF data file.
        
        THIS RUNS VERY FAST NOW, do not neet lambdas if CVR exsists.
    """

    utils.sts('Generating BIFs')

    # if cvr is provided, us it for information here.
    ballotid_to_style_dict, parsed_dominion_cvr = get_cvr_info(argsdict)

    # check to see if style lookup table is specified.
    style_lookup_table_df = get_style_lookup_table(argsdict)
    
    pstyle_region_str = argsdict.get('pstyle_region')
    pstyle_region_dict = json.loads(pstyle_region_str) if (pstyle_region_str) else None
    pstyle_pattern = argsdict.get('pstyle_pattern', '')
    vendor = argsdict.get('vendor')

    for archive_idx, source in enumerate(argsdict['source']):
        archive_basename = os.path.basename(source)
        archive_root = os.path.splitext(archive_basename)[0]
        archive = open_archive(argsdict, archive_basename)

        df_dict = {}        # to save time, we will build the dataframe as a dict of dict, then in one swoop create the dataframe.
        file_paths = get_image_file_paths_from_archive(archive)
        utils.sts(f"Total of {len(file_paths)} image files in the archive")

        # now scan archives for additional information.

        for index, file_path in enumerate(file_paths):
            style = card_code = ballot_type_id = ''
            _, ballot_file_paths = get_next_ballot_paths(index, archive, file_paths)
            _, _, ballot_id = analyze_ballot_filepath(ballot_file_paths[0])

            # initialize defaults in local dict
            bifdict = {c: '' for c in BIF.get_bif_columns()}
            party = bifdict['party'] = get_party(argsdict, file_path)
            precinct = bifdict['precinct'] = get_precinct(argsdict, file_path)
            bifdict['sheet0'] = '0'
            
            #utils.sts(f"Processing {ballot_id} precinct {precinct} party {party}", 3)
            if vendor == 'Dominion':
                if parsed_dominion_cvr:
                    try:
                        ballot_rec = parsed_dominion_cvr[ballot_id]
                    except KeyError:
                        bifdict['comments'] = "Couldn't find ballot id in the CVR dict"
                    else:
                        for field in ['style_num', 'cvr_name', 'card_code', 'ballot_type_id']:
                            bifdict[field] = ballot_rec[field]
                        bifdict['is_bmd'] = '1' if ballot_rec['is_bmd'] else '0'
                        bifdict['sheet0'] = str(ballot_rec['sheet0'])

                else:
                    try:
                        style_num = str(ballotid_to_style_dict[ballot_id])
                    except (KeyError, TypeError):
                        utils.exception_report(f"ballot_id {ballot_id} found in {source} but not in ballotid_to_style_dict. Skipping.")
                        continue
                    bifdict['style_num'] = bifdict['card_code'] = style_num

                # the following creates the CONV_card_code_TO_ballot_type_id_DICT
                card_code = bifdict['card_code']
                
                update_CONV_card_code_TO_ballot_type_id_DICT(card_code, ballot_type_id)

            elif vendor == 'ES&S':

                is_bmd = is_archived_file_BMD_type_ess(argsdict, archive, ballot_file_paths[0])
                bifdict['is_bmd'] = '1' if is_bmd else '0'

                if ballotid_to_style_dict:
                    try:
                        style = str(ballotid_to_style_dict[int(ballot_id)])
                    except KeyError:
                        utils.exception_report(f"ballot_id {ballot_id} found in {source} but not in cvr. Skipping.")
                        continue
                    card_code = style
                    
                elif style_lookup_table_df is not None:
                    # style lookup table has been specified and loaded. 
                    # look up style based on party and precinct values from path.
                    #To select a row based on multiple conditions you can use &:
                    
                    try:
                        lookup_row = style_lookup_table_df.loc[(style_lookup_table_df['party'] == party) & (style_lookup_table_df['precinct'] == int(precinct))]
                    except Exception as err:
                        utils.exception_report(f"style lookup table format problem: {err}")
                        sys.exit(1)
                    if len(lookup_row) > 1:
                        utils.exception_report(f"Duplicate row values in style lookup table: {lookup_row}")
                    
                    is_bmd = is_archived_file_BMD_type_ess(argsdict, archive, ballot_file_paths[0])
                    bifdict['is_bmd'] = '1' if is_bmd else '0'
                    bifdict['style_num'] = str(lookup_row['style_num'].values.item())
                    bifdict['archive_basename'] = archive_basename
                    bifdict['ballot_id'] = ballot_id
                    bifdict['file_paths'] = ';'.join(ballot_file_paths)
                    bifdict['card_code'] = str(lookup_row['card_code'].values.item())
                
                else:
                    # if we do not have the ballot_id_to_style dict, this happens if there is no CVR.
                    # we must determine the style and bmd status by inspection of ballots.
                    # this can be very time consuming!
                    # NOTE: should use genbif_from_ballots
                   

                    # @@ Should check to see if bif files already exist and appear to have the correct number of records.
                    bifdict = create_bif_dict_by_reading_ballot(argsdict, ballot_id, index, archive_basename, archive, ballot_file_paths,
                                                                pstyle_region_dict, pstyle_pattern)

            df_dict[index] = bifdict

        # create the dataframe all at once.
        df = pd.DataFrame.from_dict(df_dict, "index")
        DB.save_data(data_item=df, dirname='bif', name=f"{archive_root}_bif.csv")
        
def read_pstyle_from_image(image, pstyle_region_dict, pstyle_pattern):
    if pstyle_region_dict:
        # use this field in ES&S case for printed style number for now.
        # card_code not fully decoded and not sure if it creates this value. 
        working_image = utils.extract_region(image, pstyle_region_dict)
        pstyle_num = ocr_text(working_image)
        if pstyle_pattern:
            pstyle_num = utils.apply_regex(pstyle_num, pstyle_pattern)
        return pstyle_num
    return None
    

def read_pstyle_from_image_if_specd(argsdict, image):
    if argsdict['pstyle_region']:
        pstyle_region_dict = argsdict['pstyle_region']
        if not isinstance(pstyle_region_dict, dict):
            logs.exception_report(f"pstyle_region not a dict: '{pstyle_region}'")
        pstyle_pattern = argsdict['pstyle_pattern']
        pstyle_num = read_pstyle_from_image(image, pstyle_region_dict, pstyle_pattern)
        return pstyle_num
    else:
        return None
    
    
def create_bif_dict_by_reading_ballot(argsdict, ballot_id, index, archive_basename, archive, ballot_file_paths,
                                      pstyle_region_dict, pstyle_pattern, chunk_idx):
    utils.sts(f"Chunk:{chunk_idx} index:{index} Ballot:{ballot_id} in {archive_basename} -- building bif record...", 3)
    ballot = get_ballot_from_image_filepaths(argsdict, file_paths=ballot_file_paths, archive_basename=archive_basename, archive=archive)

    row = {c: '' for c in BIF.get_bif_columns()}
    row['file_paths'] = ';'.join(ballot_file_paths)

    for field in ['archive_basename', 'ballot_id', 'precinct', 'party', 'card_code', 'style_num']:
        row[field] = ballot.ballotdict[field]
    row['is_bmd'] = '1' if ballot.ballotdict['is_bmd'] else '0'
    row['sheet0'] = str(ballot.ballotdict['sheet0'])
    row['ballot_type_id'] = ''      # this is specific to Dominion
        
    pstyle_num = read_pstyle_from_image(ballot.ballotimgdict['images'][0], pstyle_region_dict, pstyle_pattern)
    if pstyle_num:
        row['style_num'] = pstyle_num
    utils.sts(f"bif record:{pprint.pformat(row)}", 3)
    return row
    

def genbif_from_ballots(argsdict: dict):
    """
    This function is used when no cvr exists and we need to scan all the
    ballots to create bifs. This is a slow process, so we create
    tasklist for lambdas processing.
    """

    if argsdict['use_s3_results']:
        DB.delete_dirname_files_filtered(dirname='bif', s3flag=True, file_pat=None)
        DB.delete_dirname_files_filtered(dirname='bif', subdir='chunks', s3flag=True, file_pat=None)

    # Clear lambda tracker catche
    if argsdict.get('use_lambdas'):
        LambdaTracker.clear_requests()

    max_chunk_size = argsdict.get('genbif_ballots_per_chunk', 200)
    max_concurrency = argsdict.get('max_lambda_concurrency', 1000)
    chunk_limit = argsdict.get('genbif_chunk_limit', None)
    num_archives = len(argsdict['source'])
    max_concurrency = max_concurrency // num_archives

    utils.sts('Generating tasklists to scan ballots to create bifs')
    for archive_idx, source in enumerate(argsdict['source']):
        archive_basename = os.path.basename(source)
        archive = open_archive(argsdict, archive_basename) # will open on s3 directly if using s3
        file_paths = get_image_file_paths_from_archive(archive)
        utils.sts(f"Total of {len(file_paths)} image files in the archive")

        filelist = []
        for index, file_path in enumerate(file_paths):
            _, ballot_file_paths = get_next_ballot_paths(index, archive, file_paths)
            #_, _, ballot_id = analyze_ballot_filepath(ballot_file_paths[0])

            filelist.append( ';'.join(ballot_file_paths) )
        utils.sts(f"Total of {len(filelist)} ballots in the archive")
        archive.close()

        chunks_lol = utils.split_list_into_chunks_lol(item_list=filelist, max_chunk_size=max_chunk_size, max_concurrency=max_concurrency)
        num_chunks = len(chunks_lol)
        utils.sts(f"Split into {num_chunks} chunks with maximum of {max_chunk_size} ballots each.")
        #count = 0
        
        # The loop below may delegate processing to lambdas.
        # Should perform consistency checks here (or before this point) to avoid any costly errors, such as:
        #   1. output bucket specified exists and is writeable.
        # It would be best to make these checks as settings file is initially processed.
        
        
        for chunk_idx, filelist in enumerate(chunks_lol):
            if chunk_limit and chunk_idx >= chunk_limit:
                break
            utils.sts(f"Processing chunk #{chunk_idx} with {len(filelist)} ballots", 3)
            
            build_one_chunk(
                argsdict=argsdict,
                dirname='bif',
                subdir='chunks',
                chunk_idx=chunk_idx, 
                filelist=filelist, 
                group_name=archive_basename, 
                task_name='bif',
                incremental = argsdict['incremental_genbif']
                )   # this may delegate to one lambda
            #count = count+1
            if argsdict['use_lambdas'] and not archive_idx and not chunk_idx and argsdict['one_lambda_first']:
                if not wait_for_lambdas(argsdict, task_name='bif'):
                    utils.exception_report("task 'bif' failed delegation to lambdas.")
                    sys.exit(1)           


    wait_for_lambdas(argsdict, task_name='bif')      # @@ wait_for_lambdas should be enhanced to track specific tasks or better use SQS messaging.
    
    for archive_idx, source in enumerate(argsdict['source']):
        archive_rootname = os.path.splitext(os.path.basename(source))[0]

        dirname = 'bif'

        DB.combine_dirname_chunks(
            dirname=dirname, subdir='chunks', 
            dest_name=f"{archive_rootname}_{dirname}.csv", 
            file_pat=fr"{archive_rootname}_{dirname}_chunk_\d+\.csv")
            
        logs.get_and_merge_s3_logs(dirname='bif', rootname='log', chunk_pat=fr'{archive_rootname}_{dirname}_chunk_\d+', subdir='chunks')
        logs.get_and_merge_s3_logs(dirname='bif', rootname='exc', chunk_pat=fr'{archive_rootname}_{dirname}_chunk_\d+', subdir='chunks')



def build_one_chunk(argsdict, dirname, subdir=None, chunk_idx=None, filelist=None, group_name='', task_name='', incremental=False):
    """ This entry point either delegates to lambda or executes here.
        this is now a general function that either goes directly to delgated function or
        launches lambda to complete the task.
        
        Chunk naming convention: 
            {archiveroot}_{bif|marks}_chunk_{index}.csv
        
    """
    
    if incremental:
        if is_dirname_chunk_built(dirname, group_name=group_name, chunk_idx=chunk_idx):
            utils.sts(f"Chunk {chunk_idx} of group {group_name} already built and exists locally", 3)
            return
            
    # NOTE: df is passed directly, then must fill na values.
    #   tasklist_df.fillna('', inplace=True)

    #import pdb; pdb.set_trace()
    task_args = {
        'argsdict':         argsdict,
        'dirname':          dirname,
        'subdir':           subdir,
        'group_name':       group_name,
        'chunk_idx':        chunk_idx,
        'chunk_name':       create_dirname_chunk_name(dirname, group_name, chunk_idx),
        'filelist':         filelist,
        'task_name':        task_name,
        }

    if argsdict.get('use_lambdas'):
        # this delegates the task to lambdas.
        delegate_task_chunk(task_args)
    else:
        # otherwise, we skip delegation and accepting delegation, and launch task directly.
        launcher.launch_task(task_args, s3flag=argsdict['use_s3_results'])


def delegate_task_chunk(task_args):

    argsdict = task_args.get('argsdict')
    task_name = task_args.get('task_name')
    if argsdict.get('save_lambda_task_args'):
        # Just save the task arguments to a file and stop. This file will be used to test lambda locally
        # Save only first chunk in file if 'save_lambda_task_args' set True. So that we can debug lambda for first chunk arguments.
        with open(f'./input_files/{task_name}_lambda_task_args.json', 'w+') as f:
            f.write(json.dumps({"task_args": task_args}))
            f.close()
            print(f'task_args is written to file: /input_files/{task_name}_lambda_task_args.json')
        sys.exit(0)

    utils.sts(f"Submitting chunk #{task_args['chunk_idx']} for task {task_args['dirname']}.", 3)
    if config_d.MOCK_LAMBDA:
        request_id = 'fake_lambda_id'
    else:        
        response = s3utils.invoke_lambda(
            function_name=f"arn:aws:lambda:us-east-1:174397498694:function:{argsdict['lambda_function']}",
            async_mode=True,
            custom_payload={'task_args': task_args},
            region='us-east-1'
            )
        request_id = response['ResponseMetadata']['RequestId']

    LambdaTracker.add_new_request(
        request_id=request_id,
        chunk_name=task_args['chunk_name'],
        task_args=task_args
        )
    

        
        

def delegated_build_bif_chunk(dirname, task_args, s3flag=None):
    """ this function is suitable for execution in lambda after delegation
        can also use by local machine even if s3 is used for output.
    """

    # task_args: argsdict, archive_basename, chunk_idx, filelist
    args.argsdict = argsdict = task_args['argsdict']
    
    chunk_idx   = task_args['chunk_idx']
    filelist    = task_args['filelist']                         # the list of files to be processed in this chunk.
    subdir      = task_args['subdir']
    chunk_name  = task_args['chunk_name']
    
    archive_basename = task_args['group_name']
    archive = open_archive(argsdict, archive_basename)          # if using s3, this will open the archive on s3.
    full_file_list = get_file_paths(archive)
    if not full_file_list:
        raise LookupError(f"archive {archive_basename} appears empty")

    pstyle_region_dict = argsdict.get('pstyle_region')
    pstyle_pattern = argsdict.get('pstyle_pattern', '')

    df_dict = {}        # to save time, we will build the dataframe as a dict of dict, then in one swoop create the dataframe.
                        # format is {1: {'lkadsjf': asdlkfj, }, 2: {...} ...)
    
    #filelist = filelist[0:5]
    for index, file_paths in enumerate(filelist):
    
        ballot_file_paths = re.split(r';', file_paths)
        _, _, ballot_id = analyze_ballot_filepath(ballot_file_paths[0])

        df_dict[index] = create_bif_dict_by_reading_ballot(argsdict, 
                                                            ballot_id, 
                                                            index, 
                                                            archive_basename, 
                                                            archive, 
                                                            ballot_file_paths,
                                                            pstyle_region_dict, 
                                                            pstyle_pattern,
                                                            chunk_idx)
    # create the dataframe all at once.
    #print(df_dict)
    chunk_df = pd.DataFrame.from_dict(df_dict, "index")

    DB.save_data(data_item=chunk_df, dirname=dirname, subdir=subdir, name=chunk_name, format='.csv', s3flag=s3flag)



def parse_dominion_cvr_chunks_to_dict(argsdict: dict, cvr_path: str) -> dict:
    """
        Using Lambdas for this operation was found not to be necessary once
        we optimized the operation of creating the pandas tables.

        read json CVR file in Dominion format.
        create dict keyed by ballot_id with dict of attributes.
        'ballot_type_id'    - 1-180 code BallotTypeId from CVR
        'is_bmd'               - 1 if ballot is bmd
        'card_code'         - style code found on the ballot
        'cvr_name'          - name of the cvr chunk (filename without path)
        'style_num'         - style indicator (str)
        'sheet0'            - sheet value decoded from card_code
        
        This is not currently extracting the list of contests included in the CVR.
        

    """
    cvr_dict = {}
    cvr_reg = r'CvrExport_\d+\.json'
    archive = open_zip_archive(cvr_path)
    cvrlist = [n for n in archive.namelist() if re.match(cvr_reg, n)]
    total_num = len(cvrlist)
    for index, name in enumerate(cvrlist):
        cvr_name = os.path.basename(name)
        if (index+1) % 100 == 0:
            utils.sts(f"Parsing CVR JSON file {cvr_name} #{index}: of {total_num} ({round(100 * (index+1) / total_num, 2)}%)")

        data = json.loads(archive.read(name))
        for session in data['Sessions']:
            tabulator_id = session.get('TabulatorId')
            batch_id = session.get('BatchId')
            record_id = session.get('RecordId')
            is_bmd = True if session.get('SessionType') == 'QRVote' else False
            try:
                card_code = session['Original']['Cards'][0]['Id']
            except KeyError:
                card_code = 0
            try:
                ballot_type_id = session['Original']['BallotTypeId']
            except KeyError:
                ballot_type_id = 0

            style_num, sheet0 = dominion_build_effective_style_num(argsdict, card_code, ballot_type_id)

            ballot_id = f'{tabulator_id:05d}_{batch_id:05d}_{record_id:06d}'
            cvr_dict[ballot_id] = {
                'is_bmd': is_bmd,
                'cvr_name': cvr_name,
                'style_num': style_num,             # internal style number LPSETTT Lang, Party, Sheet, ETTT ExternalId , ballot_type_id
                'card_code': str(card_code),
                'ballot_type_id': int(ballot_type_id),
                'sheet0': sheet0,
            }

    return cvr_dict


global archive
archive = None

def get_ballot_from_image_filepaths(argsdict:dict, file_paths:list, mode='archive', archive_basename=None, archive=None):
    """ given list of one or two filepaths that comprise the ballot,
        access the images and extract the style and BMD status information.
        creates ballot object and returns it.
        
        if argsdict['style_from_party'] provides a list of style nums for each party, then
            set style_num according to that but also leave card_code equal to what was read from the card.
        
    """
    # this call does nothing more than initialize the instance data
    ballot = Ballot(argsdict, file_paths=file_paths, archive_basename=archive_basename)

    if mode=='local':
        ballot.load_source_files(archive=None, mode=mode)
        
    elif mode=='archive':
        ballot_id = ballot.ballotdict['ballot_id']
        precinct = ballot.ballotdict['precinct']

        #    utils.sts (f"opening archive: '{archive_basename}'...", 3)
        #    #archives_folder_path = argsdict['archives_folder_path']
        #    archive = open_archive(argsdict, archive_basename)
        #    current_archive_basename = archive_basename

        if not ballot.load_source_files(archive):
            string = f"EXCEPTION: Could not load source files from archive {archive_basename} for ballot_id: {ballot_id} Precinct: {precinct}"
            utils.exception_report(string)
            sys.exit(1)

    ballot.get_ballot_images()      # this reads images from PDFs
    ballot.align_images()
    ballot.read_style_num_from_barcode(argsdict)
 
# this now handled after bif is built -- see set_style_from_party_if_enabled
#    style_from_party = argsdict.get('style_from_party', '')
#    if style_from_party:
#        party = ballot.ballotdict['party']
#        if not party:
#            utils.exception_report("style_from_party was specified but no party is available")
#            return
#        style_from_party_dict = eval(style_from_party)
#        try:
#            ballot.ballotdict['style_num'] = style_from_party_dict[party]
#        except KeyError:
#            utils.exception_report(f"party {party} not found in style_from_party {style_from_party} directive")

    if not ballot.ballotdict['card_code']:
        # here, we find that we are unable to read the style from the ballot.
        # see if this is a ballot with a barcode

        barcodes = barcode_decode(ballot.ballotimgdict['images'][0])
        ballot.ballotdict['is_bmd'] = bool(barcodes)

    return ballot

'''
def send_cvr_chunk(file_list: list, chunk_name: str):
    reg = r'(\d+)\w\..+$'
    ballot_ids = []
    for f in file_list:
        ballot_id = re.search(reg, f)
        if ballot_id:
            ballot_ids.append(int(ballot_id.group(1)))
    chunk = CVR.data_frame[CVR.data_frame['Cast Vote Record'].isin(ballot_ids)]
    item = f"{Job.get_path_name()}cvr_chunks/{chunk_name}-cvr.csv"
    s3 = boto3.resource('s3')
    obj = s3.Object(config_d.TASKS_BUCKET, item)
    buff = chunk.to_csv(index=False)
    obj.put(Body=buff)
'''

def set_style_from_party_if_enabled(argsdict, bif_df):
    """ if 'style_from_party' directive exists, substitute new 
        style_nums in table 
    """

    style_from_party_dict = get_style_from_party_dict(argsdict)
    if style_from_party_dict:
        bif_df['style_num'] = bif_df.apply(lambda x: style_from_party_dict.get(x.get('party')), axis=1)

    return bif_df
    
    
def one_style_from_party_if_enabled(argsdict, style_num, party):
    style_from_party_dict = get_style_from_party_dict(argsdict)
    if style_from_party_dict:
        return style_from_party_dict.get(party, style_num)
    return style_num

def get_style_from_party_dict(argsdict):
    """ @@TODO this should use json.loads instead of eval """
    style_from_party = argsdict.get('style_from_party', '')
    if style_from_party:
        return eval(style_from_party)
    return None    
    

def combine_archive_bifs():
    """
    BIF tables are constructed for each archive. Combine these into a single BIF table.
    Returns full_bif_df. 
    
    NOTE! This function does not create any new files.
    
    """
    utils.sts("Combining archive bifs", 3)
    
    return DB.combine_dirname_dfs(dirname='bif', file_pat=r'_bif\.csv')
    

def combine_and_sanitize_bifs(argsdict):
    """ in some cases, card_code may be misread or pstyle may not be read correctly.
        We can largely remove errors by correcting the incorrectly read pstyle to predominant pstyle for that card_code.
        This can only be done with a unified bif table.
    """
    pass


def save_failing_ballots(argsdict):
    """ given list of ballots in inputfile, copy the original ballot image files
        to (job_folder_path)/styles/(ballot_id) folders
        
        this function
            1. builds single bif table.
            2. looks each ballot up.
            3. using entry, opens the indicated archive and extracts the original file.
            4. saves the file in folder of jobname and ballot_id in styles, see above.
    """
    
    full_bif_df = combine_archive_bifs()
    
    ballot_list = argsdict['ballotid']
    
    #archives_folder_path = argsdict['archives_folder_path']
    opened_archive_basename = ''
    archive = None
    
    for ballot_id in ballot_list:
        utils.sts(f"processing ballot_id:{ballot_id}", 3)
        rows = full_bif_df.loc[full_bif_df['ballot_id'] == ballot_id]       # select set of rows with value in column_name equal to some_value.
        
        archive_basename = rows['archive_basename'].values.item()     # return one item from a row
        file_paths_str = rows['file_paths'].values.item()
        file_paths = file_paths_str.split(';')
        
        dest_dirpath = DB.dirpath_from_dirname('styles')
        
        if archive_basename != opened_archive_basename:
            if opened_archive_basename:
                archive.close()
            archive = open_archive(argsdict, archive_basename)
            opened_archive_basename = archive_basename
            
        for file_path in file_paths:
            basename = os.path.basename(file_path)
            dest_filepath = os.path.join(dest_dirpath, ballot_id, basename)
            extract_file(archive, file_path, dest_filepath)
            utils.sts(f"...extracted:{file_path} to {dest_filepath}", 3)
        
    if opened_archive_basename:
        archive.close()
        
        
def reprocess_failing_ballots(argsdict):
    """ given list of ballots in inputfile, attempt to align these ballots.

            1. builds single bif table.
            2. looks each ballot up.
            3. using the entry, call 
                get_ballot_from_image_filepaths(argsdict:dict, file_paths:list, mode=local)
    """
    
    dirpath = DB.dirpath_from_dirname('styles')
    ballot_list = argsdict['ballotid']
    
    for ballot_id in ballot_list:
        local_file_path = f"{dirpath}{ballot_id}/{ballot_id}.tif"
        local_file_paths = [local_file_path]
        
        ballot = get_ballot_from_image_filepaths(argsdict, local_file_paths, mode='local')
        ballot.get_timing_marks()       # for each image, capture the timing marks to ballot instance.
        
        
def create_bif_report(argsdict):
    """ Analyze ballots based on information in the BIF table.
        archive_basename,ballot_id,file_paths,cvr_file,precinct,party,style_num,card_code,ballot_type_id,sheet0,is_bmd,style_roi_corrupted,comments
    """
    
    full_bif_df = combine_archive_bifs()
    
    unique_ballots_num  = len(list(full_bif_df['ballot_id'].unique()))
    records_num         = len(full_bif_df.index)
    dups_num            = records_num - unique_ballots_num

    archives_list       = list(full_bif_df['archive_basename'].unique())
    archives_num        = len(archives_list)

    cvr_files_list      = list(full_bif_df['cvr_file'].unique())
    cvr_files_num       = len(cvr_files_list) if cvr_files_list[0] else 0

    precincts_list      = list(full_bif_df['precinct'].unique())
    precincts_num       = len(precincts_list)

    party_list          = list(full_bif_df['party'].unique())
    party_num           = len(party_list)

    # style_num is now filtered with pstyle_pattern during bif creation.
    # so this will be redundant for newer bif data.
    # pstyle_pattern = argsdict.get('pstyle_pattern')
    # if pstyle_pattern:
        # full_bif_df['style_num'] = full_bif_df['style_num'].map(lambda style_num: utils.apply_regex(style_num, pstyle_pattern))
        
    style_list          = list(full_bif_df['style_num'].unique())
    style_num_num       = len(style_list)

    card_code_list      = sorted(list(full_bif_df['card_code'].unique()))
    card_code_num       = len(card_code_list)
    no_card_code_num    = len(full_bif_df.loc[full_bif_df['card_code'] == ''])

    bmd_num             = len(full_bif_df.loc[full_bif_df['is_bmd'] != 0])

    corrupted_num       = len(full_bif_df.loc[full_bif_df['style_roi_corrupted'] != ''])

    sheet0_list         = list(full_bif_df['sheet0'].unique())
    sheet0_num          = len(sheet0_list)
    each_sheet_num_list = []
    for sheet0 in sheet0_list:
        each_sheet_num_list.append(len(full_bif_df.loc[full_bif_df['sheet0'] == sheet0].index))
    
    utils.sts( f"               BIF REPORT\n"
               f"Election Name:                     {argsdict['election_name']}\n"
               f"Number of Ballot Archives:         {archives_num}\n"
               f"Total number of BIF records:       {records_num}\n"
               f"Unique ballot_ids:                 {unique_ballots_num}\n"
               f"Duplicate ballot_ids:              {dups_num}\n"
               f"Number of CVR files:               {cvr_files_num}\n"
               f"Number of precincts:               {precincts_num}\n"
               f"Number of parties:                 {party_num}\n"
               f"Number of style_nums:              {style_num_num}\n"
               f"Number of card_codes:              {card_code_num}\n"
               f"Number of ballots w/o card_codes:  {no_card_code_num}\n"
               f"Number of BMD ballots:             {bmd_num}\n"
               f"Number of corrupted ballots:       {corrupted_num}\n"
               f"Number of different sheets:        {sheet0_num}\n"
                "    Sheet0  Count"
               )
               
    for sheet0, count in enumerate(each_sheet_num_list):
        utils.sts(f"       {sheet0}    {count}")
               
    if card_code_num <= style_num_num:
        
        card_code_to_styles_dict = {}
        utils.sts("Card Code       | P | styl | pstyle")
        for card_code in card_code_list:
            styles_per_card_code = list(full_bif_df.loc[full_bif_df['card_code'] == card_code]['style_num'].unique())
            parsed_cc_style = get_parsed_barcode(card_code)
            card_code_to_styles_dict['card_code'] = styles_per_card_code
            ones = '-'
            if card_code:
                bin_cc = bin(int(card_code, 0))
                ones = bin_cc.count('1')
                if ones and (ones % 2) == 0:
                    # even parity is an error in ES&S card_code
                    ballot_ids_with_card_code = list(full_bif_df.loc[full_bif_df['card_code'] == card_code]['ballot_id'])
                    utils.sts(f"Even parity is an error -- ballot_ids:{ballot_ids_with_card_code}", 3)
                    
            utils.sts(f"{'%15s' % card_code} | {ones} | {'%4s' % parsed_cc_style} | {styles_per_card_code}")
    
    bmdsdf = full_bif_df.loc[full_bif_df['ballot_id'].isin(['29642','14538','15422','15014'])]
    utils.sts(f"bmds\n{bmdsdf[['ballot_id','precinct','party','style_num','card_code']]}")


def build_dirname_tasks(argsdict, dirname, subdir=None, ballots_per_chunk=200):
    """ with all bif chunks created, scan them and create tasks in dirname.
        each task contains records from bif for ballots to be included
        in the processing chunk. These are written to extraction_tasklists folder.
        For lambdas processing mode, these tasklists could launch an extraction lambda
    """

    utils.sts(f"Building tasklists to {dirname}/{subdir}...", 3)

    bifpaths = get_biflist(argsdict)     # returns either s3path list or pathlist, depending on argsdict['use_s3_results']
    max_concurrency = argsdict.get('max_lambda_concurrency', 1000)

    tasks_queued = 0
    total_ballots_queued = 0
    
    DB.delete_dirname_files_filtered(dirname=dirname, subdir=subdir)

    for bif_pathname in bifpaths:
        utils.sts(f"  Processing bif {bif_pathname}...", 3)
        BIF.load_bif(bif_pathname=bif_pathname)        # uses s3 based on DB.MODE
        bif_basename = os.path.basename(bif_pathname)
        archive_name = re.sub(r'_bif\.csv$', '', bif_basename)

        reduced_df = BIF.df_without_corrupted()
        
        # the following should be moved to bif generation phase (generally not done)
        reduced_df = set_style_from_party_if_enabled(argsdict, reduced_df)

        # the following reduces the ballots selected based on input
        # parameters and whether the ballots have been successfully mapped.
        filtered_df = filter_extraction_ballots(argsdict, reduced_df)
        
        sorted_df = filtered_df.sort_values(by=['cvr_file'])     #ascending - bool or list of bool, default True; inplace - bool, default False


        num_ballots_in_bif = len(BIF.df.index)
        num_to_be_extracted = len(sorted_df.index)
        num_excluded = num_ballots_in_bif - num_to_be_extracted

        utils.sts(f"Total of {num_ballots_in_bif} ballots, {num_to_be_extracted} to be extracted, {num_excluded} ballots excluded.", 3)
        if not num_to_be_extracted:
            continue
            
        chunks_lodf = utils.split_df_into_chunks_lodf(df=sorted_df, max_chunk_size=ballots_per_chunk, max_concurrency=max_concurrency)
        num_chunks = len(chunks_lodf)

        utils.sts(f"Split into {num_chunks} chunks, each with no more than {ballots_per_chunk} ballots each.")

        for chunk_index, chunk_df in enumerate (chunks_lodf):
            chunk_name = f"{archive_name}_chunk_{'%4.4u' % (chunk_index)}.csv"
            utils.sts(f"Creating {dirname} chunk: {chunk_name}...", 3)
            
            DB.save_data(
                data_item=chunk_df, 
                dirname=dirname,
                subdir=subdir,
                name=chunk_name, 
                )
            tasks_queued += 1
            total_ballots_queued += len(chunk_df.index)


    utils.sts(f"Total of {tasks_queued} {dirname} tasks queued with a total of {total_ballots_queued} ballots.", 3)


def parse_tasklist_name(tasklist_name):
    """ pull out the group_name, chunk_idx from tasklist_name
        tasklist_name has the following format:
            f"{group_name}_chunk_{chunk_idx}.csv"
    """
    match = re.search(r'^(.*)_chunk_(.*)\.csv$', tasklist_name)
    tasklist_dict = {
        'group_name': match[1],
        'chunk_idx': match[2],
        }
    return tasklist_dict


def get_status_genbif_from_ballots(argsdict):
    pass

if __name__ == "__main__":

    
    reprocess_failing_ballots()