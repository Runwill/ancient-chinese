"""Retired spelling presets cannot alter user-defined mappings or add hidden h."""

import copy
import unittest

from nocm_transcriber import NocmTranscriber, migrate_scheme_data


class RetiredSpellingTests(unittest.TestCase):
    def test_migration_removes_all_retired_metadata_without_touching_maps(self):
        for style in ('nasal', 'english', 'custom'):
            with self.subTest(style=style):
                old = {
                    'maps': {'onset': {'b': 'B', 'd': 'D', 'g': 'G', 'm̥': 'hm'},
                             'nucleus': {'a': 'a'}},
                    'parse_order': {'onset': ['m̥', 'b', 'd', 'g']},
                    'options': {'voiced_stop_style': style,
                                'extra_h_voiceless_sonorant': True,
                                'english_voiced_stops': True,
                                'improve_pharyngeal': True},
                    'option_definitions': {key: {'label': key} for key in (
                        'voiced_stop_style', 'extra_h_voiceless_sonorant',
                        'english_voiced_stops')},
                    'labels': {'voiced_stop_style': 'old', 'onset': {'b': '保留'}},
                    'rules': {'pharyngeal_relax': [['Ba', 'YES', '保留说明']]},
                }
                before = copy.deepcopy(old)
                scheme, changed = migrate_scheme_data(old)
                self.assertTrue(changed)
                for key in ('voiced_stop_style', 'extra_h_voiceless_sonorant',
                            'english_voiced_stops'):
                    for field in ('options', 'option_definitions', 'labels'):
                        self.assertNotIn(key, scheme[field])
                for field in ('maps', 'parse_order', 'rules'):
                    self.assertEqual(scheme[field], before[field])
                self.assertEqual(scheme['labels']['onset'], {'b': '保留'})
                self.assertEqual(NocmTranscriber(scheme).convert_text('ba da ga m̥a'),
                                 'YES Da Ga hma')
                second, changed = migrate_scheme_data(scheme)
                self.assertFalse(changed)
                self.assertEqual(second, scheme)

    def test_retired_extra_h_has_no_effect_even_without_migration(self):
        scheme = {
            'maps': {'onset': {'m̥': 'hm', 'n̥': 'hn', 'r̥': 'R', 'l̥': 'hl', 'ŋ̊': 'hN'},
                     'nucleus': {'a': 'a'}},
            'options': {'extra_h_voiceless_sonorant': True},
        }
        self.assertEqual(NocmTranscriber(scheme).convert_text('m̥a n̥a r̥a l̥a ŋ̊a [m̥a]'),
                         'hma hna Ra hla hNa [m̥a]')

    def test_relocated_rule_switches_still_control_their_own_rules(self):
        base = {'maps': {'onset': {'b': 'B'}, 'nucleus': {'a': 'a'}},
                'rules': {'pharyngeal_relax': [['Ba', 'Pa']],
                          'syllable_relax': [['Pa', 'Sa'], ['Ba', 'Xa']]}}
        for pharyngeal, syllable, expected in (
                (False, False, 'Ba'), (True, False, 'Pa'),
                (False, True, 'Xa'), (True, True, 'Sa')):
            with self.subTest(pharyngeal=pharyngeal, syllable=syllable):
                scheme = copy.deepcopy(base)
                scheme['options'] = {'improve_pharyngeal': pharyngeal,
                                     'improve_syllable': syllable}
                self.assertEqual(NocmTranscriber(scheme).convert_text('ba'), expected)


if __name__ == '__main__':
    unittest.main()
