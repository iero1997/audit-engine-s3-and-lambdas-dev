"""
Dominion QRCode Decoder for BMD ballots

The qr codes in the Dominion ballots encode votes as bits, labeling bit '1' 
as a vote bit. so for example if we have a contest that has 'A', 'B', 'C' &
'D' as contestants. then if a person votes for 'A' and 'C', the vote bits become
'1010' indicating that the first and the third contestants has been elected.

This decoder uses the contest manifest files to get all information needed
about the election. The inputs are qr code bytes and ballot type id.
ballot type id is a number between 1 & 180 which gives the type and sequence
of contests in a given ballot.

The QR codes in this election ballot hold at most 122 bytes and any ballot 
that has more than 122 bytes should accommodate the rest of the bytes with 
additional QR code.

"""

import binascii
import json
import bitarray 


"""
Parse manifest files to use 
    => BallotTypeManifest :       { ballot_type_id : ballot_Description, ... }  
    => BallotTypeContestManifest :  { BallotTypeID : [ContestID,..], ...}
    => Contest_Manifest :           { ContestID : [ContestDescription, VoteFor] }
    => CandidateManifest :          { ContestId : [ candiate, .. ]}

"""
with open("CVR_Export_20200326124513/BallotTypeManifest.json", 'r') as read_file:
    BallotTypeManifest_data = json.load(read_file)
BallotTypeManifest = {} # dictinary to store ballot type id
for i in BallotTypeManifest_data['List']:
    BallotTypeManifest[i['Id']] = i['Description']

with open("CVR_Export_20200326124513/BallotTypeContestManifest.json", 'r') as read_file:
    BallotTypeContestManifest_data = json.load(read_file)
BallotTypeContestManifest = {} # dictionary of list, to store each contest in a each ballot type id
for type in BallotTypeManifest:
    BallotTypeContestManifest[type]=[]
for b in BallotTypeContestManifest_data['List']:
    BallotTypeContestManifest[b['BallotTypeId']].append(b['ContestId'])

with open("CVR_Export_20200326124513/ContestManifest.json", 'r') as read_file:
    Contest_Manifest_data = json.load(read_file)
Contest_Manifest = {} # dictionary of list to store contests info
for i in Contest_Manifest_data['List']:
    Contest_Manifest[i['Id']] = [i['Description'] , i['VoteFor']]

with open("CVR_Export_20200326124513/CandidateManifest.json", 'r') as read_file:
    CandidateManifest_data = json.load(read_file)
CandidateManifest = {} # dictionary of list, to store each candidate in each contest.
for contest in Contest_Manifest:
    CandidateManifest[contest] = []
for candidate in CandidateManifest_data['List']:  
    if(candidate['Type'] in ['Regular', 'WriteIn'] ): # only take 'Regular' and 'WriteIn' contests
        CandidateManifest[candidate['ContestId']].append(candidate['Description']) 




"""
Function to return all occurences of a sub string
We use this function to find all occurence of bit '1'(vote bit) in the bitfield

Parameters
----------
    str : string  
        string to perform the search on
    sub : string
        sub string to search
Returns
-------
    list of int : 
        index where the subsring is found
 
"""
def find_all(str, sub): 
    start = 0
    while True:
        start = str.find(sub, start)
        if start == -1: return
        yield start
        start += len(sub) # use start += 1 to find overlapping matches




"""
Function that returns the Writein votes
Writein votes are found as string in the qr code bytes

Parameters
----------
    block : list of bytes
        bytes of the write in votes from all the blocks          
Returns
-------
    list of list of string : 
        writein votes as a string in a list
 
"""
def get_writein(block):
    votes = [[],[]]
    count = 0
    for sub in block:
        if(sub):
            num = sub[0] # get number of write in votes in the current sub block
            mini_block = sub[1:]
            for _ in range(num):
                start = mini_block.find(b'\x00')
                mini_block = mini_block[start+2:]
                end = mini_block.find(b'\x00')
                votes[count].append((mini_block[0:end]).decode('utf-8')) # decode to utf-8 and store the result in vote
        count += 1
    return votes





"""
Function to decode vote bits.
The vote decoding process mainly includes taking on succesive bits in the provided bitfiled 
and matching the votes to the repective contests.

Parameters
----------
    vote_bits_list : List of bitstring
        bitstring list holding the vote bits
    all_contest : List
        list of all contests 
    end_blocks : List of bytes
        bytes of the write in votes        
Returns
-------
    dictionary of list :
        verbose ballots vote
 
""" 
def decode_vote(vote_bits_list, all_contest, end_blocks): 
    VoteResult = {}
    for cont in all_contest:
        VoteResult[Contest_Manifest[cont][0]]=[]
    start = 0
    end = 0
    length = 0
    check = 1
    writein = 0
   
    writein_vote_lists = get_writein(end_blocks) # get the writein votes
   
    for contest in all_contest:
        if contest in [7, 8, 9, 10, 11, 12, 23, 22, 24]:
            vote_bits = vote_bits_list[0] # bits from the first block
            writein_vote = writein_vote_lists[0]
        else:
            vote_bits = vote_bits_list[1]
            writein_vote = writein_vote_lists[1]
            if check: # changing to the second block
                start = 0
                end = 0
                length = 0
                writein = 0
            check = 0

        # print(Contest_Manifest[contest][0]) # print the contest

        length = len(CandidateManifest[contest])
        end += length
        contest_bits = vote_bits[start:end]
        pos = list(find_all(contest_bits, '1'))
        
        if len(pos)<1: # if no vote
            vote = 'BLANK CONTEST'
            # print('\t'+ vote)
            VoteResult[Contest_Manifest[contest][0]].append(vote)
        else:
            if len(pos) < Contest_Manifest[contest][1] : # check undervotes
                vote = 'UNDER_VOTE_BY '+ str(Contest_Manifest[contest][1] - len(pos))
                VoteResult[Contest_Manifest[contest][0]].append(vote)
                # print('\t' + vote)
            for p in pos:
                vote = CandidateManifest[contest][p]
                if(vote == 'Write-in'): # write in votes
                    vote = vote + ' '+ writein_vote[writein]
                    # print('\t'+ vote)
                    writein += 1
                    VoteResult[Contest_Manifest[contest][0]].append(vote)
                else:
                    # print('\t'+ vote)
                    VoteResult[Contest_Manifest[contest][0]].append(vote) 
        
        start = end 

    return VoteResult

"""
Function to decode QR bytes.
This function reads qr bytes and gets values like number of qr codes, 
precinct, sheet number, card codes, block lengths, blocks, ... 
We use block lenghts in order to identify blocks of bytes that belong to
a certain contest.

Parameters
----------
    vote_bits_list : List of bitsting
        bitstring list holding the votes
    all_contest : List
        list of all contests
    end_blocks : List of bytes
        bytes of the write in votes from all the blocks       

Returns
-------
    dictionary of list
        verbose ballots vote
""" 
def decode_qr_bytes(byte_value, ballot_typ_id): 
    bytestr =  binascii.unhexlify(byte_value)
    
    # number_of_qrs = bytestr[0:2] # number of qr codes 
    # un_const_1 = bytestr[2:6] # unknown constant '000102000000'
    # un_const_2 = bytestr[8:16] # unknown constant '00000000000000000'
    # un_const_3 = bytestr[19:21] # unknown constant '0000' 
    # un_const_4 = bytestr[22] # unknown constant '00' 
    # # .....
    # precinct = int.from_bytes(bytestr[6:8], byteorder='little')  # precinct value
    sheet_num = bytestr[16] # number of sheets 1 2 ..   

    if(sheet_num == 1):  # identify sheet number.
        blklen_1 = 0
        blklen_1_1 = 0
        blklen_2 = bytestr[21]    # length for the second block
        blklen_2_1 = bytestr[21+blklen_1+1]
        card_id_paper_index_0 = int.from_bytes(bytestr[17:19], byteorder='little') #card id of paper index 1
        card_id_paper_index_1 = 0
        chunk_1 = bytestr[17:17+blklen_1]
        chunk_2 = bytestr[21+blklen_1+4:21+blklen_1+blklen_2+1]
    else:
        blklen_1 = bytestr[21]  # length for block 1
        blklen_1_1 = bytestr[23] # lenght for sub block 1
        blklen_2 = bytestr[25+blklen_1]    # length for the second block
        blklen_2_1 = bytestr[25+blklen_1+1]
        card_id_paper_index_0 = int.from_bytes(bytestr[17:19], byteorder='little') #card id of paper index 0
        card_id_paper_index_1 = int.from_bytes(bytestr[25+blklen_1-4:25+blklen_1-2], byteorder='little') #card id of paper index 1
        chunk_1 = bytestr[25:25+blklen_1]
        chunk_2 = bytestr[25+blklen_1+4:25+blklen_1+blklen_2+1]
            
    all_contests = BallotTypeContestManifest[ballot_typ_id]

    end_block_1 = chunk_1[blklen_1_1:] # sub block of block 1
    end_block_2 = chunk_2[blklen_2_1 + 4:] # sub block of block 2

    chunk_1_bin = bitarray.bitarray( endian='big')
    chunk_1_bin.frombytes(chunk_1)
    chunk_1_bin_str = chunk_1_bin.to01() # change to a string containing 0's and 1's for easy manipulation

    chunk_2_bin = bitarray.bitarray( endian='big')
    chunk_2_bin.frombytes(chunk_2)
    chunk_2_bin_str = chunk_2_bin.to01()
    
    vote_bits_list = [chunk_1_bin_str, chunk_2_bin_str] # list containing the two blocks
    end_blocks = [end_block_1, end_block_2[1:]]

    Result = decode_vote(vote_bits_list, all_contests, end_blocks) # decode the votes

    return Result
        

    
# if __name__ == "__main__":
    
    
