# -*- coding: utf-8 -*-

#Canto - ncurses RSS reader
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from canto.canto_interface import CantoInterface
from canto.canto_backend import CantoBackend

import unittest
import signal
import shutil
import time
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

        fpath = os.getenv("PWD") + "/tests/perms/bad-files"
        b.args(["-D", fpath])
        self.assertEqual(b.ensure_paths(), None)

        for f in [ "feeds", "conf", "daemon-log", "pid" ]:
            os.chmod(fpath + "/" + f, 0222)
            self.assertEqual(b.ensure_paths(), -1)
            os.chmod(fpath + "/" + f, 0444)
            self.assertEqual(b.ensure_paths(), -1)
            os.chmod(fpath + "/" + f, 0666)
            self.assertEqual(b.ensure_paths(), None)

    def test_pid_lock(self):
        b = CantoBackend()
        c = CantoBackend()

        b.args(["-D", os.getenv("PWD") + "/tests/perms/good"])
        b.ensure_paths()
        self.assertEqual(b.pid_lock(), None)

        c.args(["-D", os.getenv("PWD") + "/tests/perms/good"])
        c.ensure_paths()
        self.assertEqual(c.pid_lock(), -1)

        b.pid_unlock()
        self.assertEqual(c.pid_lock(), None)

    def protocol(self, conf_dir, commands, responses):
        pid = os.fork()
        if not pid:
            b = CantoBackend()
            try:
                b.start(["-D", conf_dir])
            except SystemExit:
                os._exit(0)
        else:
            print "Forked: %d" % pid

        time.sleep(2)
        socket_path = conf_dir + "/.canto_socket"
        i = CantoInterface(False, socket_path,\
                commands=commands, responses=responses)
        i.run()

    def test_list_feeds(self):
        conf_dir = os.getenv("PWD") + "/tests/good/listfeeds"
        commands = ["LISTFEEDS ", "DIE "]
        responses = []

        self.protocol(conf_dir, commands, responses)
        print responses
        self.assertTrue(responses[0][0] == "LISTFEEDS")
        self.assertTrue(eval(responses[0][1]) ==
                [ ('Canto', 'http://codezen.org/static/canto.xml'),
                  ('Reddit Science', 'http://science.reddit.com/.rss') ])
