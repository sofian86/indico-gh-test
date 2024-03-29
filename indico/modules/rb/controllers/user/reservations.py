# -*- coding: utf-8 -*-
##
##
## This file is part of Indico
## Copyright (C) 2002 - 2013 European Organization for Nuclear Research (CERN)
##
## Indico is free software: you can redistribute it and/or
## modify it under the terms of the GNU General Public License as
## published by the Free Software Foundation, either version 3 of the
## License, or (at your option) any later version.
##
## Indico is distributed in the hope that it will be useful, but
## WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with Indico.  If not, see <http://www.gnu.org/licenses/>.

from datetime import datetime, time, timedelta, date
from collections import defaultdict

import dateutil
import transaction
from flask import request, session, jsonify, flash
from werkzeug.datastructures import MultiDict

from indico.core.db import db
from indico.core.errors import IndicoError, AccessError, NoReportError, NotFoundError
from indico.modules.rb.controllers import RHRoomBookingBase
from indico.modules.rb.forms.base import FormDefaults
from indico.modules.rb.forms.reservations import (BookingSearchForm, NewBookingCriteriaForm, NewBookingPeriodForm,
                                                  NewBookingConfirmForm, NewBookingSimpleForm, ModifyBookingForm)
from indico.modules.rb.models.locations import Location
from indico.modules.rb.models.reservations import Reservation, RepeatMapping
from indico.modules.rb.models.reservation_occurrences import ReservationOccurrence
from indico.modules.rb.models.rooms import Room
from indico.modules.rb.views.user.reservations import (WPRoomBookingSearchBookings, WPRoomBookingSearchBookingsResults,
                                                       WPRoomBookingCalendar, WPRoomBookingNewBookingSelectRoom,
                                                       WPRoomBookingNewBookingSelectPeriod,
                                                       WPRoomBookingNewBookingConfirm,
                                                       WPRoomBookingNewBookingSimple, WPRoomBookingModifyBooking,
                                                       WPRoomBookingBookingDetails)
from indico.util.date_time import get_datetime_from_request
from indico.util.i18n import _
from indico.util.string import natural_sort_key
from indico.web.flask.util import url_for


class RHRoomBookingBookingMixin:
    """Mixin that retrieves the booking or fails if there is none."""
    def _checkParams(self):
        resv_id = request.view_args['resvID']
        self._reservation = Reservation.get(resv_id)
        if not self._reservation:
            raise NoReportError('No booking with id: {}'.format(resv_id))


class RHRoomBookingBookingDetails(RHRoomBookingBookingMixin, RHRoomBookingBase):
    def _get_view(self, **kwargs):
        return WPRoomBookingBookingDetails(self, **kwargs)

    def _process(self):
        return self._get_view(reservation=self._reservation).display()


class _SuccessUrlDetailsMixin:
    def _get_success_url(self):
        return url_for('rooms.roomBooking-bookingDetails', self._reservation)


class RHRoomBookingAcceptBooking(_SuccessUrlDetailsMixin, RHRoomBookingBookingMixin, RHRoomBookingBase):
    def _checkProtection(self):
        RHRoomBookingBase._checkProtection(self)
        if not self._reservation.can_be_accepted(session.user):
            raise IndicoError("You are not authorized to perform this action")

    def _process(self):
        if self._reservation.find_overlapping().filter(Reservation.is_accepted).count():
            raise IndicoError("This reservation couldn't be accepted due to conflicts with other reservations")
        if self._reservation.is_pending:
            self._reservation.accept(session.user)
            flash(_(u'Booking accepted'), 'success')
        self._redirect(self._get_success_url())


class RHRoomBookingCancelBooking(_SuccessUrlDetailsMixin, RHRoomBookingBookingMixin, RHRoomBookingBase):
    def _checkProtection(self):
        RHRoomBookingBase._checkProtection(self)
        if not self._reservation.can_be_cancelled(session.user):
            raise IndicoError("You are not authorized to perform this action")

    def _process(self):
        if not self._reservation.is_cancelled and not self._reservation.is_rejected:
            self._reservation.cancel(session.user)
            flash(_(u'Booking cancelled'), 'success')
        self._redirect(self._get_success_url())


class RHRoomBookingRejectBooking(_SuccessUrlDetailsMixin, RHRoomBookingBookingMixin, RHRoomBookingBase):
    def _checkParams(self):
        RHRoomBookingBookingMixin._checkParams(self)
        self._reason = request.form.get('reason', u'')

    def _checkProtection(self):
        RHRoomBookingBase._checkProtection(self)
        if not self._reservation.can_be_rejected(session.user):
            raise IndicoError("You are not authorized to perform this action")

    def _process(self):
        if not self._reservation.is_cancelled and not self._reservation.is_rejected:
            self._reservation.reject(session.user, self._reason)
            flash(_(u'Booking rejected'), 'success')
        self._redirect(self._get_success_url())


class RHRoomBookingCancelBookingOccurrence(_SuccessUrlDetailsMixin, RHRoomBookingBookingMixin, RHRoomBookingBase):
    def _checkParams(self):
        RHRoomBookingBookingMixin._checkParams(self)
        occ_date = dateutil.parser.parse(request.view_args['date'], yearfirst=True).date()
        self._occurrence = self._reservation.occurrences.filter(ReservationOccurrence.date == occ_date).one()

    def _checkProtection(self):
        RHRoomBookingBase._checkProtection(self)
        if not self._reservation.can_be_cancelled(session.user):
            raise IndicoError("You are not authorized to perform this action")

    def _process(self):
        if self._occurrence.is_valid:
            self._occurrence.cancel(session.user)
            flash(_(u'Booking occurrence cancelled'), 'success')
        self._redirect(self._get_success_url())


class RHRoomBookingRejectBookingOccurrence(_SuccessUrlDetailsMixin, RHRoomBookingBookingMixin, RHRoomBookingBase):
    def _checkParams(self):
        RHRoomBookingBookingMixin._checkParams(self)
        occ_date = dateutil.parser.parse(request.view_args['date'], yearfirst=True).date()
        self._reason = request.form.get('reason', u'')
        self._occurrence = self._reservation.occurrences.filter(ReservationOccurrence.date == occ_date).one()

    def _checkProtection(self):
        RHRoomBookingBase._checkProtection(self)
        if not self._reservation.can_be_rejected(session.user):
            raise IndicoError("You are not authorized to perform this action")

    def _process(self):
        if self._occurrence.is_valid:
            self._occurrence.reject(session.user, self._reason)
            flash(_(u'Booking occurrence rejected'), 'success')
        self._redirect(self._get_success_url())


class RHRoomBookingSearchBookings(RHRoomBookingBase):
    menu_item = 'bookingListSearch'
    show_blockings = True

    def _get_form_data(self):
        return request.form

    def _filter_displayed_rooms(self, rooms, occurrences):
        return rooms

    def _checkParams(self):
        self._rooms = sorted(Room.find_all(is_active=True), key=lambda r: natural_sort_key(r.full_name))
        self._form_data = self._get_form_data()
        self._form = BookingSearchForm(self._form_data)
        self._form.room_ids.choices = [(r.id, None) for r in self._rooms]

    def _is_submitted(self):
        return self._form.is_submitted()

    def _process(self):
        form = self._form
        if self._is_submitted() and form.validate():
            if form.data.get('is_only_my_rooms'):
                form.room_ids.data = [room.id for room in Room.find_all() if room.is_owned_by(session.user)]

            occurrences = ReservationOccurrence.find_with_filters(form.data, session.user).all()
            rooms = self._filter_displayed_rooms([r for r in self._rooms if r.id in set(form.room_ids.data)],
                                                 occurrences)
            return WPRoomBookingSearchBookingsResults(self, rooms=rooms, occurrences=occurrences,
                                                      show_blockings=self.show_blockings,
                                                      start_dt=form.start_dt.data, end_dt=form.end_dt.data,
                                                      form=form, form_data=self._form_data,
                                                      menu_item=self.menu_item).display()

        return WPRoomBookingSearchBookings(self, errors=form.error_list, rooms=self._rooms,
                                           user_has_rooms=session.user.has_rooms).display()


class RHRoomBookingSearchBookingsShortcutBase(RHRoomBookingSearchBookings):
    """Base class for searches with predefined criteria"""
    search_criteria = {}
    show_blockings = False

    def _is_submitted(self):
        return True

    def _get_form_data(self):
        if request.method == 'POST':
            # Actual form submission (when using the period selector widget)
            return RHRoomBookingSearchBookings._get_form_data(self)

        # Class-specific criteria + default times
        data = MultiDict(self.search_criteria)
        data['start_time'] = '00:00'
        data['end_time'] = '23:59'
        data['start_date'] = date.today().strftime('%d/%m/%Y')
        data['end_date'] = (date.today() + timedelta(weeks=1)).strftime('%d/%m/%Y')
        data.setlist('room_ids', [r.id for r in self._rooms])
        return data


class _RoomsWithBookingsMixin:
    def _filter_displayed_rooms(self, rooms, occurrences):
        booked_rooms = {occ.reservation.room_id for occ in occurrences}
        return [r for r in rooms if r.id in booked_rooms]


class _MyRoomsMixin:
    def _filter_displayed_rooms(self, rooms, occurrences):
        return [r for r in rooms if r.is_owned_by(session.user)]


class RHRoomBookingSearchMyBookings(_RoomsWithBookingsMixin, RHRoomBookingSearchBookingsShortcutBase):
    menu_item = 'myBookingList'
    search_criteria = {
        'is_only_mine': True
    }


class RHRoomBookingSearchBookingsMyRooms(_MyRoomsMixin, RHRoomBookingSearchBookingsShortcutBase):
    menu_item = 'usersBookings'
    search_criteria = {
        'is_only_my_rooms': True
    }


class RHRoomBookingSearchPendingBookingsMyRooms(_MyRoomsMixin, RHRoomBookingSearchBookingsShortcutBase):
    menu_item = 'usersPendingBookings'
    search_criteria = {
        'is_only_my_rooms': True,
        'is_only_pending_bookings': True
    }


class RHRoomBookingNewBookingBase(RHRoomBookingBase):
    def _make_confirm_form(self, room, step=None, defaults=None, form_class=NewBookingConfirmForm):
        # Note: ALWAYS pass defaults as a kwargs! For-Event room booking depends on it!
        # Step 3
        # If we come from a successful step 2 we take default values from that step once again
        if step == 2:
            defaults.used_equipment = []  # wtforms bug; avoid `foo in None` check
            form = form_class(formdata=MultiDict(), obj=defaults)
        else:
            form = form_class(obj=defaults)

        if not room.notification_for_assistance:
            del form.needs_assistance

        can_book = room.can_be_booked(session.user)
        can_prebook = room.can_be_prebooked(session.user)
        if room.is_auto_confirm or (not can_prebook or (can_book and room.can_be_booked(session.user, True))):
            # The user has actually the permission to book (not just because he's an admin)
            # Or he simply can't even prebook the room
            del form.submit_prebook
        if not can_book:
            # User can only prebook
            del form.submit_book

        form.used_equipment.query = room.find_available_vc_equipment()
        return form

    def _get_all_conflicts(self, room, form, reservation_id=None):
        conflicts = defaultdict(list)
        pre_conflicts = defaultdict(list)

        candidates = ReservationOccurrence.create_series(form.start_dt.data, form.end_dt.data,
                                                         (form.repeat_interval.data, form.repeat_interval.data))
        occurrences = ReservationOccurrence.find_overlapping_with(room, candidates, reservation_id).all()

        for cand in candidates:
            for occ in occurrences:
                if cand.overlaps(occ):
                    if occ.reservation.is_accepted:
                        conflicts[cand].append(occ)
                    else:
                        pre_conflicts[cand].append(occ)

        return conflicts, pre_conflicts

    def _get_all_occurrences(self, room_ids, form, flexible_days=0, reservation_id=None):
        start_dt = form.start_dt.data
        end_dt = form.end_dt.data
        repeat_frequency = form.repeat_frequency.data
        repeat_interval = form.repeat_interval.data
        day_start_dt = datetime.combine(start_dt.date(), time())
        day_end_dt = datetime.combine(end_dt.date(), time(23, 59))
        today_start_dt = datetime.combine(date.today(), time())
        flexible_start_dt = day_start_dt - timedelta(days=flexible_days)
        if not session.user.isAdmin():
            flexible_start_dt = max(today_start_dt, flexible_start_dt)
        flexible_end_dt = day_end_dt + timedelta(days=flexible_days)

        occurrences = ReservationOccurrence.find_all(
            Reservation.room_id.in_(room_ids),
            Reservation.id != reservation_id,
            ReservationOccurrence.start_dt >= flexible_start_dt,
            ReservationOccurrence.end_dt <= flexible_end_dt,
            ReservationOccurrence.is_valid,
            _join=Reservation,
            _eager=ReservationOccurrence.reservation
        )

        candidates = {}
        for days in xrange(-flexible_days, flexible_days + 1):
            offset = timedelta(days=days)
            series_start = start_dt + offset
            series_end = end_dt + offset
            if series_start < flexible_start_dt:
                    continue
            candidates[series_start, series_end] = ReservationOccurrence.create_series(series_start, series_end,
                                                                                       (repeat_frequency,
                                                                                        repeat_interval))
        return occurrences, candidates

    def _create_booking(self, form, room):
        if 'submit_book' in form and 'submit_prebook' in form:
            # Admins have the choice
            prebook = form.submit_prebook.data
        else:
            # Otherwise the existence of the book submit button means the user can book
            prebook = 'submit_book' not in form
        reservation = Reservation.create_from_data(room, form.data, session.user, prebook)
        db.session.add(reservation)
        db.session.flush()
        return reservation

    def _get_success_url(self, booking):
        return url_for('rooms.roomBooking-bookingDetails', booking)

    def _create_booking_response(self, form, room):
        """Creates the booking and returns a JSON response."""
        try:
            booking = self._create_booking(form, room)
        except NoReportError as e:
            transaction.abort()
            return jsonify(success=False, msg=unicode(e))
        flash(_(u'Pre-Booking created') if booking.is_pending else _(u'Booking created'), 'success')
        return jsonify(success=True, url=self._get_success_url(booking))


class RHRoomBookingNewBookingSimple(RHRoomBookingNewBookingBase):
    def _checkParams(self):
        self._room = Room.get(int(request.view_args['roomID']))
        if self._room is None:
            raise NotFoundError('This room does not exist')

    def _make_form(self):
        if 'start_date' in request.args:
            start_date = datetime.strptime(request.args['start_date'], '%Y-%m-%d').date()
        else:
            start_date = date.today()
        defaults = FormDefaults(room_id=self._room.id,
                                start_dt=datetime.combine(start_date, Location.working_time_start),
                                end_dt=datetime.combine(start_date, Location.working_time_end),
                                booked_for_id=session.user.id,
                                booked_for_name=session.user.getStraightFullName().decode('utf-8'),
                                contact_email=session.user.getEmail().decode('utf-8'),
                                contact_phone=session.user.getPhone().decode('utf-8'))

        return self._make_confirm_form(self._room, defaults=defaults, form_class=NewBookingSimpleForm)

    def _get_view(self, **kwargs):
        return WPRoomBookingNewBookingSimple(self, **kwargs)

    def _process(self):
        room = self._room
        rooms = Room.find_all()
        form = self._make_form()

        if form.is_submitted() and not form.validate():
            occurrences = {}
            candidates = {}
            conflicts = {}
            pre_conflicts = {}
        else:
            occurrences, candidates = self._get_all_occurrences([self._room.id], form)
            conflicts, pre_conflicts = self._get_all_conflicts(self._room, form)

        if form.validate_on_submit() and not form.submit_check.data:
            return self._create_booking_response(form, room)

        can_override = room.can_be_overriden(session.user)
        return self._get_view(form=form,
                              room=room,
                              rooms=rooms,
                              occurrences=occurrences,
                              candidates=candidates,
                              conflicts=conflicts,
                              pre_conflicts=pre_conflicts,
                              start_dt=form.start_dt.data,
                              end_dt=form.end_dt.data,
                              repeat_frequency=form.repeat_frequency.data,
                              repeat_interval=form.repeat_interval.data,
                              can_override=can_override).display()


class RHRoomBookingCloneBooking(RHRoomBookingBookingMixin, RHRoomBookingNewBookingSimple):
    def _checkParams(self):
        RHRoomBookingBookingMixin._checkParams(self)

        # use 'room' if passed through GET
        room_id = request.args.get('room', None)

        if room_id is None:
            # otherwise default to reservation's
            self._room = self._reservation.room
        else:
            self._room = Room.get(int(room_id))

        if self._room is None:
            raise NotFoundError('This room does not exist')

    def _get_view(self, **kwargs):
        return RHRoomBookingNewBookingSimple._get_view(self, clone_booking=self._reservation, **kwargs)

    def _make_form(self):
        defaults = FormDefaults(
            self._reservation,
            skip_attrs={'room_id', 'booked_for_id', 'booked_for_name', 'contact_email', 'contact_phone'},
            room_id=self._room.id,
            booked_for_id=session.user.id,
            booked_for_name=session.user.getStraightFullName().decode('utf-8'),
            contact_email=session.user.getEmail().decode('utf-8'),
            contact_phone=session.user.getPhone().decode('utf-8')
        )

        return self._make_confirm_form(self._room, defaults=defaults, form_class=NewBookingSimpleForm)


class RHRoomBookingNewBooking(RHRoomBookingNewBookingBase):
    def _checkParams(self):
        try:
            self._step = int(request.form.get('step', 1))
        except ValueError:
            self._step = 1

    def _get_view(self, view, **kwargs):
        views = {'select_room': WPRoomBookingNewBookingSelectRoom,
                 'select_period': WPRoomBookingNewBookingSelectPeriod,
                 'confirm': WPRoomBookingNewBookingConfirm}
        return views[view](self, **kwargs)

    def _get_select_room_form_defaults(self):
        return FormDefaults(start_dt=datetime.combine(date.today(), Location.working_time_start),
                            end_dt=datetime.combine(date.today(), Location.working_time_end))

    def _make_select_room_form(self):
        # Step 1
        self._rooms = sorted(Room.find_all(is_active=True), key=lambda r: natural_sort_key(r.full_name))

        form = NewBookingCriteriaForm(obj=self._get_select_room_form_defaults())
        form.room_ids.choices = [(r.id, None) for r in self._rooms]
        return form

    def _make_select_period_form(self, defaults=None):
        # Step 2
        # If we come from a successful step 1 submission we use the default values provided by that step.
        if self._step == 1:
            return NewBookingPeriodForm(formdata=MultiDict(), obj=defaults)
        else:
            return NewBookingPeriodForm()

    def _show_confirm(self, room, form, step=None, defaults=None):
        # form can be PeriodForm or Confirmform depending on the step we come from
        if step == 2:
            confirm_form = self._make_confirm_form(room, step, defaults=defaults)
        else:
            # Step3 => Step3 due to an error in the form
            confirm_form = form

        conflicts, pre_conflicts = self._get_all_conflicts(room, form)
        repeat_msg = RepeatMapping.getMessage(form.repeat_frequency.data, form.repeat_interval.data)
        return self._get_view('confirm', form=confirm_form, room=room, start_dt=form.start_dt.data,
                              end_dt=form.end_dt.data, repeat_frequency=form.repeat_frequency.data,
                              repeat_interval=form.repeat_interval.data, repeat_msg=repeat_msg, conflicts=conflicts,
                              pre_conflicts=pre_conflicts, errors=confirm_form.error_list).display()

    def _process_select_room(self):
        # Step 1: Room(s), dates, repetition selection
        form = self._make_select_room_form()
        if form.validate_on_submit():
            flexible_days = form.flexible_dates_range.data
            day_start_dt = datetime.combine(form.start_dt.data.date(), time())
            day_end_dt = datetime.combine(form.end_dt.data.date(), time(23, 59))

            selected_rooms = [r for r in self._rooms if r.id in form.room_ids.data]
            occurrences, candidates = self._get_all_occurrences(form.room_ids.data, form, flexible_days)

            period_form_defaults = FormDefaults(repeat_interval=form.repeat_interval.data,
                                                repeat_frequency=form.repeat_frequency.data)
            period_form = self._make_select_period_form(period_form_defaults)

            # Show step 2 page
            return self._get_view('select_period', rooms=selected_rooms, occurrences=occurrences, candidates=candidates,
                                  start_dt=day_start_dt, end_dt=day_end_dt, period_form=period_form, form=form,
                                  repeat_frequency=form.repeat_frequency.data,
                                  repeat_interval=form.repeat_interval.data, flexible_days=flexible_days).display()

        # GET or form errors => show step 1 page
        return self._get_view('select_room', errors=form.error_list, rooms=self._rooms, form=form,
                              max_room_capacity=Room.max_capacity, can_override=session.user.isRBAdmin()).display()

    def _process_select_period(self):
        form = self._make_select_period_form()
        if form.is_submitted():
            # Errors in here are only caused by users messing with the submitted data so it's not
            # worth making the code more complex to show the errors nicely on the originating page.
            # Doing so would be very hard anyway as we don't keep all data necessary to show step 2
            # when it's not a step 1 form submission.
            if not form.validate():
                raise IndicoError('<br>'.join(form.error_list))
            room = Room.get(form.room_id.data)
            if not room:
                raise IndicoError('Invalid room')
            # Show step 3 page
            confirm_form_defaults = FormDefaults(form.data,
                                                 booked_for_id=session.user.id,
                                                 booked_for_name=session.user.getStraightFullName().decode('utf-8'),
                                                 contact_email=session.user.getEmail().decode('utf-8'),
                                                 contact_phone=session.user.getPhone().decode('utf-8'))
            return self._show_confirm(room, form, self._step, confirm_form_defaults)

    def _process_confirm(self):
        # The form needs the room to create the equipment list, so we need to get it "manually"...
        room = Room.get(int(request.form['room_id']))
        form = self._make_confirm_form(room)
        if not room.can_be_booked(session.user) and not room.can_be_prebooked(session.user):
            raise IndicoError('You cannot book this room')
        if form.validate_on_submit():
            return self._create_booking_response(form, room)
        # There was an error in the form
        return self._show_confirm(room, form)

    def _process(self):
        if self._step == 1:
            return self._process_select_room()
        elif self._step == 2:
            return self._process_select_period()
        elif self._step == 3:
            return self._process_confirm()
        else:
            self._redirect(url_for('rooms.book'))


class RHRoomBookingModifyBooking(RHRoomBookingBookingMixin, RHRoomBookingNewBookingBase):
    def _checkProtection(self):
        if not self._reservation.can_be_modified(session.user):
            raise AccessError

    def _get_view(self, **kwargs):
        return WPRoomBookingModifyBooking(self, **kwargs)

    def _get_success_url(self):
        return url_for('rooms.roomBooking-bookingDetails', self._reservation)

    def _process(self):
        room = self._reservation.room
        form = ModifyBookingForm(obj=self._reservation, old_start_date=self._reservation.start_dt.date())
        form.used_equipment.query = room.find_available_vc_equipment()

        if form.is_submitted() and not form.validate():
            occurrences = {}
            candidates = {}
            conflicts = {}
            pre_conflicts = {}
        else:
            occurrences, candidates = self._get_all_occurrences([room.id], form, reservation_id=self._reservation.id)
            conflicts, pre_conflicts = self._get_all_conflicts(room, form, self._reservation.id)

        if form.validate_on_submit() and not form.submit_check.data:
            try:
                self._reservation.modify(form.data, session.user)
                flash(_(u'Booking updated'), 'success')
            except NoReportError as e:
                transaction.abort()
                return jsonify(success=False, msg=unicode(e))
            return jsonify(success=True, url=self._get_success_url())

        return self._get_view(form=form, room=room, rooms=Room.find_all(), occurrences=occurrences,
                              candidates=candidates, conflicts=conflicts, pre_conflicts=pre_conflicts,
                              start_dt=form.start_dt.data, end_dt=form.end_dt.data,
                              repeat_frequency=form.repeat_frequency.data, repeat_interval=form.repeat_interval.data,
                              reservation=self._reservation, can_override=room.can_be_overriden(session.user)).display()


class RHRoomBookingCalendar(RHRoomBookingBase):
    MAX_DAYS = 365 * 2

    def _checkParams(self):
        today = datetime.now().date()
        self.start_dt = get_datetime_from_request('start_', default=datetime.combine(today, time(0, 0)))
        self.end_dt = get_datetime_from_request('end_', default=datetime.combine(self.start_dt.date(), time(23, 59)))
        period = self.end_dt.date() - self.start_dt.date() + timedelta(days=1)
        self._overload = period.days > self.MAX_DAYS

    def _process(self):
        if self._overload:
            rooms = []
            occurrences = []
        else:
            rooms = Room.find_all(is_active=True)
            occurrences = ReservationOccurrence.find_all(
                Reservation.room_id.in_(room.id for room in rooms),
                ReservationOccurrence.start_dt >= self.start_dt,
                ReservationOccurrence.end_dt <= self.end_dt,
                ReservationOccurrence.is_valid,
                _join=Reservation,
                _eager=ReservationOccurrence.reservation
            )

        return WPRoomBookingCalendar(self, rooms=rooms, occurrences=occurrences, start_dt=self.start_dt,
                                     end_dt=self.end_dt, overload=self._overload, max_days=self.MAX_DAYS).display()
