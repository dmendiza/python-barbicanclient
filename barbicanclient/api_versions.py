#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import functools
import logging
import re

from barbicanclient import exceptions

LOG = logging.getLogger(__name__)

SERVER_INITIAL_VERSION = "1.0"
# This is the default, for when the server doesn't return version information

MAX_VERSION = "1.1"
MIN_VERSION = "1.0"

_SUBSTITUTIONS = {}

_type_error_msg = "'%(other)s' should be an instance of '%(cls)s'"


class APIVersion(object):
    """API Version

    This class represents an API version with convenience
    methods for manipulation and comparison of version
    numbers that we need to do to implement microversions.
    """

    def __init__(self, version_str=None):
        """Create an API version object."""
        self.ver_major = 0
        self.ver_minor = 0

        if version_str is not None:
            match = re.match(
                r"^[v]?([1-9]\d*)[\.]?([1-9]\d*|0|latest)?$", version_str)
            if match:
                self.ver_major = int(match.group(1))
                if match.group(2) is None:
                    self.ver_minor = 0
                elif match.group(2) == "latest":
                    # NOTE(andreykurilin): Infinity allows to easily determine
                    # latest version and doesn't require any additional checks
                    # in comparison methods.
                    self.ver_minor = float("inf")
                else:
                    self.ver_minor = int(match.group(2))
            else:
                msg = ("Invalid format of client version '%s'. "
                       "Expected format 'X.Y', where X is a major part and Y "
                       "is a minor part of version.") % version_str
                raise exceptions.UnsupportedVersion(msg)

    def __str__(self):
        """Debug/Logging representation of object."""
        if self.is_latest():
            return "Latest API Version Major: %s" % self.ver_major
        return ("API Version Major: %s, Minor: %s"
                % (self.ver_major, self.ver_minor))

    def __repr__(self):
        if self:
            return "<APIVersion: %s>" % self.get_string()
        return "<APIVersion: null>"

    def __bool__(self):
        return self.ver_major != 0 or self.ver_minor != 0

    __nonzero__ = __bool__

    def is_latest(self):
        return self.ver_minor == float("inf")

    def __lt__(self, other):
        if not isinstance(other, APIVersion):
            raise TypeError(_type_error_msg % {"other": other,
                                               "cls": self.__class__})

        return ((self.ver_major, self.ver_minor) <
                (other.ver_major, other.ver_minor))

    def __eq__(self, other):
        if not isinstance(other, APIVersion):
            raise TypeError(_type_error_msg % {"other": other,
                                               "cls": self.__class__})

        return ((self.ver_major, self.ver_minor) ==
                (other.ver_major, other.ver_minor))

    def __gt__(self, other):
        if not isinstance(other, APIVersion):
            raise TypeError(_type_error_msg % {"other": other,
                                               "cls": self.__class__})

        return ((self.ver_major, self.ver_minor) >
                (other.ver_major, other.ver_minor))

    def __le__(self, other):
        return self < other or self == other

    def __ne__(self, other):
        return not self.__eq__(other)

    def __ge__(self, other):
        return self > other or self == other

    def matches(self, min_version, max_version=None):
        """Check if version matches the range

        Returns whether the version object represents a version
        greater than or equal to the minimum version and less than
        or equal to the maximum version.

        :param min_version: Minimum acceptable version.
        :param max_version: Maximum acceptable version.
        :returns: boolean

        If min_version is null then there is no minimum limit.
        If max_version is null then there is no maximum limit.
        If self is null then raise ValueError
        """

        if not self:
            raise ValueError("Null APIVersion doesn't support 'matches'.")

        if isinstance(min_version, str):
            min_version = APIVersion(version_str=min_version)
        if isinstance(max_version, str):
            max_version = APIVersion(version_str=max_version)

        # This will work when they are None and when they are version 0.0
        if not min_version and not max_version:
            return True

        if not max_version:
            return min_version <= self
        if not min_version:
            return self <= max_version
        return min_version <= self <= max_version

    def get_string(self):
        """Converts object to string representation

        which if used to create an APIVersion object results in the
        same version.
        """
        if not self:
            raise ValueError("Null APIVersion cannot be converted to string.")
        elif self.is_latest():
            return "%s.%s" % (self.ver_major, "latest")
        return "%s.%s" % (self.ver_major, self.ver_minor)

    def get_major_version(self):
        return "%s" % self.ver_major


class VersionedMethod(object):

    def __init__(self, name, start_version, end_version, func):
        """Versioning information for a single method

        :param name: Name of the method
        :param start_version: Minimum acceptable version
        :param end_version: Maximum acceptable_version
        :param func: Method to call

        Minimum and maximums are inclusive
        """
        self.name = name
        self.start_version = start_version
        self.end_version = end_version
        self.func = func

    def __str__(self):
        return ("Version Method %s: min: %s, max: %s"
                % (self.name, self.start_version, self.end_version))

    def __repr__(self):
        return "<VersionedMethod %s>" % self.name


def discover_version(client, requested_version):
    """Returns most recent version supported by API and client

    :param client: client object
    :param requested_version: requested version represented by APIVersion obj
    :returns: APIVersion
    """

    # get the version supported by the server
    versions = client.versions.list_versions()

    # only v1 exists right now
    version = versions[0]
    server_start_version = APIVersion(
        version.get('min_version', SERVER_INITIAL_VERSION))
    server_end_version = APIVersion(
        version.get('max_version', SERVER_INITIAL_VERSION))

    _validate_server_version(server_start_version, server_end_version)

    # get the highest version the server can handle relative to the
    # requested version
    valid_version = _validate_requested_version(
        requested_version,
        server_start_version,
        server_end_version)

    # see if we need to downgrade for the client
    client_max = APIVersion(MAX_VERSION)
    if client_max < valid_version:
        msg = ("Requested version %(requested_version)s is "
               "not supported. Downgrading requested version "
               "to %(actual_version)s.")
        LOG.debug(msg, {
            "requested_version": requested_version,
            "actual_version": client_max})
        valid_version = client_max

    return valid_version


def _validate_requested_version(requested_version,
                                server_start_version,
                                server_end_version):
    """Validates the requested version.

    Checks 'requested_version' is within the min/max range supported by the
    server. If 'requested_version' is not within range then attempts to
    downgrade to 'server_end_version'. Otherwise an UnsupportedVersion
    exception is thrown.

    :param requested_version: requestedversion represented by APIVersion obj
    :param server_start_version: APIVersion object representing server min
    :param server_end_version: APIVersion object representing server max
    """
    valid_version = requested_version
    if not requested_version.matches(server_start_version, server_end_version):
        if server_end_version <= requested_version:
            if (APIVersion(MIN_VERSION) <= server_end_version and
                    server_end_version <= APIVersion(MAX_VERSION)):
                msg = ("Requested version %(requested_version)s is "
                       "not supported. Downgrading requested version "
                       "to %(server_end_version)s.")
                LOG.debug(msg, {
                    "requested_version": requested_version,
                    "server_end_version": server_end_version})
            valid_version = server_end_version
        else:
            raise exceptions.UnsupportedVersion(
                ("The specified version isn't supported by server. The valid "
                 "version range is '%(min)s' to '%(max)s'") % {
                     "min": server_start_version.get_string(),
                     "max": server_end_version.get_string()})

    return valid_version


def _validate_server_version(server_start_version, server_end_version):
    """Validates the server version.

    Checks that the 'server_end_version' is greater than the minimum version
    supported by the client. Then checks that the 'server_start_version' is
    less than the maximum version supported by the client.

    :param server_start_version:
    :param server_end_version:
    :return:
    """
    if APIVersion(MIN_VERSION) > server_end_version:
        raise exceptions.UnsupportedVersion(
            ("Server's version is too old. The client's valid version range "
             "is '%(client_min)s' to '%(client_max)s'. The server valid "
             "version range is '%(server_min)s' to '%(server_max)s'.") % {
                 'client_min': MIN_VERSION,
                 'client_max': MAX_VERSION,
                 'server_min': server_start_version.get_string(),
                 'server_max': server_end_version.get_string()})
    elif APIVersion(MAX_VERSION) < server_start_version:
        raise exceptions.UnsupportedVersion(
            ("Server's version is too new. The client's valid version range "
             "is '%(client_min)s' to '%(client_max)s'. The server valid "
             "version range is '%(server_min)s' to '%(server_max)s'.") % {
                 'client_min': MIN_VERSION,
                 'client_max': MAX_VERSION,
                 'server_min': server_start_version.get_string(),
                 'server_max': server_end_version.get_string()})


def update_headers(headers, api_version):
    """Set 'OpenStack-API-Version' header if api_version is not null """
    if api_version and api_version.ver_minor != 0:
        headers["OpenStack-API-Version"] = "volume " + api_version.get_string()


def add_substitution(versioned_method):
    _SUBSTITUTIONS.setdefault(versioned_method.name, [])
    _SUBSTITUTIONS[versioned_method.name].append(versioned_method)


def get_substitutions(func_name, api_version=None):
    substitutions = _SUBSTITUTIONS.get(func_name, [])
    if api_version:
        return [m for m in substitutions
                if api_version.matches(m.start_version, m.end_version)]
    return substitutions


def get_function_name(func):
    return "%s.%s" % (func.__module__, func.__qualname__)


def add_arg(f, *args, **kwargs):
    """Bind CLI arguments to a shell.py `do_foo` function."""

    if not hasattr(f, 'arguments'):
        f.arguments = []

    # NOTE(sirp): avoid dups that can occur when the module is shared across
    # tests.
    if (args, kwargs) not in f.arguments:
        # Because of the semantics of decorator composition if we just append
        # to the options list positional options will appear to be backwards.
        f.arguments.insert(0, (args, kwargs))


def wraps(start_version, end_version=None):
    start_version = APIVersion(start_version)
    if end_version:
        end_version = APIVersion(end_version)
    else:
        end_version = APIVersion("%s.latest" % start_version.ver_major)

    def decor(func):
        func.versioned = True
        name = get_function_name(func)
        versioned_method = VersionedMethod(name, start_version,
                                           end_version, func)
        add_substitution(versioned_method)

        @functools.wraps(func)
        def substitution(obj, *args, **kwargs):
            methods = get_substitutions(name, obj.api_version)

            if not methods:
                raise exceptions.VersionNotFoundForAPIMethod(
                    obj.api_version.get_string(), name)

            method = max(methods, key=lambda f: f.start_version)

            return method.func(obj, *args, **kwargs)

        if hasattr(func, 'arguments'):
            for cli_args, cli_kwargs in func.arguments:
                add_arg(substitution, *cli_args, **cli_kwargs)
        return substitution

    return decor