#!/usr/bin/python3

"""calibre2jellyfin.py

   Python script to construct a Jellyfin ebook library from a Calibre library.

   2023-11-17 initial revision, https://github.com/shawn61cp/calibre2jellyfin
   author Shawn C. Powell
   contributors Cudail
   license GPL3
"""

import sys
import configparser
import argparse
import re
import logging
from pathlib import Path
from xml.dom import minidom
from os import stat, utime

# ------------------
#   Globals
# ------------------


CONFIG_FILE_PATH = Path.home() / '.config' / (Path(__file__).stem + '.cfg')
CMDARGS: argparse.Namespace


# ------------------
#   Classes
# ------------------


class Construct:
    """Processes a configured [Construct] section"""
    author_folders: list[str]
    book_file_types: list[str]
    subjects: list[list[str]]
    calibre_store: Path
    jellyfin_store: Path
    foldermode: str
    mangle_meta_title: bool
    mangle_meta_title_sort: bool
    selection_mode: str

    def __init__(self, section: configparser.SectionProxy):

        try:
            # get simple configs
            self.selection_mode = section['selectionMode']
            self.calibre_store = Path(section['calibreStore'])
            self.jellyfin_store = Path(section['jellyfinStore'])
            self.foldermode = section['foldermode']
            self.mangle_meta_title = section.getboolean('mangleMetaTitle')
            self.mangle_meta_title_sort = section.getboolean('mangleMetaTitleSort')
            # convert multiline configs to lists
            self.book_file_types = section['bookfiletypes'][1:].split('\n')
            if self.selection_mode == 'author':
                self.author_folders = section['authorFolders'][1:].split('\n')
                self.subjects = [['']]
            else:
                self.subjects = [x.split(',') for x in section['subjects'][1:].lower().split('\n')]
                self.author_folders = []
        except Exception as excep:
            logging.critical(
                'A required parameter is missing from [%s] '
                'in configuration file "%s". : %s',
                section, CONFIG_FILE_PATH, excep
            )
            sys.exit(-1)

        # sanity check configuration parameters
        try:
            if not self.calibre_store.is_dir():
                raise ValueError(f'calibreStore value "{self.calibre_store}" is not a directory or does not exist')
            if not self.jellyfin_store.is_dir():
                raise ValueError(f'jellyfinStore value "{self.jellyfin_store}" is not a directory or does not exist')
            if self.jellyfin_store.samefile(self.calibre_store):
                raise ValueError('jellyfinStore and calibreStore must be different locations')
            if self.foldermode not in ('book', 'series,book', 'author,series,book'):
                raise ValueError('foldermode value must be "book", "series,book" or "author,series,book"')
            if self.selection_mode not in ('author', 'subject'):
                raise ValueError('selectionMode must be "author" or "subject"')
            if self.selection_mode == 'author' and self.author_folders[0] == '':
                raise ValueError('authorFolders must contain at least one entry')
            if self.selection_mode == 'subject' and self.subjects[0][0] == '':
                raise ValueError('subjects must contain at least one entry')
            if self.book_file_types[0] == '':
                raise ValueError('bookfiletypes must contain at least one entry')
        except ValueError as excep:
            logging.critical(
                'Inappropriate parameter value in %s in configuration file "%s": %s',
                section, CONFIG_FILE_PATH, excep
            )
            sys.exit(-1)

    def do_books_by_author(self) -> None:

        """Iterates Book.do() over configured authors.

            self          Construct object, data from config Construct section

            returns                 None
        """

        # for each configured author
        for author_folder in self.author_folders:

            book = Book(self, author_folder)
            if not book.author_folder_src_path:
                continue

            # for each book folder in source author folder
            for book.book_folder_src_path in book.author_folder_src_path.iterdir():
                if book.book_folder_src_path.is_dir():
                    book.get()
                    if CMDARGS.debug:
                        print(f'Book attributes: {vars(book)}')
                        print(f'Book metadata  : {vars(book.metadata)}')
                    book.do()

    def do_books_by_subject(self) -> None:

        """Iterates Book.do() over books having configured subjects.

            self          Construct object, data from config Construct section

            returns                 None
        """

        # for author folder in Calibre store
        for author_folder in self.calibre_store.iterdir():

            book = Book(self, author_folder.name)
            if not book.author_folder_src_path:
                continue

            # for each book folder in source author folder
            for book.book_folder_src_path in book.author_folder_src_path.iterdir():
                if book.book_folder_src_path.is_dir():
                    book.get()
                    if CMDARGS.debug:
                        print(f'Book attributes: {vars(book)}')
                        print(f'Book metadata  : {vars(book.metadata)}')
                    if book.check_subjects():
                        book.do()

    def do(self) -> None:

        """Create (or update) one target Jellyfin e-book library as defined by a configured Construct section

            section                 config parser section obj

            returns                 None
        """

        if CMDARGS.debug:
            print(f'[Construct] parameters: {vars(self)}')
            
        if self.selection_mode == 'author':
            self.do_books_by_author()
        else:
            self.do_books_by_subject()


class BookMetadata:
    """Retrieves, stores, and writes out metadata for a book"""
    doc: minidom.Document | None
    series: str
    series_index: str
    author: str
    subjects: list[str]
    titleel: minidom.Element | None
    sortel: minidom.Element | None
    descel: minidom.Element | None

    def __init__(self):
        self.doc = None
        self.series = ''
        self.series_index = ''
        self.author = ''
        self.subjects = []
        self.titleel = None
        self.sortel = None
        self.descel = None

    def get(self, metadata_file_path: Path | None) -> None:

        """Creates a miniDOM object from the metadata file and extracts
            various items of interest.

            metadata_file_path      pathlib.Path, full path to metadata file

            Returns                 None
        """

        if not metadata_file_path:
            return

        # open the metadata file and create a document object
        try:
            with open(metadata_file_path, 'r', encoding='utf8') as docfile:
                self.doc = minidom.parse(docfile)
        except OSError as excep:
            logging.warning('Could not read metadata file "%s": %s', metadata_file_path, excep)
            return
        except Exception as excep:
            logging.warning('Could not parse metadata file "%s": %s', metadata_file_path, excep)
            return

        # get series info and other elements

        titleels = self.doc.getElementsByTagName('dc:title')
        if titleels:
            self.titleel = titleels[0]

        authorels = self.doc.getElementsByTagName('dc:creator')
        if authorels:
            self.author = authorels[0].firstChild.data

        descels = self.doc.getElementsByTagName('dc:description')
        if descels:
            self.descel = descels[0]

        subjectels = self.doc.getElementsByTagName('dc:subject')
        if subjectels:
            self.subjects = [el.firstChild.data.lower() for el in subjectels]

        metatags = self.doc.getElementsByTagName('meta')
        for metatag in metatags:
            if metatag.getAttribute('name') == 'calibre:series':
                self.series = metatag.getAttribute('content')
            elif metatag.getAttribute('name') == 'calibre:series_index':
                self.series_index = metatag.getAttribute('content')
            elif metatag.getAttribute('name') == 'calibre:title_sort':
                self.sortel = metatag

    def write(self, metadata_file_dst_path: Path) -> None:

        """Writes out the book metadata

            metadata_file_dst_path      pathlib.Path(), full path to destination metadata file

            returns                     None
        """

        # create/truncate the metadata file and write it out
        if self.doc:
            try:
                with open(metadata_file_dst_path, 'w', encoding='utf8') as docfile:
                    self.doc.writexml(docfile)
            except OSError as excep:
                logging.warning('Could not (over) write metadata file "%s": %s', metadata_file_dst_path, excep)


class Book:
    """Exports one book"""
    author_folder_src_path: Path | None
    author_folder_dst_path: Path | None
    book_folder: str
    book_folder_src_path: Path | None
    book_folder_dst_path: Path | None
    book_file_src_path: Path | None
    book_file_dst_path: Path | None
    metadata_file_src_path: Path | None
    metadata_file_dst_path: Path | None
    cover_file_src_path: Path | None
    cover_file_dst_path: Path | None
    metadata: BookMetadata
    construct: Construct

    def __init__(self, construct: Construct, author_folder: str):
        self.construct = construct
        self.author_folder_src_path = construct.calibre_store / author_folder
        if not self.author_folder_src_path.is_dir() or self.author_folder_src_path.name[0:1]=='.':
            if construct.selection_mode == 'author':
                logging.warning(
                    'Author folder "%s" does not exist or is not a directory'
                    ' in Calibre store "%s".',
                    author_folder, construct.calibre_store
                )
            self.author_folder_src_path = None
        self.author_folder_dst_path = construct.jellyfin_store / author_folder
        self.book_folder = ''
        self.book_folder_src_path = None
        self.book_folder_dst_path = None
        self.book_file_src_path = None
        self.book_file_dst_path = None
        self.metadata_file_src_path = None
        self.metadata_file_dst_path = None
        self.cover_file_src_path = None
        self.cover_file_dst_path = None
        self.metadata = BookMetadata()

    def get(self):

        """Constructs paths, files, and metadata pertinent to the book"""

        # find first instance of configured book file types
        self.book_file_src_path = find_book(self.construct.book_file_types, self.book_folder_src_path)
        if not self.book_file_src_path:
            return

        # locate related book files
        self.book_folder = self.book_folder_src_path.name
        self.metadata_file_src_path = find_metadata(self.book_folder_src_path)
        self.cover_file_src_path = find_cover(self.book_folder_src_path)
        self.metadata.get(self.metadata_file_src_path)

        # Output is organized as '.../author/series/book/book.ext', '.../series/book/book.ext'
        # or '.../book/book.ext' depending on foldermode.  If series info was expected but not found,
        # output structure collapses to '.../author/book/book.ext' in author,series,book mode
        # or '.../book/book.ext' in series,book mode.
        # If series info was expected and found, then mangle the book's folder name by prepending
        # the book's series index. Once the folder structure has been determined,
        # create the destination folder(s) if they do not exist.

        if self.metadata.series and self.construct.foldermode in ['author,series,book', 'series,book']:
            self.book_folder = sanitize_filename(f'{format_series_index(self.metadata.series_index)} - {self.book_folder}')
            if self.construct.foldermode == 'author,series,book':
                self.book_folder_dst_path = self.author_folder_dst_path / sanitize_filename(f'{self.metadata.series} Series') / self.book_folder
            else:
                self.book_folder_dst_path = self.construct.jellyfin_store / sanitize_filename(f'{self.metadata.series} Series') / self.book_folder
        elif self.construct.foldermode in ['book', 'series,book']:
            self.book_folder_dst_path = self.construct.jellyfin_store / self.book_folder
        else:
            self.book_folder_dst_path = self.author_folder_dst_path / self.book_folder

        self.book_file_dst_path = self.book_folder_dst_path / self.book_file_src_path.name

        if self.cover_file_src_path is not None:
            self.cover_file_dst_path = self.book_folder_dst_path / self.cover_file_src_path.name

        if self.metadata.doc and self.metadata_file_src_path:
            self.metadata_file_dst_path = self.book_folder_dst_path / self.metadata_file_src_path.name

    def do(self) -> None:

        """Creates folder, files and symlinks for one book.

            returns                 None
        """

        if not self.book_file_src_path:
            if self.construct.selection_mode == 'author':
                logging.warning('No book file of configured type was found in "%s"', self.book_folder_src_path)
            return

        print(self.book_folder_src_path, flush=True)

        if self.metadata.doc and not self.metadata.titleel:
            logging.warning(
                'Missing normally required <dc:title> element in metadata for "%s"',
                self.book_folder_src_path
            )

        if self.metadata.doc and not self.metadata.author:
            logging.warning(
                'Missing normally required <dc:creator> (i.e. author) element in metadata for "%s"',
                self.book_folder_src_path
            )

        if CMDARGS.dryrun:
            return

        # Create the destination book folder
        try:
            self.book_folder_dst_path.mkdir(parents=True, exist_ok=True)
        except OSError as excep:
            logging.warning(
                'Could not create book\'s destination folder (or a parent folder thereof) '
                '"%s": %s', self.book_folder_dst_path, excep
            )
            if self.metadata.doc:
                self.metadata.doc.unlink()
                self.metadata.doc = None
            return

        # Create a symlink to the source book if it does not exist
        # If it exists and is out of date, touch it; This helps jellyfin respond quickly to changes.
        if self.book_file_dst_path.exists():
            if stat(self.book_file_dst_path, follow_symlinks=False).st_mtime < stat(self.book_file_src_path).st_mtime:
                try:
                    utime(self.book_file_dst_path, follow_symlinks=False)
                except OSError as excep:
                    logging.warning(
                        'Could not touch book symlink %s: %s', self.book_file_dst_path, excep
                    )
        else:
            try:
                self.book_file_dst_path.symlink_to(self.book_file_src_path)
            except OSError as excep:
                logging.warning(
                    'Could not create book symlink "%s": %s', self.book_file_dst_path, excep
                )

        # Create a symlink to the cover image if it does not exist
        # If it exists and is out of date, touch it; This helps jellyfin respond quickly to changes.
        if self.cover_file_src_path:
            if self.cover_file_dst_path.exists():
                if stat(self.cover_file_dst_path, follow_symlinks=False).st_mtime < stat(self.cover_file_src_path).st_mtime:
                    try:
                        utime(self.cover_file_dst_path, follow_symlinks=False)
                    except OSError as excep:
                        logging.warning(
                            'Could not touch cover image symlink %s: %s',
                            self.cover_file_dst_path, excep
                        )
            else:
                try:
                    self.cover_file_dst_path.symlink_to(self.cover_file_src_path)
                except OSError as excep:
                    logging.warning(
                        'Could not create cover image symlink "%s": %s',
                        self.cover_file_dst_path, excep
                    )

        # Output a metadata xml (.opf) file into the destination book folder.
        # If folder mode is 'author,series,book' or 'series,book', series info was found,
        # and mangling is enabled, mangle the book title (<dc:title>) and/or title_sort
        # elements by prepending the book's index to it's title.
        # Also prepend a "Book X of Lorem Ipsum" header to the book description.
        # Otherwise, write out the original metadata unchanged.

        if self.metadata.doc and self.metadata_file_src_path:
            copy_metadata = False

            if CMDARGS.updateAllMetadata:
                copy_metadata = True
            elif self.metadata_file_dst_path.exists():
                if stat(self.metadata_file_dst_path).st_mtime < stat(self.metadata_file_src_path).st_mtime:
                    copy_metadata = True
            else:
                copy_metadata = True

            if copy_metadata:
                if self.metadata.series and self.construct.foldermode in ['author,series,book', 'series,book']:
                    if self.metadata.titleel and self.construct.mangle_meta_title:
                        self.metadata.titleel.firstChild.data = f'{format_series_index(self.metadata.series_index)} - {self.metadata.titleel.firstChild.data}'
                    if self.metadata.sortel and self.construct.mangle_meta_title_sort:
                        self.metadata.sortel.setAttribute(
                            'content',
                            f'{format_series_index(self.metadata.series_index)} - {self.metadata.sortel.getAttribute("content")}'
                        )
                    if self.metadata.descel:
                        self.metadata.descel.firstChild.data = f'<H4>Book {self.metadata.series_index} of <em>{self.metadata.series}</em>, by {self.metadata.author}</H4>{self.metadata.descel.firstChild.data}'

                self.metadata.write(self.metadata_file_dst_path)

            self.metadata.doc.unlink()
            self.metadata.doc = None

    def check_subject_line(self, line: list[str]) -> bool:
        """Tests one line from required- subjects

            returns:        True if line's items exist in book metadata subjects
                            False otherwise
        """

        # Note: Depends on both metadata subjects and configuration subjects
        # having been set up for case insensitive comparison (i.e. all made
        # lower case or upper case)

        for item in line:
            if item.strip() not in self.metadata.subjects:
                return False
        return True

    def check_subjects(self) -> bool:

        """Determines whether the book subjects match any of the subjects
        required by the Construct section

            returns:        True if matched, False otherwise
        """

        for line in self.construct.subjects:
            if self.check_subject_line(line):
                return True
        return False


# ------------------
#   Functions
# ------------------


def find_book(book_file_types: list[str], book_folder_src_path: Path) -> Path | None:

    """Locates first instance of a file having an configured book extension

        book_file_types         [], list of file extensions identifying books (exclude periods)
        book_folder_src_path    pathlib.Path, full path to book folder to search

        returns                 pathlib.Path, full path to located book file
                                None if not found
    """

    for type_ext in book_file_types:
        for book_file_path in book_folder_src_path.glob('*.' + type_ext):
            return book_file_path
    return None


def find_metadata(book_folder_src_path: Path) -> Path | None:

    """Locates first instance of a metadata file (one w an .opf extension)

        book_folder_src_path    pathlib.Path, full path to book folder to search

        returns                 pathlib.Path, full path to metadata file
                                None if not found
    """

    for metadata_file_path in book_folder_src_path.glob('*.opf'):
        return metadata_file_path
    return None


def find_cover(book_folder_src_path: Path) -> Path | None:

    """Locates instance of a book cover image

        book_folder_src_path    pathlib.Path, full path to book folder to search

        returns                 pathlib.Path, full path to cover image
                                None if not found
    """

    for cover_file_path in book_folder_src_path.glob('cover.jpg'):
        return cover_file_path
    return None


def format_series_index(series_index: str) -> str:

    """Formats series index string

        series_index            str, series index str extracted from metadata, may be empty

        returns                 str, formatted series index
                                examples:
                                ''          ->  '999'
                                '3'         ->  '003'
                                '34'        ->  '034'
                                '345'       ->  '345'
                                '3456'      ->  '3456'
                                '3.2'       ->  '003.02'
    """

    if not series_index:
        return '999'

    if '.' in series_index:
        i = series_index.index('.')
        return f'{series_index[0:i]:>03s}.{series_index[i+1:]:>02s}'

    return f'{series_index:>03s}'


def sanitize_filename(sani: str) -> str:

    """Removes illegal characters from strings that will be incorporated in
    file names.

        sani                string to sanitize

        returns             sanitized string

    From:   stackoverflow thread
            https://stackoverflow.com/questions/7406102/create-sane-safe-filename-from-any-unsafe-string
    By:     Mitch McMabers https://stackoverflow.com/users/8874388/mitch-mcmabers and others
    """

    # illegal chars
    sani = re.sub(r"[/\\?%*:|\"<>\x7F\x00-\x1F]", "-", sani)
    # windows illegal file names
    sani = re.sub(
        r"^ ?(CON|CONIN\$|CONOUT\$|PRN|AUX|CLOCK\$|NUL|"
        r"COM0|COM1|COM2|COM3|COM4|COM5|COM6|COM7|COM8|COM9|"
        r"LPT0|LPT1|LPT2|LPT3|LPT4|LPT5|LPT6|LPT7|LPT8|LPT9|"
        r"LST|KEYBD\$|SCREEN\$|\$IDLE\$|CONFIG\$)([. ]|$)",
        '-', sani, flags=re.IGNORECASE
    )
    # windows illegal chars at start/end
    sani = re.sub(r"^ |[. ]$", '-', sani)

    return sani


# ------------------
#   Main
# ------------------


def main(clargs: list[str] | None = None):

    """Main

        clargs                      [], list of command line arguments
                                    used to invoke when/if calibre2jellyfin is loaded as a module
                                    example:
                                    calibre2jellyfin.main(['--update-all-metadata', ...])
    """

    global CMDARGS

    logging.basicConfig(format='%(levelname)s:%(filename)s:%(lineno)s: %(message)s', level=logging.DEBUG)

    # Parse command line arguments
    cmdparser = argparse.ArgumentParser(
        description='A utility to construct a Jellyfin ebook library from a Calibre library.'
        f' Configuration file "{CONFIG_FILE_PATH}" is required.'
    )
    cmdparser.add_argument(
        '--update-all-metadata',
        dest='updateAllMetadata',
        action='store_true',
        help='Useful to force a one-time update of all metadata files, '
        'for instance when configurable metadata mangling options have changed. '
        '(Normally metadata files are only updated when missing or out-of-date.)'
    )
    cmdparser.add_argument(
        '--dryrun',
        dest='dryrun',
        action='store_true',
        help='Displays normal console output but makes no changes to exported libraries.'
    )
    cmdparser.add_argument(
        '--debug',
        dest='debug',
        action='store_true',
        help='Emit debug information.'
    )
    CMDARGS = cmdparser.parse_args(clargs)

    # read configuration
    try:
        with open(CONFIG_FILE_PATH, 'r', encoding='utf8') as configfile:
            config = configparser.ConfigParser()
            config.read_file(configfile)
    except OSError as configexcep:
        logging.critical('Could not read configuration "%s": %s', CONFIG_FILE_PATH, configexcep)
        sys.exit(-1)
    except configparser.Error as configexcep:
        logging.critical('Invalid configuration "%s": %s', CONFIG_FILE_PATH, configexcep)
        sys.exit(-1)

    logging.info('Using configuration "%s"', CONFIG_FILE_PATH)

    # Default mangling behavior to that of original script
    config['DEFAULT']['mangleMetaTitle'] = '1'
    config['DEFAULT']['mangleMetaTitleSort'] = '0'
    config['DEFAULT']['selectionMode'] = 'author'
    config['DEFAULT']['subjects'] = ''

    # for each configured Construct
    for section in config:
        if section[0:9] == 'Construct':
            construct = Construct(config[section])
            construct.do()


if __name__ == '__main__':
    main()
