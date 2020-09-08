#import io
import os
import re
import sys
import time
import logging
import zipfile
import traceback
from zipfile import ZipFile
from aws_lambda import s3utils


#import time


from utilities import utils, logs

# does anyone know why this TRY is here??
try:
    from utilities.config_d import config_dict

    from utilities.images_utils import get_images_from_pbm, get_images_from_pdf, get_images_from_png, get_images_from_tif
    from models.DB import DB
except ImportError:
    get_images_from_pbm = get_images_from_pdf = get_images_from_png = get_images_from_tif = None

PRECINCT_REG = re.compile(r'/(.*?)\.zip$')
BALLOT_FORMAT = {
    '.pdf': {
        'name_reg': r"(\d+i)\.pdf$",
        'get_images': get_images_from_pdf,
    },
    '.pbm': {
        'name_reg': r"(\w+)[FR]\.pbm$",
        'get_images': get_images_from_pbm,
    },
    '.png': {
        'name_reg': r"(\w+)\.png$",
        'get_images': get_images_from_png,
    },
    '.tif': {
        'name_reg': r"(\w+)\.tif$",
        'get_images': get_images_from_tif,
    },
    '.json': {
        'name_reg': r"(\w+)\.json$",
        'get_images': None,
    },
}


def analyze_ballot_filepath(file_path: str) -> tuple:  # returns name, extension, ballotid
    """ given file path, return filename, extension, ballotid = analyze_ballot_filepath(file_path)
        Note: extension includes '.'
    """
    #_, filename = os.path.split(file_path) 
    filename = utils.safe_path_split(file_path)[1]           # archives opened in linux env use both '/' and '\\' separators.
    name, extension = os.path.splitext(filename)
    
    # leave only digits and underscores in the ballotid
    ballotid = re.sub(r'[^\d_]', '', name)
    
    # sometimes there is an additional extension at th end of the file name.
    # this may indicate the sheet number, but the rest of the ballot_id is still unique
    ballotid = re.sub(r'^(\d{5}_\d{5}_\d{5,})_\d$', r'\1', ballotid)
    
    return name, extension, ballotid

def get_ballotid(file_path):
    return analyze_ballot_filepath(file_path)[2]

def get_ballotid_of_marks_df(file_path):
    match = re.search(r'^marks_df_(\d+)\.json$', file_path)
    return match[1]

def get_attribute_from_path(argsdict, ballot_image_path, attribute_name):
    """ given ballot_image_path from zip archive, extract attribute from path
        based on setting of level from argsdict for the attribute.
        attribute of -1 means not available.
        attribute_names are: 'precinct-folder', 'party-folder', 'group-folder'
        returns '' if attribute of -1 is specified.
    """

    attribute_str = ''
    path_segments = re.split(r'[/\\]', ballot_image_path)
    path_segments.pop()
    

    folder_level = int(argsdict.get(attribute_name, 0))  # -1 means the path does not provide this info.
    if folder_level >= 0:
        if not (folder_level < len(path_segments)):
            utils.sts(
                f"get_attribute_from_path: {attribute_name} input spec {folder_level} is out of range. Must be less than {len(path_segments)}\n"
                f"ballot_image_path provided is {ballot_image_path}")
            import pdb; pdb.set_trace()
            sys.exit(1)
        attribute_str = path_segments[folder_level]
    #elif attribute_name == 'precinct-folder':
    #    utils.exception_report(f"{attribute_name} specified as -1, this attribute cannot be determined from ballot file path. "
    #              f"Apparently all image files are provided in one big heap. Consider using 'precinct_pattern' input parameter.")
    #    attribute_str = 'Unspecified Precinct'

    return attribute_str


def get_precinct(argsdict, ballot_image_path):
    """
    Gets ballot 'precinct' and 'type' (party) based on ballot ballot image file path.
    If precinct_pattern is specified, it is used as regex to extract a portion of the filename.
    
    otherwise,
    If 'precinct-folder' is specified in the input file and it is not -1, it will be used, if possible.
    
    NOTE: These input parameters precinct-folder and party-folder are temporary. Instead, it will likely
          be possible to gather these parameters from the path for a given vendor without needing those
          parameters because the 'party' level is either there or not, and can only be a few different
          strings. Other vendors have other schemes.
          ES&S .pbm files from ES&S have the precinct encoded differently. Can use 'precinct_pattern' in these cases.
          use precinct_folder_pattern to extract active portion of the folder level specified.
    """
    precinct_str = ''
    precinct_pattern = argsdict.get('precinct_pattern')
    if precinct_pattern:
        filename, _, _ = analyze_ballot_filepath(ballot_image_path)
        precinct_str = utils.apply_regex(filename, precinct_pattern, default='')
        return precinct_str

    precinct_folder_pattern = argsdict.get('precinct_folder_pattern', '')
    if precinct_folder_pattern:
        precinct_folder_str = get_attribute_from_path(argsdict, ballot_image_path, 'precinct-folder')
        precinct_str = utils.apply_regex(precinct_folder_str, precinct_folder_pattern)
    
    return precinct_str


def get_party(argsdict, ballot_image_path):
    """
    Gets ballot 'party' based on ballot ballot image file path.
    If 'party-folder' is specified in the input file and it is not -1, it will be used, if possible.
    otherwise, the path compenents of 1 is used.
    string from the path are returned.
    
    TODO: These input parameters precinct-folder and party-folder are temporary. Instead, it will likely
          be possible to gather these parameters from the path for a given vendor without needing those
          parameters because the 'party' level is either there or not, and can only be a few different
          strings. Other vendors have other schemes.
    TODO: ES&S .pbm files from ES&S have the precinct encoded differently.
    """
    return get_attribute_from_path(argsdict, ballot_image_path, 'party-folder')

def get_group(argsdict, ballot_image_path):
    """ The group attribute typically separates VBM and inperson voting.
        SF uses the strings 'CGr_Election Day' and 'CGr_Vote by Mail'
    """
    
    return get_attribute_from_path(argsdict, ballot_image_path, 'group-folder')


def open_zip_archive(source, testzip=False):
    """ Gets ZIP archive from source file path
        Checks for error conditions and raises errors.
    """
    if not os.path.exists(source):
        raise FileNotFoundError('Source file not found')
    # check if passed argument is ZIP file
    if not zipfile.is_zipfile(source):
        raise ValueError('Source file is not in ZIP format')
    # load source archive
    archive_obj = ZipFile(source, 'r')
    # check if some files are corrupted
    if testzip:
        corrupted_file = ZipFile.testzip(archive_obj)
        if corrupted_file:
            print(f"Corrupted files: {corrupted_file}")
    return archive_obj
    
    
def set_archive_path_local_vs_s3(argsdict, archive_basename):
    """ function derives proper full path to archive either on s3 or local
    """
    archive_basename = os.path.basename(archive_basename)
    folder_path = argsdict['archives_folder_s3path'] if argsdict['use_s3_archives'] else argsdict['archives_folder_path']
    fullpath = os.path.join(folder_path, archive_basename)
    return fullpath
    
WAS_ARCHIVE_GENERATED_ON_WINDOWS_DICT = {}
def was_archive_generated_on_windows(archive_obj):

    try:
        archive_basename = os.path.basename(archive_obj.fp.name)
    except:
        # can't find basename for some reason -- we can't use lookup optimization
        return bool(re.search(r'\\', get_file_paths(archive_obj)[0]))

    if WAS_ARCHIVE_GENERATED_ON_WINDOWS_DICT.get(archive_basename, None) is None:
        # we have not evaluated this archive to detemine whether it was generated on windows.
        WAS_ARCHIVE_GENERATED_ON_WINDOWS_DICT[archive_basename] = bool(re.search('\\', get_file_paths(archive_obj)[0]))
    return WAS_ARCHIVE_GENERATED_ON_WINDOWS_DICT[archive_basename]

def open_archive(argsdict, archive_basename, silent_error=False):
    """ This is a general entry point for both local archives and s3 based archives.
        The source_path can be full path to local or s3 resources, or just basename.
        1. check argsdict['use_s3_archives']
        2. reduce source_path to just basename
        3. prepend either argsdict['archives_folder_path'] or argsdict['archives_folder_s3path']
    """
    
    fullpath = set_archive_path_local_vs_s3(argsdict, archive_basename)
        
    utils.sts(f"Opening source archive: {fullpath}", 3)
    
    if argsdict['use_s3_archives']:
        archive_obj = s3_open_archive(s3path=fullpath, silent_error=silent_error)
    else:
        archive_obj = open_local_archive(source_path=fullpath, silent_error=silent_error)
        
    return archive_obj


def open_local_archive(source_path, testzip=False, silent_error=False):
    """ Deals with the error conditions raised in open_zip_archive
        Q: why is it a good idea to keep these separate?
        It seems that only one archive can be open at a time.
        
    """
    # we've had trouble with spurious "file does not exist" detections when it does.
    source_path = os.path.normcase(os.path.normpath(source_path)).strip()
    
    if os.path.isfile(source_path):
        utils.sts(f"Verified that {source_path} exists.")
    else:
        utils.sts(f"Archive {source_path} does not exist according to os.path.exists().")
        
        # this may be a spurious problem related to using a file server.
        
        tot_time = 0
        for i in range(1,20):
            utils.sts(f"Waiting {i} seconds", 3)
            time.sleep(i)
            tot_time += i
            if os.path.isfile(source_path):
                utils.sts(f"After wait of {tot_time} secs, {source_path} now exists according to os.path.exists().", 3)
                #import pdb; pdb.set_trace()
                break
        else:
            utils.sts(f"After wait of {tot_time} secs, {source_path} still not found according to os.path.exists().", 3)
            import pdb; pdb.set_trace()
            sys.exit(1)
    
    try:
        archive = open_zip_archive(source_path, testzip)
    except (FileNotFoundError, ValueError) as error:
        if not silent_error:
            logging.error(f"Failed to open archive {source_path} Program failed due to %s", error)
            sys.exit(1)
        else:
            return None
    return archive
    



def s3_open_archive(s3path, silent_error=False):
    """ open archive according to s3path
        s3://<bucket>/US/WI/WI_Dane_2019_Spring_Pri/2019 Spring Primary Ballot Images.zip
    """
    if not s3utils.does_s3path_exist(s3path):
        if not silent_error:
            utils.sts(f"s3path: {s3path} not found. Cannot open archive.", 3)
            sys.exit(1)
        return None
    
    try:
        s3_IO_obj = s3utils.get_s3path_IO_object(s3path)
        archive_obj = ZipFile(s3_IO_obj, 'r')
    except (FileNotFoundError, ValueError) as error:
        if not silent_error:
            logging.error(f"Failed to open archive {s3path} Program failed due to %s", error)
            sys.exit(1)
        else:
            return None
    
    return archive_obj
    
    
def get_file_paths(archive_obj) -> list:
    """Gets a list of paths that end with an extension of any kind.
       It seems filtering at this stage is a waste of time.   
    """
    regex = r"\.\w+$"
    file_paths = filter(
        lambda file: file if re.search(regex, file) else False,
        ZipFile.namelist(archive_obj))
    return list(file_paths)

def adjust_filepath_separators(archive_obj, path):
    """ final path separators must be altered if archive was generated on windows and being read on linux.
        This occurs when the list of filepaths internal to the archive are listed on one platform and then
        used on the other, when the archive was originally created on Windows.
    """
    
    # this function deals with an inconsistency in zip archives
    # with regard to the last filepath separator in file names
    # in the archive.
    
    # There are four cases, based on whether the archive is 
    # produced and then viewed on Windows vs. Linux system.
    
    #                     Archive generated on:
    #              |------------------|------------------|
    #              |     Windows      |      Linux       |
    #              | Actual    Shown  | Actual    Shown  |
    # Viewed on:   |--------+---------|------------------|
    #   Windows    |   \    |    /    |   /    |    /    |
    #              |------------------|------------------|
    #   Linux      |   \    |    \    |   /    |    /    |    
    #              |------------------|------------------|
    
    # strangely, when an archive is generated on windows,
    # the last separator is actually \ but it is converted
    # by the library so it is /. Thus, if an archive is only
    # used on windows or only on linux, this is not a problem.
    # However, a zip archive used in linux will regard the
    # last separator not as a file separator, but as a 
    # legitimate filename character, and then join the 
    # basename with the prior path element as one file name.
    
    # In every case, what is shown is what must be used to
    #   access a file. Therefore, we will look at the first
    #   file entry, and if there are any file separators,
    #   then take the last one, and make that the required
    #   separator.

    # According to zip file specification:
    # https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT
            
    #   4.4.17.1 The name of the file, with optional relative path.
    #   The path stored MUST NOT contain a drive or
    #   device letter, or a leading slash.  All slashes
    #   MUST be forward slashes '/' as opposed to
    #   backwards slashes '\' for compatibility with Amiga
    #   and UNIX file systems etc.  If input came from standard
    #   input, there is no file name field.  
               
 

    if was_archive_generated_on_windows(archive_obj):
    
        if os.sep == '/':
            # Linux:
            # when trying to access entries using constructed paths, the last element must be changed
            # to match the true form of the files as stored in the zip archive.
            path = '\\'.join(utils.safe_path_split(path))
        else:
            # Windows:
            # When accessing an entry based on a list of files stored in the archive which was generated
            # on linux, then the windows interface requires that the separator be changed to '/'
            path = '/'.join(utils.safe_path_split(path))
            
    return path


def get_image_file_paths_from_archive(archive_obj):
    """
    Filters 'file_paths' to only containing certain name format
    based on file extension.
    NOTE: file paths from archives created on windows will use backslash
            as the final path separator if read on linux. These are not
            altered at this point.
    """
    
    file_paths = get_file_paths(archive_obj)
    filtered_paths = []
    for file_path in file_paths:
        try:
            # note that the extension includes '.'
            #file_ext = re.search(r'(\.\w+)$', file_path).group(1)
            file_ext = os.path.splitext(file_path)[1]
            if file_ext == '.db': continue                              # sometimes "Thumbs.db" are included.
            
            # the following attempts to read the file.
            filtered_path = re.search(
                BALLOT_FORMAT[file_ext]['name_reg'], file_path)
        except (AttributeError, KeyError) as error:
            print(f"Couldn't parse the file path:{file_path} error:{error}")
            continue
        if filtered_path:
            filtered_paths.append(file_path)
    return filtered_paths


def get_archived_file(archive, file_name=None):
    """ Returns dictionary of 'file_name' from archive
        NOTE: This may alter the final path separator if running on linux
                and archive was originally produced on windows.
    """
    try:
        result = {'name': file_name, 'bytes_array': archive.read(adjust_filepath_separators(archive, file_name))}
    except (OSError, KeyError):
        result = None
    return result

def get_archived_file_size(archive, file_name) -> int:
    """ return the size of the file without extracting it. """
    zipinfo = archive.getinfo(adjust_filepath_separators(archive, file_name))
    return zipinfo.file_size


def is_archived_file_BMD_type_ess(argsdict, archive, file_name) -> bool:
    """
    :param source_name: Name of the source with file. Used for lambdas S3 lookup.
    """
    if not argsdict.get('BMDs_exist', False):
        return False
    
    expressvote_ballot_threshold = int(argsdict.get('BMD_filesize_threshold', 0))
    if not expressvote_ballot_threshold:
        expressvote_ballot_threshold = int(config_dict['EXPRESSVOTE_BALLOT_FILESIZE_THRESHOLD'])
    """ typically expressvote BMD ballots are smaller than conventional ballots,
        about 16K while standard hand-marked paper ballots are larger, at least 34K.
        We can check before we remove from the archive. Note, this varies depending on the
        complexity of the ballot.
        
    """
    return get_archived_file_size(archive, file_name) < expressvote_ballot_threshold


def get_next_ballot_paths(index, archive, file_paths, extension=None):
    """
    given entire list of file_paths and index in archive,
    Returns a list of one or two filepaths that relate to a single ballot
    Most ballot types(.pdf, .png, .tif) have one file per both sides but
    .pbm has two filenames per ballot.

    """
    try:
        file_path = file_paths[index]
    except:
        pass
        
    # for most cases, there is only one file per ballot sheet. .pbm has two files per sheet.
    return_paths = [file_path]
    
    if extension is None:
        _, extension = os.path.splitext(file_path)      # note: extension includes '.'
 
        
    if extension == '.pbm':
        index += 1
        try:
            R_file_path = file_paths[index]
        except:    
            utils.exception_report(f"Warning: could not find rear file of .pbm file {file_path}, insufficient files.")
            return index-1, return_paths
            
        if file_path.endswith('F.pbm') and R_file_path.endswith('R.pbm'):
            _, _, ballotid = analyze_ballot_filepath(file_path)
            _, _, R_ballotid = analyze_ballot_filepath(R_file_path)
            if ballotid == R_ballotid:
                return_paths.append(R_file_path)
        else:
            utils.exception_report(f"Warning: could not find rear file of .pbm file {file_path}")
            return index-1, return_paths
            
    return index, return_paths


def get_ballot_images(index, archive, file_paths, extension=None):
    """
    Returns a list of images from a file, using a method specified
    file is indexed in file_paths
    in BALLOT_METHOD dictionary under 'extension' key.
    """
    file_path = file_paths[index]
    if extension is None:
        name, extension, ballotid = analyze_ballot_filepath(file_path)      # note: extension includes '.'
    ballot_file = get_archived_file(archive, file_path)

    images = BALLOT_FORMAT[extension]['get_images'](ballot_file)

    # Exception for .pbm two sided ballots divided to two files
    if extension == '.pbm':
        try:
            index += 1
            r_file_path = file_paths[index]
            if file_path.endswith('F.pbm') and r_file_path.endswith('R.pbm'):
                r_name, r_extension, r_ballotid = analyze_ballot_filepath(r_file_path)
                r_ballot_file = get_archived_file(archive, r_file_path)
                images.append(get_ballot_images(r_ballot_file, r_extension))
        except IndexError as error:
            logging.error("Couldn't find the rear page due to: %s", error)
            sys.exit(1)
    return index, images


def filter_paths_by_skip(argsdict, file_paths):
    """
    Returns a filtered list of file paths. The'skip' parameter can be a number
    of elements to skip from the start of the list or a precinct against which
    the list should be filtered. Any other precincts after the precinct in
    'skip' will be returned also.
    """

    def is_int(text):
        try:
            return isinstance(text, int)
        except ValueError:
            return False

    skip = argsdict.get('skip')
    if skip is None or skip == 0 or skip == '0':
        return file_paths
    if is_int(skip):
        skip = int(skip)
        list_len = len(file_paths)
        diff = skip - list_len
        file_paths = file_paths[skip - config_dict['SKIPPED_NUM']:]
        if config_dict['SKIPPED_NUM'] < skip:
            config_dict['SKIPPED_NUM'] += list_len if diff >= 0 \
                else skip - config_dict['SKIPPED_NUM']
        if config_dict['SKIPPED_NUM'] > skip:
            config_dict['SKIPPED_NUM'] = skip
    else:
        print("Skip argument is not an integer.\nFiltering file names list...")
        i = 0
        for file_path in file_paths:
            if skip not in file_path:
                i += 1
            else:
                break
        file_paths = file_paths[i:]
    print(f"Filtered {len(file_paths)} file(s) from the list.")
    return file_paths


def filter_paths_by_precinct(argsdict, file_paths):
    """
    Return filtered list of file paths.
    'precincts' parameter should be a list of precincts to which
    list should be filtered.
    """
    precincts = argsdict.get('precinct')
    if precincts is None or precincts == []:
        return file_paths

    if not isinstance(precincts, list):
        precincts = [precincts]
    utils.sts("Filtering file names list by specified precincts...", 3)
    selected_file_paths = []
    for file_path in file_paths:
        precinct_of_file = get_precinct(argsdict, file_path)
        if precinct_of_file in precincts:
            selected_file_paths.append(file_path)
    utils.sts(f"Selected {len(selected_file_paths)} file(s) from the list.", 3)
    return selected_file_paths


def null_function(parameter):
    return parameter


def filter_ballotids(argsdict, proposed_ballot_id_list, silent=False):
    """
    Return filtered list of ballotids.
    argsdict['ballotid'] - list of ballot_ids which will be included.
    If empty, do not filter.
    """
    return filter_proposed_list_by_ballotid(argsdict, proposed_ballot_id_list, null_function, silent)


def filter_paths_by_ballotid(argsdict, file_paths, silent=False):
    """
    Return filtered list of file paths.
    argsdict['ballotid'] - list of ballot_ids which will be included.
    If empty, do not filter.
    """
    return filter_proposed_list_by_ballotid(argsdict, file_paths, get_ballotid, silent)


def filter_mark_df_paths_by_ballotid(argsdict, file_paths, silent=False):
    """
    Return filtered list of file paths.
    argsdict['ballotid'] - list of ballot_ids which will be included.
    If empty, do not filter.
    """
    return filter_proposed_list_by_ballotid(argsdict, file_paths, get_ballotid_of_marks_df, silent)


def filter_proposed_list_by_ballotid(argsdict, proposed_list, get_ballot_id_function, silent):
    """
    Return filtered list of proposed_list.
    argsdict['ballotid'] - list of ballot_ids which will be included.
    If empty, do not filter.
    get_ballot_id_function - this function is used to extract the ballot_id from one entry in the proposed_list
    """
    include_ballotids = argsdict.get('ballotid', [])
    if not isinstance(include_ballotids, list):
        include_ballotids = [include_ballotids]

    exclude_ballotids = argsdict.get('exclude_ballotid', [])
    if not isinstance(exclude_ballotids, list):
        exclude_ballotids = [exclude_ballotids]

    if (not include_ballotids or not len(include_ballotids)) and \
            (not exclude_ballotids or not len(exclude_ballotids)):
        return proposed_list

    utils.sts("Filtering list by specified ballotids...", 3)
    selected_items = []
    for item in proposed_list:
        ballotid_of_item = int(get_ballot_id_function(item))
        if include_ballotids:
            # include_ballotids specification overrides exclusion.
            if ballotid_of_item in include_ballotids:
                selected_items.append(item)
        elif exclude_ballotids:
            if not ballotid_of_item in exclude_ballotids:
                selected_items.append(item)
        else:
            selected_items = proposed_list
            break

    utils.sts(f"Selected {len(selected_items)} item(s) from the list.", 3)
    return selected_items


def filter_paths_by_limit(argsdict, file_paths):
    """
    Return filtered list of file paths.
    'precincts' parameter should be a list of precincts to which
    list should be filtered.
    """
    config_dict['LIMITED_NUM'] = 0
    files_limit = argsdict.get('limit')
    if files_limit is not None and files_limit >= config_dict['LIMITED_NUM']:
        list_len = len(file_paths)
        diff = files_limit - list_len
        file_paths = file_paths[:(files_limit - config_dict['LIMITED_NUM'])]
        if config_dict['LIMITED_NUM'] < files_limit:
            config_dict['LIMITED_NUM'] += list_len if diff >= 0 else files_limit - config_dict['LIMITED_NUM']
        if config_dict['LIMITED_NUM'] > files_limit:
            config_dict['LIMITED_NUM'] = files_limit
    return file_paths


def filter_image_file_paths(argsdict, file_paths):
    """
    argsdict: arguments as provided from CLI and input file.
    file_paths: file paths from archive already filtered to image files.
    
    filters list based on precinct, skip, and limit
    returns file_paths
    """

    file_paths = filter_paths_by_precinct(argsdict, file_paths)
    file_paths = filter_paths_by_ballotid(argsdict, file_paths)
    file_paths = filter_paths_by_skip(argsdict, file_paths)
    file_paths = filter_paths_by_limit(argsdict, file_paths)
    return file_paths


file_paths_cache = {}
archives = []


def copy_ballot_pdfs_to_report_folder(argsdict, ballot_id_list, dirname):
    utils.sts(f"Copying {len(ballot_id_list)} ballot image files classified as {dirname}", 3)
    if not len(ballot_id_list): return

    target_folder = DB.dirpath_from_dirname(dirname)
    mutated_ballot_id_list = ballot_id_list.copy()

    # first create the list of all the archive paths in this archive that are in ballot_id_list
    # and open the archives and leave them open during processing.
    if not file_paths_cache:
        for archive_idx, archive_path in enumerate(argsdict['source']):
            archive = open_archive(argsdict, archive_path)
            archives.append(archive)
            file_paths_list = get_image_file_paths_from_archive(archive)
            file_paths_cache[archive_idx] = file_paths_list

    while mutated_ballot_id_list:
        ballot_id = mutated_ballot_id_list.pop(0)
        target_filename = f"{ballot_id}i.pdf"
        for archive_idx in range(len(archives)):
            ballot_paths = [x for x in file_paths_cache[archive_idx] if re.search(r'[\\/]' + target_filename, x)]
            if len(ballot_paths):
                utils.sts(f"Extracting {ballot_paths[0]} from archive {archive_idx}", 3)
                archives[archive_idx].extract(ballot_paths[0], path=target_folder)
                break
        else:
            mbidl = ', '.join(mutated_ballot_id_list)
            utils.sts(f"Logic error: Failed to find some ballot_ids in ballot archives: {mbidl}", 0)
            traceback.print_stack()
            sys.exit(1)


def copy_ballot_pdfs_from_archive_to_report_folder(archive, filepaths, ballot_id, dirname):
    target_filename = f"{ballot_id}i.pdf"
    target_folder = DB.dirpath_from_dirname(dirname)
    ballot_paths = [x for x in filepaths if re.search(r'[\\/]' + target_filename, x)]
    if len(ballot_paths):
        utils.sts(f"Extracting {ballot_paths[0]} from archive", 3)
        archive.extract(ballot_paths[0], path=target_folder)
        return

    utils.sts(f"Logic error: Failed to find ballot_id {ballot_id} in ballot archive.", 0)
    traceback.print_stack()
    sys.exit(1)


def extract_file(archive, file_name, dest_filepath):
    """ given zip archive which is already open, extract a single file 'file_name' and write it to dest filepath.
        Note that zipfile.extract() does not work because it always reproduces the entire path.
    """
    
    newfilebytes = bytes(archive.read(adjust_filepath_separators(archive, file_name)))
    fh = open(dest_filepath, "wb")
    fh.write(newfilebytes)
    fh.close()

