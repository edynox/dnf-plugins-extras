# local.py
# Automatically copy all downloaded packages to a repository on the local
# filesystem
#
# Copyright (C) 2015 Igor Gnatenko
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU General Public License v.2, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY expressed or implied, including the implied warranties of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.  You should have received a copy of the
# GNU General Public License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.  Any Red Hat trademarks that are incorporated in the
# source code or documentation are not subject to the GNU General Public
# License and may only be used or replicated with the express permission of
# Red Hat, Inc.
#

from __future__ import absolute_import
from __future__ import unicode_literals

import dnf
import dnf.cli
import dnfpluginsextras
import iniparse.compat as ini
import os
import shutil

_ = dnfpluginsextras._


class LocalConfParse(object):
    """Parsing config

    Args:
      conf (iniparse.compat.ConfigParser): Config to parse

    """
    def __init__(self, conf):
        self.conf = conf

    def _get_bool(self, section, name):
        tmp = self.conf.get(section, name)
        if tmp == "false" or tmp == "0":
            return False
        else:
            return True

    def parse_config(self):
        conf = self.conf
        main = {}
        crepo = {}

        main["enabled"] = self._get_bool("main", "enabled")
        crepo["enabled"] = self._get_bool("createrepo", "enabled")

        if main["enabled"]:
            try:
                main["repodir"] = conf.get("main", "repodir")
            except ini.Error:
                main["repodir"] = "/var/lib/dnf/plugins/local"

        if crepo["enabled"]:
            try:
                crepo["cachedir"] = conf.get("createrepo", "cachedir")
            except ini.Error:
                crepo["cachedir"] = None
            try:
                crepo["quiet"] = self._get_bool("createrepo", "quiet")
            except ini.Error:
                crepo["quiet"] = True
            try:
                crepo["verbose"] = self._get_bool("createrepo", "verbose")
            except ini.Error:
                crepo["verbose"] = False

        return main, crepo


class Local(dnf.Plugin):

    name = "local"

    def __init__(self, base, cli):
        super(Local, self).__init__(base, cli)
        self.base = base
        self.main = {}
        self.crepo = {}
        # To store original keepcache param
        self.keepcache = None
        self.logger = dnfpluginsextras.logger

    def config(self):
        conf = self.read_config(self.base.conf, "local")

        parser = LocalConfParse(conf)
        try:
            self.main, self.crepo = parser.parse_config()
        # FIXME: https://bugzilla.redhat.com/show_bug.cgi?id=1186053
        except ini.Error:
            self.main["enabled"] = False
            self.crepo["enabled"] = False
            return

        local_repo = dnf.repo.Repo("_local", self.base.conf.cachedir)
        local_repo.baseurl = "file://{}".format(self.main["repodir"])
        self.base.repos.add(local_repo)

        # FIXME: https://bugzilla.redhat.com/show_bug.cgi?id=1185977
        self.keepcache = self.base.conf.keepcache
        self.base.conf.keepcache = True

    def transaction(self):
        main, crepo = self.main, self.crepo

        if not main["enabled"]:
            return

        repodir = main["repodir"]
        if not os.path.isdir(repodir):
            self.logger.error(
                "local: " + _("'{}' is not a directory").format(repodir))
            return

        for pkg in self.base.transaction.install_set:
            if pkg.repo.pkgdir == repodir:
                continue
            path = os.path.join(pkg.repo.pkgdir, pkg.location.split("/")[-1])
            self.logger.debug(
                "local: " + _("Copying '{}' to local repo").format(path))
            try:
                shutil.copy2(path, repodir)
            except IOError:
                self.logger.error(
                    "local: " + _("Can't write file '{}'").format(os.path.join(
                        repodir, os.path.basename(path))))

        if not self.keepcache:
            self.base.clean_used_packages()

        if not crepo["enabled"]:
            return

        args = ["createrepo", "--update", "--unique-md-filenames"]
        if crepo["quiet"]:
            args.append("--quiet")
        if crepo["verbose"]:
            args.append("--verbose")
        if crepo["cachedir"] is not None:
            args.append("--cachedir")
            args.append(crepo["cachedir"])
        args.append(repodir)
        self.logger.debug("local: " + _("Rebuilding local repo"))
        os.spawnvp(os.P_WAIT, "createrepo", args)
