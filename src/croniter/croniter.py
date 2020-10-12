#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import absolute_import, print_function, division

import math
import re
from time import time
import datetime
from dateutil.relativedelta import relativedelta
from dateutil.tz import tzutc
import calendar
import natsort

step_search_re = re.compile(r'^([^-]+)-([^-/]+)(/(.*))?$')
search_re = re.compile(r'^([^-]+)-([^-/]+)(/(.*))?$')
only_int_re = re.compile(r'^\d+$')
any_int_re = re.compile(r'^\d+')
star_or_int_re = re.compile(r'^(\d+|\*)$')
VALID_LEN_EXPRESSION = [5, 6]


class CroniterError(ValueError):
    """ General top-level Croniter base exception """
    pass


class CroniterBadCronError(CroniterError):
    """ Syntax, unknown value, or range error within a cron expression """
    pass


class CroniterBadDateError(CroniterError):
    """ Unable to find next/prev timestamp match """
    pass


class CroniterNotAlphaError(CroniterBadCronError):
    """ Cron syntax contains an invalid day or month abreviation """
    pass


def zerodate(d):
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def timedelta_to_seconds(td):
    """
    Converts a 'datetime.timedelta' object `td` into seconds contained in
    the duration.
    Note: We cannot use `timedelta.total_seconds()` because this is not
    supported by Python 2.6.
    """
    return (td.microseconds + (td.seconds + td.days * 24 * 3600) * 10**6) \
        / 10**6


def datetime_to_timestamp(d):
    """
    Converts a `datetime` object `d` into a UNIX timestamp.
    """
    if d.tzinfo is not None:
        d = d.replace(tzinfo=None) - d.utcoffset()
    return timedelta_to_seconds(d - datetime.datetime(1970, 1, 1))


def timestamp_to_datetime(timestamp, tzinfo=None):
    """
    Converts a UNIX timestamp `timestamp` into a `datetime` object.
    """
    result = datetime.datetime.utcfromtimestamp(timestamp)
    if tzinfo:
        result = result.replace(tzinfo=tzutc()).astimezone(tzinfo)
    return result


def get_next_dst_window(dt1, dt2=None):
    '''
    Return the lower, upper bound of the first DST transition between
    the two dates, and if it is the summer, or winter one.
    '''
    if dt2 is None:
        dt2 = dt1 + relativedelta(days=3)
    minh = min(zerodate(dt1), zerodate(dt2))
    minhdst = timedelta_to_seconds(minh.utcoffset())
    is_summer = True
    window = None, None, is_summer
    for hour in range(
        int(
            round(
                croniter._timedelta_to_seconds(abs(dt1 - dt2)) / 60)
        )
    ):
        curh = minh + relativedelta(hours=hour)
        upb = timestamp_to_datetime(datetime_to_timestamp(curh), tzinfo=curh.tzinfo)
        coffset = timedelta_to_seconds(upb.utcoffset())
        if coffset != minhdst:
            ilowb = upb - relativedelta(hours=1)
            lowb = timestamp_to_datetime(datetime_to_timestamp(ilowb), tzinfo=curh.tzinfo)
            lowboffset = timedelta_to_seconds(lowb.utcoffset())
            # impossible to happen for now
            if upb is None:
                raise CroniterError('DST window error')
            window = lowb, upb, coffset > lowboffset
            break
    return window


class croniter(object):
    MONTHS_IN_YEAR = 12
    RANGES = (
        (0, 59),
        (0, 23),
        (1, 31),
        (1, 12),
        (0, 6),
        (0, 59)
    )
    DAYS = (
        31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31
    )

    ALPHACONV = (
        {},  # 0: min
        {},  # 1: hour
        {"l": "l"},  # 2: dom
        {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
         'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12},  # 3: mon
        {'sun': 0, 'mon': 1, 'tue': 2, 'wed': 3, 'thu': 4, 'fri': 5, 'sat': 6},  #4: dow
        {}  # command/user
    )

    LOWMAP = (
        {},
        {},
        {0: 1},
        {0: 1},
        {7: 0},
        {},
    )

    LEN_MEANS_ALL = (
        60,
        24,
        31,
        12,
        7,
        60
    )

    bad_length = 'Exactly 5 or 6 columns has to be specified for iterator' \
                 'expression.'

    def __init__(self, expr_format, start_time=None, ret_type=float,
                 day_or=True, max_years_between_matches=None, is_prev=False):
        self._ret_type = ret_type
        self._day_or = day_or

        self._max_years_btw_matches_explicitly_set = (
            max_years_between_matches is not None)
        if not self._max_years_btw_matches_explicitly_set:
            max_years_between_matches = 50
        self._max_years_between_matches = max(int(max_years_between_matches), 1)

        if start_time is None:
            start_time = time()

        self.tzinfo = None

        self.start_time = None
        self.dst_start_time = None
        self.cur = None
        self.set_current(start_time)

        self.expanded, self.nth_weekday_of_month = self.expand(expr_format)
        self._is_prev = is_prev

    @classmethod
    def _alphaconv(cls, index, key, expressions):
        try:
            return cls.ALPHACONV[index][key.lower()]
        except KeyError:
            raise CroniterNotAlphaError(
                "[{0}] is not acceptable".format(" ".join(expressions)))

    def get_next(self, ret_type=None, start_time=None):
        if start_time is not None:
            self.set_current(start_time)
        return self._get_next(ret_type or self._ret_type, is_prev=False)

    def get_prev(self, ret_type=None):
        return self._get_next(ret_type or self._ret_type, is_prev=True)

    def get_current(self, ret_type=None):
        ret_type = ret_type or self._ret_type
        if issubclass(ret_type, datetime.datetime):
            return self._timestamp_to_datetime(self.cur)
        return self.cur

    def set_current(self, start_time):
        if isinstance(start_time, datetime.datetime):
            self.tzinfo = start_time.tzinfo
            start_time = self._datetime_to_timestamp(start_time)

        self.start_time = start_time
        self.dst_start_time = start_time
        self.cur = start_time
        return self.cur

    @classmethod
    def _datetime_to_timestamp(cls, d):
        """
        Converts a `datetime` object `d` into a UNIX timestamp.
        """
        return datetime_to_timestamp(d)

    def _timestamp_to_datetime(self, timestamp):
        """
        Converts a UNIX timestamp `timestamp` into a `datetime` object.
        """
        return timestamp_to_datetime(timestamp, tzinfo=self.tzinfo)

    @classmethod
    def _timedelta_to_seconds(cls, td):
        """
        Converts a 'datetime.timedelta' object `td` into seconds contained in
        the duration.
        Note: We cannot use `timedelta.total_seconds()` because this is not
        supported by Python 2.6.
        """
        return timedelta_to_seconds(td)

    def _get_next(self, ret_type=None, is_prev=None):
        if is_prev is None:
            is_prev = self._is_prev
        self._is_prev = is_prev
        expanded = self.expanded[:]
        nth_weekday_of_month = self.nth_weekday_of_month.copy()

        ret_type = ret_type or self._ret_type

        if not issubclass(ret_type, (float, datetime.datetime)):
            raise TypeError("Invalid ret_type, only 'float' or 'datetime' "
                            "is acceptable.")

        # exception to support day of month and day of week as defined in cron
        if (expanded[2][0] != '*' and expanded[4][0] != '*') and self._day_or:
            bak = expanded[4]
            expanded[4] = ['*']
            t1 = self._calc(self.cur, expanded, nth_weekday_of_month, is_prev)
            expanded[4] = bak
            expanded[2] = ['*']

            t2 = self._calc(self.cur, expanded, nth_weekday_of_month, is_prev)
            if not is_prev:
                result = t1 if t1 < t2 else t2
            else:
                result = t1 if t1 > t2 else t2
        else:
            result = self._calc(self.cur, expanded,
                                nth_weekday_of_month, is_prev)
        self.cur = result
        if issubclass(ret_type, datetime.datetime):
            result = timestamp_to_datetime(self.cur, tzinfo=self.tzinfo)
        return result

    # iterator protocol, to enable direct use of croniter
    # objects in a loop, like "for dt in croniter('5 0 * * *'): ..."
    # or for combining multiple croniters into single
    # dates feed using 'itertools' module
    def all_next(self, ret_type=None):
        '''Generator of all consecutive dates. Can be used instead of
        implicit call to __iter__, whenever non-default
        'ret_type' has to be specified.
        '''
        # In a Python 3.7+ world:  contextlib.supress and contextlib.nullcontext could be used instead
        try:
            while True:
                self._is_prev = False
                yield self._get_next(ret_type or self._ret_type)
        except CroniterBadDateError:
            if self._max_years_btw_matches_explicitly_set:
                return
            else:
                raise

    def all_prev(self, ret_type=None):
        '''Generator of all previous dates.'''
        try:
            while True:
                self._is_prev = True
                yield self._get_next(ret_type or self._ret_type)
        except CroniterBadDateError:
            if self._max_years_btw_matches_explicitly_set:
                return
            else:
                raise

    def iter(self, *args, **kwargs):
        return (self._is_prev and self.all_prev or self.all_next)

    def __iter__(self):
        return self
    __next__ = next = _get_next

    def _calc(self, now, expanded, nth_weekday_of_month, is_prev):
        if is_prev:
            now = math.ceil(now)
            nearest_diff_method = self._get_prev_nearest_diff
            sign = -1
            offset = (len(expanded) == 6 or now % 60 > 0) and 1 or 60
        else:
            now = math.floor(now)
            nearest_diff_method = self._get_next_nearest_diff
            sign = 1
            offset = (len(expanded) == 6) and 1 or 60

        dst = now = self._timestamp_to_datetime(now + sign * offset)

        month, year = dst.month, dst.year
        current_year = now.year
        DAYS = self.DAYS

        def proc_month(d):
            if expanded[3][0] != '*':
                diff_month = nearest_diff_method(
                    d.month, expanded[3], self.MONTHS_IN_YEAR)
                days = DAYS[month - 1]
                if month == 2 and self.is_leap(year) is True:
                    days += 1

                reset_day = 1

                if diff_month is not None and diff_month != 0:
                    if is_prev:
                        d += relativedelta(months=diff_month)
                        reset_day = DAYS[d.month - 1]
                        d += relativedelta(
                            day=reset_day, hour=23, minute=59, second=59)
                    else:
                        d += relativedelta(months=diff_month, day=reset_day,
                                           hour=0, minute=0, second=0)
                    return True, d
            return False, d

        def proc_day_of_month(d):
            if expanded[2][0] != '*':
                days = DAYS[month - 1]
                if month == 2 and self.is_leap(year) is True:
                    days += 1
                if 'l' in expanded[2] and days == d.day:
                    return False, d

                if is_prev:
                    days_in_prev_month = DAYS[
                        (month - 2) % self.MONTHS_IN_YEAR]
                    diff_day = nearest_diff_method(
                        d.day, expanded[2], days_in_prev_month)
                else:
                    diff_day = nearest_diff_method(d.day, expanded[2], days)

                if diff_day is not None and diff_day != 0:
                    if is_prev:
                        d += relativedelta(
                            days=diff_day, hour=23, minute=59, second=59)
                    else:
                        d += relativedelta(
                            days=diff_day, hour=0, minute=0, second=0)
                    return True, d
            return False, d

        def proc_day_of_week(d):
            if expanded[4][0] != '*':
                diff_day_of_week = nearest_diff_method(
                    d.isoweekday() % 7, expanded[4], 7)
                if diff_day_of_week is not None and diff_day_of_week != 0:
                    if is_prev:
                        d += relativedelta(days=diff_day_of_week,
                                           hour=23, minute=59, second=59)
                    else:
                        d += relativedelta(days=diff_day_of_week,
                                           hour=0, minute=0, second=0)
                    return True, d
            return False, d

        def proc_day_of_week_nth(d):
            if '*' in nth_weekday_of_month:
                s = nth_weekday_of_month['*']
                for i in range(0, 7):
                    if i in nth_weekday_of_month:
                        nth_weekday_of_month[i].update(s)
                    else:
                        nth_weekday_of_month[i] = s
                del nth_weekday_of_month['*']

            candidates = []
            for wday, nth in nth_weekday_of_month.items():
                w = (wday + 6) % 7
                c = calendar.Calendar(w).monthdayscalendar(d.year, d.month)
                if c[0][0] == 0:
                    c.pop(0)
                for n in nth:
                    if len(c) < n:
                        continue
                    candidate = c[n - 1][0]
                    if (
                        (is_prev and candidate <= d.day) or
                        (not is_prev and d.day <= candidate)
                    ):
                        candidates.append(candidate)

            if not candidates:
                if is_prev:
                    d += relativedelta(days=-d.day,
                                       hour=23, minute=59, second=59)
                else:
                    days = DAYS[month - 1]
                    if month == 2 and self.is_leap(year) is True:
                        days += 1
                    d += relativedelta(days=(days - d.day + 1),
                                       hour=0, minute=0, second=0)
                return True, d

            candidates.sort()
            diff_day = (candidates[-1] if is_prev else candidates[0]) - d.day
            if diff_day != 0:
                if is_prev:
                    d += relativedelta(days=diff_day,
                                       hour=23, minute=59, second=59)
                else:
                    d += relativedelta(days=diff_day,
                                       hour=0, minute=0, second=0)
                return True, d
            return False, d

        def proc_hour(d):
            if expanded[1][0] != '*':
                diff_hour = nearest_diff_method(d.hour, expanded[1], 24)
                if diff_hour is not None and diff_hour != 0:
                    if is_prev:
                        d += relativedelta(
                            hours=diff_hour, minute=59, second=59)
                    else:
                        d += relativedelta(hours=diff_hour, minute=0, second=0)
                    return True, d
            return False, d

        def proc_minute(d):
            if expanded[0][0] != '*':
                diff_min = nearest_diff_method(d.minute, expanded[0], 60)
                if diff_min is not None and diff_min != 0:
                    if is_prev:
                        d += relativedelta(minutes=diff_min, second=59)
                    else:
                        d += relativedelta(minutes=diff_min, second=0)
                    return True, d
            return False, d

        def proc_second(d):
            if len(expanded) == 6:
                if expanded[5][0] != '*':
                    diff_sec = nearest_diff_method(d.second, expanded[5], 60)
                    if diff_sec is not None and diff_sec != 0:
                        d += relativedelta(seconds=diff_sec)
                        return True, d
            else:
                d += relativedelta(second=0)
            return False, d

        procs = [proc_month,
                 proc_day_of_month,
                 (proc_day_of_week_nth if nth_weekday_of_month
                     else proc_day_of_week),
                 proc_hour,
                 proc_minute,
                 proc_second]

        while abs(year - current_year) <= self._max_years_between_matches:
            next = False
            for proc in procs:
                (changed, dst) = proc(dst)
                if changed:
                    month, year = dst.month, dst.year
                    next = True
                    break
            dst = dst.replace(microsecond=0)
            # if a DST occurs during the 24 hours between result candidate
            # and selected original date:
            # we check if final candidate is occuring during
            # the one-hour DST transition.
            # In this case:
            #  Summer time (+1h delta): 2(-3)h -> 3h
            #    the algo is NEXTing: we add one hour for candidates between the window
            #    0 * * * * -> xxxx 0100
            #    0 * * * * -> xxxx 0300
            #    0 * * * * -> xxxx 0400
            #    0 * * * * -> xxxx 0500
            #    the algo is PREVing: we remove one hour for candidates between the window
            #    0 * * * * -> xxxx 0400
            #    0 * * * * -> xxxx 0300
            #    0 * * * * -> xxxx 0100
            #    0 * * * * -> xxxx 0000
            #  Winter time (+1h delta): 2(-3)h -> 1h
            #    the algo is NEXTing: we add 2 hours
            #    0 * * * * -> xxxx 0300
            #    0 * * * * -> xxxx 0600
            #    0 * * * * -> xxxx 0700
            #    the algo is PREVing: we remove two hour
            #    0 * * * * -> xxxx 0300
            #    0 * * * * -> xxxx 0100
            #    0 * * * * -> xxxx 0000
            if dst.tzinfo is not None:
                curdt = self._timestamp_to_datetime(self.cur)
                lowb, upb, is_summer = get_next_dst_window(curdt)
                ohl = dst + relativedelta(hours=1)
                if lowb is not None:
                    if (
                        is_summer and
                        ((curdt <= lowb and dst > lowb) or
                         (curdt < lowb and dst >= lowb))
                    ):
                        sign = is_prev and -1 or 1
                        dst += sign * relativedelta(hours=1)
                        next = False
                    elif (
                        not is_summer and
                        (curdt >= upb) and
                        (dst < lowb)
                    ):
                        sign = is_prev and -1 or 1
                        dst += sign * relativedelta(hours=1)
                        next = False
            if next:
                continue
            return self._datetime_to_timestamp(dst)

        if is_prev:
            raise CroniterBadDateError("failed to find prev date")
        raise CroniterBadDateError("failed to find next date")

    def _get_next_nearest(self, x, to_check):
        small = [item for item in to_check if item < x]
        large = [item for item in to_check if item >= x]
        large.extend(small)
        return large[0]

    def _get_prev_nearest(self, x, to_check):
        small = [item for item in to_check if item <= x]
        large = [item for item in to_check if item > x]
        small.reverse()
        large.reverse()
        small.extend(large)
        return small[0]

    def _get_next_nearest_diff(self, x, to_check, range_val):
        for i, d in enumerate(to_check):
            if d == "l":
                # if 'l' then it is the last day of month
                # => its value of range_val
                d = range_val
            if d >= x:
                return d - x
        return to_check[0] - x + range_val

    def _get_prev_nearest_diff(self, x, to_check, range_val):
        candidates = to_check[:]
        candidates.reverse()
        for d in candidates:
            if d != 'l' and d <= x:
                return d - x
        if 'l' in candidates:
            return -x
        candidate = candidates[0]
        for c in candidates:
            # fixed: c < range_val
            # this code will reject all 31 day of month, 12 month, 59 second,
            # 23 hour and so on.
            # if candidates has just a element, this will not harmful.
            # but candidates have multiple elements, then values equal to
            # range_val will rejected.
            if c <= range_val:
                candidate = c
                break

        return (candidate - x - range_val)

    def is_leap(self, year):
        if year % 400 == 0 or (year % 4 == 0 and year % 100 != 0):
            return True
        else:
            return False

    @classmethod
    def expand(cls, expr_format):
        expressions = expr_format.split()

        if len(expressions) not in VALID_LEN_EXPRESSION:
            raise CroniterBadCronError(cls.bad_length)

        expanded = []
        nth_weekday_of_month = {}

        for i, expr in enumerate(expressions):
            e_list = expr.split(',')
            res = []

            while len(e_list) > 0:
                e = e_list.pop()

                if i == 4:
                    e, sep, nth = str(e).partition('#')
                    if nth and not re.match(r'[1-5]', nth):
                        raise CroniterBadCronError(
                            "[{0}] is not acceptable".format(expr_format))

                t = re.sub(r'^\*(\/.+)$', r'%d-%d\1' % (
                    cls.RANGES[i][0],
                    cls.RANGES[i][1]),
                    str(e))
                m = search_re.search(t)

                if not m:
                    t = re.sub(r'^(.+)\/(.+)$', r'\1-%d/\2' % (
                        cls.RANGES[i][1]),
                        str(e))
                    m = step_search_re.search(t)

                if m:
                    (low, high, step) = m.group(1), m.group(2), m.group(4) or 1
                    if i == 2 and high == 'l':
                        high = '31'

                    if not any_int_re.search(low):
                        low = "{0}".format(cls._alphaconv(i, low, expressions))

                    if not any_int_re.search(high):
                        high = "{0}".format(cls._alphaconv(i, high, expressions))

                    if (
                        not low or not high or int(low) > int(high)
                        or not only_int_re.search(str(step))
                    ):
                        if i == 4 and high == '0':
                            # handle -Sun notation -> 7
                            high = '7'
                        else:
                            raise CroniterBadCronError(
                                "[{0}] is not acceptable".format(expr_format))

                    low, high, step = map(int, [low, high, step])
                    try:
                        rng = range(low, high + 1, step)
                    except ValueError as exc:
                        raise CroniterBadCronError(
                            'invalid range: {0}'.format(exc))
                    e_list += (["{0}#{1}".format(item, nth) for item in rng]
                               if i == 4 and nth else rng)
                else:
                    if t.startswith('-'):
                        raise CroniterBadCronError((
                            "[{0}] is not acceptable,"
                            "negative numbers not allowed"
                        ).format(expr_format))
                    if not star_or_int_re.search(t):
                        t = cls._alphaconv(i, t, expressions)

                    try:
                        t = int(t)
                    except ValueError:
                        pass

                    if t in cls.LOWMAP[i]:
                        t = cls.LOWMAP[i][t]

                    if (
                        t not in ["*", "l"]
                        and (int(t) < cls.RANGES[i][0] or
                             int(t) > cls.RANGES[i][1])
                    ):
                        raise CroniterBadCronError(
                            "[{0}] is not acceptable, out of range".format(
                                expr_format))

                    res.append(t)

                    if i == 4 and nth:
                        if t not in nth_weekday_of_month:
                            nth_weekday_of_month[t] = set()
                        nth_weekday_of_month[t].add(int(nth))

            res = set(res)
            res = natsort.natsorted(res)
            if len(res) == cls.LEN_MEANS_ALL[i]:
                res = ['*']

            expanded.append(['*'] if (len(res) == 1
                                      and res[0] == '*')
                            else res)

        return expanded, nth_weekday_of_month

    @classmethod
    def is_valid(cls, expression):
        try:
            cls.expand(expression)
        except CroniterError:
            return False
        else:
            return True

    @classmethod
    def match(cls, cron_expression, testdate, day_or=True):
        cron = cls(cron_expression, testdate, ret_type=datetime.datetime, day_or=day_or)
        td, ms1 = cron.get_current(datetime.datetime), relativedelta(microseconds=1)
        cron.set_current(td + ms1)
        tdp, tdt = cron.get_current(), cron.get_prev()
        return (max(tdp, tdt) - min(tdp, tdt)).total_seconds() < 60


def croniter_range(start, stop, expr_format, ret_type=None, day_or=True, exclude_ends=False):
    """
    Generator that provides all times from start to stop matching the given cron expression.
    If the cron expression matches either 'start' and/or 'stop', those times will be returned as
    well unless 'exclude_ends=True' is passed.

    You can think of this function as sibling to the builtin range function for datetime objects.
    Like range(start,stop,step), except that here 'step' is a cron expression.
    """
    auto_rt = datetime.datetime
    if type(start) != type(stop):
        raise TypeError("The start and stop must be same type.  {0} != {1}".
                        format(type(start), type(stop)))
    if isinstance(start, (float, int)):
        start, stop = (datetime.datetime.utcfromtimestamp(t) for t in (start, stop))
        auto_rt = float
    if ret_type is None:
        ret_type = auto_rt
    if not exclude_ends:
        ms1 = relativedelta(microseconds=1)
        if start < stop:    # Forward (normal) time order
            start -= ms1
            stop += ms1
        else:               # Reverse time order
            start += ms1
            stop -= ms1
    year_span = math.floor(abs(stop.year - start.year)) + 1
    ic = croniter(expr_format, start, ret_type=datetime.datetime, day_or=day_or,
                  max_years_between_matches=year_span)
    # define a continue (cont) condition function and step function for the main while loop
    if start < stop:        # Forward
        def cont(v):
            return v < stop
        step = ic.get_next
    else:                   # Reverse
        def cont(v):
            return v > stop
        step = ic.get_prev
    try:
        dt = step()
        while cont(dt):
            if ret_type is float:
                yield ic.get_current(float)
            else:
                yield dt
            dt = step()
    except CroniterBadDateError:
        # Stop iteration when this exception is raised; no match found within the given year range
        return
