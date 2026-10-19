"""Release-discovery regressions: do not depend on GitHub's stale 'latest' flag."""
import json
import unittest
from unittest.mock import patch

from orbit_update import UpdateError
from orbit_update_full import latest_snapshot_release


def release(version, *, ready=True, draft=False, prerelease=False):
    name='ORBITclip_CleanInstall_v'+version.replace('.','_')+'.zip'
    return {
        'tag_name':'v'+version,'draft':draft,'prerelease':prerelease,
        'assets':[{'name':name,'size':250000,
                   'url':'https://api.github.com/repos/Wolchau/ORBITclip/releases/assets/123',
                   'digest':'sha256:'+'a'*64}] if ready else []
    }


class ReleaseDiscoveryTests(unittest.TestCase):
    def get(self,current,items):
        with patch('orbit_update_full._get_bytes',return_value=json.dumps(items).encode()) as fetch:
            result=latest_snapshot_release(current)
            self.assertIn('/releases?per_page=50',fetch.call_args.args[0])
            self.assertNotIn('/releases/latest',fetch.call_args.args[0])
            return result

    def test_latest_release_flag_cannot_hide_newer_tag(self):
        entries=[release('7.8.3'),release('7.8.4'),release('7.7.1')]
        entries[0]['make_latest']='true'
        result=self.get('7.8.3',entries)
        self.assertEqual(result['version'],'7.8.4')

    def test_out_of_order_version_and_prerelease(self):
        entries=[release('7.8.5'),release('7.9.0',prerelease=True),
                 release('7.8.4'),release('7.8.3'),release('7.9.1',draft=True)]
        self.assertEqual(self.get('7.8.2',entries)['version'],'7.8.5')

    def test_skip_versions_select_latest_complete_release(self):
        result=self.get('7.8.2',[release('7.8.3'),release('7.8.4'),release('7.8.5')])
        self.assertEqual(result['version'],'7.8.5')
        self.assertIn('/releases/assets/',result['url'])

    def test_missing_newest_zip_is_error_not_false_up_to_date(self):
        with self.assertRaisesRegex(UpdateError,'7.8.5'):
            self.get('7.8.3',[release('7.8.5',ready=False),release('7.8.4')])

    def test_no_new_release_is_none(self):
        self.assertIsNone(self.get('7.8.4',[release('7.8.4'),release('7.8.3')]))

    def test_empty_or_malformed_payload_is_not_latest(self):
        self.assertIsNone(self.get('7.8.3',[]))
        with self.assertRaises(UpdateError):
            self.get('7.8.3',{'unexpected':'response'})

    def test_invalid_tags_do_not_erase_stable_versions(self):
        entries=[{'tag_name':'preview', 'assets':[]},release('7.8.4'),
                 {'tag_name':'v7.8.5-rc1', 'assets':[]}]
        self.assertEqual(self.get('7.8.3',entries)['version'],'7.8.4')


if __name__=='__main__':unittest.main()
