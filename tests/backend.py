# -*- coding: utf-8 -*-

#Canto - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto.canto_backend import CantoBackend

import unittest
import shutil
import os

class Tests(unittest.TestCase):

    def test_args(self):
        b = CantoBackend()

        # Test no arguments
        b.args([])
        self.assertEqual(b.conf_dir, os.getenv("HOME") + "/.canto-ng/")
        self.assertEqual(type(b.conf_dir), unicode)

        # Test -D initial directory setup
        b.args(["-D", "/some/path/somewhere"])
        self.assertEqual(b.conf_dir, "/some/path/somewhere")
        self.assertEqual(type(b.conf_dir), unicode)

    def test_perms(self):
        b = CantoBackend()

        b.args(["-D", os.getenv("PWD") + "/tests/perms/good"])
        self.assertEqual(b.ensure_paths(), None)
        
        b.args(["-D", os.getenv("PWD") + "/tests/perms/file"])
        self.assertEqual(b.ensure_paths(), -1)

        b.args(["-D", os.getenv("PWD") + "/tests/perms/bad-read"])
        self.assertEqual(b.ensure_paths(), -1)

        b.args(["-D", os.getenv("PWD") + "/tests/perms/bad-write"])
        self.assertEqual(b.ensure_paths(), -1)

        cpath = os.getenv("PWD") + "/tests/perms/create"

        if os.path.exists(cpath):
            shutil.rmtree(cpath)

        b.args(["-D", cpath])
        self.assertEqual(b.ensure_paths(), None)
        self.assertTrue(os.path.exists(cpath))
        shutil.rmtree(cpath)
        self.assertFalse(os.path.exists(cpath))
