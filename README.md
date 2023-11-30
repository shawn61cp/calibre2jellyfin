# calibre2jellyfin
Python script to construct a Jellyfin ebook library from a Calibre library.

## Linux 

#### Overview
* Created folder structure (foldermode in .cfg) is one of:
  * .../author/series/book/...
  * .../book/...
* Destination book folder contains
  * symlink to book file in Calibre library
  * symlink to cover image in Calibre library
  * copy, possibly modified, of Calibre's metadata file
* Books are selected for inclusion by listing author folders in the .cfg file
* Series handling
  * When foldermode is author/series/book, the script will extract series and series index from Calibre's metadata file.  If found, the target book folder name will be prepended with the series index.  So will the \<dc:title\> element in the metadata file.  If series info is expected but not found, the structure collapses to .../author/book/....
* Multiple output libraries may be configured 

#### Example author/series/book structure 
<table>
  <thead>
    <tr><th>Calibre store</th><th>Created Jellyfin store</th></tr>
  </thead>
 <tbody>
  <tr>
   <td><pre>
└── Author/
    └── Book A/
    │   ├── cover.jpg
    │   ├── metadata.opf
    │   └── Book A.epub
    ├── Book B/
    │   ├── cover.jpg
    │   ├── metadata.opf
    │   └── Book B.epub
   </pre>
   </td>
   <td><pre>
└── Author/
    └── Lorem ipsum dolor sit amet Series/
        ├── 001 - Book A/
        │   ├── cover.jpg      <- symlink
        │   ├── metadata.opf   <- modified copy
        │   └── Book A.epub    <- symlink
        ├── 002 - Book B/
        │   ├── cover.jpg      <- symlink
        │   ├── metadata.opf   <- modified copy
        │   └── Book B.epub    <- symlink
   </pre>    
   </td>
  </tr>
 </tbody>
</table>
Jellyfin will display a drillable folder structure similarly to the way it does for movies, shows, and music.  Jellyfin will extract and display the mangled book title that is prepended with the series index as the book title.

#### Dependencies
* Python 3
  
#### Installation

<pre>
1. In your browser navigate to "https://github.com/shawn61cp/calibre2jellyfin"
2. Click the green "Code" button
3. In the resulting dropdown, just over halfway down, find and click on "Download ZIP".
4. Save the zip file somewhere convenient and extract it.  We will call this EXTRACT_FOLDER.
5. Change to directory EXTRACT_FOLDER/calibre2jellyfin-main
6. In a terminal:
7.      <code>$ chmod 755 calibre2jellyfin.py</code>
8. Choose a location to install the script.  You may want to add this location to your path.  We will call this INSTALL_FOLDER.
9. In a terminal:
10.     <code>$ cp calibre2jellyfin.py INSTALL_FOLDER/</code>
11.     <code>$ cp calibre2jellyfin.cfg ~/.config/</code>
</pre>

#### Usage

* Edit the ~/.config/calibre2jellyfin.cfg file before first use.
    * Following the comments in the .cfg, set up your source and destination storage locations (libraries), your folder mode, and your list of authors.
* If you added the calibre2jellyfin.py script to a location on your path, in a terminal:
    * <code>$ calibre2jellyfin.py</code>
* If not, include the full path to the script:
    * <code>$ INSTALL_FOLDER/calibre2jellyfin.py</code>

## Real Life

The installation and usage instructions above work fine but there may be other situations encountered or other conveniences desired.

#### Permissions on created Jellyfin library

The usage/installation steps described above yield a Jellyfin store that is owned by whatever user ran the script.  Jellyfin can serve up this library because Calibre generally makes its folders and files world readable and so does the script.  If you make the library owned by Jellyfin (the <code>jellyfin</code> Linux user/service account), you will be able to delete books through the Jellyfin interface assuming you have administrative permission on the library within the Jellyfin app itself.  

If your situation is like mine, cleaning up my Calibre library, ensuring the right metadata and covers got downloaded etc., is an ongoing task.  If you discover an issue while browsing your books within Jellyfin, you can delete the Jellyfin book (within Jellyfin), go back to your Calibre library, clean things up, and then re-run the script. Et voilà! Depending on the issue, you might not even have to delete the book from Jellyfin; Rerunning the script might be sufficient. However, deleting the book, or even the author folder if there were many changes, from Jellyfin does guarantee a clean re-creation.

Note that because the book and cover files are soft linked, and the folders and metadata file are copies, when you delete a book or author through the Jellyfin interface, you are only affecting the Jellyfin library and not your precious Calibre library.

For myself, I arrange to run the script under the <code>jellyfin</code> account.  This will result in the files and folders output by the script being owned by <code>jellyfin</code>.  The default home directory for the <code>jellyfin</code> user is <code>/var/lib/jellyfin</code>.  I create the path and install the script to <code>/var/lib/jellyfin/.local/bin/calibre2jellyfin.py</code>.  Similarly I install the configuration file to <code>/var/lib/jellyfin/.config/calibre2jellyfin.cfg</code>.

###### Set up the script under the jellyfin account

The steps to accomplish the above follow.  I refer again to the EXTRACT_FOLDER as described in the installation section above. Finally, <code>jellyfin</code> by default does not permit logins so these steps will be performed as <code>root</code>.

Change to <code>root</code>:
<code>
 $ sudo su - 
</code>

Create the paths for the script and its configuration
<code>
 \# mkdir -p /var/lib/jellyfin/.local/bin
 \# mkdir -p /var/lib/jellyfin/.config
</code>

Copy the script and configuration.  Note: If you already have a .cfg set up, copy that instead of the sample .cfg from the EXTRACT_FOLDER.
<code>
 \# cp EXTRACT_FOLDER/calibre2jellyfin-main/calibre2jellyfin.py /var/lib/jellyfin/.local/bin/
 \# cp EXTRACT_FOLDER/calibre2jellyfin-main/calibre2jellyfin.cfg /var/lib/jellyfin/.config/
</code>

Change ownership of the files and paths created above to <code>jellyfin</code>.
<code>
\# chown -R jellyfin:jellyfin /var/lib/jellyfin/.local
 \# chown -R jellyfin:jellyfin /var/lib/jellyfin/.config 
</code>

If you did not do so during the installation steps, make the script executable.

<code>\# chmod 755 /var/lib/jellyfin/.local/bin/calibre2jellyfin.py</code>

Now, if you did not already have a .cfg set up, continue as <code>root</code> and edit the configuration file <code>/var/lib/jellyfin/.config/calibre2jellyfin.cfg</code> as described under Usage above.

Finally, exit from the root shell.

<code># exit</code>

###### Running the installed script

I find that when dealing with accounts that do not permit login that the <code>runuser</code> utility is convenient.  _Possibly this is habit. :)_  To run the script I execute the following from my own account.

<code>$ sudo runuser -u jellyfin -- /var/lib/jellyfin/.local/bin/calibre2jellyfin.py</code>

#### Scheduling the script to run automatically

You can use CRON to run the script regularly to keep your Jellyfin library updated.  The steps below assume the script has been set up under the <code>jellyfin</code> user as described above.  The cron job is set up under the root account but again uses <code>runuser</code> to execute it as <code>jellyfin</code>.

Change to the root account

<code>$ sudo su -</code>

Start the cron editor  

<code>\# crontab -e</code>

Add a line like this to the cron file.  The redirection causes any error messages to be included in the mailed log (if you have that enabled).  The example below runs the script every night at 11:00 PM.

<code>0 23 * * * runuser -u jellyfin -- /var/lib/jellyfin/.local/bin/calibre2jellyfin.py 2\>&1</code>

Save the file, exit the editor, and exit the root shell.

#### Calibre Author Folders

Typically the Calibre author folder is named exactly as the author appears in the Calibre interface.  Occasionally however it is not.  I have seen this when Calibre displays authors as "Jane Doe & John Q. Public" but the folder name is actually just "Jane Doe".  Also when the list of authors is very long, as happens in technical books, Calibre will limit the length of the folder name.

If you find that an expected author does not show up in the created Jellyfin library, double check that the author as listed in the .cfg file matches the actual folder name in the Calibre library.

Another thing I have encountered is when multiple versions of the author name exist, such as "Public, John Q." and "John Q. Public", and they are then consolidated, Calibre actually moves the books into the folder matching the consolidated name.  If the author name configured for calibre2jellyfin happened to match the author name that "went away", updates to that author's books may appear to die, or you might see two different versions of the same author in Jellyfin.  The solution is to just delete, in Jellyfin, one or both authors, ensure that the author configured in the .cfg file matches the Calibre author folder, then re-run the script to have them cleanly re-created.  Jellyfin will eventually detect the changes and update the display contents.  You can also right-click on an item within Jellyfin and request an immediate metadata refresh.  Even so sometimes it will take a few minutes  for Jellyfin to recognize the changes.

## Windows

The script does not yet support windows.  Some things that will differ are:

* Because of the complications surrounding symlinks, file will probably be copied instead of creating symlinks.
    * The above will then probably require some command line options or date comparison logic to control whether files are overwritten when the script is re-run.
* The configuration file will probably be expected to be found in the same folder where the script is installed.

