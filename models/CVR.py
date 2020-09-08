import re
import os
import sys
import json
import datetime
import collections
from zipfile import ZipFile
import xml.dom.minidom

import numpy as np
import pandas as pd

from utilities import utils, logs
from utilities.config_d import config_dict
from utilities import style_utils

from models.DB import DB


class CVR:
    """
    Contains variables and methods related to CVR. Class variable holds
    Pandas data frame build from excel file. Class methods help with
    reading CVR excel file, renaming unnamed columns and returning
    contest results.
    """
    data_frame = pd.DataFrame()
    master_styles_dict = {}
    cvr_ballotid_to_styles_dict = {}

    @staticmethod
    def load_excel_to_df(argsdict: dict, filename_list: list, column_names_list: list):
        """
        Reads a CVR excel file and saves it as a pandas data frame.
        Combines multiple CVR files and assumes columns are identical.
        Renames unnamed columns by duplicating last column name.
        This is specific to ES&S cvr files.
        """
        for idx, file_name in enumerate(filename_list):
            utils.sts(f"Reading cvr file {file_name}...")
            if not idx:
                #CVR.data_frame = pd.read_excel(file, engine='xlrd')
                CVR.data_frame = DB.load_data(dirname='archives', name=file_name, user_format=True)
            else:
                # df = pd.read_excel(file, engine='xlrd')
                df = DB.load_data(dirname='archives', name=file_name, user_format=True)
                CVR.data_frame = CVR.data_frame.append(df, ignore_index=True)

        if argsdict.get('convert_cvr_image_cells_to_writein', False):
            CVR.set_cells_with_images_to_writeins(argsdict['cvr'])

        if column_names_list:
            utils.sts("replacing column names with replacement column names provided.")
            # use the replacement column headers instead of those provided.
            orig_col_names = CVR.data_frame.columns
            if not len(orig_col_names) == len(column_names_list):
                utils.sts("replacement column headers not right length to replace header names in CVR")
                sys.exit(1)
            # we will replace any "blank" col names with "Unnamed: XXX" so we can remove them later.
            for i, orig_col_name in enumerate(orig_col_names):
                if re.match(r'Unnamed:', orig_col_name):
                    column_names_list[i] = orig_col_name
            CVR.data_frame.columns = column_names_list

        utils.sts("Checking for duplicate column names.")
        # at this point, there should be no duplicate column names.
        column_name_set = len(set(CVR.data_frame.columns))
        column_name_list = len(list(CVR.data_frame.columns))
        if not column_name_set == column_name_list:
            utils.sts("Column Names are duplicated")
            sys.exit(1)

        utils.sts("Replacing columns with 'Unnamed' with prior named column name.")
        CVR.data_frame.columns = CVR.rename_unnamed(list(CVR.data_frame.columns))

    @staticmethod
    def set_cells_with_images_to_writeins(file_paths):
        """Reads CVR spreadsheet as a ZIP and extracts information from
        the .xml file about the cells that have images in them.
        Then sets null cells in CVR data frame to write-in, if the cell
        has an image within.
        :param file_path: Path to the CVR file.
        @TODO: Need to fix for s3 operation.
                probably first download the file and then perform the work.
        """
        dirpath = DB.dirpath_from_dirname('archives')
        if dirpath.startswith('s3'):
            utils.sts("Cannot convert images to writeins on s3")
            sys.exit(1)
        
        
        if isinstance(file_paths, str):
            file_paths = [file_paths]
        for file_path in file_paths:
            archive = ZipFile(file_path, 'r')
            xml_path = 'xl/drawings/drawing1.xml'
            try:
                xml_file = archive.read(xml_path)
            except KeyError:
                utils.sts(f'Couldn\'t find {xml_path} in {file_path}')
                break
            doc = xml.dom.minidom.parseString(xml_file.decode())
            for cellAnchorElement in doc.getElementsByTagName('xdr:twoCellAnchor'):
                fromElement = cellAnchorElement.getElementsByTagName('xdr:from')[0]
                row = fromElement.getElementsByTagName('xdr:row')[0].firstChild.data
                col = fromElement.getElementsByTagName('xdr:col')[0].firstChild.data
                CVR.data_frame.iat[int(row) - 1, int(col)] = 'write-in:'

    @staticmethod
    def load_cvrs_to_df(argsdict):
        cvr_replacement_header_list = ''
        if not argsdict['use_cvr_columns_without_replacement']:
            # this reads the EIF for the replacement
            cvr_replacement_header_list = style_utils.get_replacement_cvr_header(argsdict)
        CVR.load_excel_to_df(argsdict, argsdict['cvr'], cvr_replacement_header_list)

    @staticmethod
    def drop_unused_columns(dataframe):
        return dataframe.drop(['Cast Vote Record', 'Precinct'], axis=1)

    @staticmethod
    def get_all_contests(dataframe) -> list:
        """
        Creates a list of all contests names for a given CVR.
        """
        return [contest for contest in dataframe.columns if contest != 'Ballot Style']

    @staticmethod
    def get_contests_per_style(contests: list, dataframe, ballot_styles) -> dict:
        """
        Builds a dictionary of contests per ballot style. For example,
        {"Ballot Style 204": ["Justice of the Supreme Court".. ]
        :param contests: all columns with contest names
        :param dataframe: a pandas data frame with CVR
        :param ballot_styles: a pandas object with all ballot styles

        """
        contests_per_style = collections.OrderedDict()
        for ballot_style in ballot_styles:
            df = dataframe[dataframe['Ballot Style'] == ballot_style]
            contests_per_style[ballot_style] = CVR.get_value_only_contests(contests, df)
        return contests_per_style

    @staticmethod
    def get_value_only_contests(contests: list, ballot_style_df) -> list:
        """
        Builds a list of contests with at least a value (option)
        :param contests: all columns with contest names
        :param ballot_style_df: filtered CVR dataframe that returns contests
        only for a given ballot style
        """
        return [contest for contest in contests if len(set(ballot_style_df[contest].dropna())) != 0]

    @staticmethod
    def get_cvr_names(contest_name, df):
        ignored = ['undervote', 'overvote']
        cvr_names = []
        for option in set(df[contest_name].dropna()):
            if option not in ignored:
                cvr_names.append(option)
        return cvr_names

    @staticmethod
    def get_contest_option_items(contest: list, df) -> dict:
        """
        Builds a dictionary with a contest per unique ballot style as a key
        and contest options as unique values.
        :param contest: a single contest per unique ballot style
        :param df: filtered CVR dataframe that returns all options for
        a give ballot style and contest
        """
        new_key_pattern = re.compile(r'\.\d')  # RCL says: I don't know why .n is removed.
        styles_json = {
            re.sub(new_key_pattern, '', contest_name): {
                'position': None,
                'shape': None,
                'ocr_name': None,
                'cvr_name': re.sub(new_key_pattern, '', contest_name),
                'official_name': None,
                'ballot_name': None,
                'express_vote_name': None,
                'vote_for': None,
                'on_page': None,
                'description': None,
                'options': [{
                    'position': None,
                    'shape': None,
                    'ocr_name': None,
                    'cvr_name': cvr_name,
                    'official_name': None,
                    'ballot_name': None,
                    'express_vote_name': None,
                    'on_page': None,
                    'mark_contours': [],
                } for cvr_name in CVR.get_cvr_names(contest_name, df)]
            } for contest_name in CVR.merge_unnamed(contest)
        }
        return styles_json

    @staticmethod
    def build_style_dict(options_per_style: dict, dataframe) -> dict:
        """
        Creates a nested dictionary with the ballot style number as a key
        and contest names as keys of the inner dictionary that holds all
        options as values.
        :param options_per_style: a dictionary with all options per given
        ballot style
        :param dataframe: a CVR data frame that's used to build the dict
        """
        result = collections.OrderedDict()
        for ballot_style, contest in options_per_style.items():
            # e.g. Ballot Style 204 -> 204
            key = ballot_style.rpartition(" ")[-1]
            result[key] = CVR.get_contest_option_items(contest, dataframe)
        return result

    @staticmethod
    def merge_unnamed(contests_with_options: list):
        pattern = re.compile(r'^Unnamed:\s\d+$').match
        return list(CVR.filter_unnamed(contests_with_options, pattern))

    @staticmethod
    def make_dir() -> object:
        """
        Creates a folder where the results are saved.
        :return: a folder called 'style_dict'
        """
        return os.makedirs(os.path.join(config_dict['STYLE_DICT']), exist_ok=True)

    @staticmethod
    def write_style_dict_to_json(data, tag):
        """
        Saves the dictionary of styles to a JSON file.
        :param data: style dict or ballotid to style dict.
        :param tag: filename decoration to distinguish the files
        """
        CVR.make_dir()
        file_path = f"{config_dict['STYLE_DICT']}{tag}.json"
        with open(file_path, 'w') as jf:
            jf.write(json.dumps(data))

    @staticmethod
    def read_style_dict_from_json(tag) -> dict:
        """
        Reads the dictionary of styles to a JSON file.
        :param tag: filename decoration to distinguish the files
        """
        CVR.make_dir()
        file_path = f"{config_dict['STYLE_DICT']}{tag}.json"
        try:
            with open(file_path, 'r') as jf:
                return json.load(jf)
        except FileNotFoundError:
            utils.sts(f"Style Dict JSON file '{tag}' not found", 3)
            return None

    @staticmethod
    def cvr_to_styles_dict(cvr_data) -> dict:
        """
        A driver method that encapsulates the entire logic for parsing a CVR
        file to a JSON style dictionary.
        :param cvr_data: a parsed Excel file to a pandas data frame
        style_dict {style_name : [list of contests]}
        """
        start = datetime.datetime.utcnow()
        utils.sts("Searhing CVR chunk for styles...", 3)

        # convert 'Ballot Style NNN' to 'NNN' (must be a string for use as key in JSON)
        cvr_data['Ballot Style'] = cvr_data['Ballot Style'].apply(lambda x: re.sub(r'^\D+', '', x))
        CVR.filtered_data = CVR.drop_unused_columns(cvr_data)
        CVR.unique_ballot_styles = CVR.filtered_data['Ballot Style'].unique()
        CVR.contests = CVR.get_all_contests(CVR.filtered_data)

        utils.sts(f"Found {len(CVR.unique_ballot_styles)} unique style(s).\nMapping Contests per style...", 3)

        style_dict = CVR.get_contests_per_style(
            CVR.contests,
            CVR.filtered_data,
            CVR.unique_ballot_styles,
        )

        end = datetime.datetime.utcnow()
        time_taken = utils.show_time((end - start).total_seconds())
        utils.sts(f"Processed {len(CVR.filtered_data)} rows in {time_taken}", 3)

        return style_dict

    @staticmethod
    def value_or_previous(iterator: list, regex_match, default=None):
        """
        A generator that produces either a current column name or
        a swapped name based on a passed regex match pattern. This
        method is used in conjunction with rename_unnamed()
        """
        previous_item = default
        for item in iterator:
            if not regex_match(item):
                previous_item = item
            yield previous_item

    @staticmethod
    def filter_unnamed(iterator, regex_patter):
        """
        A generator that yields unnamed columns that are used for
        merging values from contest options.
        """
        for item in iterator:
            if regex_patter(item):
                continue
            yield item

    @staticmethod
    def rename_unnamed(columns):
        """
        Takes a list of column names and iterates through them, changing
        'Unnamed' columns to the last valid header. For example:
        Input:
        ['Constable T Rutland', 'Unnamed: 245', 'Town Board Chairperson']
        Output:
        ['Constable T Rutland', 'Constable T Rutland','Town Board Chairperson']
        """
        pattern = re.compile(r'^Unnamed:\s\d+$').match
        return list(CVR.value_or_previous(columns, pattern))

    @staticmethod
    def get_cvr_contest_results(ballot_number, contest):
        """
        Returns a tuple: a list of results for specific contest (string)
        of selected ballot number (int) and length of columns found
        under passed contest.
        """
        row = CVR.data_frame.loc[CVR.data_frame['Cast Vote Record'] == int(ballot_number)]
        if row.empty:
            return [], 0

        row = row.replace(r'^\s*$', np.nan, regex=True)
        row = row.dropna(axis='columns', how='all')

        if not contest or contest not in list(row.columns):
            return [], 0

        count = len(list(row[contest]))
        result = list(row[contest]) if isinstance(row[contest].iloc[0], str) else list(row[contest].iloc[0])
        return result, count

    @staticmethod
    def lookup_ballot_dol(argsdict: dict, ballot_id: str, custom_cvr: pd.DataFrame = pd.DataFrame()) -> dict:
        """
        Look up a given ballot and return a dict with contest as the key, 
        and list of voted selections for that contest. CVR.data_frame must be loaded for all ballot_ids
        selection list may contain 'overvote' or 'undervote'
        """
        if not custom_cvr.empty:
            row = custom_cvr.loc[custom_cvr['Cast Vote Record'] == int(ballot_id)]
        else:
            row = CVR.data_frame.loc[CVR.data_frame['Cast Vote Record'] == int(ballot_id)]
        if row.empty:
            # ballot not found in CVR!
            return None

        # remove all columns that do not apply to this ballot_id
        row = row.replace(r'^\s*$', np.nan, regex=True)
        row = row.dropna(axis='columns', how='all')

        contests = list(row.columns)
        id_col_num = len(argsdict['initial_cvr_cols'])
        contestset = set(contests[id_col_num:])
        ballot_dol = dict.fromkeys(contestset)
        for contest in ballot_dol:
            is_text = isinstance(row[contest].iloc[0], str)
            ballot_dol[contest] = list(row[contest]) if is_text else list(row[contest].iloc[0])
        return ballot_dol
