# cmpcvr.py

import os
import sys
import traceback

from utilities import utils, args, logs
from utilities.bif_utils import build_one_chunk #, parse_tasklist_name
from utilities.cvr_comparator import compare_chunk_with_cvr 
#from utilities import launcher

from models.DB import DB
from models.CVR import CVR
from models.LambdaTracker import LambdaTracker, wait_for_lambdas


def cmpcvr_by_tasklists(argsdict: dict):
    """
    ACTIVE
    Comparison with CVR proceeds using the same chunks as were used in extraction.
    Each marks tasklist is a BIF table with information about each ballots, one per record.
    After extractvote is completed, marks_chunks folder contains marks_df.csv for each chunk.
    As the BIF table is sorted by 'cvrfile', this will reduce the size of CVR that must be loaded.

    """
    utils.sts('cmpcvr by tasklists', 3)

    # get the list of all extraction tasks in marks/tasks/ subfolder, without .csv extension.
    # name is like {archive_root}_chunk_{chunk_idx}.csv 
    tasklists = DB.list_files_in_dirname_filtered(dirname='marks', subdir='tasks', file_pat=r'.*\.csv$', fullpaths=False, no_ext=True)
    total_num = len(tasklists)
    utils.sts(f"Found {total_num} tasklists", 3)

    use_lambdas = argsdict['use_lambdas']

    if use_lambdas:
        LambdaTracker.clear_requests()

    # The 'extraction_tasks' are ordered also according to archive_root.

    archive_rootnames = []                     
    for source in argsdict['source']:
        archive_rootname = os.path.splitext(os.path.basename(source))[0]
        archive_rootnames.append(archive_rootname)                     

    for archive_idx, archive_rootname in enumerate(archive_rootnames):
        # process the tasklists one archive at a time.
        cmpcvr_tasks = [t for t in tasklists if t.startswith(archive_rootname)]
    
        for chunk_idx, tasklist_name in enumerate(cmpcvr_tasks):
        
            #----------------------------------
            # this call may delegate to lambdas and return immediately
            # if 'use_lambdas' is enabled.
            # otherwise, it blocks until the chunk is completed.
            # once the lambda is launched, processing continues at
            # 'delegated_cmpcvr()' below.
            
            build_one_chunk(argsdict, 
                dirname='cmpcvr', 
                chunk_idx=chunk_idx, 
                filelist=[tasklist_name], #tasklist name will be like {archive_root}_chunk_{chunk_idx}
                group_name=archive_rootname,
                task_name='cmpcvr', 
                incremental=False)
            #----------------------------------

            if not chunk_idx and not archive_idx and argsdict['one_lambda_first']:
                if not wait_for_lambdas(argsdict, task_name='cmpcvr'):
                    utils.exception_report("task 'cmpcvr' failed delegation to lambdas.")
                    sys.exit(1)           

    wait_for_lambdas(argsdict, task_name='cmpcvr')

    for archive_rootname in archive_rootnames:
    
        #cmpcvr/chunks/disagreed_{archive_root}_chunk_{chunk_idx}.csv    # individual cmpcvr disagreed chunks
        #cmpcvr/chunks/overvotes_{archive_root}_chunk_{chunk_idx}.csv # individual cmpcvr overvote chunks

        DB.combine_dirname_chunks(dirname='cmpcvr', subdir='chunks', 
            dest_name=archive_rootname+'_cmpcvr.csv', 
            file_pat=fr'{archive_rootname}_chunk_\d+\.csv')
            
        DB.combine_dirname_chunks(dirname='cmpcvr', subdir='chunks', 
            dest_name=archive_rootname+'disagreed.csv', 
            file_pat=fr'disagreed_{archive_rootname}_chunk_\d+\.csv')
            
        DB.combine_dirname_chunks(dirname='cmpcvr', subdir='chunks', 
            dest_name=archive_rootname+'overvotes.csv', 
            file_pat=fr'overvotes_{archive_rootname}_chunk_\d+\.csv')
            
        logs.get_and_merge_s3_logs(dirname='cmpcvr', rootname='log', chunk_pat=fr'{archive_rootname}_chunk_\d+', subdir='chunks')
        logs.get_and_merge_s3_logs(dirname='cmpcvr', rootname='exc', chunk_pat=fr'{archive_rootname}_chunk_\d+', subdir='chunks')
        

def delegated_cmpcvr(dirname, task_args, s3flag=None): 
    # task_args: argsdict, archive_basename, chunk_idx, filelist
    args.argsdict = argsdict = task_args['argsdict']
    
    #chunk_idx   = task_args['chunk_idx']
    filelist    = task_args['filelist']         # bif segment defining ballots included 
    
    cmpcvr_by_one_tasklist(
            argsdict,
            tasklist_name=filelist[0],          # like {archive_root}_chunk_{chunk_idx}
            )


def cmpcvr_by_one_tasklist(argsdict, tasklist_name):
    """ This is the primary function to be run inside lambda for cmpcvr.
    
        tasklist_name is like "{archive_root}_chunk_{chunk_idx}"
    """
    # set s3 vs local mode -- this probably better done long before this point.
    DB.set_DB_mode()        

    contests_dod = DB.load_data('styles', 'contests_dod.json')
    if CVR.data_frame.empty:
        CVR.load_cvrs_to_df(argsdict)
    
    #        marks/chunks/{archive_root}_chunk_{chunk_idx}.csv           # individual marks chunks. These are kept for cmpcvr


    if not DB.file_exists(file_name=tasklist_name+'.csv', dirname='marks', subdir="chunks"):
        utils.sts(f"Logic Error: no marks df missing: {tasklist_name}")
        traceback.print_stack()
        sys.exit(1)

    audit_df = DB.load_data(dirname='marks', subdir="chunks", name=tasklist_name, format='.csv')
    
    #---------------------------------------
    # primary call of this function performs chunk comparison
    
    overvotes_results, disagreed_results, blank_results = compare_chunk_with_cvr(
        argsdict=argsdict,
        contests_dod=contests_dod,
        cvr_df=CVR.data_frame,
        audit_df=audit_df,
        chunk_name=tasklist_name,
        )
    #---------------------------------------
    """
        cmpcvr/chunks/disagreed_{archive_root}_chunk_{chunk_idx}.csv    # individual cmpcvr disagreed chunks
        cmpcvr/chunks/overvotes_{archive_root}_chunk_{chunk_idx}.csv    # individual cmpcvr overvote chunks
    """
        
       
    DB.save_data(data_item=disagreed_results, 
        dirname='cmpcvr', subdir='chunks', 
        name=f"disagreed-{tasklist_name}.csv")

    DB.save_data(data_item=disagreed_results, 
        dirname='cmpcvr', subdir='chunks', 
        name=f"overvotes-{tasklist_name}.csv")

    DB.save_data(data_item=blank_results, 
        dirname='cmpcvr', subdir='chunks', 
        name=f"blanks-{tasklist_name}.csv")

#----------------------------------------------

