import os
import glob
import json
import datetime
from operator import itemgetter

import dominate
from dominate.util import raw
from dominate.tags import a, div, h1, h2, h5, h6, link, p, script, table, tbody, td, th, thead, tr, u, i
import pandas as pd

from utilities import utils, logs
from utilities.config_d import config_dict
#from models.Contest import Contest
from models.DB import DB


#STATUS_DICT = Contest.contest_status_dict
#VALIDATION_DICT = Contest.validation_status_dict
STYLES = []
VOTES_RESULTS = []
DISAGREED_BALLOTS = []
OVERVOTED_BALLOTS = []
COUNTERS = {
    'agreed_ballots': 0,
    'blank_ballots': 0,
}

ROIS_MAP_DF = pd.DataFrame()


def report_head(doc):
    with doc.head:
        link(
            rel='stylesheet',
            href='https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/css/bootstrap.min.css',
            integrity="sha384-ggOyR0iXCbMQv3Xipma34MD+dH/1fQ784/j6cY/iJTQUOhcWr7x9JvoRxT2MZw1T",
            crossorigin="anonymous",
        )
        link(
            rel='stylesheet',
            href='https://use.fontawesome.com/releases/v5.7.0/css/all.css',
            integrity='sha384-lZN37f5QGtY3VHgisS14W3ExzMWZxybE1SJSEsQp9S+oqd12jhcu+A56Ebc1zFSJ',
            crossorigin="anonymous",
        )
        script(
            src="https://code.jquery.com/jquery-3.4.1.slim.min.js",
            integrity="sha384-J6qa4849blE2+poT4WnyKhv5vZF5SrPo0iEjwBvKU7imGFAV0wwj1yYfoRSJoZ+n",
            crossorigin="anonymous"
        )
        script(
            src="https://stackpath.bootstrapcdn.com/bootstrap/4.4.1/js/bootstrap.min.js",
            integrity="sha384-wfSDF2E50Y2D1uUdj0O3uMBJnjuUD4Ih7YwaYd1iqfktj0Uod8GCExl3Og8ifwB6",
            crossorigin="anonymous"
        )

def report_headline(version):
    with div(cls='jumbotron'):
        h1('Audit Engine: {version} - Discrepancy Report for Automated Independent Audit'.format(version=version))
        build_time = datetime.datetime.now(datetime.timezone.utc)
        p(f'Summary built at: {build_time.strftime("%Y-%m-%d %H:%M:%S")}', cls='lead')


def get_disagreed_votes_number_for_option(option: str, contest_disagreed_df: pd.DataFrame) -> tuple:
    """
    :return: Tuple of ints. First is the count of votes, which are not
    agreed across Audit and CVR (both says different things).
    Second is the number of votes that are not agreed on the CVR.
    """
    disagreed = 0
    certified_results = 0
    for _, row in contest_disagreed_df.iterrows():
        vote_difference = json.loads(row['vote_difference'])
        vote_difference = vote_difference.get(option)
        if vote_difference != 0:
            disagreed += 1
        if vote_difference != -1:
            certified_results += 1
    return disagreed, certified_results


def mount_option_row(option: str, contest_disagreed_df: pd.DataFrame, contest_marks_df: pd.DataFrame):
    audit_votes = contest_marks_df.loc[contest_marks_df['option'] == option]['num_votes'].sum()
    disagreed_votes, certified_results = get_disagreed_votes_number_for_option(option, contest_disagreed_df)
    audit_system_adjudicated_votes = audit_votes - disagreed_votes
    audit_indeterminate_votes = disagreed_votes
    canvassing_board_adjustments = 0
    audit_total_votes = audit_system_adjudicated_votes + canvassing_board_adjustments
    certified_results_total = audit_votes - certified_results
    with tr():
        td(option)
        td(audit_system_adjudicated_votes)
        td(audit_indeterminate_votes)
        td(canvassing_board_adjustments)
        td(audit_total_votes)
        td(certified_results_total)
        td(certified_results_total - audit_total_votes)


def mount_discrepancy_table(contest: str, contest_disagreed_df: pd.DataFrame,
                            precinct_marks_df: pd.DataFrame) -> table:
    contest_marks_df = precinct_marks_df.loc[precinct_marks_df['contest'] == contest]
    overvotes = contest_marks_df['overvotes'].sum()
    undervotes = contest_marks_df['undervotes'].sum()
    options = [o for o in contest_marks_df['option'].unique().tolist() if not o.startswith('#contest vote_for')]
    with table(cls='table table-striped'):
        with thead():
            with tr():
                th('Candidate or Issue', scope="col")
                th('Audit System Adjudicated Votes', scope="col")
                th('Audit Indeterminate Votes', scope="col")
                th('Canvassing Board Adjustments', scope="col")
                th('Audit Total Votes', scope="col")
                th('Certified Results Total', scope="col")
                th('Difference', scope="col")
        with tbody():
            for option in options:
                mount_option_row(option, contest_disagreed_df, contest_marks_df)
            with tr():
                td('Number of overvotes')
                td(overvotes, colspan=6)
            with tr():
                td('Number of undervotes')
                td(undervotes, colspan=6)


def build_discrepancy_reports(precinct: str, precinct_agreed_df: pd.DataFrame, precinct_disagreed_df: pd.DataFrame,
                              precinct_marks_df: pd.DataFrame) -> dominate.document:
    version = utils.show_version()
    doc = dominate.document(title='Audit Engine version: ' + version)
    report_head(doc)
    with doc:
        with div(cls='container'):
            report_headline(version)
            div(a('< Back', href='#', onclick='window.history.back()'))
            h5(precinct)
            for contest in precinct_marks_df['contest'].unique().tolist():
                contest_disagreed_df = precinct_disagreed_df.loc[precinct_disagreed_df['contest'] == contest]
                h6(contest)
                mount_discrepancy_table(contest, contest_disagreed_df, precinct_marks_df)            
    return doc


def build_discrepancy_parent_report(discrepancy_reports):
    version = utils.show_version()
    doc = dominate.document(title='Audit Engine version: ' + version)
    report_head(doc)
    discrepancy_reports.sort(key=itemgetter('discrepancy', 'ballots'), reverse=True)
    with doc:
        with div(cls='container'):
            report_headline(version)
            with table(cls='table table-striped'):
                with thead():
                    with tr():
                        th('#', scope="col")
                        th('Precinct', scope="col")
                        th('Ballots total', scope="col")
                        th('Discrepancy', scope="col")
                        th('Report', scope="col")
                with tbody():
                    for index, report in enumerate(discrepancy_reports):
                        with tr():
                            report_abs_path = os.path.abspath(report.get('path'))
                            th(index + 1)
                            td(report.get('precinct'))
                            td(report.get('ballots'))
                            td(f"{report.get('discrepancy')}%")
                            td(a(i(cls='far fa-file-alt'), href=report_abs_path, targer='_blank'))
    return doc


def generate_cmpcvr_report(argsdict):
    discrepancy_reports = []
    report_dirpath = DB.dirpath_from_dirname('reports')
    report_path = f"{report_dirpath}Discrepancy Report for Automated Independent Audit.html"
    #cmpcvr_dirpath = DB.dirpath_from_dirname('cmpcvr')
    #try:
    # #    cmpcvr_agreed_df = pd.read_csv(f"{cmpcvr_dirpath}cmpcvr-agreed.csv")
    # cmpcvr_agreed_df = DB.load_data(dirname='cmpcvr', name='cmpcvr-agreed.csv', silent_error=True)
    # #except pd.errors.EmptyDataError:
    # if cmpcvr_agreed_df is None:
        # cmpcvr_agreed_df = pd.DataFrame(columns=['ballot_id', 'style', 'precinct', 'contest', 'agreed', 'blank',
        #                                         'chunk_name', 'contests_mismatch'])
    # try:
        # cmpcvr_disagreed_df = pd.read_csv(f"{cmpcvr_dirpath}cmpcvr-disagreed.csv")
    # except pd.errors.EmptyDataError:
    cmpcvr_disagreed_df = DB.load_data(dirname='cmpcvr', name='disagreed.csv', silent_error=True)
    if cmpcvr_disagreed_df is None:
        cmpcvr_disagreed_df = pd.DataFrame(columns=['ballot_id', 'style', 'precinct', 'contest', 'agreed', 'blank', 'chunk_name',
                                                   'contests_mismatch', 'vote_difference', 'audit_info', 'cvr_info'])
    # try:
        # columns = ['idx', 'ballot_id', 'style', 'precinct', 'contest', 'option',
        # 'has_indication', 'num_marks', 'num_votes', 'pixel_metric_value',
        # 'writein_name', 'overvotes', 'undervotes', 'ssidx', 'delta_y',
        # 'ev_coord_str', 'ev_logical_style', 'ev_precinct_id']
        # dtype = {'idx': int, 'ballot_id': int, 'style': int, 'precinct': str,
        # 'option': str, 'has_indication': str, 'writein_name': str,
        # 'num_marks': int, 'num_votes': int, 'pixel_metric_value': float,
        # 'overvotes': int, 'undervotes': int, 'ssidx': int, 'delta_y': int}
        # ballot_marks_df = pd.read_csv(cmpcvr_dirpath + 'ballot_marks_df.csv', dtype=dtype, skiprows=1, names=columns)
    # except ValueError:
        # ballot_marks_df = pd.read_csv(cmpcvr_dirpath + 'ballot_marks_df.csv')
        
    # the following will require that all marks_df segments are combined.
    ballot_marks_df = DB.load_data(dirname='marks', name='marks.csv', silent_error=True)

    num_marks_ballots = len(ballot_marks_df['ballot_id'].unique())
    
    precincts = ballot_marks_df['precinct'].unique().tolist()
    for precinct in precincts:
        #precinct_cmpcvr_agreed_df = cmpcvr_agreed_df.loc[cmpcvr_agreed_df['precinct'] == precinct]
        precinct_cmpcvr_disagreed_df = cmpcvr_disagreed_df.loc[cmpcvr_disagreed_df['precinct'] == precinct]
        disagreed_rows = len(precinct_cmpcvr_disagreed_df['ballot_id'].unique())

        # Pass precincts in which number of disagreed ballots is smaller than the threshold.
        discrepancy = round((disagreed_rows / num_marks_ballots) * 100, 2)
        if discrepancy < argsdict.get('precinct_reporting_threshold_percent', 0):
            continue
        precinct_report_path = f"{report_dirpath}Report - {precinct}.html"
        discrepancy_reports.append({
            'precinct': precinct,
            'ballots': num_marks_ballots,
            'discrepancy': discrepancy,
            'path': precinct_report_path
        })
        precinct_marks_df = ballot_marks_df.loc[ballot_marks_df['precinct'] == precinct]
        with open(precinct_report_path, 'w') as html_file:
            doc = build_discrepancy_reports(
                precinct, 
                precinct_agreed_df=None, 
                precinct_disagreed_df=precinct_cmpcvr_disagreed_df,
                precinct_marks_df=precinct_marks_df)
                
            html_file.write(doc.render())
    with open(report_path, 'w') as html_file:
            doc = build_discrepancy_parent_report(discrepancy_reports)
            html_file.write(doc.render())
            utils.sts(os.path.abspath(report_path))


def get_contest_row(contest, cmpcvr_details, style_df):
    cmpcvr_options = cmpcvr_details.get('options')
    contest_row = div(h6(u(contest)), cls='my-2')
    contest_df = style_df.loc[style_df['contest'] == contest]
    options = [o for o in contest_df['option'].tolist() if '#contest vote_for' not in o]
    for option in options:
        option_row = div(div(option, cls='col'), cls='row')
        if option in cmpcvr_options:
            if cmpcvr_options[option].get('selected'):
                option_row.attributes['class'] += ' font-weight-bold'
            if cmpcvr_options[option].get('PMV'):
                option_row += div(f"PMV: {cmpcvr_options[option].get('PMV')}", cls='col')
        contest_row += option_row
    return contest_row


def get_ballot_details_td(row) -> td:
    disagreed_contests = json.loads(row['disagreed_info'])
    details_td = td(colspan='2')
    details_tr = div(cls='row')
    details_td += details_tr
    contests_mismatch = disagreed_contests.get('contests_mismatch')
    audit_col = div(h5('Audit'), cls='col')
    cvr_col = div(h5('CVR'), cls='col')
    details_tr += audit_col, cvr_col
    if contests_mismatch:
        audit_col += [div(c) for c in contests_mismatch['audit_contests'].split(',')]
        cvr_col += [div(c) for c in contests_mismatch['cvr_contests'].split(',')]
        excluded_col = div(h5('Excluded'), cls='col')
        excluded_col += [div(c) for c in contests_mismatch['excluded_contests'].split(',')]
        details_td += div(excluded_col, cls='row')
        return details_td
    style_df = ROIS_MAP_DF.loc[ROIS_MAP_DF['style'] == int(row['style'])]
    contests = style_df['contest'].unique()
    for contest in contests:
        if contest in disagreed_contests:
            audit_col += get_contest_row(contest=contest, cmpcvr_details=disagreed_contests[contest]['audit'],
                                         style_df=style_df)
            cvr_col += get_contest_row(contest=contest, cmpcvr_details=disagreed_contests[contest]['cvr'],
                                         style_df=style_df)
    return details_td


def get_summary_table(cmpcvr_df):
    ballots_processed = cmpcvr_df.shape[0]
    styles_detected = len(cmpcvr_df['style'].unique())
    matched_ballots = len(cmpcvr_df.loc[cmpcvr_df['agreed'] == 1])
    non_matched_ballots = len(cmpcvr_df.loc[cmpcvr_df['agreed'] == 0])
    blank_ballots = len(cmpcvr_df.loc[cmpcvr_df['blank'] == 1])
    overvoted_ballots = len(cmpcvr_df.loc[cmpcvr_df['overvotes'] > 0])
    with table(cls='table table-striped'):
        with tbody():
            with tr():
                th('Number of ballots processed')
                td(ballots_processed)
            with tr():
                th('Number of different ballot types')
                td(styles_detected)
            with tr():
                th('Number of ballots matching the CVR results')
                td(matched_ballots)
            with tr():
                th('Number of ballots not matching the CVR results')
                td(non_matched_ballots)
            with tr():
                th('Number of completely blank ballots')
                td(blank_ballots)
            with tr():
                th('Number of overvotes')
                td(overvoted_ballots)


def mount_ballots_to_table(cmpcvr_df: pd.DataFrame) -> tuple:
    cmpcvr_df.dropna(subset=['disagreed_info'], inplace=True)
    index = 1
    for _, row in cmpcvr_df.iterrows():
        head_row = tr(cls='', data_toggle='collapse', data_target=f'#collapse{index}')
        head_row += th(index), td(row['ballot_id']), td(row['style'])
        collapse_row = tr(id=f'collapse{index}', cls='collapse')
        collapse_row += td(), get_ballot_details_td(row)
        index += 1
        yield head_row, collapse_row


def get_cmpcvr_doc(cmpcvr_df: pd.DataFrame) -> dominate.document:
    version = utils.show_version()
    doc = dominate.document(title='Audit Engine version: ' + version)
    with doc.head:
        link(
            rel='stylesheet',
            href='https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/css/bootstrap.min.css',
            integrity="sha384-ggOyR0iXCbMQv3Xipma34MD+dH/1fQ784/j6cY/iJTQUOhcWr7x9JvoRxT2MZw1T",
            crossorigin="anonymous",
        )
        script(
            src="https://code.jquery.com/jquery-3.4.1.slim.min.js",
            integrity="sha384-J6qa4849blE2+poT4WnyKhv5vZF5SrPo0iEjwBvKU7imGFAV0wwj1yYfoRSJoZ+n",
            crossorigin="anonymous"
        )
        script(
            src="https://stackpath.bootstrapcdn.com/bootstrap/4.4.1/js/bootstrap.min.js",
            integrity="sha384-wfSDF2E50Y2D1uUdj0O3uMBJnjuUD4Ih7YwaYd1iqfktj0Uod8GCExl3Og8ifwB6",
            crossorigin="anonymous"
        )
    with doc:
        with div(cls='container'):
            with div(cls='jumbotron'):
                h1('Audit Engine: {version} - vote records summary'.format(version=version))
                build_time = datetime.datetime.now(datetime.timezone.utc)
                p(f'Summary built at: {build_time.strftime("%Y-%m-%d %H:%M:%S")}', cls='lead')
            get_summary_table(cmpcvr_df)
            with table(cls='table table-hover'):
                with thead():
                    with tr():
                        th('#', scope="col")
                        th('Ballot ID', scope="col")
                        th('Style', scope="col")
                table_body = tbody()
                table_body += mount_ballots_to_table(cmpcvr_df)
            
    return doc

def create_html_string(COUNTERS, BALLOTLISTS, DISAGREED_INFO_DICT):
    """Creates a HTML string for generating the summary file.
    
    Accesses the following:
        COUNTERS['ballots_processed']
        COUNTERS['styles_detected']
        COUNTERS['matched_ballots']
        COUNTERS['non_matched_ballots']
        COUNTERS['blank_ballots']
        list of ballot OVERVOTED_BALLOTS
        list of ballot DISAGREED_BALLOTS
            accesses ballot pdf files per precinct and ballot_id
        DISAGREE_INFO_DICT is keyed by ballot_id which provides dict of contests providing error information
                f"{config_dict['RESOURCES_PATH']}{config_dict['DISAGREEMENTS_PATHFRAG']}{ballot.ballotdict['precinct']}/{ballot.ballotdict['ballot_id']}.pdf")

        list STYLES
            style.style_num
            style.number
            style.build_from_count
        files style_summary = glob.glob(f"{config_dict['RESOURCES_PATH']}{config_dict['STYLES_PATHFRAG']}{style.code}.html")[0]
        list VOTES_RESULTS   (results for each contest)
            result_contest['contest_name']
            result_contest['selections']
            result_contest['vote_for']
            result_contest['question']
            result_contest['total_ballots']
            result_contest['total_votes']
            result_contest['undervote']
            result_contest['overvote']
    """
    script_abs_path = os.path.abspath('assets/copy_to_clipboard.js')
    version = utils.show_version()
    doc = dominate.document(title='Audit Engine version: ' + version)
    with doc.head:
        link(
            rel='stylesheet',
            href='https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/css/bootstrap.min.css',
            integrity="sha384-ggOyR0iXCbMQv3Xipma34MD+dH/1fQ784/j6cY/iJTQUOhcWr7x9JvoRxT2MZw1T",
            crossorigin="anonymous",
        )
        script(type='text/javascript', src=script_abs_path)

    with doc:
        with div(cls='container'):
            with div(cls='jumbotron'):
                h1('Audit Engine: {version} - vote records summary'.format(version=version))
                build_time = datetime.datetime.now(datetime.timezone.utc)
                p(f'Summary built at: {build_time.strftime("%Y-%m-%d %H:%M:%S")}', cls='lead')
            with table(cls='table table-striped'):
                with tbody():
                    with tr():
                        th('Number of ballots processed')
                        td(COUNTERS['ballots_processed'])
                    with tr():
                        th('Number of different ballot types')
                        td(COUNTERS['styles_detected'])
                    with tr():
                        th('Number of ballots matching the CVR results')
                        td(COUNTERS['matched_ballots'])
                    with tr():
                        th('Number of ballots not matching the CVR results')
                        td(COUNTERS['non_matched_ballots'])
                    with tr():
                        th('Number of completely blank ballots')
                        td(COUNTERS['blank_ballots'])
                    with tr():
                        th('Number of overvotes')
                        td(COUNTERS['overvoted_ballots'])
                    with tr():
                        th('Number of disagreements')
                        td(COUNTERS['disagreed_ballots'])
            with div(cls='my-4'):
                h2('Styles')
            with table(cls='table table-striped'):
                with thead():
                    with tr():
                        th('Style code', scope="col")
                        th('Style number', scope="col")
                        th('Based on number of ballots', scope="col")
                        th('Built at', scope="col")
                with tbody():
                    for style in STYLES:
                        with tr():
                            utc_time = datetime.datetime.utcfromtimestamp(style.timestamp)
                            style_summary = glob.glob(f"{config_dict['RESOURCES_PATH']}{config_dict['STYLES_PATHFRAG']}{style.code}.html")[0]
                            td(a(style.style_num, href=os.path.realpath(style_summary), target="_blank"))
                            td(style.number)
                            td(style.build_from_count)
                            td(f'{utc_time.strftime("%Y-%m-%d %H:%M:%S")}')
            # Tables with contests results:
            with div(cls='my-4'):
                h2('Contests results')
            for result_contest in VOTES_RESULTS:
                contest_name = result_contest['contest_name']
                selections = result_contest['selections']
                vote_for = result_contest['vote_for']
                question = result_contest['question']
                with div(cls='my-4'):
                    h5(f'Contest results "{contest_name}" (vote for {vote_for}):')
                    if question:
                        h6(f'Question "{question}"')
                with table(cls='table table-striped'):
                    with thead():
                        with tr():
                            th('#', scope="col")
                            th('Candidate', scope="col")
                            th('Votes', scope="col")
                            th('%', scope="col")
                    with tbody():
                        for index, candidate_name in enumerate(sort_option_names(selections.keys())):
                            try:
                                total_votes = result_contest['total_votes']
                                percent = round((selections[candidate_name] / total_votes) * 100, 2)
                            except ZeroDivisionError:
                                percent = 0.0
                            with tr():
                                th(index + 1, scope="row")
                                td(candidate_name)
                                td(candidate_name)
                                td(f'{percent}%')
                with table(cls='table table-striped'):
                    with tbody():
                        with tr():
                            th('Total number of ballots')
                            td(result_contest['total_ballots'])
                        with tr():
                            th('Number of votes')
                            td(result_contest['total_votes'])
                        with tr():
                            th('Number of undervotes')
                            td(result_contest['undervote'])
                        with tr():
                            th('Number of overvotes')
                            td(result_contest['overvote'])
            # Table with overvotes:
            with div(cls='my-4'):
                h2('Ballots with overvotes:')
            with table(cls='table table-striped'):
                with thead():
                    with tr():
                        th('#', scope="col")
                        th('Precinct / Contest name', scope="col")
                        th('Ballot file / Ballot and CVR status', scope="col")
                        th('Overvotes / Contest validation status', scope="col")
                with tbody():
                    dirpath = DB.dirpath_from_dirname('overvotes')
                    for index, ballot_id in enumerate(BALLOTLISTS['overvoted_ballots']):
                        filepathlist = glob.glob(f"{dirpath}**/{ballot_id}i.pdf", recursive=True)
                        if not filepathlist: continue 
                        filepath = filepathlist[0]
                        with tr():
                            th(index + 1, scope="row")
                            td('')
                            with td():
                                ballot_image_filepath = os.path.abspath(filepath)
                                a(ballot_id, href=ballot_image_filepath, target="_blank")
                            td('')
#                        overvotes_contests = list(
#                            filter(
#                                lambda x: (x.contest_ballot_status == STATUS_DICT['overvote']) or
#                                (x.contest_cvr_status == STATUS_DICT['overvote']), ballot.ballotdict['contests']))
#                        for contest in overvotes_contests:
#                            with tr():
#                                td()
#                                td(contest.contest_name)
#                                td(f"{contest.contest_ballot_status} / {contest.contest_cvr_status}")
#                                td(contest.contest_validation if contest.contest_validation is not None else '')
            # Table with blank ballots:
            with div(cls='my-4'):
                h2('Blank Ballots:')
            with table(cls='table table-striped'):
                with thead():
                    with tr():
                        th('#', scope="col")
                        th('Precinct / Contest name', scope="col")
                        th('Ballot file / Ballot and CVR status', scope="col")
                        th('Overvotes / Contest validation status', scope="col")
                with tbody():
                    dirpath = DB.dirpath_from_dirname('blank_ballots')
                    for index, ballot_id in enumerate(BALLOTLISTS['blank_ballots']):
                        filepathlist = glob.glob(f"f{dirpath}{ballot_id}i.pdf", recursive=True)
                        if not filepathlist:
                            continue
                        filepath = filepathlist[0]
                        with tr():
                            th(index + 1, scope="row")
                            td('')
                            with td():
                                ballot_image_filepath = os.path.abspath(filepath)
                                a(ballot_id, href=ballot_image_filepath, target="_blank")
                            td('')
            # Table with disagreements:
            with div(cls='my-4'):
                h2('Ballots with disagreements:')
            with table(cls='table table-striped'):
                with thead():
                    with tr():
                        th('#', scope="col")
                        th('Ballot file', scope="col")
                        th('Disagreement Details', scope="col")
                with tbody():
                    dirpath = DB.dirpath_from_dirname('disagreements')
                    for index, ballot_id in enumerate(BALLOTLISTS['disagreed_ballots']):
                        filepathlist = glob.glob(f"{dirpath}**/{ballot_id}i.pdf", recursive=True)
                        if not filepathlist: continue 
                        filepath = filepathlist[0]
                        with tr():
                            th(index + 1, scope="row")
                            with td():
                                ballot_image_filepath = os.path.abspath(filepath)
                                a(ballot_id, href=ballot_image_filepath, target="_blank")
                            td(raw(f"<pre>{DISAGREED_INFO_DICT[ballot_id]}</PRE>"))
    return doc


def sort_option_names(options):
    """
    Returns an alphabetically sorted list with option names.
    Puts write-ins at the end.
    """
    return sorted(options, key=lambda x: (x == 'write-in:', x))


def write_html_summary(html_doc, filename='summary'):
    summary_path = DB.dirpath_from_dirname(filename)
    if not os.path.exists(summary_path):
        os.makedirs(summary_path)
    html_file_path = f"{summary_path}{filename}.html"
    html_file = open(html_file_path, 'w')
    html_file.write(html_doc.render())
    html_file.close()
    return os.path.abspath(html_file_path)
