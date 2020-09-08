#!/usr/bin/env python3.7
import re
import os
import json
import string
import argparse
import datetime
import collections

import openpyxl
import pandas as pd


STYLE_DICT = f'resources/style_dict/'

WARNING = string.Template("""
WARNING: Duplicated column values found!
CVR conversion of $FILE has been aborted.
""")
INSTRUCTIONS = string.Template("""
Use the COLUMN NAME to locate the duplicated column(s)
and change the COLUMN VALUE to a unique value. Then,
run the converter again.
-----------------------------------------------------------------------
""")


def drop_unused_columns(dataframe):
    return dataframe.drop(['Cast Vote Record', 'Precinct'], axis=1)


def get_all_contests(dataframe) -> list:
    """
    Creates a list of all contests names for a given.
    :param dataframe: a pandas data frame created from a CVR file
    """
    return [contest for contest in dataframe.columns
            if contest != 'Ballot Style']


def get_contests_per_style(contests: list, dataframe, ballot_styles) -> dict:
    """
    Builds a dictionary of contests per ballot style. For example,
    {"204": {"Justice of the Supreme Court"... }
    :param contests: all columns with contest names
    :param dataframe: a pandas data frame with CVR
    :param ballot_styles: a pandas object with all ballot styles
    """
    contests_per_style = collections.OrderedDict()
    for ballot_style in ballot_styles:
        df = dataframe[dataframe['Ballot Style'] == ballot_style]
        contests_per_style[ballot_style] = get_value_only_contests(contests, df)
    return contests_per_style


def get_value_only_contests(contests: list, ballot_style_df) -> list:
    """
    Builds a list of contests with at least a value (option)
    :param contests: all columns with contest names
    :param ballot_style_df: filtered CVR dataframe that returns
    contests only for a given ballot style
    """
    return [contest for contest in contests
            if len(set(ballot_style_df[contest].dropna())) != 0]


def get_cvr_names(contest_name: str, df) -> list:
    """
    Iterates through all options per given contests and retrieves
    unique values, skipping undervote & overvote
    :param contest_name: official contest name per unique Ballot Style
    :param df: a pandas dataframe to iterate over
    :return a list of all options per given contest per Ballot Style
    """
    ignored = ['undervote', 'overvote']
    return [option for option in set(df[contest_name].dropna())
            if option not in ignored]


def get_clean_key(contest_name: str) -> str:
    """
    If a contest name contains strings like 2.1 or 1.3, it'll remove the
    dot and whatever follows and creat a new key. This is used if there
    are duplicated columns in the pandas dataframe.
    :param contest_name: official contest name per unique Ballot Style
    :return a cleaned-up contest string that serves as a key
    """
    new_key_pattern = re.compile(r'\.\d')
    return re.sub(new_key_pattern, '', contest_name)


def get_contest_option_items(contest: list, df) -> dict:
    """
    Builds a dictionary with a contest per unique ballot style
    as a key and contest options as unique values.
    :param contest: a single contest per unique ballot style
    :param df: filtered CVR dataframe that returns all options for
    a give ballot style and contest
    :return a dictionary of styles
    """
    styles_json = {
        get_clean_key(contest_name): {
            'position': None,
            'shape': None,
            'ocr_name': None,
            'cvr_name': get_clean_key(contest_name),
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
            } for cvr_name in get_cvr_names(contest_name, df)]
        } for contest_name in merge_unnamed(contest)
    }
    return styles_json


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
        # e.g. Ballot Style 204 -> 204 both for Dane & Wakulla
        key = get_style_number(ballot_style)
        result[key] = get_contest_option_items(contest, dataframe)
    return result


def get_style_number(ballot_style: str) -> str:
    """
    Retrieves style number from its name.
    :param ballot_style: ballot style name e.g. Ballot Style 204
    :return a string of digits from the ballot style name
    """
    return ''.join(char for char in ballot_style.split() if char.isdigit())


def merge_unnamed(contests_with_options: list) -> list:
    """
    Filters out contests with the Unnamed XXX values.
    :param contests_with_options: a filtered list of contests that have
    any options
    :return a list of contests without the Unnamed XXX values
    """
    pattern = re.compile(r'^Unnamed:\s\d+$').match
    return list(filter_unnamed(contests_with_options, pattern))


def make_dir() -> object:
    """
    Creates a folder where the results are saved.
    :return: a folder called 'style_dict'
    """
    return os.makedirs(os.path.join(STYLE_DICT), exist_ok=True)


def write_to_json(data: dict):
    """
    Saves the dictionary of styles to a JSON file.
    :param data: a fully parsed CVR data frame
    """
    make_dir()
    file_path = f"{STYLE_DICT}CVR_STYLES.json"
    with open(file_path, 'w') as jf:
        jf.write(json.dumps(data))


def cvr_to_styles_dict(cvr_data):
    """
    A driver method that encapsulates the entire logic for parsing
    a CVR file to a JSON style dictionary.
    :param cvr_data: a parsed Excel file to a pandas data frame
    """
    start = datetime.datetime.utcnow()
    filtered_data = drop_unused_columns(cvr_data)
    unique_ballot_styles = filtered_data['Ballot Style'].unique()
    contests = get_all_contests(filtered_data)
    show_process_info(unique_ballot_styles, done=False)

    styles = get_contests_per_style(
        contests,
        filtered_data,
        unique_ballot_styles,
    )

    write_to_json(build_style_dict(styles, filtered_data))
    end = datetime.datetime.utcnow()
    time_taken = show_time((end - start).total_seconds())
    show_process_info(filtered_data, time_taken, done=True)


def rename_unnamed(columns):
    """
    Takes a list of column names and iterates through them, changing
    'Unnamed' columns to the last valid header. For example:
    Input:
    ['Constable T Rutland', 'Unnamed: 245', 'Town Board Chairperson']
    Output:
    ['Constable T Rutland', 'Constable T Rutland', ... ]
    """
    pattern = re.compile(r'^Unnamed:\s\d+$').match
    return list(value_or_previous(columns, pattern))


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


def filter_unnamed(iterator, regex_patter):
    """
    A generator that yields unnamed columns that are used for
    merging values from contest options.
    """
    for item in iterator:
        if regex_patter(item):
            continue
        yield item


def show_process_info(styles_or_rows, time_taken=None, done=False):
    """
    Displays CLI info while processing CVR files to JSON.
    :param styles_or_rows: takes an iterator of either a list of Ballot
    Styles or all rows in the CVR file
    :param time_taken: execution time
    :param done: a boolean switch for printing different messages
    """
    if done:
        print(f"Processed {len(styles_or_rows)} rows in {time_taken}")
    else:
        print(f"Found {len(styles_or_rows)} unique style(s).\nProcessing...")


def show_time(time_in_seconds: float) -> str:
    """
    Converts float time value from time.time() object in seconds
    to an approximation in a human readable format.
    >>> show_time(668.0372)
    >>> '00:11:06'
    :param time_in_seconds: utc.now() float value
    :return human_readable_time: a string in the OO:OO:OO format.
    """
    if isinstance(time_in_seconds, float):
        minutes, seconds = divmod(int(time_in_seconds), 60)
        hours, minutes = divmod(minutes, 60)
        human_readable_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return human_readable_time
    else:
        raise TypeError("Invalid time execution input.")


def check_duplicates(columns: list) -> list:
    """
    Iterates through all columns from the CVR file and checks if there
    are any duplicates.
    :param columns: a list of columns from the CVR file
    :return if found, a list of duplicated columns
    """
    seen = {}
    dupes = []
    for index, column in enumerate(columns):
        if column not in seen:
            seen[column] = 1
        else:
            if seen[column] == 1:
                dupes.append((column, index + 1))
            seen[column] += 1
    return dupes


def get_column_title(column_index: int) -> str:
    """
    Given a column index, returns the column title in the excel format.
    For example, 1 -> A1
    :param column_index: integer value for column index
    :return excel style column title -> AX1
    """
    assert isinstance(column_index, int) and column_index > 0
    letters = string.ascii_uppercase
    title = []
    while column_index:
        column_index, remainder = divmod(column_index-1, 26)
        title.append(letters[remainder])
    return ''.join(reversed(title)) + "1"


def get_worksheet_columns(file) -> list:
    """
    Opens a workbook and fetches its first worksheet [0] and row [1]
    :param file: a CVR file in .xlsx format
    :return a list of column names taken from row one
    """
    wb = openpyxl.load_workbook(file).worksheets[0][1]
    return [cell.value for cell in wb if cell.value is not None]


def has_duplicates(file) -> bool:
    """
    Takes a CVR file and checks its columns for duplicates. If found,
    the CVR conversion is aborted and a table with column value and title
    is shown to the user.
    :param file: a CVR file in .xlsx format
    :return a boolean value
    """
    print(f"Checking for duplicated column values in {file}...")
    dupes = check_duplicates(get_worksheet_columns(file))
    if len(dupes) > 0:
        show_duplicates(dupes, file)
        return True

    return False


def get_longest_key(dupes, padding: int = 0) -> int:
    """
    Calculates the length of the longest column name. Used to format
    the table with duplicated column values and titles.
    :param dupes: a list of duplicated columns
    :param padding: the distance between the column value and column title
    in the formatted output
    """
    return len(max([name for name, _ in dupes], key=len)) + padding


def show_duplicates(dupes: list, file):
    """
    Displays formatted information on duplicated column values and their
    column titles.
    :param dupes: a list of duplicated columns
    :param file a CVR file in .xlsx format
    """
    longest_key = get_longest_key(dupes, padding=5)
    print(f"{WARNING.substitute(FILE=file)}")
    header = f"COLUMN VALUE" + " " * (longest_key // 2) + "COLUMN TITLE\n"
    print(header + "-" * len(header))
    for dupe in dupes:
        contest, column_index = dupe
        delimiter = f"{contest}:"
        print(f"{delimiter:{longest_key}}{get_column_title(column_index)}")
    print(f"{INSTRUCTIONS.substitute()}")


def parse_cvr(args):
    """
    Converts valid CVR files to JSON schema. If the CVR file has
    duplicated columns it'll abort the conversion and point to
    the repeated values by column titles.
    """
    file_path = os.path.join(r','.join(args['file']))
    for file in file_path.split(','):
        if not has_duplicates(file):
            data_frame = pd.read_excel(file, engine='xlrd')
            cvr_to_styles_dict(data_frame)


def get_parser():
    """Initializes parser and its arguments"""
    parser = argparse.ArgumentParser(description='CVR to JSON schema parser')
    parser.add_argument('file', metavar='FILE', type=str, nargs='+',
                        help='the CVR file to parse')
    return parser


def command_line_runner():
    """Parses command arguments."""
    parser = get_parser()
    args = vars(parser.parse_args())

    if not args['file']:
        parser.print_help()
        return

    parse_cvr(args)


if __name__ == "__main__":
    command_line_runner()
