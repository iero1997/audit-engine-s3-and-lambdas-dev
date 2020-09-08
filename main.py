#----------------------------------------------------------
"""
    AuditEngine Compute Service -- overall description

    This code implements a back-end compute service for the AuditEngine.org
    service. This compute service can be run in local machine but ultimate
    target is EC2 instance due to the extended time periods required.

    This service processes ballot image archives in the form of ZIP files 
    and ultimately, creates an independent tabulation of the results of every
    contest in the election.

    The compute service may maintain files during an invocation in local memory,
    but otherwise, all data is read from and written to S3. To maintain highest
    efficiency and lowest cose, S3 data, EC2, and Lambda functions all in the same 
    region. Due to the proximity of most of the consequential elections in the U.S.
    we will use us-east-1 as our aws region. 

    compute sevice uses two buckets:
    
    bucket: us-east-1-audit-engine-election-data 
        region: us-east-1
        attributes: 
                this bucket should be WORM -- write once, read many and have "write-lock"
                The compute service does not write to this bucket, but user uploads will
                ultimately be written to this bucket. Data can be public in this bucket.
        purpose: Used for all election data derived from election officials, such as:
                BIA - ballot image archives   -- zip archives (required)
                CVR - cast-vote records files -- can be .xlsx, .csv, or zipped JSON or XML
                                            (optional)
                any other files which vary from district to district, but may include:
                    voted-nonvoted file -- lists voters who voted and did not vote
                    summary of results  -- high level file describing votes cast for each margin.
                    etc.
                Note: we have no control over the naming conventions of these files and so we
                    will need to tag them according to their type, esp. the BIA and CVR files.
        organization: each election will have a separate prefix where all files will be stored.
                The prefix has the following structure:
                    CC/ST/election_name/
                        CC -- two digit country code, upper case, such as 'US'
                        ST -- two digit state (or region) code, upper case, such as 'CA'
                        election name is structured as: ST_District_Name_YYYY-Type where:
                            ST -- two digit state code, upper case.
                            District_Name -- full county name or "Statewide", like "San_Francisco"
                            Type -- type code, like Pri - Primary, Gen - General, Spc - Special
                            
    bucket: us-east-1-audit-engine-election-data-private
        Same as above but not visible to the public.

    bucket: us-east-1-audit-engine-jobs
        region: us-east-1
        attributes: not public
        purpose: This bucket is used for user-established and working files. 
        organization: Detailed organization is provided below. 
                Primary prefix is jobname, similar to election name but can have additional string to 
                differentiate different jobs using the same election data. The name is 
                arbitrary but should be similar to election data name.
                
    JOB FILES
        Job files are of two types: config files, and working data files. When running in local mode
            these files are located in folders included in the repo.
            
        config files
            JOB settings file: csv format in name,value format provides settings for specific runs.
                local mode: in input_files/, with names like JOB_<electiondesignator><run>.csv
                    for example, JOB_FL_Collier_2020_Pri-01.csv
                website: in {job_s3path}/config/
                    this file can be initialized either by uploading 
                    or by using pre-canned settings that are related to the vendor and county.
                    This file can be then edited online or by re-uploading a new version.
                    Final settings can be exported in the export function.
            EIF - Election Informaiton File, .csv format which provides ballot text for each contest.
                local mode: in EIFs/, with names like EIF_<electiondesignator>.csv
                website: in {job_s3path}/config/
            BOF - Ballot Options File. This is an optional file only used when ballot options differ
                significantly from the official options.
                local mode: in EIFs/, with names like BOF_<electiondesignator>.csv
                website: in {job_s3path}/config/
            Manual_Styles_to_Contests_table.csv -- provides list of contests in each style 
                if this information is not available in CVR, and if it is needed to understand the ballots.
                local mode: in EIFs/, with names like STC_<electiondesignator>.csv
                website: in {job_s3path}/config/
            NOTE: Prior to launching lambdas, these files are copied to s3 folder {job_s3path}/config/
               
                
        working files
            bif - ballot information file(s), provides a CSV table of all ballots and information about each one.
                These files can be built from CVR in only a few seconds, if sufficient information is provided, or they 
                can be built by examining every ballot, which requires the use of lamabdas.
                bif_chunks/ - in this folder, chunks of BIF table are first placed by lambdas if 'genbif_from_ballots'
                    operation is performed. If built by scanning all ballots, then files of the format: 
                    <archive_root>_bif_chunk_NNNN.csv are created in this folder. These are not used by any other process,
                    but only to create the combined bif files, one per archive.
                bif/ - after completing the extraction from ballots or CVR files, then there is one bif file for each
                    archive, with name of: {archive_root}_bif.csv
                align_errors/ - in this folder will be a separate folder for each ballot that failed to align or card_code 
                    not successfully extracted. This will only be built in this phase if using 'genbif_from_ballots'
                
            styles - for each ballot style, a master ballot is derived using image processing to improve the image
                template_tasks/ - folder where tasklists are generated prior to generating templates. 
                    Each tasklist provides information about the ballots that comprise each style, and one tasklist
                    is sent to a single Lambda. These tasklists are csv files in BIF format.
                    Each lambda may complete three steps, if enabled:
                        1. combine images (usually 50) from images archives to create a single template image.
                            in styles/{style_num}/
                        2. perform image analysis and OCR text on each ballot to create rois_list_{style_num}.csv
                            in styles/ with detailed images extracted in 
                        3. map the rois to contests, creating the rois_map.csv

                rois_list.csv -- this list is 
                rois - for each ballot style, rois (regions of interest) are defined.
                roismap.csv -- this datatable provides information of the x,y location of each target on the ballot for each style
                ...redline.png -- template images with additional boxes and text added to allow human operators to 
                    approve the mapping of contests and options to the ballot images.
                assist/ - style templates which need assistance by operator to add line and boxes to allow segmentation.
                    The above data items are on style basis, and a single lambda may be used to generate each style.
                    The roismap can be combined into a single csv table.
                map_report.txt -- this provides a report of the mapping and any mapping failures.
                    
            marks 
                marks_tasks - prior to extracting the vote and generating the marks data tables, this folder provides
                    task lists which are chunks of BIF tables. These task lists are used for both genmarks and cmpcvr.
                    The bif table segments are sorted by CVR links so the cmpcvr step need not load the entire CVR.
                    (Note that it may be desired to organize the marks_tasks to correspond to batches as scanned and stored,
                    so that an individual batch can be hand-tallied and compared to the audit result. Not yet supported)
                marks_chunks - the extractvote function produces the results into the marks_chunks folder (formerly 'results')
                    when lambdas are run, each processes a subset of perhaps 200 ballots and
                    produces an {archive_root}_marks_chunk_NN.csv file for each tasklist.
                marks
                    this folder contains files that are combined marks chunks
                    into a single {archive_root}_marks.csv for each archive.
                    
            cmpcvr - if a cvr is available with a record for each ballot, it can be compared with 
                    the result of the auditing system. This process can be delegated to lambdas to save time.
                    This function uses the marks_tasks/ and marks_chunks/ from the marks phase, and
                    processes one chunk at a time. The marks_tasks are sorted by CVR file to reduce the size of the
                    cvr file that need be loaded at one time to perform the comparison.
                cmpcvr_chunks -
                    the comparison produces an <archive_root>_cmpcvr_chunk_NN.csv file for each comparison chunk
                    These can be combined into a single table for each archive at the end.
                    
            reports - final reports of the independent evaluation of the ballots.
                To produce the reports, each marks_chunk can be separately evaluated to produce a subtotal for
                    each contest over that chunk, and then this can be easily checked against each chunk.
                chunk_report.csv -- this table provides the totals for each option of each contest where each record
                    provides the totals for one chunk.
                The final totals are the sum of the columns in the chunk_report.csv.  
            
            logs   - logs from each lambda which are then combined into combined log files.
                    includes exception report files and map_report files.
                logfile.txt -- this a combined log file including every phase.
                exception_report.txt -- this is a combined exception report 
    
    """


import sys


#from aws_lambda.core import update_archives, test_ec2_task_server, upload_ec2_scripts
from aws_lambda.lambda_updater import update_lambda
from utilities.html_utils import generate_cmpcvr_report
from utilities.styles_from_cvr_converter import convert_cvr_to_styles
from utilities.genrois import genrois
from utilities.maprois import maprois
from utilities.bif_utils import genbif_from_cvr, genbif_from_ballots, create_bif_report, save_failing_ballots, \
    reprocess_failing_ballots
from utilities.gentemplates import build_template_tasklists, gentemplates_by_tasklists, post_gentemplate_cleanup
from utilities.extract_utils import genreport, plotmetrics, evalmarks, check_extraction
from utilities.cmpcvr import cmpcvr_by_tasklists
from utilities.votes_extractor import extractvote_by_tasklists, build_extraction_tasks
from utilities.style_utils import get_manual_styles_to_contests

from utilities import utils, web_scraper, self_test, args, logs
from models.DB import DB
import pprint


def main():
    utils.show_logo()
    print(  f"\n\n{'=' * 50}")

    argsdict = args.get_args()          # parses input_file as specifed in CLI using arg_specs.csv
    args.argsdict = argsdict
    
    print("argsdict:")
    print(pprint.pformat(argsdict))

    print(  f"\n\n{'=' * 50}")

    if (argsdict.get('self_test')):
        self_test.self_test(argsdict)


    """ The paths of archives is normalized to allow the archives to be either local or on s3.
        'archives_folder_path' -- path to folder on local system.
        'archives_folder_s3path' -- s3path to folder on s3
        'source' list are basenames, without path, but including extension.
        
    """


    # if argsdict['archives_folder_path'] and not argsdict['source']:
        # # create a list of source archives in the source folder.
        # srcdict = {}
        # dirdict = utils.get_dirdict(argsdict['archives_folder_path'], '.zip')
        # for name, path in dirdict.items():

            # if (name in argsdict['exclude_archives'] or
                # argsdict['include_archives'] and not name in argsdict['include_archives']):
                # continue
            # srcdict[name] = path

        # argsdict['source'] = list(srcdict.values())
        # argsdict['srcdict'] = srcdict
        # utils.sts(f"input directive 'source' resolved to: {argsdict['source']}", 3)

    op = argsdict.get('op', 'all').lower()
    
    DB.set_DB_mode()
    
    """ =======================================================================
        PRIMARY API ENTRY POINTS
        
        Each one of the following relies on a job file which provides the settings
        as parameter,value in csv file, where comments are allowed preceded by #.
        Thus the api must provide 
            -i path             location of settings file -- could be file on s3.
            -op operation       string like 'genbif_from_cvr'
            
        Each function produces:
            log.txt                 appends extensive status reports.
            exception_report.txt    appends each exception encountered. 
                                        exceptions to processing and not python exceptions, per se.
                                        
            as well as other files, noted below.
            
        Initial implementation will include one major intry point with operation selection as follows:
            'genbif_from_cvr'           (Fast)
            'genbif_from_ballots'       (Slow)
            'create_bif_report'         (Fast)
            'gentemplates'              (Slow)
            'genmaprois'                (Somewhat slow)
            'extractvote'               (Very slow)
            'genreport'                 (fast)
            'cmpcvr_and_report'         (somewhat slow)
            'get_status'                (fast) - return status of slow functions.    
                op='get_status' ref='function'
                    where function = one of 'genbif_from_ballots', 'gentemplates', 'genmaprois', 'extractvote'
            
        In the functions below, argsdict is established from the settings file.
        
    """

    if op == 'copy_config_files_to_s3':
        """ This function will copy local config files in EIFs to s3, to simulate
            interaction with the frontend website, which will upload and place files
            s3://us-east-1-audit-engine-jobs/{job_name}/config/ 
            
            Files to be placed there:
                JOB settings file
                EIF file
                BOF file
                manual_styles_to_contests
                style_lookup_table
                
            In local mode running these are in either EIFs/ or input_files/ in repo folder.
                
        """
        DB.upload_file_dirname('config', argsdict['eif'])
        DB.upload_file_dirname('config', argsdict['bof'])
        DB.upload_file_dirname('config', argsdict['manual_styles_to_contests_filename'])
        DB.upload_file_dirname('config', argsdict['style_lookup_table_filename'])
        DB.upload_file_dirname('config', argsdict['input'], local_dirname='input_files')
            
        
        
        
    elif op == 'precheck_job_files':
        """ This function simply does a precheck of the job files that exist
            in the config folder for this job on s3.
        """
        pass
    
    
    
    
    
    
    elif op == 'genbif_from_cvr':
        """ 
        If CVR file(s) are provided with style information included, 
        this operation builds "ballot information file" BIF data by reviewing the CVR
        May also use path information of ballots in archives for precincts, groups, party.
        For Dominion, scan CVR JSON chunks and fill in info about ballots.
        Creates one .csv file for each archive in folder bif.
        This is a relatively fast operation that can be completed typically in a matter of seconds
        Result:
            BIF data file ready for BIF report.
            log
            exception report
        """
        genbif_from_cvr(argsdict)


    elif op == 'genbif_from_ballots':
        """ 
        If no CVR is available, we must scan the ballots to generate the bif.
        Each ballot is reviewed and style information is read from the ballots.
        May also use path information of ballots in archives for precincts, groups, party.
        This can be done by lambdas and should complete within minutes but
        typically will not complete during a single REST post/response.
        Result:
            BIF ready to produce BIF report.
            separate folder for each failing ballot to allow investigation.
            log
            exception report
        """
        genbif_from_ballots(argsdict)
        
    # elif op == 'get_status':
        # """ This function provides status operation in terms of % complete.
        # """
        # if ref == 'genbif_from_ballots':
            # return get_status_genbif_from_ballots(argsdict)
        # elif ref == 'gentemplates':
            # return get_status_gentemplates(argsdict)
        # elif ref == 'genmaprois':
            # return get_status_genmaprois(argsdict)
        # elif ref == 'extractvote':
            # return get_status_extractvote(argsdict)
        # else:
            # utils.sts(f"ref '{ref}' not supported by op=get_status", 3)

    elif op == 'create_bif_report':
        """ 
        as a result of validate_bifs or genbif_from_ballots, this report is 
        generated, or it can be generated once the BIF is built. Report provides:
            Number of Ballot Archives
            Total number of BIF records
            Unique ballot_ids
            Duplicate ballot_ids
            Number of CVR files
            Number of precincts
            Number of parties
            Number of style_nums
            Number of card_codes
            Number of ballots w/o card_codes
            Number of BMD ballots
            Number of corrupted ballots (could not be read)
            Number of different sheets
            Number of each sheet
        
        This operation completes quickly and currently produces a text report to console.
        Can provide alternative data output as JSON or HTML through command line switch.
            
        """
        create_bif_report(argsdict)
        
    elif op == 'build_template_tasklists':
        """ 
        Scan bifs and generate template tasklists, with one tasklist csv file per style.
        tasklist is the same format as bif but should not be updated with any information.
        This generally not used as REST entry point.
        """
        build_template_tasklists(argsdict)

    elif op == 'gentemplates':
        """ this function requires that BIF data is available. Used as REST entry point.
            1. generates template tasklists
            2. contructs templates by combining usually 50 ballots to improve resolution.
            Result is a set of raw templates (PNG files), one for each style,
            and possibly also checkpoint images including the components (up to 50).
            
            This function takes significant time, of more than a minute per style. 
            However, this can be delegated to lambdas and may be completed 
            in (# styles/1000) * time per style, but still too long for single REST POST.
            For Dane County, WI, with 191 styles, it still takes at least a minute.
            If all 10,000 styles are used in SF, time is 10 minutes.
            
            Log file updated.
            Report generated of result.
            PNG files for review of each style.
        """
        if argsdict['include_gentemplate_tasks']:    # sub tasks in gentemplate action - generate base templates
            build_template_tasklists(argsdict)
            
        gentemplates_by_tasklists(argsdict)

    elif op == 'gentemplates_only':
        """ This function used for debugging only when tasklists are already generated.
            Tasklists take only seconds to complete now.
            NOT USED IN REST API
        """
        gentemplates_by_tasklists(argsdict)

    elif op == 'genrois':
        """
        After templates are generated, each style is image-analyzed and then OCR'd.
        Result is set of PNG images providing regions of interest (ROIs) determined.
        Style templates must be generated at this point to allow further analysis and generation of rois
        The json list of rois and the image for each result.
        
        Result:
            Creates a report of rois generated
            PNG image files with graphic outlines of rois that can be reviewed by the user.
        """
        genrois(argsdict)

    elif op == 'maprois':
        """
        Once Rois are generated, they can be fairly quickly mapped to contests and options based on information
        in the EIF - Election Information File. This operates at the rate of several seconds per style.
        Result is 
            PNG "redlines" showing the mapping of contests and options to each style.
            Map report, providing detail of where mapping may have gotten off track.
            Log.
        """
        maprois(argsdict)

    elif op == 'genmaprois':
        """ 
        Major REST entry point.
        This the most typical operation once templates have been generated, which may take
        time and use compute resources. May need to be done repetitively while operator makes
        changes to settings file. Operator must review the map report and redlines.
        Once review is completed, then extraction can commence.
        Can break this up for processing by lambdas but it is so fast now that it may not be necessary.
        Result is:
            PNG images showing ROIS from genrois
            PNG redlines showing the correspondence of contests and options for each style.
            failures copied to assist folder
            Map Report
            Log
        """
    
        genrois(argsdict)
        maprois(argsdict)

    elif op == 'get_assist_requests':
        """ 
        After genmaprois is completed, some styles may need manual assistance by human operator.
        This is used in graphic-mode dominant rois generation rather than OCR dominant generation.
        Front end first requests assist requests, and the response is
            list of ballot_ids which needs assistance.
            path to each template file
            path to existing json file for that template.
            
        NOTE this is a new function which is not implemented yet.
        """
        pass
        
    elif op == 'write_new_assist_annotation':
        """ The front end will implement functionality like is implemented by 
            tools/template_edit.py, to allow the user to add rectangular regions,
            horizontal and vertical lines, to the image.
            Then, this writes a new JSON annodation file.
            Maybe this does not need to be provided if frontend can write to s3 directly.
        
        NOTE this is a new function which is not implemented yet, but is implemented
            for CLI operation as 'template_edit' using tools/template_edit.py
        """
        pass
        
    elif op == 'build_extraction_tasks':
        """ Scan bifs and generate extraction tasklists, with an appropriate number of ballots for each lambda.
            tasklist is the same format as bif and should not be updated with any information by lambda.
            This function completes rapidly and thus is combined with actual extraction.
        """
        build_extraction_tasks(argsdict)

    elif op == 'extractvote_only':
        """ with extraction tasklists already built, go through all the ballots in the 
            archives and extract the marks into single csv data table for each tasklist, 
            and then combine into a single csv file for each archive.
            Each tasklist is delegated to a separate lambda process.
            Each lambda can take up to 15 minutes to process one tasklist. Total time of this
            process is less than (# ballots / 200,000) * 15 minutes.
            So for a county like SF, with 500K ballots, upper limit is about 35 minutes.
            LA, the largest county in the US has about 6 million ballots, upper limit is 7.5 hours.
        """
        extractvote_by_tasklists(argsdict)
        #extractvote(argsdict)

    elif op == 'extractvote':
        """ Build extraction tasklists and then extract vote 
            Perform both the tasklist generation (fast) and extraction (slow) above.
            This is the normal REST entry point.
            Result is 
                marks_df.csv for each archive.
                Extraction Report
                Log
                Exception Report
        """
        # go through all the ballots in the archives and extract the marks into single json file for each archive
        build_extraction_tasks(argsdict)
        extractvote_by_tasklists(argsdict)

    elif op == 'genreport':
        """
        Once extraction is completed, a report of results can be produced independent of the voting 
        system results, or CVR. Can be compared with high-level election results.
        
        Result:
            summary of the election results per audit system.
            Includes total number of ballots:
                not processed by audit system due to misalignment or other corruption.
                not provided in archives.
            Compares with high-level election result.
            
        """
        genreport(argsdict)

    elif op == 'cmpcvr':
        """ If a CVR is available and the voting system evaluation of each ballot
            is provided, then this function compares the audit system result with
            the voting system cvr and provides a comprehensive result.
            This function processes each marks_df.csv that corresponds to each archive, and
            compares each record with CVR, which is fully combined into one data file by this
            function.
            Result:
                cmpresult_n.csv for each archive n processed.
                This file is not combined to a single report.
        """
        cmpcvr_by_tasklists(argsdict)

    elif op == 'gen_cmpcvr_report':
        """ 
        The result of cmpcvr is on an archive-by-archive basis and compares
        the combined CVR, which is generally not organized by archive, with the 
        marks_df.csv which are organized by archive. Creates a ballot-by-ballot
        comparison result on per-archive basis as csv file. Includes any 
        adjudications in the determination of discrepancies.
        Result:
            comprehensive report of the comparison, as JSON or text.
            JSON discrepancy list reduced to just the discrepancies.
            
        """
        generate_cmpcvr_report(argsdict)
        
    elif op == 'cmpcvr_and_report':
        """
        This is a major REST entry point.
        compares the CVR and creates a report by combining the above two functions.
        """
        cmpcvr_by_tasklists(argsdict)
        generate_cmpcvr_report(argsdict)
       
        
    elif op == 'get_discrepancy_list':
        """ new function for front end. After cmpcvr is completed, a full report is created. 
            This provides just the discrepancies to allow for adjudication in frontend UI,
            and the existing adjudication JSON file.
            This is a new function.
            Result:
                JSON list of discrepancies
                log updated.
            NOTE: THIS IS A NEW FUNCTION
        """
        pass
        
    elif op == 'submit_adjudications':
        """ front end will implement a review of all discrepancies and provides
            a DRE-like entry of votes as determined by review of ballot images
            This is a new function.
            Perhaps front end updates the adjudication file but this function 
            may be better so the action is properly logged.
            Results:
                status
                log updated.
            NOTE: THIS IS A NEW FUNCTION
        """
        pass

    # =============================================================================
    #    Updates the lambdas functions.
    # =============================================================================
    
    elif op == 'update_lambda' or op == 'update_lambdas':

        branch = argsdict.get('update_branch', 's3-and-lambdas-dev')

        """ to run this function, you must first delete the tree 'lambda_deploytment'
            including the folder.
        """
        
        function_name = argsdict.get('lambda_function', 'all')
        if function_name == 'all':
           update_lambda(update_all=True, branch=branch)
        else:
            update_lambda(function_name=function_name, branch=branch)

    # =============================================================================
    #    Additional operations only used for development and CLI operation.
    # =============================================================================
    
    elif op == 'post_gentemplate_cleanup':
        post_gentemplate_cleanup(argsdict)
    
    # elif op == 'combine_bif_chunks':
        # """ used for testing combining bif chunks
        # """
        # utils.combine_dirname_chunks_each_archive(argsdict, dirname='bif')
        
        
    elif op == 'get_manual_styles_to_contests':
    
        logs.sts("Processing manual_styles_to_contests", 3)
        style_to_contests_dol = get_manual_styles_to_contests(argsdict, silent_error=True)
        
        logs.sts(f"style_to_contests_dol:\n {pprint.pformat(style_to_contests_dol)}")

        if style_to_contests_dol:
            DB.save_data(data_item=style_to_contests_dol, dirname='styles', name='CVR_STYLE_TO_CONTESTS_DICT.json')


    elif op == 'web2eif':
        """
        This operation scrapes from a url provided a high-level report of results.
        It was thought at the time that this report would provide unique contest names
        and consistent option names, but even though they were shorter and a bit better
        than the CVR, they also were insufficient for our needs. Thus, althought this
        does provide a basic function, it is not up to date with the current EIF format
        and does not eliminate the need for the EIF and manual editing.
        RESEARCH ONLY.
        """
        web_scraper.run_scraper(url=argsdict['url'])
        sys.exit()

    #elif op == 'tidycvr':
    #    """ This operation converts and ES&S cvr to tidy format
    #    Although it is operational, it was found that the existing ES&S format was
    #    a reasonably consice and useful format and we would work with it.
    #    """
    #    tidy_ess_cvr(argsdict)
    #    sys.exit()

    elif op == 'cvr2styles':
        """
        DEPRECATED. Use validate_bifs or genbif_from_ballots
        This operation preprocesses an ES&S CVR file or multiple Dominion CVR files.
        creates two dicts:
        styles_dict, which provides contest list for each style_num
        ballotid_to_style dict, which provides style_num based on ballotid.
        This currently only works if the CVR has a column providding the style named 'Ballot Style'
        Would need a different approach if no Ballot Style column is provided, such as
            creating a logical style iD, perhaps bitstring of contests, and use that as a logcal style identifier.
            This would not match to any style designator on the ballot.
        Proceses multple CVR files one at a time. (scalable)

        convert_cvr_to_styles function is in styles_from_cvr_converter.py
        for dominion, get_styles_to_contests_dominion is in gentemplate.py
        """
        convert_cvr_to_styles(argsdict)

    elif op == 'gentrm':
        gentemplates_by_tasklists(argsdict)
        genrois(argsdict)
        maprois(argsdict)

    elif op == 'tltrm':
        build_template_tasklists(argsdict)
        gentemplates_by_tasklists(argsdict)
        genrois(argsdict)
        maprois(argsdict)

    elif op == 'alltemplates':
        """
        Perform all the steps to creation of templates
        """
        genbif_from_cvr(argsdict)
        build_template_tasklists(argsdict)
#        convert_cvr_to_styles(argsdict)
        gentemplates_by_tasklists(argsdict)
        genrois(argsdict)
        maprois(argsdict)

    # elif op == 'download_results':
        # # download all results from s3 bucket.
        # s3utils.download_entire_dirname(argsdict, dirname='marks')
        # s3utils.get_and_merge_lambda_logs(argsdict)

    elif op == 'download_gentemplates':
        # download all gentemplates from s3 bucket.
        # NOT UPDATED TO NEW FILE STRUCTURE
        DB.download_entire_dirname(dirname='styles')
        #DB.download_entire_dirname(dirname='styles')

    elif op == 'delete_s3_results':
        # delete all results on s3 bucket.
        DB.delete_s3_results(argsdict)

    elif op == 'merge_results':
        """ merge results into single csv file.
        """
        utils.merge_results()

    elif op == 'check_extraction':
        check_extraction(argsdict)

    elif op == 'extractcmp':
        build_extraction_tasks(argsdict)
        extractvote_by_tasklists(argsdict)
        cmpcvr_by_tasklists(argsdict)
  
    # elif op == 'getlogs':
        # DB.get_and_merge_s3_logs()

    elif op == 'plotmetrics':
        plotmetrics()

    elif op == 'evalmarks':
        evalmarks()

    elif op == 'save_failing_ballots':
        # given list of ballots in inputfile, copy the original ballot image files
        # to (jobname)/styles/(ballot_id) folders
        
        # this function
        #   1. builds single bif table.
        #   2. looks each ballot up.
        #   3. using entry, opens the indicated archive and extracts the original file.
        #   4. saves the file in folder of jobname and ballot_id in styles, see above.
        save_failing_ballots(argsdict)

    elif op == 'reprocess_failing_ballots':
    
        reprocess_failing_ballots(argsdict)


    else:
        print("op value not defined ", op)
        sys.exit()


if __name__ == "__main__":
    main()
