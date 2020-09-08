

class Style:
    """
    Class contains variables and methods related to single style.
    """

    def __init__(self, style_num: str):
        """
        :param code: Code in hex like '0x2100e10400000' (or in binary)
            describing style identity.
        """
        self.code = None                    # str: Number converted from the ballot indicating style i.e. '12'.
        self.style_ocrnum = None            # str: Number taken from the ballot indicating style i.e. '12'.
        self.style_num = style_num          
        self.timestamp = None               # int: Timestamp when style was built.
        self.build_from_count = None        # int: Number saying from how many ballots style was built.
        self.precinct = None                # str: Precinct to which style is related, i.e. 'T Albion Wds 1-2'. 
                                            #       (@@styles may span precincts tho, so this may not be reliable)
        self.build_from_ballots = []        # list of str: Ballot IDs from which style was built.    
        self.filepaths = []                 # pathnames of template images
        self.style_failed_to_map = False    # bool: True only if the template is known to be invalid.
        self.sheet = 0                      # int: sheet number, 0, 1...
        self.target_side = 'left'           # str: either 'left' or 'right' from argsdict at this time.
        
        # new version of the timing vector
        self.timing_marks = [
                {'left_vertical_marks':[], 'right_vertical_marks':[], 'top_marks':[]},     #page0
                {'left_vertical_marks':[], 'right_vertical_marks':[], 'top_marks':[]},     #page1
                ],

