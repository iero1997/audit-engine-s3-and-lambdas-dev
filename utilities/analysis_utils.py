import math
import re
import sys
import statistics

import cv2
import numpy as np
import pandas as pd

from utilities import utils, args, logs
from utilities.vendor import get_layout_params
from utilities.images_utils import expressvote_conversion
from utilities.literal_fuzzy_matching_utils import fuzzy_compare_str, fuzzy_compare_str_to_list
from utilities.alignment_utils import dominion_bmd_conversion

#from utilities.expressvote_style_matcher import ev_get_matched_style, update_expressvote_contests
from models.DB import DB
#from models.Ballot import Ballot


def convert_ev_logical_style_to_style_num(logical_style_num: int) -> int:
    """ ES&S ExpressVote ballots include a "logical style number" in the top barcode.
        it is up to 10 decimal digits long.
        This can be converted to the Ballot Style in the CVR.
        1. convert to binary.
        2. strip lowest 15 bits.
        3. interpret remaining as integer.
    """
    
    logical_style_int = int(logical_style_num)      # make sure it is an integer.
    unknown_val_1 = logical_style_int & 0xFF        # lowest 8 bits appear to provide a separate value.
    unknown_val_2 = (logical_style_int >> 8) & 0xFF # next 8 bits appear to provide a separate value.
                                                    # this appears to be used for party designation.
    
    if not unknown_val_1 == 1 or not unknown_val_2 in [1, 2]:
        # these have always been 1 and so if they are not, then we have not encountered that before.
        string = "### WARNING: convert_ev_logical_style_to_style_num: ev_logical_style unknown_val_1 != 1 or unknown_val_2 not in [1, 2] \n" \
                 "This is a new situation that requires analysis."
        utils.exception_report(string)
    
    style_num = logical_style_int >> 16             # shift right 16 bits
    return style_num
    
assert convert_ev_logical_style_to_style_num(1179905) == 18
assert convert_ev_logical_style_to_style_num(1769729) == 27
assert convert_ev_logical_style_to_style_num(8651009) == 132
assert convert_ev_logical_style_to_style_num(12845313) == 196
assert convert_ev_logical_style_to_style_num(13566209) == 207
assert convert_ev_logical_style_to_style_num(1835265) == 28



def get_votefor_list_from_style_rois_map_df(style_rois_map_df: pd.DataFrame) -> list:
    """ given a dataframe, derive the votefor_list
        which provides the votefor value for each contest on that style
    """
    votefor_list = []
    
    for idx in range(len(style_rois_map_df.index)):
        option = style_rois_map_df.iloc[idx]['option']
        if not option.startswith('#'): continue
        votefor = get_votefor_from_option_field(option)
        votefor_list.append(votefor)
    return votefor_list
    
def sanitize_ev_line(line):
    line = line.upper()
    line = re.sub(r'\s*[{+>]+$', '', line)                  # remove plus sign at the end and intervening spaces. This seems to happen a lot.
    line = line.strip()
    line = re.sub(r'[\xa2\xA9\x80\u20ac]', 'C', line)       # replace cent symbol, copyright or Euro symbol to C & unicode Euro symbol to C
    line = re.sub(r'[\xc9\u00e9]', 'E', line)                     # E with accent to E, unicode character U+00E9 (LATIN SMALL LETTER E WITH ACUTE)
    line = re.sub(r'\u201c', 'I', line)                     # replace double back ticks to I
    line = re.sub(r'\xa5', 'V', line)                       # yen symbol looks like V.
    line = re.sub(r'\xa3', 'L', line)                        # point simbol is like L

    line = correct_ocr_mispellings_of_common_words(line)    # note this is done before punctuation is removed below so they can be corrected to chars when appropriate.

    line = re.sub(r'[\*\-\_\,\~{}+<>=\"\|\u20140\u201d0\u2019;]', '', line) # don't remove periods as they are commonly used for middle initials. 
                                                            # \u2014 is an em dash \u201d is unusual double quote. \u2019 backquote

    
    check_ev_line_for_unexpected_chars(line)
    return line
    
def check_ev_line_for_unexpected_chars(line):
    match = re.search(r'([^A-Z0-9\(\)\s/\:\.])', line)
    if bool(match):
        utils.exception_report(f"Invalid character detected in EV OCR line: {match[1]} ({hex(ord(match[1]))}) line:{line}")
        
def correct_ocr_mispellings_of_common_words(line):
    """ upon entry, characters from TESSERACT have been upper-cased 
        and known unicode mistakes removed
        but not all special chars removed.
    
        common mistakes of characters:
        
        D   [D0OB]
        E   [EF]
        f   [tf]
        I   [I1L!l|T]
        J   [J3]
        L   [L\\!]
        M   [WHM]
        m   (m|rn)
        N   [WN]
        O   [ODU0GC@]
        P   [FP]
        R   [RK]
        rn  (m|rn)
        Q   [Q@]
        T   [TY1F]
        t   [tf]
        Y   [YV]
        1   [I1L!l|]    (one)
    """
    line = re.sub(r'[WHM]U[WN][I1L!l|T]C[I1L!l|T][FP]A[L\\!]', 'MUNICIPAL', line)
    line = re.sub(r'SCH[ODU0GC@][ODU0GC@][L\\!]', 'SCHOOL', line)
    line = re.sub(r'[Q@][I1L!l|]', 'Q1', line)
    line = re.sub(r'[Q@]2', 'Q2', line)
    line = re.sub(r'[J3]U[D0OB]G[EF]', 'JUDGE', line)
    line = re.sub(r'[DO0B][I1L!l|T]STR[I1L!l|T]C[TY1]', 'DISTRICT', line)
    line = re.sub(r'W/[I1L!l|]', 'W/I', line)
    line = re.sub(r'[RK][EF]F[EF][RK][EF]N[D0O]UM', 'REFERENDUM', line)
    line = re.sub(r'[HMW][EF][HMW]B[EF]R', 'MEMBER', line)
    line = re.sub(r'\s[ODU0GC@][EF]\s', ' OF ', line)
    line = re.sub(r'\s[TY1F]H[EF]\s', ' THE ', line)
    line = re.sub(r'[WHM]A[YV][ODU0GC@][RK]', 'MAYOR', line)
    line = re.sub(r'SU[FP][EF][RK][YV][I1L!l|T]S[ODU0GC@][RK]', 'SUPERVISOR', line)
    line = re.sub(r'\b[WN][ODU0GC@]\sS[EF][L\\!][EF]C[TY1F][I1L!l|T][ODU0GC@][WN]\s[WHM]A[D0OB]EF]', 'NO SELECTION MADE', line)

    
    if len(line) <= 4:
        # allow slop in the length of the string.
        line = re.sub(r'[WN][ODU0GCAo]', 'NO', line)
        line = re.sub(r'[YV][EFeo][sS]', 'YES', line)

    return line
  
def correct_ocr_mispellings_of_common_words_mixedcase(line):
    """ upon entry, characters from TESSERACT have NOT been upper-cased 
        and known unicode mistakes removed
        but not all special chars removed.
    
        common mistakes of characters:
        
        D   [D0OB]
        E   [EF]
        f   [tf]
        I   [I1L!l|T]
        J   [J3]
        L   [L\\!]
        M   [WHM]
        m   (m|rn)
        N   [WN]
        O   [ODU0GC@]
        P   [FP]
        R   [RK]
        rn  (m|rn)
        Q   [Q@]
        T   [TY1F]
        t   [tf]
        Y   [YV]
        1   [I1L!l|]    (one)
    """
    line = line.strip(' ')
    
    line = re.sub(r'[WHM]U[WN][I1L!l|T]C[I1L!l|T][FP]A[L\\!]', 'MUNICIPAL', line)
    line = re.sub(r'SCH[ODU0GC@][ODU0GC@][L\\!]', 'SCHOOL', line)
    line = re.sub(r'[Q@][I1L!l|]', 'Q1', line)
    line = re.sub(r'[Q@]2', 'Q2', line)
    line = re.sub(r'[J3]U[D0OB]G[EF]', 'JUDGE', line)
    line = re.sub(r'[DO0B][I1L!l|T]STR[I1L!l|T]C[TY1]', 'DISTRICT', line)
    line = re.sub(r'W/[I1L!l|]', 'W/I', line)
    line = re.sub(r'[RK][EF]F[EF][RK][EF]N[D0O]UM', 'REFERENDUM', line)
    line = re.sub(r'[HMW][EF][HMW]B[EF]R', 'MEMBER', line)
    line = re.sub(r'\s[ODU0GC@][EF]\s', ' OF ', line)
    line = re.sub(r'\s[TY1F]H[EF]\s', ' THE ', line)
    line = re.sub(r'[WHM]A[YV][ODU0GC@][RK]', 'MAYOR', line)
    line = re.sub(r'SU[FP][EF][RK][YV][I1L!l|T]S[ODU0GC@][RK]', 'SUPERVISOR', line)
    line = re.sub(r'[WN][ODU0GC@]\sS[EF][L\\!][EF]C[TY1F][I1L!l|T][ODU0GC@][WN]\s[WHM]A[D0OB]EF]', 'NO SELECTION MADE', line)
    line = re.sub(r'\b[KR]epresentative\b', 'Representative', line)
    line = re.sub(r'\bGove(m|rn)m?or\b', 'Governor', line)
    line = re.sub(r'\bGove(m|rn)men[tk]\b', 'Government', line)
    line = re.sub(r'\bgove(m|rn)or\b', 'governor', line)
    line = re.sub(r'\bCh[il][eco][tf]\b', 'Chief', line)
    line = re.sub(r'\bA[isrxy]s?[tf]ic[1ltif][ea]\b', 'Article', line)
    line = re.sub(r'\ba[sr]tic[1lti]e\b', 'article', line)
    line = re.sub(r'\bArticle [iIl!1]', 'Article I', line)
    line = re.sub(r'\bArticle [iIl!1][iIl!1]', 'Article II', line)
    line = re.sub(r'\bArticle [iIl!1][iIl!1][iIl!1]', 'Article III', line)
    line = re.sub(r'\bArticle [iIl!1]V', 'Article IV', line)
    line = re.sub(r'\bArticle V[iIl!1]', 'Article VI', line)
    line = re.sub(r'\bArticle V[iIl!1][iIl!1]', 'Article VII', line)
    line = re.sub(r'\bArticle V[iIl!1][iIl!1][iIl!1]', 'Article VIII', line)
    line = re.sub(r'\bArticle [iIl!1]X', 'Article IX', line)
    line = re.sub(r'\bArticle X[iIl!1]', 'Article XI', line)
    line = re.sub(r'\bArticle X[iIl!1][iIl!1]', 'Article XII', line)
    line = re.sub(r'\bArticle X[iIl!1][iIl!1][iIl!1]\b', 'Article XIII', line)
    line = re.sub(r'\bA[pno][pno]rova[li1]\b', 'Approval', line)
    line = re.sub(r'\b[GC]o[mn]mi[lt][lt]?[esa][esao]\b', 'Committee', line)
    line = re.sub(r'L[il]eutenant', 'Lieutenant', line)

    line = re.sub(r'\bCourtofAppea[lt]\b', 'Court of Appeal', line)
    line = re.sub(r'\bAppee?a[tl]\b', 'Appeal', line)
    line = re.sub(r'\bAtto(rn|m)[eo][vy]\b', 'Attorney', line)
    line = re.sub(r'\bG?C[aoO]n[sS]t[i]?t[u]?[t]?ic?ona[iIl!l]?\b', 'Constitutional', line)
    
    line = re.sub(r'\bAnuse\b', 'Abuse', line)
    line = re.sub(r'\bA[jM]?m[oae][hna][dago]me[nmr][try]r?\b', 'Amendment', line)
    line = re.sub(r'\b[GCV]ons(tin|uru)tio[mn]al\b', 'Constitutional', line)
    line = re.sub(r'\b[WV][eo]t[ea]f[oa]rOn[eas]\b', 'Vote for One', line)
    line = re.sub(r'\b[lti1]egis[lti1]ature\b', 'legislature', line)
    line = re.sub(r'\bAg([tr]i|n)cu[flit]?[tl]ure\b', 'Agriculture', line)
    line = re.sub(r'\bCiti[rze][ea]n', 'Citizen', line)
    line = re.sub(r'\bDe[lft]en[cdt]i?er\b', 'Defender', line)
    line = re.sub(r'\bDi[sa]tr?[li]ct\b', 'District', line)
    line = re.sub(r'\bEnc[li]osed\b', 'Enclosed', line)
    line = re.sub(r'\bEstab[il]?[il]shes\b', 'Establishes', line)
    line = re.sub(r'\bEt[hfmn]?ic[sae]\b', 'Ethics', line)
    line = re.sub(r'\bFinanc[hit]a[li]?\b', 'Financial', line)
    line = re.sub(r'\b[FP]ropose[da]/b', 'Proposed', line)
    line = re.sub(r'\bGen[ce]ra[ilrt]\b', 'General', line)
    line = re.sub(r'\b[DG]epar[ti]ment\b', 'Department', line)
    line = re.sub(r'\b[DG]i?scriminatory\b', 'Disciminatory', line)
    line = re.sub(r'\b[BG]oard\b', 'Board', line)
    
    line = re.sub(r'\bJu[da]g[eao]\b', 'Judge', line)
    line = re.sub(r'\bJui?di[ca][ilt][ae][litf]\b', 'Judicial', line)
    line = re.sub(r'\bJus?tic[oe]\b', 'Justice', line)
    line = re.sub(r'\b[KR]evi[zsg][it]o[nr]\b', 'Revision', line)
    line = re.sub(r'\bLo[Dbo]b?[op]ying\b', 'Lobbying', line)
    line = re.sub(r'\bLoca[il]\b', 'Local', line)
    line = re.sub(r'\bO[fl][fl][li]cers?\b', 'Officer', line)
    line = re.sub(r'\bProhib[is]ts\b', 'Prohibits', line)
    line = re.sub(r'\bPub[li][li][ce]\b', 'Public', line)
    line = re.sub(r'\b[QC]harter\b', 'Charter', line)
    line = re.sub(r'\bQua[il]ifying\b', 'Qualifying', line)
    line = re.sub(r'\bRemova[il]\b', 'Removal', line)
    line = re.sub(r'\bR[ea]view\b', 'Review', line)
    line = re.sub(r'\bR[eo]pr[oe]s[eo][nf]tf?ativ[oe]s?\b', 'Representative', line)
    line = re.sub(r'\bRe[yv][ti][sagc][it]on\b', 'Revision', line)
    line = re.sub(r'\bS[ea][acosq]t[il[oaqp][eng]\b', 'Section', line)
    line = re.sub(r'\bSchoo[il]\b', 'School', line)
    line = re.sub(r'\bSha[ilf][ilf]\b', 'Shall', line)
    line = re.sub(r'\bS[it]ates\b', 'States', line)
    line = re.sub(r'\bautho(n|ri)za([ti]i|[5f])on\b', 'authorization', line)
    line = re.sub(r'\bbounda(n|ri)es\b', 'boundaries', line)
    line = re.sub(r'\bc(n|r)?im(m|in)i?(d|al)\b', 'criminal', line)
    line = re.sub(r'\b(ck|di)scrimina[ti]ory\b', 'discriminatory', line)
    line = re.sub(r'\bcompe[mn]sa([if]|[it])ion\b', 'compensation', line)
    line = re.sub(r'\bcounterterror?(ri|n)sm\b', 'counterterrorism', line)
    line = re.sub(r'\bde[ops][ea]r[it]ment\b', 'department', line)
    line = re.sub(r'\be[fl]i?minate', 'eliminate', line)
    line = re.sub(r'\b[ae]pproval\b', 'approval', line)
    line = re.sub(r'\b[ae]pproved\b', 'approved', line)
    line = re.sub(r'\b[tl]an[gq]ua[qg]e\b', 'language', line)
    line = re.sub(r'\b[tl]egis[ilt]ature\b', 'legislature', line)
    line = re.sub(r'\b[tl]egis[ilt]atures\b', 'legislatures', line)
    line = re.sub(r'\b[tl]eg[ij]s[li]ative\b', 'legislative', line)
    line = re.sub(r'\bma[nm]d[az]ti?ory\b', 'mandatory', line)
    line = re.sub(r'\bordi[nm]ance', 'ordimance', line)
    line = re.sub(r'\bpe[nm]a[li]it?ies\b', 'penalities', line)
    line = re.sub(r'\bpermanen[ti]ly\b', 'permanenily', line)
    line = re.sub(r'\bposi[fti]?i?on\b', 'posifion', line)
    line = re.sub(r'\bprosecu[tf]{,2}ion\b', 'prosecution', line)
    line = re.sub(r'\bpro[vw]ides\b', 'provides', line)
    line = re.sub(r'\bre[lf]ated\b', 'related', line)
    line = re.sub(r'\bremo[vw]es\b', 'removes', line)
    line = re.sub(r'\brest(n|r[ti])c[ti][ti]ons\b', 'restrictions', line)
    line = re.sub(r'\brest(n|r[ti])ct?[if]ve\b', 'restrictive', line)
    line = re.sub(r'\brest(n|ri)i?ctions\b', 'restrictions', line)
    line = re.sub(r'\bre[lt]a[lt]ed\b', 'related', line)
    line = re.sub(r'\b[fr]inancial\b', 'financial', line)
    line = re.sub(r'\b[pr]roposed\b', 'proposed', line)
    line = re.sub(r'\bschoo[li]\b', 'schooi', line)
    line = re.sub(r'\bsecu[rt][li]ty\b', 'security', line)
    line = re.sub(r'\bs[tiu]r?uct[iu]re\b', 'structure', line)
    line = re.sub(r'\b[Ss]tepnanie\b', 'Stephanie', line)
    line = re.sub(r'\bsupe[nr]maj[ao](ri|n|mi)[lt]y\b', 'supermajority', line)
    line = re.sub(r'\bte(m|rr)i[it]or?[ni]?al\b', 'territorial', line)
    line = re.sub(r'\b[tr]ev[ri]s[ri]on\b', 'revision', line)
    line = re.sub(r'\bvapor-genera[tfif]{,3}ng\b', '', line)
    line = re.sub(r'\bva[tp]e\b', 'vape', line)
    line = re.sub(r'\b[vw]oter', 'voter', line)
    line = re.sub(r'\b[wj]?udicial\b', 'judicial', line)

    line = re.sub(r'\(tm\)', '"', line)                         # " is frequently misinterpreted as TM symbol, which is sanitized as (tm) but should be "
    return line

def correct_ocr_mispellings_of_common_names_mixedcase(line):
    line = re.sub(r'Nufiez', 'Nuniez', line)
    line = re.sub(r'\(tm\)', '"', line)                         # " is frequently misinterpreted as TM symbol, which is sanitized as (tm) but should be "

    return line


  
def parse_ev_bottom_strlist(votefor_list: list, bottom_strlist: list, ballot_id: str) -> list:
    """
    This function decodes the multi-line format where there is a contest name followed by options,
    each on separate lines.
    
    :param  votefor_list -- (list of int) for each contest in this style,
                                provides the votefor value for each.
    :param  bottom_strlist -- a list of string decoded from the bottom of the ballot
    :return 
    :       ev_contests -- (list) list of contest dictionaries containing
                                  string under `ocr_contestname`
                                  and list under `ocr_names`:
    """
    # declaring contests list
    ev_contests = []

    # extracting contests and options
    # it appears that this code relies on length of the line to classify contestnames vs option names.
    
    error = ''
    for votefor in votefor_list:
        try:
            contest = sanitize_ev_line(bottom_strlist.pop(0))
        except IndexError:
            error = 'Insufficient Contests found on expressvote ballot'
            break
            
        ev_contests.append({
            "ocr_contestname": sanitize_ev_line(contest),
            "ocr_names": []
            })
        for i in range(votefor):
            try:
                option = bottom_strlist.pop(0)
            except IndexError:
                error = f"Insufficient options found on expressvote ballot for contest: {contest}"
                break
            ev_contests[-1]["ocr_names"].append(sanitize_ev_line(option))
            
    if error:        
        string = f"Parsing contesta and options failed on ballot:{ballot_id}\n{error}"
        utils.exception_report(string)
        
    return ev_contests
    
    
def analyze_bmd_ess(argsdict, ballot, rois_map_df, contests_dod) -> pd.DataFrame:
    """
    This function extracts votes as specified in page_rois_map_df from one image.
    returns page_marks_df
    """
    ev_fuzzy_thres_contest  = 0.8       # config_dict['fuzzy_thres']['contest']
    #ev_max_chars            = 51        # max characters in one line of the EV ballot summary
    ev_fuzzy_thres_writein  = 0.6
    writein_prefix          = 'W/I:'
    
    ballot_id = ballot.ballotdict['ballot_id']
    precinct = ballot.ballotdict['precinct']
    utils.sts(f"Processing ExpressVote Ballot ID:{ballot_id} using OCR", 3)
    
    #if int(ballot_id) == 261997:
    #    import pdb; pdb.set_trace()
    
    ev_header_code, bottom_strlist, ev_coord_str_list = expressvote_conversion(
            ballot.ballotimgdict['images'][0], 
            ballot_id,
            expressvote_header=argsdict.get('expressvote_header'),
            )
    """ This function performs alignment, trimming, segmentation and ocr,
        barcode decoding, and comparision with the expressvote_header
        :returns ev_coord_str_list -- barcodes (list) list of sorted decoded barcodes:
        :returns bottom_strlist (list) unparsed list of strings at the bottom.
    """
    
    if ev_header_code is None:
        utils.sts(f"Initial check of expressvote ballot failed for ballot_id:{ballot_id}", 3)
        return None
    if len(ev_header_code) < 26:
        utils.sts(f"Header barcode is incorrect length for ballot {ballot_id}", 3)
        return None
        
    # Split and extract data from header barcode, including style_num
    ballot.ballotdict['ev_precinct_id']     = ev_precinct_id    = int(ev_header_code[0:10])
    ballot.ballotdict['ev_logical_style']   = ev_logical_style  = int(ev_header_code[10:20])
    style_num = str(convert_ev_logical_style_to_style_num(ev_logical_style))
    ballot.ballotdict['style_num']          = style_num
    ballot.ballotdict['ev_num_writeins']    = int(ev_header_code[20:23])
    ballot.ballotdict['ev_num_marks']       = int(ev_header_code[23:26])
    ballot.ballotdict['ev_coord_str_list']  = normalize_ev_coord_str_list(ev_coord_str_list)
    
    style_rois_map_df = rois_map_df.loc[rois_map_df['style_num'] == style_num]
    
    if not len(style_rois_map_df.index):
        # we have no style information defined for this style. This can happen if no 
        # nonBMD ballots exist for this style, and there are no templates generated and no
        # analysis of ev_coord_str values that can be used in barcode extraction.
        # one way to deal with this might be to use the contests and options as defined in EIF
        # and using the master_style_dict -- indexed by style, provides list of contests
        # and construct a marks_df that way.
        string = f"### EXCEPTION: 'Known_Limitation_001' ev_ballot {ballot_id} style {style_num} has no rois_map defined.\n" \
               + "Probably this is because no nonBMD ballots exist to create the map.\n"
        utils.exception_report(string)
        return None
    
    votefor_list = get_votefor_list_from_style_rois_map_df(style_rois_map_df)
    # the function above contructs the votefor list for this style as a list
        
    ev_contests = parse_ev_bottom_strlist(votefor_list, bottom_strlist, ballot_id)
    ballot.ballotdict['ev_contests'] = ev_contests
    ballot.ballotdict['ocr_options'] = flatten_selected_options(ev_contests)
    
    
    ocr_parse_success_flag = False
    if ev_contests:
        # attempt to extract votes from OCR'd text
        if utils.is_verbose_level(3):
            for ev_contest in ev_contests:
                utils.sts(f"Contest: {ev_contest['ocr_contestname']} Options: {', '.join(ev_contest['ocr_names'])}", 3)
        ev_contests_idx = -1
        page_marks_lod = []
        ocr_parse_success_flag = True
        
        for idx in range(len(style_rois_map_df.index)):
            page_rois_dict = style_rois_map_df.iloc[idx]

            contest = page_rois_dict['contest']
            option = page_rois_dict['option']
            
            marks_dict = create_empty_marks_dict()
            
            marks_dict['ballot_id']         = ballot_id
            marks_dict['style_num']         = style_num
            marks_dict['precinct']          = precinct
            marks_dict['contest']           = contest
            marks_dict['option']            = option
            marks_dict['ev_precinct_id']    = ev_precinct_id

            if option.startswith(r'#'):
                # contest header uses option starting with #, initialize parsing the next contest.
                ev_contests_idx += 1
                try:
                    ev_ocr_contest_name = ev_contests[ev_contests_idx]['ocr_contestname']
                except IndexError:
                    string = f"### EXCEPTION: contest '{contest}' not found on expressvote ballot {ballot_id} -- aborting" \
                           + f"ev_contests: {ev_contests}"
                    utils.exception_report(string)
                    ocr_parse_success_flag = False
                    break
                    
                bmd_contest_name = get_bmd_contest_name(contests_dod[contest], contest, ballot_id)
                
                # compare the contest name with the ocr name. Since we know the style, these should match,
                # and if not, we create an exception report and give up.
                matchflag, _ = fuzzy_compare_str(
                        correct_str=bmd_contest_name, 
                        ocr_str=ev_ocr_contest_name[:(len(bmd_contest_name)+1)],    # compare only the first left chars to match bmd_contest_name, allowing some slop.
                        thres=ev_fuzzy_thres_contest)
                if not matchflag:
                    string = "Contest mismatch:\n%52s | %-52s\n" % ('----bmd_contest_name-----', '----ev_ocr_contest_name----')
                    string += "%52s | %-52s" % (bmd_contest_name, ev_ocr_contest_name)
                    utils.exception_report(string)
                    ocr_parse_success_flag = False
                    break
                
                # get the options as extracted from the ev image and the official options list as provided in the roismap.
                # the roismap lists them in the order they are on the ballot so these should match the barcode order too.
                ocr_options = ev_contests[ev_contests_idx]['ocr_names']                 
                contest_df = style_rois_map_df.loc[style_rois_map_df['contest'] == contest]
                official_options_list = contest_df['option'][1:]        # discard #contest header and keep the rest.
                
                success_flag, spec_idx_val_dict, writein_idx_val_dict = ev_match_options(ballot_id, contest, ocr_options, official_options_list)
                # return offsets into official option list and ocr_val
                if not success_flag:
                    ocr_parse_success_flag = False
                    break
                
                page_marks_lod.append(marks_dict)   # this appends the contest header
                option_num = 0
                continue
            
            if not option_num in spec_idx_val_dict and not option_num in writein_idx_val_dict:
                option_num += 1
                continue        # do not include record that has no marks. 
            
            if option_num in spec_idx_val_dict:
                _, metric = spec_idx_val_dict[option_num]
                marks_dict['pixel_metric_value'] = round(metric * 100)
                #style_rois_map_df.iloc[idx]['ev_coord_str'] = ev_coord_str_list[ev_coord_idx]
            elif option_num in writein_idx_val_dict:
                # we assume it is probably a writein if it does not match, if writeins are available.
                # create a metric based on match to the prefix 'W/I:'
                writein_name, _ = writein_idx_val_dict[option_num]
                writein_prefix_match, metric = fuzzy_compare_str(
                    writein_prefix, 
                    writein_name[:(len(writein_prefix)+1)],     # limit comparision of writein-prefix to the length of that prefix + slop.
                    ev_fuzzy_thres_writein)
                if not writein_prefix_match:
                    # match is unreliable, drop to using barcodes.
                    ocr_parse_success_flag = False
                    break
                    
                marks_dict['writein_name'] = writein_name
                marks_dict['pixel_metric_value'] = metric

            #try:
            #    marks_dict['ev_coord_str'] = ev_coord_str_list[ev_coord_idx]
            #    ev_coord_idx += 1
            #except IndexError:
            #    string = f"Insufficient barcodes decoded for the {bmd_contest_name} on ev ballot {ballot_id}"
            #    utils.exception_report(string)
            #    missing_bacodes_flag = True
            #    # note that we do not return None here because even though the barcodes are incomplete, we may be able to parse the OCR text.
                
            marks_dict['has_indication'] = 'DefiniteMark'
            marks_dict['num_marks'] = 1
            page_marks_lod.append(marks_dict)
            option_num += 1

    if not ocr_parse_success_flag:
        # bailed out of the loop above because of inconsistencies or never started.
            
        string = f"### WARNING: expressvote ballot {ballot_id} of precinct {precinct}: OCR not successful. Using Barcodes" 
        utils.exception_report(string)
        page_marks_lod = extract_marks_from_barcodes(ballot, style_rois_map_df)
        # failed to parse OCR to create ballot_marks_df, but barcodes exist.
        # The rois_map has been filled in with ev_coord_str during template generation.
        # then we can use them to complete the ballot_marks_df
        
        # if this also fails, then bail out.
        if not page_marks_lod:
            return None
   
    evaluate_votes_on_ballot(page_marks_lod)

    print_contest_marks_lod(page_marks_lod)

    # create dataframe and save it.
    ballot_marks_df = create_empty_marks_df()
    ballot_marks_df = ballot_marks_df.append(page_marks_lod, ignore_index=True, sort=False)

    ballot.ballotdict['marks_df'] = ballot_marks_df

    return ballot_marks_df


def analyze_bmd_dominion(argsdict, ballot, rois_map_df, contests_dod) -> pd.DataFrame:
    """
    This function extracts votes as specified in page_rois_map_df from one image.
    returns page_marks_df
    
    Currently having trouble with this function as it does not convert the barcode data.
    
     barcode_decode(Image.open("R:\\BallotImageArchive\\CA_San_Francisco_2020_Pri\\D01\\D01\\Pre_Pct 9101\\CGr_Election Day\\00005_00213_000001.tif"))
        [Decoded(data=b'', type='QRCODE', rect=Rect(left=59, top=706, width=270, height=269), polygon=[Point(x=59, y=706),
        Point(x=61, y=974), Point(x=329, y=975), Point(x=327, y=710)])]
    barcode_decode(Image.open("R:\\BallotImageArchive\\CA_San_Francisco_2020_Pri\\D01\\D01\\Pre_Pct 9101\\CGr_Election Day\\00005_00545_000050.tif"))
        [Decoded(data=b'', type='QRCODE', rect=Rect(left=65, top=722, width=268, height=267), polygon=[Point(x=65, y=722),
        Point(x=67, y=989), Point(x=333, y=989), Point(x=331, y=723)])]
    
    
    """
    bmd_fuzzy_thres_contest  = 0.8       # config_dict['fuzzy_thres']['contest']
    #bmd_max_chars            = 51        # max characters in one line of the EV ballot summary
    bmd_fuzzy_thres_writein  = 0.6
    writein_prefix          = 'W/I:'
    
    ballot_id = ballot.ballotdict['ballot_id']
    precinct = ballot.ballotdict['precinct']
    utils.sts(f"Processing Dominion BMD Ballot ID:{ballot_id} using OCR", 3)
    
    import pdb; pdb.set_trace()
    
    bottom_strlist, vertical_code, qrcode = dominion_bmd_conversion(ballot.ballotimgdict['images'][0])  #@ needed
    """
    :param image: (np.array) array of an unaligned image of Dominion type ballot, which may be an BMD ballot summary
    :return both_columns.splitlines(): (list) list of lines OCRed from ballot results
    :return vertical_code: (str) string containing OCRed vertical code of the ballot
    :return qrcode[0]: qrcode of the ballot
    """
    
    if not bottom_strlist:
        utils.sts(f"Initial check of bmd ballot failed for ballot_id:{ballot_id}", 3)
        return None
    if len(qrcode) < 30:   # arbitrary value for now until we figure this out.
        utils.sts(f"QRcode is incorrect length for ballot {ballot_id}", 3)
        return None
   
    style_num, bmd_precinct_id = qrcode_to_style_num(qrcode)    # @@ missing this function
   
    style_rois_map_df = rois_map_df.loc[rois_map_df['style_str'] == str(style_num)]
    
    if not len(style_rois_map_df.index):
        # we have no style information defined for this style. This can happen if no 
        # nonBMD ballots exist for this style, and there are no templates generated and no
        # analysis of ev_coord_str values that can be used in barcode extraction.
        # one way to deal with this might be to use the contests and options as defined in EIF
        # and using the master_style_dict -- indexed by style, provides list of contests
        # and construct a marks_df that way.
        string = f"### EXCEPTION: 'Known_Limitation_001' BMD ballot {ballot_id} style {style_num} has no rois_map defined.\n" \
               + "Probably this is because no nonBMD ballots exist to create the map.\n"
        utils.exception_report(string)
        return None
    
    votefor_list = get_votefor_list_from_style_rois_map_df(style_rois_map_df)
    # the function above contructs the votefor list for this style as a list
        
    bmd_contests = parse_bmd_bottom_strlist_dom(votefor_list, bottom_strlist, ballot_id)  # @@ Need this
    ballot.ballotdict['bmd_contests'] = bmd_contests
    ballot.ballotdict['ocr_options'] = flatten_selected_options(bmd_contests)
    
    ocr_parse_success_flag = False
    if bmd_contests:
        # attempt to extract votes from OCR'd text
        if utils.is_verbose_level(3):
            for bmd_contest in bmd_contests:
                utils.sts(f"Contest: {bmd_contest['ocr_contestname']} Options: {', '.join(bmd_contest['ocr_names'])}", 3)
        bmd_contests_idx = -1
        #line_os = 0
        page_marks_lod = []
        ocr_parse_success_flag = True
        
        for idx in range(len(style_rois_map_df.index)):
            page_rois_dict = style_rois_map_df.iloc[idx]

            contest = page_rois_dict['contest']
            option = page_rois_dict['option']
            
            marks_dict = create_empty_marks_dict()
            
            marks_dict['ballot_id']         = ballot_id
            marks_dict['style_num']         = '' #??
            marks_dict['precinct']          = precinct
            marks_dict['contest']           = contest
            marks_dict['option']            = option
            marks_dict['bmd_precinct_id']   = bmd_precinct_id

            if option.startswith(r'#'):
                # contest header uses option starting with #, initialize parsing the next contest.
                bmd_contests_idx += 1
                try:
                    bmd_ocr_contest_name = bmd_contests[bmd_contests_idx]['ocr_contestname']
                except IndexError:
                    string = f"### EXCEPTION: contest '{contest}' not found on expressvote ballot {ballot_id} -- aborting" \
                           + f"bmd_contests: {bmd_contests}"
                    utils.exception_report(string)
                    ocr_parse_success_flag = False
                    break
                    
                bmd_contest_name = get_bmd_contest_name(contests_dod[contest], contest, ballot_id)
                
                # compare the contest name with the ocr name. Since we know the style, these should match,
                # and if not, we create an exception report and give up.
                # TODO this must change for Dominion because strings are just in a single list.
                matchflag, _ = fuzzy_compare_str(
                        correct_str=bmd_contest_name, 
                        ocr_str=bmd_ocr_contest_name[:(len(bmd_contest_name)+1)],    # compare only the first left chars to match bmd_contest_name, allowing some slop.
                        thres=bmd_fuzzy_thres_contest)
                if not matchflag:
                    string = "Contest mismatch:\n%52s | %-52s\n" % ('----bmd_contest_name-----', '----ocr_contest_name----')
                    string += "%52s | %-52s" % (bmd_contest_name, bmd_ocr_contest_name)
                    utils.exception_report(string)
                    ocr_parse_success_flag = False
                    break
                
                # get the options as extracted from the ev image and the official options list as provided in the roismap.
                # the roismap lists them in the order they are on the ballot so these should match the barcode order too.
                ocr_options = bmd_contests[bmd_contests_idx]['ocr_names']                 
                contest_df = style_rois_map_df.loc[style_rois_map_df['contest'] == contest]
                official_options_list = contest_df['option'][1:]        # discard #contest header and keep the rest.
                
                # @@ need to create bmd_match_options. Same as ev_match_options?
                success_flag, spec_idx_val_dict, writein_idx_val_dict = bmd_match_options(ballot_id, contest, ocr_options, official_options_list)
                # return offsets into official option list and ocr_val
                if not success_flag:
                    ocr_parse_success_flag = False
                    break
                
                page_marks_lod.append(marks_dict)   # this appends the contest header
                option_num = 0
                continue
            
            if not option_num in spec_idx_val_dict and not option_num in writein_idx_val_dict:
                option_num += 1
                continue        # do not include record that has no marks. 
            
            if option_num in spec_idx_val_dict:
                _, metric = spec_idx_val_dict[option_num]
                marks_dict['pixel_metric_value'] = round(metric * 100)
                #style_rois_map_df.iloc[idx]['ev_coord_str'] = ev_coord_str_list[ev_coord_idx]
            elif option_num in writein_idx_val_dict:
                # we assume it is probably a writein if it does not match, if writeins are available.
                # create a metric based on match to the prefix 'W/I:'
                writein_name, _ = writein_idx_val_dict[option_num]
                writein_prefix_match, metric = fuzzy_compare_str(
                    writein_prefix, 
                    writein_name[:(len(writein_prefix)+1)],     # limit comparision of writein-prefix to the length of that prefix + slop.
                    bmd_fuzzy_thres_writein)
                if not writein_prefix_match:
                    # match is unreliable, drop to using barcodes.
                    ocr_parse_success_flag = False
                    break
                    
                marks_dict['writein_name'] = writein_name
                marks_dict['pixel_metric_value'] = metric

            #try:
            #    marks_dict['ev_coord_str'] = ev_coord_str_list[ev_coord_idx]
            #    ev_coord_idx += 1
            #except IndexError:
            #    string = f"Insufficient barcodes decoded for the {bmd_contest_name} on ev ballot {ballot_id}"
            #    utils.exception_report(string)
            #    missing_bacodes_flag = True
            #    # note that we do not return None here because even though the barcodes are incomplete, we may be able to parse the OCR text.
                
            marks_dict['has_indication'] = 'DefiniteMark'
            marks_dict['num_marks'] = 1
            page_marks_lod.append(marks_dict)
            option_num += 1

    if not ocr_parse_success_flag:
        # bailed out of the loop above because of inconsistencies or never started.
            
        string = f"### WARNING: expressvote ballot {ballot_id} of precinct {precinct}: OCR not successful. Using Barcodes" 
        utils.exception_report(string)
        page_marks_lod = extract_marks_from_barcodes(ballot, style_rois_map_df)
        # failed to parse OCR to create ballot_marks_df, but barcodes exist.
        # The rois_map has been filled in with ev_coord_str during template generation.
        # then we can use them to complete the ballot_marks_df
        
        # if this also fails, then bail out.
        if not page_marks_lod:
            return None
   
    evaluate_votes_on_ballot(page_marks_lod)

    print_contest_marks_lod(page_marks_lod)

    # create dataframe and save it.
    ballot_marks_df = create_empty_marks_df()
    ballot_marks_df = ballot_marks_df.append(page_marks_lod, ignore_index=True, sort=False)

    ballot.ballotdict['marks_df'] = ballot_marks_df

    return ballot_marks_df
    
def qrcode_to_style_num():
    pass

def bmd_match_options(ballot_id, contest, ocr_options, official_options_list) -> (bool, dict, dict):
    """ given list of ocr options for this contest, match with official options.
        special care is given to ballots with 'NO SELECTION MADE'
        and non matching entries that are probably writeins.
        param: ballot_id (str) -- passed for exception reports only.
        param: contest (str) -- official contest name for exception reports.
        param: ocr_options (list of str) -- list of options read from the ev ballot for this contest.
        param: official_options_list (list of str) -- options which are valid for this contest.
        return: success_flag, which is true unless matches failed.
                two dicts, with key being the index of the option found in the correct options as provided from roismap
                and the content a tuple: (ocr_option, and metric)
        
    """
    undervote_str = 'NO SELECTION MADE'
    ev_fuzzy_thres_no_selection = 0.80   # config_dict['fuzzy_thres']['options']
    ev_fuzzy_thres_options = 0.60        # config_dict['fuzzy_thres']['options']
    ev_max_chars = 51                    # max characters in one line of the EV ballot summary
    success_flag = True
    
    # first split official options into specified and writein options.
    specified_options = []
    writein_options = []
    for off_option in official_options_list:
        if off_option.startswith('writein'):
            writein_options.append(off_option)
        else:
            specified_options.append(off_option[:ev_max_chars].upper())

    num_writeins_avail = len(writein_options)
    num_specified_options = len(specified_options)
    specified_dict = {}
    writein_dict = {}
    writein_option_num = 0
    non_matched_options = []
    non_matched_metrics = []
    for ocr_option in ocr_options:
        # disregard 'NO SELECTION MADE' options
        match_flag, metric = fuzzy_compare_str(
            undervote_str, 
            ocr_option,
            ev_fuzzy_thres_no_selection,
            justify='right')
        if match_flag: continue
        
        # match_flag == False
        # in (rare) cases, there are no specified options and only writeins.
        if specified_options:
            match_flag, idx, metric = fuzzy_compare_str_to_list(
                correct_strlist = specified_options, 
                ocr_str = ocr_option, 
                thres=ev_fuzzy_thres_options,
                #fuzzy_compare_mode='best_of_all'
                )
            # idx is the offset within correct_strlist the option is found
        
        if match_flag:
            specified_dict[idx] = (ocr_option, metric)
        else:
            if writein_option_num < num_writeins_avail:
                writein_dict[num_specified_options + writein_option_num] = (ocr_option, 0)
                writein_option_num += 1
            else:
                # oops, we don't recognize this entry and writeins are all used up.
                non_matched_options.append(ocr_option)
                non_matched_metrics.append(str(round(metric, 2)))

    if non_matched_options:
        success_flag = False
        string = f"### EXCEPTION: Could not locate ocr option '{', '.join(non_matched_options)}' \n" + \
                 f"ballot_id:{ballot_id} contest:{contest} metrics:'{', '.join(non_matched_metrics)}'"
        utils.exception_report(string)
    return success_flag, specified_dict, writein_dict
    
def parse_bmd_bottom_strlist_dom(votefor_list: list, bottom_strlist: list, ballot_id: str) -> list:
    """
    This function decodes the multi-line format where there is a contest name followed by options,
    each on separate lines.
    
    :param  votefor_list -- (list of int) for each contest in this style,
                                provides the votefor value for each.
    :param  bottom_strlist -- a list of string decoded from the bottom of the ballot
    :return 
    :       ev_contests -- (list) list of contest dictionaries containing
                                  string under `ocr_contestname`
                                  and list under `ocr_names`:
    """
    # declaring contests list
    ev_contests = []

    # extracting contests and options
    # it appears that this code relies on length of the line to classify contestnames vs option names.
    
    error = ''
    for votefor in votefor_list:
        try:
            contest = sanitize_ev_line(bottom_strlist.pop(0))
        except IndexError:
            error = 'Insufficient Contests found on expressvote ballot'
            break
            
        ev_contests.append({
            "ocr_contestname": sanitize_ev_line(contest),
            "ocr_names": []
            })
        for i in range(votefor):
            try:
                option = bottom_strlist.pop(0)
            except IndexError:
                error = f"Insufficient options found on expressvote ballot for contest: {contest}"
                break
            ev_contests[-1]["ocr_names"].append(sanitize_ev_line(option))
            
    if error:        
        string = f"Parsing contesta and options failed on ballot:{ballot_id}\n{error}"
        utils.exception_report(string)
        
    return ev_contests



def ev_match_options(ballot_id, contest, ocr_options, official_options_list) -> (bool, dict, dict):
    """ given list of ocr options for this contest, match with official options.
        special care is given to ballots with 'NO SELECTION MADE'
        and non matching entries that are probably writeins.
        param: ballot_id (str) -- passed for exception reports only.
        param: contest (str) -- official contest name for exception reports.
        param: ocr_options (list of str) -- list of options read from the ev ballot for this contest.
        param: official_options_list (list of str) -- options which are valid for this contest.
        return: success_flag, which is true unless matches failed.
                two dicts, with key being the index of the option found in the correct options as provided from roismap
                and the content a tuple: (ocr_option, and metric)
        
    """
    undervote_str = 'NO SELECTION MADE'
    ev_fuzzy_thres_no_selection = 0.80   # config_dict['fuzzy_thres']['options']
    ev_fuzzy_thres_options = 0.60        # config_dict['fuzzy_thres']['options']
    ev_max_chars = 51                    # max characters in one line of the EV ballot summary
    success_flag = True
    
    # first split official options into specified and writein options.
    specified_options = []
    writein_options = []
    for off_option in official_options_list:
        if off_option.startswith('writein'):
            writein_options.append(off_option)
        else:
            specified_options.append(off_option[:ev_max_chars].upper())

    num_writeins_avail = len(writein_options)
    num_specified_options = len(specified_options)
    specified_dict = {}
    writein_dict = {}
    writein_option_num = 0
    non_matched_options = []
    non_matched_metrics = []
    for ocr_option in ocr_options:
        # disregard 'NO SELECTION MADE' options
        match_flag, metric = fuzzy_compare_str(
            undervote_str, 
            ocr_option,
            ev_fuzzy_thres_no_selection,
            justify='right')
        if match_flag: continue
        
        # match_flag == False
        # in (rare) cases, there are no specified options and only writeins.
        if specified_options:
            match_flag, idx, metric = fuzzy_compare_str_to_list(
                correct_strlist = specified_options, 
                ocr_str = ocr_option, 
                thres=ev_fuzzy_thres_options,
                #fuzzy_compare_mode='best_of_all'
                )
            # idx is the offset within correct_strlist the option is found
        
        if match_flag:
            specified_dict[idx] = (ocr_option, metric)
        else:
            if writein_option_num < num_writeins_avail:
                writein_dict[num_specified_options + writein_option_num] = (ocr_option, 0)
                writein_option_num += 1
            else:
                # oops, we don't recognize this entry and writeins are all used up.
                non_matched_options.append(ocr_option)
                non_matched_metrics.append(str(round(metric, 2)))

    if non_matched_options:
        success_flag = False
        string = f"### EXCEPTION: Could not locate ocr option '{', '.join(non_matched_options)}' \n" + \
                 f"ballot_id:{ballot_id} contest:{contest} metrics:'{', '.join(non_matched_metrics)}'"
        utils.exception_report(string)
    return success_flag, specified_dict, writein_dict
    
def normalize_ev_coord_str(ev_coord_str):
    """ Sometimes the ev_coord_str is changed to integer and leading zero is omitted 
        Format is XXYYPS. Sometimes changed to XYYPS
    """
    ev_coord_str = str(ev_coord_str)
    ev_coord_str = re.sub(r"^'", '', ev_coord_str)
    ev_coord_str = re.sub(r"'$", '', ev_coord_str)
    if len(ev_coord_str) < 6:
        ev_coord_str = '0'+ev_coord_str     # prepend the zero character
    return ev_coord_str
    
def normalize_ev_coord_str_list(ev_coord_str_list):
    for idx in range(len(ev_coord_str_list)):
        ev_coord_str_list[idx] = normalize_ev_coord_str(ev_coord_str_list[idx])
    return ev_coord_str_list
    
    
def flatten_selected_options(ev_contests):
    """ given ev_contests, which is list of dicts, each with two components: 
            'ocr_contestname': the name of the contest and 
            'ocr_names': the options.
        concatenate all the ocr_names and then drop all 'NO SELECTION MADE' options
        return the list.
    """
    undervote_str = 'NO SELECTION MADE'
    ev_fuzzy_thres_no_selection = 0.80   # config_dict['fuzzy_thres']['ev_fuzzy_thres_no_selection']
    
    ocr_options = []
    for idx in range(len(ev_contests)):
        ocr_options.extend(ev_contests[idx]['ocr_names'])
        
    filtered_ocr_options = []
    for ocr_option in ocr_options:
    
        match_flag, _ = fuzzy_compare_str(
            undervote_str, 
            ocr_option,
            ev_fuzzy_thres_no_selection,
            justify='right')
        if match_flag: continue
        filtered_ocr_options.append(ocr_option)
        
    return filtered_ocr_options
        
    
def extract_marks_from_barcodes(ballot, style_rois_map_df: pd.DataFrame) -> list:
    """ failed to parse OCR to create page_marks_lod, but barcodes may exist.
        if the rois_map has been filled in with barcodes from earlier ballots, 
        then we can use them to complete the page_marks_lod
        
        algorithm:
        ballot contains 'ev_coord_str_list' which is the list of barcodes.
        walk through the style_rois_map_df and build page_marks_lod
        also have the list of ev_coord_str values.
        
        for each contest, build a contest header no matter what.
            for each option listed in style_rois_map:
                if ev_coord_str is found in 'ev_coord_str_list'
                    build a page_marks_lod record and append.
        
        if everything goes well, return the page_marks_lod, else None.        
    """
    ballot_id = ballot.ballotdict['ballot_id']
    utils.sts(f"Processing ExpressVote Ballot ID:{ballot_id} using barcode data", 3)
    #import pdb; pdb.set_trace()
    page_marks_lod = []
    ev_coord_str_list = ballot.ballotdict['ev_coord_str_list']                  # working copy of barcodes from this ballot (already normalized)
    if not ev_coord_str_list:
        if ballot.ballotdict['ev_num_marks'] > 0:
            string = "### EXCEPTION: no barcodes provided and num marks " \
                    + f"does not match value:{ballot.ballotdict['ev_num_marks']} in ev header for ballot_id:{ballot_id} " \
                    + f"Some barcodes not found in rois_map:{', '.join(ev_coord_str_list)}"
            utils.exception_report(string)
            return []
    
    ev_coord_str_list_mutated = ev_coord_str_list.copy()                        # we remove options found from this mutated list to make sure we found them all
    ocr_options = flatten_selected_options(ballot.ballotdict['ev_contests'])    # list of options may not be usable but we will try to use for writeins.
    option_num = 0

    for idx in range(len(style_rois_map_df.index)):
        page_rois_dict = style_rois_map_df.iloc[idx]

        contest = page_rois_dict['contest']
        option = page_rois_dict['option']
        
        marks_dict = create_empty_marks_dict()

        marks_dict['ballot_id']         = ballot_id
        marks_dict['style_num']         = ballot.ballotdict['style_num']
        marks_dict['precinct']          = ballot.ballotdict['precinct']
        marks_dict['contest']           = contest
        marks_dict['option']            = option
        marks_dict['ev_precinct_id']    = ballot.ballotdict['ev_precinct_id']

        if option.startswith(r'#'):
            # contest header uses option starting with #, initialize parsing the next contest.
            page_marks_lod.append(marks_dict)   # this appends the contest header
            continue

        if not ev_coord_str_list_mutated:
            # already found all options as indicted by barcodes
            continue    # we can't break here because we need to fill in all the contest headers.

        this_option_ev_coord_str = normalize_ev_coord_str(page_rois_dict['ev_coord_str'])
        # the barcode value for this option determined during template generation,
        # normalization deals with possible leading zero that might be missing if encoded as integer.
        # and removal of extra quotes to try to keep those zeros.
        
        utils.sts(f"Looking for option [{this_option_ev_coord_str}] in {ev_coord_str_list}", 3)
        
        try:
            ev_coord_idx = ev_coord_str_list.index(this_option_ev_coord_str)
            # important, cannot use the mutated list above so we can access a possible writein name.
        except ValueError:
            # this rois_map entry not selected in this ballot.
            # this case is not unusual
            utils.sts("Not found", 3)
            continue
            
        # we found barcode value for this option.
        utils.sts(f"Found at index {ev_coord_idx}", 3)
        marks_dict['has_indication'] = 'DefiniteMark'
        marks_dict['num_marks'] = 1
        marks_dict['pixel_metric_value'] = 100
        marks_dict['ev_coord_str'] = this_option_ev_coord_str
        if option.startswith('writein'):
            try:
                writein_name = ocr_options[ev_coord_idx]
                marks_dict['writein_name'] = writein_name 
            except:
                pass
        ev_coord_str_list_mutated.remove(this_option_ev_coord_str)
        page_marks_lod.append(marks_dict)
        option_num += 1
    
    if len(ev_coord_str_list_mutated) or not option_num == ballot.ballotdict['ev_num_marks']:
        # this exception will be hit if the style_rois_map does not exist.
        # That can happen if no hand-marked ballots exist in the precinct, i.e. if they are all
        # ev ballots. We can't extract the barcodes if we don't know the ev_coord_str values for each option.
        
        string = f"### EXCEPTION: number of options found:{option_num} " \
                + f"does not match value:{ballot.ballotdict['ev_num_marks']} in ev header for ballot_id:{ballot_id}\n" \
                + f"Some barcodes not found in rois_map:{', '.join(ev_coord_str_list_mutated)}\n" \
                + "Possibly [Known_Limitation_001]: BMD ballots cannot be converted with no nonBMD ballots"
        utils.exception_report(string)
    return page_marks_lod
    
    
def create_empty_marks_dict():
    marks_dict = {
        'ballot_id':'', 
        'style_num':'', 
        'precinct':'', 
        'contest':'', 
        'option':'', 
        'has_indication':'',
        'num_marks': 0, 
        'num_votes': 0, 
        'pixel_metric_value': 0,
        'writein_name': '', 
        'overvotes': 0, 
        'undervotes': 0, 
        'ssidx': 0,                     # allows multiple instances of the same marks record for adjudication
        'delta_y': 0,                   # adjustment due to possible stretching of image
        'ev_coord_str': '',             # barcode str provided for this vote x,y coords for this option.
        'ev_precinct_id': '',           # numeric precinct id from barcode
        }
    return marks_dict
    
def create_empty_marks_df():
    marks_dict = create_empty_marks_dict()
    marks_df = pd.DataFrame(columns=marks_dict.keys())
    return marks_df


def print_marks_dict_contest(marks_dict):
    """ print given marks dict as one-liner starting at contest """

    if marks_dict['option'].startswith('#'):
        # contest header
        string = "%40s %20s OV:%1u UV:%1u" % \
            (marks_dict['contest'][:40], marks_dict['option'][:20], marks_dict['overvotes'], marks_dict['undervotes'])
    else:
        string = "%40s %20s           ADJ:%3.1d V:%1u M:%1u PMV:%4.1d IND:%s" % \
            (marks_dict['contest'][:40], marks_dict['option'][:20], marks_dict['delta_y'], \
            marks_dict['num_votes'], marks_dict['num_marks'], \
            marks_dict['pixel_metric_value'], marks_dict['has_indication'][:1])

    utils.sts(string, 3)

def print_contest_marks_lod(contest_marks_lod):
    for marks_dict in contest_marks_lod:
        print_marks_dict_contest(marks_dict)

def get_pixel_metric_value(argsdict:dict, image: np.ndarray, target_x, target_y, ballot_id, idx, contestoption) -> int:
    """ Analyzes target location using pixel metric value approach.
        image: full image of one side of page.
        target_x, target_y: distortion corrected image coordinates.
        ballot_id: used only for status and debugging messages.
        :return: pixel_metric_value
    """
    if target_y is None or target_x is None:
        utils.exception_report("Unexpected condition. target_x and target_y should be defined.")
        import pdb; pdb.set_trace()

    layout_params = get_layout_params(argsdict)
    target_w_os = round(layout_params['target_area_w'] / 2 )
    target_h_os = round(layout_params['target_area_h'] / 2 )

    target_area = image[
        int(target_y - target_h_os) : int(target_y + target_h_os),
        int(target_x - target_w_os) : int(target_x + target_w_os)
        ].copy()

    _, target_area_thresh = cv2.threshold(target_area, 170, 255, 1)

    pixel_metric_value = cv2.countNonZero(target_area_thresh)

    if args.argsdict.get('save_mark_images', False):
        # marks/ballots/{ballotid}/{ballotid}-{part_name}.png
        DB.save_one_image_area_dirname(
            dirname='marks', 
            subdir=f"ballots/{ballot_id}",
            style_num=ballot_id, 
            idx=idx, 
            type_str=contestoption, 
            image=target_area_thresh)

    return pixel_metric_value
    
def det_adaptive_thresholds(pmv_list):
    """
    Algorithm:
    1. Given list of pixel metric values from an entire side of a ballot
    2. sort these by value.
    3. remove all 0 values in case they were left in (or all metric values are provided in testing)
    4. test range of marks > min_range_for_any_marks to evaluate if the ballot is blank. If blank return defauls.
    5. create list of all gaps between each sequential value.
    6. look for the first large gap that is larger than fraction of max value OR
       sufficiently over the incremental mean of prior values.
    7. set the thresholds in the center of this gap.
    """

    first_gap_frac_of_max = 0.50
    first_gap_delta_over_incmean = 50
    min_range_for_any_marks = 80

    # the following are default values.
    marginal_thres = 200
    definite_thres = 245

    # eliminate all zero values; zeros are found in contest headers and may already be removed.
    filter_zeros = [i for i in pmv_list if i != 0]
    if not filter_zeros:
        return [marginal_thres, definite_thres]

    pmv_list.sort()
    full_range = pmv_list[-1] - pmv_list[0]
    if full_range < min_range_for_any_marks:
        # range of pixel values does not meet criteria that ballot is not blank.
        # probably blank ballot, return defaults
        return [marginal_thres, definite_thres]

    # make a list of all the incremental gaps
    gaps_list = []
    for idx in range(len(pmv_list)-1):
        gaps_list.append(round(pmv_list[idx+1] - pmv_list[idx], 2))

    # the first big gap may not be the max, but it will be at least x% the max.
    # most of the time, the first gap is the max. But sometimes there is another
    # max which is almost the same but a little bigger. So we need to make sure 
    # we are seeing the first big gap. Just taking the max gap does not always
    # work because sometimes there is a big gap at the very end.
    big_gap_threshold = max(gaps_list) * first_gap_frac_of_max

    thres_list = [0, 0]
    for idx in range(2, len(gaps_list)):
        prior_incrmean = statistics.mean(gaps_list[0:(idx-1)])    # do not include this value in the mean

        if not thres_list[0] and gaps_list[idx] > big_gap_threshold:
            # The gap at index is likely the separation between no-marks and marks.
            # this is the more stringent requirement generally
            thres_list[0] = pmv_list[idx] + gaps_list[idx] / 2

        if not thres_list[1] and gaps_list[idx] > (first_gap_delta_over_incmean + prior_incrmean):
            # The gap at index is likely the separation between no-marks and marks.
            # this is the more lenient requirement generally
            thres_list[1] = pmv_list[idx] + gaps_list[idx] / 2

        if thres_list[0] and thres_list[1]:
            break

    thres_list.sort()
    if not thres_list[1]:
        # no thresholds found. return defaults
        return [marginal_thres, definite_thres]

    if not thres_list[0]:
        thres_list[0] = thres_list[1]-1
    return thres_list
            


def evaluate_thresholds(ballot, page_marks_lod):
    """
    This function evaluates the marks on a ballot and classifies them as
    DefiniteMark, MarginalMark, or NoMark using an adaptive threshold method.

    Because of differences in scanning,
    it is necessary to compare with all the targets on the ballot to get an
    idea of what the threshold should be.

    page_marks_lod: a list of dicts where each one is a marks_dict record.

    modifies page_marks_lod in place.
    """

    # first determine the thresholds:
    # skip first entry which is the contest header
    pmv_list = [d['pixel_metric_value'] for d in page_marks_lod if not d['option'].startswith('#')]
    
    marginal_thres, definite_thres = det_adaptive_thresholds(pmv_list)

    for marks_dict in page_marks_lod:
        if marks_dict['option'].startswith('#'): continue

        pixel_metric_value = marks_dict['pixel_metric_value']

        if pixel_metric_value < marginal_thres:
            marks_dict['has_indication'] = 'NoMark'
            marks_dict['num_marks'] = 0
        elif pixel_metric_value < definite_thres:
            marks_dict['has_indication'] = 'MarginalMark'
            marks_dict['num_marks'] = 0
        else:
            marks_dict['has_indication'] = 'DefiniteMark'
            marks_dict['num_marks'] = 1

    utils.sts(f"Thresholds set to {marginal_thres} and {definite_thres}", 3)

    ballot.ballotdict['marginal_thres'] = marginal_thres
    ballot.ballotdict['definite_thres'] = definite_thres


def split_lod_to_lolod_by_field(lod, field):
    lolod = [[]]
    previous_value = None
    lolod_idx = 0
    for idx, d in enumerate(lod):
        if idx and not d[field] == previous_value:
            lolod_idx += 1
            lolod.append([])
        lolod[lolod_idx].append(d)
        previous_value = d[field]
    return lolod


def get_votefor(marks_dict):
    """ get the votefor value for this contest based on the marks_dict of the contest header.
        currently, this is done through a hack of the option name
    """
    option_field = marks_dict['option']
    return get_votefor_from_option_field(option_field)
    
def get_votefor_from_option_field(option_field):
    match = re.search(r'vote_for\s*=\s*(\d+)', option_field)
    if not match:
        print (f"Could not find 'vote_for' in contest header: {option_field}")
        sys.exit(1)
    votefor = int(match.group(1))
    return votefor

def get_bmd_contest_name(contest_dict, contest, ballot_id):
    """ given contest_dict which is from the contests_dod, provide the 'bmd_contest_name'
        if it is available. If not, produce an exception report. parameter ballot_id
        is passed only for the exception report.
    """
    bmd_contest_name = contest_dict.get('bmd_contest_name','')
    if not bmd_contest_name:
        string = f"### EXCEPTION: Could not locate bmd_contest_name for contest:{contest} in EIF " \
                 + f"for ballot_id: {ballot_id}"
        utils.exception_report(string)
        # default to using the official contest name
        bmd_contest_name = contest
    return bmd_contest_name


def evaluate_votes_in_contest(contest_marks_lod):
    """
    evaluate the votes in a contest.
    1. get votefor from header line.
    2. tot_marks = sum(num_marks) in rest of the dicts
    3. if tot_marks > votefor, overvote situation
        set overvotes = 1 in header line, return
    4. if tot_marks < votefor,
        select party-line option if there is only one matching party directive.
       else undervotes = votefor - tot_marks
    5. set num_votes = num_marks for each lod entry
    """
    #import pdb; pdb.set_trace()
    tot_num_marks = sum(int(d['num_marks']) for d in contest_marks_lod[1:])
    votefor = get_votefor(contest_marks_lod[0])

    if tot_num_marks > votefor:
        # overvote condition
        # marginal marks are initially regarded as nonmarks to bias toward 
        # not triggering the overvote condition.
        contest_marks_lod[0]['overvotes'] = 1
        # the following is normally redundant, but is a safety precaution.
        for idx in range(1, len(contest_marks_lod)):
            contest_marks_lod[idx]['num_votes'] = 0
            
    else:
        if tot_num_marks < votefor:
            # undervote condition
            
            # handle marginal marks in undervote condition
            # check for marginal marks and accept them if it does not cause overvote
            for idx in range(1, len(contest_marks_lod)):
                if contest_marks_lod[idx]['has_indication'] == 'MarginalMark':
                    contest_marks_lod[idx]['num_marks'] = 1
                    tot_num_marks += 1
                    if tot_num_marks >= votefor: break
                    
        #if tot_num_marks == 0:
        #    adjust_undervotes_for_partyline_default(ballot, ballot_marks_lod, votefor)
            
        if tot_num_marks < votefor:
            contest_marks_lod[0]['undervotes'] = votefor - tot_num_marks

        for idx in range(1, len(contest_marks_lod)):
            contest_marks_lod[idx]['num_votes'] = contest_marks_lod[idx]['num_marks']


def adjust_undervotes_for_partyline_default(ballot, ballot_marks_lod, votefor):
    # this is not yet implemented and will likely need a default vote in the ballot_marks_lod 
    # that can be assigned.
    pass

def evaluate_votes_on_ballot(ballot_marks_lod):
    """
    This function converts marks to votes on a ballot.
    A ballot must be processed due to the possibility of party-line voting.
    At this time, there is no support for party-line voting, however.

    ballot_marks_lod: a list of dicts where each one is a marks_df record.
    1. vote_for=n is expected in the contest header.
    2. get total marks in the contest.
    3. calculate the overvotes and undervotes, and writes them in the contest header
    4. if contest is overvoted, then leave num_votes as 0, else copy num_marks for each candidate.
    5. Also prints the contest
    """

    # This first part would determine a party-line vote that might be applied.
    # Would need more information to know now this would be extracted from a given ballot.

    # Next step is to break the ballot_marks_lod into contests.

    ballot_marks_lolod = split_lod_to_lolod_by_field(ballot_marks_lod, 'contest')
    
    for contest_marks_lod in ballot_marks_lolod:
        evaluate_votes_in_contest(contest_marks_lod)

def adjust_target_loc(target_x, target_y, style_page_timing_marks, layout_params):
    """ Given target_x and target_y, return adjusted versions according to 
        style_page_timing_marks and layout_params. Returns adjusted target_x and target_y
        @@ This method to adjust target location cannot deal with large distortions.
            Could correct it by checking index of timing mark in template and comparing with
            the index of the target synced to and if incorrect, correcting to the right one.
    """
    
    adjusted_x, adjusted_y = target_x, target_y
    
    if not style_page_timing_marks is None and style_page_timing_marks['left_vertical_marks']:
        # based on timing vector, correct target_y
        v_mid_marks = create_midmarks_list(style_page_timing_marks, 'v')
        adjusted_y = min(v_mid_marks, key=lambda y:abs(y-target_y))     # returns the closest mid_mark

    if layout_params.get('adjust_target_x', False) and not style_page_timing_marks is None and style_page_timing_marks['top_marks']:
        # based on timing vector, correct target_x
        
        h_mid_marks = create_midmarks_list(style_page_timing_marks, 'h')
        adjusted_x = min(h_mid_marks, key=lambda x:abs(x-target_x))     # returns the closest mid_mark

    return adjusted_x, adjusted_y


def get_target_coords(page_rois_dict: dict, ballot, page: int, layout_params) -> tuple:
    """ get and adjust target coords for rois 
        note that this is used during vote extraction.
    """
         
    # The majority of target location determination is done during maprois.
    # Here, the calculated target_x and _y are adjusted to the specific timing
    # marks on this ballot, if timing marks were successfully extracted.
    
    if math.isnan(page_rois_dict['target_x']) or math.isnan(page_rois_dict['target_y']):
        # sometimes the map does not have proposed target_x and target_y values. This is actually a logic error.
        # @@ better would be to use the same function as is used in maprois to redo these if they are not
        # available. Because this is a logic error, we will also record it as an exception.
        
        utils.exception_report("WARN: get_target_coords: target_x or target_y not available in rois_map during extraction")
        
        # this assumes calculation from top left corner which is not always the case.
        _, x, y, _, _ = page_rois_dict['roi_coord_csv'].split(r',')
        target_x = 36 + int(x)
        target_y = 26 + int(y)

    else:
        target_x = int(page_rois_dict['target_x'])
        target_y = int(page_rois_dict['target_y'])  # normally, target_y is determined during genrois phase

    delta_x = 0
    adjusted_x = target_x
    delta_y = 0
    adjusted_y = target_y

    try:
        ballot_timing_marks = ballot.ballotdict.get('timing_marks')       
        page_timing_marks = ballot_timing_marks[page]
    except:
        return adjusted_x, adjusted_y, delta_x, delta_y
        
    # @@ This syncing method cannot deal with very large distortions.
    adjusted_x, adjusted_y = adjust_target_loc(target_x, target_y, page_timing_marks, layout_params)
    
    delta_x = adjusted_x - target_x   # adjustment used to correct the location, frequently negative
    delta_y = adjusted_y - target_y   # adjustment used to correct the location, frequently negative
            
    return adjusted_x, adjusted_y, delta_x, delta_y

def create_midgap_list(style_dict: dict, page: int) -> list:
    """ Given timing marks in style_dict, provide standard midgaps.
        midgaps are the y pixel coordinates of the gaps which 
        are numbered starting at zero prior to the first timing mark.
        midgaps are used to locate possible horizontal lines.
    """

    v_marks = style_dict['timing_marks'][page]['left_vertical_marks']
    midgaps = [round((v_marks[i]['y']+v_marks[i-1]['y']+v_marks[i-1]['h'])/2) for i in range(1,len(v_marks))]
    #num_gaps = len(midgaps)
    try:
        period  = midgaps[1] - midgaps[0]
    except IndexError:
        return []
    
    # extend gaps list to before first timing mark and after last timing mark.
    midgaps.append(midgaps[-1] + period)
    midgaps.insert(0, midgaps[0] - period)

    #utils.sts(f"v_marks:{v_marks}\nmidgaps:{midgaps}", 3)
    
    return midgaps
    
def create_midmarks_list(page_timing_marks: dict, h_or_v = 'v') -> list:
    """ Given timing marks from style_dict or ballot instance, provide standard midgaps.
        midgaps are the y pixel coordinates of the gaps which 
        are numbered starting at zero prior to the first timing mark.
    """

    if h_or_v == 'v':
        v_marks = page_timing_marks['left_vertical_marks']
        midmarks = [(v_marks[i]['y'] + round(v_marks[i]['h']/2)) for i in range(len(v_marks))]
    else:
        h_marks = page_timing_marks['top_marks']
        midmarks = [(h_marks[i]['x'] + round(h_marks[i]['w']/2)) for i in range(len(h_marks))]
    return midmarks
    
def analyze_one_image_by_page_rois_map_df(argsdict, ballot, page, page_rois_map_df, page_marks_lod, layout_params):
    """
    extract votes as specified in page_rois_map_df from one image.
    This function does NOT evaluate overvotes nor determine ultimate votes for ballot
    which must be done at the higher level, at both a ballot and contest level
    This function is blind to contest and option, and just deals with the marks.
    Also does not threshold the marks.
    returns page_marks_df
    """
    
    ballot_id = ballot.ballotdict['ballot_id']
    
    # images already have been aligned.
    try:
        image = ballot.ballotimgdict['images'][page]
    except:
        utils.exception_report(f"Image for ballot:{ballot_id} page:{page} is unexpectedly missing. Extraction aborted.")
        return

    # note, timing_marks are updated in ballot prior to this function.

    # now evaluate each of the marks on the current ballot based on the style_rois_map_df
    # rois_map_df has the following columns: ROISMAP_COLUMNS

    for idx in range(len(page_rois_map_df.index)):
        page_rois_dict = page_rois_map_df.iloc[idx]

        contest = page_rois_dict['contest']
        option = page_rois_dict['option']
        
        #if ballot_id == '151798' and \
        #    contest == 'Madison Metropolitan Board Member Seat 3' and \
        #    option == 'writein_0':
        #    import pdb; pdb.set_trace()

        marks_dict = create_empty_marks_dict()
        
        marks_dict['ballot_id']         = ballot_id
        marks_dict['style_num']         = ballot.ballotdict['style_num']
        marks_dict['precinct']          = ballot.ballotdict['precinct']
        marks_dict['contest']           = contest
        marks_dict['option']            = option
        marks_dict['ev_precinct_id']    = 0

        if bool(re.match(r'#', option)):
            # contest header, just add it to page_marks_lod.
            page_marks_lod.append(marks_dict)
            continue

        # use the timing marks derived for the ballot and adjust the timing marks.
        adjusted_x, adjusted_y, delta_x, delta_y = get_target_coords(page_rois_dict, ballot, page, layout_params)
        marks_dict['delta_y'] = delta_y

        marks_dict['pixel_metric_value'] = \
            get_pixel_metric_value(argsdict, image, adjusted_x, adjusted_y,
                ballot_id, idx, f"{option[:20]}")
        """ returns pixel_metric_value
            Please note that marks are not evaluated regarding voting rules
            to create overvotes, undervotes, etc. however, this does implement
            adaptive thresholding.
        """
        page_marks_lod.append(marks_dict)
        # add all records to the df at this point. We need even unmarked records 
        # to allow adaptive thresholding.


def analyze_images_by_style_rois_map_df(argsdict: dict, ballot, style_rois_map_df):
    """
    Given ballot images and style_rois_map_df which applies to this style:
    process image only if it is called for in the rois_map_df

    For each contest and option line, access roi of ballot and interpret
    the mark. Add record to the marks_df for each contest/option pair.
    return newly built marks_df which refers only to this ballot.
    """
    ballot_marks_lod = []
    page_mode_thresholds = False    # if True, evaluate one page at a time, else include both pages.
    layout_params = get_layout_params(argsdict)     
    # note that page and sheet not passed as those are only used params used in genrois.


    for page in range(2):
        # process images only if we have marks to extract
        page_rois_map_df = style_rois_map_df.loc[(style_rois_map_df['p'] == int(page))]
        if page_rois_map_df.empty:
            continue
        page_marks_lod = []
        
        analyze_one_image_by_page_rois_map_df(argsdict, ballot, page, page_rois_map_df, page_marks_lod, layout_params)

        # thresholds must be evaluated on an image-by-image basis
        # to take into account the relative density of the image
        if page_mode_thresholds:
            # calculating thresholds on single page basis instead of by full ballot makes some sense
            # because the density of each side may be different. However, the adaptive thresholding is
            # also related to the habits of the voter. In testing also, it was found that frequently on 
            # side 2, there is only one or two contests and it is too few to be included in the calculations.
            evaluate_thresholds(ballot, page_marks_lod)

        ballot_marks_lod.extend(page_marks_lod)

    if not page_mode_thresholds:
        # calculate thresholds on both pages at one time.
        evaluate_thresholds(ballot, ballot_marks_lod)
        
    # overvotes must be evaluated on a ballot-basis in case of party-line voting
    # otherwise, they are analyzed on contest basis.
    evaluate_votes_on_ballot(ballot_marks_lod)

    print_contest_marks_lod(ballot_marks_lod)

    # create dataframe and save it.
    ballot_marks_df = create_empty_marks_df()
    ballot_marks_df = ballot_marks_df.append(ballot_marks_lod, ignore_index=True)

    ballot.ballotdict['marks_df'] = ballot_marks_df

    return ballot_marks_df

