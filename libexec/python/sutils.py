'''
utils.py: python helper for singularity command line tool

Copyright (c) 2016, Vanessa Sochat. All rights reserved. 

"Singularity" Copyright (c) 2016, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of any
required approvals from the U.S. Dept. of Energy).  All rights reserved.
 
This software is licensed under a customized 3-clause BSD license.  Please
consult LICENSE file distributed with the sources of this project regarding
your rights to use or distribute this software.
 
NOTICE.  This Software was developed under funding from the U.S. Department of
Energy and the U.S. Government consequently retains certain rights. As such,
the U.S. Government has been granted for itself and others acting on its
behalf a paid-up, nonexclusive, irrevocable, worldwide license in the Software
to reproduce, distribute copies to the public, prepare derivative works, and
perform publicly and display publicly, and to permit other to do so. 

'''

from defaults import (
    SINGULARITY_CACHE
)
from message import bot
import datetime
import errno
import hashlib
import json
import os
import subprocess
import stat
import sys
import tempfile
import tarfile
import base64
try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

from io import (
    BytesIO,
    StringIO
)

# Python less than version 3 must import OSError
if sys.version_info[0] < 3:
    from exceptions import OSError


############################################################################
## HTTP OPERATIONS #########################################################
############################################################################

def add_http(url,use_https=True):
    '''add_http will add a http / https prefix to a url, in case the user didn't
    specify
    :param url: the url to add the prefix to
    :param use_https: should we default to https? default is True
    '''
    scheme = "https://"
    if use_https == False:
        scheme="http://"

    parsed = urlparse(url)
    # Returns tuple with(scheme,netloc,path,params,query,fragment)

    return "%s%s" %(scheme,"".join(parsed[1:]).rstrip('/'))

    
def basic_auth_header(username, password):
    '''basic_auth_header will return a base64 encoded header object to
    generate a token
    :param username: the username
    :param password: the password
    '''
    s = "%s:%s" % (username, password)
    if sys.version_info[0] >= 3:
        s = bytes(s, 'utf-8')
        credentials = base64.b64encode(s).decode('utf-8')
    else:
        credentials = base64.b64encode(s)
    auth = {"Authorization": "Basic %s" % credentials}
    return auth


############################################################################
## COMMAND LINE OPERATIONS #################################################
############################################################################


def run_command(cmd):
    '''run_command uses subprocess to send a command to the terminal.
    :param cmd: the command to send, should be a list for subprocess
    '''
    try:
        bot.verbose2("Running command %s with subprocess" %" ".join(cmd))
        process = subprocess.Popen(cmd,stdout=subprocess.PIPE)
    except OSError as error:
        bot.error("Error with subprocess: %s, returning None" %error)
        return None

    output = process.communicate()[0]
    if process.returncode != 0:
        return None

    return output


def is_number(image):
    '''is_number determines if the user is providing a singularity hub
    number (meaning the id of an image to download) vs a full name)
    :param image: the image name, after the uri is removed (shub://)
    '''
    try:
        float(image)
        return True
    except ValueError:
        return False



def show_progress(iteration,total,length=100,fill='█'):
    '''create a terminal progress bar
    :param iteration: current iteration (Int)
    :param total: total iterations (Int)
    :para, length: character length of bar (Int)
    :param fill: bar fill character (Str)
    '''
    percent = ("{0:.1f}").format(100 * (iteration / float(total)))
    progress = int(length * iteration // total)
    bar = fill * progress + '-' * (length - progress)

    # Only show progress bar for level verbose
    if bot.level > 1:
        print('\rProgress |%s| %s%%' % (bar, percent), end="\r")
        if iteration == total: 
            print()



############################################################################
## TAR/COMPRESSION #########################################################
############################################################################


def extract_tar(archive,output_folder):
    '''extract_tar will extract a tar archive to a specified output folder
    :param archive: the archive file to extract
    :param output_folder: the output folder to extract to
    '''
    # If extension is .tar.gz, use -xzf
    args = '-xf'
    if archive.endswith(".tar.gz"):
        args = '-xzf'

    # Just use command line, more succinct.
    command = ["tar", args, archive, "-C", output_folder, "--exclude=dev/*"]
    if not bot.is_quiet():
        print("Extracting %s" %archive)

    return run_command(command)


def create_tar(files,output_folder=None):
    '''create_memory_tar will take a list of files (each a dictionary
    with name, permission, and content) and write the tarfile (a sha256 sum name 
    is used) to the output_folder. If there is no output folde specified, the
    tar is written to a temporary folder.
    '''
    if output_folder is None:
        output_folder = tempfile.mkdtemp()

    finished_tar = None
    additions = []
    contents = []

    for entity in files:
        info = tarfile.TarInfo(name=entity['name'])
        info.mode = entity['mode']
        info.mtime = int(datetime.datetime.now().strftime('%s'))
        info.uid = entity["uid"]
        info.gid = entity["gid"]
        info.uname = entity["uname"] 
        info.gname = entity["gname"]

        # Get size from stringIO write
        filey = StringIO()
        content = None
        try: #python3
            info.size = filey.write(entity['content'])
            content = BytesIO(entity['content'].encode('utf8'))
        except: #python2
            info.size = int(filey.write(entity['content'].decode('utf-8')))
            content = BytesIO(entity['content'].encode('utf8'))
        pass
        
        if content is not None:
            addition = {'content':content,
                        'info':info}
            additions.append(addition)
            contents.append(content)

    # Now generate the sha256 name based on content
    if len(additions) > 0:
        hashy = get_content_hash(contents)
        finished_tar = "%s/sha256:%s.tar.gz" %(output_folder, hashy)

        # Warn the user if it already exists
        if os.path.exists(finished_tar):
            bot.debug("metadata file %s already exists, will over-write." %(finished_tar))

        # Add all content objects to file
        tar = tarfile.open(finished_tar, "w:gz")
        for a in additions:
            tar.addfile(a["info"],a["content"])
        tar.close()

    else:
        bot.debug("No contents, environment or labels, for tarfile, will not generate.")

    return finished_tar



############################################################################
## HASHES ##################################################################
############################################################################


def get_content_hash(contents):
    '''get_content_hash will return a hash for a list of content (bytes or other)
    '''
    hasher = hashlib.sha256()
    for content in contents:
        if isinstance(content,BytesIO):
            content = content.getvalue()
        if not isinstance(content,bytes):
            content = bytes(content)
        hasher.update(content) 
    return hasher.hexdigest()



############################################################################
## FOLDERS #################################################################
############################################################################


def get_cache(subfolder=None,quiet=False):
    '''get_cache will return the user's cache for singularity. The path
    returned is generated at the start of the run, and returned optionally
    with a subfolder
    :param subfolder: a subfolder in the cache base to retrieve, specifically
    '''

    # Clean up the path and create
    cache_base = clean_path(SINGULARITY_CACHE)

    # Does the user want to get a subfolder in cache base?
    if subfolder != None:
        cache_base = "%s/%s" %(cache_base,subfolder)
        
    # Create the cache folder(s), if don't exist
    create_folders(cache_base)

    if not quiet:
        bot.info("Cache folder set to %s" %cache_base)
    return cache_base



def create_folders(path):
    '''create_folders attempts to get the same functionality as mkdir -p
    :param path: the path to create.
    '''
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            bot.error("Error creating path %s, exiting." %path)
            sys.exit(1)


############################################################################
## PERMISSIONS #############################################################
############################################################################


def has_permission(file_path,permission=None):
    '''has_writability will check if a file has writability using
    bitwise operations. file_path can be a tar member
    :param file_path: the path to the file, or tar member
    :param permission: the stat permission to check for
    is False)
    '''
    if permission == None:
        permission = stat.S_IWUSR
    if isinstance(file_path,tarfile.TarInfo):
        has_permission = file_path.mode & permission
    else:
        st = os.stat(file_path)
        has_permission = st.st_mode & permission
    if has_permission > 0:
        return True
    return False


def change_tar_permissions(tar_file,permission=None):
    '''change_tar_permissions changes a permission if 
    any member in a tarfile file does not have it
    :param file_path the path to the file
    :param permission: the stat permission to use
    '''
    tar = tarfile.open(tar_file, "r:gz")

    # Add all content objects to file
    fd, tmp_tar = tempfile.mkstemp(prefix=("%s.fixperm." % tar_file))
    os.close(fd)
    fixed_tar = tarfile.open(tmp_tar, "w:gz")

    if permission == None:
        permission = stat.S_IWUSR

    # Add owner write permission to all, not symlinks
    bot.verbose("Fixing permission for %s" %(tar_file))
    
    members = tar.getmembers()

    ii=0
    count = len(members)
    show_progress(ii,count,length=50)

    for member in members:  
        if member.isdir() or member.isfile() and not member.issym():
            member.mode = permission | member.mode
            extracted = tar.extractfile(member)        
            fixed_tar.addfile(member, extracted)
        else:    
            fixed_tar.addfile(member)

        ii += 1
        show_progress(ii,count,length=50)


    fixed_tar.close()
    tar.close()
 
    # Rename the fixed tar to be the old name
    os.rename(tmp_tar, tar_file)
    return tar_file        
        

############################################################################
## FILES ###################################################################
############################################################################


def write_file(filename,content,mode="w"):
    '''write_file will open a file, "filename" and write content, "content"
    and properly close the file
    '''
    bot.verbose2("Writing file %s with mode %s." %(filename,mode))
    with open(filename,mode) as filey:
        filey.writelines(content)
    return filename


def write_json(json_obj,filename,mode="w",print_pretty=True):
    '''write_json will (optionally,pretty print) a json object to file
    :param json_obj: the dict to print to json
    :param filename: the output file to write to
    :param pretty_print: if True, will use nicer formatting   
    '''
    bot.verbose2("Writing json file %s with mode %s." %(filename,mode))
    with open(filename,mode) as filey:
        if print_pretty == True:
            filey.writelines(json.dumps(json_obj, indent=4, separators=(',', ': ')))
        else:
            filey.writelines(json.dumps(json_obj))
    return filename


def read_json(filename,mode='r'):
    '''read_json reads in a json file and returns
    the data structure as dict.
    '''
    with open(filename,mode) as filey:
        data = json.load(filey)
    return data


def read_file(filename,mode="r"):
    '''write_file will open a file, "filename" and write content, "content"
    and properly close the file
    '''
    bot.verbose3("Reading file %s with mode %s." %(filename,mode))
    with open(filename,mode) as filey:
        content = filey.readlines()
    return content


def clean_path(path):
    '''clean_path will canonicalize the path
    :param path: the path to clean
    '''
    return os.path.realpath(path.strip(" "))


def get_fullpath(file_path,required=True):
    '''get_fullpath checks if a file exists, and returns the
    full path to it if it does. If required is true, an error is triggered.
    :param file_path: the path to check
    :param required: is the file required? If True, will exit with error
    '''
    file_path = os.path.abspath(file_path)
    if os.path.exists(file_path):
        return file_path

    # If file is required, we exit
    if required == True:
        bot.error("Cannot find file %s, exiting." %file_path)
        sys.exit(1)

    # If file isn't required and doesn't exist, return None
    bot.warning("Cannot find file %s" %file_path)
    return None


def get_next_infos(base_dir,prefix,start_number,extension):
    '''get_next infos will browse some directory and return
    the next available file
    '''
    output_file = None
    counter = start_number
    found = False

    while not found:
        output_file = "%s/%s-%s%s" %(base_dir,
                                     counter,
                                     prefix,
                                     extension)
        if not os.path.exists(output_file):
            found = True
        counter+=1
    return output_file


def write_singularity_infos(base_dir,prefix,start_number,content,extension=None):
    '''write_singularity_infos will write some metadata object
    to a file in some base, starting at some default number. For example,
    we would want to write dockerN files with docker environment exports to
    some directory ENV_DIR and increase N until we find an available path
    :param base_dir: the directory base to write the file to
    :param prefix: the name of the file prefix (eg, docker)
    :param start_number: the number to start looking for available file at
    :param content: the content to write
    :param extension: the extension to use. If not defined, uses .sh
    '''
    if extension == None:
        extension = ""
    else:
        extension = ".%s" %(extension)

    # if the base directory doesn't exist, exit with error.
    if not os.path.exists(base_dir):
        bot.warning("Cannot find required metadata directory %s. Exiting!" %base_dir)
        sys.exit(1)

    # Get the next available number
    output_file = get_next_infos(base_dir,prefix,start_number,extension)
    write_file(output_file,content)
    return output_file
