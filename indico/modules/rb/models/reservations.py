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
## along with Indico; if not, see <http://www.gnu.org/licenses/>.

from collections import defaultdict, OrderedDict
from datetime import datetime

from sqlalchemy import Date, Time
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import cast
from werkzeug.datastructures import OrderedMultiDict

from indico.core.db import db
from indico.core.db.sqlalchemy.custom import static_array
from indico.core.db.sqlalchemy.custom.utcdatetime import UTCDateTime
from indico.core.errors import NoReportError
from indico.modules.rb.models.reservation_edit_logs import ReservationEditLog
from indico.modules.rb.models.reservation_occurrences import ReservationOccurrence
from indico.modules.rb.models.room_nonbookable_periods import NonBookablePeriod
from indico.modules.rb.models.equipment import (ReservationEquipmentAssociation, EquipmentType,
                                                RoomEquipmentAssociation)
from indico.modules.rb.models.utils import limit_groups, unimplemented, Serializer
from indico.modules.rb.notifications.reservations import (notify_confirmation, notify_cancellation,
                                                          notify_creation, notify_modification,
                                                          notify_rejection)
from indico.util.date_time import now_utc, format_date, format_time
from indico.util.i18n import _, N_
from indico.util.string import return_ascii
from indico.util.struct.enum import IndicoEnum
from indico.web.flask.util import url_for
from MaKaC.common.Locators import Locator
from MaKaC.user import AvatarHolder


class ConflictingOccurrences(Exception):
    pass


class RepeatFrequency(int, IndicoEnum):
    NEVER = 0
    DAY = 1
    WEEK = 2
    MONTH = 3
    YEAR = 4


class RepeatMapping(object):
    _mapping = {
        (RepeatFrequency.NEVER, 0): (N_('Single reservation'), None, 'none'),
        (RepeatFrequency.DAY, 1): (N_('Repeat daily'), 0, 'daily'),
        (RepeatFrequency.WEEK, 1): (N_('Repeat once a week'), 1, 'weekly'),
        (RepeatFrequency.WEEK, 2): (N_('Repeat once every two week'), 2, 'everyTwoWeeks'),
        (RepeatFrequency.WEEK, 3): (N_('Repeat once every three week'), 3, 'everyThreeWeeks'),
        (RepeatFrequency.MONTH, 1): (N_('Repeat every month'), 4, 'monthly')
    }

    @classmethod
    @unimplemented(exceptions=(KeyError,), message=_('Unimplemented repetition pair'))
    def getMessage(cls, repeat_frequency, repeat_interval):
        return cls._mapping[(repeat_frequency, repeat_interval)][0]

    @classmethod
    @unimplemented(exceptions=(KeyError,), message=_('Unimplemented repetition pair'))
    def getOldMapping(cls, repeat_frequency, repeat_interval):
        return cls._mapping[(repeat_frequency, repeat_interval)][1]

    @classmethod
    @unimplemented(exceptions=(KeyError,), message=_('Unimplemented repetition pair'))
    def get_short_name(cls, repeat_frequency, repeat_interval):
        # for the API
        return cls._mapping[(repeat_frequency, repeat_interval)][2]

    @classmethod
    @unimplemented(exceptions=(KeyError,), message=_('Unknown old repeatability'))
    def getNewMapping(cls, repeat):
        if repeat is None or repeat < 5:
            for k, (_, v, _) in cls._mapping.iteritems():
                if v == repeat:
                    return k
        else:
            raise KeyError('Undefined old repeat: {}'.format(repeat))

    @classmethod
    def getMapping(cls):
        return cls._mapping


class Reservation(Serializer, db.Model):
    __tablename__ = 'reservations'
    __public__ = []
    __calendar_public__ = [
        'id', ('booked_for_name', 'bookedForName'), ('booking_reason', 'reason'), ('details_url', 'bookingUrl')
    ]
    __api_public__ = [
        'id', ('start_dt', 'startDT'), ('end_dt', 'endDT'), 'repeat_frequency', 'repeat_interval',
        ('booked_for_name', 'bookedForName'), ('details_url', 'bookingUrl'), ('booking_reason', 'reason'),
        ('uses_vc', 'usesAVC'), ('needs_vc_assistance', 'needsAVCSupport'),
        'needs_assistance', ('is_accepted', 'isConfirmed'), ('is_valid', 'isValid'), 'is_cancelled',
        'is_rejected', ('location_name', 'location')
    ]

    @declared_attr
    def __table_args__(cls):
        return (db.Index('ix_reservations_start_dt_date', cast(cls.start_dt, Date)),
                db.Index('ix_reservations_end_dt_date', cast(cls.end_dt, Date)),
                db.Index('ix_reservations_start_dt_time', cast(cls.start_dt, Time)),
                db.Index('ix_reservations_end_dt_time', cast(cls.end_dt, Time)),
                {'schema': 'roombooking'})

    id = db.Column(
        db.Integer,
        primary_key=True
    )
    created_dt = db.Column(
        UTCDateTime,
        nullable=False,
        default=now_utc
    )
    start_dt = db.Column(
        db.DateTime,
        nullable=False,
        index=True
    )
    end_dt = db.Column(
        db.DateTime,
        nullable=False,
        index=True
    )
    repeat_frequency = db.Column(
        db.SmallInteger,
        nullable=False,
        default=RepeatFrequency.NEVER
    )  # week, month, year, etc.
    repeat_interval = db.Column(
        db.SmallInteger,
        nullable=False,
        default=0
    )  # 1, 2, 3, etc.
    booked_for_id = db.Column(
        db.String
        # Must be nullable for legacy data :(
    )
    booked_for_name = db.Column(
        db.String,
        nullable=False
    )
    created_by_id = db.Column(
        db.String
        # Must be nullable for legacy data :(
    )
    room_id = db.Column(
        db.Integer,
        db.ForeignKey('roombooking.rooms.id'),
        nullable=False,
        index=True
    )
    contact_email = db.Column(
        db.String,
        nullable=False
    )
    contact_phone = db.Column(
        db.String,
        nullable=False
    )
    is_accepted = db.Column(
        db.Boolean,
        nullable=False
    )
    is_cancelled = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )
    is_rejected = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )
    booking_reason = db.Column(
        db.Text,
        nullable=False
    )
    rejection_reason = db.Column(
        db.String
    )
    uses_vc = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )
    needs_vc_assistance = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )
    needs_assistance = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )
    event_id = db.Column(
        db.Integer,
        index=True
    )

    edit_logs = db.relationship(
        'ReservationEditLog',
        backref='reservation',
        cascade='all, delete-orphan',
        lazy='dynamic'
    )
    occurrences = db.relationship(
        'ReservationOccurrence',
        backref='reservation',
        cascade='all, delete-orphan',
        lazy='dynamic'
    )
    used_equipment = db.relationship(
        'EquipmentType',
        secondary=ReservationEquipmentAssociation,
        backref='reservations',
        lazy='dynamic'
    )

    @hybrid_property
    def is_archived(self):
        return self.end_dt < datetime.now()

    @hybrid_property
    def is_repeating(self):
        return self.repeat_frequency != RepeatFrequency.NEVER

    @hybrid_property
    def is_valid(self):
        return self.is_accepted and not (self.is_rejected or self.is_cancelled)

    @is_valid.expression
    def is_valid(self):
        return self.is_accepted & ~(self.is_rejected | self.is_cancelled)

    @return_ascii
    def __repr__(self):
        return u'<Reservation({0}, {1}, {2}, {3}, {4})>'.format(
            self.id,
            self.room_id,
            self.booked_for_name,
            self.start_dt,
            self.end_dt
        )

    @hybrid_property
    def is_pending(self):
        return not (self.is_accepted or self.is_rejected or self.is_cancelled)

    @is_pending.expression
    def is_pending(self):
        return ~(Reservation.is_accepted | Reservation.is_rejected | Reservation.is_cancelled)

    @property
    def location_name(self):
        return self.room.location_name

    @property
    def repetition(self):
        return self.repeat_frequency, self.repeat_interval

    @property
    def details_url(self):
        return url_for('rooms.roomBooking-bookingDetails', self, _external=True)

    @property
    def status_string(self):
        parts = []
        if self.is_valid:
            parts.append(_("Valid"))
        else:
            if self.is_cancelled:
                parts.append(_("Cancelled"))
            if self.is_rejected:
                parts.append(_("Rejected"))
            if not self.is_accepted:
                parts.append(_("Not confirmed"))
        if self.is_archived:
            parts.append(_("Archived"))
        else:
            parts.append(_("Live"))
        return ', '.join(parts)

    @property
    def event(self):
        from MaKaC.conference import ConferenceHolder

        return ConferenceHolder().getById(str(self.event_id))

    @event.setter
    def event(self, event):
        self.event_id = int(event.getId())

    def get_vc_equipment(self):
        vc_equipment = self.room.available_equipment \
                           .correlate(ReservationOccurrence) \
                           .with_entities(EquipmentType.id) \
                           .filter_by(name='Video conference') \
                           .as_scalar()
        return self.used_equipment.filter(EquipmentType.parent_id == vc_equipment)

    @staticmethod
    def get_with_data(*args, **kwargs):
        filters = kwargs.pop('filters', None)
        limit = kwargs.pop('limit', None)
        offset = kwargs.pop('offset', 0)
        order = kwargs.pop('order', Reservation.start_dt)
        limit_per_room = kwargs.pop('limit_per_room', False)
        if kwargs:
            raise ValueError('Unexpected kwargs: {}'.format(kwargs))

        query = Reservation.query.options(joinedload(Reservation.room))
        if filters:
            query = query.filter(*filters)
        if limit_per_room and (limit or offset):
            query = limit_groups(query, Reservation, Reservation.room_id, order, limit, offset)

        query = query.order_by(order, Reservation.created_dt)

        if not limit_per_room:
            if limit:
                query = query.limit(limit)
            if offset:
                query = query.offset(offset)

        result = OrderedDict((r.id, {'reservation': r}) for r in query)

        if 'vc_equipment' in args:
            vc_id_subquery = db.session.query(EquipmentType.id) \
                .correlate(Reservation) \
                .filter_by(name='Video conference') \
                .join(RoomEquipmentAssociation) \
                .filter(RoomEquipmentAssociation.c.room_id == Reservation.room_id) \
                .as_scalar()

            # noinspection PyTypeChecker
            vc_equipment_data = dict(db.session.query(Reservation.id, static_array.array_agg(EquipmentType.name))
                                     .join(ReservationEquipmentAssociation, EquipmentType)
                                     .filter(Reservation.id.in_(result.iterkeys()))
                                     .filter(EquipmentType.parent_id == vc_id_subquery)
                                     .group_by(Reservation.id))

            for id_, data in result.iteritems():
                data['vc_equipment'] = vc_equipment_data.get(id_, ())

        if 'occurrences' in args:
            occurrence_data = OrderedMultiDict(db.session.query(ReservationOccurrence.reservation_id,
                                                                ReservationOccurrence)
                                               .filter(ReservationOccurrence.reservation_id.in_(result.iterkeys()))
                                               .order_by(ReservationOccurrence.start_dt))
            for id_, data in result.iteritems():
                data['occurrences'] = occurrence_data.getlist(id_)

        return result.values()

    @property
    def created_by_user(self):
        return AvatarHolder().getById(self.created_by_id) if self.created_by_id else None

    @created_by_user.setter
    def created_by_user(self, user):
        self.created_by_id = user.getId() if user else None

    @property
    def booked_for_user(self):
        return AvatarHolder().getById(self.booked_for_id) if self.booked_for_id else None

    @booked_for_user.setter
    def booked_for_user(self, user):
        self.booked_for_id = user.getId() if user else None

    @property
    def contact_emails(self):
        return set(filter(None, map(unicode.strip, self.contact_email.split(u','))))

    def accept(self, user):
        self.is_accepted = True
        self.add_edit_log(ReservationEditLog(user_name=user.getFullName(), info=['Reservation accepted']))
        notify_confirmation(self)

        valid_occurrences = self.occurrences.filter(ReservationOccurrence.is_valid).all()
        pre_occurrences = ReservationOccurrence.find_overlapping_with(self.room, valid_occurrences, self.id).all()
        for occurrence in pre_occurrences:
            if not occurrence.is_valid:
                continue
            occurrence.reject(u'Rejected due to collision with a confirmed reservation')

    def cancel(self, user, reason=None, silent=False):
        self.is_cancelled = True
        self.rejection_reason = reason
        self.occurrences.filter_by(is_valid=True).update({'is_cancelled': True}, synchronize_session='fetch')
        if not silent:
            notify_cancellation(self)
            log_msg = u'Reservation cancelled: {}'.format(reason) if reason else 'Reservation cancelled'
            self.add_edit_log(ReservationEditLog(user_name=user.getFullName(), info=[log_msg]))

    def reject(self, user, reason, silent=False):
        self.is_rejected = True
        self.rejection_reason = reason
        self.occurrences.filter_by(is_valid=True).update({'is_rejected': True, 'rejection_reason': reason},
                                                         synchronize_session='fetch')
        if not silent:
            notify_rejection(self)
            log_msg = u'Reservation rejected: {}'.format(reason)
            self.add_edit_log(ReservationEditLog(user_name=user.getFullName(), info=[log_msg]))

    def add_edit_log(self, edit_log):
        self.edit_logs.append(edit_log)

    def find_excluded_days(self):
        return self.occurrences.filter(~ReservationOccurrence.is_valid)

    @staticmethod
    def find_overlapping_with(room, occurrences, reservation_id=None):
        return Reservation.find(Reservation.room == room,
                                Reservation.id != reservation_id,
                                ReservationOccurrence.is_valid,
                                ReservationOccurrence.filter_overlap(occurrences),
                                _join=ReservationOccurrence)

    def find_overlapping(self):
        occurrences = self.occurrences.filter(ReservationOccurrence.is_valid).all()
        return Reservation.find_overlapping_with(self.room, occurrences, self.id)

    def get_conflicting_occurrences(self):
        valid_occurrences = self.occurrences.filter(ReservationOccurrence.is_valid).all()
        colliding_occurrences = ReservationOccurrence.find_overlapping_with(self.room, valid_occurrences, self.id).all()
        conflicts = defaultdict(lambda: dict(confirmed=[], pending=[]))
        for occurrence in valid_occurrences:
            for colliding in colliding_occurrences:
                if occurrence.overlaps(colliding):
                    key = 'confirmed' if colliding.reservation.is_accepted else 'pending'
                    conflicts[occurrence][key].append(colliding)
        return conflicts

    def create_occurrences(self, skip_conflicts, user):
        ReservationOccurrence.create_series_for_reservation(self)
        db.session.flush()

        # Check for conflicts with nonbookable periods
        if not user.isRBAdmin():
            nonbookable_periods = self.room.nonbookable_periods.filter(NonBookablePeriod.end_dt > self.start_dt)
            for occurrence in self.occurrences:
                if not occurrence.is_valid:
                    continue
                for nbd in nonbookable_periods:
                    if nbd.overlaps(occurrence.start_dt, occurrence.end_dt):
                        if not skip_conflicts:
                            raise ConflictingOccurrences()
                        occurrence.cancel(user, u'Skipped due to nonbookable date', silent=True, propagate=False)
                        break

        # Check for conflicts with blockings
        blocked_rooms = self.room.get_blocked_rooms(*(occurrence.start_dt for occurrence in self.occurrences))
        for br in blocked_rooms:
            blocking = br.blocking
            if blocking.can_be_overridden(user, self.room):
                continue
            for occurrence in self.occurrences:
                if occurrence.is_valid and blocking.is_active_at(occurrence.start_dt.date()):
                    # Cancel OUR occurrence
                    msg = u'Skipped due to collision with a blocking ({})'
                    occurrence.cancel(user, msg.format(blocking.reason), silent=True, propagate=False)

        # Check for conflicts with other occurrences
        conflicting_occurrences = self.get_conflicting_occurrences()
        for occurrence, conflicts in conflicting_occurrences.iteritems():
            if not occurrence.is_valid:
                continue
            if conflicts['confirmed']:
                if not skip_conflicts:
                    raise ConflictingOccurrences()
                # Cancel OUR occurrence
                msg = u'Skipped due to collision with {} reservation(s)'
                occurrence.cancel(user, msg.format(len(conflicts['confirmed'])), silent=True, propagate=False)
            elif conflicts['pending'] and self.is_accepted:
                # Reject OTHER occurrences
                for conflict in conflicts['pending']:
                    conflict.reject(user, u'Rejected due to collision with a confirmed reservation')

    @classmethod
    def create_from_data(cls, room, data, user, prebook=None):
        """Creates a new reservation.

        :param room: The Room that's being booked.
        :param data: A dict containing the booking data, usually from a :class:`NewBookingConfirmForm` instance
        :param user: The :class:`Avatar` who creates the booking.
        :param prebook: Instead of determining the booking type from the user's
                        permissions, always use the given mode.
        """

        populate_fields = ('start_dt', 'end_dt', 'repeat_frequency', 'repeat_interval', 'room_id', 'booked_for_id',
                           'contact_email', 'contact_phone', 'booking_reason', 'used_equipment',
                           'needs_assistance', 'uses_vc', 'needs_vc_assistance')

        if data['repeat_frequency'] == RepeatFrequency.NEVER and data['start_dt'].date() != data['end_dt'].date():
            raise ValueError('end_dt != start_dt for non-repeating booking')

        if prebook is None:
            prebook = not room.can_be_booked(user)
            if prebook and not room.can_be_prebooked(user):
                raise NoReportError('You cannot book this room')

        room.check_advance_days(data['end_dt'].date(), user)
        room.check_bookable_hours(data['start_dt'].time(), data['end_dt'].time(), user)

        reservation = cls()
        for field in populate_fields:
            if field in data:
                setattr(reservation, field, data[field])
        reservation.room = room
        reservation.booked_for_name = reservation.booked_for_user.getFullName()
        reservation.is_accepted = not prebook
        reservation.created_by_user = user
        reservation.create_occurrences(True, user)
        if not any(occ.is_valid for occ in reservation.occurrences):
            raise NoReportError(_('Reservation has no valid occurrences'))
        notify_creation(reservation)
        return reservation

    def modify(self, data, user):
        """Modifies an existing reservation.

        :param data: A dict containing the booking data, usually from a :class:`ModifyBookingForm` instance
        :param user: The :class:`Avatar` who modifies the booking.
        """

        populate_fields = ('start_dt', 'end_dt', 'repeat_frequency', 'repeat_interval', 'booked_for_id',
                           'contact_email', 'contact_phone', 'booking_reason', 'used_equipment',
                           'needs_assistance', 'uses_vc', 'needs_vc_assistance')
        # fields affecting occurrences
        occurrence_fields = {'start_dt', 'end_dt', 'repeat_frequency', 'repeat_interval'}
        # fields where date and time are compared separately
        date_time_fields = {'start_dt', 'end_dt'}
        # fields for the repetition
        repetition_fields = {'repeat_frequency', 'repeat_interval'}
        # pretty names for logging
        field_names = {
            'start_dt/date': "start date",
            'end_dt/date': "end date",
            'start_dt/time': "start time",
            'end_dt/time': "end time",
            'repetition': "booking type",
            'booked_for_id': "'Booked for' user",
            'contact_email': "contact email",
            'contact_phone': "contact phone number",
            'booking_reason': "booking reason",
            'used_equipment': "list of equipment",
            'needs_assistance': "option 'General Assistance'",
            'uses_vc': "option 'Uses Video Conference'",
            'needs_vc_assistance': "option 'Video Conference Setup Assistance'"
        }

        self.room.check_advance_days(data['end_dt'].date(), user)
        self.room.check_bookable_hours(data['start_dt'].time(), data['end_dt'].time(), user)

        changes = {}
        update_occurrences = False
        old_repetition = self.repetition

        for field in populate_fields:
            old = getattr(self, field)
            new = data[field]
            converter = unicode
            if field == 'used_equipment':
                # Dynamic relationship
                old = sorted(old.all())
                converter = lambda x: ', '.join(x.name for x in x)
            if old != new:
                # Apply the change
                setattr(self, field, data[field])
                # Booked for id updates also update the (redundant) name
                if field == 'booked_for_id':
                    old = self.booked_for_name
                    new = self.booked_for_name = self.booked_for_user.getFullName()
                # If any occurrence-related field changed we need to recreate the occurrences
                if field in occurrence_fields:
                    update_occurrences = True
                # Record change for history entry
                if field in date_time_fields:
                    # The date/time fields create separate entries for the date and time parts
                    if old.date() != new.date():
                        changes[field + '/date'] = {'old': old.date(), 'new': new.date(), 'converter': format_date}
                    if old.time() != new.time():
                        changes[field + '/time'] = {'old': old.time(), 'new': new.time(), 'converter': format_time}
                elif field in repetition_fields:
                    # Repetition needs special handling since it consists of two fields but they are tied together
                    # We simply update it whenever we encounter such a change; after the last change we end up with
                    # the correct change data
                    changes['repetition'] = {'old': old_repetition,
                                             'new': self.repetition,
                                             'converter': lambda x: RepeatMapping.getMessage(*x)}
                else:
                    changes[field] = {'old': old, 'new': new, 'converter': converter}

        if not changes:
            return False

        # Create a verbose log entry for the modification
        log = ['Booking modified']
        for field, change in changes.iteritems():
            field_title = field_names.get(field, field)
            converter = change['converter']
            old = converter(change['old'])
            new = converter(change['new'])
            if not old:
                log.append(u"The {} was set to '{}'".format(field_title, new))
            elif not new:
                log.append(u"The {} was cleared".format(field_title))
            else:
                log.append(u"The {} was changed from '{}' to '{}'".format(field_title, old, new))

        self.edit_logs.append(ReservationEditLog(user_name=user.getFullName(), info=log))

        # Recreate all occurrences if necessary
        if update_occurrences:
            cols = [col.name for col in ReservationOccurrence.__table__.columns
                    if not col.primary_key and col.name not in {'start_dt', 'end_dt'}]

            old_occurrences = {occ.date: occ for occ in self.occurrences}
            self.occurrences.delete(synchronize_session='fetch')
            self.create_occurrences(True, user)
            db.session.flush()
            # Restore rejection data etc. for recreated occurrences
            for occurrence in self.occurrences:
                old_occurrence = old_occurrences.get(occurrence.date)
                # Copy data from old occurrence UNLESS the new one is invalid (e.g. because of collisions)
                # Otherwise we'd end up with valid occurrences ignoring collisions!
                if old_occurrence and occurrence.is_valid:
                    for col in cols:
                        setattr(occurrence, col, getattr(old_occurrence, col))
            # Don't cause new notifications for the entire booking in case of daily repetition
            if self.repeat_frequency == RepeatFrequency.DAY and all(occ.notification_sent
                                                                    for occ in old_occurrences.itervalues()):
                for occurrence in self.occurrences:
                    occurrence.notification_sent = True

        # Sanity check so we don't end up with an "empty" booking
        if not any(occ.is_valid for occ in self.occurrences):
            raise NoReportError(_('Reservation has no valid occurrences'))

        notify_modification(self, changes)
        return True

    def getLocator(self):
        locator = Locator()
        locator['roomLocation'] = self.location_name
        locator['resvID'] = self.id
        return locator

    def can_be_modified(self, user):
        if not user:
            return False
        if self.is_rejected or self.is_cancelled:
            return False
        if user.isRBAdmin():
            return True
        return self.created_by_user == user or self.is_booked_for(user) or self.room.is_owned_by(user)

    def can_be_cancelled(self, user):
        return user and (self.is_owned_by(user) or user.isRBAdmin() or self.is_booked_for(user))

    def can_be_accepted(self, user):
        return user and (user.isRBAdmin() or self.room.is_owned_by(user))

    def can_be_rejected(self, user):
        return user and (user.isRBAdmin() or self.room.is_owned_by(user))

    def can_be_deleted(self, user):
        return user and user.isRBAdmin()

    def is_owned_by(self, avatar):
        return self.created_by_id == avatar.id

    def is_booked_for(self, user):
        return user and (self.booked_for_user == user or self.contact_email in user.getEmails())
