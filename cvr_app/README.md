# cvr2styles
a CVR to styles dictionary converter

## General
This is a (_almost_) stand-alone script that converts valid CVR excel files to
a styles dictionary in the JSON format. 

## Usage

```
usage: cvr2styles.py [-h] [-v] [FILE [FILE ...]]

CVR to JSON schema parser

positional arguments:
  FILE           the CVR file to parse

optional arguments:
  -h, --help     show this help message and exit
  -v, --version  displays the current version of cvr2styles
```

**Requirements**

- [x] Python 3.7
- [x] pandas
- [x] openpyxl

Create a new virtual environment with `Python 3.7` and install all dependencies:
> pip3 install -r requirements-cvr.txt

Run the script with:
> python3 cvr2styles.py CVR_FILE.xlsx
