# -*- coding: utf-8 -*-
##
##
## This file is part of Indico.
## Copyright (C) 2002 - 2013 European Organization for Nuclear Research (CERN).
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
## along with Indico. If not, see <http://www.gnu.org/licenses/>.

from MaKaC.webinterface.rh import admins, announcement, taskManager, maintenance, domains, users, groups, templates, \
    conferenceModif, collaboration, services, api, oauth
from indico.web.flask.util import rh_as_view
from indico.web.flask.wrappers import IndicoBlueprint


admin = IndicoBlueprint('admin', __name__, url_prefix='/admin')

# General settings
admin.add_url_rule('/', 'adminList', rh_as_view(admins.RHAdminArea))
admin.add_url_rule('/settings/general/cache', 'adminList-switchCacheActive',
                   rh_as_view(admins.RHAdminSwitchCacheActive))
admin.add_url_rule('/settings/general/debug', 'adminList-switchDebugActive',
                   rh_as_view(admins.RHAdminSwitchDebugActive))
admin.add_url_rule('/settings/general/news', 'adminList-switchNewsActive',
                   rh_as_view(admins.RHAdminSwitchNewsActive))
admin.add_url_rule('/settings/general/', 'generalInfoModification', rh_as_view(admins.RHGeneralInfoModification))
admin.add_url_rule('/settings/general/', 'generalInfoModification-update',
                   rh_as_view(admins.RHGeneralInfoPerformModification), methods=('POST',))

# System settings
admin.add_url_rule('/settings/system', 'adminSystem', rh_as_view(admins.RHSystem))
admin.add_url_rule('/settings/system/modify', 'adminSystem-modify', rh_as_view(admins.RHSystemModify),
                   methods=('GET', 'POST'))

# Announcement
admin.add_url_rule('/announcement', 'adminAnnouncement', rh_as_view(announcement.RHAnnouncementModif))
admin.add_url_rule('/announcement', 'adminAnnouncement-save', rh_as_view(announcement.RHAnnouncementModifSave),
                   methods=('POST',))

# News
admin.add_url_rule('/news', 'updateNews', rh_as_view(admins.RHUpdateNews))

# Upcoming events
admin.add_url_rule('/upcoming-events', 'adminUpcomingEvents', rh_as_view(admins.RHConfigUpcoming))

# Task manager
admin.add_url_rule('/tasks', 'taskManager', rh_as_view(taskManager.RHTaskManager))

# Maintenance
admin.add_url_rule('/maintenance/', 'adminMaintenance', rh_as_view(maintenance.RHMaintenance))
admin.add_url_rule('/maintenance/pack-db', 'adminMaintenance-pack', rh_as_view(maintenance.RHMaintenancePack),
                   methods=('GET', 'POST'))
admin.add_url_rule('/maintenance/pack-db/execute', 'adminMaintenance-performPack',
                   rh_as_view(maintenance.RHMaintenancePerformPack), methods=('POST',))
admin.add_url_rule('/maintenance/clean-tmp', 'adminMaintenance-tmpCleanup',
                   rh_as_view(maintenance.RHMaintenanceTmpCleanup), methods=('GET', 'POST'))
admin.add_url_rule('/maintenance/clean-tmp/execute', 'adminMaintenance-performTmpCleanup',
                   rh_as_view(maintenance.RHMaintenancePerformTmpCleanup), methods=('POST',))

# Protection
admin.add_url_rule('/protection/messages', 'adminProtection', rh_as_view(admins.RHAdminProtection))

# IP domains (let's call them "networks" in the URL - that's more fitting)
admin.add_url_rule('/networks/create', 'domainCreation', rh_as_view(domains.RHDomainCreation))
admin.add_url_rule('/networks/create', 'domainCreation-create', rh_as_view(domains.RHDomainPerformCreation),
                   methods=('POST',))
admin.add_url_rule('/networks/<domainId>/modify', 'domainDataModification', rh_as_view(domains.RHDomainModification))
admin.add_url_rule('/networks/<domainId>/modify', 'domainDataModification-modify',
                   rh_as_view(domains.RHDomainPerformModification), methods=('POST',))
admin.add_url_rule('/networks/<domainId>/details', 'domainDetails', rh_as_view(domains.RHDomainDetails))
admin.add_url_rule('/networks/', 'domainList', rh_as_view(domains.RHDomains), methods=('GET', 'POST'))

# Users
admin.add_url_rule('/settings/users/', 'userManagement', rh_as_view(users.RHUserManagement))
admin.add_url_rule('/settings/users/creation', 'userManagement-switchAuthorisedAccountCreation',
                   rh_as_view(users.RHUserManagementSwitchAuthorisedAccountCreation))
admin.add_url_rule('/settings/users/moderate-creation', 'userManagement-switchModerateAccountCreation',
                   rh_as_view(users.RHUserManagementSwitchModerateAccountCreation))
admin.add_url_rule('/settings/users/notify-creation', 'userManagement-switchNotifyAccountCreation',
                   rh_as_view(users.RHUserManagementSwitchNotifyAccountCreation))
admin.add_url_rule('/users/', 'userList', rh_as_view(users.RHUsers), methods=('GET', 'POST'))
admin.add_url_rule('/users/merge', 'userMerge', rh_as_view(admins.RHUserMerge), methods=('GET', 'POST'))

# Groups
admin.add_url_rule('/users/groups/', 'groupList', rh_as_view(groups.RHGroups), methods=('GET', 'POST'))
admin.add_url_rule('/users/groups/<groupId>', 'groupDetails', rh_as_view(groups.RHGroupDetails))
admin.add_url_rule('/users/groups/<groupId>/modify', 'groupModification', rh_as_view(groups.RHGroupModification))
admin.add_url_rule('/users/groups/<groupId>/modify', 'groupModification-update',
                   rh_as_view(groups.RHGroupPerformModification), methods=('POST',))
admin.add_url_rule('/users/groups/create', 'groupRegistration', rh_as_view(groups.RHGroupCreation))
admin.add_url_rule('/users/groups/create', 'groupRegistration-update',
                   rh_as_view(groups.RHGroupPerformCreation), methods=('POST',))

# Layout
admin.add_url_rule('/layout/', 'adminLayout', rh_as_view(admins.RHAdminLayoutGeneral), methods=('GET', 'POST'))
admin.add_url_rule('/layout/social', 'adminLayout-saveSocial', rh_as_view(admins.RHAdminLayoutSaveSocial),
                   methods=('POST',))
admin.add_url_rule('/layout/template-set', 'adminLayout-saveTemplateSet',
                   rh_as_view(admins.RHAdminLayoutSaveTemplateSet), methods=('POST',))
admin.add_url_rule('/layout/styles/timetable/', 'adminLayout-styles', rh_as_view(admins.RHStyles),
                   methods=('GET', 'POST'))
admin.add_url_rule('/layout/styles/timetable/create', 'adminLayout-addStyle', rh_as_view(admins.RHAddStyle),
                   methods=('GET', 'POST'))
admin.add_url_rule('/layout/styles/timetable/<templatefile>/delete', 'adminLayout-deleteStyle',
                   rh_as_view(admins.RHDeleteStyle))
admin.add_url_rule('/layout/styles/conference/', 'adminConferenceStyles', rh_as_view(admins.RHConferenceStyles))

# Badge templates
admin.add_url_rule('/layout/badges/', 'badgeTemplates', rh_as_view(templates.RHBadgeTemplates),
                   methods=('GET', 'POST'))
admin.add_url_rule('/layout/badges/save', 'badgeTemplates-badgePrinting',
                   rh_as_view(conferenceModif.RHConfBadgePrinting), methods=('GET', 'POST'))
admin.add_url_rule('/layout/badges/pdf-options', 'adminLayout-setDefaultPDFOptions',
                   rh_as_view(templates.RHSetDefaultPDFOptions), methods=('POST',))
admin.add_url_rule('/layout/badges/design', 'badgeTemplates-badgeDesign',
                   rh_as_view(templates.RHConfBadgeDesign), methods=('GET', 'POST'))

# Poster templates
admin.add_url_rule('/layout/posters/', 'posterTemplates', rh_as_view(templates.RHPosterTemplates),
                   methods=('GET', 'POST'))
admin.add_url_rule('/layout/posters/save', 'posterTemplates-posterPrinting',
                   rh_as_view(conferenceModif.RHConfPosterPrinting), methods=('GET', 'POST'))
admin.add_url_rule('/layout/posters/design', 'posterTemplates-posterDesign',
                   rh_as_view(templates.RHConfPosterDesign), methods=('GET', 'POST'))

# Collaboration
admin.add_url_rule('/collaboration', 'adminCollaboration', rh_as_view(collaboration.RHAdminCollaboration))

# IP ACL
admin.add_url_rule('/protection/ip-acl', 'adminServices-ipbasedacl', rh_as_view(services.RHIPBasedACL))
admin.add_url_rule('/protection/ip-acl/add', 'adminServices-ipbasedacl_fagrant',
                   rh_as_view(services.RHIPBasedACLFullAccessGrant), methods=('POST',))
admin.add_url_rule('/protection/ip-acl/remove', 'adminServices-ipbasedacl_farevoke',
                   rh_as_view(services.RHIPBasedACLFullAccessRevoke), methods=('POST',))

# HTTP API
admin.add_url_rule('/api/', 'adminServices-apiOptions', rh_as_view(api.RHAdminAPIOptions))
admin.add_url_rule('/api/', 'adminServices-apiOptionsSet', rh_as_view(api.RHAdminAPIOptionsSet), methods=('POST',))
admin.add_url_rule('/api/keys', 'adminServices-apiKeys', rh_as_view(api.RHAdminAPIKeys))

# OAuth
admin.add_url_rule('/oauth/consumers', 'adminServices-oauthAuthorized', rh_as_view(oauth.RHAdminOAuthAuthorized))
admin.add_url_rule('/oauth/authorized', 'adminServices-oauthConsumers', rh_as_view(oauth.RHAdminOAuthConsumers))

# Analytics
admin.add_url_rule('/analytics', 'adminServices-analytics', rh_as_view(services.RHAnalytics))
admin.add_url_rule('/analytics', 'adminServices-saveAnalytics', rh_as_view(services.RHSaveAnalytics), methods=('POST',))

# Webcast
admin.add_url_rule('/webcast/live', 'adminServices-webcast', rh_as_view(services.RHWebcast), methods=('GET', 'POST'))
admin.add_url_rule('/webcast/setup/', 'adminServices-webcastSetup', rh_as_view(services.RHWebcastSetup))
admin.add_url_rule('/webcast/setup/sync/set-url', 'adminServices-webcastSaveWebcastSynchronizationURL',
                   rh_as_view(services.RHWebcastSaveWebcastSynchronizationURL), methods=('POST',))
admin.add_url_rule('/webcast/setup/sync', 'adminServices-webcastManualSynchronization',
                   rh_as_view(services.RHWebcastManuelSynchronizationURL), methods=('POST',))
admin.add_url_rule('/webcast/setup/stream/add', 'adminServices-webcastAddStream',
                   rh_as_view(services.RHWebcastAddStream), methods=('POST',))
admin.add_url_rule('/webcast/setup/stream/remove', 'adminServices-webcastRemoveStream',
                   rh_as_view(services.RHWebcastRemoveStream))
admin.add_url_rule('/webcast/setup/channel/move/down', 'adminServices-webcastMoveChannelDown',
                   rh_as_view(services.RHWebcastMoveChannelDown))
admin.add_url_rule('/webcast/setup/channel/move/up', 'adminServices-webcastMoveChannelUp',
                   rh_as_view(services.RHWebcastMoveChannelUp))
admin.add_url_rule('/webcast/setup/channel/remove', 'adminServices-webcastRemoveChannel',
                   rh_as_view(services.RHWebcastRemoveChannel))
admin.add_url_rule('/webcast/setup/channel/modify', 'adminServices-webcastModifyChannel',
                   rh_as_view(services.RHWebcastModifyChannel), methods=('POST',))
admin.add_url_rule('/webcast/setup/channel/add', 'adminServices-webcastAddChannel',
                   rh_as_view(services.RHWebcastAddChannel), methods=('POST',))
admin.add_url_rule('/webcast/archive/', 'adminServices-webcastArchive', rh_as_view(services.RHWebcastArchive))
admin.add_url_rule('/webcast/<webcastid>/archive', 'adminServices-webcastArchiveWebcast',
                   rh_as_view(services.RHWebcastArchiveWebcast))
admin.add_url_rule('/webcast/<webcastid>/unarchive', 'adminServices-webcastUnArchiveWebcast',
                   rh_as_view(services.RHWebcastUnArchiveWebcast))
admin.add_url_rule('/webcast/<webcastid>/remove', 'adminServices-webcastRemoveWebcast', rh_as_view(services.RHWebcastRemoveWebcast))
admin.add_url_rule('/webcast/add', 'adminServices-webcastAddWebcast', rh_as_view(services.RHWebcastAddWebcast),
                   methods=('POST',))
admin.add_url_rule('/webcast/onair/add', 'adminServices-webcastAddOnAir', rh_as_view(services.RHWebcastAddOnAir))
admin.add_url_rule('/webcast/onair/remove', 'adminServices-webcastRemoveFromAir',
                   rh_as_view(services.RHWebcastRemoveFromAir))
admin.add_url_rule('/webcast/channel/switch', 'adminServices-webcastSwitchChannel',
                   rh_as_view(services.RHWebcastSwitchChannel))

# Plugins
admin.add_url_rule('/plugins/', 'adminPlugins', rh_as_view(admins.RHAdminPlugins), methods=('GET', 'POST'))
admin.add_url_rule('/settings/plugins/reload-all', 'adminPlugins-saveOptionReloadAll',
                   rh_as_view(admins.RHAdminPluginsSaveOptionReloadAll), methods=('POST',))
admin.add_url_rule('/plugins/reload-all', 'adminPlugins-reloadAll', rh_as_view(admins.RHAdminPluginsReloadAll),
                   methods=('POST',))
admin.add_url_rule('/plugins/clear-all-info', 'adminPlugins-clearAllInfo',
                   rh_as_view(admins.RHAdminPluginsClearAllInfo), methods=('POST',))
admin.add_url_rule('/plugins/type/<pluginType>/', 'adminPlugins', rh_as_view(admins.RHAdminPlugins),
                   methods=('GET', 'POST'))
admin.add_url_rule('/plugins/type/<pluginType>/reload', 'adminPlugins-reload',
                   rh_as_view(admins.RHAdminPluginsReload), methods=('POST',))
admin.add_url_rule('/plugins/type/<pluginType>/toggle', 'adminPlugins-toggleActivePluginType',
                   rh_as_view(admins.RHAdminTogglePluginType))
admin.add_url_rule('/plugins/type/<pluginType>/save-options', 'adminPlugins-savePluginTypeOptions',
                   rh_as_view(admins.RHAdminPluginsSaveTypeOptions), methods=('POST',))
admin.add_url_rule('/plugins/plugin/<pluginType>/<pluginId>/toggle', 'adminPlugins-toggleActive',
                   rh_as_view(admins.RHAdminTogglePlugin))
admin.add_url_rule('/plugins/plugin/<pluginType>/<pluginId>/save-options', 'adminPlugins-savePluginOptions',
                   rh_as_view(admins.RHAdminPluginsSaveOptions), methods=('POST',))