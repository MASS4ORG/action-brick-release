import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('workflow_check', Path(__file__).parents[1] / 'scripts/check.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CheckTests(unittest.TestCase):
    def check_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'action.yml').write_text(text)
            return module.check(root)

    def test_unpinned_or_unlabelled_external_actions_are_rejected(self):
        for reference in ['actions/checkout@v7', 'actions/checkout@' + 'a' * 39,
                          'actions/checkout@' + 'a' * 40, 'docker://rhysd/actionlint:1.7.12']:
            with self.subTest(reference=reference):
                self.assertTrue(self.check_text('  - uses: ' + reference + '\n'))
        self.assertTrue(self.check_text('- "uses": actions/checkout@v7\n'))
        self.assertTrue(self.check_text('- {uses: actions/checkout@v7}\n'))
        self.assertTrue(self.check_text('steps: [{uses: MASS4ORG/brick-action-build@v1}, {uses: actions/checkout@v7}]\n'))

    def test_exact_pins_internal_v1_and_local_actions_are_accepted(self):
        text = '- uses: actions/checkout@' + 'a' * 40 + ' # v7.0.1\n'
        text += '- uses: MASS4ORG/brick-action-build@v1\n- uses: ./local\n'
        self.assertEqual([], self.check_text(text))

    def test_fixed_cli_defaults_are_rejected(self):
        self.assertTrue(self.check_text('IMAGE: ghcr.io/mass4org/turian-cli:3.4.0@sha256:' + 'a' * 64))
        self.assertTrue(self.check_text('PINNED_IMAGE: anything'))

    def test_legitimate_gitlab_pin_must_match_shared_template(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.github').mkdir()
            image = 'ghcr.io/mass4org/turian-cli@sha256:' + 'a' * 64
            (root / '.github/cli-pins.json').write_text(json.dumps({'gitlab-template': image}))
            template = root / 'template.yml'
            template.write_text('  TURIAN_CLI_IMAGE: ' + image + '\n')
            self.assertEqual([], module.check(root, template))
            template.write_text('  TURIAN_CLI_IMAGE: ' + image.replace('a' * 64, 'b' * 64) + '\n')
            self.assertTrue(module.check(root, template))
