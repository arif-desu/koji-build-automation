import koji
import os
import time
import string
import random
import logging
from util import (config_to_dict, nestedseek, error)


class KojiSession(koji.ClientSession):

    def __init__(self, kojiconfig , section = None):
        assert kojiconfig, "Configuration file path should not be empty"
        self.logger = logging.getLogger('kojisession')

        config = config_to_dict(kojiconfig, section)

        try:
            self.server = str(config.get("server"))
            self.logger.info("Server set to %s" %  self.server)
        except KeyError:
            error("Parameter server not defined in %s" % kojiconfig)
        
        try:
            self.auth = str(config.get("authtype")).lower()
        except KeyError as e:
            self.auth = None
            self.logger.warning("Authentication method not defined")
        
        if self.auth is not None:
            if self.auth == "ssl":
                try :
                    self._ca_cert = os.path.expanduser(config.get("serverca"))
                    self._client_cert = os.path.expanduser(config.get("cert"))
                    self.set = True
                except KeyError:
                    self.logger.warning('SSL certificate info not defined in %s' % kojiconfig, exc_info=True)
                    self.set = False
                except (FileNotFoundError, PermissionError) as e:
                    self.logger.warning(e)
                    self.set = False
            elif self.auth == "kerberos" :
                try:
                    self._principal = os.path.expanduser(config.get("principal"))
                    self._keytab = os.path.expanduser(config.get("keytab"))
                    self.set = True
                except KeyError:
                    self.logger.warning('Kerberos authentication info not defined in %s' % kojiconfig, exc_info=True)
                    self.set = False
                except (FileNotFoundError, PermissionError) as e:
                    self.logger.warning(e)
                    self.set = False
                except TypeError:
                    pass

        else :
            self.logger.warning('Unsupported authentication method "%s" specified in configuration file' % self.auth)
            self.set = False

        # Call parent class constructor   
        koji.ClientSession.__init__(self, baseurl = self.server)

    """-----------------------------------------------------------------------------------------------------------"""

    def login(self) -> bool:
        """
        Login to koji instance using SSL or Keberos authentication
        """
        if self.set is not False:
            if self.auth == "ssl":
                info = self.ssl_login(cert = self._client_cert, 
                                    serverca = self._ca_cert)
            elif self.auth == "kerberos":
                info =  self.gssapi_login(principal = self._principal, 
                                        keytab = self._keytab) 
            else :
                self.logger.critical('Unsupported authentication method "%s" specified' % self.auth)
                return False
            
            if info is True:
                self.logger.info("Logged in as %s@%s. Authenticated via %s" % (((self.getLoggedInUser()).get('name')), 
                                                                                 self.server, self.auth))
            return info
        else:
            return False

    """-----------------------------------------------------------------------------------------------------------"""

    def getSCM_URL(self, tag, pkg):
        build_id = None
        try:
            pkginfo = self.getLatestRPMS(tag = tag, package = pkg)
        except koji.GenericError as e:
            self.logger.error(str(e).splitlines()[-1])
        except IndexError:
            self.logger.critical("No package %s in tag %s" % (pkg, tag))
        else:
            build_id = list(nestedseek(pkginfo, key = 'build_id'))[0]

        if build_id is not None:
            info = self.getBuild(buildInfo = build_id)
            self.logger.debug("Package %s : SCM URL - %s" % pkg, info['source'])
            return info['source']
        else:
            return None
        
    """-----------------------------------------------------------------------------------------------------------"""

    def isNoArch(self, tag, pkg):
        noarch = ['src', 'noarch']

        try:
            builds = self.getLatestRPMS(tag = tag, package = pkg)
        except koji.GenericError as e:
            self.logger.warning(str(e).splitlines()[-1])

        if any(builds):
            arches = nestedseek(builds, key = 'arch')
            for arch in arches:
                if str(arch) not in noarch:
                    return False
        
            return True
        else:
            self.logger.critical("No builds for package %s" % pkg)
            return False
    """-----------------------------------------------------------------------------------------------------------"""

    def getPackageList(self, tag) :
        res = self.listPackages(tagID = tag)
        if res is not None:
            packages = nestedseek(res, "package_name")
            for pkg in packages:
                yield pkg
        else:
            self.logger.info(f"No package tagged under tag :{tag}")
            return None
    """-----------------------------------------------------------------------------------------------------------"""

    def importPackage(self, pkgdir, tag, prune_dir: bool = True):
        
        def unique_path(prefix):
            """Create a unique path fragment by appending a path component to prefix. """
            return '%s/%r.%s' % (prefix, time.time(),
                                ''.join([random.choice(string.ascii_letters) for i in range(8)]))
        
        if not os.path.exists(pkgdir):
            self.logger.critical(f"Directory {pkgdir} does not exist")
            return False
        
        if self.getSessionInfo() is None:
            if self.login() == False:
                self.logger.critical("You must be logged in to import packages")
                return False
            
        for rpm in list(os.listdir(pkgdir)):
            localfile = '/'.join([pkgdir, rpm])
            serverdir = unique_path('app-import')
            # uploadWrapper - undocumented API
            self.uploadWrapper(localfile = localfile, path = serverdir)
            try:
                self.importRPM(path = serverdir, basename = rpm)
                self.logger.info(f"Imported {rpm}")
            except koji.GenericError as e:
                error("Error importing: %s" % str(e).splitlines()[-1])

        untagged = self.untaggedBuilds()

        # Tag imported packages
        for rpm in untagged:
            self.tagBuildBypass(tag, build = rpm)
            self.logger.info(f"Tagging build {rpm} under {tag}")

        self.logger.info("Successfully imported package : %s" % (os.path.basename(pkgdir)))

        # Prune downloads after uploading to save disk space
        if prune_dir:
            try :
                os.rmdir(pkgdir)
                self.logger.info(f"Removing directory {pkgdir}")
            except PermissionError:
                self.logger.warning(f"Permission error removing directory {pkgdir}")

        return 0
    """-----------------------------------------------------------------------------------------------------------"""

    def totalHosts(self, arch) :
        return len(self.listHosts(arches = list(arch), enabled = True, channelID = "default"))
    
    """-----------------------------------------------------------------------------------------------------------"""
    
    def readyHosts(self, arch) :
        return len(self.listHosts(arches = list(arch), enabled = True, ready = True, channelID = "default"))

    
            

        

