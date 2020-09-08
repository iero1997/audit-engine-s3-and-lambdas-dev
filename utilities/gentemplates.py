import re
import os
import sys
#import time
#import glob

#import pandas as pd

from utilities import utils, args, logs
from utilities.bif_utils import get_biflist, set_style_from_party_if_enabled, build_one_chunk
from utilities.style_utils import generate_style_template, get_manual_styles_to_contests
from utilities.zip_utils import open_archive
from utilities.alignment_utils import are_timing_marks_consistent
#from utilities import launcher
from utilities import genrois
from utilities import maprois
from utilities.cvr_utils import create_contests_dod
from utilities.styles_from_cvr_converter import convert_cvr_to_styles
from utilities.images_utils import create_redlined_images

#from aws_lambda import s3utils

from models.DB import DB
from models.BIF import BIF
from models.Ballot import Ballot
from models.LambdaTracker import LambdaTracker, wait_for_lambdas



def build_template_tasklists(argsdict):
    """ with all bif chunks created, scan them and create template_tasklists.
        each tasklist contains records from bif for ballots to be included
        in the template. These are written to template_tasklists folder.
        
        Note that this processes BIFs one at a time, rather than combining
        them all in memory, which is not scalable.
    """

    utils.sts("Building template tasklists...", 3)
    
    incomplete_style_ballots_dodf = {}      # dict keyed by style of df
    completed_eff_styles_dodf = {}          # 

    num_ballots_to_combine = argsdict.get('threshold', 50)

    # then following works even if bif is generated from CVR.
    # because the separate bif csv files are still produced.
    bif_names = get_biflist(fullpaths=False)

    if argsdict['merge_similar_styles']:
        
        #sheetstyle_map_dict = DB.load_json('styles', 'sheetstyle_map_dict.json', silent_error=False)
        sheetstyle_map_dict = DB.load_data(dirname='styles', name='sheetstyle_map_dict.json')

    for bif_name in bif_names:
        utils.sts(f"  Processing bif {bif_name}...", 3)
        
        BIF.load_bif(name=bif_name)
        reduced_df = BIF.df_without_corrupted_and_bmd()
        reduced_df = set_style_from_party_if_enabled(argsdict, reduced_df)
        
        style_nums_in_this_bif = list(reduced_df['style_num'].unique())
        utils.sts(f"  Found {len(style_nums_in_this_bif)} unique styles", 3)

        for style_num in style_nums_in_this_bif:
            utils.sts(f"Processing style:{style_num} ", 3, end='')
            previously_captured = 0

            eff_style = style_num
            if argsdict['merge_similar_styles']:
                eff_style = sheetstyle_map_dict[style_num[1:]]          # skip language char.
                # this is the contests-only style on per sheet basis.
                # it does not have language included. So we add the language from original style
                lang_code = style_num[0:1]                              # first char
                eff_style = "%1.1u%4.4u" % (int(lang_code), int(eff_style))

                utils.sts(f"Effective (merged) style is:{eff_style} ", 3, end='')
            
            if eff_style in completed_eff_styles_dodf:
                utils.sts(" Tasklist already created", 3)
                continue

            # first see if we were already working on this style
            if eff_style in incomplete_style_ballots_dodf:
                previously_captured = len(incomplete_style_ballots_dodf[eff_style].index)
                utils.sts(f"Previously captured {previously_captured} ", 3, end='')
            # find records with this eff_style

            style_df = reduced_df[(reduced_df['style_num'] == style_num)][0:(num_ballots_to_combine-previously_captured)]
            utils.sts(f" Just Captured {len(style_df.index)}", 3, end='')

            if previously_captured:
                style_df = incomplete_style_ballots_dodf[eff_style].append(style_df, ignore_index=True)
                utils.sts(f" Total captured {len(style_df.index)}", 3, end='')
            if len(style_df.index) >= num_ballots_to_combine:
                completed_eff_styles_dodf[eff_style] = style_df
                try:
                    del incomplete_style_ballots_dodf[eff_style]
                except: pass
                utils.sts(" Full", 3)
            else:
                utils.sts(" Queued", 3)
                incomplete_style_ballots_dodf[eff_style] = style_df


    # skip those that have too few records, i.e. < min_ballots_required

    min_ballots_required = argsdict.get('min_ballots_required', 1)
    too_few_ballots_styles = []
    template_tasklists_dodf = {}
    for eff_style, style_df in {**completed_eff_styles_dodf, **incomplete_style_ballots_dodf}.items():
        num_records = len(style_df.index)
        if num_records < min_ballots_required:
            utils.sts(f"Style has too few records, {min_ballots_required} ballots are required, skipping...", 3)
            too_few_ballots_styles.append(style_num)
            continue
        template_tasklists_dodf[eff_style] = style_df
        
    # write tasklists
    utils.sts("\n  Writing tasklists:", 3)
    if not argsdict['use_single_template_task_file']:
        for eff_style, style_df in template_tasklists_dodf.items():
            utils.sts(f"  Writing tasklists for style:{eff_style} with {'%2.2u' % (len(style_df.index))} entries ", 3, end='')
            style_df.sort_values(by=['archive_basename'], inplace=True)
            pathname = DB.save_data(data_item=style_df, dirname='styles', subdir='tasks', name=str(eff_style), format='.csv')
            utils.sts(f"to {pathname}", 3)
    else:
        template_tasklists_dolod = utils.dodf_to_dolod(template_tasklists_dodf)
        utils.sts(f"Writing combined tasklists with {'%2.2u' % (len(template_tasklists_dolod))} tasklists ", 3, end='')
        DB.save_data(data_item=template_tasklists_dolod, dirname='styles', name="template_tasklists_dolod.json")

    completed_count = len(completed_eff_styles_dodf)
    incompleted_count = len(incomplete_style_ballots_dodf)

    utils.sts(  f"Total number of styles detected: {completed_count + incompleted_count} \n"
                f"            Completed tasklists: {completed_count}\n"
                f"   Incomplete tasklists created: {incompleted_count}\n"
                f"    Styles will too-few ballots: {too_few_ballots_styles}\n"
                , 3)


def is_style_num_valid(argsdict, style_num) -> bool:
    """ check that style_num is within the range specified in the input file in parameters
        style_num_low_limit and style_num_high_limit
    """
    if style_num is None:
        return False

    style_num_low_limit = argsdict.get('style_num_low_limit')
    style_num_high_limit = argsdict.get('style_num_high_limit')
    if style_num_low_limit is None or style_num_high_limit is None:
        return True

    return (style_num_low_limit <= int(style_num) < style_num_high_limit)


def generate_template_for_style_by_tasklist_lod(argsdict: dict,
                                                tasklist_lod: list = None):
    """ ACTIVE
        This function is driven by a preselected set of ballots listed in BIF format.
        This list is prefiltered to exclude BMD ballots, and the ballots are all of the
        same physical style so they can be combined to produce a template with higher
        resolution and which largely excludes random marks. Generates a set of template images
        1. opens the files either from local zip archives or on s3 bucket (already unzipped.)
        2. aligns the images to alignment targets.
        3. reads the barcode style and checks it with the card_code (which may differ from the style_num)
        4. gets the timing marks.
        5. calls generate_style_template(), which:
            a. reviews the images and chooses the most average image in terms of stretch.
            b. discards any excessively stretched images.
            c. stretch-fixes the rest on timing-mark basis to "standard" timing marks.
            d. combines into one image.
            e. saves style information as JSON.
    """
    global archive
    global current_archive_basename
    current_archive_basename = ''

    ballot_queue = []
    ballots_unprocessed = []
    tot_failures = 0

    #if not tasklist_lod:
    #    tasklist_lod = tasklist_df.to_dict(orient='records')
    for task_idx, item_dict in enumerate(tasklist_lod):
        #import pdb; pdb.set_trace()

        archive_basename = item_dict['archive_basename']
        ballot_file_paths = re.split(r';', item_dict['file_paths'])
        precinct = item_dict['precinct']
        sheet0 = item_dict['sheet0']
        card_code = item_dict['card_code']
        style_num = item_dict['style_num']      # will be the same for all records.

        ballot      = Ballot(argsdict, file_paths=ballot_file_paths, archive_basename=archive_basename)    # initialize and derive ballot_id, precinct, party, group, vendor
        ballot_id   = ballot.ballotdict['ballot_id']
        precinct    = ballot.ballotdict['precinct']

        utils.sts (f"gentemplate_by_tasklist for "
                    f"style_num:{style_num} "
                    f"item:{task_idx} "
                    f"in archive {archive_basename} "
                    f"ballotid:{ballot_id} "
                    f"in precinct:'{precinct}'...", 3)

        if archive_basename != current_archive_basename:
            if current_archive_basename:
                archive.close()
            utils.sts (f"opening archive: '{archive_basename}'...", 3)
            archive = open_archive(argsdict, archive_basename)
            current_archive_basename = archive_basename

        if not ballot.load_source_files(archive):
            utils.exception_report(f"EXCEPTION: Could not load source files from archive {archive_basename} "
                                    f"item:{task_idx} for ballot_id: {ballot_id} Precinct: {precinct}")
            continue
        ballot.get_ballot_images()
        ballot.align_images()
        read_style_num = ballot.read_style_num_from_barcode(argsdict)
        if not argsdict.get('style_from_party', None) and not argsdict.get('style_lookup_table_path', ''):
            if str(read_style_num) != str(card_code):
                utils.exception_report(f"Style {read_style_num} in ballot {ballot_id} doesn't match style card_code {card_code} from tasklist")
                #add_instruction(bif_name=source_name, ballot_id=ballot_id, column='style_num', value=f'not matched to {style_num}')
                ballots_unprocessed.append(ballot_id)
                continue
        #add_instruction(bif_name=archive_basename, ballot_id=ballot_id, column='style_num', value=style_num)

        ballot.get_timing_marks()       # for each image, capture the timing marks to ballot instance.
                                        # note that sometimes timing marks are not available on page 1.

        if not are_timing_marks_consistent(ballot.ballotdict['timing_marks']):
            utils.exception_report(f"EXCEPTION: Timing mark recognition failed: ballot_id: {ballot_id} Precinct: {precinct}")
            tot_failures += 1
            continue
        ballot_queue.append(ballot)

    utils.sts(f"Generating Style Template from {len(ballot_queue)} ballots (omitted {tot_failures} failed ballots)...", 3)
    if generate_style_template(argsdict, ballot_queue, style_num, sheet0):
        utils.sts(f"Style templates generation completed successfully.\n Processed a total of {len(ballot_queue)} ballots", 3)
        return True
    else:
        utils.sts("Style templates generation FAILED.", 3)
        return False

def gentemplates_by_tasklists(argsdict):
    """
    ACTIVE
    This replaces the gentemplates function.
    given tasklists which exist in the tasklist folder,
    read each in turn and if the number of ballots included meet a minimum,
    process each line item in turn.
    The style is the name of the tasklist.

    Tasklists are generated by reviewing the BIF tables.
    
    Each delegetion to lambdas (or performed locally) will include 
    subprocesses according to the argsdict parameters:
    
        include_gentemplate_tasks       - include the generation of tasklists prior to delegation.
        use_single_template_task_file   - means a single JSON file will be created instead of separate task files on s3
                                            and a portion of that task list will be passed to each lambda
        include_gentemplate             - for each style, combine ballots to create a base template
        include_genrois                 - generate regions of interest (ROIs) and OCR
        include_maprois                 - map the official contest names to what is read on the ballot to create roismap
        

    
    """
    styles_on_input = []
    #attempted_but_failed_styles = []   # will need to determine by looking for templates

    utils.sts('Generating style templates from a combined set of ballot images', 3)

    # this loads and parses the EIF
    contests_dod = create_contests_dod(argsdict)
    #DB.save_style(name='contests_dod', style_data=contests_dod)
    DB.save_data(data_item=contests_dod, dirname='styles', name='contests_dod.json')

    # style_to_contests_dol
    # if the CVR is available, we can get a list of styles that are associated with a ballot_type_id.
    # this may be enough to know exactly what contests are on a given ballot, but only if the 
    # style which keys this list is also directly coupled with the card_code read from the ballot.
    # In some cases, such as Dane County, WI, this is a 1:1 correspondence. But SF has an complex
    # style conversion which is nontrivial to figure out. 
    # thus, this is still needed in style discovery.

    style_to_contests_dol = DB.load_data(dirname='styles', name='CVR_STYLE_TO_CONTESTS_DICT.json', silent_error=True)
    if not style_to_contests_dol:
        logs.sts("CVR_STYLE_TO_CONTESTS_DICT.json not available. Trying to convert CVR to styles", 3)
        style_to_contests_dol = convert_cvr_to_styles(argsdict, silent_error=True)
        if not style_to_contests_dol:
            logs.sts("Unable to convert CVR to style_to_contests_dol, trying manual_styles_to_contests", 3)
            style_to_contests_dol = get_manual_styles_to_contests(argsdict, silent_error=True)

        if style_to_contests_dol:
            DB.save_data(data_item=style_to_contests_dol, dirname='styles', name='CVR_STYLE_TO_CONTESTS_DICT.json')
            
    if not style_to_contests_dol:
        logs.sts("style_to_contests_dol unavailable. full style search is required.", 3)

    if argsdict.get('use_lambdas'):
        LambdaTracker.clear_requests()

    first_pass = True

    if argsdict['use_single_template_task_file']:
        template_tasklists_dolod = DB.load_data(dirname='styles', name="template_tasklists_dolod.json")
        total_num = len(template_tasklists_dolod)
        utils.sts(f"Found {total_num} taskslists", 3)
        
        for chunk_idx, (style_num, style_lod) in enumerate(template_tasklists_dolod.items()):
            if not style_num: continue
            
            if argsdict.get('include_style_num') and style_num not in argsdict['include_style_num'] or \
                argsdict.get('exclude_style_num') and style_num in argsdict['exclude_style_num']:
                continue
            
            styles_on_input.append(style_num)

            if argsdict.get('incremental_gentemplate', False) and DB.template_exists(style_num):
                utils.sts(f"Style {style_num} already generated, skipping...", 3)
                continue
                
            utils.sts(f"Processing template for style {style_num} #{chunk_idx}: of {total_num} ({round(100 * (chunk_idx+1) / total_num, 2)}%)")

            # the function call below will delegate to lambdas if use_lambdas is True.
            build_one_chunk(argsdict,
                dirname='styles', 
                subdir=style_num,
                chunk_idx=chunk_idx, 
                filelist=[style_lod],            # only one style per lambda chunk, but can execute gentemplate, genrois, and maprois for same style.
                group_name=style_num, 
                task_name='gentemplate', 
                incremental=False,
                )

            if argsdict['use_lambdas'] and first_pass and argsdict['one_lambda_first']:
                if not wait_for_lambdas(argsdict, task_name='gentemplate'):
                    utils.exception_report("task 'gentemplate' failed delegation to lambdas.")
                    sys.exit(1)           
                first_pass = False
            # if not generate_template_for_style_by_tasklist_df(argsdict, style_num, tasklist_df):
                # attempted_but_failed_styles.append(style_num)
        
    else:    
        tasklists = DB.list_files_in_dirname_filtered(dirname='styles', subdir="tasks", file_pat=r'.*\.csv', fullpaths=False)
        total_num = len(tasklists)
        utils.sts(f"Found {total_num} taskslists", 3)

        for chunk_idx, tasklist_name in enumerate(tasklists):
            if tasklist_name == '.csv': continue
            
            style_num = os.path.splitext(os.path.basename(tasklist_name))[0]
            styles_on_input.append(style_num)

            if args.argsdict.get('incremental_gentemplate', False) and DB.template_exists(style_num):
                utils.sts(f"Style {style_num} already generated, skipping...", 3)
                continue
                
            utils.sts(f"Processing template for style {style_num} #{chunk_idx}: of {total_num} ({round(100 * (chunk_idx+1) / total_num, 2)}%)")

            # the function call below will delegate to lambdas if use_lambdas is True.
            build_one_chunk(argsdict,
                dirname='styles', 
                chunk_idx=chunk_idx, 
                filelist=[tasklist_name], 
                group_name=style_num, 
                task_name='gentemplate', 
                incremental=False,
                )
            if argsdict['use_lambdas'] and first_pass and argsdict['one_lambda_first']:
                if not wait_for_lambdas(argsdict, task_name='gentemplate'):
                    utils.exception_report("task 'gentemplate' failed delegation to lambdas.")
                    sys.exit(1)           
                first_pass = False

    wait_for_lambdas(argsdict, task_name='gentemplate')
    post_gentemplate_cleanup(argsdict)
    
    
def post_gentemplate_cleanup(argsdict):
    # this portion of the above function has been separated to allow for individual testing.

    # normally, we combine chunks, but in the case of styles generation, this is not needed except for roismap.

    logs.sts("gentemplates_by_tasklists completed.\n", 3)
    
    #import pdb; pdb.set_trace()

    if argsdict['include_maprois']:
        #styles_completed = DB.list_subdirs_with_filepat('styles', file_pat=r'\.json$', s3flag=None)
        #attempted_but_failed_styles = [s for s in styles_on_input if s not in styles_completed]

        logs.sts("Combining roismap for each style into a single .csv file.", 3)
        DB.combine_dirname_chunks(dirname='styles', subdir="roismap", dest_name='roismap.csv', file_pat=r'_roismap\.csv')

        good_map_num = logs.get_and_merge_s3_logs(dirname='styles', rootname='map_report', chunk_pat=r'\d+_styles_chunk_\d+', subdir='logs_good_maps')
        fail_map_num = logs.get_and_merge_s3_logs(dirname='styles', rootname='map_report', chunk_pat=r'\d+_styles_chunk_\d+', subdir='logs_failed_maps')
        
        logs.sts(f"{good_map_num} styles successfully mapped; {fail_map_num} styles did not fully map.", 3)
    
    # style logs are placed in one folder in styles
    # logs are like exc_11010_styles_chunk_84.txt
    # downloads file_pat=fr"{rootname}_{chunk_pat}\.txt"
    logs.get_and_merge_s3_logs(dirname='styles', rootname='log', chunk_pat=r'\d+_styles_chunk_\d+', subdir='logs')
    logs.get_and_merge_s3_logs(dirname='styles', rootname='exc', chunk_pat=r'\d+_styles_chunk_\d+', subdir='logs')


def delegated_gentemplate(dirname, task_args, s3flag=None):
    args.argsdict = argsdict = task_args['argsdict']
    
    chunk_idx   = task_args['chunk_idx']
    tasklist    = task_args['filelist']         # bif segment defining ballots included 
    style_num   = task_args['group_name']
    
    if isinstance(tasklist[0], str):
        # when using individual files, tasklist[0] is the tasklist file name.
        tasklist_lod = DB.load_data(dirname='styles', subdir='tasks', name=tasklist[0], format='.csv', type='lod')
    else:
        tasklist_lod = tasklist[0]
    
    if argsdict['include_gentemplate']:
        # generate a "blank" ballot image for this style in dirname 'styles'
        generate_template_for_style_by_tasklist_lod(argsdict, tasklist_lod=tasklist_lod)
    
    style_rois_list = None
    if argsdict['include_genrois']:
        # generate rois information to dirname 'rois'
        style_rois_list = genrois.genrois_one_style(argsdict, style_num)

    if argsdict['include_maprois']:
        style_rois_map_df, error_flag = maprois.maprois_discover_style(
            argsdict,
            style_num,
            style_rois_list=style_rois_list,
            #rois_map_df=None,
            contests_dod=None,
            style_to_contests_dol=None,
            )
            
        #import pdb; pdb.set_trace()
        if error_flag or not len(style_rois_map_df.index):
            logs.exception_report(f"Failed to map style:{style_num}")
            logs.report_lambda_logfile(s3dirname='styles', chunk_name=f"{style_num}_styles_chunk_{chunk_idx}", rootname='map_report', subdir='logs_failed_maps')
        else:
            logs.report_lambda_logfile(s3dirname='styles', chunk_name=f"{style_num}_styles_chunk_{chunk_idx}", rootname='map_report', subdir='logs_good_maps')
            create_redlined_images(argsdict, style_num, style_rois_map_df)
            DB.save_data(data_item=style_rois_map_df, dirname='styles', subdir='roismap', name=f"{style_num}_roismap", format='.csv')
        



def get_status_gentemplates(argsdict):
    pass
