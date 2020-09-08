#import json
import time
#import sys
import json
import posixpath

from utilities import logs
from aws_lambda import s3utils
from models.DB import DB

class LambdaTracker():
    lambda_requests = {}

    @classmethod
    def add_new_request(cls, request_id: str, chunk_name: str, task_args: dict):
        cls.lambda_requests[request_id] = {
            'chunk_name': chunk_name,
            'task_args': task_args,
            'status': 'Running'
        }

    @classmethod
    def get_status_request_keys(cls, status) -> list:
        return [k for k, v in cls.lambda_requests.items() if v['status'].upper() == status.upper()]

    @classmethod
    def get_not_done_request_keys(cls) -> list:
        return [k for k, v in cls.lambda_requests.items() if v['status'].upper() != 'DONE']

    @classmethod
    def clear_requests(cls):
        cls.lambda_requests = {}
        # Remove lambda_tracker folder so that history is clean
        DB.delete_dirname_files_filtered(dirname='lambda_tracker', s3flag=True)
        
        
    
def wait_for_lambdas(argsdict: dict, task_name=None): #, download_failed=False):
    """ Waits for every lambda request added to LambdaTracker.
    
        Note: not specific to task_name. Only only one use of Lambdas at a time
                by a specific job_name.
        We may want to use task_name to create separate folders for any given task.
        So keep task_name for now even though we are not using it.
    
    """
    if not argsdict['use_lambdas']: return
        
    # running_requests = LambdaTracker.get_status_request_keys('Running')
    total_requests = len(LambdaTracker.lambda_requests.keys())
    running_requests = total_requests
    if not running_requests: return

    wait = 10
    timeout = 60 * 20
    time.sleep(10)  # Just to be sure that all lambdas tracker files are on the bucket
    s3dirpath_completed = DB.dirpath_from_dirname('lambda_tracker', subdir='Completed')
    s3dirpath_failed = DB.dirpath_from_dirname('lambda_tracker', subdir='Failed')

    while timeout > 0 and running_requests:
        time.sleep(wait)
        timeout -= wait

        # running_requests = LambdaTracker.get_status_request_keys('Running')
        files_completed = s3utils.list_files_in_s3dirpath(s3dirpath_completed)
        files_failed = s3utils.list_files_in_s3dirpath(s3dirpath_failed)
        completed_requests = len(files_completed)
        failed_requests = len(files_failed)
        running_requests = total_requests - completed_requests - failed_requests
        if timeout <= 0 or not running_requests:
            break
        logs.sts(f'Waiting for lambdas. Timeout (s): {timeout}. Running: {running_requests}')
        # for request in running_requests:
        #     chunk_name = LambdaTracker.lambda_requests[request].get('chunk_name')
        #     tracker = s3utils.check_lambda_status(argsdict, task_name=task_name, chunk_name=chunk_name)
        #     if tracker:
        #         if tracker.get('status') != 'Running':
        #             #import pdb; pdb.set_trace()
        #             LambdaTracker.lambda_requests[request]['status'] = tracker['status']
        #             utils.sts(f"Task {chunk_name}, ID {request} changed status to {tracker['status']}")
        #             if tracker.get('error_info'):
        #                 LambdaTracker.lambda_requests[request]['error_type'] = tracker['error_info']['error_type']
        #                 LambdaTracker.lambda_requests[request]['error_message'] = tracker['error_info']['error_message']
        #                 LambdaTracker.lambda_requests[request]['error_stack'] = tracker['error_info']['error_stack']
        #     else:
        #         utils.sts(f"Trackign info from job:{job_name}, task:{task_name} and chunk:{chunk_name} not found", 3)

    # failed_requests = LambdaTracker.get_not_done_request_keys()
    failed_requests_log_list = s3utils.list_files_in_s3dirpath(s3dirpath_failed)
    all_succeeded = True
    if failed_requests_log_list:
        # if download_failed:
            # #download_results(argsdict)
            # pass
        for failed_request in failed_requests_log_list:
            print(f'Lambda request failed. please check cloudwatch logs for chunks: {failed_request} \n')
            # request = LambdaTracker.lambda_requests[failed_request]
            # chunk_name = request.get('chunk_name')
            # utils.sts(f'Task: {chunk_name}, ID: {failed_request} failed')
            # if request['status'] == 'Failed':
            #     utils.sts(f"{request.get('error_type')}: {request.get('error_message')}")
            #     error_stack = request.get('error_stack')
            #     for error_item in error_stack:
            #         print(error_item)
            #         #utils.sts(f"Error Stack: {request.get('error_stack')}")
            # else:
            #     utils.sts('Error: TIMEOUT')
            # utils.sts(f"Files payload: {json.dumps(request['task_args'])}", verboselevel=1)
            # print('Files payload list saved to log file')
        all_succeeded = False
        
    logs.sts(f"All lambdas finished; {completed_requests} {round(100 * completed_requests/(completed_requests + failed_requests), 2)}% successful, "
             f"{failed_requests} {round(100 * failed_requests/(completed_requests + failed_requests), 2)}% failed", 3)
             
    return all_succeeded


def build_lambda_tracker_s3path(argsdict, task_name, chunk_name, status):
    job_folder_s3path = argsdict['job_folder_s3path']
    lambda_status_s3path = posixpath.join(job_folder_s3path, f"lambda_tracker/{status}/{task_name}_{chunk_name}.json")
    return lambda_status_s3path
    

def create_lambda_tracker_s3path_by_task_args(task_args, status):
    return build_lambda_tracker_s3path(task_args['argsdict'], task_args['task_name'], task_args['chunk_name'], status)
    
    
def lambda_report_status(task_args, request_id, status, error_info=None):

    tracker_s3path = create_lambda_tracker_s3path_by_task_args(task_args, status)
    buff = json.dumps({
        "request_id":   request_id,
        "status":       status,
        "error_info":   error_info,
        'task_args':    task_args,
    })
    s3utils.write_buff_to_s3path(tracker_s3path, buff)
    # log to cloudwatch in case if there is any error for tracking
    if error_info:
        print(buff)
    logs.sts(f"Tracker file written with status='{status}'", 3)
    
    
def check_lambda_status(argsdict, task_name, chunk_name):
    tracker_s3path = build_lambda_tracker_s3path(argsdict, task_name, chunk_name)
    buff = s3utils.read_buff_from_s3path(tracker_s3path)
    return json.loads(buff)


