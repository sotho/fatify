#!/usr/bin/python3

import os
import sys

# pull in some spaghetti to make this stuff work without fuse-py being installed
try:
    import _find_fuse_parts
except ImportError:
    pass
import fuse


if not hasattr(fuse, "__version__"):
    raise RuntimeError("your fuse-py doesn't know of fuse.__version__, probably it's too old.")

fuse.fuse_python_api = (0, 2)


illegal_chars = "?*:"

# replace every illegal character with an underscore
translate_table = str.maketrans(illegal_chars, "_" * len(illegal_chars))

# keep a mapping of files
forward_mapping = {}  # original path -> translated
backward_mapping = {}  # translated -> original path


def transform_path(path):
    trans = path.translate(translate_table)
    if trans == path:
        # no replacement was done, no need to keep a mapping
        return path

    if path in forward_mapping:
        # mapping already known
        return forward_mapping[path]

    # new mapping, but the translated filename might already be in use by
    # another file, i.e. we have a collision
    if trans in backward_mapping:
        assert (
            backward_mapping[trans] != path
        ), "Mapping table inconsistent. backward_mapping[%s] = %s, but path = %s" % (
            trans,
            backward_mapping[trans],
            path,
        )

        root, ext = os.path.splitext(trans)
        for i in range(1, 10):
            candidate = root + str(i) + ext
            if candidate not in backward_mapping:
                # found a free name
                forward_mapping[path] = candidate
                backward_mapping[candidate] = path
                print("New mapping (collision %d): '%s' -> '%s'" % (i, path, candidate))
                return candidate
            else:
                assert (
                    backward_mapping[candidate] != path
                ), "Mapping table inconsistent. backward_mapping[%s] = %s, but path = %s" % (
                    trans,
                    backward_mapping[trans],
                    path,
                )

        print("Cannot resolve collision for '%s'" % path)
        assert False
    else:
        # no collision
        forward_mapping[path] = trans
        backward_mapping[trans] = path
        print("New mapping: '%s' -> '%s'" % (path, trans))
        return trans

    assert False


def back_transform_path(path):
    if path == '/':
        return path

    dirname = back_transform_path(os.path.dirname(path))
    basename = os.path.basename(backward_mapping.get(path, path))

    return os.path.join(dirname, basename)


def get_root_path(partial):
    global root
    partial = back_transform_path(partial)
    if partial.startswith("/"):
        partial = partial[1:]
    return os.path.join(root, partial)


def flag2mode(flags):
    md = {os.O_RDONLY: "rb", os.O_WRONLY: "wb", os.O_RDWR: "wb+"}
    m = md[flags & (os.O_RDONLY | os.O_WRONLY | os.O_RDWR)]

    if flags | os.O_APPEND:
        m = m.replace("w", "a", 1)

    return m


class FatFS(fuse.Fuse):
    def __init__(self, *args, **kw):
        fuse.Fuse.__init__(self, *args, **kw)

    def getattr(self, path):
        #print("getattr: %s -> %s" % (path, get_root_path(path)))
        return os.lstat(get_root_path(path))

    def readlink(self, path):
        return os.readlink(get_root_path(path))

    def readdir(self, path, offset):
        # sort to make mapping in case of collision more stable
        #print("readdir %s -> %s" % (path, get_root_path(path)))
        for e in sorted(os.listdir(get_root_path(path))):
            trans = os.path.basename(transform_path(os.path.join(path, e)))
            #print("readdir element: %s" % trans)
            yield fuse.Direntry(trans)

    # def unlink(self, path):
    #     os.unlink(get_root_path(path))

    # def rmdir(self, path):
    #     os.rmdir(get_root_path(path))

    # def symlink(self, path, path1):
    #     os.symlink(path, get_root_path(path1))

    # def rename(self, path, path1):
    #     os.rename(get_root_path(path), get_root_path(path1))

    # def link(self, path, path1):
    #     os.link(get_root_path(path), get_root_path(path1))

    # def chmod(self, path, mode):
    #     os.chmod(get_root_path(path), mode)

    # def chown(self, path, user, group):
    #     os.chown(get_root_path(path), user, group)

    # def truncate(self, path, len):
    #     f = open(get_root_path(path), "a")
    #     f.truncate(len)
    #     f.close()

    # def mknod(self, path, mode, dev):
    #     os.mknod(get_root_path(path), mode, dev)

    # def mkdir(self, path, mode):
    #     os.mkdir(get_root_path(path), mode)

    # def utime(self, path, times):
    #     os.utime(get_root_path(path), times)

    # def access(self, path, mode):
    #     if not os.access(get_root_path(path), mode):
    #         return -EACCES

    class FatFile(object):
        def __init__(self, path, flags, *mode):
            self.file = os.fdopen(os.open(get_root_path(path), flags, *mode), flag2mode(flags))
            self.fd = self.file.fileno()

        def read(self, length, offset):
            return os.pread(self.fd, length, offset)

        # def write(self, buf, offset):
        #     return os.pwrite(self.fd, buf, offset)

        def release(self, flags):
            self.file.close()

        def _fflush(self):
            if "w" in self.file.mode or "a" in self.file.mode:
                self.file.flush()

        def fsync(self, isfsyncfile):
            self._fflush()
            if isfsyncfile and hasattr(os, "fdatasync"):
                os.fdatasync(self.fd)
            else:
                os.fsync(self.fd)

        def flush(self):
            self._fflush()
            # cf. xmp_flush() in fusexmp_fh.c
            os.close(os.dup(self.fd))

        def fgetattr(self):
            return os.fstat(self.fd)

        # def ftruncate(self, len):
        #     self.file.truncate(len)

    def main(self, *a, **kw):
        self.file_class = self.FatFile
        return fuse.Fuse.main(self, *a, **kw)


def main():
    usage = (
        """
FATify file names, i.e. replace all characters not allowed in FAT file names to underscore

"""
        + fuse.Fuse.fusage
    )
    server = FatFS(version="%prog " + fuse.__version__, usage=usage, dash_s_do="setsingle")

    server.parser.add_option(
        mountopt="root",
        metavar="PATH",
        default="/",
        help="mirror filesystem from under PATH and transform filenames to only use FAT-allowed characters [default: %default]",
    )
    server.parse(values=server, errex=1)
    global root
    root = server.root
    server.main()


if __name__ == "__main__":
    main()
