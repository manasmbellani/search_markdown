#!/usr/bin/python3
import argparse
import os
import re
import queue
import threading
import sys

from queue import Queue
from termcolor import colored, cprint

# Connector to use for representing flattened structure of chained nodes in
# the markdown
NODE_CONNECTOR = " --> "

# Substitute Linebreak to use instead of actual line break when printing flattened structure
LINEBREAK = " \\n "

# Default markdown extensions
MARKDOWN_EXTENSIONS = ".md"

# Color to use for file name where matches were found 
FILEPATH_COLOR = "green"

# Color to use for matched text
MATCH_COLOR = "red"

# Initial Block period (in seconds)
INIT_BLOCK_PERIOD = 1

# Description for this Script 
DESCRIPTION = """
Script to parse and search Markdown files
"""

# Heading prefix, suffix to use
HEADING_PREFIX = " [[ "
HEADING_SUFFIX = " ]] "

# Markdown heading character
MARKDOWN_HEADING_CHAR = "#"

# Markdown code context
MARKDOWN_CODE_CHARS = "```"

# New Line replacement character
NEW_LINE_REPLACEMENT = "\\n"

# Global flag to indicate when user interrupts e.g. via CTRL-C
user_interrupt_flag = threading.Event()

# Print queue to be used for printing results
print_queue = None

# Search tasks queue for files to search
search_tasks_queue = None

# Verbose flag to print messages
verbose_flag = False

class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawTextHelpFormatter):
    """Class for custom formatting of Argparse
    """
    pass

def error(msg):
    """Print error message

    Args:
        msg (msg): Error message
    """
    text = colored("[-] " + msg, "red")
    print(text)

def debug(msg):
    """Print debug message

    Args:
        msg (msg): Error message
    """
    global verbose_flag

    if verbose_flag:
        print("[*] " + msg)

def open_markdown_file(markdown_file):
    """Open the Markdown file and parse the Markdown file recursively into a map which can be easily
    searched

    Args:
        markdown_file (str): Markdown file to parse

    Returns:
        list: Structure of the Markdown file
    """
    
    map_structure = []
    if not os.path.isfile(markdown_file):
        error(f"File: {markdown_file} not found")
    else:
        prev_context = []
        current_context = ""
        in_code = False
        with open(markdown_file, "r+") as f:
            for l in f:
                if l.strip():
                    if l.startswith(MARKDOWN_HEADING_CHAR): 
                        if not in_code:
                            # A new heading reached hence update the markdown map structure
                            if current_context:
                                map_structure.append(NODE_CONNECTOR.join(prev_context) + NODE_CONNECTOR + current_context)

                            heading_level = len(l.split(" ")[0])

                            if heading_level > len(prev_context):
                                prev_context.append(current_context)
                            else:
                                prev_context = prev_context[0:heading_level]
                            current_context = l.strip() + LINEBREAK
                        else:
                            # Any heading like string inside code block (```) in markdown is probably comments for code
                            current_context += l.strip() + LINEBREAK

                    elif l.startswith(MARKDOWN_CODE_CHARS):
                        # Code block identified
                        in_code = not in_code
                        current_context += l.strip() + LINEBREAK
                    else:
                        # Normal line identified, just append it...
                        current_context += l.strip() + LINEBREAK

            # End of the file reached so update the map with the last element
            map_structure.append(NODE_CONNECTOR.join(prev_context) + NODE_CONNECTOR + current_context)

    return map_structure


def search_markdown_file(filepath, map_structure, keywords, delimiter, replace_newlines, 
    case_sensitive=False):
    """Search the Markdown structure

    Args:
        filepath (str): File path to search maps used for printing  
        map_structure (dict): Structure of markdown file
        keywords (str): Regex string to search for in the map
        delimiter (str): Delimiter to use form multiple keywords
        replace_newlines (bool): Replace new lines
        case_sensitive (bool, optional): Whether the search should be case-sensitive or not. Defaults, False

    Returns:
        list: List of string matches found that have the keywords that were found (that are color formatted)
    """
    lines_found = []

    # Get the list of keywords to search for
    keywords_arr = keywords.split(delimiter)

    debug(f"Searching freeplane map: {filepath} for keywords: {keywords}...")
    for l in map_structure:

        # Assume keywords match has been found
        kw_match_found = True

        # Search for keywords and ensure that they are found
        line_to_search = l
        for kw in keywords_arr:
    
            if case_sensitive:
                ms = re.search(kw, line_to_search)
            else:
                ms = re.search(kw, line_to_search, re.I)
            if ms:

                # Simply, color the keywords discovered in the line
                if case_sensitive:
                    line_to_search = re.sub(kw, lambda m: colored(m.group(), MATCH_COLOR) , line_to_search)
                else:
                    line_to_search = re.sub(kw, lambda m: colored(m.group(), MATCH_COLOR) , line_to_search, flags=re.I)
                
                # Replace the new lines with characters to replace new lines
                if replace_newlines:
                    line_to_search = line_to_search.replace("\n", LINEBREAK)
                    line_to_search = line_to_search.replace("\r", LINEBREAK)
            else:
                # Match wasn't found in line, stop searching
                kw_match_found = False
                break

        # If keywords found, then append
        if kw_match_found:
            lines_found.append(line_to_search)

    return lines_found

def print_matches(block_period=INIT_BLOCK_PERIOD):
    """Pretty format and print the matches found to the user

    Args:
        block_period(int): Block period to wait for matches to print
    """
    global print_queue

    continue_thread = True
    while continue_thread:
        rv = None
        try:
            rv = print_queue.get(block=True, timeout=block_period)
        except queue.Empty:
            pass

        if rv:
            map_file, matches = rv['file'], rv['matches']

            if matches:
                print(colored(map_file, FILEPATH_COLOR))
                for l in matches:
                    print(l)
                print()
        else:
            continue_thread = False


def init_print_queue():
    """
    Returns a queue which contains the matches that were found in each queue

    Returns:
        Queue: A queue that consists of matches to print for each file (a dict which consists of a 'file' and 'matches')
    """
    global print_queue

    if not print_queue:
        print_queue = Queue()
    return print_queue

def put_on_print_queue(filepath, matches):
    """Put file path and matches found on the print queue for printing

    Args:
        filepath (str): File path for which matches were found
        matches (list): List of matches for the file
    """
    global print_queue

    debug(f"Putting matches: {len(matches)} found for filepath: {filepath}...")
    print_queue.put(
        {'file': filepath,
        'matches': matches}
    )

def init_search_tasks_queue():
    """
    Returns:
        Queue: A queue that consists of collection of files to search
    """
    global search_tasks_queue

    if not search_tasks_queue:
        search_tasks_queue = Queue()
    return search_tasks_queue

def put_search_tasks(filepath):
    """Put a search task which specifies the filepath to search

    Args:
        filepath (str): Filepath to search
    """
    global search_tasks_queue
    search_tasks_queue.put(filepath)

def open_map_and_search(keywords, delimiter, case_sensitive, replace_newlines, 
    block_period=INIT_BLOCK_PERIOD):
    """Open a single markdown file from the queue and search

    Args:
        keywords (str): Keywords to search for in the map file
        delimiter (str): Delimiter to use for multiple keywords
        case_sensitive (bool): Case sensitive
        replace_newlines (str): Newlines for replacement
        block_period (int): Period to block the thread to wait for data
    """
    global user_interrupt_flag, search_tasks_queue

    continue_thread = True
    while continue_thread:

        # Get the file path to search 
        filepath = None
        try:
            filepath = search_tasks_queue.get(block=True, timeout=block_period)
        except queue.Empty:
            pass

        if filepath:

            # Open the markdown file
            did_user_interrupt = user_interrupt_flag.is_set()
            if not did_user_interrupt:
                map_structure = open_markdown_file(filepath)
                #print(map_structure)
            else:
                continue_thread = False

            # Search the markdown map for the keywords
            did_user_interrupt = user_interrupt_flag.is_set()
            if not did_user_interrupt:
                lines_found = search_markdown_file(filepath, map_structure, keywords, delimiter, 
                    replace_newlines, case_sensitive)
            else:
                continue_thread = False

            # Put the lines found from print queue for printing to terminal
            did_user_interrupt = user_interrupt_flag.is_set()
            if not did_user_interrupt:
                put_on_print_queue(filepath, lines_found)
            else:
                continue_thread = False
        else:
            continue_thread = False


def list_files_to_check(file_folder, extensions):
    """List files to search

    Args:
        file_folder (str): File/folder
        extensions (str): List of extensions (comma-separated) for freeplane files
    Returns:
        list: List of file paths (str) to search from file/folder

    """
    files_to_search = []
    map_extensions = extensions.split(",")
    if os.path.isfile(file_folder):
        files_to_search.append(file_folder)
    elif os.path.isdir(file_folder):
        for dp, _, files in os.walk(file_folder):
            for f in files:
                if any([f.endswith(e) for e in map_extensions ]):
                    full_path = os.path.join(dp, f)
                    files_to_search.append(full_path)
    else:
        error(f"Unknown file path: {file_folder}")

    return files_to_search

def launch_all_threads(file_folder, keywords, delimiter, case_sensitive, extensions, num_threads,
    replace_newlines):
    """
    Launch all the threads that will perform the search across the various Freeplane Map files

    Args:
        file_folder (str): Path to file/folder 
        keywords (str): Regex keywords to search
        delimiter (str): Delimiter to use for multiple keywords
        case_sensitive (bool): Case sensitive
        extensions (str): List of freeplane file extensions
        num_threads (int): Number of threads for search tasks
        replace_new_lines (bool): Replace new lines
    """

    files_to_search = list_files_to_check(file_folder, extensions)

    thread_objects = []

    # Launch the threads to open map and search
    for _ in range(0, num_threads):
        t = threading.Thread(target=open_map_and_search, args=(keywords, delimiter, case_sensitive,
            replace_newlines))
        t.start()   
        thread_objects.append(t)

    # Launch the search threads
    for fp in files_to_search:
        put_search_tasks(fp)

    # Launch the thread to print the task

    t = threading.Thread(target=print_matches)
    t.start()
    thread_objects.append(t)

    # Join all the threads to the main thread
    for t in thread_objects:
        t.join()


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION, formatter_class=CustomFormatter)
    parser.add_argument("-k", "--keywords", required=True, 
        help=("One or multiple Keyword search (or regex) in Freeplane files. "
              "Repeat this argument to supply multiple values"))
    parser.add_argument("-d", "--delimiter", default=" ", 
        help="Delimiter to use for multiple keywords")
    parser.add_argument("-f", "--file-folder", default="/opt/my-maps", help="File/folder to search")
    parser.add_argument("-c", "--case-sensitive", action="store_true", 
        help="Keyword search (regex) in the Markdown files")
    parser.add_argument("-nt", "--num-threads", default=10, 
        help="Number of threads to use to search for strings")
    parser.add_argument("-e", "--extensions", default=MARKDOWN_EXTENSIONS, 
        help="Markdown file extensions to use for identifying markdown files")
    parser.add_argument("-v", "--verbose", action="store_true",
        help="Verbose to print messages")
    parser.add_argument("-rn", "--replace-newlines", action="store_true", 
        help="Replace new lines with '\\n' to allow printing of matches per line")

    args = parser.parse_args()

    if args.verbose:
        global verbose_flag
        verbose_flag = True

    init_print_queue()
    
    init_search_tasks_queue()

    launch_all_threads(args.file_folder, args.keywords, args.delimiter, args.case_sensitive, 
        args.extensions, int(args.num_threads), args.replace_newlines)

if __name__ == "__main__":
    sys.exit(main())

