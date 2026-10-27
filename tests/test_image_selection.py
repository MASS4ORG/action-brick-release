"""Regression tests for shared CLI selection, including partial-ingest retries."""

import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('resolve_image', Path(__file__).parents[1] / 'scripts/resolve_image.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
IMAGE = module.REPOSITORY + '@sha256:' + 'a' * 64
PACKAGE = 'org.mass4.turian.cameras'


class RegistryFixture:
    def __init__(self):
        self.calls = []

    def highest(self):
        self.calls.append('highest')
        return '9.10.0'

    def resolve(self, reference, expected):
        self.calls.append((reference, expected))
        return IMAGE


class SelectionTests(unittest.TestCase):
    def test_recorded_archive_download_requires_the_recorded_hash(self):
        payload = b'exact stored archive'
        import base64
        import hashlib
        record = {'id': '2dda8cc6-1276-402f-a30c-9d63550e348d', 'packageId': PACKAGE, 'version': '1.0.2',
                  'variant': 'source', 'integrity': 'sha256-' + base64.b64encode(hashlib.sha256(payload).digest()).decode()}
        for data, succeeds in [(payload, True), (b'corrupted', False)]:
            with self.subTest(succeeds=succeeds), tempfile.TemporaryDirectory() as directory:
                opener = type('Fixture', (), {'open': lambda self, *args, **kwargs: io.BytesIO(data)})()
                with patch.object(module.urllib.request, 'build_opener', return_value=opener):
                    if succeeds:
                        result = module.download_recorded('https://store.example', 'mass4_fixture', record, Path(directory))
                        self.assertTrue(result['available'])
                        self.assertEqual(payload, (Path(directory) / result['file']).read_bytes())
                    else:
                        with self.assertRaises(module.SelectionError):
                            module.download_recorded('https://store.example', 'mass4_fixture', record, Path(directory))
                        self.assertEqual([], list(Path(directory).iterdir()))

    def test_first_release_and_verify_use_same_stable_selection(self):
        registry = RegistryFixture()
        with patch.object(module, 'get_json', return_value=(module.NOT_FOUND, {})):
            first = module.select(package=PACKAGE, version='1.0.2', token='mass4_fixture', registry=registry)
            verify = module.select(registry=RegistryFixture())
        self.assertEqual(first, verify)
        self.assertEqual('highest-stable-semver', first['selection'])

    def test_pending_source_receipt_bypasses_newer_tags_and_covers_partial_publish(self):
        registry = RegistryFixture()
        seen = []
        def read(url, token='', **kwargs):
            seen.append((url, token))
            if url.endswith('variant=source'):
                return {'packageId': PACKAGE, 'version': '1.0.2', 'variant': 'source', 'status': 'pending',
                        'build': {'image': IMAGE, 'turianVersion': '3.4.0'}}, {}
            return module.NOT_FOUND, {}
        with patch.object(module, 'get_json', side_effect=read):
            selected = module.select('9.10.0', PACKAGE, '1.0.2', 'mass4_fixture', registry=registry)
        self.assertEqual('store-record', selected['selection'])
        self.assertEqual('3.4.0', selected['version'])
        self.assertEqual([('sha256:' + 'a' * 64, '3.4.0')], registry.calls)
        self.assertTrue(seen[-1][0].endswith('variant=turian3.4'))

    def test_exact_override_never_enumerates_tags(self):
        registry = RegistryFixture()
        result = module.select('3.5.0', registry=registry)
        self.assertEqual('exact-override', result['selection'])
        self.assertEqual([('3.5.0', '3.5.0')], registry.calls)

    def test_provenance_errors_never_become_first_publications(self):
        registry = RegistryFixture()
        with patch.object(module, 'get_json', side_effect=module.SelectionError('HTTP 503')):
            with self.assertRaises(module.SelectionError):
                module.select(package=PACKAGE, version='1.0.2', token='mass4_fixture', registry=registry)
        self.assertEqual([], registry.calls)

    def test_matching_twin_receipt_is_reused_and_conflicting_receipt_is_rejected(self):
        source = {'packageId': PACKAGE, 'version': '1.0.2', 'variant': 'source',
                  'build': {'image': IMAGE, 'turianVersion': '3.4.0'}}
        for twin_image in [IMAGE, module.REPOSITORY + '@sha256:' + 'b' * 64]:
            twin = {**source, 'variant': 'turian3.4', 'build': {**source['build'], 'image': twin_image}}
            with self.subTest(twin_image=twin_image), patch.object(module, 'get_json', side_effect=[(source, {}), (twin, {})]):
                if twin_image == IMAGE:
                    self.assertEqual(IMAGE, module.select(package=PACKAGE, version='1.0.2', token='mass4_fixture', registry=RegistryFixture())['image'])
                else:
                    with self.assertRaises(module.SelectionError):
                        module.select(package=PACKAGE, version='1.0.2', token='mass4_fixture', registry=RegistryFixture())

    def test_malformed_or_missing_recorded_build_never_falls_back(self):
        for value in [None, {'packageId': PACKAGE, 'version': '1.0.2', 'variant': 'source', 'build': None},
                      {'packageId': 'org.other.brick', 'version': '1.0.2', 'variant': 'source'}]:
            registry = RegistryFixture()
            with self.subTest(value=value), patch.object(module, 'get_json', return_value=(value, {})):
                with self.assertRaises(module.SelectionError):
                    module.select(package=PACKAGE, version='1.0.2', token='mass4_fixture', registry=registry)
            self.assertEqual([], registry.calls)

    def test_highest_uses_numeric_semver_excludes_mutable_and_prerelease_tags_and_paginates(self):
        registry = object.__new__(module.Registry)
        registry.token = 'registry-fixture'
        pages = [({'tags': ['latest', '9.9.9', 'v10.0.0', '10.0.0-rc.1', '01.0.0', '3.5']},
                  {'Link': '</v2/mass4org/turian-cli/tags/list?n=1000&last=x>; rel="next"'}),
                 ({'tags': ['10.0.0', '9.10.0', '10.0.0+meta']}, {})]
        with patch.object(module, 'get_json', side_effect=pages) as read:
            self.assertEqual('10.0.0', registry.highest())
            self.assertEqual(2, read.call_count)

    def test_no_stable_versions_is_a_failure(self):
        registry = object.__new__(module.Registry)
        registry.token = 'fixture'
        with patch.object(module, 'get_json', return_value=({'tags': ['latest', '3.5.0-beta.1']}, {})):
            with self.assertRaises(module.SelectionError):
                registry.highest()

    def test_version_label_must_match_selected_tag(self):
        registry = object.__new__(module.Registry)
        registry.token = 'fixture'
        with patch.object(registry, 'manifest', return_value=('sha256:' + 'a' * 64, {'config': {'digest': 'x'}})):
            with patch.object(module, 'get_json', return_value=({'config': {'Labels': {'org.opencontainers.image.version': '3.4.0'}}}, {})):
                with self.assertRaises(module.SelectionError):
                    registry.resolve('3.5.0', '3.5.0')

    def test_invalid_overrides_and_tokens_fail(self):
        for version in ['latest', 'main', 'v3.5.0', '3.5', '3.5.0-rc.1', '03.5.0']:
            with self.subTest(version=version), self.assertRaises(module.SelectionError):
                module.select(version, registry=RegistryFixture())
        self.assertEqual('mass4_fixture', module.store_token(json.dumps({'secret': 'mass4_fixture'})))
        for token in ['Bearer mass4_fixture', '{"secret":42}', 'mass4_fixture\ninjected']:
            with self.subTest(token=token), self.assertRaises(module.SelectionError):
                module.store_token(token)


if __name__ == '__main__':
    unittest.main()
