# Audit Engine

## Installation

`pip install -r requirements.txt`

### Tesseract installation

#### For Windows

<https://github.com/UB-Mannheim/tesseract/wiki>

#### For Linux and iOS

<https://github.com/tesseract-ocr/tesseract/wiki#installation>

#### Environment variable

After installation declare environment variables:
**TESSERACT_PATH** with value of Tesseract exec file i.e.
`D:\Program Files\Tesseract-OCR\tesseract.exe`

## Usage

Run `python main.py [-s source] [-c cvr] [-a aliases] [-i input] [--eif] [--skip]
 [-l limit] [-v verbose] [-t threshold] [--precinct-folder] [--party-folder]
 [-rf refresh] [-rm remove] [-ws webscraper]`

`source` - a relative path to the ZIP file with ballots in PDF format

`cvr` - a relative path to the excel file with Cast Vote Record

`input` - a relative path to the input file. Input file is an excel file with
columns `argument` and `value`. `argument` column takes a value of file types
like `source`, `cvr`, `aliases` and other arguments available. `value` column
contain relative paths to these files

`eif` - a relative path to the Election Information File (EIF). This file contains
the following columns: 

official_contest_name: unique names which will be used as a replacement header in the cvr file

original_cvr_header: the original contest names from the cvr for reference

ballot_contest_name: The exact text from the ballot fro this contest, including newlines

vote_for: The maximum number of votes allowed

writein_num: The number of write-in lines

official_options: a comma-separated list of official contest names

description: for question-type contests, the full desription of the question as found on the ballot

`job` - a path in which all other resource related files will be saved. usualy resouces/jobname

`skip` - skip a number of ballots from the top of the files list or skip
to the desired precinct and any precinct after that

`limit` - a number indicating how many ballots should be processed in the audit run

`precinct` - one or more lines that specify which precincts are to be included in the audit run

`ballotid` - one or more lines that specify which ballotids are to be included in the audit run

`verbose` - a number indicating levels of JSON data to display on screen. 
Verbose=1 provides just top level dictionary.
Verbose=2 provides dictionary entries of Contest but not Options.
Verbose=3 provides everything including gory detail

`threshold` - a number indicating threshold of images required to build new style

`precinct-folder` - a number indicating which level of source ZIP file directory
tree is a precinct name. Starting from the first level of directories as `0`.
Default value `0`

`party-folder` - a number indicating which level of source ZIP file directory
tree is a party name. Starting from first level of directories as `0`. 
Default value `1`

`refresh` - a `true` / `false` value indicating if program should load already
processed results and process them with new aliases

`remove` - a `true` / `false` value indicating if previous styles and results
should be removed before processing new ballots

`webscraper` - a simple web-scraper for County of Dane election results. Takes
a URL to election results page as an argument, scrapes the page, and saves the
parsed results to a comma-separated value file. As of now (25/11/19),
the scraper handles *only* County of Dane 
[URLs](https://elections.countyofdane.com/Election-Result/).

## Linting and Testing

Install dev dependencies on machines where testing is performed:

`pip install -r requirements-dev.txt`

### Linting

Run the linter for a selected file (when in project main directory):

`pylint --rcfile .pylintrc file_to_lint.py`

Run the linter for the entire project - for UNIX based systems:

`pylint --rcfile .pylintrc $(pwd)`

### Testing

Run all tests (when in project main directory):

`pytest`

### Lambda

To deploy repository to AWS lambda, first make a fresh copy of the repository. Then install some of the necessary dependencies with:

`pip install -t . git+git://github.com/NaturalHistoryMuseum/pyzbar.git@feature/40-path-to-zbar`

and

`pip install -r requirements-lambda.txt -t .`

(make sure dependencies are installed inside repository folder). Next compress repository to the ZIP file.

Note: Currently we have to install specific version (branch 40) of the **pyzbar** module. It's because this version handles loading **zbar** module with an environment variable. Files inside main folder named *libzbar* are related to this.

Next download **Levenshtein** module binaries manually by going to [this site](https://pypi.org/project/python-Levenshtein-wheels/#files). There look for a package with Python version 3.7 and architecture *manylinux2010_x86_64*.

Archive upload as lambda function code.

Set enviroment variable `ZBAR_PATH: libzbar.so`.

Set enviroment variable `STORE_TYPE: s3`.

Set function handler to `utilities/votes_extractor.lambda_handler`.

Add layers for these modules:

- PyMUPDF
- Pandas
- OpenCV
- Tesseract
- Pytesseract

Most of them can be found under [this repository](https://github.com/keithrozario/Klayers/blob/master/deployments/python3.7/arns/us-east-1.csv).
