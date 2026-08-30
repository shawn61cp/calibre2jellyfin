#!/usr/bin/python3

"""calibre2jellyfin.py

   Python script to construct a Jellyfin ebook library from a Calibre library.

   2023-11-17 initial revision, https://github.com/shawn61cp/calibre2jellyfin
   author Shawn C. Powell
   contributors Cudail
   license GPL3

   Copyright (C) 2023-2026  Shawn C. Powell and Contributors.
   
   This program is free software: you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation, either version 3 of the License, or
   (at your option) any later version.
   
   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.
   
   You should have received a copy of the GNU General Public License
   along with this program.  If not, see <https://www.gnu.org/licenses/>.   
"""

import sys
import configparser
import argparse
import textwrap
import re
import logging
import gettext
from pathlib import Path
from xml.dom import minidom
from os import stat, utime

# ------------------
#   Globals
# ------------------

_t = gettext.translation(
	'calibre2jellyfin', 
	localedir=Path(__file__).resolve().parent / 'calibre2jellyfin.locale'
)
_ = _t.gettext

CONFIG_FILE_PATH = Path.home() / '.config' / (Path(__file__).stem + '.cfg')
CMDARGS: argparse.Namespace
VERSION: str = '2026-03-17'
report: dict = {}
list_format: str = ''

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

			mangle_meta_title: integer      0 - disable, 1 - formatted, 2 - unformatted

			mangle_meta_title_sort: bool    True if metadata sort title should be prefixed
											with series index.

			selection_mode: str             Determines how books will be selected,
											either by 'author', 'subject', 'all'

			section_name: str               Name of current section

			prescan: bool                   True if report is being pre-loaded for --invert output

			additional_authors:bool         True if books are to be output under the additional authors

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
	mangle_meta_title: int
	mangle_meta_title_sort: bool
	selection_mode: str
	section_name: str
	prescan: bool
	additional_authors: bool

	def __init__(self, section: configparser.SectionProxy):

		"""Initialize a Construct object from a configuration file [Section]

		Exceptions:
			KeyError
			Thrown by configparser when a required parameter is missing.

			ValueError
			Thrown by self when a configuration parameter is invalid.
		"""

		self.section_name = section.name
		self.prescan = False

		# get simple configs
		self.selection_mode = section['selectionMode']
		self.calibre_store = Path(section['calibreStore'])
		self.jellyfin_store = Path(section['jellyfinStore'])
		self.foldermode = section['foldermode']
		self.mangle_meta_title = section.getint('mangleMetaTitle')
		self.mangle_meta_title_sort = section.getboolean('mangleMetaTitleSort')
		self.additional_authors = section.getboolean('additionalAuthors')
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
			raise ValueError(_('calibreStore value "{calibre_store}" is not a directory or does not exist').format(calibre_store=self.calibre_store))
		if not self.jellyfin_store.is_dir():
			raise ValueError(_('jellyfinStore value "{jellyfin_store}" is not a directory or does not exist').format(jellyfin_store=self.jellyfin_store))
		if self.jellyfin_store.samefile(self.calibre_store):
			raise ValueError(_('jellyfinStore and calibreStore must be different locations'))
		if self.foldermode not in ('book', 'series,book', 'author,series,book'):
			raise ValueError(_('foldermode must be "book", "series,book" or "author,series,book"'))
		if self.selection_mode not in ('author', 'subject', 'all'):
			raise ValueError(_('selectionMode must be "author", "subject" or "all"'))
		if self.selection_mode == 'author' and self.author_folders[0] == '':
			raise ValueError(_('authorFolders must contain at least one entry'))
		if self.selection_mode == 'subject' and self.subjects[0][0] == '':
			raise ValueError(_('subjects must contain at least one entry'))
		if self.book_file_types[0] == '':
			raise ValueError(_('bookfiletypes must contain at least one entry'))
		if self.mangle_meta_title and (self.mangle_meta_title < 0 or self.mangle_meta_title > 2):
			raise ValueError(_('mangleMetaTitle must be 0, 1, or 2'))

	def do_books_by_author(self) -> None:

		"""Iterates Book.do() over configured authors.

			returns:
				None
		"""

		# for each configured author
		for author_folder in self.author_folders:

			author_folder_src_path = self.calibre_store / author_folder
			if not author_folder_src_path.is_dir():
				if not self.prescan:
					logging.warning(
						_('Author folder "%s" does not exist or is not a directory in Calibre store "%s".'),
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

		logging.info(_('Processing [%s]:'), self.section_name)

		if CMDARGS.debug:
			print(_('[Construct] parameters: {vars}').format(vars=vars(self)), flush=True)

		if self.prescan and str(self.calibre_store) in report:
			return

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
			authors: str                        Comma delimited list of authors
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
	authors: str
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
		self.authors = ''
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
			logging.warning(_('Could not read metadata file "%s": %s'), metadata_file_path, excep)
			return
		except Exception as excep:
			logging.warning(_('Could not parse metadata file "%s": %s'), metadata_file_path, excep)
			return

		# get series info and other elements

		titleels = self.doc.getElementsByTagName('dc:title')
		if titleels:
			self.titleel = titleels[0]

		authorels = self.doc.getElementsByTagName('dc:creator')
		if authorels:
			self.authors = ', '.join([el.firstChild.data for el in authorels])

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
			self.formatted_series_index = '{series_index:>03s}.{series_index[i+1:]:>02s}'.format(series_index=self.series_index[0:i])
			return

		self.formatted_series_index = '{series_index:>03s}'.format(series_index=self.series_index)

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
				logging.warning(_('Could not write or overwrite metadata file "%s": %s'), metadata_file_dst_path, excep)


class Book:

	"""Exports one book and related files

		Attributes:
			author_folder_src_path: Path            Full path to source author folder.
			author_folder_dst_path: Path            Full path to dest author folder.
			override_author_folder_dst_name: str    Override destination author folder.
													Used to output books to their additional
													authors.  Also non-empty value indicates recursion.
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
			matched_subject: str                    Subject spec that matched book

		Usage:

			... path iteration, path checks, ...
				book = Book(construct, author_folder_src_path, book_folder_src_path)
				book.do()   # export the book
	"""

	author_folder_src_path: Path
	author_folder_dst_path: Path
	override_author_folder_dst_name: str
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
		book_folder_src_path: Path,
		override_author_folder_dst_name:str = ''
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

				override_author_folder_dst_name
					str, overrides name of output author folder, only effective when folder mode is 'author,series,book'
					
		"""
		self.construct = construct
		self.author_folder_src_path = author_folder_src_path
		self.override_author_folder_dst_name = override_author_folder_dst_name
		if self.override_author_folder_dst_name:
			if self.override_author_folder_dst_name[-1] == '.':
				self.override_author_folder_dst_name[-1] = '_'
			self.override_author_folder_dst_name = sanitize_filename(self.override_author_folder_dst_name)
			self.author_folder_dst_path = construct.jellyfin_store / self.override_author_folder_dst_name
		else:
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
			self.book_folder = sanitize_filename(
				'{formatted_series_index}'.format(formatted_series_index=self.metadata.formatted_series_index) +
				' - {book_folder}'.format(book_folder=self.book_folder)
			)
			if self.construct.foldermode == 'author,series,book':
				self.book_folder_dst_path = (
					self.author_folder_dst_path
					/ sanitize_filename(_('{series} Series').format(series=self.metadata.series))
					/ self.book_folder
				)
			else:
				self.book_folder_dst_path = (
					self.construct.jellyfin_store
					/ sanitize_filename(_('{series} Series').format(series=self.metadata.series))
					/ self.book_folder
				)
		elif self.construct.foldermode in ['book', 'series,book']:
			self.book_folder_dst_path = self.construct.jellyfin_store / self.book_folder
		else:
			self.book_folder_dst_path = self.author_folder_dst_path / self.book_folder

		self.book_file_dst_path = self.book_folder_dst_path / self.book_file_src_path.name

		if self.cover_file_src_path:
			self.cover_file_dst_path = self.book_folder_dst_path / self.cover_file_src_path.name

		if self.metadata_file_src_path and self.metadata.doc:
			self.metadata_file_dst_path = self.book_folder_dst_path / self.metadata_file_src_path.name

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

		"""Conditionally creates/updates destination book file (symlink)

			returns
				None
		"""

		# Create a symlink to the source book if it does not exist
		# If it exists and is out of date, touch it; This helps jellyfin respond quickly to changes.
		if self.book_file_dst_path.exists():
			if (
				stat(self.book_file_dst_path, follow_symlinks=False).st_mtime
				< stat(self.book_file_src_path).st_mtime
			):
				try:
					utime(self.book_file_dst_path, follow_symlinks=False)
				except OSError as excep:
					logging.warning(
						_('Could not touch book symlink %s: %s'), self.book_file_dst_path, excep
					)
		else:
			try:
				self.book_file_dst_path.symlink_to(self.book_file_src_path)
			except OSError as excep:
				logging.warning(
					_('Could not create book symlink "%s": %s'), self.book_file_dst_path, excep
				)

	def do_cover(self) -> None:

		"""Conditionally creates/updates cover image (symlink)

			returns
				None

		"""

		# Create a symlink to the cover image if it does not exist
		# If it exists and is out of date, touch it; This helps jellyfin respond quickly to changes.

		if self.cover_file_src_path:
			if self.cover_file_dst_path.exists():
				if (
					stat(self.cover_file_dst_path, follow_symlinks=False).st_mtime
					< stat(self.cover_file_src_path).st_mtime
				):
					try:
						utime(self.cover_file_dst_path, follow_symlinks=False)
					except OSError as excep:
						logging.warning(
							_('Could not touch cover image symlink %s: %s'),
							self.cover_file_dst_path, excep
						)
			else:
				try:
					self.cover_file_dst_path.symlink_to(self.cover_file_src_path)
				except OSError as excep:
					logging.warning(
						_('Could not create cover image symlink "%s": %s'),
						self.cover_file_dst_path, excep
					)

	def mangle_series_metadata(self) -> None:
		"""Conditionally mangles metadata (title and title-sort) with series info.

			returns
				None

			requires
				self.metadata.series
				self.metadata.formatted_series_index

		"""

		if self.construct.foldermode not in ['author,series,book', 'series,book']:
			return

		if self.metadata.titleel:
			if self.construct.mangle_meta_title == 1:
				self.metadata.titleel.firstChild.data = (
					'{formatted_series_index}'.format(formatted_series_index=self.metadata.formatted_series_index) +
					' - {data}'.format(data=self.metadata.titleel.firstChild.data)
				)
			elif self.construct.mangle_meta_title == 2:
				self.metadata.titleel.firstChild.data = (
					'{series_index}'.format(series_index=self.metadata.series_index) +
					' - {data}'.format(data=self.metadata.titleel.firstChild.data)
				)

		if self.metadata.sortel and self.construct.mangle_meta_title_sort:
			self.metadata.sortel.setAttribute(
				'content',
				'{formatted_series_index}'.format(formatted_series_index=self.metadata.formatted_series_index) +
				' - {attribute}'.format(attribute=self.metadata.sortel.getAttribute("content"))
			)

	def do_metadata(self) -> None:

		"""Conditionally outputs the metadata file.

			returns
				None

		"""

		# Output a metadata xml (.opf) file into the destination book folder.
		# If folder mode is 'author,series,book' or 'series,book', series info was found,
		# and mangling is enabled, mangle the book title (<dc:title>) and/or title_sort
		# elements by prepending the book's index to it's title.
		# Also prepend a "Book X of Lorem Ipsum, by Author..." header to the book description.
		# Otherwise, write out the original metadata unchanged.

		if not (self.metadata.doc and self.metadata_file_src_path):
			return

		copy_metadata = False

		if CMDARGS.updateAllMetadata:
			copy_metadata = True
		elif self.metadata_file_dst_path.exists():
			if stat(self.metadata_file_dst_path).st_mtime < stat(self.metadata_file_src_path).st_mtime:
				copy_metadata = True
		else:
			copy_metadata = True

		if not copy_metadata:
			return

		desc_header = []

		if self.metadata.series:
			self.mangle_series_metadata()
			desc_header.append(
				_('Book') + ' ' + self.metadata.series_index +
				' ' + _('of') + ' <em>' + self.metadata.series + '</em>'
			)

		if self.metadata.authors:
			desc_header.append(_('by') + ' ' + self.metadata.authors)

		if self.metadata.descel and desc_header:
			self.metadata.descel.firstChild.data = (
				'<H4>{header}</H4>{data}'.format(
					header=', '.join(desc_header),
					data=self.metadata.descel.firstChild.data
				)
			)

		self.metadata.write(self.metadata_file_dst_path)

	def do_additional_authors(self) -> None:

		"""Outputs book to additional authors if configured and folder
			mode is 'author,series,book'

			returns
				None
		"""

		if not self.construct.additional_authors:
			return
		
		if self.override_author_folder_dst_name:
			return
			
		if not self.construct.foldermode == 'author,series,book':
			return

		authorels = self.metadata.doc.getElementsByTagName('dc:creator')
		if not authorels:
			return
		if len(authorels) < 2:
			return

		for authorel in authorels[1:]:
			author = authorel.firstChild.data
			if not author:
				continue
			addBook = Book(
				self.construct,
				self.author_folder_src_path,
				self.book_folder_src_path,
				author
			)
			addBook.do()
		
	def do_list(self) -> None:

		"""Outputs report as specified by the --list command line argument

			Updates
				report

			returns
				None
		"""

		if self.metadata.titleel:
			book = self.metadata.titleel.firstChild.data
		else:
			book = ''
		line = list_format.format(
			authors=self.metadata.authors,
			subject=self.matched_subject,
			section=self.construct.section_name,
			book=book,
			bfolder=self.book_folder_src_path.name,
			afolder=self.author_folder_src_path.name,
			series=self.metadata.series,
			index=self.metadata.formatted_series_index
		)

		store = str(self.construct.calibre_store)
		if store not in report:
			report[store] = []

		if line in report[store]:
			if CMDARGS.invert and not self.construct.prescan:
				report[store].remove(line)
			return
		elif CMDARGS.invert and not self.construct.prescan:
			return
		report[store].append(line)

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
			if (
				self.construct.selection_mode in ['author', 'all']
				and not self.construct.prescan
			):
				logging.warning(_('No book file of configured type was found in "%s"'), self.book_folder_src_path)
			return

		if CMDARGS.debug:
			print(_('Book attributes:  {vars}').format(vars=vars(self)), flush=True)
			if self.metadata.doc:
				print(_('Book metadata:    {vars}').format(vars=vars(self.metadata)), flush=True)

		if not self.metadata_file_src_path:
			logging.warning(_('No metadata was found in "%s"'), self.book_folder_src_path)

		if self.construct.selection_mode == 'subject':
			if not self.metadata.doc:
				return
			if not self.check_subjects():
				return

		if CMDARGS.list_spec:
			self.do_list()
			return

		# recursing first simplifies some things
		self.do_additional_authors()

		if self.override_author_folder_dst_name:
			print(
				'{src_path} (+ {override_author})'.format(
					src_path=self.book_folder_src_path,
					override_author=self.override_author_folder_dst_name
				), flush=True
			)
		else:
			print(self.book_folder_src_path, flush=True)

		if not self.cover_file_src_path:
			logging.warning(_('No cover image was found in "%s"'), self.book_folder_src_path)

		if self.metadata.doc and not self.metadata.titleel:
			logging.warning(
				_('Missing normally required <dc:title> element in metadata for "%s"'),
				self.book_folder_src_path
			)

		if self.metadata.doc and not self.metadata.authors:
			logging.warning(
				_('Missing normally required <dc:creator> (i.e. author) element in metadata for "%s"'),
				self.book_folder_src_path
			)

		if CMDARGS.dryrun:
			print('> {path}'.format(path=self.book_file_dst_path), flush=True)
			print('> {path}'.format(path=self.metadata_file_dst_path), flush=True)
			print('> {path}'.format(path=self.cover_file_dst_path), flush=True)
			return

		# Create the destination book folder
		try:
			self.book_folder_dst_path.mkdir(parents=True, exist_ok=True)
		except OSError as excep:
			logging.warning(
				_('Could not create book\'s destination folder (or a parent folder thereof) "%s": %s'),
				self.book_folder_dst_path, excep
			)
			return

		# Output the book files
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


class CustomHelpFormatter(argparse.HelpFormatter):
	"""Argparse help formatter that supports newlines"""
	
	def _split_lines(self, text, width):
		lines = text.split('\n')
		formatted_lines = []
		for line in lines:
			if line:
				formatted_lines.extend(textwrap.wrap(line, width))
			else:
				formatted_lines.append('')
		return formatted_lines


# ------------------
#   Functions
# ------------------


def custom_textwrap(text: str, width: int, prefix: str, suffix: str) -> str:
	
	"""Similar to textwrap.wrap but adds prefix and suffice to each line.
		Lines are split on newlines if present.
	"""
	
	lines = []
	worklines = text.split('\n')
	for line in worklines:
		if line:
			lines.extend(textwrap.wrap(line, width))
		else:
			lines.append('')
	return prefix + (suffix + prefix).join(lines) + suffix
	
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


def do_constructs(config: configparser.ConfigParser) -> None:

	"""Iterates over configured [Construct] sections. Prints --list report.

		config:
			initialized config parser object

		Exceptions:
			ValueError and KeyError
			See Construct()

	"""

	logging.info('Scanning ...')

	# for each configured Construct
	for section in config:
		if section[0:9] == 'Construct':
			construct = Construct(config[section])
			construct.do()

	if CMDARGS.list_spec:
		for store in report:
			if CMDARGS.invert:
				selection_str = _('excluded:')
			else:
				selection_str = _('selected:')
			print('{store}, {selection_str}\n{list_format}'.format(
				store=store,
				selection_str=selection_str,
				list_format=list_format
			), flush=True)
			report[store].sort()
			for line in report[store]:
				print(line, flush=True)


def do_prescan(config: configparser.ConfigParser) -> None:

	"""Pre-loads REPORT with all possible values precedent to an --invert(ed) report.

		config:
			initialized config parser object

		returns:
			None

		Exceptions:
			ValueError and KeyError
			See Construct()

	"""

	logging.info('Prescanning ...')

	# for each configured Construct
	for section in config:
		if section[0:9] == 'Construct':
			construct = Construct(config[section])
			save_selection_mode = construct.selection_mode
			construct.selection_mode = 'all'
			construct.prescan = True
			construct.do()
			construct.prescan = False
			construct.selection_mode = save_selection_mode


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

	global CMDARGS, list_format

	logging.basicConfig(format='%(levelname)s:%(filename)s:%(lineno)s: %(message)s', level=logging.DEBUG)

	# Parse command line arguments
	cmdparser = argparse.ArgumentParser(
		description=custom_textwrap(
			_(
				'A utility to construct a Jellyfin ebook library from a Calibre library. '
			     'Configuration file "{path}" is required (see below).'
			).format(path=CONFIG_FILE_PATH),
			70, '', '\n'
		),
		formatter_class = argparse.RawTextHelpFormatter,
#		formatter_class = CustomHelpFormatter,
		epilog=(
			'─────────────────────\n'
			+_('THE CONFIGURATION FILE') + '\n'
			'\n'
			+_('Required configuration file name and location:') + '\n'
			'\t' + '{CONFIG_FILE}'.format(CONFIG_FILE=CONFIG_FILE_PATH) + '\n'
			'\n'
			+_('Configuration Sections:') + '\n'
			'\t' + _('The configuration file must consist of [Construct] sections that contain parameters.') + '\n'
			'\t' + _('There may be multiple [Construct] sections.') + '\n'
			'\t' + _('[Construct] section names must be uniquely named or numbered.') + '\n'
			'\t' + _('[Construct] section names must begin with exactly the nine letters "Construct"') + '\n'
			'\t' + _('[Construct] section identifiers should not be indented.') + '\n'
			'\n'
			'\t' + _('Examples:') + '\n'
			'\t[Construct]\n'
			'\t[Construct2]\n'
			'\t[Construct3]\n'
			'\t[ConstructFiction]\n'
			'\n'
			+_('Configuration Parameters:') + '\n'
			'\t' + _('Parameters must be indented within a preceding section.') + '\n'
			+ custom_textwrap(
				_('Parameters consist of the parameter label followed by " = " followed by the parameter value.'),
				50, '\t', '\n'
			) +
			'\n'
			+ custom_textwrap(
				_('Multiline parameters begin on the line following the "parameter =" statement and must be indented.'),
				50, '\t', '\n'
			) +
			'\n'
			+ custom_textwrap(
				_('See below for configuration examples.'),
				50, '\t', '\n'
			) +
			'\n'
			'\t──────────────────────────────────\n'
			'\t'+_('Parameter:')+	'\t\t'		'calibreStore\n'
			'\n'
			'\t\t\t\t\t'					+_('The full path to the source Calibre library.') + '\n'
			'\n'
			'\t\t\t\t\t'					+_('Required.') + '\n'
			'\t──────────────────────────────────\n'
			'\t'+_('Parameter:')+	'\t\t'		'jellyfinStore\n'
			'\n'
			'\t\t\t\t\t'					+_('The full path to the destination Jellyfin library.') + '\n'
			+ custom_textwrap(
				_(
					'You may also point this to a subfolder within the Jellyfin library, for instance '
					'in the case where you are creating category subfolders.'
				),
				50, '\t\t\t\t\t', '\n'
			) +
			'\n'
			'\t\t\t\t\t'					+_('Required.') + '\n'
			'\t──────────────────────────────────\n'
			'\t'+_('Parameter:')+	'\t\t'		'foldermode\n'
			'\n'
			+custom_textwrap(_('Control file and directory structure of the output Jellyfin library.'),50,'\t\t\t\t\t','\n')+
			'\n'
			'\t\t\t\t\t'					+_('Must be one of:') + '\n'
											+custom_textwrap(
												'author,series,book\n'
												'series,book\n'
												'book\n',
												50, '\t\t\t\t\t\t', '\n'
											)+
			'\t──────────────────────────────────\n'
			'\t'+_('Parameter:')+	'\t\t'		'mangleMetaTitle\n'
			'\n'
			'\t\t\t\t\t'					+_('Controls mangling of the metadata title element.') + '\n'
			'\n'
			'\t\t\t\t\t'					+_('Must be one of:') + '\n'
			'\t\t\t\t\t\t'						'0 : ' + _('Disable title mangling') + '\n'
			'\t\t\t\t\t\t'						'1 : ' + _('Prefix title with formatted series index (e.g. "007")') + '\n'
			'\t\t\t\t\t\t'						'2 : ' + _('Prefix title with unformatted series index (e.g. "7")') + '\n'
			'\n'
			'\t\t\t\t\t'					+_('If not specified, defaults to:') + '\n'
			'\t\t\t\t\t\t'						'1 : ' + custom_textwrap(
													_('This is for backward compatibility.  Mode 2 will likely be preferred.'),
													50, '\t\t\t\t\t\t', '\n'
												)[6:] +
			'\n'
			'\t\t\t\t\t'					+_('Has no effect unless foldermode is one of:') + '\n'
											+custom_textwrap(
												'author,series,book\n'
												'series,book\n'
												'book\n',
												50, '\t\t\t\t\t\t', '\n'
											)+
			'\t──────────────────────────────────\n'
			'\t'+_('Parameter:')+	'\t\t'		'mangleMetaTitleSort\n'
			'\n'
			'\t\t\t\t\t'					+_('Controls mangling of the metadata title sort value.') + '\n'
			'\n'
			'\t\t\t\t\t'					+_('Must be one of:') + '\n'
			'\t\t\t\t\t\t'						'0 : ' + _('Disable title sort mangling') + '\n'
			'\t\t\t\t\t\t'						'1 : ' + _('Enable title sort mangling') + '\n'
			'\n'
			'\t\t\t\t\t'					+_('If not specified, defaults to:') + '\n'
			'\t\t\t\t\t\t'						'0 : ' + custom_textwrap(
													_('This is for backward compatibility.  Mode 1 will likely be preferred.'),
													50, '\t\t\t\t\t\t', '\n'
												)[6:] +
			'\n'
			'\t\t\t\t\t'					+_('Has no effect unless foldermode is one of:') + '\n'
			'\t\t\t\t\t\t'						'author,series,book''\n'
			'\t\t\t\t\t\t'						'series,book''\n'
			'\t──────────────────────────────────\n'
			'\t'+_('Parameter:')+	'\t\t'		'additionalAuthors\n'
			'\n'								
			+custom_textwrap(
				_(
					'Controls whether books are output under '
					'each of multiple authors, or only '
					'under the "primary" author.'
				),
				50, '\t\t\t\t\t', '\n'
			) +
			'\n'
			'\t\t\t\t\t'					+_('Must be one of:') + '\n'
			'\t\t\t\t\t\t'						'0 : ' + _('Disable output for additional authors.') + '\n'
			'\t\t\t\t\t\t'						'1 : ' + _('Enable output for additional authors.') + '\n'
			'\n'
			'\t\t\t\t\t'					+_('Default:') + '\n'
			'\t\t\t\t\t\t'						'0''\n'
			'\n'
			'\t\t\t\t\t'					+_('Has no effect unless foldermode is:') + '\n'
			'\t\t\t\t\t\t'						'author,series,book''\n'
			'\t──────────────────────────────────\n'
			'\t'+_('Parameter:')+	'\t\t'		'bookfiletypes\n'
			'\n'
			+ custom_textwrap(
				_(
					'Multiline list of book file extensions, in order '
				    'of preference first to last, and excluding "." separator.'
				),
				50, '\t\t\t\t\t', '\n'
			) +
			'\n'
			+ custom_textwrap(
				_(
					'Calibre2jellyfin will only output a single file '
				    'for the text of each book.  Outputting books in '
				    'multiple formats results in a suboptimal '
				    'Jellyfin presentation.'
				),
				50, '\t\t\t\t\t', '\n'
			) +
			'\n'
			+ custom_textwrap(
				_(
					'Must be one or more of the book file extension types '
				    'that Jellyfin recognizes such as: azw, azw3,'
				    'epub, mobi, pdf, cbz, and cbr.'
				),
				50, '\t\t\t\t\t', '\n'
			) +
			'\t──────────────────────────────────\n'
			'\t'+_('Parameter:')+	'\t\t'		'selectionMode\n'
			'\n'
			'\t\t\t\t\t'					+_('Book selection mode.') + '\n'
			'\n'
			'\t\t\t\t\t'					+_('Must be one of:') + '\n'
			'\t\t\t\t\t\t'						'author  : ' + _('select by author folder') + '\n'
			'\t\t\t\t\t\t'						'subject : ' + _('select by metadata subject (aka tag)') + '\n'
			'\t\t\t\t\t\t'						'all     : ' + _('select all books in source library') + '\n'
			'\n'
			'\t\t\t\t\t'					+_('If not present defaults to:') + '\n'
			'\t\t\t\t\t\t'						'author''\n'
			'\n'
			+ custom_textwrap(
				_(
					'Note that in the case of selection by subject, '
				    'if the Calibre metadata file cannot be found ' 
				    'then the book cannot be selected.'
				),
				50, '\t\t\t\t\t', '\n'
			) +
			'\t──────────────────────────────────\n'
			'\t'+_('Parameter:')+	'\t\t'		'authorFolders\n'
			'\n'
			+ custom_textwrap(
				_(
					'Multiline list of author folders within the '
				    'source Calibre library.  All books in these '
				    'author folders will be selected and output.'
				),
				50, '\t\t\t\t\t', '\n'
			) +
			'\n'
			+ custom_textwrap(
				_(
					'Required when selectionMode is author. '
				    'Ignored otherwise.'
				),
				50, '\t\t\t\t\t', '\n'
			) +
			'\t──────────────────────────────────\n'
			'\t'+_('Parameter:')+	'\t\t'		'subjects\n'
			'\n'
			+ custom_textwrap(
				_(
					'Multiline list of subjects (aka tags in '
				    'Calibre).'
				),
				50, '\t\t\t\t\t', '\n'
			) +
			'\n'
			+ custom_textwrap(
				_('Required when selectionMode is subject.'),
				50, '\t\t\t\t\t', '\n'
			) +
			'\n'
			+ custom_textwrap(
				_(
					'Individual lines implement OR logic. '
				    'Comma delimited lists implement AND logic. '
				    'The example below would select any book '
				    'having both "science fiction" AND "alien contact" '
				    'tags, OR a "thriller" tag.'
				),
				50, '\t\t\t\t\t', '\n'
			) +
			'\n'
			'\t\t\t\t\t'	+_('Example:') + '\n'
			'\t\t\t\t\t'	'subjects =\n'
			'\t\t\t\t\t\t'		+_('science fiction, alien contact') + '\n'
			'\t\t\t\t\t\t'		+_('thriller') + '\n'
			'\n'
			'─────────────────────\n'
			+_('CONFIGURATION EXAMPLES') + '\n'
			'\n'
			'\t' + _('Sample configuration for fiction books:') + '\n'
			'\n'
			'\t'	'[Construct1]'										'\n'
			'\n'
			'\t\t'		'calibreStore = /path/to/Calibre/library'		'\n'
			'\t\t'		'jellyfinStore = /path/to/Jellyfin/library'		'\n'
			'\t\t'		'foldermode = author,series,book'				'\n'
			'\t\t'		'mangleMetaTitle = 2'							'\n'
			'\t\t'		'mangleMetaTitleSort = 1'						'\n'
			'\t\t'		'additionalAuthors = 0'							'\n'
			'\t\t'		'bookfiletypes ='								'\n'
			'\t\t'		'    epub'										'\n'
			'\t\t'		'    pdf'										'\n'
			'\t\t'		'    mobi'										'\n'
			'\t\t'		'selectionMode = author'						'\n'
			'\t\t'		'authorFolders ='								'\n'
			'\t\t'		'    Andre Norton'								'\n'
			'\t\t'		'    Dean Koontz'								'\n'
			'\t\t'		'    ...'										'\n'
			'\t\t'		'subjects ='									'\n'
			'\t\t'		'    science fiction, alien contact'			'\n'
			'\t\t'		'    thriller'									'\n'
			'\n'
			'\t' + _('Sample configuration for comic books:') + '\n'
			'\n'
			'\t'	'[Construct2]'										'\n'
			'\t\t'	'calibreStore = /path/to/Calibre/library'			'\n'
			'\t\t'	'jellyfinStore = /path/to/Jellyfin/library'			'\n'
			'\t\t'	'foldermode = series,book'							'\n'
			'\t\t'	'mangleMetaTitle = 2'								'\n'
			'\t\t'	'mangleMetaTitleSort = 1'							'\n'
			'\t\t'	'bookfiletypes ='									'\n'
			'\t\t'	'    cbz'											'\n'
			'\t\t'	'    cbr'											'\n'
			'\t\t'	'selectionMode = author'							'\n'
			'\t\t'	'authorFolders ='									'\n'
			'\t\t'	'    Stan Lee'										'\n'
			'\t\t'	'    Jim Davis'										'\n'
			'\t\t'	'    ...'											'\n'
			'\n'
			'\n'
			'\t' + _('Sample configuration for nonfiction books:') + '\n'
			'\n'
			'\t'	'[Construct3]'										'\n'
			'\n'
			'\t\t'		'calibreStore = /path/to/Calibre/library'		'\n'
			'\t\t'		'jellyfinStore = /path/to/Jellyfin/library'		'\n'
			'\t\t'		'foldermode = book'								'\n'
			'\t\t'		'bookfiletypes ='								'\n'
			'\t\t'		'    epub'										'\n'
			'\t\t'		'    pdf'										'\n'
			'\t\t'		'selectionMode = author'						'\n'
			'\t\t'		'authorFolders ='								'\n'
			'\t\t'		'    Donald Knuth'								'\n'
			'\t\t'		'    Linus Torvalds'							'\n'
			'\t\t'		'    ...'										'\n'
			'\n'
		)
	)
	cmdparser.add_argument(
		'--debug',
		dest='debug',
		action='store_true',
		help=_('Emit debug information.')
	)
	cmdparser.add_argument(
		'--dryrun',
		dest='dryrun',
		action='store_true',
		help=custom_textwrap(_('Displays normal console output but makes no changes to exported libraries.'),50,'','\n')
	)
	cmdparser.add_argument(
		'--invert',
		dest='invert',
		action='store_true',
		help=custom_textwrap(_('Inverts the sense of the --list argument, showing those items that will not be exported. ') +
		' '+ _('Only valid in combination with --list.'),50,'','\n')
	)
	cmdparser.add_argument(
		'--list',
		dest='list_spec',
		action='store',
		help=custom_textwrap(
			_('Suspends normal export behavior.') +
			' ' + _('Instead prints information from configuration sections and the file system that is useful for curation.') +
			' ' + _('LIST_SPEC is a comma-delimited list of columns to include in the report.') +
			' ' + _('The output is tab-separated.  Columns must be one or more of the following:')
		,50,'','\n') +
		'\n\tauthors   ' + _(': display list of authors') +
		'\n\tsection   ' + _(': display name of construct section') +
		'\n\tbook      ' + _(': display book title') +
		'\n\tbfolder   ' + _(': display book folder') +
		'\n\tafolder   ' + _(': display author folder') +
		'\n\tsubject   ' + _(': display matched subject') +
		'\n\tseries    ' + _(': display name of series') +
		'\n\tindex     ' + _(': display series index') +
		'\n\n' + custom_textwrap(_('The report output is sorted so there will be a pause while all configured sections are processed.'),50,'','\n') +
		'\n' + _('Example:'' --list afolder,book,series')
	)
	cmdparser.add_argument(
		'--update-all-metadata',
		dest='updateAllMetadata',
		action='store_true',
		help=custom_textwrap(_(
			'Useful to force a one-time update of all metadata files, '
			'for instance when configurable metadata mangling options have changed. '
			'Normally metadata files are only updated when missing or out-of-date.'
		),50,'','\n')
	)
	cmdparser.add_argument(
		'-v', '--version',
		dest='version',
		action='store_true',
		help=_('Display version string.')
	)
	CMDARGS = cmdparser.parse_args(clargs)

	if CMDARGS.version:
		print(_('version {version}').format(version=VERSION), flush=True)
		return

	if CMDARGS.dryrun and (CMDARGS.list_spec or CMDARGS.updateAllMetadata):
		logging.critical(_('Incompatible arguments'))
		sys.exit(-1)

	if CMDARGS.invert and not CMDARGS.list_spec:
		logging.critical(_('Argument --invert may only be used in conjunction with --list.'))
		sys.exit(-1)

	if CMDARGS.list_spec:
		cols = CMDARGS.list_spec.split(',')
		for report_col in cols:
			if report_col not in ['section', 'authors', 'book', 'subject', 'bfolder', 'afolder', 'series', 'index']:
				logging.critical(
					_(
						'--list columns must be one or more of "section", "authors", "book", "bfolder", "afolder", '
						'"subject", "series", "index"'
					)
				)
				sys.exit(-1)
		list_format = '\t'.join(['{{{col}}}'.format(col=col) for col in cols])

	# read configuration
	try:
		with open(CONFIG_FILE_PATH, 'r', encoding='utf8') as configfile:
			config = configparser.ConfigParser()
			config.read_file(configfile)
	except OSError as configexcep:
		logging.critical(_('Could not read configuration "%s": %s'), CONFIG_FILE_PATH, configexcep)
		sys.exit(-1)
	except configparser.Error as configexcep:
		logging.critical(_('Invalid configuration "%s": %s'), CONFIG_FILE_PATH, configexcep)
		sys.exit(-1)

	logging.info(_('Using configuration "%s"'), CONFIG_FILE_PATH)

	# Default mangling behavior to that of original script
	config['DEFAULT']['mangleMetaTitle'] = '1'
	config['DEFAULT']['mangleMetaTitleSort'] = '0'
	config['DEFAULT']['selectionMode'] = 'author'
	config['DEFAULT']['subjects'] = ''
	config['DEFAULT']['additionalAuthors'] = '0'

	try:
		if CMDARGS.invert:
			do_prescan(config)
		do_constructs(config)
	except ValueError as excep:
		logging.critical(
			_('Inappropriate parameter value in configuration file "%s": %s'),
			CONFIG_FILE_PATH, excep
		)
		sys.exit(-1)
	except KeyError as excep:
		logging.critical(
			_('A required parameter (%s) is missing from configuration file "%s".'),
			excep, CONFIG_FILE_PATH
		)
		sys.exit(-1)


if __name__ == '__main__':
	main()














