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

import ast
import json
from datetime import date

from sqlalchemy import and_, func, or_, cast
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import joinedload

from MaKaC.webinterface import urlHandlers as UH
from MaKaC.accessControl import AccessWrapper
from MaKaC.common.Locators import Locator
from MaKaC.common.cache import GenericCache
from MaKaC.errors import MaKaCError
from MaKaC.user import Avatar, AvatarHolder
from indico.core.db.sqlalchemy import db
from indico.core.db.sqlalchemy.custom import static_array
from indico.core.errors import IndicoError
from indico.modules.rb.utils import rb_check_user_access
from indico.modules.rb.models.blockings import Blocking
from indico.modules.rb.models.blocked_rooms import BlockedRoom
from indico.modules.rb.models.reservation_occurrences import ReservationOccurrence
from indico.modules.rb.models.reservations import Reservation, RepeatMapping
from indico.modules.rb.models.room_attributes import RoomAttribute, RoomAttributeAssociation
from indico.modules.rb.models.room_bookable_hours import BookableHours
from indico.modules.rb.models.equipment import EquipmentType, RoomEquipmentAssociation
from indico.modules.rb.models.room_nonbookable_periods import NonBookablePeriod
from indico.modules.rb.models.utils import Serializer, cached, versioned_cache
from indico.util.decorators import classproperty
from indico.util.i18n import _
from indico.util.string import return_ascii, natural_sort_key
from indico.web.flask.util import url_for


_cache = GenericCache('Rooms')


class Room(versioned_cache(_cache, 'id'), db.Model, Serializer):
    __tablename__ = 'rooms'
    __table_args__ = {'schema': 'roombooking'}

    __public__ = [
        'id', 'name', 'location_name', 'floor', 'number', 'building',
        'booking_url', 'capacity', 'comments', 'owner_id', 'details_url',
        'large_photo_url', 'small_photo_url', 'has_photo', 'is_active',
        'is_reservable', 'is_auto_confirm', 'marker_description', 'kind'
    ]

    __public_exhaustive__ = __public__ + [
        'has_webcast_recording', 'has_vc', 'has_projector', 'is_public', 'has_booking_groups'
    ]

    __calendar_public__ = [
        'id', 'building', 'name', 'floor', 'number', 'kind', 'booking_url', 'details_url', 'location_name'
    ]

    __api_public__ = (
        'id', 'building', 'name', 'floor', 'longitude', 'latitude', ('number', 'roomNr'), ('location_name', 'location'),
        ('full_name', 'fullName'), ('booking_url', 'bookingUrl')
    )

    __api_minimal_public__ = (
        'id', ('full_name', 'fullName')
    )

    id = db.Column(
        db.Integer,
        primary_key=True
    )
    location_id = db.Column(
        db.Integer,
        db.ForeignKey('roombooking.locations.id'),
        nullable=False
    )
    photo_id = db.Column(
        db.Integer,
        db.ForeignKey('roombooking.photos.id')
    )
    name = db.Column(
        db.String,
        nullable=False
    )
    site = db.Column(
        db.String,
        default=''
    )
    division = db.Column(
        db.String
    )
    building = db.Column(
        db.String,
        nullable=False
    )
    floor = db.Column(
        db.String,
        default='',
        nullable=False
    )
    number = db.Column(
        db.String,
        default='',
        nullable=False
    )
    notification_before_days = db.Column(
        db.Integer
    )
    notification_for_responsible = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )
    notification_for_assistance = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )
    reservations_need_confirmation = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )
    telephone = db.Column(
        db.String
    )
    key_location = db.Column(
        db.String
    )
    capacity = db.Column(
        db.Integer,
        default=20
    )
    surface_area = db.Column(
        db.Integer
    )
    latitude = db.Column(
        db.String
    )
    longitude = db.Column(
        db.String
    )
    comments = db.Column(
        db.String
    )
    owner_id = db.Column(
        db.String,
        nullable=False
    )
    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        index=True
    )
    is_reservable = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )
    max_advance_days = db.Column(
        db.Integer
    )

    attributes = db.relationship(
        'RoomAttributeAssociation',
        backref='room',
        cascade='all, delete-orphan',
        lazy='dynamic'
    )

    blocked_rooms = db.relationship(
        'BlockedRoom',
        backref='room',
        cascade='all, delete-orphan',
        lazy='dynamic'
    )

    bookable_hours = db.relationship(
        'BookableHours',
        backref='room',
        order_by=BookableHours.start_time,
        cascade='all, delete-orphan',
        lazy='dynamic'
    )

    available_equipment = db.relationship(
        'EquipmentType',
        secondary=RoomEquipmentAssociation,
        backref='rooms',
        lazy='dynamic'
    )

    nonbookable_periods = db.relationship(
        'NonBookablePeriod',
        backref='room',
        order_by=NonBookablePeriod.end_dt.desc(),
        cascade='all, delete-orphan',
        lazy='dynamic'
    )

    photo = db.relationship(
        'Photo',
        backref='room',
        cascade='all, delete-orphan',
        single_parent=True,
        lazy=True
    )

    reservations = db.relationship(
        'Reservation',
        backref='room',
        cascade='all, delete-orphan',
        lazy='dynamic'
    )

    @hybrid_property
    def is_auto_confirm(self):
        return not self.reservations_need_confirmation

    @is_auto_confirm.expression
    def is_auto_confirm(self):
        return ~self.reservations_need_confirmation

    @property
    def booking_url(self):
        if self.id is None:
            return None
        return url_for('rooms.room_book', self)

    @property
    def details_url(self):
        if self.id is None:
            return None
        return str(UH.UHRoomBookingRoomDetails.getURL(target=self))

    @property
    def full_name(self):
        if self.has_special_name:
            return u'{} - {}'.format(self.generate_name(), self.name)
        else:
            return u'{}'.format(self.generate_name())

    @property
    @cached(_cache)
    def has_booking_groups(self):
        return self.has_attribute('allowed-booking-group')

    @property
    @cached(_cache)
    def has_projector(self):
        return self.has_equipment('Computer Projector')

    @property
    def has_special_name(self):
        return self.name and self.name != self.generate_name()

    @property
    @cached(_cache)
    def has_webcast_recording(self):
        return self.has_equipment('Webcast/Recording')

    @property
    @cached(_cache)
    def is_public(self):
        return self.is_reservable and not self.has_booking_groups

    @property
    def kind(self):
        if not self.is_reservable or self.has_booking_groups:
            return 'privateRoom'
        elif self.is_reservable and self.reservations_need_confirmation:
            return 'moderatedRoom'
        elif self.is_reservable:
            return 'basicRoom'
        return ''

    @property
    def location_name(self):
        return self.location.name

    @property
    def marker_description(self):
        infos = []

        infos.append(u'{capacity} {label}'.format(capacity=self.capacity,
                                                  label=_(u'person') if self.capacity == 1 else _(u'people')))
        infos.append(_(u'public') if self.is_public else _(u'private'))
        infos.append(_(u'auto-confirmation') if self.is_auto_confirm else _(u'needs confirmation'))
        if self.has_vc:
            infos.append(_(u'video conference'))

        return u', '.join(map(unicode, infos))

    @property
    @cached(_cache)
    def has_vc(self):
        return self.has_equipment('Video conference')

    @property
    def large_photo_url(self):
        if self.id is None:
            return None
        return url_for('rooms.photo', self, size='large')

    @property
    def small_photo_url(self):
        if self.id is None:
            return None
        return url_for('rooms.photo', self, size='small')

    @property
    def has_photo(self):
        return self.photo_id is not None

    @return_ascii
    def __repr__(self):
        return u'<Room({0}, {1}, {2})>'.format(
            self.id,
            self.location_id,
            self.name
        )

    def has_equipment(self, equipment_name):
        return self.available_equipment.filter_by(name=equipment_name).count() > 0

    def find_available_vc_equipment(self):
        vc_equipment = self.available_equipment \
                           .correlate(Room) \
                           .with_entities(EquipmentType.id) \
                           .filter_by(name='Video conference') \
                           .as_scalar()
        return self.available_equipment.filter(EquipmentType.parent_id == vc_equipment)

    def get_attribute_by_name(self, attribute_name):
        return (self.attributes
                .join(RoomAttribute)
                .filter(RoomAttribute.name == attribute_name)
                .first())

    def has_attribute(self, attribute_name):
        return self.get_attribute_by_name(attribute_name) is not None

    def getLocator(self):
        locator = Locator()
        locator['roomLocation'] = self.location_name
        locator['roomID'] = self.id
        return locator

    def generate_name(self):
        return u'{}-{}-{}'.format(
            self.building,
            self.floor,
            self.number
        )

    def update_name(self):
        if not self.has_special_name and self.building and self.floor and self.number:
            self.name = self.generate_name()

    @classmethod
    def find_all(cls, *args, **kwargs):
        """Retrieves rooms, sorted by location and full name"""
        rooms = super(Room, cls).find_all(*args, **kwargs)
        rooms.sort(key=lambda r: natural_sort_key(r.location_name + r.full_name))
        return rooms

    @classmethod
    def find_with_attribute(cls, attribute):
        """Search rooms which have a specific attribute"""
        return (Room.query
                .with_entities(Room, RoomAttributeAssociation.value)
                .join(Room.attributes, RoomAttributeAssociation.attribute)
                .filter(RoomAttribute.name == attribute)
                .all())

    @staticmethod
    def get_with_data(*args, **kwargs):
        from indico.modules.rb.models.locations import Location

        only_active = kwargs.pop('only_active', True)
        filters = kwargs.pop('filters', None)
        order = kwargs.pop('order', [Location.name, Room.building, Room.floor, Room.number, Room.name])
        if kwargs:
            raise ValueError('Unexpected kwargs: {}'.format(kwargs))

        query = Room.query
        entities = [Room]

        if 'equipment' in args:
            entities.append(static_array.array_agg(EquipmentType.name))
            query = query.outerjoin(RoomEquipmentAssociation).outerjoin(EquipmentType)
        if 'vc_equipment' in args or 'non_vc_equipment' in args:
            vc_id_subquery = db.session.query(EquipmentType.id) \
                                       .correlate(Room) \
                                       .filter_by(name='Video conference') \
                                       .join(RoomEquipmentAssociation) \
                                       .filter(RoomEquipmentAssociation.c.room_id == Room.id) \
                                       .as_scalar()

            if 'vc_equipment' in args:
                # noinspection PyTypeChecker
                entities.append(static_array.array(
                    db.session.query(EquipmentType.name)
                    .join(RoomEquipmentAssociation)
                    .filter(
                        RoomEquipmentAssociation.c.room_id == Room.id,
                        EquipmentType.parent_id == vc_id_subquery
                    )
                    .order_by(EquipmentType.name)
                    .as_scalar()
                ))
            if 'non_vc_equipment' in args:
                # noinspection PyTypeChecker
                entities.append(static_array.array(
                    db.session.query(EquipmentType.name)
                    .join(RoomEquipmentAssociation)
                    .filter(
                        RoomEquipmentAssociation.c.room_id == Room.id,
                        (EquipmentType.parent_id == None) | (EquipmentType.parent_id != vc_id_subquery)
                    )
                    .order_by(EquipmentType.name)
                    .as_scalar()
                ))

        if not entities:
            raise ValueError('No data provided')

        query = query.with_entities(*entities) \
                     .outerjoin(Location, Location.id == Room.location_id) \
                     .group_by(Location.name, Room.id)

        if only_active:
            query = query.filter(Room.is_active)
        if filters:
            query = query.filter(*filters)
        if order:
            query = query.order_by(*order)

        keys = ('room',) + tuple(args)
        return (dict(zip(keys, row if args else [row])) for row in query)

    @classproperty
    @staticmethod
    def max_capacity():
        return db.session.query(db.func.max(Room.capacity)).scalar() or 0

    @staticmethod
    def filter_available(start_dt, end_dt, repetition, include_pre_bookings=True, include_pending_blockings=True):
        """Returns a SQLAlchemy filter criterion ensuring that the room is available during the given time."""
        # Check availability against reservation occurrences
        dummy_occurrences = ReservationOccurrence.create_series(start_dt, end_dt, repetition)
        overlap_criteria = ReservationOccurrence.filter_overlap(dummy_occurrences)
        reservation_criteria = [Reservation.room_id == Room.id,
                                ReservationOccurrence.is_valid,
                                overlap_criteria]
        if not include_pre_bookings:
            reservation_criteria.append(Reservation.is_accepted)
        occurrences_filter = Reservation.occurrences.any(and_(*reservation_criteria))
        # Check availability against blockings
        if include_pending_blockings:
            valid_states = (BlockedRoom.State.accepted, BlockedRoom.State.pending)
        else:
            valid_states = (BlockedRoom.State.accepted,)
        blocking_criteria = [BlockedRoom.blocking_id == Blocking.id,
                             BlockedRoom.state.in_(valid_states),
                             Blocking.start_date <= start_dt.date(),
                             Blocking.end_date >= end_dt.date()]
        blockings_filter = Room.blocked_rooms.any(and_(*blocking_criteria))
        return ~occurrences_filter & ~blockings_filter

    @staticmethod
    def find_with_filters(filters, avatar):
        from indico.modules.rb.models.locations import Location

        equipment_count = len(filters['available_equipment'])
        equipment_subquery = None
        if equipment_count:
            equipment_subquery = (
                db.session.query(RoomEquipmentAssociation)
                .with_entities(func.count(RoomEquipmentAssociation.c.room_id))
                .filter(
                    RoomEquipmentAssociation.c.room_id == Room.id,
                    RoomEquipmentAssociation.c.equipment_id.in_(eq.id for eq in filters['available_equipment'])
                )
                .correlate(Room)
                .as_scalar()
            )

        q = (
            Room.query
            .join(Location.rooms)
            .filter(
                Location.id == filters['location'].id if filters['location'] else True,
                (Room.capacity >= (filters['capacity'] * 0.8)) if filters['capacity'] else True,
                Room.is_reservable if filters['is_only_public'] else True,
                Room.is_auto_confirm if filters['is_auto_confirm'] else True,
                Room.is_active if filters.get('is_only_active', False) else True,
                (equipment_subquery == equipment_count) if equipment_subquery is not None else True)
        )

        if filters['available'] != -1:
            repetition = RepeatMapping.getNewMapping(ast.literal_eval(filters['repeatability']))
            is_available = Room.filter_available(filters['start_dt'], filters['end_dt'], repetition,
                                                 include_pre_bookings=filters['include_pre_bookings'],
                                                 include_pending_blockings=filters['include_pending_blockings'])
            # Filter the search results
            if filters['available'] == 0:  # booked/unavailable
                q = q.filter(~is_available)
            elif filters['available'] == 1:  # available
                q = q.filter(is_available)

        free_search_columns = (
            'name', 'site', 'division', 'building', 'floor', 'number', 'telephone', 'key_location', 'comments'
        )
        if filters['details']:
            # Attributes are stored JSON-encoded, so we need to JSON-encode the provided string and remove the quotes
            # afterwards since PostgreSQL currently does not expose a function to decode a JSON string:
            # http://www.postgresql.org/message-id/51FBF787.5000408@dunslane.net
            details = filters['details'].lower()
            details_str = u'%{}%'.format(details)
            details_json = u'%{}%'.format(json.dumps(details)[1:-1])
            free_search_criteria = [getattr(Room, c).ilike(details_str) for c in free_search_columns]
            free_search_criteria.append(Room.attributes.any(cast(RoomAttributeAssociation.value, db.String)
                                                            .ilike(details_json)))
            q = q.filter(or_(*free_search_criteria))

        q = q.order_by(Room.capacity)
        rooms = q.all()
        # Apply a bunch of filters which are *much* easier to do here than in SQL!
        if filters['is_only_public']:
            # This may trigger additional SQL queries but is_public is cached and doing this check here is *much* easier
            rooms = [r for r in rooms if r.is_public]
        if filters.get('is_only_my_rooms'):
            rooms = [r for r in rooms if r.is_owned_by(avatar)]
        if filters['capacity']:
            # Unless it would result in an empty resultset we don't want to show room which >20% more capacity
            # than requested. This cannot be done easily in SQL so we do that logic here after the SQL query already
            # weeded out rooms that are too small
            matching_capacity_rooms = [r for r in rooms if r.capacity <= filters['capacity'] * 1.2]
            if matching_capacity_rooms:
                rooms = matching_capacity_rooms
        return rooms

    @property
    def owner(self):
        return AvatarHolder().getById(self.owner_id)

    def has_live_reservations(self):
        return self.reservations.filter_by(
            is_archived=False,
            is_cancelled=False,
            is_rejected=False
        ).count() > 0

    def get_blocked_rooms(self, *dates, **kwargs):
        states = kwargs.get('states', (BlockedRoom.State.accepted,))
        return (self.blocked_rooms
                .options(joinedload(BlockedRoom.blocking))
                .join(BlockedRoom.blocking)
                .filter(or_(Blocking.is_active_at(d) for d in dates),
                        BlockedRoom.state.in_(states))
                .all())

    @cached(_cache)
    def get_attribute_value(self, name, default=None):
        attr = self.get_attribute_by_name(name)
        return attr.value if attr else default

    def set_attribute_value(self, name, value):
        attr = self.get_attribute_by_name(name)
        if attr:
            if value:
                attr.value = value
            else:
                self.attributes.filter(RoomAttributeAssociation.attribute_id == attr.attribute_id) \
                    .delete(synchronize_session='fetch')
        elif value:
            attr = self.location.get_attribute_by_name(name)
            if not attr:
                raise ValueError("Attribute {} not supported in location {}".format(name, self.location_name))
            attr_assoc = RoomAttributeAssociation()
            attr_assoc.value = value
            attr_assoc.attribute = attr
            self.attributes.append(attr_assoc)

    @property
    def notification_emails(self):
        return set(filter(None, map(unicode.strip, self.get_attribute_value(u'notification-email', u'').split(u','))))

    def _can_be_booked(self, avatar, prebook=False, ignore_admin=False):
        if not avatar or not rb_check_user_access(avatar):
            return False

        if (not ignore_admin and avatar.isRBAdmin()) or (self.is_owned_by(avatar) and self.is_active):
            return True

        if self.is_active and self.is_reservable and (prebook or not self.reservations_need_confirmation):
            group_name = self.get_attribute_value('allowed-booking-group')
            if not group_name or avatar.is_member_of_group(group_name):
                return True

        return False

    def can_be_booked(self, avatar, ignore_admin=False):
        """
        Reservable rooms which does not require pre-booking can be booked by anyone.
        Other rooms - only by their responsibles.
        """
        return self._can_be_booked(avatar, ignore_admin=ignore_admin)

    def can_be_overriden(self, avatar):
        return avatar.isRBAdmin() or self.is_owned_by(avatar)

    def can_be_prebooked(self, avatar, ignore_admin=False):
        """
        Reservable rooms can be pre-booked by anyone.
        Other rooms - only by their responsibles.
        """
        return self._can_be_booked(avatar, prebook=True, ignore_admin=ignore_admin)

    def can_be_modified(self, accessWrapper):
        """Only admin can modify rooms."""
        if not accessWrapper:
            return False

        if isinstance(accessWrapper, AccessWrapper):
            avatar = accessWrapper.getUser()
            return avatar.isRBAdmin() if avatar else False
        elif isinstance(accessWrapper, Avatar):
            return accessWrapper.isRBAdmin()

        raise MaKaCError(_('canModify requires either AccessWrapper or Avatar object'))

    def can_be_deleted(self, accessWrapper):
        return self.can_be_modified(accessWrapper)

    @cached(_cache)
    def is_owned_by(self, avatar):
        """
        Returns True if user is responsible for this room. False otherwise.
        """
        # legacy check, currently every room must be owned by someone
        if not self.owner_id:
            return None

        if self.owner_id == avatar.id:
            return True
        manager_group = self.get_attribute_value('manager-group')
        if not manager_group:
            return False
        return avatar.is_member_of_group(manager_group.encode('utf-8'))

    @classmethod
    def get_owned_by(cls, user):
        return [room for room in cls.find(is_active=True) if room.is_owned_by(user)]

    @classmethod
    def user_owns_rooms(cls, user):
        return any(room for room in cls.find(is_active=True) if room.is_owned_by(user))

    def check_advance_days(self, end_date, user=None, quiet=False):
        if not self.max_advance_days:
            return
        if user and (user.isRBAdmin() or self.is_owned_by(user)):
            return
        advance_days = (end_date - date.today()).days
        ok = advance_days < self.max_advance_days
        if quiet:
            return ok
        elif not ok:
            msg = _('You cannot book this room more than {} days in advance')
            raise IndicoError(msg.format(self.max_advance_days))

    def check_bookable_hours(self, start_time, end_time, user=None, quiet=False):
        if user and (user.isRBAdmin() or self.is_owned_by(user)):
            return True
        bookable_hours = self.bookable_hours.all()
        if not bookable_hours:
            return True
        for bt in bookable_hours:
            if bt.fits_period(start_time, end_time):
                return True
        if quiet:
            return False
        raise IndicoError('Room cannot be booked at this time')
