# -*- coding: utf-8 -*-
#Canto - RSS reader backend
#   Copyright (C) 2010 Jack Miller <jack@codezen.org>
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License version 2 as 
#   published by the Free Software Foundation.

from client import CantoClient
from encoding import encoder, decoder
from format import escsplit

import xml.parsers.expat
import feedparser
import traceback
import urllib2
import pprint
import time
import sys

def print_wrap(s):
    print encoder(s)

class CantoRemote(CantoClient):
    def __init__(self):
        if self.common_args() == -1:
            sys.exit(-1)

        try:
            if self.port < 0:
                self.start_daemon()
                CantoClient.__init__(self, self.socket_path)
            else:
                CantoClient.__init__(self, None,\
                        port = self.port, address = self.addr)
        except Exception, e:
            print_wrap("Error: %s" % e)
            print_wrap(self.socket_path)
            sys.exit(-1)

        self.handle_args()

    def print_help(self):
        print_wrap("USAGE: canto-remote [command] [options]")
        self.print_commands()

    def print_commands(self):
        print_wrap("COMMANDS")
        print_wrap("\thelp - get help on a command")
        print_wrap("\taddfeed - subscribe to a new feed")
        print_wrap("\tlistfeeds - list all subscribed feeds")
        print_wrap("\tdelfeed - unsubscribe from a feed")
        print_wrap("\tforce-update - refetch all feeds")
        print_wrap("\tconfig - change / query configuration variables")
        print_wrap("\tone-config - change / query one configuration variable")
        print_wrap("\texport - export feed list as OPML")
        print_wrap("\timport - import feed list from OPML")
        print_wrap("\tkill - cleanly kill the daemon")
        print_wrap("\tscript - run script")

    def _wait_response(self, cmd):
        r = None
        while True:
            r = self.read()
            if type(r) == int:
                if r == 16:
                    print_wrap("Server hung up.")
                else:
                    print_wrap("Got code: %d" % r)
                print_wrap("Please check daemon-log for exception.")
                return
            elif type(r) == tuple:
                if not cmd:
                    return r
                if r[0] == cmd:
                    return r[1]
                elif r[0] == "ERRORS":
                    print_wrap("ERRORS!")
                    for s in r[1]:
                        for o in r[1][s]:
                            print_wrap("%s.%s = %s <-- %s" %\
                                    (s, o, r[1][s][o][0], r[1][s][o][1]))
            elif r:
                print_wrap("Unknown return: %s" % r)
                break
        return None

    def _read_back_config(self):
        sections = self._wait_response("CONFIGS")
        for section in sections:
            for secvar in sections[section].keys():
                print_wrap("%s.%s = %s" % (section, secvar,\
                        sections[section][secvar]))

    def _autoname(self, URL):
        request = urllib2.Request(URL)
        request.add_header('User-Agent',\
                'Canto-Remote/0.8.0 + http://codezen.org/canto')
        try:
            content = feedparser.parse(feedparser.urllib2.urlopen(request))
        except Exception, e:
            print_wrap("ERROR: Couldn't determine name: %s" % e)
            return None

        if "title" in content["feed"]:
            return content["feed"]["title"]
        else:
            print_wrap("Couldn't find title in feed!")

        return None

    def _get_feeds(self):
        self.write("LISTTAGS", [])
        r = self._wait_response("LISTTAGS")

        r = [ x[9:] for x in r if x.startswith("maintag") ]
        self.write("CONFIGS", [ "Feed " + tag for tag in r ])
        c = self._wait_response("CONFIGS")

        ret = []

        for tag in r:
            t = {"tag" : tag}
            f = "Feed " + tag

            # Move any other interesting settings:
            for att in c[f]:
                t[att] = c[f][att]

            ret.append(t)

        return ret

    def _addfeed(self, attrs):
        if "name" not in attrs or not attrs["name"]:
            attrs["name"] = self._autoname(attrs["url"])
        if not attrs["name"]:
            return False

        print_wrap("Adding feed %s - %s" % (attrs["url"], attrs["name"]))

        configs = {}
        name = "Feed " + attrs["name"]
        del attrs["name"]

        configs[name] = attrs

        self.write("SETCONFIGS", configs )
        self.write("CONFIGS", [ name ])
        self._read_back_config()
        return True

    def cmd_addfeed(self):
        """USAGE: canto-remote addfeed [URL] (option=value) ...
    Where URL is the feed's URL. You can also specify options for the feed:

        name = Feed name (if not specified remote will attempt to lookup)
        rate = Rate, in minutes, at which this feed should be fetched.

        username = Username (if necessary) for password protected feeds.
        password = Password for password protected feeds."""

        if len(sys.argv) < 2:
            return False

        feed = { "url" : sys.argv[1] }
        name = None

        # Grab any feedopts from the commandline.

        for arg in sys.argv[2:]:
            opt, val = escsplit(arg, "=", 1, 1)
            if not opt or not val:
                print_wrap("ERROR: can't parse '%s' as x=y setting." % arg)
                continue
            feed[opt] = val

        return self._addfeed(feed)

    def cmd_listfeeds(self):
        """USAGE: canto-remote listfeeds
    Lists all tracked feeds."""

        if len(sys.argv) > 1:
            return False

        for idx, f in enumerate(self._get_feeds()):
            s = ("%d. " % idx) + f["tag"] + " "

            if "alias" in f:
                s += "(" + f["alias"] + ")"

            s += "\n   " + f["url"] + "\n"
            print_wrap(s)

    def cmd_delfeed(self):
        """USAGE: canto-remote delfeed [URL|name|alias]
    Unsubscribe from a feed."""
        if len(sys.argv) != 2:
            return False

        term = sys.argv[1]

        for idx, f in enumerate(self._get_feeds()):
            matches = [ f["url"], f["tag"], "%s" % idx]
            if "alias" in f:
                matches.append(f["alias"])

            if term in matches:
                print_wrap("Unsubscribing from %s" % f["url"])
                self.write("SETCONFIGS",  { "Feed " + f["tag"] : None })

    def _config(self, args):
        sets = {}
        gets = []

        for arg in args:
            var, val = escsplit(arg, "=", 1, 1)
            var = var.lstrip().rstrip()

            section, secvar = escsplit(var, ".", 1, 1)
            section = section.lstrip().rstrip()

            if secvar:
                secvar = secvar.lstrip().rstrip()

            if not section or not secvar:
                print_wrap("ERROR: Unable to parse \"%s\" as section.variable" % var)
                continue

            if val:
                val = val.lstrip().rstrip()
                if section in sets:
                    sets[section].update({secvar : val})
                else:
                    sets[section] = { secvar : val }

            if var not in gets:
                gets.append(var)

        self.write("SETCONFIGS", sets)
        self.write("CONFIGS", gets)
        self._read_back_config()
        return True

    def cmd_one_config(self):
        """USAGE: canto-remote one-config [option] ( = value)
    Where option is a full variable declaration like 'section.variable' and
    value is any string. If value is omitted, the current value will be printed.

    This differs from config as only one option can be set/got at a time, but
    it allows lax argument parsing (i.e. one-config CantoCurses.browser =
    firefox %u will work as expected, without quoting.)

    NOTE: validation is done by the client that uses the variable, canto-remote
    will let you give bad values, or even set values to non-existent
    variables."""

        if len(sys.argv) < 2:
            return False

        arg = " ".join(sys.argv[1:])

        return self._config([arg])

    def cmd_config(self):
        """USAGE: canto-remote config [option](=value) ...
    Where option is a full variable declaration like 'section.variable' and
    value is any string. If value is omitted, the current value will be printed.

    This differs from one-config as multiple sets/gets can be done, but it is
    more strict in terms of argument parsing.

    NOTE: validation is done by the client that uses the variable, canto-remote
    will let you give bad values, or even set values to non-existent
    variables."""

        if len(sys.argv) < 2:
            return False

        return self._config(sys.argv[1:])

    def cmd_export(self):
        """USAGE: canto-remote export

    This will print an OPML file to standard output."""

        print_wrap("""<opml version="1.0">""")
        print_wrap("""\t<body>""")
        for f in self._get_feeds():
            self.write("FEEDATTRIBUTES", { f["url"] : [ "version"] })
            attrs = self._wait_response("FEEDATTRIBUTES")
            if "atom" in attrs[f["url"]]["version"]:
                feedtype = "pie"
            else:
                feedtype = "rss"

            print_wrap("""\t\t<outline text="%s" xmlUrl="%s" type="%s" />""" %\
                (encoder(f["tag"].replace("\"","\\\"")),
                 encoder(f["url"].replace("\"","\\\"")),
                 feedtype))

        print_wrap("""\t</body>""")
        print_wrap("""</opml>""")

    def cmd_import(self):
        """USAGE: canto-remote import [OPML file]

    This will automatically import feeds from an OPML file, which can be
    generated by many different feed readers and other programs."""

        if len(sys.argv) != 2:
            return False

        opmlpath = sys.argv[1]

        try:
            data = decoder(open(opmlpath, "r").read())
        except Exception, e:
            print_wrap("Couldn't read OPML file:")
            traceback.print_exc()
            return

        feeds = []
        def parse_opml(name, attrs):
            # Skip elements we don't care about.
            if name != "outline":
                return

            # Skip outline elements with unknown type.
            if "type" in attrs and attrs["type"] not in ["pie","rss"]:
                return

            # Skip outline elements with type, but no URL
            if "xmlUrl" not in attrs:
                return

            f = { "url" : attrs["xmlUrl"], "name" : None }
            if "text" in attrs:
                f["name"] = attrs["text"]

            feeds.append(f)

        parser = xml.parsers.expat.ParserCreate()
        parser.StartElementHandler = parse_opml
        parser.Parse(data.encode("UTF-8"), 1)

        for feed in feeds:
            self._addfeed(feed)

    def cmd_script(self):
        """USAGE canto-remote script (scriptfile)

    Run script from scriptfile or stdin.

    Note: This is intended for testing and does not gracefully handle errors."""

        if len(sys.argv) not in [1, 2]:
            return False

        if len(sys.argv) == 1:
            lines = sys.stdin.readlines()
        else:
            f = open(sys.argv[1], "r")
            lines = f.readlines()
            f.close()

        pp = pprint.PrettyPrinter()

        for line in lines:
            line = line[:-1].lstrip()
            print_wrap(line)
            sys.__stdout__.flush()

            # Wait for n responses.

            if line.startswith("REMOTE_WAIT "):
                num = int(line.split(" ", 1)[-1])
                for i in xrange(num):
                    r = self._wait_response(None)
                    pp.pprint(r)
                    sys.__stdout__.flush()

            elif line.startswith("REMOTE_IGNORE "):
                num = int(line.split(" ", 1)[-1])
                for i in xrange(num):
                    self._wait_response(None)

            # Hang with socket open so that the daemon thinks
            # we're using any data we've requested. Script runners
            # must be smart enough to signal-kill this remote.

            elif line.startswith("REMOTE_HANG"):
                while True:
                    time.sleep(1000)

            # Skip comments / blank

            elif line == '' or line.startswith("#"):
                continue

            else:
                cmd, arg = line.split(' ', 1)
                self.write(cmd, eval(arg))

    def cmd_kill(self):
        """USAGE: canto-remote kill

    Cleanly kill the connected daemon."""

        self.write("DIE", {})

    def cmd_force_update(self):
        """USAGE: canto-remote force-update

    Force fetch of all feeds."""

        self.write("FORCEUPDATE", {})

    def cmd_help(self):
        """USAGE: canto-remote help [command]"""
        if len(sys.argv) < 2:
            return False

        command = "cmd_" + sys.argv[1].replace("-","_")

        if command in dir(self):
            print_wrap(getattr(self, command).__doc__)
        else:
            print_wrap(self.cmd_help.__doc__)
            self.print_commands()

    def handle_args(self):
        if len(sys.argv) < 1:
            self.print_help()
            return

        sys.argv = [ decoder(a) for a in sys.argv ]

        command = "cmd_" + sys.argv[0].replace("-","_")

        if command in dir(self):
            func = getattr(self, command)
            r = func()
            if r == False:
                print_wrap(func.__doc__)
        else:
            self.print_help()
