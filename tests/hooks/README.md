PEP8 Git Pre-Commit Hook
====================

This is a pre-commit hook for Git that checks the code to be committed
against Python PEP8 style guide. The hook prevents the commit if there are
any style violations.

**Installation**:

**Linux / Unix**
1. Install the _pycodestyle_: ```sudo pip3 install pycodestyle```
2. Rename the ```pre-commit.py``` file to ```pre-commit``` and copy it to 
```your_project/.git/hooks/```
3. Make the pre-commit executable: ```chmod a+x your_project/.git/hooks/pre-commit```

**Windows**
1. You're on your own. ;) Just kidding, steps one and two are the same.
2. Make sure the pre-commit file is executable by right clicking on the file
and selecting ```Properties``` and then go to ```Security``` tab. 

Currently, the following PEP8 codes are checked:

- E111 indentation is not a multiple of four
- E125 continuation line does not distinguish itself from next logical line
- E203 whitespace before ':'
- E261 at least two spaces before inline comment
- E262 inline comment should start with '# '
- E301 expected 1 blank line, found 0
- E302 expected 2 blank lines, found 1
- E303 too many blank lines (2)
- E502 the backslash is redundant between brackets
- E701 multiple statements on one line (colon)
- E711 comparison to None should be 'if cond is None:'
- W291 trailing whitespace
- W293 blank line contains whitespace

**Modifications**:

In case you want to modify the list of codes to ignore, edit the
```ignore_codes``` list in the pre-commit file.
  
If you want to select only specific codes to scan for, use the
```select_codes``` list.

Additional arguments to _pycodestyle_ (e.g., ```--max-line-length=120```)
can be added to the ```overrides``` list.
