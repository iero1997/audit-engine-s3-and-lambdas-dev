import re
#import os
#import posixpath
import sys
#import ntpath
import collections

#from io import BytesIO #, StringIO

#import boto3
import pandas as pd

from utilities import utils, logs
from models.DB import DB
#from aws_lambda.core import check_if_exists
#from utilities import config_d
#from aws_lambda import s3utils
#from models.Job import Job
#from botocore.exceptions import ClientError

EIF_COLS = [
    'official_contest_name',    # (REQ) these column names will be used instead of the columns provided in the CVR. This field must have a value
                                #       The first few fields are provided if they match the CVR file, as follows
                                #       Cast Vote Record, Precinct, Ballot Style
    'in_group',                 # (OPT) integers that define groups where if one contest (or ex_group) is included, all are included.
    'ex_group',                 # (OPT) integers taht define groups where only one contest in the group may be included.    
    'id',                       # (OPT) internally defined integer key
    'sheet',                    # (OPT) if ballot has multiple sheets, the sheet where this contest is found, if included. this is one-based sheet (sheet1)
    'party',                    # (OPT) for partisan elections, the 2-3 character party designator, DEM, REP, AI, PF, GRN, LIB.    
    'original_cvr_header',      # (OPT) these are the column names provided in the original CVR in the exact order.
                                #       this list is for reference as this table is built.
                                #       not used if CVR is not in table format
    'ballot_contest_name',      # (REQ) this is the exact text as provided on the ballot for the contest name
                                #       including embedded newlines. The column is required, but if field is empty, no contest name header exists.
    'contest_num',              # (OPT) number of contest lines of text in contest header. 
                                #       If not provided, det. by counting lines in 'ballot_contest_name'
                                #       This field only required separately if not all lines are included in 'ballot_contest_name',
                                #       which may be the case in the case of bilingual ballots, so that not all lines will be compared.
                                #       Do not count blank lines
    'bmd_contest_name',         # (OPT) contest names as found on BMD ballots.
    'vote_for',                 # (REQ) max number of votes in this contest, default 1
    'writein_num',              # (REQ) provided if the number is different from the vote_for.
                                #       some districts provide write-in lines only when there are official write-in candidate.
                                #       some provide a separate write-in line for each vote_for.
                                #       a entry of '0' means no write-ins. blank means same as vote-for
                                #       see also setting 'writein_str' which provides the standard string used to introduce this field
    'official_options',         # (REQ) list of candidates or yes/no options, not necessarily in the order on the ballot.
                                #       ballot options will be looked up from a separate file because each ballot option may comprise several lines.
                                #       if no additional ballot_options.xlsx file is specified, then the official options are used.
    'description',              # (REQ) for question type contests, this field provides the exact text
    'descr_num',                # (OPT) number of description lines of text in contest description. 
                                #       If not provided, det. by counting lines in 'description'
                                #       This field only required separately if not all lines are included in 'description'
                                #       which may be the case in the case of bilingual ballots, so that not all lines will be compared.
                                #       Do not count blank lines
    'qualified_writeins',       # (OPT) list of qualified writeins for this contest
]
EIF_REQUIRED_COLS = [           # if these cols do not exist, error occurs.
    'official_contest_name',    # note, this field requires a value
    'ballot_contest_name',
    'vote_for',
    'writein_num',
    'official_options',
    'description',
]

EIF_STRIP_COLS = [              # in these columns, leading and trailing spaces are stripped.
    'official_contest_name', 
    'original_cvr_header', 
    'ballot_contest_name', 
    'bmd_contest_name', 
    'official_options', 
    'description',
]



def load_eif(argsdict):
    """returns conversions for contest names.
    This function implements the new EIF format which provides the following columns:
    # columns are defined above. 
    """

    """=================================================================
    The EIF file is used as follows:
        replace cvr columns
            when the column 'original_cvr_header' exists, then it signals replacement of the original header.
                when the cvr is read, the columns are replaced by the 
                values in the 'official_contest_name' column.
                This column also includes the initial indexing column names, 
                Cast Vote Record, Precinct, and Ballot Style, if they exist in the CVR.
                after the columns are replaced, then the official_contest_names 
                are always used when data is accessed from any cvr file.
        ballot text lookup      
            when we are mapping contests and options to ROIs as extracted from the ballot,
            we need the actual text as provided on the ballot for the best matching success.
            for that purpose, the styledict provides the the contests 
            included. It must be built or provided using the official_contest_names.
            Then, we need to look up the ballot text from the EIF file, which has the following components:
                ballot_contest_name
                ballot_options
                description
                writein_num
            to create this lookup, the leading rows, containing any of: (Cast Vote Record, Precinct, Ballot Style)
            then the list is scanned and rows with duplicate official_contest_name contents are deleted.
            delete (or ignore) column 'original_cvr_columns'
            look up the (first) record matching the official contest name, return the 
            ballot_contest_name, [ballot_options], description, and writein_num.
                if the ballot_contest_name is blank, the official_contest_name is used.
                if the ballot_options columns is blank, the official options field is used.
                if the writein_num is blank, it defaults to the vote_for field, which defaults to 1.
                    If the writein_num is 0, it is not considered blank, and it returns 0.
                                        
    """
    utils.sts("Loading EIF...", 3)
    eif_filename = argsdict.get('eif')
    
    eif_df = DB.load_data(dirname='EIFs', name=eif_filename, user_format=True)
       
    eif_df = check_table(eif_df, table_name=eif_filename, required_columns_list = EIF_REQUIRED_COLS, strip_cols=EIF_STRIP_COLS)
    
    if 'original_cvr_header' in list(eif_df.columns):
        # not needed to check this if there is no original CVR header.
        cvr_replacement_header_list = eif_df['official_contest_name'].tolist()
        expected_initial_cvr_cols = argsdict.get('initial_cvr_cols', ['Cast Vote Record', 'Precinct', 'Ballot Style'])
        if not expected_initial_cvr_cols == cvr_replacement_header_list[0:len(expected_initial_cvr_cols)]:
            utils.sts(f"ERROR: EIF list of initial_cvr_cols does not match input file setting {','.join(expected_initial_cvr_cols)}", 0)
            sys.exit(1)

        # drop the first few rows of the dataframe, we don't need these extra CVR fields.
        contest_lookup_df = eif_df.iloc[len(expected_initial_cvr_cols):]
    else:
        contest_lookup_df = eif_df
        
    # eliminate all the duplicates which occur when vote_for > 1
    contest_lookup_df = contest_lookup_df.drop_duplicates('official_contest_name', keep='first')
    utils.sts("EIF loaded OK.", 3)
    return contest_lookup_df


def get_replacement_cvr_header(argsdict: dict) -> list:
    """
    :param args_dict: Dict of arguments passed on script input.
    """
    utils.sts("Loading EIF...", 3)
    
    eif_filename = argsdict.get('eif')
    
    eif_df = DB.load_data(dirname='EIFs', name=eif_filename, user_format=True)

    eif_df = check_table(eif_df, table_name=eif_filename, required_columns_list = EIF_REQUIRED_COLS, strip_cols=EIF_STRIP_COLS)

    cvr_replacement_header_list = list(eif_df['official_contest_name'])
    expected_initial_cvr_cols = argsdict.get('initial_cvr_cols',
                                              ['Cast Vote Record', 'Precinct', 'Ballot Style'])
    if not all(item in cvr_replacement_header_list for item in expected_initial_cvr_cols):
        expected_cols = ','.join(expected_initial_cvr_cols)
        utils.sts(f"ERROR: CVR does not have the expected fields in the header {expected_cols}", 0)
        sys.exit(1)
    return cvr_replacement_header_list
    
def check_table(
        table_df: pd.DataFrame,
        table_name: str,
        required_columns_list: list = [],
        check_dups: bool = True,
        #silent_error: bool = False,
        strip_cols: list = []
) -> pd.DataFrame:
    """ This function handles general opening of xls file and convertion to data frame.
        Please note that this function is not appropriate for very large tables, like the CVR file.
        If expected_column_header is provided, then the actual columns found must
            match those but may have more columns.
        if table_path starts with 's3://' then the file is read from s3 path
            
    :param table_df: DataFrame
    :param required_columns_list: List of headers to which headers from xls
    file must match.
    :param check_dups: Flag saying if duplicated columns should be removed.
    :param silent_error: Flag saying if exceptions should not return a message.
    :param strip_cols: list of columns to be stripped of leading and trailing spaces.
    :return: DataFrame.
    """
    utils.sts("Checking table...", 3)
    # if not table_path:
        # if silent_error:
            # return None
        # utils.sts(f"ERROR: Required File not specified: {table_path}", 0)
        # sys.exit(1)
        
    # _, ext = os.path.splitext(table_path)
    # ext = ext.lower()
    # if not ext in ['.xlsx', '.csv']:
        # if silent_error:
            # return None
        # utils.sts(f"ERROR: EIF extension '{ext}' not supported in path {table_path}", 0)
        # sys.exit(1)

    # if table_path.startswith('s3://'):
        # s3_IO_obj = s3utils.get_s3path_IO_object(table_path)
        
        # if ext == '.xlsx':
            # df = pd.read_excel(s3_IO_obj, comment='#', engine='xlrd')
        # else:
            # df = pd.read_csv(s3_IO_obj, sep=',', comment='#', skip_blank_lines=True)
    # else:
        # try:
            # if ext == '.xlsx': 
                # df = pd.read_excel(table_path, comment='#', engine='xlrd')
            # elif ext == '.csv':
                # df = pd.read_csv(table_path, sep=',', comment='#', skip_blank_lines=True)
        # except (FileNotFoundError, ValueError) as error:
            # if silent_error:
                # return None
            # utils.sts(error, 3)
            # sys.exit(1)
    # df.fillna(value='', inplace=True)
    sanitize_headers(table_df)
    
    
    if not required_fields_exist(required_field_list=required_columns_list, actual_field_list=list(table_df.columns)):
    #if expected_columns_list and not all(item in required_columns_list for item in list(table_df.columns)):
        utils.sts(f"ERROR: table columns differ from the expected headers in {table_name}\n"
            f"Required header fields: {', '.join(required_columns_list)}\n"
            f"Header fields as read: {', '.join(list(table_df.columns))}\n"
            "Additional header fields are allowed. Check the file format.", 0)
        sys.exit(1)
        
    if check_dups:
        dups = utils.find_duplicates(list(table_df.columns))
        if dups:
            duplicates = '\n'.join(dups)
            utils.sts(f"Duplicate Columns Detected in {table_name}. "
                       f"Table column names should be unique.\n{duplicates}")
    for col in strip_cols:
        if col in list(table_df.columns):
            table_df[col] = table_df[col].str.strip()
    
    utils.sts(f"Loaded table OK, {len(table_df.index)} records and {len(list(table_df.columns))} columns", 3)
    return table_df

def sanitize_headers(data_frame):
    """Sanitizes headers of the 'data_frame'.
    :param data_frame: Pandas data frame to get sanitized headers from.
    """
    data_frame.columns = data_frame.columns.str.strip().str.replace(' ', '_').str.replace(r'_{2,}', '_')
    
    
def required_fields_exist(required_field_list: list, actual_field_list: list):
    """ check that all fields in required_field_list exist in the actual_field_list """
    if not required_field_list: return True
    
    for item in required_field_list:
        if not item in actual_field_list: return False
    return True

def create_contests_dod(argsdict) -> dict:  # ordered dict of dict (dod)
    """
    create the contests_dod (ordered dict of dict) which provides information about all contests
    This information is derived from the EIF and BOF.
    contests_dod has the following shape:
    {   official_contest_name : contest_dict }
    
    and each contest_dict has:
    {   official_contest_name:  str,
        ballot_contest_name:    str,
        bmd_contest_name:       str,
        contest_name_num:       int, 0 if there is no contest name, else number of rois
        official_options_list:  csv [ordered list of str] -- if 'no candidate' exists then it is empty.
        ballot_options_list:    csv [ordered list of str]
        writein_num:            int, number of write-in lines on the ballot for this contest
        ballot_descr:           str,
        vote_for:               int, defaults to 1
        descr_num:              int, 0 if there is no descr, else number of rois
        min_rois_num:           int,
    }
    This structure does NOT provide information about styles.
    contests_dod provides dict of information for each contest.
    
    contests_dod.keys() will provide the list of all contest names in their proper order.
    
    """
    eif_df = load_eif(argsdict)
    eif_columns = list(eif_df.columns)
    #import pdb; pdb.set_trace()
    bof_df = load_bof_df(argsdict)
    # this is the list of all contests (not the replacement list)
    official_contest_names_list = eif_df['official_contest_name'].tolist()

    contests_dod = collections.OrderedDict()

    for contest_str in official_contest_names_list:
        #if contest_str == 'Waunakee School Board Member Village of Waunakee (2)':
        #    import pdb; pdb.set_trace()
        # look up this contest_name
        contest_dict = {}
        eif_contest_dict = dict_of_df_record(eif_df, 'official_contest_name', contest_str, dfname='EIF')
        contest_dict['contest_str']             = contest_str

        # need to handle the description first
        contest_dict['ballot_descr']            = eif_contest_dict['description']
        contest_dict['descr_num']               = count_lines(contest_dict['ballot_descr'])
        if 'descr_num' in eif_columns:
            contest_dict['descr_num']           = utils.set_default_int(eif_contest_dict['descr_num'], contest_dict['descr_num'])
        
        contest_dict['ballot_contest_name']     = eif_contest_dict['ballot_contest_name'].strip()
        contest_dict['contest_name_num']        = count_lines(contest_dict['ballot_contest_name'])
        if 'contest_name_num' in eif_columns:
            contest_dict['contest_name_num']    = utils.set_default_int(eif_contest_dict['contest_name_num'], contest_dict['contest_name_num'])
        if argsdict.get('question_contests_have_no_contest_name') and contest_dict['descr_num']:
            # If question contests are fully_joined, the contest name can be included in the description.
            contest_dict['contest_name_num'] = 0
        
        contest_name = contest_dict['ballot_contest_name']
        contest_name = contest_name.replace("\n", " ")
        contest_name = re.sub(r'\s+', ' ', contest_name)      # remove double+ spaces
        contest_dict['ballot_contest_name'] = contest_name
        
        contest_dict['bmd_contest_name']        = eif_contest_dict['bmd_contest_name'].strip()
        contest_dict['official_options_list']   = strip_list(eif_contest_dict['official_options'].split(','))
        try:
            pattern_found = bool(re.search('no candidate', contest_dict['official_options_list'][0], flags=re.I))
        except IndexError:
            continue
        if contest_dict['official_options_list'] and pattern_found:
            contest_dict['official_options_list'] = []

        # write-in defaults to 1, except when a description is provided, then 0
        writein_num = utils.set_default_int(eif_contest_dict['writein_num'], 1)
        if contest_dict['ballot_descr']:
            writein_num = 0
        contest_dict['writein_num'] = writein_num
        contest_dict['writein_options_list']    = []
        for writein_idx in range(writein_num):
            contest_dict['writein_options_list'].append('writein_' + f'{writein_idx}')

        # ballot options default to official options unless we have BOF information
        # and that will override only those official options when specified.
        contest_dict['ballot_options_list']     = ballot_options_from_bof(bof_df, contest_str,
                                                                      contest_dict['official_options_list'])
        contest_dict['option_num']              = int(len(contest_dict['official_options_list']))
        contest_dict['vote_for']                = utils.set_default_int(eif_contest_dict.get('vote_for', 1), 1)

        contest_dict['sheet0']                  = (eif_contest_dict.get('sheet', 1) - 1)
        
        contest_dict['min_rois_num']            = contest_dict['contest_name_num'] \
                                                + contest_dict['descr_num'] \
                                                + contest_dict['writein_num'] \
                                                + contest_dict['option_num']
        
        contests_dod[contest_str] = contest_dict
        
    return contests_dod
    
def count_lines(s_str: str) -> int:
    if not s_str or not len(str(s_str)):
        return 0
    num_newlines = s_str.count('\n')
    return num_newlines + 1
 
def load_bof_df(argsdict):
    """returns conversions for ballot options.
    This function implements the Ballot Options File (BOF)
    """
    bof_columns = ['official_contest_name',
                   # official contest name used as a means to look up the ballot option.
                   'official_option',
                   # one option per record used as a second index to look up the ballot option
                   'ballot_option',
                   # ballot options as shown on the ballot, and only provided if the ballot
                   # option differs from the official option.
                   ]
    bof_filename = argsdict.get('bof')
    if not bof_filename:
        return None
        
    bof_df = DB.load_data(dirname='EIFs', name=bof_filename, silent_error=False, user_format=True)
    
    bof_df = check_table(bof_df, table_name=bof_filename, required_columns_list=bof_columns, strip_cols=bof_columns)
    
    utils.sts(f"BOF {bof_filename} loaded.")
    return bof_df

def strip_list(str_list):
    """
    Remove leading and trailing spaces, and then remove list items that are ''
    """
    return [i.strip() for i in filter(None.__ne__, str_list) if len(i) > 0]



def strip_dict(d):
    """
    Remove leading and trailing spaces from all keys and items in dict that are strings.
    """
    return {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in d.items()}


def dict_of_df_record(df, key, val, dfname='Unnamed', silent_error=False):
    """ I don't think this is actually necessary because just reading the record creates a dict.
    """

    list_of_dict = df.to_dict(orient='records')
    for record in list_of_dict:
        record = strip_dict(record)
        if record[key] == val:
            return record
    if silent_error:
        return None
    utils.sts(f"Key error. Can't find record with {key} == '{val}' in dataframe {dfname}\n{df}", 0)
    sys.exit(1)


def dict_of_df_record2(df, key1, val1, key2, val2, dfname='Unnamed', silent_error=False):
    list_of_dict = df.to_dict(orient='records')
    for record in list_of_dict:
        record = strip_dict(record)
        if record[key1] == val1 and record[key2] == val2:
            return record
    if silent_error:
        return {}
    utils.sts(f"Key error. Can't find record with {key1} == {val1} and {key2} == {val2} in dataframe {dfname}", 0)
    sys.exit(1)

def ballot_options_from_bof(bof_df, official_contest_name, official_options_list):
    """ the BOF file provides details on ballot options if they differ substanitally from the official ballot options.
        columns:
            official_contest_name
            official_option
            ballot_option
    """
    if bof_df is None:
        return official_options_list
    
    ocn_df = bof_df.loc[bof_df['official_contest_name'] == official_contest_name]
    if ocn_df.empty:
        return official_options_list
    
    ballot_options = []
    for official_option in official_options_list:
        try:
            ballot_option = ocn_df.loc[bof_df['official_option'] == official_option]['ballot_option'].values[0]
        except IndexError or KeyError:
            ballot_options.append(official_option)
            continue

        ballot_options.append(ballot_option)
    return ballot_options



