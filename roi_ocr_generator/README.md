## General
This is a stand-alone script that finds required regions of interest within images and
saves them in a styles dictionary in the JSON format.

Style directory should contain both JSON and PNG files.
JSON files in style directory should at this moment contain:

{
    "created_from": n,
    "rois": []
}

Where n stand for numer of ballots the corresponding image were created from.

## Usage

```
usage: roi_ocr_generator.py [-h] [-s] STYLE DIR PATH

CVR to JSON schema parser

positional arguments:
  STYLE DIR PATH            style directory path

optional arguments:
  -h, --help                show this help message and exit
  -v, --version             save ROIs images
```
