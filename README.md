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
  * When foldermode is author/series/book, the script will extract series and series index from Calibre's metadata file.  If found, the target book folder name will be prepended with the series index.  The \<dc:title\> element in the metadata file.  If series info is expected but not found, the structure collapses to .../author/book/....
* Multiple output libraries may be configured 

#### Example author/series/book structure 
<table>
  <thead>
    <tr><th>Calibre store</th><th>Created Jellyfin store</th></tr>
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
   Lorem ipsum dolor sit amet Series /
      001 - Book A/
         book A.ext     <- symlink
         cover.jpg      <- symlink
         metadata.opf   <- title modified "001 - Book A"
      002 - Book B/
         book B.ext     <- symlink
         cover.jpg      <- symlink
         metadata.opf   <- title modified "002 - Book B"
   </pre>    
   </td>
  </tr>
 </tbody>
</table>
Jellyfin will display a drillable folder structure similarly to the way it does for movies, shows, and music.  Jellyfin will extract and display the mangled book title that is prepended with the series index as the book title.

#### Installation

<pre>
1. In your browser navigate to "https://github.com/shawn61cp/calibre2jellyfin"
2. Click the green "Code" button
3. In the resulting dropdown, just over halfway down, find and click on "Download ZIP".
4. Save the zip file somewhere convenient and extract it.  We will call this ***extract folder***.
5. Change to directory ***extract folder***/calibre2jellyfin-main
6. In a terminal:
7.      <code>$ chmod 755 calibre2jellyfin.py</code>
8. Choose a location to install the script.  You may want to add this location to your path.  We will call this ***install folder***.
9. In a terminal:
10.     <code>$ cp calibre2jellyfin.py ***install folder***/</code>
11.     <code>$ cp calibre2jellyfin.cfg ~/.config/</code>
</pre>

#### Usage

<pre>
* Edit the ~/.config/calibre2jellyfin.cfg file before first use.
    * Following the comments in the .cfg, set up your source and destination storage locations (libraries), your folder mode, and your list of authors.
* If you added the calibre2jellyfin.py script to a location on your path, in a terminal:
    * <code>$ calibre2jellyfin.py</code>
* If not, include the full path to the script:
    * <code>$ ***install folder***/calibre2jellyfin.py</code>
</pre>


