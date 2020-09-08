# csv_to_json_converter.py

# accepts name of csv file to convert to json, and name of file for output.
#

import sys
import pandas as pd
import numpy as np
import json
import pprint
import io
import re


def convert_csv_to_json(input_path, output_path):

    with open(input_path, mode='r') as fh:
        buff = fh.read()

    lines = re.split('\n', buff)
    lines = [line for line in lines if not bool(re.search(r'^"?#', line)) and not bool(re.search(r'^,+$', line))]
    
    buff = '\n'.join(lines)
    
    print(buff)
    
    sio = io.StringIO(buff)

    df = pd.read_csv(
        sio, 
        na_filter=False, 
        index_col=False, 
        sep=",", 
#        comment="#",
        true_values=["TRUE", "Yes"],
        false_values=["FALSE", "No"],
#        skip_blank_lines=True
        ).replace(np.nan, '', regex=True)
        
    #df.dropna(how="all", inplace=True)
    #df.replace(np.nan, '', regex=True)
    
    print(f"Read {input_path}, {len(df.index)} records")
    
    print(pprint.pformat(df))

    if False:
        df.to_json(output_path)
    
    else:
    
        df_dict = df.to_dict(orient='records') 
            
        with open(output_path, mode='w') as fh:
        
            #json.dump(obj, fp, *, skipkeys=False, ensure_ascii=True, check_circular=True, allow_nan=True, cls=None, indent=None, separators=None, default=None, sort_keys=False, **kw)

            json.dump(df_dict, fh, indent=4)
        
    print(f"Created output file {output_path}")
    
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: csv_to_json_converter.py {inputfile} {outputfile}")
    else:
        convert_csv_to_json(sys.argv[1], sys.argv[2])
