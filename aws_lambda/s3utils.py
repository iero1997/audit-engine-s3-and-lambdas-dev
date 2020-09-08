#---------------------------------------------------------------------------------
# s3utils.py

# Overview of philosophy of working with s3 vs. local files.
#
# s3path -- we have standardized on using an s3path to s3 file resources.
#   It includes the bucket and prefix to the resource, in the form:
#   s3://bucket/prefix/filename.ext

# parse_s3path(s3path) will parse the s3path descriptor into its components.
#   protocol, bucket, key, prefix, basename. The protocol is always 's3://'

# DB.dirpath_from_dirname(dirname, s3flag) will produce a dirpath
#   to one of the working folders base on the dirname, like 'bif'
#   Returns a path to the folder either locally or in s3 as s3path.
#   The job folder where these working folders are located is 
#   set in the settings file as 'job_folder_path' which is the local path or
#   'job_folder_s3path'. When the system is installed on an EC2 instance,
#   that path will need to be included in this function.

# Generally, for situations where we use lambdas to provide massive parallelism,
#   each lambda will be responsible for one "chunk" of work, where we set the 
#   chunk size so the lambda will be guaranteed to complete with the lambda timeout.

# Each lambda is provided a tasklist in the API call either explicitly or to a
#   file on s3. Right now, we are not triggering the invocation of the lambda with 
#   the writing of a tasklist, but that is one option for the future.

# As a result of processing, each lambda will produce results in chunks.
#   These chunks are placed in the folder associated with the operation.
#   For 'genbif_from_ballots' the chunks are placed in the 'bif' folder.
#   For 'extractvote' the chunks are placed in the 'marks' folder.
#   For 'cmpcvr' the chunks are placed in the 'cmpcvr' folder
#   The gentemplate/genrois/maprois function sequence generates only one
#       set of files for each style, so it is a little bit different.

# Also for all lambdas, there is at least one log file, and exception_reports.
#   The exception reports are not programmatic exceptions but exceptions to 
#   our expectations in the processing, such as ballots that we can't handle for
#   some reason, or styles that will not map.
# The gentemplate/genrois/maprois sequence generates also a map_report which
#   describes the mapping and redline proofs of the mapping on the ballot templates.

# In all functions, the open_archive method can open the ZIP archives of ballots images
#   either on the local machine, or directly from s3. This is a big breakthrough to 
#   simplify operations in this module.

# For the first three functions, they produce chunks in the corresponding folders.
#   The result folders on s3 should be emptied prior to the lambdas are launched.
#   The chunks must be copied back to the lambda supervisor, and combined. 
#   For this, the following functions exist in this module:

# download_entire_dirname(argsdict: dict, dirname: str, file_pat)
#   The dirname will be the same on both s3 storage and the local machine.
#   This downloads all files using concurrency, those paths that meet file_pat match

# merge_csv_dirname_local(argsdict, dirname, dest_name, file_pat=r'\d+-\d+.csv')
#   This function merges results that are in the same csv format. It simply combines the
#   files while also omitting the first header line.

# merge_txt_dirname(dirname: str, destpath: str)
#   This function combines text files, and does not omit the first line, and 
#       writes the result at destpath. This is used to combine log files, such as:
#           logfile.txt
#           exception_report.txt
#           map_report.txt

#---------------------------------------------------------------------------------



import io
import os
#import posixpath
import concurrent.futures
import re
import sys
import json
#import shutil
import glob
import logging
import platform
import threading
from inspect import signature
#import traceback
import subprocess
import pandas as pd
#import numpy as np      # imported only for np.nan
import boto3
from botocore.exceptions import ClientError
from boto3.s3.transfer import TransferConfig

s3_config = TransferConfig(max_concurrency=20, use_threads=True)
logging.basicConfig(
    level=logging.INFO, format='%(asctime)-12s %(levelname)-8s %(message)s')


#from models.BIF import BIF
from utilities import utils, logs

# some basic utilities for use with s3 storage and interaction with lambdas.

SimulateAWS = False      
# if this is true, then we do not start EC2 instance, and we use local storage to messages
# to second python process all running locally to debug the communication code.
# Run -op update_archives with this set, and the code will do the following:
#   1. uploading has been separately tested, so we can use sample zip file already on resources/s3sim folder.
#   2. ec2sim is set up to match situation that would exist in linux environment.
#   3. ec2_task_server.py is set up to run in ec2sim folder and it enters task_server loop.
#   4. request messages are formatted and saved to s3sim/TASKS_BUCKET.
#   5. ec2_task_server.py processes messages and transfers are simulated on local machine instead of using s3.
#   6. request_message is processed to transfer zip file and unzip, then transfer back.
s3sim_path = 'resources/s3sim'


def s3_get_key_list(bucket, keyprefix, maxkeys=20):
    """ given keyprefix, return list of files that match the prefix.
    """
    
    if SimulateAWS:
        sim_bucket = s3sim_path + "/" + bucket 
        if not os.path.isdir(sim_bucket):
            os.makedirs(sim_bucket)
        if keyprefix.endswith('.json'):
            key_list = glob.glob(s3sim_path + "/" + bucket + "/" + keyprefix )
        else:
            key_list = glob.glob(s3sim_path + "/" + bucket + "/" + keyprefix + "/*/*.json")
        #key_list = [key for key in simkeys if key.startswith(keyprefix)]
        key_list = [key.replace(sim_bucket+'/', '') for key in key_list]

    else:
        s3client = boto3.client('s3')
        
        list_resp_dict = s3client.list_objects_v2(
            Bucket=bucket,                              # Bucket name to list.
            Delimiter='/',                              # A delimiter is a character you use to group keys.
            MaxKeys=maxkeys,                            # Sets the maximum number of keys returned in the response.
            Prefix=keyprefix,                           # Limits the response to keys that begin with the specified prefix.
            )
        key_list = []
        if list_resp_dict['KeyCount']:
            try:
                key_list = [list_resp_dict['Contents'][i]['Key'] for i in range(len(list_resp_dict['Contents']))]
            except KeyError:
                pass

    return key_list


def remove_key_from_s3(bucket: str, key: str):
    if SimulateAWS:
        s3sim_itempath = s3sim_path + "/" + bucket + "/" + key
        os.remove(s3sim_itempath)
        print("removed " + s3sim_itempath)
    else:
        logging.info("Removing " + key + " from S3: " + bucket)
        run_cmd(get_aws_s3_cmd(action='rm', key=key, bucket=bucket))
        logging.info("Done!")


def run_cmd(cmd: str):
    subprocess.run([cmd], shell=True)

def get_aws_s3_cmd(
        action: str,
        key: str,
        bucket: str,
        fetch: bool = False,
        dest: str = '.',
        recursive: bool = False
) -> str:
    cmd = None
    if action == 'rm':
        cmd = "aws s3 rm s3://" + bucket + "/" + key

    if action == 'cp':
        cmd = "aws s3 cp {key} s3://" + bucket + "/" + key

    if action == 'cp' and fetch is True:
        cmd = "aws s3 cp s3://" + bucket + "/" + key + " " + dest

    return cmd + " --recursive" if recursive else cmd
   
   
def get_s3_core(bucket, key):
    s3 = boto3.client('s3')
    data = s3.get_object(Bucket=bucket, Key=key)
    body = data['Body'].read()
    return body
 
   
def put_s3_core(bucket, key, strobj):  
    s3 = boto3.resource('s3')
    request_obj = s3.Object(bucket, key)
    request_obj.put(Body=strobj)                   # adds this object to the bucket.


def write_buff_to_s3path(s3path, buff):
    s3dict = parse_s3path(s3path)
    put_s3_core(s3dict['bucket'], s3dict['key'], buff) 
    if not does_s3path_exist(s3path):
        utils.sts(f"s3path {s3path} not found after write_buff_to_s3path. Perhaps bucket is incorrectly specified.", 3)
        sys.exit(1)
    
    
def read_buff_from_s3path(s3path):
    if not does_s3path_exist(s3path):
        utils.sts(f"s3path {s3path} not found, cannot read_buff_from_s3path", 3)
        sys.exit(1)
    s3dict = parse_s3path(s3path)
    buff = get_s3_core(s3dict['bucket'], s3dict['key'])
    return buff
    

def read_csv_from_s3path(s3path, user_format=False, dtype=None):
    buff = read_buff_from_s3path(s3path)
    # s3dict = parse_s3path(s3path)
    # client = boto3.client('s3')
    # csv_obj = client.get_object(Bucket=s3dict['bucket'], Key=s3dict['key'])
    # body = csv_obj['Body']
    # csv_string = body.read().decode('utf-8')
    if user_format:
        buff = utils.preprocess_csv_buff(buff)
        from models.DB import DB

        return DB.buff_csv_to_df(buff, user_format=user_format, dtype=dtype)
    else:
        sio = io.StringIO(buff.decode('utf-8'))
        return pd.read_csv(
            sio, 
            na_filter=False, 
            index_col=False,
            dtype=dtype
            )

    
def read_lod_from_s3path(s3path, user_format=False):
    df = read_csv_from_s3path(s3path=s3path, user_format=user_format)
    lod = df.to_dict(orient='records')
    return lod

def read_xlsx_from_s3path(s3path):
    s3_IO_obj = get_s3path_IO_object(s3path)    
    return pd.read_excel(s3_IO_obj)
    

def write_df_to_csv_s3path(s3path, df):
    buff = df.to_csv(None, index=False)     # None as path or buff encodes as csv and returns string
    write_buff_to_s3path(s3path, buff)
    if not does_s3path_exist(s3path):
        utils.sts(f"s3path {s3path} not found after write_df_to_csv_s3path. Perhaps bucket is incorrectly specified.", 3)
        sys.exit(1)
    

def list_files_in_prefix_s3(s3path, file_pat=None):
    # use DB.list_files_in_dirname_filtered
    # r'(^\d+).\w+$'
    #utils.sts("Editign not finished on this!", 3)
    #sys.exit(1)
    # use DB.list_files_in_dirname_filtered

    s3dict = parse_s3path(s3path)

    s3 = boto3.resource('s3')
    bucket_obj = s3.Bucket(s3dict['bucket'])
    
    prefix = s3dict['prefix']
    
    #items = [obj.key.split(prefix)[1] for obj in bucket_obj.objects.filter(Prefix=prefix)]
    items = [obj.key for obj in bucket_obj.objects.filter(Prefix=prefix)]
    
    if file_pat is not None:
        r = re.compile(file_pat)
    
        result = []
        for item in items:
            if r.search(item):
                result.append(item)
    else:
        result = items

    return result


def get_s3path_IO_object(s3path):
    """ given s3path, like 's3://bucket/prefix/rootname.ext' 
        provide a filelike object that can be used like a local file.
    """

    s3dict = parse_s3path(s3path)
   
    s3 = boto3.resource("s3")
    s3_object = s3.Object(bucket_name=s3dict['bucket'], key=s3dict['key'])

    return S3File(s3_object)    # returns s3_IO_obj that can be treated like a file.
    

def does_s3path_exist(s3path) -> bool:
    """ Checks if file/directory exists on S3 bucket.
        Lighter function than 'prefix_exists' because
        it only checks the head of the object.
    
    :param bucket: name of the S3 bucket
    :param key: file path on S3 bucket
    :return boolean: True if key exists, False if key does not exist
    """
    
    s3_dict = parse_s3path(s3path)
    
    s3_client = boto3.client('s3')
    try:
        s3_client.head_object(Bucket=s3_dict['bucket'], Key=s3_dict['key'])
        return True
    except ClientError:
        # Key not found
        return False


    

class S3File(io.RawIOBase):
    """ this class allows a file on s3 to be opened and used as if it is a local file
    """

    def __init__(self, s3_object):
        self.s3_object = s3_object
        self.position = 0

    def __repr__(self):
        return "<%s s3_object=%r>" % (type(self).__name__, self.s3_object)

    @property
    def size(self):
        return self.s3_object.content_length

    def tell(self):
        return self.position

    def seek(self, offset, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            self.position = offset
        elif whence == io.SEEK_CUR:
            self.position += offset
        elif whence == io.SEEK_END:
            self.position = self.size + offset
        else:
            raise ValueError("invalid whence (%r, should be %d, %d, %d)" % (
                whence, io.SEEK_SET, io.SEEK_CUR, io.SEEK_END
            ))

        return self.position

    def seekable(self):
        return True

    def read(self, size=-1):
        if size == -1:
            # Read to the end of the file
            range_header = "bytes=%d-" % self.position
            self.seek(offset=0, whence=io.SEEK_END)
        else:
            new_position = self.position + size

            # If we're going to read beyond the end of the object, return
            # the entire object.
            if new_position >= self.size:
                return self.read()

            range_header = "bytes=%d-%d" % (self.position, new_position - 1)
            self.seek(offset=size, whence=io.SEEK_CUR)

        return self.s3_object.get(Range=range_header)["Body"].read()

    def readable(self):
        return True

def parse_arn(arn_str):
    """ arndict = parse_arn(arn_str)
        arn format: arn:<partition>:<service>:<region>:<account>:<resource>
    """

    arndict = {}
    match = re.search(r'^\s*arn:([^:]*):([^:]*):([^:]*):([^:]*):(.*)\s*$', arn_str)
    
    arndict['partition']    = match[1]
    arndict['service']      = match[2]
    arndict['region']       = match[3]
    arndict['account']      = match[4]
    arndict['resource']     = match[5]
    
    if arndict['service'] == 's3':
        match = re.search(r'^([^/]*)/(.*)$', arndict['resource'])
        arndict['bucket']       = match[1]
        arndict['key']          = match[2]
    return arndict
    

def parse_s3path(s3path):
    """ the s3 path we use is the same as what is used by s3 console.
        format is:
            s3://<bucket>/<prefix>/<basename>
            
        where <prefix>/<basename> is the key.
    """
    s3dict = {}
    match = re.search(r'(.*://)([^/]+)/(.*/)(.*)$', s3path)
    
    if match:
        s3dict['protocol']      = match[1]
        s3dict['bucket']        = match[2]
        s3dict['prefix']        = match[3]
        s3dict['basename']      = match[4]
        s3dict['key']           = s3dict['prefix'] + s3dict['basename']
    
    if (not match or
        s3dict['protocol'] != 's3://' or
        not s3dict['bucket'] or
        not s3dict['key']):
    
        utils.exception_report(f"s3_path format invalid: {s3path}")
        sys.exit(1)
    return s3dict

def delete_s3paths(s3paths):
    """ delete a list of s3path in single bucket 
    
    Delete={
            'Objects': [
                {
                    'Key': 'string',
                    'VersionId': 'string'
                },
            ],
            'Quiet': True|False
        },
        MFA='string',
        RequestPayer='requester',
        BypassGovernanceRetention=True|False
    )
    this has been tested.
    
    """
    
    s3dict = parse_s3path(s3paths[0])
    s3 = boto3.resource('s3')
    bucket_obj = s3.Bucket(s3dict['bucket'])
    
    objects_list = []
    for s3path in s3paths:
        s3dict = parse_s3path(s3path)
        objects_list.append({'Key': s3dict['key']})
        
    bucket_obj.delete_objects(Delete={'Objects': objects_list})

    utils.sts(f"Deleted {s3paths}", 3)

def invoke_lambda(
        function_name: str = None,
        async_mode: bool = False,
        custom_payload: dict = None,
        region: str = 'us-east-1'
) -> dict:
    if function_name is None:
        raise Exception(f"Missing parameter: "
                        f"{get_func_param(invoke_lambda(), 'function_name')}")

    lambda_client = boto3.client('lambda', region_name=region)
    response = None
    try:
        print(f"Launching: {function_name.split('function')[0]}")
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType='Event' if async_mode else 'RequestResponse',
            Payload=json.dumps(custom_payload)
        )
        rid = response['ResponseMetadata']['RequestId']
        status = response['ResponseMetadata']['HTTPStatusCode']
        print(f"ID: {rid if rid is not None else ''}\nStatus: {status}")
        if not async_mode:
            result = json.loads(response['Payload'].read())
            print(f"\nResult: {result}")
        return response
    except (ClientError, TypeError) as error:
        logging.error(f"Failed to invoke a lambda function:\n{error}")
        return response
        
        
def get_func_param(func_name, param: str) -> str:
    return signature(func_name).parameters[param]



MAX_THREADS = 10
CUSTOM_CONFIG = TransferConfig(max_concurrency=MAX_THREADS, use_threads=True)


def fetch_s3key_to_dirpath(s3key: str, local_dirpath: str, bucket_obj, silent=True):
    """ download object with key s3key from bucket_obj
        extract basename from key
        write to local_dirpath
    """

    s3basename = s3key.rpartition('/')[-1]
    local_path = os.path.join(local_dirpath, s3basename)
        
    if not silent:
        utils.sts(f"Fetching: {s3key} to {local_path}", 3)
        
    bucket_obj.download_file(s3key, local_path, Config=CUSTOM_CONFIG)
    

def upload_filepath_to_s3path(filepath, s3filepath):
    s3dict = parse_s3path(s3filepath)
    upload_file(file_path=filepath, s3_object_name=s3dict['key'], bucket=s3dict['bucket'])


def upload_file(
        # file_name: str,
        file_path: str,
        s3_object_name,
        bucket,
) -> bool:
    """
        Upload a file to an S3 bucket
    :param file_path: local path to file to upload.
    :param file_name: filename to use on s3 for this file in bucket.
    :param bucket: Bucket to upload to
    :param s3_object_name: S3 object name. If not specified then file_name is used
    :return: True if file was uploaded, else False
    """
    if s3_object_name is None:
        s3_object_name = os.path.basename(file_path)

    s3_client = boto3.client('s3')
    try:
        # A sentinel that handles segmentation fault on Linux Python 3.7+ while using boto3
        is_linux = platform.system() == 'Linux' and os.name == 'posix'
        if sys.version_info >= (3,7,0) and is_linux:
            cmd = f"aws s3 cp {file_path} s3://{bucket}/{s3_object_name}"
            subprocess.run(cmd, shell=True)
        else:
            # note that f-strings not avaiable until 3.6
            logging.info(f"Uploading {file_path} to s3://{bucket}/{s3_object_name}...")
            s3_client.upload_file(
                file_path, bucket, s3_object_name, Config=s3_config,
                Callback=ProgressPercentage(file_path)
            )
    except ClientError as error:
        logging.error(f"Failed to upload {file_path} to s3://{bucket}/{s3_object_name} due to: {error}")
        return False
    return True
    

class ProgressPercentage(object):
    """
    A simple class implementing a porgress bar. The class is passed as
    an additional argument to upload_file().
    """

    def __init__(self, filename):
        self._filename = filename
        self._size = float(os.path.getsize(filename))
        self._seen_so_far = 0
        self._lock = threading.Lock()

    def __call__(self, bytes_amount):
        with self._lock:
            self._seen_so_far += bytes_amount
            percentage = (self._seen_so_far / self._size) * 100
            sys.stdout.write(
                "\r%s %s / %s bytes (%.2f%%)" % (self._filename, self._seen_so_far, self._size, percentage)
            )
            sys.stdout.flush()


def list_files_in_s3dirpath(s3dirpath, file_pat=None, fullpaths=False):
    """ tested """
    
    s3dict = parse_s3path(s3dirpath)
    bucket = s3dict['bucket']
    prefix = s3dict['prefix']
    
    s3 = boto3.resource('s3')
    bucket_obj = s3.Bucket(bucket)
    objs = bucket_obj.objects.filter(Prefix=prefix)
    all_s3keys = list(obj.key for obj in objs)
    if file_pat is None:
        s3paths = [f"s3://{bucket}/{key}" for key in all_s3keys]
    else:
        s3paths = [f"s3://{bucket}/{key}" for key in all_s3keys if bool(re.search(file_pat, key))]
    if fullpaths:
        return s3paths
        
    return [os.path.basename(p) for p in s3paths]
    


def download_entire_s3dirpath_filtered(s3dirpath: str, local_dirpath, file_pat=None): #, keep_contents=False):
    """ given dirname on s3, download all files into dirname on local machine.
   
    returns number of flies downloaded.
    """

    utils.sts(f"Downloading\n  From:{s3dirpath}\n    To:{local_dirpath}\n  with filter:'{file_pat}'", 3)
    s3dict = parse_s3path(s3dirpath)
    job_prefix = s3dict['prefix']

    #s3_client = boto3.client('s3', config=botocore.client.Config(max_pool_connections=MAX_THREADS))
    
    s3 = boto3.resource('s3')
    bucket_obj = s3.Bucket(s3dict['bucket'])
    all_s3keys = list(obj.key for obj in bucket_obj.objects.filter(Prefix=job_prefix))
    if file_pat:
        filtered_s3keys = [key for key in all_s3keys if bool(re.search(file_pat, key))]
    else:
        filtered_s3keys = all_s3keys
    utils.sts(f"Starting downloading files. {len(filtered_s3keys)} found.")

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        executor.map(lambda s3key: fetch_s3key_to_dirpath(s3key, local_dirpath, bucket_obj), filtered_s3keys)
    executor.shutdown()
    utils.sts("Finished")
    
    return len(filtered_s3keys)
    
