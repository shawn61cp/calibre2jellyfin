#!/usr/bin/python3

#   calibre2jellyfin.py
#
#   Python script to construct a Jellyfin ebook library from a Calibre library.
#
#   2023-11-17 initial revision
#   author Shawn C. Powell
#

import configparser
import argparse
from sys import stderr, exit
from pathlib import Path
from xml.dom import minidom
import re

# ------------------
#   Set up
# ------------------


def logError(msg, e):
    """Disposes error messages

        msg                 str, error message
        e                   Exception

        returns            None
    """
    print(msg, file=stderr, flush=True)
    print(e, file=stderr, flush=True)


configfilepath = Path.home() / '.config' / (Path(__file__).stem + '.cfg')

# Parse command line arguments

cmdparser = argparse.ArgumentParser(
    description='A utility to construct a Jellyfin ebook library from a Calibre library.'
    f' Configuration file {configfilepath} is required.'
)
cmdargs = cmdparser.parse_args()

# read configuration

try:
    configfile = open(configfilepath, 'r')
except Exception as e:
    logError(f'Could not open configuration {configfilepath}', e)
    exit(-1)

try:
    config = configparser.ConfigParser()
    config.read_file(configfile)
except Exception as e:
    logError(f'Could not read configuration {configfilepath}', e)
    exit(-1)
finally:
    configfile.close()

print('Using configuration', configfilepath, sep=' ', flush=True)


# ------------------
#   Functions
# ------------------

def findBook(bookfiletypes, bookFolderSrcPath):
    """Locates first instance of a file having an configured book extension

        bookfiletypes       [], list of file extensions identifying books (exclude periods)
        bookFolderSrcPath   pathlib.Path, full path to book folder to search

        returns             pathlib.Path, full path to located book file
                            None if not found
    """
    for typeExt in bookfiletypes:
        for bookFilePath in bookFolderSrcPath.glob('*.' + typeExt):
            return bookFilePath
    return None


def findMetadata(bookFolderSrcPath):
    """Locates first instance of a metadata file (one w an .opf extension)

        bookFolderSrcPath   pathlib.Path, full path to book folder to search

        returns             pathlib.Path, full path to metadata file
                            None if not found
    """
    for metadataFilePath in bookFolderSrcPath.glob('*.opf'):
        return metadataFilePath
    return None


def findCover(bookFolderSrcPath):
    """Locates instance of a book cover image

        bookFolderSrcPath   pathlib.Path, full path to book folder to search

        returns             pathlib.Path, full path to cover image
                            None if not found
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
        return doc, series, series_index

    # open the metadata file
    try:
        docfile = open(metadataFilePath)
    except Exception as e:
        logError(f'Could not open metadata file {metadataFilePath}', e)
        return doc, series, series_index

    # create a document object from the metadata file
    try:
        doc = minidom.parse(docfile)
    except Exception as e:
        doc = None
        logError(f'Could not read metadata file {metadataFilePath}', e)
        return doc, series, series_index
    finally:
        docfile.close()

    # get series info
    metas = doc.getElementsByTagName('meta')
    for m in metas:
        if m.getAttribute('name') == 'calibre:series':
            series = m.getAttribute('content')
        elif m.getAttribute('name') == 'calibre:series_index':
            series_index = m.getAttribute('content')

    docfile.close()
    return doc, series, series_index


def writeMetadata(metadatadoc, metadataDstFilePath):
    """Writes out the book metadata

        metadatadoc             minidom doc, doc object from source metadata
        metadataDstFilePath     pathlib.Path(), full path to destination metadata file

        returns                 None
    """
    try:
        docfile = open(metadataDstFilePath, 'w')
    except Exception as e:
        logError(
            f'Could not create (or truncate existing) metadata file {metadataDstFilePath}',
            e
        )
        return

    try:
        metadatadoc.writexml(docfile)
    except Exception as e:
        logError(f'Could not write metadata file {metadataDstFilePath}', e)
    finally:
        docfile.close()


def sanitizeFilename(s):
    """Removes illegal characters from strings that will be incorporated in
    file names.

        s                   string to sanitize
        returns             sanitized string

    From: stackoverflow thread https://stackoverflow.com/questions/7406102/create-sane-safe-filename-from-any-unsafe-string
    By: Mitch McMabers https://stackoverflow.com/users/8874388/mitch-mcmabers and others
    """
    
    # illegal chars
    z = re.sub(r"[/\\?%*:|\"<>\x7F\x00-\x1F]", "-", s)
#    # windows illegal file names
#    z = re.sub(r"^(CON|CONIN\$|CONOUT\$|PRN|AUX|CLOCK\$|NUL|COM0|COM1|COM2|COM3|COM4|COM5|COM6|COM7|COM8|COM9|LPT0|LPT1|LPT2|LPT3|LPT4|LPT5|LPT6|LPT7|LPT8|LPT9|LST|KEYBD\$|SCREEN\$|\$IDLE\$|CONFIG\$)(\.|$)", '-', z, flags=re.IGNORECASE)
#    # windows illegal chars at start/end
#    z = re.sub(r"^ |[. ]$", '-', z)
    
    return z


def doBook(authorSrcPath, authorDstPath, bookFolderSrcPath, bookfiletypes, foldermode, jellyfinStore):
    """Creates folder, files and symlinks for one book.

        authorSrcPath       pathlib.Path, full path to source author folder
        authorDstPath       pathlib.Path, full path to destination author folder
        bookFolderSrcPath   pathlib.Path, full path to source book folder
        bookfiletypes       list, extensions identifying book files (exclude periods)
        foldermode          str, one of 'author,series,book' or 'book'
        jellyfinStore       pathlib.Path, full path top level output storage location
                            (i.e. will be jellyfin library folder)

        returns             None
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
    # If series info was expected but not found, output structure collapses to '.../author/book/book.ext'.
    # If series info was expected and found, then mangle the book's folder name by prepending the book's series index.
    # Once the folder structure has been determined, create the destination folder(s) if they do not exist.
    if series > '' and foldermode == 'author,series,book':
        if series_index == '':
            series_index = '99'
        bookFolder = sanitizeFilename('{:>03s} - {}'.format(series_index, bookFolder))
        bookFolderDstPath = authorDstPath / sanitizeFilename(series + ' Series') / bookFolder
    elif foldermode == 'book':
        bookFolderDstPath = jellyfinStore / bookFolder
    else:
        bookFolderDstPath = authorDstPath / bookFolder

    try:
        bookFolderDstPath.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logError(
            f'Could not create book\'s destination folder (or a parent folder thereof) {bookFolderDstPath}',
            e
        )
        if metadatadoc is not None:
            metadatadoc.unlink()
        return

    # Create a symlink to the source book if it does not exist
    bookFileDstPath = bookFolderDstPath / bookFileSrcPath.name
    if not bookFileDstPath.exists():
        try:
            bookFileDstPath.symlink_to(bookFileSrcPath)
        except Exception as e:
            logError(f'Could not create book symlink {bookFileDstPath}', e)

    # Create a symlink to the cover image if it does not exist
    if coverSrcFilePath is not None:
        coverDstFilePath = bookFolderDstPath / coverSrcFilePath.name
        if not coverDstFilePath.exists():
            try:
                coverDstFilePath.symlink_to(coverSrcFilePath)
            except Exception as e:
                logError(f'Could not create cover image symlink {coverDstFilePath}', e)

    # Output a metadata xml (.opf) file into the destination book folder.
    # If folder mode is 'author,series,book' and series info was found,
    # mangle the book title (<dc:title>) by prepending the book's index
    # to it's title.
    # Otherwise, just write out a copy of the original metadata.
    if metadatadoc is not None:
        metadataDstFilePath = bookFolderDstPath / metadataSrcFilePath.name
        if series > '' and foldermode == 'author,series,book':
            titleel = metadatadoc.getElementsByTagName('dc:title')[0]
            titleel.firstChild.data = '{:>03s} - {}'.format(series_index, titleel.firstChild.data)

        writeMetadata(metadatadoc, metadataDstFilePath)
        metadatadoc.unlink()


def doConstruct(section):
    """Create (or update) one target book library that will be presented by jellyfin.

        section             config parser section obj

        returns             None
    """

    # convert multiline parameters to lists
    authorFolders = section['authorFolders'][1:].split('\n')
    bookfiletypes = section['bookfiletypes'][1:].split('\n')

    calibreStore = Path(section['calibreStore'])
    jellyfinStore = Path(section['jellyfinStore'])
    foldermode = section['foldermode']

    # sanity check configuration parameters
    try:
        if not calibreStore.is_dir():
            raise ValueError(f'calibreStore value ("{calibreStore}") is not a directory')
        if not jellyfinStore.is_dir():
            raise ValueError(f'jellyfinStore value ("{jellyfinStore}") is not a directory')
        if jellyfinStore.samefile(calibreStore):
            raise ValueError(f'jellyfinStore and calibreStore values must be different locations')
        if foldermode != 'book' and foldermode != 'author,series,book':
            raise ValueError(f'foldermode value must be "book" or "author,series,book"')
        if authorFolders[0] == '':
            raise ValueError('authorFolders must contain at least one entry')
        if bookfiletypes[0] == '':
            raise ValueError('bookfiletypes must contain at least one entry')
    except Exception as e:
        logError(f'Inappropriate parameter value in configuration file {configfilepath}', e)
        exit(-1)

    # for each configured author
    for authorFolder in authorFolders:

        # get and create destination author folder
        authorSrcPath = calibreStore / authorFolder
        authorDstPath = jellyfinStore / authorFolder
        if foldermode == 'author,series,book':
            try:
                authorDstPath.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logError(f'Could not create author folder {authorDstPath}', e)
                continue

        # for each book folder in source author folder
        for bookFolderSrcPath in authorSrcPath.iterdir():
            doBook(authorSrcPath, authorDstPath, bookFolderSrcPath, bookfiletypes, foldermode, jellyfinStore)


# ------------------
#   Main
# ------------------


# for each configured Construct
for section in config:
    if section[0:9] == 'Construct':
        try:
            doConstruct(config[section])
        except Exception as e:
            logError(f'Unexpected error encountered constructing {section}', e)
            exit(-1)

exit(0)
