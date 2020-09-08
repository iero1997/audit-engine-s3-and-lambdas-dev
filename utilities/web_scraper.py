# pylint: disable=redefined-builtin
import csv
import re
import os
import sys
import logging
import datetime

import requests
from lxml import html
from requests import ConnectionError

from utilities import utils
from utilities.config_d import config_dict

logging.basicConfig(
    level=logging.INFO, format='%(asctime)-12s %(levelname)-8s %(message)s')
BASE_URL = "https://elections.countyofdane.com/Election-Result/110"
XPATH_ROOT = '//*[@id="{}"]'
TABLE_BODY = '/div/div[3]/div/table/tbody/'
XPATHS = {
    'top': '//*[@id="top"]/text()',
    'contest': XPATH_ROOT + '/div/div[1]/h4/text()',
    'candidate': XPATH_ROOT + TABLE_BODY + '/td[1]/strong/text()',
    'party': XPATH_ROOT + TABLE_BODY + '/td[1]/small/em/text()',
    'vote_percentage': XPATH_ROOT + TABLE_BODY + '/td[2]/div/div/@aria-valuenow',
    'number_of_votes': XPATH_ROOT + TABLE_BODY + '/td[3]/text()'
}
RACE_PATTERN = re.compile(r'race0[1-9]\d+')
BRACKETS = re.compile(r'\(|\)')
HEADERS = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/77.0.3865.120 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                      "image/webp,image/apng,*/*;q=0.8,application/"
                      "signed-exchange;v=b3",
            "Content-Type": "text/html; charset=utf-8",
            "Authority": "elections.countyofdane.com",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US, en",
        }
FIELDNAMES = [
            'Official_Contest_Name',
            "Vote_for",
            "Official_Options",
            "Party",
            "CVR_Contest_Name",
            "CVR_Options",
            "Ballot_Contest_Name",
            "Ballot_Options",
            "ExpressVote_Contest_Name",
            "ExpressVote_Options",
            "Ballot_Description",
        ]


def head_option(values: list) -> str:
    """
    A simple function that returns the head of a list (in this case) or
    any other iterable object.
    :param values: an iterator, in this case, as list of xpath elements
    :return: head list element
    """
    if iter(values):
        return next(iter(values), None)
    else:
        raise TypeError("Object is not iterable!")


def request_page(url: str = None, headers: dict = None):
    """
    Sends a GET request for a given URL.
    :param url: a URL to a site that the content of is going to be scraped
    :param headers:
    :return: a string representation of the url DOM
    """
    logging.info("Connecting...")
    if url is not None:
        try:
            request = requests.get(url, headers=headers)
        except ConnectionError as error:
            logging.error("Failed to connect due to: %s", error)
        else:
            return html.fromstring(request.content)
    else:
        logging.warning("Missing parameter: url. Nothing to scrape!")
        sys.exit(1)


def extractor(page_element: object, element_xpath: str) -> list:
    """
    This is a generic HTML element content extractor that navigates DOM
    with XPath queries.
    :param page_element: an element of the page to extract contents from
    :param element_xpath: an XPath query to navigate the tree
    :return: a list of xpath element objects
    """
    return page_element.xpath(element_xpath)


def filter_race_divs(page_element: object) -> iter:
    """
    Produces a generator expression with all race divs in the HTML
    that match a certain pattern.
    :param page_element: a race div element that contains race results
    :return: a generator expression
    """
    race_divs = extractor(page_element, '//*[@class="row"]/@id')
    return (race_div for race_div in race_divs if RACE_PATTERN.match(race_div))


def get_race_div_ids(page_element: object):
    """
    This is a finite generator built from all div elements containing an id
    fetched from a target url that are filtered against a race id pattern.
    :return: yields a valid race HTML div element
    """
    total_races = len(list(filter_race_divs(page_element)))
    logging.info("Found %d race result(s).", total_races)
    race_div_ids = filter_race_divs(page_element)
    for race_div_id in race_div_ids:
        yield race_div_id


def parse_vote_percentage(vote_percentage: list) -> list:
    """
    Converts string literals to float values.
    :param vote_percentage: a list of string values for vote percentages
    :return: a list of floats
    """
    return [float(percent) for percent in vote_percentage]


def parse_vote_count(vote_counts: list) -> list:
    """
    Converts string literals to integer values.
    :param vote_counts: a list of string values for number of votes
    :return: a list of integers
    """
    return [int(vote_count.replace(",", "")) for vote_count in vote_counts]


def parse_race(page_element: object, race_number: str) -> dict:
    """
    Parses all values from each tag within a race div to a dictionary,
    mirroring the race div data structure.
    :param race_number: a unique race id
    :param page_element: a string representation of the HTML DOM
    :return: a dictionary with parsed values from each tag with the race div
    """
    logging.info("Parsing: %s", race_number)
    contest = head_option(
        extractor(page_element, XPATHS['contest'].format(race_number))
    )
    if contest is not None:
        race_result = {
            'contest': contest,
            'candidate': extractor(
                page_element, XPATHS['candidate'].format(race_number)),
            'party': extractor(
                page_element, XPATHS['party'].format(race_number)),
            'vote_%': parse_vote_percentage(extractor(
                page_element, XPATHS['vote_percentage'].format(race_number))),
            'vote_count': parse_vote_count(extractor(
                page_element, XPATHS['number_of_votes'].format(race_number))),
        }
        return race_result
    else:
        logging.warning("There's no data for %s", race_number)
        return {}


def make_dir() -> object:
    """
    Creates a folder where the results are saved.
    :return: a folder called 'scraper'
    """
    return os.makedirs(os.path.join(config_dict['SCRAPER']), exist_ok=True)


def write_results_to_eif(race_results: list, file_name: str):
    """
    Parses a list of dictionaries with race results to a
    comma-separated-value EIF file and writes it to a disc.
    :param file_name: a file name taken from the page's h2 tag
    :param race_results: a list of dictionaries with race results
    """
    logging.info("Writing results as %s", file_name)
    make_dir()
    file_path = f"{config_dict['SCRAPER']}{file_name}.csv"
    try:
        with open(file_path, "w", newline="") as eif_file:
            fieldnames = FIELDNAMES
            writer = csv.DictWriter(eif_file, fieldnames=fieldnames)
            writer.writeheader()
            for race in race_results:
                contest = race['contest'].replace(",", "")
                for candidate, party in zip(race['candidate'], race['party']):
                    writer.writerow({
                        "Official_Contest_Name": contest,
                        "Official_Options": candidate,
                        "Party": re.sub(BRACKETS, "", party),
                    })
    except (IOError, KeyError) as error:
        logging.error("Unable to write results to a file due to: %s", error)
    else:
        logging.info("Successfully parsed %d result(s).", len(race_results))


def parse_election_page(page_element: object) -> list:
    """
    Uses a generator (get_race_div_ids()) to create a list of dictionaries
    containing parsed race results.
    :param page_element: a div element that contains an election's results
    :return: a list of dictionaries with parsed election results
    """
    return [parse_race(page_element, race_id) for race_id
            in get_race_div_ids(page_element)]


def get_file_name(page_element: object) -> str:
    """
    Parses an HTML element object with an election name to a string that's
    used as a file name.
    :param page_element: an HTML element that contains the name of the election
    :return: an election title
    """
    election = head_option(extractor(page_element, XPATHS['top']))
    return "EIF_" + election.strip().replace(" ", "_")


def run_scraper(url: str = BASE_URL):
    """
    One function to rule them all!
    :param url: an URL to County of Dane election result page
    :return:
    """
    start = datetime.datetime.utcnow()
    page = request_page(url, HEADERS)
    file_name = get_file_name(page)
    write_results_to_eif(parse_election_page(page), file_name)
    end = datetime.datetime.utcnow()
    logging.info("Execution time: %s", utils.show_time((end - start).total_seconds()))


if __name__ == "__main__":
    run_scraper()
