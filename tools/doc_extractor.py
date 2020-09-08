"""
doc_extractor.py

This script creates a document which summarizes the content of .py files in the passed folder
and all sub folders.

Function simply looks for lines starting with def name( ) and followed by triple quote docstring.
Lists these in the order found in the files, into a unified document.
"""

"""
Algorithm
1. accept folder name from args
2. create list of .py documents in the folder and all sub folders.
3. for each file:
4.      open each file found in alphabetical order
5.      write name of the file in the output.
6.      search for 'def defname (', and following docstring.
7.      create dict of dict
            defname
                filename
                start_offset_line
                end_offset_line
                def_and_docstring
                body
                calls_list
                used_by_list
                
8. after all files are processed, search all bodies for defnames and add to calls_list
    for each entry in dict
        consider defname
        for each entry in dict
            search body of each entry for 'defname('
            if found
                append to calls_list of that entry
                append this entry defname to used_by_list
            
9. create output file
    filename 
    start_offset_line
    end_offset_line
    def_and_docstring
    calls_list
    used_by_list
"""

import argparse
import os
import glob
import re



def get_args():
    """Get arguments and return them parsed"""
    parser = argparse.ArgumentParser(description="doc_extractor")
    parser.add_argument("-p", "--path", help="path to folder",
                        metavar="path", type=str)
    return parser.parse_args()
    
def split_blocks_at_lines_with_pattern(data: str, pattern: str) -> list:
    """ split block of lines at lines with pattern.
        used to split up python modules into functions and classes.
    """
    block_list = []
    datalines = data.splitlines(keepends=True)
    
    current_block = 0
    block_list.append('')
    for line in datalines:
        match = re.search(pattern, line)
        if match:
            current_block += 1
            block_list.append('')
        block_list[current_block] += line
        
    return block_list

    
    
    

def main():
    file_ext = '.py'
    function_prefix_pattern = r'^\s*(?:def\s+|class\s+\w+\:)'


    args = get_args()
    pathspec = f"{args.path}/*/*{file_ext}"
    file_list = glob.glob(pathspec)            # Return a possibly-empty list of path names that match pathspec
    
    func_dict = {}
    
    #import pdb; pdb.set_trace()
    for filepath in file_list:
        print (f"======================================\n{filepath}\n======================================")
        with open(filepath) as f:
            data = f.read()
        if not len(data):
            print ("File is empty!")
            continue
            
        function_list = split_blocks_at_lines_with_pattern(data, function_prefix_pattern)
        
        path,filename = os.path.split(filepath)
        fileroot, ext = os.path.splitext(path)
        
        previous_lines = 0
        for idx, functionstr in enumerate(function_list):
            if not functionstr and idx == 0:
                # case where function starts at the very top.
                continue
            functionlines = functionstr.splitlines()
            match = re.search(r'^\s*(?:def|class)\s+([^\(\s\:]+)\s*[\(\:]', functionlines[0])
            if match:
                defname = match[1]
            else:
                if idx == 0: 
                    previous_lines += len(functionlines)
                    fileheader = ''
                    match = re.search(r'(\s*""".*?""")(.*)$', functionstr, flags=re.S)
                    if match:
                        fileheader = match[1]
                        print (fileheader)
                    continue           # header block of file
                print (f"Can't parse function name in this line:'{functionlines[0]}'")

            # first try to match typical function with parenthesis.
            match = re.search(r'^(.*?\([^)]*\).*?:)(.*)$', functionstr, flags=re.S)
            if match:
                entire_def = match[1]
                body = match[2]
            else:
                # Try to match case without parenthesis and just ':'.
                match = re.search(r'^(.*?:)(.*)$', functionstr, flags=re.S)
                if match:
                    entire_def = match[1]
                    body = match[2]
                else:
                    print (f"Can't parse function name in this line:'{functionstr}'")
                

            
            docstr = ''
            netbody = ''
            match = re.search(r'(\s*""".*?""")(.*)$', body, flags=re.S)
            if match:
                docstr = match[1]
                netbody = match[2]
                
            func_dict['defname'] = {
                'filename': filename,
                'start_offset_line': previous_lines,
                'end_offset_line': previous_lines + len(functionlines),
                'entire_def': entire_def,
                'docstr': docstr,
                'netbody': netbody,
                'calls_list': [],
                'used_by_list': [],
                }

            previous_lines += len(functionlines)
            
            print (f"{entire_def}{docstr}\n")
    
    

if __name__ == "__main__":
    main()
