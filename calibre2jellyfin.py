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
VERSION: str = '2024-11-22'
report: list[str] = []

# ------------------
#   Classes
# ------------------


class Construct:

    """Processes a configured [Construct] section

        Attributes:
            See example calibre2jellyfin.cfg for additional info.

            author_folders: list[str]       Books in these author folders will be exported.
                                            Applies only when selection_mode == 'author'

            book_file_types: list[str]      Book file extensions, in order of precedence,
                                            that must match in order to be exported.

            subjects: list[list[str]]       Books matching any of these subjects will be
                                            exported.  Applies only when selection_mode == 'subject'

            calibre_store: Path             Full path to the source Calibre library

            jellyfin_store: Path            Full path to the destination Jellyfin library

            foldermode: str                 Destination library folder structure:
                                                'author,series,book'
                                                'series,book'
                                                'book'

            mangle_meta_title: bool         True if metadata title should be prefixed with
                                            series index.

            mangle_meta_title_sort: bool    True if metadata sort title should be prefixed
                                            with series index.

            selection_mode: str             Determines how books will be selected,
                                            either by 'author', 'subject', 'all'

            section_name: str               Name of current section

        Usage:

            ... initialize logging ...
            ... get command line args ...
            ... get configuration ...
            ... set configuration DEFAULTs if necessary ...
            ... iterate config [ConstructXXX] sections ...
                try:
                    construct = Construct(section)
                except KeyError ...     # required config parameter missing
                    ...
                except ValueError ...   # invalid config parameter value
                    ...

                construct.do()          # export the library as defined by
                                        # the current config [ConstructXXX] section
    """

    author_folders: list[str]
    book_file_types: list[str]
    subjects: list[list[str]]
    calibre_store: Path
    jellyfin_store: Path
    foldermode: str
    mangle_meta_title: bool
    mangle_meta_title_sort: bool
    selection_mode: str
    section_name: str

    def __init__(self, section: configparser.SectionProxy):

        """Initialize a Construct object from a configuration file [Section]

        Exceptions:
            KeyError
            Thrown by configparser when a required parameter is missing.

            ValueError
            Thrown by self when a configuration parameter is invalid.
        """

        self.section_name = section.name

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
        elif self.selection_mode == 'subject':
            self.subjects = [x.split(',') for x in section['subjects'][1:].lower().split('\n')]
            self.author_folders = []
        else:
            self.subjects = [['']]
            self.author_folders = []

        # sanity check configuration parameters
        if not self.calibre_store.is_dir():
            raise ValueError(f'calibreStore value "{self.calibre_store}" is not a directory or does not exist')
        if not self.jellyfin_store.is_dir():
            raise ValueError(f'jellyfinStore value "{self.jellyfin_store}" is not a directory or does not exist')
        if self.jellyfin_store.samefile(self.calibre_store):
            raise ValueError('jellyfinStore and calibreStore must be different locations')
        if self.foldermode not in ('book', 'series,book', 'author,series,book'):
            raise ValueError('foldermode value must be "book", "series,book" or "author,series,book"')
        if self.selection_mode not in ('author', 'subject', 'all'):
            raise ValueError('selectionMode must be "author", "subject", or "all"')
        if self.selection_mode == 'author' and self.author_folders[0] == '':
            raise ValueError('authorFolders must contain at least one entry')
        if self.selection_mode == 'subject' and self.subjects[0][0] == '':
            raise ValueError('subjects must contain at least one entry')
        if self.book_file_types[0] == '':
            raise ValueError('bookfiletypes must contain at least one entry')

    def do_books_by_author(self) -> None:

        """Iterates Book.do() over configured authors.

            returns:
                None
        """

        # for each configured author
        for author_folder in self.author_folders:

            author_folder_src_path = self.calibre_store / author_folder
            if not author_folder_src_path.is_dir():
                logging.warning(
                    'Author folder "%s" does not exist or is not a directory'
                    ' in Calibre store "%s".',
                    author_folder, self.calibre_store
                )
                continue

            # for each book folder in source author folder
            for book_folder_src_path in author_folder_src_path.iterdir():

                if not book_folder_src_path.is_dir():
                    continue

                book = Book(self, author_folder_src_path, book_folder_src_path)
                book.do()

    def do_books_all(self) -> None:

        """Iterates Book.do() over entire Calibre library.

            returns
                None
        """

        # for author folder in Calibre store
        for author_folder_src_path in self.calibre_store.iterdir():

            if not author_folder_src_path.is_dir() or author_folder_src_path.name[0:1] == '.':
                continue

            # for each book folder in source author folder
            for book_folder_src_path in author_folder_src_path.iterdir():

                if not book_folder_src_path.is_dir():
                    continue

                book = Book(self, author_folder_src_path, book_folder_src_path)
                book.do()

    def do(self) -> None:

        """Create (or update) one target Jellyfin e-book library as defined by a configured Construct section

            returns
                None
        """

        if CMDARGS.debug:
            print(f'[Construct] parameters: {vars(self)}', flush=True)

        if self.selection_mode == 'author':
            self.do_books_by_author()
        else:
            self.do_books_all()


class BookMetadata:

    """Retrieves, stores, and writes out metadata for a book

        Attributes:
            doc: minidom.Document | None        DOM object created from the book metadata file.
            series: str                         Series extracted from metadata.
            series_index: str                   Series index extracted from metadata.
            formatted_series_index: str         Formatted series index for use in folder names
            author: str                         Author name extracted from metadata.
            subjects: list[str]                 Subjects extracted from metadata.
            titleel: minidom.Element | None     Metadata title element.
            sortel: minidom.Element | None      Metadata title sort element.
            descel: minidom.Element | None      Metadata description element.

        Usage:

            # path_to_metadata_file may be None, in which case the object is
            # initialized but all attributes are None or empty
            metadata = BookMetadata(path_to_metadata_file)

            # if metadata was loaded successfully
            if metadata.doc:
                ...
                ...
                if metadata was changed:
                    metadata.write()
    """

    doc: minidom.Document | None
    series: str
    series_index: str
    formatted_series_index: str
    author: str
    subjects: list[str]
    titleel: minidom.Element | None
    sortel: minidom.Element | None
    descel: minidom.Element | None

    def __init__(self, metadata_file_path: Path | None):

        """Creates a miniDOM object from the metadata file and extracts
            various items of interest.

            metadata_file_path
                pathlib.Path, full path to metadata file

            Returns
                None

            Errors
                If the metata file cannot be read or cannot be parsed,
                the error is logged via logging and the function returns
                with the .doc attribute having a value of None.

                When the metadata is successfully read, but expected elements
                are simply missing, the corresponding attribute will be either None or empty.
        """

        self.doc = None
        self.series = ''
        self.series_index = ''
        self.formatted_series_index = ''
        self.author = ''
        self.subjects = []
        self.titleel = None
        self.sortel = None
        self.descel = None

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
            self.subjects = [el.firstChild.data.lower().strip() for el in subjectels]

        metatags = self.doc.getElementsByTagName('meta')
        for metatag in metatags:
            if metatag.getAttribute('name') == 'calibre:series':
                self.series = metatag.getAttribute('content')
            elif metatag.getAttribute('name') == 'calibre:series_index':
                self.series_index = metatag.getAttribute('content')
                self.format_series_index()
            elif metatag.getAttribute('name') == 'calibre:title_sort':
                self.sortel = metatag

    def format_series_index(self) -> None:

        """Formats series index string

            returns:
                None

            examples:
                ''          ->  '999'
                '3'         ->  '003'
                '34'        ->  '034'
                '345'       ->  '345'
                '3456'      ->  '3456'
                '3.2'       ->  '003.02'
        """

        if not self.series_index:
            self.formatted_series_index = '999'
            return

        if '.' in self.series_index:
            i = self.series_index.index('.')
            self.formatted_series_index = f'{self.series_index[0:i]:>03s}.{self.series_index[i+1:]:>02s}'
            return

        self.formatted_series_index = f'{self.series_index:>03s}'

    def write(self, metadata_file_dst_path: Path) -> None:

        """Writes out the book metadata

            metadata_file_dst_path      pathlib.Path(), full path to destination metadata file

            returns
                None

            Errors
                Failure to write the metadata is logged via logging.
        """

        # create/truncate the metadata file and write it out
        if self.doc:
            try:
                with open(metadata_file_dst_path, 'w', encoding='utf8') as docfile:
                    self.doc.writexml(docfile)
            except OSError as excep:
                logging.warning('Could not (over) write metadata file "%s": %s', metadata_file_dst_path, excep)


class Book:

    """Exports one book and related files

        Attributes:
            author_folder_src_path: Path            Full path to source author folder.
            author_folder_dst_path: Path            Full path to dest author folder.
            book_folder: str                        Name of dest book folder.
            book_folder_src_path: Path              Full path to source book folder.
            book_folder_dst_path: Path              Full path to dst book folder.
            book_file_src_path: Path | None         Full path to source book file.
            book_file_dst_path: Path | None         Full path to dest book file.
            metadata_file_src_path: Path | None     Full path to source metadata file.
            metadata_file_dst_path: Path | None     Full path to dest metadata file.
            cover_file_src_path: Path | None        Full path to source cover file.
            cover_file_dst_path: Path | None        Full path to dest cover file.
            metadata: BookMetadata                  Book's metadata
            construct: Construct                    Current configuration parameters
            list_format: str                        Format string for --list output
            matched_subject: str                    Subject spec that matched book

        Usage:

            ... path iteration, path checks, ...
                book = Book(construct, author_folder_src_path, book_folder_src_path)
                ... optionally check metadata was found (book.metadata.doc is not None) ...
                book.do()   # export the book
    """

    author_folder_src_path: Path
    author_folder_dst_path: Path
    book_folder: str
    book_folder_src_path: Path
    book_folder_dst_path: Path
    book_file_src_path: Path | None
    book_file_dst_path: Path | None
    metadata_file_src_path: Path | None
    metadata_file_dst_path: Path | None
    cover_file_src_path: Path | None
    cover_file_dst_path: Path | None
    metadata: BookMetadata
    construct: Construct

    def __init__(
        self,
        construct: Construct,
        author_folder_src_path: Path,
        book_folder_src_path: Path
    ):

        """Builds paths and retrieves metadata for the book.  Logic implementing
            output folder structure is here.

            Arguments:
                construct:
                    Construct object

                author_folder_str_path:
                    Path, Full path to author folder

                book_folder_src_path:
                    Path, Full path to book folder
        """
        self.construct = construct
        self.author_folder_src_path = author_folder_src_path
        self.author_folder_dst_path = construct.jellyfin_store / author_folder_src_path.name
        self.book_folder = book_folder_src_path.name
        self.book_folder_src_path = book_folder_src_path
        self.book_folder_dst_path = None
        self.book_file_src_path = None
        self.book_file_dst_path = None
        self.metadata_file_src_path = None
        self.metadata_file_dst_path = None
        self.cover_file_src_path = None
        self.cover_file_dst_path = None
        self.metadata = None
        self.list_format = ''
        self.matched_subject = ''

        # find first instance of configured book file types
        self.find_book()
        if not self.book_file_src_path:
            return

        # locate related book files
        self.find_cover()
        self.find_metadata()
        self.metadata = BookMetadata(self.metadata_file_src_path)

        # Output is organized as '.../author/series/book/book.ext', '.../series/book/book.ext'
        # or '.../book/book.ext' depending on foldermode.  If series info was expected but not found,
        # output structure collapses to '.../author/book/book.ext' in author,series,book mode
        # or '.../book/book.ext' in series,book mode.
        # If series info was expected and found, then mangle the book's folder name by prepending
        # the book's series index. Once the folder structure has been determined,
        # create the destination folder(s) if they do not exist.

        if self.metadata.series and self.construct.foldermode in ['author,series,book', 'series,book']:
            self.book_folder = sanitize_filename(f'{self.metadata.formatted_series_index} - {self.book_folder}')
            if self.construct.foldermode == 'author,series,book':
                self.book_folder_dst_path = self.author_folder_dst_path / sanitize_filename(f'{self.metadata.series} Series') / self.book_folder
            else:
                self.book_folder_dst_path = self.construct.jellyfin_store / sanitize_filename(f'{self.metadata.series} Series') / self.book_folder
        elif self.construct.foldermode in ['book', 'series,book']:
            self.book_folder_dst_path = self.construct.jellyfin_store / self.book_folder
        else:
            self.book_folder_dst_path = self.author_folder_dst_path / self.book_folder

        self.book_file_dst_path = self.book_folder_dst_path / self.book_file_src_path.name

        if self.cover_file_src_path:
            self.cover_file_dst_path = self.book_folder_dst_path / self.cover_file_src_path.name

        if self.metadata_file_src_path and self.metadata.doc:
            self.metadata_file_dst_path = self.book_folder_dst_path / self.metadata_file_src_path.name

        if CMDARGS.list_spec:
            cols = CMDARGS.list_spec.split(',')
            self.list_format = '\t'.join([f'{{{col}}}' for col in cols])

    def find_book(self) -> None:

        """Locates first instance of a file having an configured book extension

            Sets self.book_file_src_path = full Path to source book file,
            or unchanged if not found

            returns
                None
        """

        for type_ext in self.construct.book_file_types:
            for book_file_path in self.book_folder_src_path.glob('*.' + type_ext):
                self.book_file_src_path = book_file_path
                return

    def find_metadata(self) -> None:

        """Locates first instance of a metadata file (one w an .opf extension)

            Sets self.metadata_file_src_path = full Path to metadata file,
            or unchanged if not found

            returns
                None
        """

        for metadata_file_path in self.book_folder_src_path.glob('*.opf'):
            self.metadata_file_src_path = metadata_file_path
            return

    def find_cover(self) -> None:

        """Locates instance of a book cover image

            Sets self.cover_file_src_path = full Path to cover image,
            or unchanged if not found
        """

        for cover_file_path in self.book_folder_src_path.glob('cover.jpg'):
            self.cover_file_src_path = cover_file_path
            return

    def do_book(self) -> None:

        """Conditionally creates/updates destination book folder and file (symlink)

            returns
                None
        """

        # Create the destination book folder
        try:
            self.book_folder_dst_path.mkdir(parents=True, exist_ok=True)
        except OSError as excep:
            logging.warning(
                'Could not create book\'s destination folder (or a parent folder thereof) '
                '"%s": %s', self.book_folder_dst_path, excep
            )
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

    def do_cover(self) -> None:

        """Conditionally creates/updates cover image (symlink)

            returns
                None

            Notes:
                do_book() should be called first since it creates
                the book destination folder.
        """

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

    def do_metadata(self) -> None:

        """Conditionally outputs metadata file

            returns
                None

            Notes:
                do_book() should be called first since it creates
                the book destination folder.
        """

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
                        self.metadata.titleel.firstChild.data = f'{self.metadata.formatted_series_index} - {self.metadata.titleel.firstChild.data}'
                    if self.metadata.sortel and self.construct.mangle_meta_title_sort:
                        self.metadata.sortel.setAttribute(
                            'content',
                            f'{self.metadata.formatted_series_index} - {self.metadata.sortel.getAttribute("content")}'
                        )
                    if self.metadata.descel:
                        self.metadata.descel.firstChild.data = f'<H4>Book {self.metadata.series_index} of <em>{self.metadata.series}</em>, by {self.metadata.author}</H4>{self.metadata.descel.firstChild.data}'

                self.metadata.write(self.metadata_file_dst_path)

    def do_list(self) -> None:

        """Outputs report as specified by the --list command line argument

            returns
                None
        """

        if self.metadata.titleel:
            book = self.metadata.titleel.firstChild.data
        else:
            book = ''
        line = self.list_format.format(
            author=self.metadata.author,
            subject=self.matched_subject,
            section=self.construct.section_name,
            book=book,
            bfolder=self.book_folder_src_path.name,
            afolder=self.author_folder_src_path.name
        )
        if "{book}" not in self.list_format:
            if line in report:
                return
        report.append(line)
        
    def do(self) -> None:

        """Conditionally creates/updates folder, files and symlinks for one book.

            returns
                None

            Errors
                Failures and warnings are logged via logging but otherwise
                the function proceeds transparently and silently completing
                as much as possible.
        """

        if not self.book_file_src_path:
            if self.construct.selection_mode in ['author', 'all']:
                logging.warning('No book file of configured type was found in "%s"', self.book_folder_src_path)
            return

        if CMDARGS.debug:
            print(f'Book attributes:  {vars(self)}', flush=True)
            if self.metadata.doc:
                print(f'Book metadata:    {vars(self.metadata)}', flush=True)

        if not self.metadata_file_src_path:
            logging.warning('No metadata was found in "%s"', self.book_folder_src_path)

        if self.construct.selection_mode == 'subject':
            if not self.metadata.doc:
                return
            if not self.check_subjects():
                return

        if CMDARGS.list_spec:
            self.do_list()
            return

        print(self.book_folder_src_path, flush=True)

        if not self.cover_file_src_path:
            logging.warning('No cover image was found in "%s"', self.book_folder_src_path)

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
            print(f'> {self.book_file_dst_path}', flush=True)
            print(f'> {self.metadata_file_dst_path}', flush=True)
            print(f'> {self.cover_file_dst_path}', flush=True)
            return

        self.do_book()
        self.do_cover()
        self.do_metadata()

    def check_subject_line(self, line: list[str]) -> bool:

        """Tests one line from required subjects

            line:
                list[str], list of subjects that must all match one of the
                book's subjects

            returns:
                True if all subjects matched
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

            returns:
                True if matched, False otherwise
        """

        for line in self.construct.subjects:
            if self.check_subject_line(line):
                self.matched_subject = ",".join(line)
                return True
        return False


# ------------------
#   Functions
# ------------------


def sanitize_filename(sani: str) -> str:

    """Removes illegal characters from strings that will be incorporated in
    file names.

        sani
            str, string to sanitize

        returns
            str, sanitized string

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
        '--debug',
        dest='debug',
        action='store_true',
        help='Emit debug information.'
    )
    cmdparser.add_argument(
        '--dryrun',
        dest='dryrun',
        action='store_true',
        help='Displays normal console output but makes no changes to exported libraries.'
    )
    cmdparser.add_argument(
        '--list',
        dest='list_spec',
        action='store',
        help='Suspends normal export behavior.  Instead prints info from configuration sections and file system that is useful for curation.\n LIST_SPEC is a comma-delimited list of columns to include in the report.  The output is tab-separated.  Columns may be one or more of author, section, book, bfolder, afolder, or subject.  author: display author name if the source folder exists.  section: display section name.  book: display book title.  bfolder: display book folder.  afolder: display author folder.  subject: display subject that matched.  The report output is sorted so there will be a pause while all configured sections are processed.'
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
        '-v', '--version',
        dest='version',
        action='store_true',
        help='Display version string.'
    )
    CMDARGS = cmdparser.parse_args(clargs)

    if CMDARGS.version:
        print(f'version {VERSION}', flush=True)
        return

    if CMDARGS.list_spec:
        for report_col in CMDARGS.list_spec.split(','):
            if report_col not in ['section', 'author', 'book', 'subject', 'bfolder', 'afolder']:
                logging.critical('--list columns must be one or more of "section", "author", "book", "bfolder", "afolder", or "subject"')
                sys.exit(-1)

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
            try:
                construct = Construct(config[section])
            except ValueError as excep:
                logging.critical(
                    'Inappropriate parameter value in %s in configuration file "%s": %s',
                    section, CONFIG_FILE_PATH, excep
                )
                sys.exit(-1)
            except KeyError as excep:
                logging.critical(
                    'A required parameter (%s) is missing from [%s] '
                    'in configuration file "%s".',
                    excep, section, CONFIG_FILE_PATH
                )
                sys.exit(-1)
            construct.do()

    if CMDARGS.list_spec:
        report.sort()
        for line in report:
            print(line)


if __name__ == '__main__':
    main()
