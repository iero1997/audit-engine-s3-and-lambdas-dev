import re
import sys
import os
#import time

import pandas as pd
#import boto3
#from boto3.s3.transfer import TransferConfig

from utilities import utils, args, logs
from utilities.analysis_utils import analyze_images_by_style_rois_map_df, analyze_bmd_ess, analyze_bmd_dominion
from utilities.zip_utils import open_archive
from utilities.style_utils import get_style_fail_to_map
#from aws_lambda import s3utils
from utilities.bif_utils import get_biflist, one_style_from_party_if_enabled, build_one_chunk, build_dirname_tasks
#from utilities import launcher

#from models.BIF import BIF
from models.Ballot import Ballot
from models.DB import DB
from models.LambdaTracker import LambdaTracker, wait_for_lambdas


def build_extraction_tasks(argsdict):
    """ build tasklists that will drive lambdas processing, with one tasklist passed to each contest.
    """
    genmarks_ballots_per_chunk = argsdict.get('genmarks_ballots_per_chunk', 200)
    build_dirname_tasks(argsdict, dirname='marks', subdir='tasks', ballots_per_chunk=genmarks_ballots_per_chunk)


def extract_vote_from_ballot(
        argsdict: dict,
        ballot: Ballot,
        rois_map_df,
        contests_dod,
        ballot_style_overrides_dict,
        #cvr_ballotid_to_style_dict, -- no longer uses this because BIF table has the information, accessed through Ballot.
        ):
    """ ACTIVE
    
    This function may run in AWS Lambda.
    Ballot images files have just been extracted from archive.
    :param ballot: Ballot from which votes should be extracted.
        ballot.ballotdict['is_bmd'] should be initialized
    :param rois_map_df: DataFrame objec with map of targets on all styles.
    :return: DataFrame with ballot marks info.
    """
    ballot_id = ballot.ballotdict['ballot_id']

    if ballot.ballotdict['is_bmd']:

        if argsdict['vendor'] == 'ES&S':
            # this is ES&S Specific
            # the following function analyzes the EV ballot using OCR and
            #   ballot_marks_df also contains the barcode strings for each selection (if successful).
            ballot_marks_df = analyze_bmd_ess(argsdict, ballot, rois_map_df, contests_dod)

        elif argsdict['vendor'] == 'Dominion':
            ballot_marks_df = analyze_bmd_dominion(argsdict, ballot, rois_map_df, contests_dod)

        if ballot_marks_df is None:
            string = "### EXCEPTION: BMD ballot analysis failed.\n" \
                     + f"ballot_id: {ballot_id} Precinct: {ballot.ballotdict['precinct']}"
            utils.exception_report(string)
            return None

        return ballot_marks_df

    # otherwise, this is a nonBMD ballot

    ballot.align_images()
    style_num = ballot.read_style_num_from_barcode(argsdict)
    if not style_num:
        # the barcode conversion failed. Exception handled internal to the call above.
        return None

    style_num = one_style_from_party_if_enabled(argsdict, style_num, ballot.ballotdict['party'])
    ballot.ballotdict['style_num'] = style_num

    ballot.get_timing_marks()       # for each image, capture the timing marks to ballot instance.

    if get_style_fail_to_map(style_num):
        # note that this reads the style file keeps a list of styles so it does not have to
        # read the style file each time.
        # we can't process this ballot because we were unable to map the style.
        # this will also return true if the style is out of range.

        # first we will check if there are any merged styles
        error_flag = True
        merged_styles_str = argsdict.get('merged_styles', '')
        if merged_styles_str:
            #merged_styles = json.loads(merged_styles_str)
            merged_styles = eval(merged_styles_str)
            if style_num in merged_styles or int(style_num) in merged_styles:
                eff_style_num = str(merged_styles.get(style_num, merged_styles.get(int(style_num), '')))
                utils.sts(f"INFO: Style {style_num} did not map, using merged style {eff_style_num}", 3)
                error_flag = False
                style_num = eff_style_num

        if error_flag:
            utils.exception_report(f"### EXCEPTION: style failed to map and no merged style found, ballot_id: "
                     f"{ballot_id} style: {style_num} Precinct: {ballot.ballotdict['precinct']}")
            return None

    # Get the subset of rows from the rois_map_df related to this style
    style_rois_map_df = rois_map_df.loc[rois_map_df['style_num'] == int(style_num)]

    """---------------------------------------------------------------------
    Proceed with analysis
        Given ballot object which provides the style_num and rois_map_df
        Lookup records that correspond to the style_num from rois_map_df
        For each contest and option line, access roi of ballot and interpret
        the mark. Add record to the marks_df for each contest/option pair.
        Also evaluates each contest regarding overvotes and completed num_votes
        based on the overvote status, and fills in each contest header record
        regarding overvotes, undervotes.
    """

    utils.sts(f"Style {style_num} read from ballot. Analyzing Ballot and extracting the marks...", 3)
    ballot_marks_df = analyze_images_by_style_rois_map_df(argsdict, ballot, style_rois_map_df)
    return ballot_marks_df


def extractvote_by_one_tasklist(
        argsdict: dict,
        tasklist_name: str,
        ):
    """ ACTIVE
    
    Extract vote from all ballots as specified in tasklist chunk in extraction_tasks folder.

    params:
    :param argsdict: provides arguments from input file or CLI such as filter specs.
    :param tasklist_name: created by f"{BIF.name}_chunk_{'%4.4u' % (chunk_index)}.csv"
            tasklist is found in extaction_tasks folder.

    produces results/marks_{tasklist_name}

    This is the primary extraction function for lambda operation.
    
    PRIOR TO LAUNCHING THIS:
        Check availability of:
            styles/rois_map_df.csv      -- as a result of gentemplates, genrois, genmap
            styles/contests_dod.json    -- based on EIF
            

    """

    current_archive_basename = ''
    archive = None

    # set s3 vs local mode
    DB.set_DB_mode()        

    # initialize results.
    DB.BALLOT_MARKS_DF = pd.DataFrame()
    
    rois_map_df      = DB.load_data('styles', 'roismap.csv')
    contests_dod     = DB.load_data('styles', 'contests_dod.json')

    #extraction_tasks_df = DB.load_df_csv(name=tasklist_name, dirname='extraction_tasks', s3flag=argsdict['use_s3_results'])
    extraction_tasks_df = DB.load_data(dirname='marks', subdir='tasks', name=tasklist_name)

    #archives_folder_path = argsdict['archives_folder_path']

    for task_idx in range(len(extraction_tasks_df.index)):

        task_dict           = extraction_tasks_df.iloc[task_idx]
        ballot_id           = task_dict['ballot_id']
        precinct            = task_dict['precinct']
        archive_basename    = task_dict['archive_basename']

        """ has structure of BIF
            ('archive_basename', str),
            ('ballot_id', str),
            ('file_paths', str),    # note, may be semicolon separated list.
            ('cvr_file', str),
            ('precinct', str),
            ('party', str),
            ('style_num', str),
            ('card_code', str),
            ('ballot_type_id', str),
            ('sheet0', 'Int32'),                 # 0, 1 ...
            ('is_bmd', 'Int32'),
            ('style_roi_corrupted', 'Int32'),
            ('other_comments', str),
        """

        ballot_style_overrides_dict = args.get_ballot_style_overrides(argsdict)

        #ballot_id, vendor='ES&S', precinct=None, party=None, group=None, extension=None, file_paths=[]):
        # this call does nothing more than initialize the instance data
        ballot = Ballot(argsdict, 
            file_paths = re.split(r';', task_dict['file_paths']), 
            ballot_id=ballot_id, 
            precinct=precinct, 
            archive_basename=archive_basename)

        ballot.ballotdict['is_bmd'] = bool(utils.set_default_int(task_dict.get('is_bmd', 0), 0))

        if (ballot.ballotdict['is_bmd'] and not argsdict['include_bmd_ballot_type'] or
            not ballot.ballotdict['is_bmd'] and not argsdict['include_nonbmd_ballot_type']):

            utils.exception_report(f"Tasklist says is_bmd is {ballot.ballotdict['is_bmd']} "
                "but argsdict does not include that type. Extract tasklists may be stale")
            continue

        if archive_basename != current_archive_basename:
            if current_archive_basename and archive:
                archive.close()
            utils.sts (f"opening archive: '{archive_basename}'...", 3)
            archive = open_archive(argsdict, archive_basename)
            current_archive_basename = archive_basename

        if not ballot.load_source_files(archive):
            string = f"EXCEPTION: Could not load source files from archive {archive_basename} offset {task_idx} for ballot_id: {ballot_id} Precinct: {precinct}"
            utils.exception_report(string)
            continue

        utils.sts(f"\n{'-'*50}\nProcessing tasklist:{tasklist_name} offset: {task_idx} ballot_id:{ballot_id}", 3)

        ballot.get_ballot_images()      # this reads images from PDFs

        #-----------------------------------------------------
        # this is the primary function call, performed for each ballot,
        # and producing a marks_df for this ballot, with one record for
        # each option.
        
        ballot_marks_df = extract_vote_from_ballot(
            argsdict, ballot, rois_map_df, contests_dod,
            ballot_style_overrides_dict,
            )
            
        # the above function makes exception reports if:
        #   1. the style cannot be read from the ballot, alignment or barcode error.
        #   2. the style failed to map.
        #-----------------------------------------------------

        if ballot_marks_df is None or not len(ballot_marks_df.index):
            continue    # not successful and exception has already been logged.

        DB.BALLOT_MARKS_DF = DB.BALLOT_MARKS_DF.append(ballot_marks_df, sort=False, ignore_index=True)
        continue

    #DB.save_df_csv(name=tasklist_name, dirname='marks', df=DB.BALLOT_MARKS_DF)
    DB.save_data(data_item=DB.BALLOT_MARKS_DF, dirname='marks', subdir='chunks', name=f"marks_{tasklist_name}")
    

def extractvote_by_tasklists(argsdict: dict):
    """
    ACTIVE
    This replaces the extractvotes function.
    given tasklists which exist in the extraction_tasks folder,

    Tasklists are generated by reviewing the BIF tables.
    Each tasklist creates a separate f"marks_{tasklist_name}.csv" file in the results folder.

    """
    logs.sts('Extracting marks from extraction tasklists', 3)

    tasklists = DB.list_files_in_dirname_filtered(dirname='marks', subdir='tasks', file_pat=r'^[^~].*\.csv$', fullpaths=False)
    total_num = len(tasklists)
    utils.sts(f"Found {total_num} taskslists", 3)

    use_lambdas = argsdict['use_lambdas']

    if use_lambdas:
        LambdaTracker.clear_requests()
        #clear_instructions(config_d.TASKS_BUCKET, Job.get_path_name())

    biflist = get_biflist(no_ext=True)

    for bif_idx, bifname in enumerate(biflist):
        archive_name = re.sub(r'_bif', '', bifname)
        genmarks_tasks = [t for t in tasklists if t.startswith(archive_name)]
    
        for chunk_idx, tasklist_name in enumerate(genmarks_tasks):
        
            #----------------------------------
            # this call may delegate to lambdas and return immediately
            # if 'use_lambdas' is enabled.
            # otherwise, it blocks until the chunk is completed.
            
            build_one_chunk(argsdict, 
                dirname='marks', 
                chunk_idx=chunk_idx, 
                filelist=[tasklist_name], 
                group_name=bifname,
                task_name='extractvote', 
                incremental=False)

            #----------------------------------

            if not chunk_idx and not bif_idx and argsdict['one_lambda_first']:
                if not wait_for_lambdas(argsdict, task_name='extractvote'):
                    utils.exception_report("task 'extractvote' failed delegation to lambdas.")
                    sys.exit(1)           

    wait_for_lambdas(argsdict, task_name='extractvote')

    utils.combine_dirname_chunks_each_archive(argsdict, dirname='marks')
    logs.get_and_merge_s3_logs(dirname='marks', rootname='log', chunk_pat=r"_chunk_\d+", subdir="chunks")
    logs.get_and_merge_s3_logs(dirname='marks', rootname='exc', chunk_pat=r"_chunk_\d+", subdir="chunks")
        

def delegated_extractvote(dirname, task_args, s3flag=None): 
    # task_args: argsdict, archive_basename, chunk_idx, filelist
    args.argsdict = argsdict = task_args['argsdict']
    
    #chunk_idx   = task_args['chunk_idx']
    filelist    = task_args['filelist']         # bif segment defining ballots included 
    
    extractvote_by_one_tasklist(
            argsdict,
            tasklist_name=filelist[0],
            )




