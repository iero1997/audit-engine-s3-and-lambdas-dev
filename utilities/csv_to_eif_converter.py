# pylint: disable=using-constant-test

import csv
import glob
import logging

FIELDNAMES = ['Official_Contest_Name',
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

logging.basicConfig(
    level=logging.INFO, format='%(asctime)-12s %(levelname)-8s %(message)s')


def open_file(file_path: str, mode: str = 'r'):
    handle = None
    try:
        handle = open(file_path, mode, newline='')
    except IOError:
        logging.error("Unable to open %s", file_path)
    else:
        return handle
    finally:
        handle.close()


def csv_to_eif(file: str):
    """
    A bare-bones Wakulla election results report to EIF file converter.
    :param file: a valid Wakulla election report file in the .csv format
    :return: a partially filled EIF file
    """
    csv_file = open_file(file)
    has_header = csv.Sniffer().sniff(csv_file.read(1024))
    csv_file.seek(0)
    reader = csv.reader(csv_file)
    if has_header:
        next(reader)
    eif_output = open_file("EIF_" + csv_file.name, 'w')
    writer = csv.DictWriter(eif_output, fieldnames=FIELDNAMES)
    writer.writeheader()
    for row in reader:
        contest, option, party = row[1], row[3], row[4]
        writer.writerow({
            "Official_Contest_Name": contest,
            "Official_Options": option,
            "Party": party,
        })
    logging.info("Successfully parsed: %s", csv_file.name)


def run_converter():
    for file in glob.glob('*.csv'):
        csv_to_eif(file)


if __name__ == "__main__":
    run_converter()
