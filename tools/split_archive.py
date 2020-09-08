# split_archive folder targetsize compression_factor basename name_mask opmode
#
# Given a large archive of many files, split them into several folders approximately equally
# Can decide to keep files with similar names together, such as with numbers in given position.

# folder: path to folder of interest
# targetsize: desired minimum size of a single folder after compression
# compression_factor: the (resulting size after compression)/(original size) as a decimal fraction.
# basename: the base name of the folder, to be appended by the number staring at 001.
# name_mask: regex mask to use to isolate the portion that is of interest.
# opmode: trial or run

# const min_size_factor = 0.20   # if residual is only 20% of target or less, combine into the last folder, otherwise make a new one.

# Algorithm
#   Create a list of all the files.
#   tot_num_files = count of all files.
#   total_size = total size of all the files. (Can we do this by getting total size of folder?)
#       go through all files and create an array of their sizes
#       add up all the sizes to obtain the total (can accumulate as we go)
#   num_folders = int((total_size * compression_factor / targetsize) + 1- min_size_factor)  # combine last one into previous if only 20% of target.
#   target_num_files_per_folder = int(tot_num_files / num_folders)
#
# To find the split point,
#   foreach $folder in num_folders:
#       cur_offset = $folder * target_num_files_per_folder
#       masked_cur_name = mask(filenames[$cur_offset], name_mask)
#       while (cur_offset < total_size; cur_offset++) {
#           masked_next_name = mask(filenames[$cur_offset+1], name_mask)
#           if (masked_cur_name != masked_next_name) break
#           masked_cur_name = masked_next_name;
#           }
#       }
#       $last_offset = min(total_size, $cur_offset)
#       $cut_points[$archive] = $last_offset
#   }
# if in inspection mode, print the following:
# print "Total Number of Archive Folders: ", num_folders
#   the approximate size of each archive
#   the number of archives
#   for each archive:
#       archive number
#       number of files
#       total byte size of uncompressed data.
#       estimated size of compressed data.
#       first filename, last filename
# if in run mode
# foreach $folder in $num_folders:
#   create folder basename.numeric_extension
#   starting_offset = 1 + prior_cut_point
#   ending_offset = cur_cut_point
#   for ($i = starting_offset; $i <= $ending_offset; $i++)
#       move file to folder
#--#

import re
import argparse
import glob

def apply_mask(s:str, mask:str, remove_quotes=True):
    """ Extract a substring from $str based on $mask
    """
    # remove surrounding " quotes if they are included in the string from ARGV 
    
    if remove_quotes:
        mask = mask.strip('"')
    match = re.search(mask, s)
    result = match[1]
    return result
    
assert apply_mask(r'AB-001+10001.jpg', r'^(......).*$') == 'AB-001'


def calc_bin_sizes(lst: list) -> list:
    """ given a list of cut points, return the sizes of each bin.
    """
    result = []
    for i in range (len(lst)-1):
        result.append(lst[i+1] - lst[i])

    return result

assert calc_bin_sizes([0,10,35,100]) == [10,25,65]

def get_args():
    """Get arguments and return them parsed"""
    parser = argparse.ArgumentParser(description="Citizens' Oversight: split_archive")
    parser.add_argument("workfolder",   help="path to folder of interest. use '.' to designate current folder.", type=str)
    parser.add_argument("targetsize",   help="desired minimum size of a single folder after compression in GB", type=int)
    parser.add_argument("compression_factor", help="the (resulting size after compression)/(original size) as a decimal fraction.", type=float)
    parser.add_argument("basename",     help="the base name of the folder, to be appended by the number staring at 001.", type=str)
    parser.add_argument("name_mask",    help="regex mask to use to isolate the portion that is of interest, surrounded by quotes", type=str)
    parser.add_argument("--trial",      help="analyze file without actually doing it", action='const_true')

    return parser.parse_args()

def main():
    min_size_factor = 0.20
    args = get_args()
    
    targetsize *= 1_000_000_000     # argument passed in command line is in GB.

#   Create a list of all the files.
    raw_pathnames = glob.glob(f"{workfolder}/*/*")
    
#   total_size = total size of all the files. (Can we do this by getting total size of folder?)
#       go through all files and create an array of their sizes
#       add up all the sizes to obtain the total (can accumulate as we go)

    pathnames = []
    filesizes = []
    total_size = 0
    
    for pathname in raw_pathnames:
        path, filename = os.path.split(pathname)
        if filename.startswith('.'): continue           # no filenames starting with '.'
        if not os.isfile(pathname): continue            # must be regular files.
        size = os.path.getsize(pathname)                # file size in bytes
        if not size: continue                           # file must have at least one byte.
        pathnames.append(pathname)
        filesizes.append(size)     
        total_size += size
        
    tot_num_files = len(pathnames)

    # combine last one into previous if only 20% of target.
    num_folders = int((total_size * compression_factor / targetsize) + 1 - $min_size_factor)
    target_num_files_per_folder = int(tot_num_files / num_folders)

    # find the split points
    # the goal here is to keep files together that are in the same precinct as determined by the mask.
    cut_points = []
    
    for folder in range(num_folders):
        if not folder:
            # first loop
            cur_file_os = target_num_files_per_folder
        
        # get the masked name to provide precinct information.
        last_masked_name = apply_mask(pathnames[cur_file_os - 1], name_mask)
        
        # add additional files that are in this precinct.
        while cur_file_os < total_size:
            next_masked_name = apply_mask(pathnames[cur_file_os], name_mask)
            if not $last_masked_name == $next_masked_name: break
            cur_file_os += 1
        
        cut_points[folder] = cur_file_os
        
    cut_points.insert(0, 0)                             # prepend a 0.
    folder_sizes = calc_bin_sizes(cut_points)           # get sizes by taking the differences in cut points. Opposite of cumsum.

    print ( f"Summary\nTotal Number of Archive Folders: {num_folders}\n"
            f"Approximate number of files in each archive: {target_num_files_per_folder}\n"
            f"Number of archives: {num_folders}\n"
            f"Folder  NumFiles    RawSizeInBytes      Est. Final size     first_name      last_name\n")
    for folder in range(num_folders):
        print ("%3.3u    %7.1u      %10.1u        %10.1u        %s            %s\n" %
            folder, folder_sizes[folder], 
            folder_sizes[folder] * compression_factor, 
            filenames[cut_points[folder]],
            filenames[cut_points[folder + 1] - 1]
            )

    for folder in range(num_folders):
        numstr = sprintf("_%3.3u", folder + 1);
        cand_folder = workfolder.'/'.basename.numstr;
        print ("mkdir ".$cand_folder."\n")
        if not trial:
            os.mkdir(cand_folder)
            
        for item in range(cut_points[$folder], cut_points[$folder + 1]):
            source_path = pathnames[item]
            source_head, source_filename = os.path.split(source_path)
            dest_path = source_head.'/'.basename.numstr.'/'.source_filename;
            my $cand_cmd = "mv $cand_filepath_from $cand_filepath_to";
            print "$cand_cmd\n";
            if ($opmode eq 'run') {
                `$cand_cmd`;
                }
            }
        }
        
if __name__ == "__main__":
    main()


