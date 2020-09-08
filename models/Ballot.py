import os
import sys
#import logging
import itertools

#from models.Contest import Contest
from models.DB import DB
from models.BIF import BIF
from utilities import barcode_parser, utils, args, alignment_utils, logs
from utilities.config_d import config_dict
from utilities.images_utils import get_images_from_pdf, get_images_from_pbm, get_images_from_tif, get_images_from_png, read_raw_ess_barcode
from utilities.zip_utils import get_archived_file, get_ballotid, get_precinct, get_party, get_group
from utilities.vendor import dominion_build_effective_style_num


class Ballot:
    """
    Class contains variables and methods related to single ballot.
    Instance variables describe ballot data like its id, byte arrays
    with image file, contests and other. Instance methods help with
    aligning ballot images, reading ballot code ('style_id') and
    updating contest info.
    """

    def __init__(self, 
        argsdict,
        file_paths,
        archive_basename = '',
        ballot_id   = '', 
        vendor      = '', 
        precinct    = '', 
        party       = '', 
        group       = '', 
        extension   = '', 
        ):

        self.ballotdict = {
            # the ballot_state will track the progress of processing a ballot.
            # 1 - file_paths are defined
            # 2 - ballot_id, precinct, party defined from file paths.
            # 3 - source files, like PDF, PNG, or PBM, loaded as bytes to ballot.ballotimgdict['source_files']
            # 4 - images extracted from source files.
            # 5 - images aligned, determinants completed
            # 6 - style_num read from ballot if possible
            # 7 - ballot_type determined as 'normal' or 'barcoded summary'
            # 8 - num_pages determined based on style.
            # 9 - y_timing_vectors calculated for each image.
            # 10 - Pixel Metric Values extracted to marks_df
            # 11 - adaptive thresholding applied to obtain num_marks
            # 12 - votes/ overvotes/ undervotes determined
            #       ballot.total_num_marks updated, 0 if ballot is blank.
            # 13 - cvrcmp disagreement reports    

            'ballot_state': 1,

            # state=1: one or two paths are passed during creation using helper function.
            'archive_basename': archive_basename,
            'file_paths': file_paths,

            # state=2: the ballot_id, precinct, and party can be determined from file_paths
            'ballot_id':    ballot_id   if ballot_id    else get_ballotid(file_paths[0]),
            'precinct':     precinct    if precinct     else get_precinct(argsdict, file_paths[0]),
            'party':        party       if party        else get_party(argsdict, file_paths[0]),
            'group':        group       if group        else get_group(argsdict, file_paths[0]),
            'extension':    extension   if extension    else os.path.splitext(file_paths[0])[1],     # note, extension includes '.'
            'vendor':       vendor      if vendor       else argsdict['vendor'],

            # state=3: after loading the files from source files, we have those source in ballotimgdict
            # it is at this point the ballot structure can be potentially passed for Lambda processing.

            # state=5: after images are loaded and aligned, the determinates are updated.
            'determinants': [],

            # state=6: the style_id and style_num can be read from the ballot.
            'card_code': '',
            'style_num': '',
            'pstyle_num': '',
            'ballot_type_id': '',       # ballot type id is specific to Dominion
            'p1_blank': False,
            'sheet0': 0,        # sheet number, 0-based.

            # state=7: ballot_type either 'BMD' or 'nonBMD'
            'is_bmd': False,

            # state=8: based on style information, the number of pages that need to be processed can be determined
            'num_pages': None,

            # state=9: the y_distortion_vector is determined to deal with stretched images.
            # and the distortion_metric is used to exclude ballots from use in template generation
            # if sufficient images are available.
            # THESE ARE DEPRECATED, USE BELOW
            #'x_timing_vector': [],
            #'y_timing_vector': [],
            #'distortion_metric': None,
            
            # new version of the timing vector
            'timing_marks': [
                {'left_vertical_marks':[], 'right_vertical_marks':[], 'top_marks':[]},     #page0
                {'left_vertical_marks':[], 'right_vertical_marks':[], 'top_marks':[]},     #page1
                ],
                
            # as marks are interpreted from the ballot, the ballot_marks_df is updated.
            # state = 10: pixel metric values analyzed.
            'ballot_marks_df': None,    # this is now in the marks_df.

            # state = 11: adaptive thresholding applied on ballot basis.
            'marginal_threshold': None,
            'definite_threshold': None,

            # state = 12: determine ballot stats.
            'total_num_marks': 0,
            'total_num_writeins': 0,
            'total_undervotes': 0,
            'total_overvotes': 0,

            # state = 13: cmp_cvr results
            'total_disagreements': 0,
            'disagreement_report': '',
            
            # expressvote data, extracted from barcodes
            'ev_precinct_id': 0,
            'ev_logical_style': 0,
            'ev_num_writeins': 0,
            'ev_num_marks': 0,
            'ev_coord_str_list': [],
            
            # ev OCR data: contests (list) list of contest dictionaries containing
            # contest string under `ocr_contestname`
            #and list of selected options under `ocr_names`
            'ev_contests': [],
            
            
        }
        self.ballotimgdict = {

            # state=3 files loaded as bytes to source files, not yet parsed.
            # this is a lod, where each dict entry is 'name':filename, 'bytes_array':the file.
            'source_files': [],

            # state=4 images extracted from source files
            'images': [],
            'backup_images': [],
        }

    def load_source_files(self, archive=None, mode='archive'):
        """ given file paths, load the files into ballot.ballotimgdict['source_files']
            returns False if loading failed.
            mode:
                'archive'   -- loads files identified in ballot instance from archive
                                note that this archive may be located on s3.
                'local'     -- treat filepaths as local paths of extracted files.
                's3'        -- loads files already extracted from zip archives on s3 (DEPRECATED)
            
        """
        if not isinstance(self.ballotdict['file_paths'], list):
            self.ballotdict['file_paths'] = [self.ballotdict['file_paths']]

        for file_path in self.ballotdict['file_paths']:
            if mode == 'archive':
                # this creates dict of 'name': (name), 'bytes_array': (the file)
                #if file_path.endswith('.tif'):
                #    import pdb; pdb.set_trace()
                
                ballot_file = get_archived_file(archive, file_path)
                if not ballot_file:
                    return False
            elif mode == 'local':
                with open(file_path, 'rb') as fh:
                    bytes_array = fh.read()
                ballot_file = {'name': file_path, 'bytes_array': bytes_array}
            else:
                utils.exception_report(f"Invalid mode:{mode} in load_source_files()")
                sys.exit(1)
                
                
            self.ballotimgdict['source_files'].append(ballot_file)
        return True

    '''
    def is_ballot_BMD_type(self):

        vendor = args.argsdict.get('vendor', 'ES&S')
        if vendor == 'ES&S':
            expressvote_ballot_threshold = config_dict['EXPRESSVOTE_BALLOT_FILESIZE_THRESHOLD']
            """ typically expressvote BMD ballots are smaller than conventional ballots,
                about 16K while standard hand-marked paper ballots are larger, at least 34K.
            """
            try:
                filesize = len(self.ballotimgdict['source_files'][0]['bytes_array'])
            except:
                return False
            
            return filesize < expressvote_ballot_threshold
            
        else:
            return False
    '''
    def get_ballot_images(self):
        """
        Processes files already read as dict of name, bytes_array
        Skips over the step of placing in source.
        """

        self.ballotimgdict['images'] = []
        extension = self.ballotdict['extension']
        utils.sts(f"Converting images from {extension} data...", 3, end='')

        for filedict in self.ballotimgdict['source_files']:
            if extension == '.pdf':
                images = get_images_from_pdf(filedict)
            elif extension == '.pbm':
                images = get_images_from_pbm(filedict)
            elif extension == '.tif':
                images = get_images_from_tif(filedict)
            elif extension == '.png':
                images = get_images_from_png(filedict)
            else:
                utils.exception_report(f"get_ballot_images(): 'extension':{extension} not recognized.")
                sys.exit(1)
            self.ballotimgdict['images'].extend(images)
        utils.sts(f"{len(self.ballotimgdict['images'])} image(s) converted.", 3)
            

    def align_images(self):
        """ Aligns and crops ballot images.
            Also updates determinants.
        
            card_code attribute also updated for 'Dominion' vendor
        
        """
        error = False
        vendor = self.ballotdict['vendor']
        extension = self.ballotdict['extension']
        ballot_id = self.ballotdict['ballot_id']
        
        utils.sts(f"Aligning {vendor} ballots, ballot_id:{ballot_id}...", 3, end='')
        
        if vendor == 'ES&S':
            """ ES&S has two image formats:
                1. multipage PDF with up to two pages. Images are already correctly sequenced and oriented but not aligned.
                2. single-page PBM, with one PBM page per file. Two files are opened and loaded at this point
            """
            if extension == '.pdf':
                self.ballotimgdict['images'], self.ballotdict['determinants'] = alignment_utils.ess_align_images(
                    self.ballotimgdict['images'])
            elif extension == '.pbm':
                self.ballotimgdict['images'] = alignment_utils.dane2016_alignment(self.ballotimgdict['images'])
            else:
                error = True
        elif vendor == 'Dominion':
            """ Dominion uses two types of image format.
                1. Combined image with front, back, and "auditmark" (graphical CVR details embedded in the image) as one long page
                2. Separate pages using multi-page TIF format.
                3. extract timing marks and card_code
            """
            if extension == '.tif':
                if len(self.ballotimgdict['images']) > 1:
                    # this is the multi-page TIF format. Align each page separately
                    # Used by more recent versions of Dominion system
                    # We do not need to align page 3 (index 2) as this is the audit mark.
                    for index in range(2):
                        #, image in enumerate(self.ballotimgdict['images']):
                        img, _, card_code = alignment_utils.dominion_alignment(self.ballotimgdict['images'][index], ballot_id)
                        
                        if img is not None:
                            self.ballotimgdict['images'][index] = img[0]
                        self.ballotdict['card_code'] = card_code                #if there was an error, card_code could be None.
                        #elif index:
                        #    del self.ballotimgdict['images'][index]
                elif len(self.ballotimgdict['images']) == 1:
                    # this is the combined format, which returns a list of images.
                    imgs, _, card_code = alignment_utils.dominion_alignment(self.ballotimgdict['images'][0], ballot_id)
                    if imgs is not None:
                        self.ballotimgdict['images'] = imgs
                    self.ballotdict['card_code'] = card_code                #if there was an error, card_code could be None.
            elif extension == '.png':
                # this is the combined format, which returns a list of images.
                imgs, _, card_code = alignment_utils.dominion_alignment(self.ballotimgdict['images'][0], ballot_id)
                if imgs is not None:
                    self.ballotimgdict['images'] = imgs
                self.ballotdict['card_code'] = card_code                #if there was an error, card_code could be None.
            else:
                error = True
        else:
            error = True
        if error:
            utils.exception_report(f"Ballot.align_images {vendor} not supported with file extension {extension}")

    def get_timing_marks(self):
        """ get timing marks and update ballot instance.
            updates timing_marks to None if there is a show-stopper error in getting the timing marks.
            for gentemplate() phase of operation, skip this ballot and withhold from template.
            In genrois() maybe fixed timing marks can be used.
        """
    
        self.ballotdict['timing_marks'] = alignment_utils.generic_get_timing_marks(self.ballotimgdict['images'], self.ballotdict['ballot_id'])
        if not self.ballotdict['timing_marks'][1]:
            # second page is apparently blank.
            self.ballotdict['p1_blank'] = True
         
    def sum_determinants(self, idx):
        """Returns sum of 'determinants'."""
        if self.ballotdict['determinants'][idx]:
            return sum(self.ballotdict['determinants'][idx])
        return 0

    def load_backup_images(self, remove_backup=False):
        """
        Loads a backup image if processing original image made it corrupted.
        """
        self.ballotimgdict['images'] = self.ballotimgdict['backup_images'].copy()
        if remove_backup:
            self.ballotimgdict['backup_images'][:] = (None, None)

    def update_style_hex_code(self):
        """Reads left side bar as bool and translates it into a hex code."""

        style_num = Ballot.read_style_from_image(self.ballotimgdict['images'][0])
        if style_num:
            self.ballotdict['style_num'] = style_num
            return True
        return False

    @staticmethod
    def get_longest_key(data: dict, padding: int = 5):
        """
        Calculates the value of right alignment based on the length of the
        longest key from a dictionary (data) plus padding.
        :param data: a dictionary with Ballot data
        :param padding: the distance between the key and the value e.g.
        key:[  padding   ] value
        """
        return max([len(key) for key in data.keys()]) + padding

    @staticmethod
    def slice_dictionary(dict_to_slice: dict, *, slice_size: int):
        """
        Cuts a dictionary into another dictionary with the number of keys
        equal to the slice size.
        :param dict_to_slice: ballot data dictionary
        :param slice_size: size of a new dictionary i.e. number of its keys
        """
        return dict(itertools.islice(dict_to_slice.items(), slice_size))

    @staticmethod
    def print_values(ballot_data: dict, *,
                     indent_value=None,
                     slice_size: int = 11,
                     extra_padding: int = 0):
        """
        Displays formatted values from the ballot data dictionary. The default
        values are set for verbose level one.
        :param ballot_data: Ballot data dictionary
        :param indent_value: the indent corresponds to the level of verbosity
        :param slice_size: how many are to be taken from the Ballot dictionary
        :param extra_padding: used to align printed values for levels 2 & 3
        """
        data_slice = Ballot.slice_dictionary(ballot_data, slice_size=slice_size)
        longest_key = Ballot.get_longest_key(data_slice)
        for key, value in data_slice.items():
            delimiter = f"{key}:"
            indent = "\t" * indent_value if indent_value else ""
            print(f"{indent}{delimiter:{longest_key + extra_padding}}{value}")

    @staticmethod
    def show_info(ballot_data, *, verbose_level: int = 1):
        if verbose_level == 1:
            Ballot.print_values(ballot_data)

        if verbose_level == 2:
            Ballot.print_values(ballot_data, slice_size=11, extra_padding=9)
            for contest in ballot_data['contests']:
                Ballot.print_values(contest, indent_value=1, slice_size=6)

        if verbose_level == 3:
            Ballot.print_values(ballot_data, slice_size=11, extra_padding=14)
            for contest in ballot_data['contests']:
                Ballot.print_values(contest, indent_value=1, slice_size=6, extra_padding=5)
                for option in contest['options']:
                    Ballot.print_values(option, indent_value=2, slice_size=5, extra_padding=1)
        print("-" * 79)

    def display_ballot(self, save=False):
        """
        Prints in CLI info about ballot. Uses 'verbose' as an argument
        from the config file to display levels of ballot data.
        1 = base ballot data,
        2 = base ballot data and contest data,
        3 = base ballot data, contest data and it's options.
        Passed flag 'save' indicates if the results should be saved to a file.
        """
        if config_dict['VERBOSE'] is None or config_dict['VERBOSE'] == 1:
            Ballot.show_info(self.ballotdict, verbose_level=1)
        if config_dict['VERBOSE'] == 2:
            Ballot.show_info(self.ballotdict, verbose_level=2)
        if config_dict['VERBOSE'] == 3:
            Ballot.show_info(self.ballotdict, verbose_level=3)
        if save:
            self.save_ballot(self.ballotdict)

    def save_ballot(self):
        """
        Saves ballot data to JSON file. It coverts ballot attributes
        to a dictionary on its own with 'get_ballot_data' helper or
        use passed 'data' dictionary.
        """
        
        DB.save_data(
            data_item=self.ballotdict, 
            dirname='results', 
            name=self.ballotdict['ballot_id']+'.json', 
            subdir=self.ballotdict['precinct']
            )
        
        # file_name = self.ballotdict['ballot_id']
        # file_sub_dir = '/'.join(list(filter(None, [
            # self.ballotdict['precinct'],
            # ballot_type,
            # file_name + '.json'
        # ])))
        # file_path = config_dict['RESULTS_PATH'] + file_sub_dir

        # DB.save_ballot(**{
            # 'data': self.ballotdict,
            # 'file_path': file_path,
        # })

    def save_ballot_images(self):
        """Method to save ballot as an image (JPG) file.
            This saves them by precinct rather than by style.
        """
            
        DB.save_data_list(
            data_list   = self.ballotimgdict['images'],
            dirname     = 'styles',
            name        = self.ballotdict['ballot_id'],
            format      = '.png', 
            subdir      = self.ballotdict['precinct']
            )

    def save_ballot_pdf(self):
        """Extracts ballot pdf file to be able to view it in the web browser.
            This appears to be unused.
        
        """
        precinct    = self.ballotdict['precinct']
        ballot_id   = self.ballotdict['ballot_id']
        pdf_file    = self.ballotimgdict['pdf_file']

        DB.save_data(
            data_item   = pdf_file.get('bytes_array'), 
            dirname     = 'disagreements', 
            name        = f'{ballot_id}.pdf', 
            format      = '.pdf', 
            subdir      = precinct
            )
        
        

    def load_data_json(self, json_data):
        """ This seems stupid! """
    
        self.ballotdict = json_data
        '''
        """Loads ballot data from 'json_data' like object."""
        self.ballot_id = json_data['BallotID']
        self.style_id = json_data['Style']
        self.precinct = json_data['Precinct']
        self.ballot_type = json_data['BallotType']
        self.previous_encounters = json_data['PreviousEncounters']
        self.marks_detected = json_data['MarksDetected']
        self.write_ins_marked = json_data['WriteInsMarked']
        self.write_ins_completed = json_data['WriteInsCompleted']
        self.undervotes = json_data['Undervotes']
        self.overvotes = json_data['Overvotes']
        self.disagreements = json_data['Disagreements']
        self.contests = []

        for contest_json in json_data['Contests']:
            contest_name = contest_json['BallotContestName']
            if self.precinct and self.precinct in Ballot.aliases \
                    and contest_name in Ballot.aliases[self.precinct]:
                contest_name = Ballot.aliases[self.precinct][contest_name]
            elif contest_name in Ballot.aliases['all']:
                contest_name = Ballot.aliases['all'][contest_name]
            else:
                contest_name = contest_json['ContestName']

            contest = Contest(contest_name)
            contest.ballot_contest_name = contest_json['BallotContestName']
            contest.vote_for = contest_json['VoteFor']
            contest.question = contest_json['Question']
            contest.selections = contest_json['Selections']
            contest.contest_ballot_status = contest_json['ContestBallotStatus']
            contest.contest_cvr_status = contest_json['ContestCVRStatus']
            contest.contest_validation = contest_json['ContestValidation']
            contest.options = []

            for option_json in contest_json['Options']:
                option = Option(option_json['OptionName'])
                option.has_indication = option_json['HasIndication']
                option.write_in_text_detected = option_json['WriteInTextDetected']
                option.mark_metric_value = option_json['MarkMetricValue']
                option.number_votes = option_json['NumberVotes']
                option.write_in_text = option_json['WriteInText']
                contest.options.append(option)
            self.contests.append(contest)
        '''

    def is_BMD_per_bif(self, argsdict):

        if not 'ballot_id' in BIF.df.columns.tolist():
            BIF.df = BIF.df.reset_index()
        try:
            is_bmd = BIF.df.loc[BIF.df['ballot_id']==self.ballotdict['ballot_id']]['is_bmd'].any()
        except KeyError:
            import pdb; pdb.set_trace()

        return is_bmd

    def read_style_num_from_barcode(self, argsdict):
        """
        if ballot.style_num is defined, then use it, otherwise:
        given np.array of image, read ES&S barcode and decode it.
        return style_num as str if successful else None
        typical usage:
        style_num = read_style_from_image(image)
            may return None if there is an underlying error.
        """
        
        logs.sts("Reading style_num from ballot barcode...", 3)
        ballot_id = self.ballotdict['ballot_id']

    
        ballot_style_overrides_dict = args.get_ballot_style_overrides(argsdict)

        if self.ballotdict['vendor'] == 'Dominion':
            if self.ballotdict['card_code'] is None:
                # This situation exists if there was a problem converting the barcode during alignment.
                
                self.ballotdict['style_num'] = None
            elif argsdict['conv_card_code_to_style_num']:
                #attempt to convert card_code to the official style_num which should match CVR style field.
                # if ballot_type_id or card_code cannote be read, then this may return None
                self.ballotdict['style_num'], _ = dominion_build_effective_style_num(argsdict, self.ballotdict['card_code'])
            else:
                self.ballotdict['style_num'] = self.ballotdict['card_code']
                
            if self.ballotdict['style_num'] is None:
                utils.exception_report(f"### EXCEPTION: card_code not read from ballot:{ballot_id}. ")
                return None
                
        elif self.ballotdict['vendor'] == 'ES&S':
            card_code = read_raw_ess_barcode(self.ballotimgdict['images'][0], ballot_id)
            self.ballotdict['card_code'] = style_num = card_code
            
            from utilities.bif_utils import read_pstyle_from_image_if_specd
            self.ballotdict['pstyle_num'] = read_pstyle_from_image_if_specd(argsdict, self.ballotimgdict['images'][0])
            
            # style num must be a string
            if argsdict['conv_card_code_to_style_num']:
                # converting the card_code to the style number is important to link it to the
                # style number as used on CVR. If no CVR is used, or if we are not attempting to link them
                # then using the card_code directly occurs when 'conv_card_code_to_style_num' is False
                cc_style_num = str(barcode_parser.get_parsed_barcode(card_code, ballot_id, self.ballotdict['precinct']))
                self.ballotdict['ballot_type_id'] = cc_style_num
                
            if argsdict['use_pstyle_as_style_num'] and self.ballotdict['pstyle_num']:
                self.ballotdict['style_num'] = self.ballotdict['pstyle_num']
            elif self.ballotdict['ballot_type_id']:
                self.ballotdict['style_num'] = self.ballotdict['ballot_type_id']
            else:
                self.ballotdict['style_num'] = card_code

        if not self.ballotdict['style_num'] and ballot_style_overrides_dict:
            if ballot_id in ballot_style_overrides_dict:
                return ballot_style_overrides_dict[ballot_id]

        else:
            style_num = self.ballotdict['style_num']
        return style_num
        
