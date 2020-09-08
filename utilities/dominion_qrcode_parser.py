#from utilities import utils

from bitstring import BitArray

"""
Dominion QRCode Decoder on BMD ballots

This decoder was developed on the cases in San Francisco Nov 2018 election
which included rank-choice voting (RCV) method.
For this method, we treat each rank as a separate contest in terms of marks
generation, which can be later processed to determine the vote.
For BMD ballots, there is no concern for overvotes, but for HMPB, each rank
must be first treated as a separate contest to determine the votes on each.

QR Code is version 7, 45x45 dimension, providing 64 binary bytes with level H error correction.

Can test reading at https://online-barcode-reader.inliteresearch.com/


"""


def dominion_qrcode_decoder(qrcode_bytes):
    
    



    unknown0        = qrcode_bytes[0]                                           # 0     (0x00)
    unknown1        = qrcode_bytes[1]                                           # 1     (0x01)
    unknown2_int32  = int.from_bytes(qrcode_bytes[2:6], byteorder='little')     # 1     (0x0000 0001)
    precinct        = int.from_bytes(qrcode_bytes[6:10], byteorder='little')    # 9103  (0x0000 238f)
    unknown4        = qrcode_bytes[10]                                          # 2     (0x02)
    
    style1          = int.from_bytes(qrcode_bytes[11:15], byteorder='little')   # 401   (0x0000 0191)
    blklen1         = int.from_bytes(qrcode_bytes[15:17], byteorder='little')   # 19    (0x0013)  could be block length for style1 including length bytes.
    unknown7        = int.from_bytes(qrcode_bytes[17:19], byteorder='little')   # 13    (0x000d)  ?? total number of marks on this part of ballot is 14  #noqa
    binaryvotes1    = BitArray(bytes=qrcode_bytes[19:(19+blklen1-4)])
    
    style2          = int.from_bytes(qrcode_bytes[34:38], byteorder='little')   # 402   (0x0000 0192)
    blklen2         = int.from_bytes(qrcode_bytes[38:40], byteorder='little')   # 9     (0x0009)  could be block length for style2 including length bytes.
    unknown11       = int.from_bytes(qrcode_bytes[40:42], byteorder='little')   # 3     (0x0003)  ?? total marks on this part of ballot was 6   #noqa
    binaryvotes2    = BitArray(bytes=qrcode_bytes[42:(42+blklen2-4)])
    
    mayor_bits      = binaryvotes1[0:42]
    mayor_bitfield_by_rank = []
    
    numoptions = 7
    for rank in range(6):
        mayor_bitfield_by_rank.append(mayor_bits[(numoptions*rank):(numoptions*rank+numoptions)])
    

    # this block to trick lint
    unknown0 += 0
    unknown1 += 0
    unknown2_int32 += 0
    precinct += 0
    unknown4 += 0
    style1 += 0
    unknown7 += 0
    style2 += 0
    unknown11 += 0
    binaryvotes2 += 0




def test_dominion_qrcode_decoder():

    #                 0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
    qrcode_hexstr = ("00 01 01 00 00 00 8f 23 00 00 02 91 01 00 00 13 "
    #                u1 u2 |  u3      | precinct |    | style1  | u6

    #                16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31
                    "00 0d 00 04 22 00 42 08 20 02 22 21 00 80 40 00 "
    #                u6 |u7 | mayor (42bits) |

    #                32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47
                    "00 00 92 01 00 00 09 00 03 00 0a 2a 80 00 00 64 "
    #                      | style2   | u10 | u11 |

    #                48 49 50 51 52 53 54 55 56 57 58 59 60 61 62 63
                    "ab f7 99 fe ad 85 f4 13 91 6b 29 80 30 c3 76 43 "

    #                64 65 66 67 68 69 70 71 72 73 74 75 76 77 78 79
                    "91 e1 c1 e7 fb dc 6f 02 13 fb 11 72 c0 ca ff f3")
                    
    styles_contests_options = {
        '401': { 
            'Mayor': [
                'Joel Ventresca', 
                'Wilma Pang', 
                'Robert L. Jordan, Jr', 
                'Paul Ybarra Robertson',
                'Ellen Lee Zhou',
                'London N. Breed',
                'writein:',
                ],
            'City Attorney': [
                'Dennis J. Herrera',
                'writein:',
                'writein:',
                ],
            'District Attorney': [
                'Suzy Loftus',
                'Leif Dautch',
                'Nancy Tung',
                'Chesa Boudin',
                'writein:',
                ],
            'Public Defender': [
                'Manohar "Mano" Raju',
                'writein:',
                'writein:',
                ],
            'Sheriff': [
                'Paul Miyamoto',
                'writein:',
                'writein:',
                ],
            'Treasurer': [
                'Jose Cisneros',
                'writein:',
                'writein:',
                ],
            },
        '402': {
            'Member, Board of Education': [
                'Jenny Lam',
                'Kirsten Strobel',
                'Robert K. Coleman',
                'writein',
                ],
            'Member, Community College Board': [
                'Ivy Lee',
                'writein',
                ],
            'Proposition A': ['Yes', 'No'],
            'Proposition B': ['Yes', 'No'],
            'Proposition C': ['Yes', 'No'],
            'Proposition D': ['Yes', 'No'],
            'Proposition E': ['Yes', 'No'],
            'Proposition F': ['Yes', 'No'],
            }
        }
        
    qrcode_bytes  = bytes.fromhex(qrcode_hexstr)
    
    dominion_qrcode_decoder(qrcode_bytes, styles_contests_options)
    
    # The following example is from SF 2020 Pri, ballot_id:00005_00204_000030
    
    #                 0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
    qrcode_hexstr = ("00 01 02 00 00 00 4d 04 00 00 00 00 00 00 00 00"
    #                u1 u2 |  u3      | precinct |

    #                16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31
                    "02 01 00 00 00 0d 00 07 00 20 00 00 08 80 00 00"
    # 
                    
    #                32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47
                    "00 00 02 00 00 00 0b 00 05 00 04 28 95 55 00 00"
    #                

    #                48 49 50 51 52 53 54 55 56 57 58 59 60 61 62 63
                    "00 84 2f 02 75 39 00 7c c0 25 a3 00 fa aa 41 c8"

    #                64 65 66 67 68 69 70 71 72 73 74 75 76 77 78 79
                    "70 53 dd c9 cc 24 33 d3 95 92 51 20 67 b3 02 85"

    #                80 81
                    "d8 cf")
                    
    #               precinct = 0x0000044d => 1101
    
    """
            "Cards": [
          {
            "Id": 1,
            "KeyInId": 1,
            "PaperIndex": 0,
            "Contests": [
              {
                "Id": 7,
                "ManifestationId": 170376,
                "Undervotes": 0,
                "Overvotes": 0,
                "OutstackConditionIds": [],
                "Marks": [
                  {
                    "CandidateId": 15,
                    "ManifestationId": 672352,
                    "PartyId": 1,
                    "Rank": 1,
                    "MarkDensity": 0,
                    "IsAmbiguous": false,
                    "IsVote": true,
                    "OutstackConditionIds": []
                  }
                ]
              },
              {
                "Id": 22,
                "ManifestationId": 170377,
                "Undervotes": 8,
                "Overvotes": 0,
                "OutstackConditionIds": [
                  4
                ],
                "Marks": [
                  {
                    "CandidateId": 96,
                    "ManifestationId": 672378,
                    "PartyId": 1,
                    "Rank": 1,
                    "MarkDensity": 0,
                    "IsAmbiguous": false,
                    "IsVote": true,
                    "OutstackConditionIds": []
                  },
                  {
                    "CandidateId": 100,
                    "ManifestationId": 672382,
                    "PartyId": 1,
                    "Rank": 1,
                    "MarkDensity": 0,
                    "IsAmbiguous": false,
                    "IsVote": true,
                    "OutstackConditionIds": []
                  }
                ]
              }
            ],
            "OutstackConditionIds": []
          },
          {
            "Id": 2,
            "KeyInId": 2,
            "PaperIndex": 1,
            "Contests": [
              {
                "Id": 15,
                "ManifestationId": 170378,
                "Undervotes": 1,
                "Overvotes": 0,
                "OutstackConditionIds": [
                  4,
                  6
                ],
                "Marks": []
              },
              {
                "Id": 16,
                "ManifestationId": 170379,
                "Undervotes": 0,
                "Overvotes": 0,
                "OutstackConditionIds": [],
                "Marks": [
                  {
                    "CandidateId": 78,
                    "ManifestationId": 672407,
                    "PartyId": 1,
                    "Rank": 1,
                    "MarkDensity": 0,
                    "IsAmbiguous": false,
                    "IsVote": true,
                    "OutstackConditionIds": []
                  }
                ]
              },
              {
                "Id": 17,
                "ManifestationId": 170380,
                "Undervotes": 0,
                "Overvotes": 0,
                "OutstackConditionIds": [],
                "Marks": [
                  {
                    "CandidateId": 81,
                    "ManifestationId": 672412,
                    "PartyId": 1,
                    "Rank": 1,
                    "MarkDensity": 0,
                    "IsAmbiguous": false,
                    "IsVote": true,
                    "OutstackConditionIds": []
                  }
                ]
              },
              {
                "Id": 19,
                "ManifestationId": 170381,
                "Undervotes": 0,
                "Overvotes": 0,
                "OutstackConditionIds": [],
                "Marks": [
                  {
                    "CandidateId": 83,
                    "ManifestationId": 672414,
                    "PartyId": 0,
                    "Rank": 1,
                    "MarkDensity": 0,
                    "IsAmbiguous": false,
                    "IsVote": true,
                    "OutstackConditionIds": []
                  }
                ]
              },
              {
                "Id": 20,
                "ManifestationId": 170382,
                "Undervotes": 0,
                "Overvotes": 0,
                "OutstackConditionIds": [],
                "Marks": [
                  {
                    "CandidateId": 86,
                    "ManifestationId": 672418,
                    "PartyId": 0,
                    "Rank": 1,
                    "MarkDensity": 0,
                    "IsAmbiguous": false,
                    "IsVote": true,
                    "OutstackConditionIds": []
                  }
                ]
              },
              {
                "Id": 21,
                "ManifestationId": 170383,
                "Undervotes": 0,
                "Overvotes": 0,
                "OutstackConditionIds": [],
                "Marks": [
                  {
                    "CandidateId": 88,
                    "ManifestationId": 672421,
                    "PartyId": 0,
                    "Rank": 1,
                    "MarkDensity": 0,
                    "IsAmbiguous": false,
                    "IsVote": true,
                    "OutstackConditionIds": []
                  }
                ]
              },
              {
                "Id": 1,
                "ManifestationId": 170384,
                "Undervotes": 0,
                "Overvotes": 0,
                "OutstackConditionIds": [],
                "Marks": [
                  {
                    "CandidateId": 1,
                    "ManifestationId": 672423,
                    "PartyId": 0,
                    "Rank": 1,
                    "MarkDensity": 0,
                    "IsAmbiguous": false,
                    "IsVote": true,
                    "OutstackConditionIds": []
                  }
                ]
              },
              {
                "Id": 2,
                "ManifestationId": 170385,
                "Undervotes": 0,
                "Overvotes": 0,
                "OutstackConditionIds": [],
                "Marks": [
                  {
                    "CandidateId": 3,
                    "ManifestationId": 672425,
                    "PartyId": 0,
                    "Rank": 1,
                    "MarkDensity": 0,
                    "IsAmbiguous": false,
                    "IsVote": true,
                    "OutstackConditionIds": []
                  }
                ]
              },
              {
                "Id": 3,
                "ManifestationId": 170386,
                "Undervotes": 0,
                "Overvotes": 0,
                "OutstackConditionIds": [],
                "Marks": [
                  {
                    "CandidateId": 5,
                    "ManifestationId": 672427,
                    "PartyId": 0,
                    "Rank": 1,
                    "MarkDensity": 0,
                    "IsAmbiguous": false,
                    "IsVote": true,
                    "OutstackConditionIds": []
                  }
                ]
              },
              {
                "Id": 4,
                "ManifestationId": 170387,
                "Undervotes": 0,
                "Overvotes": 0,
                "OutstackConditionIds": [],
                "Marks": [
                  {
                    "CandidateId": 7,
                    "ManifestationId": 672429,
                    "PartyId": 0,
                    "Rank": 1,
                    "MarkDensity": 0,
                    "IsAmbiguous": false,
                    "IsVote": true,
                    "OutstackConditionIds": []
                  }
                ]
              },
              {
                "Id": 5,
                "ManifestationId": 170388,
                "Undervotes": 0,
                "Overvotes": 0,
                "OutstackConditionIds": [],
                "Marks": [
                  {
                    "CandidateId": 9,
                    "ManifestationId": 672431,
                    "PartyId": 0,
                    "Rank": 1,
                    "MarkDensity": 0,
                    "IsAmbiguous": false,
                    "IsVote": true,
                    "OutstackConditionIds": []
                  }
                ]
              },
              {
                "Id": 6,
                "ManifestationId": 170389,
                "Undervotes": 0,
                "Overvotes": 0,
                "OutstackConditionIds": [],
                "Marks": [
                  {
                    "CandidateId": 11,
                    "ManifestationId": 672433,
                    "PartyId": 0,
                    "Rank": 1,
                    "MarkDensity": 0,
                    "IsAmbiguous": false,
                    "IsVote": true,
                    "OutstackConditionIds": []
                  }
                ]
              }
            ],
            "OutstackConditionIds": []
          }
    """
    

if __name__ == "__main__":
    import pdb; pdb.set_trace()
    test_dominion_qrcode_decoder()