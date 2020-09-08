import pytest

from utilities import style_utils, barcode_parser


class TestSanitizeString:
    @pytest.mark.parametrize(
        "raw_string, clean_string",
        [
            ("audit engine", "audit engine"),
            ('citizen"s oversight', "citizen's oversight"),
            ('Citizen"s--oversight', "Citizen's--oversight"),
            ("Dennis\u0020Sieg", "Dennis Sieg"),
            ("Ron\u00A0Bristol", "Ron Bristol"),
            ("Lisa\u2002Neubauer", "Lisa Neubauer"),
            ("Ahna\u002DBizjak", "Ahna-Bizjak"),
            ("April Hammond\u2043Archibald", "April Hammond-Archibald"),
        ],
    )
    def test_normal_string(self, raw_string, clean_string):
        assert style_utils.sanitize_string(raw_string) == clean_string

    @pytest.mark.parametrize("raw_input", [199, 3.142, 3 + 4j])
    def test_invalid_string_input(self, raw_input):
        with pytest.raises(TypeError):
            assert style_utils.sanitize_string(raw_input)


class TestHexCodeParser:
    def test_parsing_hex_to_decimal_on_cvt_style_sequences(self):
        for style_number, hex_code in barcode_parser.TEST_CVT_STYLE_SEQUENCES:
            if hex_code is 0:
                continue
            parsed_hex_code = barcode_parser.get_parsed_barcode(hex_code)
            assert parsed_hex_code == style_number,\
                f'parsed code {parsed_hex_code} is not equal style number {style_number}'
