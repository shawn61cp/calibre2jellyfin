#!/usr/bin/python3

#	calibre2jellyfin.py
#
#	Python script to construct a Jellyfin ebook library from a Calibre library.
#
#	2023-11-17 initial revision
#   author Shawn C. Powell
#
			
import sys
import os
import configparser
import argparse
import pathlib
import traceback
from xml.dom import minidom

# ------------------
#	Set up
# ------------------

homepath = os.path.expanduser('~')

# Parse command line arguments

cmdparser = argparse.ArgumentParser(description='A utility to maintain jellyfin-compatible file structure and metadata beside a Calibre repository.')	
cmdargs = cmdparser.parse_args()

# read configuration

try:
    configfilename = os.path.splitext(os.path.basename(__file__))[0] + '.cfg'
    configfilepath = os.path.join(homepath,'.config',configfilename)
    configfile = open(configfilepath,'r')
except:
	print(f'Could not open configuration {configfilepath}', file=sys.stderr, flush=True)
	sys.exit(-1)

try:
	config = configparser.ConfigParser()
	config.read_file(configfile)
except:
	print(f'Could not read configuration {configfilepath}', file=sys.stderr, flush=True)
	sys.exit(-1)
finally:
    configfile.close()


print('Using configuration', configfilepath, sep=' ', flush=True)	

# ------------------
#	Functions
# ------------------

def findBook(bookfiletypes, bookFolderSrcPath):
    """Locates first instance of a file having an configured book extension

        bookfiletypes       [], list of file extensions identifying books (exclude periods)
        bookFolderSrcPath   pathlib.Path, full path to book folder to search
    """
    for typeExt in bookfiletypes:
        for bookFilePath in bookFolderSrcPath.glob('*.' + typeExt):
            return bookFilePath
    return None

def findMetadata(bookFolderSrcPath):
    """Locates first instance of a metadata file (one w an .opf extension)

        bookFolderSrcPath   pathlib.Path, full path to book folder to search
    """
    for metadataFilePath in bookFolderSrcPath.glob('*.opf'):
        return metadataFilePath
    return None

def findCover(bookFolderSrcPath):
    """Locates instance of a book cover image

        bookFolderSrcPath   pathlib.Path, full path to book folder to search
    """
    for coverFilePath in bookFolderSrcPath.glob('cover.jpg'):
        return coverFilePath
    return None

def getSeries(metadataFilePath):
    """Extracts series and series index from book metadata file

        metadataFilePath    pathlib.Path, full path to metadata file
        Returns ()          doc, minidom xml doc object
                            str, name of series, empty str if none
                            str, book index in series, empty str if none
    """
    series = ''
    series_index = ''
    doc = None
    if not metadataFilePath:
        return  doc, series, series_index

    # open the metadata file
    try:
        docfile = open(metadataFilePath)
    except Exception as e:
        print(f'Could not open metadata file {metadataFilePath}', file=sys.stderr, flush=True)
        print(e, file=sys.stderr, flush=True)
        #print(traceback.format_exc(), file=sys.stderr, flush=True)

    # create a document object from the metadata file
    try:
        doc = minidom.parse(docfile)
    except Exception as e:
        print(f'Could not read metadata file {metadataFilePath}', file=sys.stderr, flush=True)
        print(e, file=sys.stderr, flush=True)
        #print(traceback.format_exc(), file=sys.stderr, flush=True)

    # get series info
    metas  = doc.getElementsByTagName('meta')
    for m in metas:
        if m.getAttribute('name') == 'calibre:series':
            series = m.getAttribute('content')
        elif m.getAttribute('name') == 'calibre:series_index':
            series_index = m.getAttribute('content')

    docfile.close()
    return  doc, series, series_index


def doBook(authorSrcPath, authorDstPath, bookFolderSrcPath, bookfiletypes, foldermode, jellyfinStore):
    """Creates folder, files and symlinks for one book.

        authorSrcPath       pathlib.Path, full path to source author folder
        authorDstPath       pathlib.Path, full path to destination author folder
        bookFolderSrcPath   pathlib.Path, full path to source book folder
        bookfiletypes       list, extensions identifying book files (exclude periods)
        foldermode          str, one of 'author,series,book' or 'book'
        jellyfinStore       pathlib.Path, full path top level output storage location (i.e. will be jellyfin library folder)
    """
    
    # find first instance of configured book file types
    bookFileSrcPath = findBook(bookfiletypes, bookFolderSrcPath)
    if not bookFileSrcPath:
        return
    print(bookFolderSrcPath)

    # locate related book files
    bookFolder = bookFolderSrcPath.name
    metadataSrcFilePath = findMetadata(bookFolderSrcPath)
    coverSrcFilePath = findCover(bookFolderSrcPath)
    metadatadoc, series, series_index = getSeries(metadataSrcFilePath)

    # Output is organized as '.../author/series/book/book.ext' or '.../book/book.ext' depending on foldermode.
    # If series info was expected but not found, output structure will be '.../author/book/book.ext'.
    # If series info was expected and found, then mangle the book's folder name by prepending the book's index.
    # Once the folder structure has been determined, create the destination folder(s) if they do not exist.
    if series > '' and foldermode == 'author,series,book':
        if series_index == '':
            series_index = '99'
        bookFolder = '{:>03s} - {}'.format(series_index,bookFolder)
        bookFolderDstPath = authorDstPath.joinpath(series + ' Series',bookFolder)
    elif foldermode == 'book':
        bookFolderDstPath = jellyfinStore.joinpath(bookFolder)
    else:
        bookFolderDstPath = authorDstPath.joinpath(bookFolder)
    pathlib.Path(bookFolderDstPath).mkdir(parents=True, exist_ok=True)

    # Create a symlink to the source book if it does not exist
    bookFileDstPath = bookFolderDstPath.joinpath(bookFileSrcPath.name)
    if not bookFileDstPath.exists():
        os.symlink(bookFileSrcPath, bookFileDstPath)

    # Create a symlink to the cover image if it does not exist
    if coverSrcFilePath is not None:
        coverDstFilePath = bookFolderDstPath.joinpath(coverSrcFilePath.name)
        if not coverDstFilePath.exists():
            os.symlink(coverSrcFilePath, coverDstFilePath)

    # Output a metadata xml (.opf) file into the destination book folder.
    # If folder mode is 'author,series,book' and series info was found,
    # mangle the book title (<dc:title>) by prepending the book's index
    # to it's title.
    # Otherwise, just write out a copy of the original metadata.
    if metadatadoc is not None:
        metadataDstFilePath = bookFolderDstPath.joinpath(metadataSrcFilePath.name)
        if series > '' and foldermode == 'author,series,book':
            titleel = metadatadoc.getElementsByTagName('dc:title')[0]
            titleel.firstChild.data = '{:>03s} - {}'.format(series_index, titleel.firstChild.data)
        try:
            docfile = open(metadataDstFilePath, 'w')
        except Exception as e:
            print(f'Could not create (or truncate existing) metadata file {metadataDstFilePath}', file=sys.stderr, flush=True)
            print(e, file=sys.stderr, flush=True)
            #print(traceback.format_exc(), file=sys.stderr, flush=True)

        try:
            metadatadoc.writexml(docfile)
        except Exception as e:
            print(f'Could not write metadata file {metadataDstFilePath}', file=sys.stderr, flush=True)
            print(e, file=sys.stderr, flush=True)
            #print(traceback.format_exc(), file=sys.stderr, flush=True)
        finally:
            docfile.close()
            
        metadatadoc.unlink()
            
def doConstruct(section):
    """Create (or update) one target book library that will be presented by jellyfin.
    """

    # convert multiline parameters to lists
    authorFolders = section['authorFolders'][1:].split('\n')
    bookfiletypes = section['bookfiletypes'][1:].split('\n')

    jellyfinStore = pathlib.Path(section['jellyfinStore'])
    foldermode = section['foldermode']
    
    # for each configured author
    for authorFolder in authorFolders:

        # get and create destination author folder
        authorSrcPath = pathlib.Path(os.path.join(section['calibreStore'], authorFolder))
        authorDstPath = pathlib.Path(os.path.join(jellyfinStore, authorFolder))
        if foldermode == 'author,series,book':
            authorDstPath.mkdir(parents=True, exist_ok=True)

        # for each book folder in source author folder
        for bookFolderSrcPath in authorSrcPath.iterdir():
            doBook(authorSrcPath, authorDstPath, bookFolderSrcPath, bookfiletypes, foldermode, jellyfinStore)
                
# ------------------
#	Main
# ------------------

# iterate over configured Construct sections

for section in config:
    if section[0:9] == 'Construct':
        try:
            doConstruct(config[section])
        except Exception as e:
            print(f'Unexpected error encountered constructing {section}', file=sys.stderr, flush=True)
            print(e, file=sys.stderr, flush=True)
            print(traceback.format_exc(), file=sys.stderr, flush=True)
            sys.exit(-1)
        
sys.exit(0)
