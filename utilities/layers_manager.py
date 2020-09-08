"""
Layer Manager is used to create AWS Lambda Layers in an AWS account.
"""

import json
import boto3
#import pandas as pd
#import numpy as np
import urllib.request
from aws_lambda import s3utils
from botocore.exceptions import ClientError

from models.DB import DB

region = 'us-east-1'
base_url = f'https://api.klayers.cloud/api/v1/layers/latest/{region}/'


def create_update_klayer(client, layer_arn, package, bucket='us-east-1-layers'):
    try:
        response = client.get_layer_version_by_arn(Arn=layer_arn)
        package_url = response['Content']['Location']
        package_sha256 = response['Content']['CodeSha256']
        # Check if layer is already up to date.
        layer_name = layer_arn.split(':')[-2]
        layer_version = layer_arn.split(':')[-1]
        current_layer_version = get_latest_layer_version(client, layer_name)
        layer_sha256 = get_layer_sha256(client, layer_name, current_layer_version)
        meta_data = {"source_layer_arn": layer_arn, "package": package}
        if package_sha256 != layer_sha256:
            if layer_sha256 is None:
                print(f"Creating layer for package: {package} from KLayer ARN: {layer_arn}")
            else:
                print(f"Updating layer for package: {package} from KLayer ARN: {layer_arn}")

            with urllib.request.urlopen(package_url) as f:
                data = f.read()
                key = f'{layer_name}/{layer_name}-{layer_version}.zip'
                s3utils.put_s3_core(bucket, key, data)
                meta_data.update(
                    {'package_uri': f"s3://{bucket}/{key}", 'layer_name': layer_name, 's3_bucket': bucket,
                     's3_key': key})
                create_layer(lambda_client, meta_data)
        else:
            # utils.sts(f'SHA256 codes are the same for layer: {layer_name}')
            # print(f'SHA256 codes are the same for layer: {layer_name}')
            print(f"Layer already upto date for package: {package} with KLayer ARN: {layer_arn}")
        return meta_data
    except Exception as ex:
        print(f"Error occurred for {package} with KLayer ARN: {layer_arn} with error: {str(ex)}")


def get_latest_layer_version(client, layer_name, max_items=1):
    """Gets SHA256 code of a layer package."""
    try:
        response = client.list_layer_versions(LayerName=layer_name, MaxItems=max_items)
    except ClientError:
        # raise ValueError(f'{layer_name} layer not found')
        # utils.sts(f'{layer_name} layer not found')
        return 0
    if len(response['LayerVersions']):
        latest_version = response['LayerVersions'][0]['Version']
    else:
        latest_version = 0
    # utils.sts(f'Layer "{layer_name}" latest version is "{latest_version}"')
    return latest_version


def get_layers(client):
    try:
        response = client.list_layers()
        return response['Layers']

    except ClientError as exp:
        print(str(exp))


def get_layer_sha256(client, layer_name, version):
    """Gets SHA256 code of a layer package."""
    try:
        response = client.get_layer_version(LayerName = layer_name, VersionNumber=version)
    except ClientError:
        # raise ValueError(f'{layer_name} layer not found')
        # utils.sts(f'{layer_name} layer not found')
        return None
    sha_code = response['Content']['CodeSha256']
    # utils.sts(f'Layer "{layer_name}" SHA256 is "{sha_code}"')
    return sha_code


def create_layer(client, meta_data):
    client.publish_layer_version(
        LayerName=meta_data['layer_name'],
        Description=f"{meta_data['source_layer_arn']}/{meta_data['package']}",
        Content={
            'S3Bucket': meta_data['s3_bucket'],
            'S3Key': meta_data['s3_key']
        },
        CompatibleRuntimes=['python3.7','python3.8']
    )


def get_klayers_latest_arn(package):
    try:
        response = urllib.request.urlopen(base_url + package)
        data = response.read().decode("utf-8")
        data = json.loads(data)
        return data['arn']

    except Exception as exp:
        print(str(exp))


def get_updated_klayer():
    lambda_client = boto3.client('lambda')
    # Get all layer deployed which are deployed from KLayers on aws account.
    deployed_layers = get_layers(lambda_client)
    deployed_klayers = []
    for layer in deployed_layers:
        if 'klayers' in layer['LayerName'].lower():
            deployed_klayers.append(layer)

    # Get all layers for which newer version is available.
    new_version_available = []
    for layer in deployed_klayers:
        source_metadata = layer['LatestMatchingVersion']['Description'].split('/')
        source_klayer_arn = source_metadata[0]
        package_name = source_metadata[1]
        latest_klayer_arn = get_klayers_latest_arn(package_name)
        if latest_klayer_arn.lower() == source_klayer_arn.lower():
            print(f"Layer {layer['LayerName']} is upto date")
        else:
            layer.update({'latest_klayer_arn' : latest_klayer_arn})
            new_version_available.append(layer)

    return new_version_available


def publish_to_sns(sub, msg):
    """
    Topic arn is obtained from AWS SNS. We can create a topic and subscriber for it who want to listen updates whenever there are updates on topic.
    To create new topic simply go to AWS Console and follow the direction given on below document
    'https://docs.aws.amazon.com/sns/latest/dg/sns-tutorial-create-topic.html'
    """
    topic_arn = "arn:aws:sns:us-east-1:174397498694:layer-updates"
    sns = boto3.client("sns")
    sns.publish(
        TopicArn=topic_arn,
        Message=msg,
        Subject=sub
    )


def lambda_handler(event, context):
    updated_klayers = get_updated_klayer()
    message = 'Hi, \n\n There is new version available for following kLayer:\n\n'
    for updated_klayer in updated_klayers:
        update_msg = f"KLayer Name: {updated_klayer['LayerName']}\nNew Version ARN: {updated_klayer['latest_klayer_arn']}\n\n"
        message = message + update_msg

    message = message + '\n\n\n\nYou may consider upgrading them\n\n'
    instructions = "Instructions:\nTo create a layer or update with a new version you can add/update list of packages " \
                   "on a csv file at path 'input_files/layers_manager_input.csv' and run script from directory 'utilities/layers_manager.py' " \
                   "on your local machine. It will scan through the all listed layers and will deploy new if required.\n\n\n\n"

    message = message + instructions
    if len(updated_klayers) > 0:
        publish_to_sns('KLayer New Version Available', message)


if __name__ == "__main__":

    lambda_client = boto3.client('lambda')
    file_path = '../input_files/layers_manager_input.csv'
    
    input_df = DB.read_local_csv_to_df(file_path, user_format=True, silent_error=False)
    for index, row in input_df.iterrows():
        create_update_klayer(lambda_client, row['klayer-arn'], row['package'])







