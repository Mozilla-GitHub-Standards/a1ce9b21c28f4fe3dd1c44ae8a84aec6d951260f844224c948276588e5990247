import base64
import re
from datetime import (date, timedelta)
try:
    from urllib.request import urlopen
except ImportError:
    from urllib import urlopen
import weakref
import whatthepatch
from .HGFileInfo import HGFileInfo
from .bugzilla import Bugzilla
from . import modules
from . import utils

hginfos = weakref.WeakValueDictionary()


def check_module(path, used_modules):
    module = modules.module_from_path(path)
    if module and module['name'] not in used_modules:
        used_modules[module['name']] = 1


def churn(path):
    if path in hginfos:
        hi = hginfos[path]
    else:
        hi = hginfos[path] = HGFileInfo(path)

    return {
        'overall': len(hi.get(path)['patches']),
        'last_3_releases': len(hi.get(path, utc_ts_from=utils.get_timestamp(date.today() + timedelta(-3 * 6 * 7)))['patches']),
    }


def patch_analysis(patch):
    info = {
        'changes_size': 0,
        'modules_num': 0,
        'code_churn_overall': 0,
        'code_churn_last_3_releases': 0,
        # 'developer_familiarity_overall': 0,
        # 'developer_familiarity_last_3_releases': 0,
        # 'reviewer_familiarity_overall': 0,
        # 'developer_familiarity_last_3_releases': 0,
    }

    used_modules = {}

    for diff in whatthepatch.parse_patch(patch):
        info['changes_size'] += len(diff.changes)

        old_path = diff.header.old_path[2:] if diff.header.old_path.startswith('a/') else diff.header.old_path
        new_path = diff.header.new_path[2:] if diff.header.new_path.startswith('b/') else diff.header.new_path

        if old_path != '/dev/null' and old_path != new_path:
            check_module(old_path, used_modules)
            code_churn = churn(old_path)
            info['code_churn_overall'] += code_churn['overall']
            info['code_churn_last_3_releases'] += code_churn['last_3_releases']

        if new_path != '/dev/null':
            check_module(old_path, used_modules)
            code_churn = churn(old_path)
            info['code_churn_overall'] += code_churn['overall']
            info['code_churn_last_3_releases'] += code_churn['last_3_releases']

        # TODO: Add number of times the file was modified by the developer or the reviewer.

    info['modules_num'] = sum(used_modules.values())

    # TODO: Add number of times the modified functions appear in crash signatures.

    # TODO: Add coverage info before and after the patch.

    return info


MOZREVIEW_URL_PATTERN = 'https://reviewboard.mozilla.org/r/([0-9]+)/diff/#index_header'
MOZREVIEW_URL_PATTERN2 = 'https://reviewboard.mozilla.org/r/([0-9]+)/'


# TODO: Consider feedback+ and feedback- as review+ and review-
def bug_analysis(bug_id):
    bug = {}

    def bughandler(found_bug, data):
        bug.update(found_bug)

    def commenthandler(found_bug, bugid, data):
        bug['comments'] = found_bug['comments']

    def attachmenthandler(attachments, bugid, data):
        bug['attachments'] = attachments

    INCLUDE_FIELDS = [
        'id', 'flags', 'depends_on', 'keywords', 'blocks', 'whiteboard', 'resolution', 'status',
        'url', 'version', 'summary', 'priority', 'product', 'component', 'severity',
        'platform', 'op_sys'
    ]

    INCLUDE_FIELDS_QUERY = 'include_fields=' + ','.join(INCLUDE_FIELDS)

    Bugzilla('id=' + str(bug_id) + '&' + INCLUDE_FIELDS_QUERY, bughandler=bughandler, commenthandler=commenthandler, attachmenthandler=attachmenthandler).get_data().wait()

    info = {
        'backout_num': 0,
        'blocks': len(bug['blocks']),
        'depends_on': len(bug['depends_on']),
        'comments': len(bug['comments']),
        'r-ed_patches': sum((a['is_patch'] == 1 or a['content_type'] == 'text/x-review-board-request') and sum(flag['name'] == 'review' and flag['status'] == '-' for flag in a['flags']) > 0 for a in bug['attachments']),
    }

    # Assume all non-obsolete and r+ed patches have landed.
    # TODO: Evaluate if reading comments to see what landed is better.
    for attachment in bug['attachments']:
        if sum(flag['name'] == 'review' and flag['status'] == '+' for flag in attachment['flags']) == 0:
            continue

        data = None

        if attachment['is_patch'] == 1 and attachment['is_obsolete'] == 0:
            data = base64.b64decode(attachment['data']).decode('ascii', 'ignore')
        elif attachment['content_type'] == 'text/x-review-board-request' and attachment['is_obsolete'] == 0:
            mozreview_url = base64.b64decode(attachment['data']).decode('utf-8')

            try:
                review_num = re.search(MOZREVIEW_URL_PATTERN, mozreview_url).group(1)
            except:
                review_num = re.search(MOZREVIEW_URL_PATTERN2, mozreview_url).group(1)

            mozreview_raw_diff_url = 'https://reviewboard.mozilla.org/r/' + review_num + '/diff/raw/'

            response = urlopen(mozreview_raw_diff_url)
            data = response.read().decode('ascii', 'ignore')

        if data is not None:
            info.update(patch_analysis(data))

    # TODO: Use a more clever way to check if the patch was backed out.
    for comment in bug['comments']:
        if 'backed out' in comment['text'].lower():
            info['backout_num'] += 1

    return info