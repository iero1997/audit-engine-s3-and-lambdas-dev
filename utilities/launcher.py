# launcher.py

import traceback
import json


from utilities import args, logs
from models import LambdaTracker
from models.DB import DB
        

def accept_delegation_task_chunk(request_id, task_args):
    """ This is a locally callable function to allow debugging.
        right after args are unpacked.
    """
    args.argsdict = argsdict = task_args['argsdict']
    
    argsdict['on_lambda'] = True
    DB.set_DB_mode()
    chunk_name      = task_args['chunk_name']
    #dirname         = task_args['dirname']
    #subdir          = task_args['subdir']
    job_name        = argsdict['job_name']

    # we must be aware that lambdas are not fully initialized prior to use. If one lambda finishes its work of the same kind, and
    # another is started, the state in that lambda is indeterminate, but we have found that files and data structures may still
    # exist.
    
    # no need to report that the Lambda is 'Running' -- we already know that.
    # LambdaTracker.lambda_report_status(task_args, request_id, status='Running')

    try:
        launch_task(task_args, s3flag=True)

        # pylint: disable=broad-except
        # We need to catch broad exception.
    except Exception as err:
        error_info = {
            'error_type':       err.__class__.__name__,
            'error_message':    repr(err),
            'error_stack':      traceback.format_tb(err.__traceback__),
            'task_args':        task_args,
            }
        LambdaTracker.lambda_report_status(task_args, request_id, status="Failed", error_info=error_info)
        msg = f"{job_name} Failed"
    else:
        LambdaTracker.lambda_report_status(task_args, request_id, status='Completed')
        error_info = None
        msg = f"{job_name} Completed"

    return {
        'body': json.dumps({
            'msg': msg,
            'error_info': error_info,
            'chunk_name': chunk_name,
        })
    }
    

def launch_task(task_args, s3flag=None):
    """ This talk launcher will allow us to launch a variety of tasks to lambdas without
        needing separate infrastructure for each one. When used in lambdas, use_s3_results should be True.
        Running locally, it can be set either way for testing.
    """

    chunk_name      = task_args['chunk_name']
    dirname         = task_args['dirname']
    subdir          = task_args['subdir']
    
    for rootname in ['log', 'exc', 'map_report']:
        logs.rm_logfile(rootname=rootname)

    if dirname == 'bif':
        from utilities import bif_utils
        bif_utils.delegated_build_bif_chunk(dirname=dirname, task_args=task_args, s3flag=s3flag)
        
    elif dirname == 'marks':
        from utilities import votes_extractor
        votes_extractor.delegated_extractvote(dirname=dirname, task_args=task_args, s3flag=s3flag)
        
    elif dirname == 'styles':
        from utilities import gentemplates
        gentemplates.delegated_gentemplate(dirname=dirname, task_args=task_args, s3flag=s3flag)    
    
    elif dirname == 'cmpcvr':
        from utilities import cmpcvr
        cmpcvr.delegated_cmpcvr(dirname=dirname, task_args=task_args, s3flag=s3flag)    
    
    else:
        raise NotImplementedError
        
    for rootname in ['log', 'exc', 'map_report']:
        logs.report_lambda_logfile(s3dirname=dirname, chunk_name=chunk_name, rootname=rootname, subdir=subdir)

