# -*- coding: utf-8 -*-
##
##
## This file is part of Indico.
## Copyright (C) 2002 - 2014 European Organization for Nuclear Research (CERN).
##
## Indico is free software; you can redistribute it and/or
## modify it under the terms of the GNU General Public License as
## published by the Free Software Foundation; either version 3 of the
## License, or (at your option) any later version.
##
## Indico is distributed in the hope that it will be useful, but
## WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
## General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with Indico;if not, see <http://www.gnu.org/licenses/>.

import traceback
from functools import wraps

from flask import request

from indico.core.errors import IndicoError
from indico.core.logger import Logger
from indico.util.json import create_json_error_answer


class classproperty(property):
    def __get__(self, obj, type=None):
        return self.fget.__get__(None, type)()


class cached_classproperty(property):
    def __get__(self, obj, type=None):
        # The property name is the function's name
        name = self.fget.__get__(True).im_func.__name__
        value = object.__getattribute__(type, name)
        # We we have a cached_classproperty, the value has not been resolved yet
        if isinstance(value, cached_classproperty):
            value = self.fget.__get__(None, type)()
            setattr(type, name, value)
        return value


def cached_writable_property(cache_attr, cache_on_set=True):
    class _cached_writable_property(property):
        def __get__(self, obj, objtype=None):
            if obj is not None and self.fget and hasattr(obj, cache_attr):
                return getattr(obj, cache_attr)
            value = property.__get__(self, obj, objtype)
            setattr(obj, cache_attr, value)
            return value

        def __set__(self, obj, value):
            property.__set__(self, obj, value)
            if cache_on_set:
                setattr(obj, cache_attr, value)
            else:
                try:
                    delattr(obj, cache_attr)
                except AttributeError:
                    pass

        def __delete__(self, obj):
            property.__delete__(self, obj)
            try:
                delattr(obj, cache_attr)
            except AttributeError:
                pass

    return _cached_writable_property


def jsonify_error(function=None, logger_name=None, logger_message=None, logging_level='info'):
    """
    Returns response of error handlers in JSON if requested in JSON
    and logs the exception that ended the request.
    """
    def _jsonify_error(f):
        @wraps(f)
        def wrapper(*args, **kw):
            for e in list(args) + kw.values():
                if isinstance(e, Exception):
                    exception = e
                    break
            else:
                raise IndicoError('Wrong usage of jsonify_error: No error found in params')

            tb = traceback.format_exc() if logging_level != 'exception' else ''
            getattr(Logger.get(logger_name), logging_level)(
                logger_message if logger_message else
                'Request {0} finished with {1}: {2}\n{3}'.format(
                    request, exception.__class__.__name__, exception, tb
                ).rstrip())

            if request.is_xhr or request.headers.get('Content-Type') == 'application/json':
                return create_json_error_answer(exception)
            else:
                return f(*args, **kw)
        return wrapper
    if function:
        return _jsonify_error(function)
    return _jsonify_error
