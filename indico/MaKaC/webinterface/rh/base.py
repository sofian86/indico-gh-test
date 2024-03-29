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
import copy
import inspect
import time
import os
import profile as profiler
import pstats
import sys
import random
import StringIO
from datetime import datetime, timedelta
from urlparse import urljoin
from xml.sax.saxutils import escape

import oauth2 as oauth
import transaction
from flask import request, session
from werkzeug.exceptions import BadRequest, MethodNotAllowed, NotFound
from ZEO.Exceptions import ClientDisconnected
from ZODB.POSException import ConflictError, POSKeyError

from MaKaC.accessControl import AccessWrapper

from MaKaC.common import fossilize, security
from MaKaC.common.contextManager import ContextManager
from MaKaC.common.utils import truncate
from MaKaC.errors import (
    AccessError,
    BadRefererError,
    ConferenceClosedError,
    KeyAccessError,
    MaKaCError,
    ModificationError,
    NotLoggedError,
)
from MaKaC.plugins.base import OldObservable
from MaKaC.webinterface.mail import GenericMailer
import MaKaC.webinterface.urlHandlers as urlHandlers
import MaKaC.webinterface.pages.errors as errors
from MaKaC.webinterface.pages.error import WErrorWSGI
from MaKaC.webinterface.pages.conferences import WPConferenceModificationClosed
from indico.core.config import Config
from indico.core.db import DBMgr
from indico.core.logger import Logger
from indico.util import json
from indico.core.db.util import flush_after_commit_queue
from indico.util.decorators import jsonify_error
from indico.util.i18n import _, availableLocales, setLocale
from indico.util.redis import RedisError
from indico.web.flask.util import ResponseUtil


class RequestHandlerBase(OldObservable):

    _uh = None

    def __init__(self, req=None):
        if req is not None:
            raise Exception("Received request object")

    def _checkProtection(self):
        """This method is called after _checkParams and is a good place
        to check if the user is permitted to perform some actions.

        If you only want to run some code for GET or POST requests, you can create
        a method named e.g. _checkProtection_POST which will be executed AFTER this one.
        """
        pass

    def _getAuth(self):
        """
        Returns True if current user is a user or has either a modification key in their session.
        """
        return session.get('modifKeys') or self._getUser()

    def getAW(self):
        """
        Returns the access wrapper related to this session/user
        """
        return self._aw

    accessWrapper = property(getAW)

    def _getUser(self):
        """
        Returns the current user
        """
        return self._aw.getUser()

    def _setUser(self, new_user=None):
        """
        Sets the current user
        """
        self._aw.setUser(new_user)

    def getRequestURL(self, secure=False):
        """
        Reconstructs the request URL
        """
        if secure:
            return urljoin(Config.getInstance().getBaseSecureURL(), request.path)
        else:
            return request.url

    def use_https(self):
        """
        If the RH must be HTTPS and there is a BaseSecurURL, then use it!
        """
        return self._tohttps and Config.getInstance().getBaseSecureURL()

    def getRequestParams(self):
        return self._params

    def _setLang(self, params=None):

        # allow to choose the lang from params
        if params and 'lang' in params:
            newLang = params.get('lang', '')
            for lang in availableLocales:
                if newLang.lower() == lang.lower():
                    session.lang = lang
                    break

        lang = session.lang
        Logger.get('i18n').debug("lang:%s" % lang)
        if lang is None:
            lang = "en_GB"
        setLocale(lang)

    def _getTruncatedParams(self):
        """Truncates params"""
        params = {}
        for key, value in self._reqParams.iteritems():
            if key == 'password':
                params[key] = '[password hidden, len=%d]' % len(value)
            elif isinstance(value, basestring):
                params[key] = truncate(value, 1024)
            else:
                params[key] = value
        return params


class RH(RequestHandlerBase):
    """This class is the base for request handlers of the application. A request
        handler will be instantiated when a web request arrives to mod_python;
        the mp layer will forward the request to the corresponding request
        handler which will know which action has to be performed (displaying a
        web page or performing some operation and redirecting to another page).
        Request handlers will be responsible for parsing the parameters coming
        from a mod_python request, handle the errors which occurred during the
        action to perform, managing the sessions, checking security for each
        operation (thus they implement the access control system of the web
        interface).
        It is important to encapsulate all this here as in case of changing
        the web application framework we'll just need to adapt this layer (the
        rest of the system wouldn't need any change).

        Attributes:
            _uh - (URLHandler) Associated URLHandler which points to the
                current rh.
            _req - UNUSED/OBSOLETE, always None
            _requestStarted - (bool) Flag which tells whether a DB transaction
                has been started or not.
            _aw - (AccessWrapper) Current access information for the rh.
            _target - (Locable) Reference to an object which is the destination
                of the operations needed to carry out the rh. If set it must
                provide (through the standard Locable interface) the methods
                to get the url parameters in order to reproduce the access to
                the rh.
            _reqParams - (dict) Dictionary containing the received HTTP
                 parameters (independently of the method) transformed into
                 python data types. The key is the parameter name while the
                 value should be the received paramter value (or values).
    """
    _tohttps = False  # set this value to True for the RH that must be HTTPS when there is a BaseSecureURL
    _doNotSanitizeFields = []
    _isMobile = True  # this value means that the generated web page can be mobile

    HTTP_VERBS = frozenset(('GET', 'POST', 'PUT', 'DELETE'))

    def __init__(self, req=None):
        """Constructor. Initialises the rh setting up basic attributes so it is
            able to process the request.

            Parameters:
                req - OBSOLETE, MUST BE NONE
        """
        RequestHandlerBase.__init__(self, req)
        self._responseUtil = ResponseUtil()
        self._requestStarted = False
        self._aw = AccessWrapper()  # Fill in the aw instance with the current information
        self._target = None
        self._reqParams = {}
        self._startTime = None
        self._endTime = None
        self._tempFilesToDelete = []
        self._redisPipeline = None
        self._doProcess = True  # Flag which indicates whether the RH process
                                # must be carried out; this is useful for
                                # the checkProtection methods when they
                                # detect that an immediate redirection is
                                # needed

    # Methods =============================================================

    def getTarget(self):
        return self._target

    def isMobile(self):
        return self._isMobile

    def _setSessionUser(self):
        self._aw.setUser(session.user)

    @property
    def csrf_token(self):
        return session.csrf_token

    def _getRequestParams(self):
        return self._reqParams

    def getRequestParams(self):
        return self._getRequestParams()

    def _disableCaching(self):
        """Disables caching"""

        # IE doesn't seem to like 'no-cache' Cache-Control headers...
        if request.user_agent.browser == 'msie':
            # actually, the only way to safely disable caching seems to be this one
            self._responseUtil.headers["Cache-Control"] = "private"
            self._responseUtil.headers["Expires"] = "-1"
        else:
            self._responseUtil.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            self._responseUtil.headers["Pragma"] = "no-cache"

    def _redirect(self, targetURL, status=303):
        targetURL = str(targetURL)
        if "\r" in targetURL or "\n" in targetURL:
            raise MaKaCError(_("http header CRLF injection detected"))
        self._responseUtil.redirect = (targetURL, status)

    def _changeRH(self, rh, params):
        """Calls the specified RH after processing this one"""
        self._responseUtil.call = lambda: rh(None).process(params)

    def _checkHttpsRedirect(self):
        """If HTTPS must be used but it is not, redirect!"""
        if self.use_https() and not request.is_secure:
            self._redirect(self.getRequestURL(secure=True))
            return True
        else:
            return False

    def _normaliseListParam(self, param):
        if not isinstance(param, list):
            return [param]
        return param

    def _processError(self, e):
        raise

    def _checkParams(self, params):
        """This method is called before _checkProtection and is a good place
        to assign variables from request params to member variables.

        Note that in any new code the params argument SHOULD be IGNORED.
        Use the following objects provided by Flask instead:
        from flask import request
        request.view_args (URL route params)
        request.args (GET params (from the query string))
        request.form (POST params)
        request.values (GET+POST params - use only if ABSOLUTELY NECESSARY)

        If you only want to run some code for GET or POST requests, you can create
        a method named e.g. _checkParams_POST which will be executed AFTER this one.
        The method is called without any arguments (except self).
        """
        pass

    def _process(self):
        """The default process method dispatches to a method containing
        the HTTP verb used for the current request, e.g. _process_POST.
        When implementing this please consider that you most likely want/need
        only GET and POST - the other verbs are not supported everywhere!
        """
        method = getattr(self, '_process_' + request.method, None)
        if method is None:
            valid_methods = [m for m in self.HTTP_VERBS if hasattr(self, '_process_' + m)]
            raise MethodNotAllowed(valid_methods)
        return method()

    def _checkCSRF(self):
        # Check referer for POST requests. We do it here so we can properly use indico's error handling
        if Config.getInstance().getCSRFLevel() < 3 or request.method != 'POST':
            return
        referer = request.referrer
        # allow empty - otherwise we might lock out paranoid users blocking referers
        if not referer:
            return
        # valid http referer
        if referer.startswith(Config.getInstance().getBaseURL()):
            return
        # valid https referer - if https is enabled
        base_secure = Config.getInstance().getBaseSecureURL()
        if base_secure and referer.startswith(base_secure):
            return
        raise BadRefererError('This operation is not allowed from an external referer.')

    @jsonify_error
    def _processGeneralError(self, e):
        """Treats general errors occured during the process of a RH."""

        if Config.getInstance().getPropagateAllExceptions():
            raise
        return errors.WPGenericError(self).display()

    @jsonify_error(logging_level='exception')
    def _processUnexpectedError(self, e):
        """Unexpected errors"""

        self._responseUtil.redirect = None
        self._responseUtil.status = 500
        if Config.getInstance().getEmbeddedWebserver() or Config.getInstance().getPropagateAllExceptions():
            raise
        return errors.WPUnexpectedError(self).display()

    @jsonify_error
    def _processHostnameResolveError(self, e):
        """Unexpected errors"""

        return errors.WPHostnameResolveError(self).display()

    @jsonify_error
    def _processAccessError(self, e):
        """Treats access errors occured during the process of a RH."""

        self._responseUtil.status = 403
        return errors.WPAccessError(self).display()

    @jsonify_error
    def _processKeyAccessError(self, e):
        """Treats access errors occured during the process of a RH."""

        # We are going to redirect to the page asking for access key
        # and so it must be https if there is a BaseSecureURL. And that's
        # why we set _tohttps to True.
        self._tohttps = True
        if self._checkHttpsRedirect():
            return
        return errors.WPKeyAccessError(self).display()

    @jsonify_error
    def _processModificationError(self, e):
        """Handles modification errors occured during the process of a RH."""
        # Redirect to HTTPS in case the user is logged in
        self._tohttps = True
        if self._checkHttpsRedirect():
            return
        return errors.WPModificationError(self).display()

    @jsonify_error
    def _processBadRequestKeyError(self, e):
        """Request lacks a necessary key for processing"""
        msg = _('Required argument missing: %s') % e.message
        return errors.WPFormValuesError(self, msg).display()

    # TODO: check this method to integrate with jsonify error
    def _processOAuthError(self, e):
        res = json.dumps(e.fossilize())
        header = oauth.build_authenticate_header(realm=Config.getInstance().getBaseSecureURL())
        self._responseUtil.headers.extend(header)
        self._responseUtil.content_type = 'application/json'
        self._responseUtil.status = e.code
        return res

    @jsonify_error
    def _processConferenceClosedError(self, e):
        """Treats access to modification pages for conferences when they are closed."""

        return WPConferenceModificationClosed(self, e._conf).display()

    @jsonify_error
    def _processTimingError(self, e):
        """Treats timing errors occured during the process of a RH."""

        return errors.WPTimingError(self, e).display()

    @jsonify_error
    def _processNoReportError(self, e):
        """Process errors without reporting"""

        return errors.WPNoReportError(self, e).display()

    @jsonify_error
    def _processNotFoundError(self, e):
        self._responseUtil.status = 404
        return WErrorWSGI((e.getMessage(), e.getExplanation())).getHTML()

    @jsonify_error
    def _processParentTimingError(self, e):
        """Treats timing errors occured during the process of a RH."""

        return errors.WPParentTimingError(self, e).display()

    @jsonify_error
    def _processEntryTimingError(self, e):
        """Treats timing errors occured during the process of a RH."""

        return errors.WPEntryTimingError(self, e).display()

    @jsonify_error
    def _processFormValuesError(self, e):
        """Treats user input related errors occured during the process of a RH."""

        return errors.WPFormValuesError(self, e).display()

    @jsonify_error
    def _processLaTeXError(self, e):
        """Treats access errors occured during the process of a RH."""

        return errors.WPLaTeXError(self, e).display()

    @jsonify_error
    def _processRestrictedHTML(self, e):

        return errors.WPRestrictedHTML(self, escape(str(e))).display()

    @jsonify_error
    def _processHtmlScriptError(self, e):
        """ TODO """
        return errors.WPHtmlScriptError(self, escape(str(e))).display()

    @jsonify_error
    def _processHtmlForbiddenTag(self, e):
        """ TODO """

        return errors.WPRestrictedHTML(self, escape(str(e))).display()

    def _process_retry_setup(self):
        # clear the fossile cache at the start of each request
        fossilize.clearCache()
        # clear after-commit queue
        flush_after_commit_queue(False)
        # delete all queued emails
        GenericMailer.flushQueue(False)
        # clear the existing redis pipeline
        if self._redisPipeline:
            self._redisPipeline.reset()

    def _process_retry_auth_check(self, params):
        # keep a link to the web session in the access wrapper
        # this is used for checking access/modification key existence
        # in the user session
        self._aw.setIP(request.remote_addr)
        self._setSessionUser()
        self._setLang(params)
        if self._getAuth():
            if self._getUser():
                Logger.get('requestHandler').info('Request %s identified with user %s (%s)' % (
                    request, self._getUser().getFullName(), self._getUser().getId()))
            if not self._tohttps and Config.getInstance().getAuthenticatedEnforceSecure():
                self._tohttps = True
                if self._checkHttpsRedirect():
                    return self._responseUtil.make_redirect()

        self._checkCSRF()
        self._reqParams = copy.copy(params)


    def _process_retry_do(self, profile):
        profile_name, res = '', ''
        # old code gets parameters from call
        # new code utilizes of flask.request
        if len(inspect.getargspec(self._checkParams).args) < 2:
            self._checkParams()
        else:
            self._checkParams(self._reqParams)

        func = getattr(self, '_checkParams_' + request.method, None)
        if func:
            func()

        self._checkProtection()
        func = getattr(self, '_checkProtection_' + request.method, None)
        if func:
            func()

        security.Sanitization.sanitizationCheck(self._target,
                                                self._reqParams,
                                                self._aw,
                                                self._doNotSanitizeFields)

        if self._doProcess:
            if profile:
                profile_name = os.path.join(Config.getInstance().getTempDir(), 'stone{}.prof'.format(random.random()))
                result = [None]
                profiler.runctx('result[0] = self._process()', globals(), locals(), profile_name)
                res = result[0]
            else:
                res = self._process()
        return profile_name, res

    def _process_retry(self, params, retry, profile, forced_conflicts):
        self._process_retry_setup()
        self._process_retry_auth_check(params)
        DBMgr.getInstance().sync()
        return self._process_retry_do(profile)

    def _process_success(self):
        Logger.get('requestHandler').info('Request {} successful'.format(request))
        # request is succesfull, now, doing tasks that must be done only once
        try:
            flush_after_commit_queue(True)
            GenericMailer.flushQueue(True)  # send emails
            self._deleteTempFiles()
        except:
            Logger.get('mail').exception('Mail sending operation failed')
        # execute redis pipeline if we have one
        if self._redisPipeline:
            try:
                self._redisPipeline.execute()
            except RedisError:
                Logger.get('redis').exception('Could not execute pipeline')

    def process(self, params):
        if request.method not in self.HTTP_VERBS:
            # Just to be sure that we don't get some crappy http verb we don't expect
            raise BadRequest

        cfg = Config.getInstance()
        forced_conflicts, max_retries, profile = cfg.getForceConflicts(), cfg.getMaxRetries(), cfg.getProfile()
        profile_name, res, textLog = '', '', []

        self._startTime = datetime.now()

        # clear the context
        ContextManager.destroy()
        ContextManager.set('currentRH', self)

        #redirect to https if necessary
        if self._checkHttpsRedirect():
            return self._responseUtil.make_redirect()

        DBMgr.getInstance().startRequest()
        textLog.append("%s : Database request started" % (datetime.now() - self._startTime))
        Logger.get('requestHandler').info('[pid=%s] Request %s started' % (
            os.getpid(), request))
        self._notify('requestStarted')  # notify components about start

        try:
            for i, retry in enumerate(transaction.attempts(max_retries)):
                with retry:
                    if i > 0:
                        self._notify('requestRetry', i)  # notify components about retry

                    try:
                        Logger.get('requestHandler').info('\t[pid=%s] from host %s' % (os.getpid(), request.remote_addr))
                        if i < forced_conflicts:  # raise conflict error if enabled to easily handle conflict error case
                            raise ConflictError
                        profile_name, res = self._process_retry(params, i, profile, forced_conflicts)
                        transaction.commit()
                        break
                    except (ConflictError, POSKeyError):
                        transaction.abort()
                        import traceback
                        # only log conflict if it wasn't forced
                        if i >= forced_conflicts:
                            Logger.get('requestHandler').warning('Conflict in Database! (Request %s)\n%s' % (request, traceback.format_exc()))
                        raise
                    except ClientDisconnected:
                        transaction.abort()
                        Logger.get('requestHandler').warning('Client Disconnected! (Request {})'.format(request))
                        time.sleep(i)
            self._process_success()
        except Exception as e:
            transaction.abort()
            res = self._getMethodByExceptionName(e)(e)
        finally:
            # notify components that the request has finished
            self._notify('requestFinished')
            DBMgr.getInstance().endRequest()

        totalTime = (datetime.now() - self._startTime)
        textLog.append('{} : Request ended'.format(totalTime))

        # log request timing
        if profile and totalTime > timedelta(0, 1) and os.path.isfile(profile_name):
            rep = Config.getInstance().getTempDir()
            stats = pstats.Stats(profile_name)
            stats.strip_dirs()
            stats.sort_stats('cumulative', 'time', 'calls')
            stats.dump_stats(os.path.join(rep, 'IndicoRequestProfile.log'))
            output = StringIO.StringIO()
            sys.stdout = output
            stats.print_stats(100)
            sys.stdout = sys.__stdout__
            s = output.getvalue()
            f = file(os.path.join(rep, 'IndicoRequest.log'), 'a+')
            f.write('--------------------------------\n')
            f.write('URL     : {}\n'.format(request.url))
            f.write('{} : start request\n'.format(self._startTime))
            f.write('params:{}'.format(params))
            f.write('\n'.join(textLog))
            f.write('\n')
            f.write('retried : {}\n'.format(10-retry))
            f.write(s)
            f.write('--------------------------------\n\n')
            f.close()
        if profile and profile_name and os.path.exists(profile_name):
            os.remove(profile_name)

        if self._responseUtil.call:
            return self._responseUtil.make_call()

        # In case of no process needed, we should return empty string to avoid erroneous output
        # specially with getVars breaking the JS files.
        if not self._doProcess or res is None:
            return self._responseUtil.make_empty()

        return self._responseUtil.make_response(res)

    def _getMethodByExceptionName(self, e):
        exception_name = {
            'NotFound': 'NotFoundError',
            'MaKaCError': 'GeneralError',
            'IndicoError': 'GeneralError',
            'ValueError': 'UnexpectedError',
            'Exception': 'UnexpectedError',
            'AccessControlError': 'AccessError'
        }.get(type(e).__name__, type(e).__name__)
        return getattr(self, '_process{}'.format(exception_name), self._processUnexpectedError)

    def _deleteTempFiles(self):
        if len(self._tempFilesToDelete) > 0:
            for f in self._tempFilesToDelete:
                if f is not None:
                    os.remove(f)

    relativeURL = None


class RHProtected(RH):

    def _getLoginURL(self):
        return urlHandlers.UHSignIn.getURL(self.getRequestURL())

    def _checkSessionUser(self):
        if self._getUser() is None:
            if request.headers.get("Content-Type", "text/html").find("application/json") != -1:
                raise NotLoggedError("You are currently not authenticated. Please log in again.")
            else:
                self._redirect(self._getLoginURL())
                self._doProcess = False

    def _checkProtection(self):
        self._checkSessionUser()


class RHDisplayBaseProtected(RHProtected):

    def _checkProtection(self):
        if not self._target.canAccess( self.getAW() ):
            from MaKaC.conference import Link, LocalFile, Category
            if isinstance(self._target,Link) or isinstance(self._target,LocalFile):
                target = self._target.getOwner()
            else:
                target = self._target
            if not isinstance(self._target, Category) and target.isProtected():
                if target.getAccessKey() != "" or target.getConference() and \
                        target.getConference().getAccessKey() != "":
                    raise KeyAccessError()
                elif target.getModifKey() != "" or target.getConference() and \
                        target.getConference().getModifKey() != "":
                    raise ModificationError()
            if self._getUser() is None:
                self._checkSessionUser()
            else:
                raise AccessError()


class RHModificationBaseProtected(RHProtected):

    _allowClosed = False

    def _checkProtection(self):
        if not self._target.canModify( self.getAW() ):
            if self._target.getModifKey() != "":
                raise ModificationError()
            if self._getUser() is None:
                self._checkSessionUser()
            else:
                raise ModificationError()
        if hasattr(self._target, "getConference") and not self._allowClosed:
            if self._target.getConference().isClosed():
                raise ConferenceClosedError(self._target.getConference())
