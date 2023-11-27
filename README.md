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

##### Example author/series/book structure 
<table>
  <thead>
    <tr><th>Calibre store</th><th>Jellyfin store</th></tr>
  </thead>
 <tbody>
  <tr>
   <td><pre>
Author/
   Book A/
      book A.ext
      cover.jpg
      metadata.opf
   Book B/
      book B.ext
      cover.jpg
      metadata.opf
   </pre>
   </td>
   <td><pre>
Author/
   Lorem ipsum dolor sit amet (i.e. the series) /
      001 - Book A/
         book A.ext
         cover.jpg
         metadata.opf   <- title modified "001 - Book A"
      002 - Book B/
         book B.ext
         cover.jpg
         metadata.opf   <- title modified "002 - Book B"
   </pre>    
   </td>
  </tr>
 </tbody>
</table>
