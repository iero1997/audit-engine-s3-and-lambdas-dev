# Global BIF data frame

import os
#import posixpath
import pandas as pd
import boto3
from botocore.exceptions import ClientError

from models.DB import DB
from utilities import utils, args, logs



BIF_COLUMNS = [
    ('archive_basename', str),
    ('ballot_id', str),
    ('file_paths', str),
    ('cvr_file', str),
    ('precinct', str),
    ('party', str),
    ('style_num', str),             # perhaps interally generated style_num
    ('card_code', str),             # barcode style value
    ('pstyle_num', str),            # printed style num
    ('ballot_type_id', str),
    ('sheet0', str),                # '0', '1' ...
    ('is_bmd', str),
    ('style_roi_corrupted', str),
    ('comments', str),
    ('chunk_idx', str),             # optional, used when a single file provides multiple chunks.
]


class BIF:
    name = ''
    df = pd.DataFrame()
    # Bool indicating if the BIF operation are done on Lambda or locally.
    # If set to True, it will try to do BIFInstructions instead of
    # saving changes to local file.
    #running_on_lambda = False

    @classmethod
    def df_without_corrupted_and_bmd(cls) -> pd.DataFrame:
        try:
            return cls.df.loc[(cls.df.style_roi_corrupted != 1)
                              & (cls.df.is_bmd != 1)]
        except AttributeError:
            raise AttributeError("Tried to access 'style_roi_corrupted' and" \
                                 "'is_bmd' columns in BIF but they don't exist")

    @classmethod
    def df_without_corrupted(cls) -> pd.DataFrame:
        try:
            return cls.df.loc[(cls.df.style_roi_corrupted != 1)]
        except AttributeError:
            raise AttributeError("Tried to access 'style_roi_corrupted' in BIF but it doesn't exist")

    @classmethod
    def df_without_bmd(cls) -> pd.DataFrame:
        try:
            return cls.df.loc[cls.df.is_bmd != 1]
        except AttributeError:
            raise AttributeError("Tried to access 'is_bmd' columns in BIF but it doesn't exist")

    @classmethod
    def df_without_nonbmd(cls) -> pd.DataFrame:
        try:
            return cls.df.loc[cls.df.is_bmd == 1]
        except AttributeError:
            raise AttributeError("Tried to access 'is_bmd' columns in BIF but it doesn't exist")

    @classmethod
    def get_ballot_index(cls, ballot_id: str) -> int:
        try:
            return cls.df.loc[cls.df['ballot_id'] == int(ballot_id)].index[0]
        except IndexError:
            return None

    @classmethod
    def set_ballot_id_as_index(cls):
        cls.df.set_index('ballot_id', inplace=True)

    @classmethod
    def set_cell_value_by_ballot_id(cls, ballot_id: str, column: str, value: [int, str],
                       source_name: str = ''):
        bif_idx = cls.get_ballot_index(ballot_id)
        cls.set_cell_value(bif_idx, column=column, value=value, source_name=source_name)

    @classmethod
    def get_cell_value_by_ballot_id(cls, ballot_id: str, column: str,
                       source_name: str = ''):
        bif_idx = cls.get_ballot_index(ballot_id)
        return cls.get_cell_value(bif_idx, column=column)

    @classmethod
    def is_bmd(cls, ballot_id):
        return bool(int(cls.get_cell_value_by_ballot_id(ballot_id, column='is_bmd')) == 1)

    @classmethod
    def set_cell_value(cls, index: str, column: str, value: [int, str],
                       source_name: str = ''):
        """Sets BIF cell value, taking index as a ballot id.
        If 'running_on_lambda' is False, it will edit the local file.
        If 'running_on_lambda' is True, it will write the instruction
        to edit the BIF file after Lambda instances finish.
        :param index: By default it will be linked to the ballot id.
        :param column: Column name to edit.
        :param value: Value to set.
        :param source_name: Name of the archive/BIF. By default it's
        saved in 'BIF.name' when BIF was loaded from the local file.
        If BIF wasn't loaded (happen when we just write BIFInstructions),
        it might be needed to pass the source name.
        """
        if index is None:
            return
        if args.argsdict.get('on_lambda'):
            pass        # we really don't want to do this!
        
            #add_instruction(bif_name=cls.name or source_name, ballot_id=index,
            #                column=column, value=value)
        else:
            try:
                cls.df.at[index, column] = value
            except KeyError as err:
                raise KeyError(f'Key {err} not found in BIF table')

    @classmethod
    def get_cell_value(cls, index: int, column: str):

        value = None
        if index is None:
            return None
        try:
            value = cls.df.at[index, column]
        except KeyError:
            raise KeyError(f'Column {column} not found in BIF table')

        return value

    @classmethod
    def load_bif(cls, bif_pathname: str = None, name = None) -> pd.DataFrame:
        # this function assumes a single bif file, however, normally bif files are
        # stored one per archive. Is this correct??
        # Yes, it opens only one bif file at a time, which may be a chunk.
        
        if not name and bif_pathname:
            name = os.path.basename(bif_pathname)
            
        rootname = os.path.splitext(name)[0]    # use root without extension.    
        cls.name = rootname

        cls.df = DB.load_data(dirname='bif', name=name, format='.csv')
            
        utils.sts(f"BIF {name} loaded. {len(cls.df.index)} records.", 3)


    @classmethod
    def save_bif(cls, argsdict, bif_name: str = '', bif_df: pd.DataFrame = pd.DataFrame()):
        # save either class data df or bif_df, if it is supplied.
         
        if not bif_name:
            bif_name = cls.name
        if bif_df.empty:
            bif_df = cls.df
        
        if cls.df.index.name == 'ballot_id':
            cls.df.reset_index('ballot_id', inplace=True)

        DB.save_data(data_item=bif_df, dirname='bif', name=bif_name, format='.csv')
        # if argsdict['use_s3_results']:
            # job_s3path = argsdict['job_folder_s3path']
            # bif_s3path = f"{job_s3path}/bif/{bif_name}.csv"
            # s3utils.write_df_to_csv_s3path(bif_s3path, bif_df)
        # else:
            # job_path = argsdict['job_folder_path']
            # bif_path = f"{job_path}/bif/{bif_name}.csv"
            # os.makedirs(os.path.dirname(bif_path), exist_ok=True)
            # bif_df.to_csv(bif_path, index=False)


    # 
    # @staticmethod
    # def file_exists(argsdict, file_name, dirname='bif', s3flag=None):
        # return DB.file_exists(file_name, dirname=dirname, s3flag=s3flag)
        # # dirpath = DB.dirpath_from_dirname('bif', s3flag=use_s3_results)
        # # if not use_s3_results:
            # # file_path = os.path.join(dirpath, file_name)
            # # return bool(os.path.isfile(file_path))
        # # else:
            # # s3path = posixpath.join(dirpath, file_name)
            # # return s3utils.does_s3path_exist(s3path)


    @staticmethod
    def get_bif_columns():
        return [c for c, t in BIF_COLUMNS]
        
    @staticmethod
    def is_bif_exist(bif_name: str, bif_path: str = '', bucket: str = '') -> bool:
        if not bif_path:
            bif_path = DB.get_bif_path(bif_name)
        if bucket:
            s3_client = boto3.client('s3')
            try:
                s3_client.head_object(Bucket=bucket, Key=bif_path)
                return True
            except ClientError:
                return False
        else:
            return os.path.isfile(bif_path)


