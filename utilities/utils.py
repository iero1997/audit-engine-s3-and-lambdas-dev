import os
import re
import csv
import sys
import shutil
#import logging
import math
import glob
#import tempfile
import platform
#import pandas as pd
#from pathlib import Path
#from utilities import config_d

if __name__ != "__main__":
    from utilities import args, logs
    from models.DB import DB
    from utilities.config_d import config_dict

LOGFILE_PATHNAME = None

def is_linux(): return platform.system() == 'Linux'

def on_lambda():
    try:
        region = os.environ['AWS_REGION']
    except:
        # Not in Lambda environment
        return False
    region += ''     # trick lint
    return True


def list_from_csv_str(csvstr):
    """ this function can be used to intelligently split fields in the input file.
        commas can be embedded in fields if they are surrounded by double quotes.
        please note: single quotes do not work!
        Single quoting will NOT allow embedded commas and is worthless!
        The input fields should be inspected for sanity and feedback provided before
        we get to this point and feedback provided to the user if they use single quotes.
    """
    csvobj = csv.reader([csvstr], delimiter=',', skipinitialspace=True)
    result_list = next(csvobj)
    for x in result_list:
        if x[0] == "'" and x[-1] == "'":
            x = x[1:-1]
        if x[0] == '"' and x[-1] == '"':
            x = x[1:-1]
    return result_list


def sane_str(string, limit=50):
    """ remove newlines and shorten to limit. """
    return re.sub(r'[\n\r]', ' ', string[:limit])


def is_verbose_level(verboselevel):
    verbose_setting = args.argsdict.get('verbose', 3)

    return bool(verbose_setting >= verboselevel)


def read_logfile(logfile_path: str):
    """
    Reads a logfile to an obj.put(Body=)
    :param logfile_path: a path to a logfile.txt
    :return:
    """
    try:
        with open(logfile_path) as lf:
            return lf.read()
    except FileNotFoundError:
        return ""

    
# def get_logfile_pathname(rootname='log'):
    # if on_lambda():
        # return f"/tmp/{rootname}.txt"
    # else:
        # dirpath = DB.dirpath_from_dirname('logs')   # this also creates the dir
        # return f"{dirpath}{rootname}.txt"
    

# def lambda_log_dump(string: str, file: str = "logfile.txt", exception: bool = False,
                    # disagreement: bool = False):
    # """
    # A condensed port of utilities.sts() for dumping lambda logs to a file.
    # :param stream: a string message
    # :param file: log file that defaults to 'logfile.txt' for each lambda
    # :param exception: a switch to separate regular stream from an exception
    # :param disagreement: a switch to separate regular stream from an disagreement
    # :return:
    # """
    # tmp_logfile_pathname = get_logfile_pathname()
    # try:
        # log = open(tmp_logfile_pathname, "a", buffering=2048)
    # except (FileNotFoundError, TypeError) as error:
        # logging.error(error)
    # else:
        # if exception or disagreement:
            # string = "exception_report" + "-" * 20 + "\n" + string
        # log.write(string + "\n")


def exception_report(string):
    return logs.exception_report(string)


def sts(string, verboselevel=0, end='\n'):
    return logs.sts(string, verboselevel, end)


def print_disagreements(string):
    logs.print_disagreements(string)


def find_duplicates(array: list) -> list:
    """
    Return a list of the duplicates occurring in a given array.
    If there are no duplicates, return empty list.
    """
    dupes = []
    seen = set()
    for x in array:
        if x in seen:
            dupes.append(x)
        seen.add(x)
    return dupes


def show_logo():
    return print(config_dict['LOGO'])


def show_version():
    current_version = f"0.{config_dict['MAJOR_RELEASE']}.{config_dict['MINOR_RELEASE']}"
    return current_version


def delete_folder_files(folder):
    """Deletes folder passed as path, and all contents, includig subfolders.
    """
    if not os.path.exists(folder):
        return
    for the_file in os.listdir(folder):
        file_path = os.path.join(folder, the_file)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except OSError as error:
            print(error)


def clear_resources():
    """Clears all resource folders."""
    print("Removing resources folder...", end=' ')
    delete_folder_files(config_dict['RESOURCES_PATH'] + config_dict['STYLES_PATHFRAG'])
    delete_folder_files(config_dict['RESOURCES_PATH'] + config_dict['RESULTS_PATHFRAG'])
    delete_folder_files(config_dict['RESOURCES_PATH'] + config_dict['DISAGREEMENTS_PATHFRAG'])
    delete_folder_files(config_dict['RESOURCES_PATH'] + config_dict['SUMMARY_PATHFRAG'])
    delete_folder_files(config_dict['RESOURCES_PATH'] + config_dict['FUZZY_MATCH_PATHFRAG'])
    print("OK")


def show_time(time_in_seconds: float) -> str:
    """
    Converts float time value from time.time() object in seconds
    to an approximation in a human readable format.
    >>> show_time(668.0372)
    >>> 'Processed in 00:11:06'
    :param time_in_seconds: time.time() object float value
    :return human_readable_time: a string in the OO:OO:OO format.
    """
    if isinstance(time_in_seconds, float):
        minutes, seconds = divmod(int(time_in_seconds), 60)
        hours, minutes = divmod(minutes, 60)
        human_readable_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return human_readable_time
    else:
        raise TypeError("Invalid time execution input.")

def apply_regex(s:str, regex:str, default=None, remove_quotes=True):
    """ Extract a substring from str based on regex
        remove surrounding " quotes if they are included in the regex pattern due to input requirements.
        if no regex is provided, return default or s without change if default is None
    """

    if remove_quotes:
        regex = regex.strip('"')
        
    if regex:
        try:
            result = str(re.search(regex, s, re.S)[1])
        except:
            result = ''
        return result
    elif default is None:
        return s
    else:
        return default
    

assert apply_regex(r'AB-001+10001.jpg', r'^(......).*$') == 'AB-001'


def reduce_dict(input_dict:dict):
    """
    reduced_dict, map_dict = reduce_dict(input_dict)

    Given input dict, create a reduced_dict which only has unique values.
    map_dict contains an entry for every original key and maps it to the new key.
    returns reduced_dict and map_dict

    thus, reduced_dict[map_dict[original_key]] is equivalent to input_dict[original_key]
    """

    reduced_dict = {}
    map_dict = {}

    for orig_key, val in input_dict.items():
        reduced_key = key_of_value(reduced_dict, val)
        if reduced_key is None:
            # no entry in reduced_dict matches.
            reduced_dict[orig_key] = val
            map_dict[orig_key] = orig_key
        else:
            map_dict[orig_key] = reduced_key

    return reduced_dict, map_dict


def key_of_value(dict, value):
    """ return the key of the first item in the dict which matches value)
    """

    for key, val in dict.items():
        if value == val:
            return key
    return None


def group_list_by_dod_attrib(input_list: list, dod, key2):
    """ Given an input_list, split it into dict_of_list based on value of
        dod[list_item][key2].  Produces
        dol[key2] = [list of list_items]
    """
    result_dol = {}

    for val in input_list:
        try:
            attrib = dod[val][key2]
        except:
            continue

        if not attrib in result_dol:
            result_dol[attrib] = []

        result_dol[attrib].append(val)

    return result_dol

assert group_list_by_dod_attrib(['a', 'b', 'c', 'd', 'e'], {'a': {'s': 0}, 'b' : {'s': 1}, 'c' : {'s': 1}, 'd' : {'s': 0}}, 's') == {0: ['a', 'd'], 1: ['b', 'c']}, "group_list_by_attrib failed"


def invert_dol_to_dict(input_dol:dict) -> dict:
    """ given a dict of lists where no element in any is seen twice,
        create a dict, where the list elements are the key and the
        value is the prior key. This allows reverse lookup of key
        based on values in the list. If some dict lists have duplicates,
        the last item will dominate.
    """
    result_dict = {}

    for key, lst in input_dol.items():
        for val in lst:
            result_dict[val] = key

    return result_dict


def set_default_int(val, default):
    """ if val is null str, None or Nan, set value to default 
        This is convenient when processing values from df or csv
    """
    if val == '' or val is None or math.isnan(val):
        val = default
    return int(val)


def get_dirdict(dirpath: str, file_type: str, silent_error:bool = False) -> dict:
    """
        return dict of files in dir at dirpath,
        keyed by root filename (w/ extension) and
        the value is the full path to the file.
    """
    try:
        filelist = os.listdir(dirpath)
    except OSError as error:
        if silent_error:
            return {}
        else:
            print(f"Failed to list directory {dirpath}: {error}")
            sys.exit(1)

    filelist = [f for f in filelist if f.lower().endswith(file_type)]

    dirdict = {}
    for file in filelist:
        #root, _ = os.path.splitext(file)
        dirdict[file] = os.path.join(dirpath, file)

    return dirdict


def casefold_list(lst):
    return [item.casefold() for item in lst]


def extract_region(image, region, mode='clear'):
    """ given an image and region dict
        make a copy of the image and isolate the region per mode
        'clear' -- return image of same size but clear everything except for region specified.
        'crop' -- return smaller image cropped to the dimensions in region.
    """
    
    x, y, w, h = region['x'], region['y'], region['w'], region['h']

    if mode == 'clear':
        working_image = image.copy()
        # clearing up left vertical shapes image
        working_image[:y, :] = 255     # clear area above region
        working_image[y + h:, :] = 255 # clear area below region
        working_image[:, :x] = 255     # clear area left of region
        working_image[:, x + w:] = 255 # clear area right of region
    else:
        working_image = image[y:y+h, x:x+w].copy()
    return working_image


def write_file(filepath, strobj):
    """ write strobj to filepath, creating any intermediate folders necessary
    """
    #dirpath, filename = os.path.split(filepath)    # does not handle mixed separators
    dirpath, filename = safe_path_split(filepath)
    
    if not os.path.isdir(dirpath):
        os.makedirs(dirpath)
    try:
        fh = open(filepath, mode='w')
        fh.write(strobj)
        fh.close()
    except OSError as err:
        print (err)
        sys.exit(1)
        
        
def read_file(filepath):
    try:
        fh = open(filepath, mode='r')
        strobj = fh.read()
        fh.close()
    except OSError as err:
        print (err)
        sys.exit(1)
        
    return strobj
    
def remove_dirpath_contents(dirpath):
    """ remove files and folders from dirpath provided.
    """
    for c in os.listdir(dirpath):
        full_path = os.path.join(dirpath, c)
        if os.path.isfile(full_path):
            os.remove(full_path)
        else:
            shutil.rmtree(full_path)
    

def remove_dirname_files_by_pattern(dirname, file_pat=None):
    """ remove files from dirpath that match regex file_pat
    """
    dirpath = DB.dirpath_from_dirname(dirname)
    for filename in os.listdir(dirpath):
        full_path = os.path.join(dirpath, filename)
        if os.path.isfile(full_path) and not (file_pat and bool(re.search(file_pat, filename))):
            os.remove(full_path)

def remove_local_files(filepaths):
    for filepath in filepaths:
        if os.path.isfile(filepath):
            os.remove(filepath)


def calc_chunk_sizes(num_items, max_chunk_size, max_concurrency):
    """ given num_items, divide these into equal
        chunks where each is no larger than chunk_size,
        but may be so small as to produce up to max_concurrency
        return list of chunk sizes.
    """
    if not num_items:
        return []
        
    if False:
        min_chunk_size_for_max_concurrency = (num_items // max_concurrency) + 1
        eff_max_size = min(min_chunk_size_for_max_concurrency, max_chunk_size)
    else:
        eff_max_size = max_chunk_size
        
    num_chunks = num_items // eff_max_size
        
    residue = num_items % max_chunk_size
    if residue:
        num_chunks += 1
    chunk_size = num_items // num_chunks
    residue = num_items % num_chunks

    first_list = [chunk_size + 1] * residue
    second_list = [chunk_size] * (num_chunks - residue)

    chunk_sizes_list = first_list + second_list

    return chunk_sizes_list
    

def convert_sizes_to_idx_ranges(sizes_list):
    """ 
        given sizes list, convert to list of tuples of ranges,
        (start,end) where end is one past the last item included.
    """
    
    ranges_list = []

    os = 0
    for size in sizes_list:
        range = (os, os+size)
        os += size
        ranges_list.append(range)

    return ranges_list
    

def split_list_into_chunks(item_list, chunk_sizes_list):
    """ given item list, split it based on chunk_sizes_list provided.
        return list of lists with those sizes.
    """
    result_lol = []

    os = 0
    for size in chunk_sizes_list:
        sublist = item_list[os:os+size]
        os += size
        result_lol.append(sublist)

    return result_lol
    

def split_list_into_chunks_lol(item_list, max_chunk_size, max_concurrency):
    """ given item_list, divide it evenly into a list of chunks, 
        with sizes less than max_chunk_size, and with at least max_concurrency chunks.
    """
    chunk_sizes_list = calc_chunk_sizes(num_items=len(item_list), max_chunk_size=max_chunk_size, max_concurrency=max_concurrency)
    chunks_lol = split_list_into_chunks(item_list, chunk_sizes_list)
    return chunks_lol


def split_df_into_ranges(df, chunk_ranges):
    """ Given a df and list of (start,end) ranges, split df into list of df.
    """
    chunks_lodf = [df[start:end] for start,end in chunk_ranges]
    return chunks_lodf
    

def split_df_into_chunks_lodf(df, max_chunk_size, max_concurrency):
    """ given a dataframe, split it evenly into a list of dataframes.
    """
    chunk_sizes_list = calc_chunk_sizes(num_items=len(df.index), max_chunk_size=max_chunk_size, max_concurrency=max_concurrency)
    chunk_ranges = convert_sizes_to_idx_ranges(chunk_sizes_list)
    chunks_lodf = split_df_into_ranges(df, chunk_ranges)
    return chunks_lodf

def merge_results(argsdict):
    merge_csv_dirname_local(argsdict, dirname='marks', dest_name='ballot_marks_df.csv', file_pat=r'marks.*\.csv')
    

def merge_csv_dirname_local(dirname, subdir, dest_name, dest_dirname=None, file_pat=None):
    """ merge all csv files in local dirname meeting file_pat into one to dest_name
        uses header line from first file, discards header is subsequent files.
        all csv files must have the same format.
    """
    
    if dest_dirname is None: dest_dirname = dirname

    sts(f"Merging csv from {dirname} to {dest_dirname}/{dest_name}", 3)

    src_dirpath = DB.dirpath_from_dirname(dirname, subdir=subdir, s3flag=False)
    dest_dirpath = DB.dirpath_from_dirname(dest_dirname, s3flag=False)
    destpath = os.path.join(dest_dirpath, dest_name)

    first_pass = True
    infilepath_list = glob.glob(f"{src_dirpath}*.csv")
    
    for idx, infilepath in enumerate(infilepath_list):
        basename = os.path.basename(infilepath)
        if file_pat is not None and not re.search(file_pat, basename):
            # skip any files that are not the lambda download format, including the one being built
            continue
        if infilepath == destpath:
            # make sure we are not appending dest to itself.
            continue
        #sts(f"Appending result #{idx} from {infilepath}", 3)
        if first_pass:
            shutil.copyfile(infilepath, destpath)
            # first file just copy to new name
            fa = open(destpath, 'a+', encoding="utf8")
            first_pass = False
            continue
        # the rest of the chunks, first strip header, and append
        with open(infilepath, encoding="utf8") as fi:
            buff = fi.read()
            lines = re.split(r'\n', buff)               # .decode('utf-8')
            non_header_lines = '\n'.join(lines[1:])     # skip header line
            fa.write(non_header_lines)        
    
    try:
        fa.close()
    except UnboundLocalError:
        pass

    
    
def combine_dirname_chunks_each_archive(argsdict, dirname):
    """ combine all the chunks in a specific dirname into {archive_rootname}_{dirname}.csv files, one per archive.
        Do this in the dirname folder.
    """

    for archive_idx, source in enumerate(argsdict['source']):
        archive_rootname = os.path.splitext(os.path.basename(source))[0]
        DB.combine_dirname_chunks(
            dirname=dirname, subdir='chunks', 
            dest_name=f"{archive_rootname}_{dirname}.csv", 
            file_pat=fr"{archive_rootname}_{dirname}_chunk_\d+\.csv")


def safe_path_split(path):
    # return head,tail allowing mixed separators, either '/' or '\\'
    return re.split(r'^(.*)[\\/]([^\\/]*)$', path)[1:3]


def path_sep_per_os(path, sep=None):
    """ based on os.sep setting, correct path to those separators, 
        assuming no / or \ characters exist in the path otherwise.
    """
    if sep is None:
        sep = os.sep
    if sep == '/':
        return re.sub(r'\\', r'/', path)
    else:
        return re.sub(r'/', r'\\', path)
    
def df_to_dod(df, field):
    """ Convert dataframe to dict-of-dict format, where first dict is based on field.
    """

    dod = {}
    idxdict = df.to_dict(orient='index')
    for idx in range(len(idxdict)):
        rowdict = idxdict[idx]
        key = rowdict[field].strip()
        if not key or key == '': continue
        dod[key] = rowdict
    return dod
    
    
   
def str2bool(value):
    """Parses string to boolean value."""
    if value is None or value == '':
        return False
    if isinstance(value, (bool, int)):
        return bool(value)
    if value.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    if value.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    raise ValueError(f"Boolean value expected, value:{value}")


def dodf_to_dolod(dodf):
    """ convert dict of dataframe to dict of list of dict.
    """
    dolod = {}
    
    for key, df in dodf.items():
    
        dolod[key] = df.to_dict(orient='records')
        
    return dolod
    
def get_next_item_dol(source_dol):
    """ given source dict of list, with ordered lists
        return dict of list, where each item provides the 
        next items in the source list, given a current item.
        resulting next_item_dol starts with None as first key, and
        if the item has no subsequent items, i.e. last in list,
        then an item in the set is None.
        None is always placed as the first item, even if it was appended last.
    """
    
    next_val_dol = {}
    
    for key in source_dol:
        prior_val = None
        for val in source_dol[key] + [None]:
            if prior_val in next_val_dol:
                if not val in next_val_dol[prior_val]:
                    next_val_dol[prior_val].append(val)
            else:
                next_val_dol[prior_val] = [val]
            prior_val = val
        
    return next_val_dol

def test_get_next_item_dol():

    test_dol = {
        1:	['A','B','C','D'],
        2:	['A','B','D','E'],
        3:	['B','C','F'],
        4:	['G','H','I'],
        5:	['G','I','J'],
        }
        
    expected_next_item_dol = {
        None: ['A','B','G'],
        'A': ['B'],
        'B': ['C', 'D'],
        'C': ['D', 'F'],
        'D': [None, 'E'],
        'E': [None],
        'F': [None],
        'G': ['H', 'I'],
        'H': ['I'],
        'I': [None, 'J'],
        'J': [None],
        }
        
    next_item_dol = get_next_item_dol(test_dol)
    
    if next_item_dol != expected_next_item_dol:
        import pprint
        print("'test_get_next_item_dol' failed")
        print(f"test_dol:{pprint.pformat(test_dol)}\n"
            f"expected_next_item_dol:\n{pprint.pformat(expected_next_item_dol)}\n"
            f"actual_next_item_dol:\n{pprint.pformat(next_item_dol)}")
            
            
def preprocess_csv_buff(buff):
    """ given a buffer which is csv file read without conversion,
        perform preprocessing to remove comments and blank lines.
        controls in pandas csv do not work very well, such as when
        there is a comma in a comment line.
    """
    
    lines = re.split('\n', buff)
    lines = [line for line in lines if line and not bool(re.search(r'^"?#', line)) and not bool(re.search(r'^,+$', line))]
    buff = '\n'.join(lines)
    
    return buff

if __name__ == "__main__":
    test_get_next_item_dol()
