if __name__ != "__main__":
    from utilities import utils, logs

"""
ES&S Timing-mark Barcode on HMBP.

This was defined by reverse engineering the ES&S style code found along
the left edge.
Confirmed for most values up to 208.
It may be better to have a fixed conversion dict and simple lookup
but not all intervening values have been confirmed and there are several
valid barcodes for a given style number.
"""

#    0x3100c14400002


# 8321 842184 2184 21
CVT_STYLE_SEQUENCES = [
                           # FFFF         
    [0x003C, 0x0020, 1],   # xxxx xxxx_xx 10_00 00
    [0x003C, 0x0010, 2],   # xxxx XXXX_XX 01_00 00 
    [0x003C, 0x0008, 3],   # xxxx XXXX_XX 00_10 00
    [0x003C, 0x0004, 4],   # xxxx XXXX_XX 00_01 00

    [0x0FC0, 0x0800, 4],   # xxxx 100000 XXXX
    [0x0FC0, 0x0400, 8],   # xxxx 010000 XXXX
    [0x0FC0, 0x0200, 12],  # xxxx 001000 XXXX
    [0x0FC0, 0x0100, 16],  # xxxx 000100 XXXX
    [0x0FC0, 0x0080, 20],  # xxxx 000010 xxxx
    [0x0FC0, 0x0040, 24],  # xxxx 000001 xxxx
    [0x0FC0, 0x0C00, 28],  # xxxx 110000 xxxx
    [0x0FC0, 0x0A00, 32],  # xxxx 101000 xxxx
    [0x0FC0, 0x0900, 36],  # xxxx 100100 xxxx
    [0x0FC0, 0x0880, 40],  # xxxx 100010 xxxx
    [0x0FC0, 0x0840, 44],  # xxxx 100001 xxxx
    [0x0FC0, 0x0600, 48],  # xxxx 011000 xxxx
    [0x0FC0, 0x0500, 52],  # xxxx 010100 xxxx
    [0x0FC0, 0x0480, 56],  # xxxx 010010 xxxx
    [0x0FC0, 0x0440, 60],  # xxxx 010001 xxxx
    [0x0FC0, 0x0300, 64],  # xxxx 001100 xxxx
    [0x0FC0, 0x0280, 68],  # xxxx 001010 xxxx
    [0x0FC0, 0x0240, 72],  # xxxx 001001 xxxx
    [0x0FC0, 0x0180, 76],  # xxxx 000110 xxxx
    [0x0FC0, 0x0140, 80],  # xxxx 000101 xxxx
    [0x0FC0, 0x00C0, 84],  # xxxx 000011 xxxx

    # xxx1 xxxxxx xxxx This bit is used to respect total bits set
    # is 5 of 14
    # [0x1000, '0x1000, 0],
    [0xE000, 0xc000, 24],  # 110x xxxxxx xxxx
    [0xE000, 0xa000, 108],  # 101x xxxxxx xxxx
    [0xE000, 0x8000, 168],  # 100x xxxxxx xxxx
    [0xE000, 0x6000, 252],  # 011x xxxxxx xxxx  # this is a guess
    [0xE000, 0x2000, 336],  # 001x xxxxxx xxxx  # this is a guess​
]


def get_core_style_code(hex_code: int) -> int:
    """Takes the hex code and bitwise shifts it right 20 bits.
    Then returns the result of shift with bitwise and operation
    with '0xFFFF'.
    :param hex_code: Hex number represented as integer.
    :return: Representation of hex number in integer.
    """
    return (hex_code >> 20) & 0xFFFF  # pull out 16 bits starting at bit 20 -- omit right 5 hex 0's


def translate_hex_code(core_hex_code: int) -> int:
    """Translates hex representation of style code to decimal.
    :param core_hex_code: Hex number represented as integer.
    :return: Style number represented as decimal.
    """
    style_number = 0
    for sequence in CVT_STYLE_SEQUENCES:
        if (core_hex_code & sequence[0]) == sequence[1]:
            style_number += sequence[2]
    return style_number

PARTY_DICT = {
    '21': 0,
    '31': 1,
    '29': 2,
    '25': 3,
    '23': 4
    }

def get_parsed_barcode(hex_code_str: str, ballot_id: str='', precinct: str='') -> int:
    """Takes the hex representation of the left side barcode found
    on the ballot and parses it to the decimal representation.
    :param hex_code_str: Hex number value provided as string 0xHHHHHHHHHHHHH
    'param ballot_id, precinct optional for exception report only.
    :return: Style number represented as decimal.
    """
    if not hex_code_str: return None
    
    hex_code = int(hex_code_str, 0)     # base of zero causes base guessing behavior.
    ones = bin(hex_code).count('1')
    if not ones & 1:
        # even number of ones is not allowed.
        string = f"### WARNING: parity error in card_code: " \
                f"ballot_id:'{ballot_id}' Precinct:'{precinct}'\n" \
                f"card_code:'{hex_code_str}' probably misread."
        if __name__ != "__main__":
            utils.exception_report(string)
        else:
            print (string)
        return None
        
    core_style_code = get_core_style_code(hex_code)
    style_num = translate_hex_code(core_style_code)
    
    if int(style_num) > 211:
        string = f"### WARNING: Known_Limitation_002: converted style number " \
                "is out of range. result is not certain but may be okay. " \
                f"balot_id:'{ballot_id}' Precinct:'{precinct}\n" \
                f"card_code:'{hex_code_str}' calculated style_num '{style_num}'"
        if __name__ != "__main__":
            utils.exception_report(string)
        else:
            print (string)
        return None
        
    # in most cases, the upper portion of card code is always 0x21
    # however, if not, then party can be encoded here.
        
    partydigits = hex_code_str[2:4]
    try:
        party = PARTY_DICT[partydigits]
        style_num = party*1000 + style_num
    except IndexError:
        string = f"### WARNING: upper digits of card code: encoding unexpected. " \
                f"balot_id:'{ballot_id}' Precinct:'{precinct}\n" \
                f"card_code '{hex_code_str}' calculated style_num '{style_num}'"
        if __name__ != "__main__":
            utils.exception_report(string)
        
        
    return style_num
    
def test_get_parsed_barcode():
    
    utils.sts("Testing barcode parsing: ", 3, end='')
    errors = 0
    for test_tuple in TEST_CVT_STYLE_SEQUENCES:
        correct_style_int, hex_style_code_str = test_tuple
        if not hex_style_code_str: continue
        calc_style_int = get_parsed_barcode(hex_style_code_str) 
        if not calc_style_int == correct_style_int:
            errors += 1
            utils.sts(f"\nhex_style_code {hex_style_code_str} produced style_int {calc_style_int} expected {correct_style_int}", 3)
    utils.sts(f"{errors} errors", 3)      

TEST_CVT_STYLE_SEQUENCES = [
    (0, ''),
    (1, '0x2100f02000000'),
    (2, '0x2100f01000000'),
    (3, '0x2100f00800000'),
    (4, '0x2100f00400000'),
    (5, '0x2100e82000000'),
    (6, '0x2100e81000000'),
    (7, '0x2100e80800000'),
    (8, '0x2100e80400000'),
    (9, '0x2100e42000000'),
    (10, '0x2100e41000000'),
    (11, '0x2100e40800000'),
    (12, '0x2100e40400000'),
    (13, '0x2100e22000000'),
    (14, '0x2100e21000000'),
    (15, '0x2100e20800000'),
    (16, '0x2100e20400000'),
    (17, '0x2100e12000000'),
    (18, '0x2100e11000000'),
    (19, '0x2100e10800000'),
    (20, '0x2100e10400000'),
    (21, '0x2100e0a000000'),
    (22, '0x2100e09000000'),
    (23, '0x2100e08800000'),
    (24, '0x2100e08400000'),
    (25, '0x2100e06000000'),
    (26, '0x2100e05000000'),
    (27, '0x2100e04800000'),
    (28, '0x2100e04400000'),
    (29, '0x2100d82000000'),
    (30, '0x2100d81000000'),
    (31, '0x2100d80800000'),
    (32, '0x2100d80400000'),
    (33, '0x2100d42000000'),
    (34, '0x2100d41000000'),
    (35, '0x2100d40800000'),
    (36, '0x2100d40400000'),
    (37, '0x2100d22000000'),
    (38, '0x2100d21000000'),
    (39, '0x2100d20800000'),
    (40, '0x2100d20400000'),
    (41, '0x2100d12000000'),
    (42, '0x2100d11000000'),
    (43, '0x2100d10800000'),
    (44, '0x2100d10400000'),
    (45, '0x2100d0a000000'),
    (46, '0x2100d09000000'),
    (47, '0x2100d08800000'),
    (48, '0x2100d08400000'),
    (49, '0x2100d06000000'),
    (50, '0x2100d05000000'),
    (51, '0x2100d04800000'),
    (52, '0x2100d04400000'),
    (53, '0x2100cc2000000'),
    (54, '0x2100cc1000000'),
    (55, '0x2100cc0800000'),
    (56, '0x2100cc0400000'),
    (57, '0x2100ca2000000'),
    (58, '0x2100ca1000000'),
    (59, '0x2100ca0800000'),
    (60, '0x2100ca0400000'),
    (61, '0x2100c92000000'),
    (62, '0x2100c91000000'),
    (63, '0x2100c90800000'),
    (64, '0x2100c90400000'),
    (65, '0x2100c8a000000'),
    (66, '0x2100c89000000'),
    (67, '0x2100c88800000'),
    (68, '0x2100c88400000'),
    (69, '0x2100c86000000'),
    (70, '0x2100c85000000'),
    (71, '0x2100c84800000'),
    (72, '0x2100c84400000'),
    (73, '0x2100c62000000'),
    (74, '0x2100c61000000'),  # T Springdale Wds 1-2
    (75, '0x2100c60800000'),  # T Springdale Wds 1-2
    (76, '0x2100c60400000'),
    (77, ''),  # 77 T Springfield Wds 1-3
    (78, '0x2100c51000000'),
    (79, '0x2100c50800000'),
    (80, ''),  # 80  not in Dane 1,2
    (81, '0x2100c4a000000'),
    (82, '0x2100c49000000'),
    (83, '0x2100c48800000'),
    (84, '0x2100c48400000'),
    (85, '0x2100c46000000'),
    (86, '0x2100c45000000'),
    (87, '0x2100c44800000'),
    (88, '0x2100c44400000'),
    (89, '0x2100c32000000'),
    (90, '0x2100c31000000'),
    (91, '0x2100c30800000'),  # T York Wd 1
    (92, '0x2100c30400000'),  # T York Wd 1
    (93, '0x2100c2a000000'),  # T York Wd 1
    (94, '0x2100c29000000'),  # T York Wd 1
    (95, '0x2100c28800000'),  # V Belleville Wds 1-2
    (96, '0x2100c28400000'),
    (97, '0x2100c26000000'),
    (98, '0x2100c25000000'),  # V Brooklyn Wds 1,3
    (99, '0x2100c24800000'),
    (100, '0x2100c24400000'),  # V Cottage Grove Wds 1-12
    (101, '0x2100c1a000000'),  # V Cottage Grove Wds 1-12
    (102, '0x2100c19000000'),
    (103, '0x2100c18800000'),  # V Dane Wd 1
    (104, '0x2100c18400000'),  # V Deerfield Wds 1-3
    (105, '0x2100c16000000'),  # V DeForest Wds 1-6, 14-18, 21
    (106, '0x2100c15000000'),  # V Maple Bluff Wds 1-2
    (107, '0x2100c14800000'),
    (108, '0x2100c14400000'),  # V Mazomanie Wds 1-3
    (109, '0x2100c0e000000'),
    (110, '0x2100c0d000000'),  # V Mount Horeb Wds 1-4
    (111, '0x2100c0c800000'),  # V Oregon Wds 1, 5-6, 11, 13
    (112, '0x2100c0c400000'),  # V Rockdale Wd 1
    (113, '0x2100b82000000'),  # V Shorewood Hills Wds 1-2
    (114, '0x2100b81000000'),  # V Waunakee Wds 6-12
    (115, '0x2100b80800000'),
    (116, '0x2100b80400000'),
    (117, '0x2100b42000000'),  # 117 not in Dane 1, 2
    (118, '0x2100b41000000'),
    (119, '0x2100b40800000'),
    (120, '0x2100b40400000'),
    (121, '0x2100b22000000'),
    (122, '0x2100b21000000'),
    (123, '0x2100b20800000'),
    (124, '0x2100b20400000'),
    (125, '0x2100b12000000'),
    (126, '0x2100b11000000'),  # C Madison Wd 132
    (127, '0x2100b10800000'),  # C Madison Wd 001
    (128, '0x2100b10400000'),  # C Madison Wd 006
    (129, '0x2100b0a000000'),  # C Madison Wd 010
    (130, '0x2100b09000000'),  # C Madison Wd 008
    (131, '0x2100b08800000'),  # C Madison Wd 018
    (132, '0x2100b08400000'),  # C Madison Wd 014
    (133, '0x2100b06000000'),  # C Madison Wd 015
    (134, '0x2100b05000000'),  # C Madison Wd 026
    (135, '0x2100b04800000'),  # C Madison Wd 024
    (136, '0x2100b04400000'),  # C Madison Wd 026
    (137, '0x2100ac2000000'),  # C Madison Wd 033
    (138, '0x2100ac1000000'),  # C Madison Wd 028
    (139, '0x2100ac0800000'),  # C Madison Wd 038
    (140, '0x2100ac0400000'),  # C Madison Wd 036
    (141, '0x2100aa2000000'),  # C Madison Wd 038
    (142, '0x2100aa1000000'),  # C Madison Wd 043
    (143, '0x2100aa0800000'),
    (144, '0x2100aa0400000'),  # C Madison Wd 048
    (145, '0x2100a92000000'),
    (146, '0x2100a91000000'),  # C Madison Wd 055
    (147, '0x2100a90800000'),  # C Madison Wd 062
    (148, '0x2100a90400000'),
    (149, '0x2100a8a000000'),  # C Madison Wd 070
    (150, '0x2100a89000000'),  # C Madison Wd 075
    (151, '0x2100a88800000'),  # C Madison Wd 076
    (152, ''),  # 152 not in Dane 1,2
    (153, '0x2100a86000000'),
    (154, '0x2100a85000000'),  # C Madison Wd 081
    (155, '0x2100a84800000'),  # C Madison Wd 086
    (156, '0x2100a84400000'),  # C Madison Wd 090
    (157, '0x2100a62000000'),  # C Madison Wd 091
    (158, '0x2100a61000000'),  # C Madison Wd 095
    (159, '0x2100a60800000'),  # C Madison Wd 096
    (160, '0x2100a60400000'),  # C Madison Wd 096
    (161, '0x2100a52000000'),
    (162, ''),  # 162 not in Dane 1,2
    (163, '0x2100a50800000'),  # C Madison Wd 104
    (164, '0x2100a50400000'),  # C Madison Wd 102
    (165, '0x2100a4a000000'),  # C Madison Wd 102
    (166, '0x2100a49000000'),  # C Madison Wd 106, C Madison Wd 105
    (167, '0x2100a48800000'),
    (168, '0x2100a48400000'),  # C Madison Wd 107
    (169, ''),  # 169 not in Dane 1,2
    (170, ''),  # 170 not in Dane 1,2
    (171, ''),  # 171 not in Dane 1,2
    (172, ''),  # 172 not in Dane 1,2
    (173, ''),  # 173 not in Dane 1,2
    (174, ''),  # 174 not in Dane 1,2
    (175, '0x2100a30800000'),  # C Madison Wd 122
    (176, '0x2100a30400000'),  # C Madison Wd 121
    (177, ''),  # 177 not in Dane 1,2
    (178, '0x2100a29000000'),  # C Madison Wd 124
    (179, '0x2100a28800000'),  # C Madison Wd 126
    (180, ''),  # 180 not in Dane 1,2
    (181, ''),  # 181 not in Dane 1,2
    (182, ''),  # 182 not in Dane 1,2
    (183, '0x2100a24800000'),  # C Madison Wd 131
    (184, ''),  # 184 not in Dane 1,2
    (185, ''),  # 185 not in Dane 1,2
    (186, ''),  # 186 not in Dane 1,2
    (187, ''),  # C Madison Wd 142
    (188, ''),  # 188 not in Dane 1,2
    (189, ''),  # 189 not in Dane 1,2
    (190, '0x2100a15000000'),
    (191, '0x2100a14800000'),
    (192, '0x2100a14400000'),
    (193, '0x2100a0e000000'),
    (194, '0x2100a0d000000'),
    (195, '0x2100a0c800000'),
    (196, '0x2100a0c400000'),  # C Monona Wds 6-10
    (197, '0x21009c2000000'),  # C Stoughton Wds 1-2
    (198, '0x21009c1000000'),
    (199, '0x21009c0800000'),  # C Stoughton Wds 5-6
    (200, '0x21009c0400000'),  # C Stoughton Wds 7-9
    (201, '0x21009a2000000'),
    (202, '0x21009a1000000'),
    (203, '0x21009a0800000'),  # C Sun Prairie Wds 10-14, 20-22, 24-25
    (204, '0x21009a0400000'),  # C Sun Prairie Wds 15-19
    (205, '0x2100992000000'),  # C Verona Wds 1-5
    (206, '0x2100991000000'),
    (207, '0x2100990800000'),
    (208, '0x2100990400000'),
    (209, '0x210098a000000'),  # V Belleville Wd 3
    (210, '0x2100989000000'),  # V Brooklyn Wd 2
    (211, '0x2100988800000'),  # V Cambridge Wd 1
    
]

if __name__ == "__main__":
    import sys
    card_code = sys.argv[1]
    style_code = get_parsed_barcode(card_code)
    print(f"style code = {style_code}")