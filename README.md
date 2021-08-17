# fatify
fuse mount a directory and replace illegal characters for FAT filesystem

My use case:

I have files on a Linux filesystem (e.g. music) and want to copy it to
a FAT filesystem (e.g. USB stick for car, external SD card for phone)
but I use characters in the file names that are illegal on FAT (like ? : *)

With this simple filesystem I can mount my music and then rsync it on my
FAT formatted stick. All illegal characters are replaced with underscores.

In terminal:

fatify.py -f -o root=Music fatify

rsync -avP fatify/ ...

