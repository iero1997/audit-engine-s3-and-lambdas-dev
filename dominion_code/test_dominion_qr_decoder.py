"""
Unit Testing program for the decode_qr_bytes function in the dominion_qr_decoder 
program.
This test is don against "TestData.json" that has 91 test cases of qr code bytes

"""

import unittest
import dominion_qr_decoder as Decoder
import json
import qr_bytes as QR


class testdecode_qr_bytes(unittest.TestCase):
    def test_decode_qr_bytes(self):
        with open("TestData.json", 'r') as read_file: # open "TestData.json"
            TestData = json.load(read_file)
        for ballot_id in QR.hex_values: # Test all of the test ballots against "TestData.json"
            output = Decoder.decode_qr_bytes(QR.hex_values[ballot_id], QR.ballot_type_ids[ballot_id])
            self.assertEqual(output, TestData[ballot_id])
        
if __name__ == '__main__':
    unittest.main()

