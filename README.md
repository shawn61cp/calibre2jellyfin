# calibre2jellyfin
Python script to construct a Jellyfin ebook library from a Calibre library.

## Linux 

* Created folder structure (foldermode in .cfg) is one of:
  * .../author/series/book/...
  * .../book/...
* Destination book folder contains
  * symlink to book file in Calibre library
  * symlink to cover image in Calibre library
  * copy, possibly modified, of Calibre's metadata file
* Books are selected for inclusion by listing author folders in the .cfg file
* Series handling
  * When foldermode is author/series/book, the script will extract series and series index from Calibre's metadata file.  If found, the target book folder name will be prepended with the series index.  The \<dc:title\> element in the metadata file.

##### Example author/series/book layout 
<table>
  <th>
    <tr><td>Calibre store</td><td>Jellyfin store</td></tr>
  </th>
</table>
