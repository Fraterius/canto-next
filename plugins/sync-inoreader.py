# Canto Inoreader Plugin
# by Jack Miller
# v0.2

# DEPENDENCIES

# This plugin requires the 'requests' module, which can usually be found in
# your distro's package manager as python3-requests (or python-requests on
# Arch).

# IMPORTANT NOTES

# - When this plugin is enabled, canto will synchronize your subscribed feeds
# with Inoreader. If you've been using canto, you should export your feeds
# (canto-remote export > feeds.opml) and import them into Inoreader if you
# don't want to lose your feeds because Inoreader's info is assumed to be more
# correct than ours.
#
# - Feed subscriptions are only synchronized *from Inoreader* on startup, so if
# you add / remove feeds with Inoreader, you will have to restart the daemon to
# pickup the changes. Adding or removing feeds with canto works properly all
# the time.
#
# - You should probably only enable this if you have disabled other sync-*
# plugins (like sync-rsync). They won't break, but having multiple
# synchronization points is pointless.
#
# - You must have a standard Inoreader account, not an OAuth (Google/Facebook
# login).

# CONFIGURATION

# Inoreader credentials

EMAIL="somebody@somewhere.com"
PASSWORD="passw0rd"

# You don't *have* to change these, but the API is rate limited. So if you want
# to avoid rate limit issues, register your own application Preferences ->
# Developer options on the Inoreader site and replace these.

APP_ID="1000001299"
APP_KEY="i0UOUtLQjj2WTre8WA3a9GWt_cgDhpkO"

BASE_URL="https://www.inoreader.com/reader/"

# === You shouldn't have to change anything past this line. ===

from canto_next.fetch import DaemonFetchThreadPlugin
from canto_next.feed import DaemonFeedPlugin, allfeeds
from canto_next.hooks import call_hook, on_hook
from canto_next.config import config

from urllib.parse import urlencode, quote
import traceback
import requests
import logging
import time
import json

log = logging.getLogger("SYNC-INOREADER")

extra_headers = {
        "User-Agent" : "Canto/0.9.0 + http://codezen.org/canto-ng",
        "AppKey" : APP_KEY,
        "AppID" : APP_ID,
}

def ino_get_auth():
    headers = extra_headers.copy()
    headers['Email'] = EMAIL
    headers['Passwd'] = PASSWORD

    r = requests.get("https://www.inoreader.com/accounts/ClientLogin", headers)
    if r.status_code != 200:
        raise Exception("Failed to authorize: [%s] %s" % (r.status_code, r.text))

    for line in r.text.splitlines():
        if line.startswith("Auth="):
            return line[5:]

    raise Exception("Failed to find Auth= in auth response")

authorization = ino_get_auth()

log.debug("authorization: %s", authorization)

# XXX : Needs to handle errors / reauth

def inoreader_req(path, query = {}):
    headers = extra_headers.copy()
    headers["Authorization"] = "GoogleLogin auth=" + authorization

    r = requests.get(BASE_URL + path, params=query, headers=headers)

    if r.status_code != 200:
        log.debug("STATUS %s", r.status_code)
        log.debug(r.headers)
        log.debug(r.text)

    return r

def full_ino_tag_suffix(tag):
    if tag in ["read", "starred", "fresh"]:
        return "/state/com.google/" + tag
    return "/label/" + tag

def full_ino_tag(tag):
    return "user/-" + full_ino_tag_suffix(tag)

def strip_ino_tag(tag):
    tag = tag.split("/", 3)
    if tag[2] == "state":
        return tag[3].split("/", 1)[1]
    return tag[3]

def has_ino_tag(item, tag):
    if "canto_inoreader_categories" not in item:
        return False

    suff = full_ino_tag_suffix(tag)
    for category in item["canto_inoreader_categories"]:
        if category.endswith(suff):
            return True
    return False

def inoreader_add_tag(ino_id, tag):
    path = "api/0/edit-tag?a=" + quote(full_ino_tag(tag))
    path += "&i=" + quote(ino_id)
    inoreader_req(path)

def inoreader_remove_tag(ino_id, tag):
    path = "api/0/edit-tag?r=" + quote(full_ino_tag(tag))
    path += "&i=" + quote(ino_id)
    inoreader_req(path)

def inoreader_get_subs():
    return inoreader_req("api/0/subscription/list").json()["subscriptions"]

def inoreader_add_sub(feed_url, title):
    query = {
        "ac" : "subscribe",
        "s" : "feed/" + feed_url,
        "t" : title
    }

    inoreader_req("api/0/subscription/edit", query)

def inoreader_del_sub(feed_url):
    query = {
        "ac" : "unsubscribe",
        "s" : "feed/" + feed_url
    }
    inoreader_req("api/0/subscription/edit", query)


# Given a change set, and the current attributes of a canto item, tell
# Inoreader about it.

def sync_state_to(changes, attrs, add_only = False):
    if "canto-state" in changes:
        if "read" in changes["canto-state"]:
            if not has_ino_tag(attrs, "read"):
                inoreader_add_tag(attrs["canto_inoreader_id"], "read")
        elif not add_only:
            if has_ino_tag(attrs, "read"):
                inoreader_remove_tag(attrs["canto_inoreader_id"], "read")

    if "canto-tags" in changes:
        for tag in changes["canto-tags"]:
            tag = tag.split(":", 1)[1] # strip user: or category: prefix
            if not has_ino_tag(attrs, tag):
                inoreader_add_tag(attrs["canto_inoreader_id"], tag)

        if add_only:
            return

        for tag in attrs["canto_inoreader_categories"]:
            tag = strip_ino_tag(tag)
            if "user:" + tag not in changes[item_id]["canto-tags"]:
                inoreader_remove_tag(attrs["canto_inoreader_id"], tag)

class CantoFeedInoReader(DaemonFeedPlugin):
    def __init__(self, feed):
        self.plugin_attrs = { "edit_inoreader_sync" : self.edit_inoreader_sync }
        self.feed = feed

    def _list_add(self, item, attr, new):
        if attr not in item:
            item[attr] = [ new ]
        elif new not in item[attr]:
            item[attr].append(new)

    def add_utag(self, item, tags_to_add, tag):
        self._list_add(item, "canto-tags", "user:" + tag)
        tags_to_add.append((self.feed._cacheitem(item)["id"], "user:" + tag))

    def add_state(self, item, state):
        self._list_add(item, "canto-state", state)

    def fetch_inoreader_data(self, feed, newcontent):
        # Grab these from the parent object

        stream_id = quote("feed/" + feed.URL, [])

        query = { "n" : 1000 }

        # Collect all of the items

        ino_entries = []
        content_path = "api/0/stream/contents/" + stream_id

        try:
            r = inoreader_req(content_path, query).json()
            ino_entries.extend(r["items"])

            #while "continuation" in r:
            #    query["c"] = r["continuation"]
            #    r = inoreader_req(content_path, query).json()
            #    ino_entries.extend(r["items"])
        except Exception as e:
            log.debug("EXCEPT: %s", traceback.format_exc(e))

        for ino_entry in ino_entries:
            for canto_entry in newcontent["entries"]:
                if ino_entry["canonical"][0]["href"] != canto_entry["link"]:
                    continue

                canto_entry["canto_inoreader_id"] = ino_entry["id"]
                canto_entry["canto_inoreader_categories"] = ino_entry["categories"]
                break

    def edit_inoreader_sync(self, **kwargs):
        feed = kwargs["feed"]
        newcontent = kwargs["newcontent"]
        tags_to_add = kwargs["tags_to_add"]
        tags_to_remove = kwargs["tags_to_remove"]

        self.fetch_inoreader_data(feed, newcontent)

        for entry in newcontent["entries"]:
            # If we didn't get an id for this item, skip it

            if "canto_inoreader_id" not in entry:
                continue

            for category in entry["canto_inoreader_categories"]:
                if category.endswith("/state/com.google/read"):
                    self.add_state(entry, "read")
                    continue

                cat = category.split("/", 3)
                if len(cat) < 4:
                    log.debug("Weird category? %s", cat)
                    continue

                if cat[2] == "state":
                    if cat[3] == "com.google/starred":
                        self.add_utag(entry, tags_to_add, "starred")
                elif cat[2] == "label":
                    self.add_utag(entry, tags_to_add, cat[3])

            # If this is the first time we've paired an item up with its
            # Inoreader data, our state is better, so sync it to Inoreader, and
            # then skip the remainder of the logic to remove canto state/tags

            if "canto-inoreader-sync" not in entry:
                sync_state_to(entry, entry, True)
                entry["canto-inoreader-sync"] = True
                continue

            if "canto-state" not in entry or type(entry["canto-state"]) != list:
                continue

            # It appears that if an item is "fresh" it will resist all attempts
            # to set it as read?

            if "read" in entry["canto-state"] and not\
                    (has_ino_tag(entry, "read") or has_ino_tag(entry, "fresh")):
                log.debug("Marking unread from Inoreader")
                entry["canto-state"].remove("read")

            if "canto-tags" not in entry or type(entry["canto-tags"]) != list:
                continue

            for tag in entry["canto-tags"][:]:
                if not has_ino_tag(entry, tag.split(":", 1)[1]):
                    entry["canto-tags"].remove(tag)
                    tags_to_remove.append((self.feed._cacheitem(entry)["id"], tag))

# For canto communicating to Inoreader, we tap into the relevant hooks to
# pickup state / tag changes, and convert that into Inoreader API calls.

def post_setattributes(socket, args):
    for item_id in args.keys():
        dict_id = json.loads(item_id)

        feed = allfeeds.get_feed(dict_id["URL"])

        attrs = feed.get_attributes([item_id], { item_id :\
                ["canto_inoreader_id", "canto_inoreader_categories", "canto-state", "canto-tags"] })
        attrs = attrs[item_id]

        # If the canto_inoreader_id isn't right (likely empty since get_attributes
        # will sub in "") then skip synchronizing this item.

        ino_id = attrs["canto_inoreader_id"]
        if not ino_id.startswith("tag:google.com,2005:reader/item/"):
            continue

        sync_state_to(args[item_id], attrs)

on_hook("daemon_post_setattributes", post_setattributes)

def post_setconfigs(socket, args):
    if "feeds" in args:
        for feed in args["feeds"]:
            inoreader_add_sub(feed["url"], feed["name"])

on_hook("daemon_post_setconfigs", post_setconfigs)

def post_delconfigs(socket, args):
    if "feeds" in args:
        for feed in args["feeds"]:
            inoreader_del_sub(feed["url"])

on_hook("daemon_post_delconfigs", post_delconfigs)

# Do the initial feed synchronization. This only occurs once per run, and
# assumes Inoreader knows everything.

def on_daemon_serving():
    log.debug("Synchronizing subscriptions.")
    ino_subs = inoreader_get_subs()

    for sub in ino_subs:
        url = sub["url"]
        name = sub["title"]

        for c_feed in config.json["feeds"]:
            if c_feed["url"] == url:
                break
        else:
            log.debug("New feed: %s", url)
            call_hook("daemon_set_configs", [ None, { "feeds" : [ { "name" : name, "url" : url } ] } ])

    for c_feed in config.json["feeds"]:
        url = c_feed["url"]

        for sub in ino_subs:
            if sub["url"] == url:
                break
        else:
            log.debug("Old feed: %s", url)
            call_hook("daemon_del_configs", [ None, { "feeds" : [ c_feed ] } ] )

on_hook("daemon_serving", on_daemon_serving)
