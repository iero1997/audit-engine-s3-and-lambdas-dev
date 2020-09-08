#import os

import pytest
from aws_lambda import core, ec2_unzip, s3utils


class TestLambda:
    # --- Test convert_file_size() ---
    @pytest.mark.parametrize("byte_size", [0, 9437184, 1000000, 116391936])
    def test_convert_file_size_valid_input(self, byte_size):
        assert core.convert_file_size(byte_size=byte_size)

    @pytest.mark.parametrize("byte_size", [0.0, 1709178.88, 2569011.2, 6983516.16])
    def test_convert_file_size_float_input(self, byte_size):
        assert core.convert_file_size(byte_size=byte_size)

    @pytest.mark.parametrize("byte_size", [None, "1073741824", ""])
    def test_convert_file_size_invali_input(self, byte_size):
        with pytest.raises(Exception):
            assert core.convert_file_size(byte_size=byte_size)

    # --- Test file_exists() ---
    @pytest.mark.parametrize("file_name,bucket_name", [('21ZRSvrppK9QD94PTJdzMNZY', 'audit-engine-test')])
    def test_file_exists_on_a_real_file_in_a_real_s3_bucket(self, file_name, bucket_name):
        assert core.file_exists(file=file_name, check_bucket=bucket_name) is True

    @pytest.mark.parametrize("file_name,bucket_name", [('thereIsNoSuchFile', 'anit_NO_S3_Bucekt')])
    def test_file_exists_on_a_fake_file_and_fake_s3_bucket(self, file_name, bucket_name):
        assert core.file_exists(file=file_name, check_bucket=bucket_name) is False

    # --- Test invoke_lambda() ---
    @pytest.mark.parametrize("dummy_function",
                             ['arn:aws:lambda:us-east-1:504255336307:function:test-dummy'])
    def test_invoke_lambda_on_an_actual_dummy_lambda_function(self, dummy_function):
        assert s3utils.invoke_lambda(function_name=dummy_function) is True

    @pytest.mark.parametrize("fake_function",
                             ['arn:aws:lambda:us-midwest-9:123456789012:function:no_such_function'])
    def test_invoke_lambda_on_a_nonexistent_lambda_function(self, fake_function):
        assert s3utils.invoke_lambda(function_name=fake_function) is False

    # --- Test validate_zip() ---
    # TODO: Add tests here!


# TODO: Write new tests!
class TestEC2Unzip:
    # --- Test get_info() ---
    @pytest.mark.parametrize("bucket,key", [
        ("readybucketone", "test_zip_smaller_than_200MB.zip"),
        ("readybucketone", "test_zip_bigger_than_200MB.zip"),
    ])
    def test_get_info_for_existing_object(self, bucket, key):
        assert ec2_unzip.get_info(bucket=bucket, key=key)

    @pytest.mark.parametrize("bucket,key", [
        ("readybucketone", "earth-chronicles.jpg"),
        ("readybucketone", "massage.txt"),
        ("readybucketone", "0.json"),
        ("readybucketone", "went.gif"),
        ("readybucketone", "nosuch.zip"),
    ])
    def test_get_info_for_non_existing_object(self, bucket, key):
        with pytest.raises(Exception):
            assert ec2_unzip.get_info(bucket=bucket, key=key)

    # --- Test find_all_zips() ---
    @pytest.mark.parametrize("bucket,min_size", [("readybucketone", ec2_unzip.MIN_ZIP_FILE_SIZE)])
    def test_find_all_zips_that_are_bigger_than_200MB(self, bucket, min_size):
        expected = ['test_zip_bigger_than_200MB.zip']
        assert list(ec2_unzip.find_all_zips(bucket=bucket)) == expected

    @pytest.mark.parametrize("bucket,min_size", [("readybucketone", ec2_unzip.MIN_ZIP_FILE_SIZE)])
    def test_find_all_zips_that_are_smaller_than_200MB_but_have_more_than_1000_items(self, bucket, min_size):
        expected = ['less_than_200MB_but_more_than_1000files.zip']
        assert list(ec2_unzip.find_all_zips(bucket=bucket, size_switch=True)) == expected

    # --- Test make_folder_name() ---
    @pytest.mark.parametrize("test_name", ["yet another file name.zip", ])
    def test_make_folder_name(self, test_name):
        expected = "yet\\ another\\ file\\ name"
        assert ec2_unzip.make_folder_name(zip_object=test_name) == expected
