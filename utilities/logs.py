# logs.py
import os
import sys
import glob
import shutil
from models.DB import DB
from utilities import utils

""" This module deals with log file from lambda processes.

    Each lambda creates a logfile in /tmp because that is the only place
    files can be created in a lambda.
    
    Prior to shutting down the lambda, it copies the log file to 's3://{bucket}/{job_name}/logs'
    with filename "log_{chunk_name}.txt", where
    chunk_name is {group_root}_{dirname}_chunk_{str(chunk_idx)}
    
    for genbif:
        log_{archive_rootname}_bif_chunk_NNN.txt
    for gentemplate:
        log_{style_num}_styles_chunk_NNN.txt
    for genrois:
        log_{style_num}_rois_chunk_NNN.txt
    for maprois:
        log_{style_num}_map_chunk_NNN.txt
    for extractvote:
        log_{archive_rootname}_marks_chunk_NNN.txt
    for cmpcvr:
        log_{archive_rootname}_cmpcvr_chunk_NNN.txt
        
    

"""

def get_logfile_pathname(rootname='log'):
    """ lambdas can only open files in /tmp
        Used only within this module.
    """
    if utils.on_lambda():
        return f"/tmp/{rootname}.txt"
    else:
        dirpath = DB.dirpath_from_dirname('logs', s3flag=False)   # this also creates the dir
        return f"{dirpath}{rootname}.txt"
        
    
def rm_logfile(rootname='log'):
    """ It is necessary when first entering a lambda to remove any stale files 
        because state is not initialized by the system.
        This is also true when we simulate lambda operation locally.
    """

    pathname = get_logfile_pathname(rootname=rootname)
    if os.path.isfile(pathname):
        os.remove(pathname)


def append_report_by_pathname(pathname, string, end="\n"):
    """ Create report name of string in reports 
        Used only within this module.
    """
    try:
        with open(pathname, mode='ta+', buffering=1024, encoding="utf8") as fh:
            print(string, file=fh, end=end)
    except:
        print(f"Failed to append to file: {pathname}")
        sys.exit(1)


def append_report(string, end='\n', rootname='log'):
    if not string: return
    logfile_path = get_logfile_pathname(rootname=rootname)
    append_report_by_pathname(logfile_path, string, end=end)


def sts(string, verboselevel=0, end='\n'):
    """ Append string to logfile report.
        Also return the string so an interal version can be maintained
        for other reporting.
        The standard logger function could be used but we are interested
        in maintaining a log linked with each phase of the process.
    """

    if not string: return
    append_report(string, end=end, rootname='log')    
    if utils.is_verbose_level(verboselevel):
        print(string, end=end)
    return string+end


def exception_report(string):
    if not string: return
    append_report('----------------------------------------\n' + string, rootname='exc')
    sts(string, 3)


def print_disagreements(string, end='\n'):
    append_report(string, rootname='disagreements', end=end)


def merge_txt_dirname(dirname: str, destpath: str, file_pat: str, subdir=None): #, main_logfile: str = "logfile.log"):
    """
    Local only.
    Consumes all .txt files in a given dirname and merges them into one
    :param dirname: name of dir of chunks to combine.
    :param destpath: path of file to create with combined files.
    :return:
    """
    dirpath = DB.dirpath_from_dirname(dirname, subdir=subdir, s3flag=False)
    txt_files = glob.iglob(os.path.join(dirpath, file_pat))
    with open(destpath, "a+b") as wfh:
        for txt_file in txt_files:
            with open(txt_file, 'rb') as rfh:
                shutil.copyfileobj(rfh, wfh)
    return len(list(txt_files))
    

def report_lambda_logfile(s3dirname, chunk_name, rootname="log", subdir=None):
    """ copy lambda logfile at /tmp/log.txt to s3dirname
        only if it exists and has nonzero size.
    """
    logfile_pathname = get_logfile_pathname(rootname=rootname)  # this generates the path to the lambda or local folder for the logs.
    upload_name = f"{rootname}_{chunk_name}"
    print(f"Reading logfile {logfile_pathname}")
    #import pdb; pdb.set_trace()
    buff = read_logfile(logfile_pathname)
    print(f"Saving logfile {logfile_pathname} to {s3dirname} as {upload_name}")
    if buff:
        file_path = DB.save_data(data_item=buff, dirname=s3dirname, name=f"{rootname}_{chunk_name}", format='.txt', subdir=subdir)
        print(f"logfile {rootname}, {len(buff)} characters saved to {file_path}")
    

def get_and_merge_s3_logs(dirname, rootname='log', chunk_pat=None, subdir=None):
    """
    Fetches all lambda logs from a job folder on S3 that meet rootname, chunk_pat.
    combine into one file, write it to dirname/{rootname}_{dirname}.txt
    :param logs_folder: an S3 folder to fetch lambda logs from
    :return:
    
    log file name: f"log_{group_root}_{dirname}_chunk_{str(chunk_idx)}.txt"
    """
    utils.sts(f"Getting the {rootname} files from s3 and combining")
    
    # download all the log files
    # make sure tmp is empty.
    tmp_dirpath = DB.dirpath_from_dirname('tmp')
    shutil.rmtree(tmp_dirpath, ignore_errors=True)
    
    sts(f"Downloading all {rootname} files, one per chunk", 3)
    # download according to matching pattern
    DB.download_entire_dirname(dirname=dirname, subdir=subdir, file_pat=fr"{rootname}_{chunk_pat}\.txt", local_dirname='tmp')
    
    sts(f"Combining {rootname} files", 3)
    dest_name = f"{rootname}_{dirname}.txt"
    dest_dirpath = DB.dirpath_from_dirname(dirname=dirname, s3flag=False)
    combined_log_filepath = dest_dirpath + dest_name

    num_files = merge_txt_dirname(dirname='tmp', subdir=subdir, destpath=combined_log_filepath, file_pat=f"{rootname}_*.txt")
    
    sts(f"Writing combined {rootname} file: {combined_log_filepath} to s3 in dirname:'{dirname}'", 3)
    if os.path.exists(combined_log_filepath):
        DB.upload_file_dirname(dirname, dest_name, local_dirname='tmp')
    return num_files

def read_logfile(logfile_path: str):
    """
    Reads a logfile to an obj.put(Body=)
    :param logfile_path: a path to a logfile.txt
    :return:
    """
    try:
        with open(logfile_path, mode='rt', encoding="utf8") as lf:
            return lf.read()
    except FileNotFoundError:
        return None

    




