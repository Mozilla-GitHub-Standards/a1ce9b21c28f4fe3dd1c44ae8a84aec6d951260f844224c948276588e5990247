# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import requests
from . import utils
from .wiki_parser import InvalidWiki, WikiParser


CALENDAR_URL = 'https://wiki.mozilla.org/Release_Management/Calendar'
_CALENDAR = None


def _get_sub_versions(s):
    s = s.strip()
    s = s.split('.')
    return [int(v.split(' ')[0]) for v in s]


def get_versions(s):
    fx = 'Firefox '
    if not s.startswith(fx):
        raise InvalidWiki('Invalid version format, expect: \"Firefox ...\"')
    version = s[len(fx):]
    versions = version.split(';')
    return [_get_sub_versions(v) for v in versions]


def get_calendar():
    global _CALENDAR
    if _CALENDAR is not None:
        return _CALENDAR

    html = requests.get(CALENDAR_URL).text.encode('ascii', errors='ignore')
    parser = WikiParser(tables=[0])
    try:
        parser.feed(html)
    except StopIteration:
        table = parser.get_tables()[0]
        if [
            'Quarter',
            'Soft Freeze',
            'Merge Date',
            'Central',
            'Beta',
            'Release Date',
            'Release',
            'ESR',
        ] != table[0]:
            raise InvalidWiki('Column headers are wrong')

        _CALENDAR = []
        for row in table[1:]:
            # some row headers are spanning on several rows
            # and then the first raw has a 'Q...' (for the quarter)
            # but not the next ones. So just remove it since it's useless.
            if row[0].startswith('Q'):
                row = row[1:]
            _CALENDAR.append(
                {
                    'soft freeze': utils.get_date_ymd(row[0]),
                    'merge': utils.get_date_ymd(row[1]),
                    'central': get_versions(row[2])[0][0],
                    'beta': get_versions(row[3])[0][0],
                    'release date': utils.get_date_ymd(row[4]),
                    'release': get_versions(row[5])[0][0],
                    'esr': get_versions(row[6]),
                }
            )
        return _CALENDAR


def get_next_release_date():
    cal = get_calendar()
    now = utils.get_date_ymd('today')
    for c in cal:
        if now < c['release date']:
            return c['release date']
    return None
