#!/usr/bin/python

import sys
import os
import glob
from subprocess import call

THUMBS_DIR = "thumbs"
THUMBS_PREFIX = "thumb-"
extList = ["jpg", "JPG", "png", "PNG", "gif", "GIF", "webm", "WEBM"]

if not os.path.exists(THUMBS_DIR):
    os.mkdir("thumbs")

fileList = []
for ext in extList:
    fileList.extend(glob.glob("*." + ext))

for f in fileList:
    if f.startswith(THUMBS_PREFIX):
        continue

    dest = os.path.join(THUMBS_DIR, THUMBS_PREFIX + f)
    dest = os.path.splitext(dest)[0] + ".webp"

    if not os.path.exists(dest):
        sys.stdout.write("%s --> %s\n" % (f, dest))
        call(["convert", f, "-auto-orient", "-resize", "450x", "-strip", "-quality", "75", dest])
