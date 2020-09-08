"""This module is used to update code on Lambda functions."""

""" Lambda functions must be established by hand in the aws console, 
    and must be in same region as s3 in use. At first, we were using
    us-east-1 but we are transitioning to us-west-2.
    
    Layers:

    Ord Name                            Version     ARN
    1   Python37-Pandas25                       1   arn:aws:lambda:us-east-1:504255336307:layer:Python37-Pandas25:1
    2   Klayers-python37-opencv-python-headless	14  arn:aws:lambda:us-east-1:113088814899:layer:Klayers-python37-opencv-python-headless:14
    3   Klayers-python37-tesseract              1   arn:aws:lambda:us-east-1:113088814899:layer:Klayers-python37-tesseract:1
    4   Klayers-python37-pytesseract            13  arn:aws:lambda:us-east-1:113088814899:layer:Klayers-python37-pytesseract:13
    5   Klayers-python37-PyMUPDF                18  arn:aws:lambda:us-east-1:113088814899:layer:Klayers-python37-PyMUPDF:18
    
to set up:
    Function name       genbif_from_ballots
    Runtime             Python 3.8
    Execution role      Use and existing role   AuditEngineJob
    CreateFunction
    
Add layers from github https://github.com/keithrozario/Klayers

    Ord Name                    Version  ARN
    1   Python37-Pandas25           19  arn:aws:lambda:us-west-2:113088814899:layer:Klayers-python37-pandas:19
    2   opencv-python-headless      14  arn:aws:lambda:us-west-2:113088814899:layer:Klayers-python37-opencv-python-headless:14
    3   tesseract                   1   arn:aws:lambda:us-east-1:113088814899:layer:Klayers-python37-tesseract:1
    4   pytesseract                 13  arn:aws:lambda:us-west-2:113088814899:layer:Klayers-python37-pytesseract:13
    5   PyMUPDF                     18  arn:aws:lambda:us-west-2:113088814899:layer:Klayers-python37-PyMUPDF:18
    

They are moving to Python 3.8
I can't find tesseract.

"""




import os
import sys
import codecs
from hashlib import sha256
from subprocess import run
from zipfile import ZipFile, ZIP_DEFLATED
import requests
import shutil
import stat

import boto3
from botocore.exceptions import ClientError


class Branch:
    name = ''


DEPLOY_DIR = 'lambda_deployment/'
DEPLOY_FILE = 'audit_engine_lambda_deploy.zip'
REPOSITORY_URL = 'https://github.com/raylutz/audit-engine'
LEVENSHTEIN_WHEELS_URL = 'https://files.pythonhosted.org/packages/e0/62/1f57fe56441b55dab26e5d0716b23f3b8e8494447c25322f6828126e7590/python_Levenshtein_wheels-0.13.1-cp37-cp37m-manylinux2010_x86_64.whl'
LAMBDA_FUNCTIONS = [
    #'audit_votes',
    #'extract_vote',
    #'genbif_from_ballots',
    'generate_template',
    #'ballot_to_style_mapper',
]


def get_function_sha256(function_name: str) -> str:
    """Gets SHA256 code of a Lambda function."""
    s3 = boto3.client('lambda')
    try:
        body = s3.get_function_configuration(FunctionName=function_name)
    except ClientError:
        raise ValueError(f'{function_name} Lambda function not found')
    sha_code = body['CodeSha256']
    print(f'Lambda function "{function_name}" SHA256 is "{sha_code}"')
    return sha_code


def get_package_sha256() -> str:
    """Gets SHA256 code of a ZIP package."""
    f = open(DEPLOY_DIR + DEPLOY_FILE, 'rb')
    b_string = f.read()
    hex_string = sha256(b_string).hexdigest()
    sha_code = codecs.encode(codecs.decode(hex_string, 'hex'), 'base64').decode().rstrip()
    print(f'Deployment package SHA256 is "{sha_code}"')
    return sha_code


def update_package(function_name: str):
    """Updates Lambda function with a ZIP package."""
    print(f'Updating code of Lambda function {function_name}')
    s3 = boto3.client('lambda')
    package = open(DEPLOY_DIR + DEPLOY_FILE, 'rb')
    s3.update_function_code(FunctionName=function_name, ZipFile=package.read())


def checkout_branch():
    print(f'Check out to {Branch.name} branch')
    run(f"cd {DEPLOY_DIR} && git checkout {Branch.name}", shell=True)


def pull_changes():
    run(f"cd {DEPLOY_DIR} && git pull", shell=True)


def install_dependencies():
    """Runs subprocess to install necessary dependencies.
    Then it downloads Levenshtein dependency.
    """
    print('Installing ZBar and dependencies')
    run(f"cd {DEPLOY_DIR} && pip install -t . git+git://github.com/NaturalHistoryMuseum/pyzbar.git@feature/40-path-to-zbar", shell=True)
    run(f"cd {DEPLOY_DIR} && pip install -r requirements-lambda.txt -t .", shell=True)
    print('Downloading python-Levenshtein-wheels file')
    lev_file = requests.get(LEVENSHTEIN_WHEELS_URL)
    lev_file_path = f'{DEPLOY_DIR}lev_file.whl'
    open(lev_file_path, 'wb').write(lev_file.content)
    print('Unzipping files')
    with ZipFile(lev_file_path, 'r') as archive:
        archive.extractall(DEPLOY_DIR)
    print('Removing archive')
    os.remove(lev_file_path)


def build_deployment_repository():
    """Makes a deployment directory and clones repository.
    Invokes 'install_dependencies()'.
    """
    print('Building deployment repository...')
    os.makedirs(DEPLOY_DIR, exist_ok=True)
    print('Cloning repository')
    run(["git", "clone", REPOSITORY_URL, DEPLOY_DIR], shell=True)
    if Branch.name:
        checkout_branch()
    install_dependencies()
    print('Deployment repository built')


def get_excluded_files() -> list:
    """Gets a list of files to exclude in deployment package."""
    excluded_files = []
    if not os.path.exists('.lambda_ignore'):
        print('Couldn\'t find .lambda_ignore file')
    else:
        with open('.lambda_ignore', 'r') as ignore_file:
            excluded_files = [l.rstrip() for l in ignore_file]
    return excluded_files
    

def del_rw(action, name, exc):
    os.chmod(name, stat.S_IWRITE)
    os.remove(name)


def build_deployment_package():
    """Builds a deployment ZIP package.
    Firstly checks for a deployment repository.
    Then it ZIPs files inside, excluding some of them based on list.
    """
    print('Building deployment package...')
    if os.path.exists(DEPLOY_DIR):
        print('Prior deploytment repository found, deleting it.')
        try:
            shutil.rmtree(DEPLOY_DIR, onerror=del_rw)  # Delete an entire directory tree
        except PermissionError:
            pass
        if os.path.exists(DEPLOY_DIR):
            print(f"Unable to delete '{DEPLOY_DIR}'")
            sys.exit(1)
    build_deployment_repository()

    print('Loading excluded files')
    excluded_files = get_excluded_files()
    print(f'{len(excluded_files)} items found')
    print('Archiving files')
    deployment_package = ZipFile(DEPLOY_DIR + DEPLOY_FILE, 'w', ZIP_DEFLATED)
    for root, _, files in os.walk(DEPLOY_DIR):
        for f in files:
            norm_path = os.path.normpath(os.path.join(root.replace(DEPLOY_DIR, ''), f))
            path_components = norm_path.split(os.sep)
            if not any(f in path_components for f in excluded_files):
                deployment_package.write(DEPLOY_DIR + norm_path, norm_path)
    print('Deployment package built')


def update_lambda(function_name: str = '', update_all: bool = False, branch: str = ''):
    """Main scope of lambda_updater."""
    if not function_name and not update_all:
        print('No function name specified to update. Please '\
            'provide valid "funtion_name" or set "update_all" to True')
        return
    if function_name:
        print(f'Update set to {function_name} function')
    else:
        print('Update set to all functions')
    
    if branch:
        Branch.name = branch
        print(f'Branch name set to {branch}')
    
    build_deployment_package()
    package_sha256 = get_package_sha256()

    if function_name:
        function_sha256 = get_function_sha256(function_name)
        if package_sha256 != function_sha256:
            update_package(function_name)
        else:
            print('SHA256 codes are the same')
    else:
        for func in LAMBDA_FUNCTIONS:
            function_sha256 = get_function_sha256(func)
            if package_sha256 != function_sha256:
                update_package(func)
            else:
                print('SHA256 codes are the same')
    print(f"Finished updating process using branch'{branch}'")


if __name__ == "__main__":
    # For running locally from this file use following
    # function call and set parameters.
    # update_lambda(update_all=True, branch='width-first-reorg')
    pass
