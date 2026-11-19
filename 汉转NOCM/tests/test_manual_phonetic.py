"""Per-occurrence manual IPA: persistence, precedence and export contracts."""

import copy
from contextlib import ExitStack
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import draft_io
import web_api
from editor_buffer import EditorBuffer
from nocm_transcriber import migrate_scheme_data


class ManualPhoneticTests(unittest.TestCase):
    def setUp(self):
        self.scheme, _ = migrate_scheme_data({
            'maps': {
                'onset': {'t': 't', 'l': 'l'},
                'nucleus': {'u': 'u', 'i': 'i', 'ə': 'ə'},
                'coda': {'n': 'n', 'ŋ': 'ŋ'},
                'tone': {'k': 'k', 'ʔ': 'ʔ'},
            },
            'options': {'dialect_xitu': True, 'dialect_xitu_shang_k': True},
        })
        self.saved = []
        patches = [
            patch('web_api._load_ui_preferences', return_value={}),
            patch('web_api._set_ui_state_value'),
            patch('web_api.get_current_data_revision', return_value='2026-11-19 00:00:00'),
            patch('web_api.get_reading_change_events', return_value={}),
            patch('web_api.load_preferred_scheme_id', return_value='test'),
            patch('web_api.load_scheme', side_effect=lambda _: copy.deepcopy(self.scheme)),
            patch('web_api.get_draft_name', return_value='测试'),
            patch('web_api.save_draft', side_effect=self.save),
            patch('web_api.list_schemes', return_value=[]),
            patch('web_api._draft_library_snapshot', return_value=([], [])),
            patch('web_api.get_groups', return_value=[]),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.api = web_api.WebApi({
            '甲': [{'phonetic': 'tuk'}, {'phonetic': 'li'}],
            '乙': [{'phonetic': 'lən'}],
        })
        self.api.buf.insert_chars_raw('甲甲乙')

    def save(self, filename, name, buffer, cell_info, *args, **kwargs):
        self.saved.append(copy.deepcopy(cell_info))
        return filename or 'test.json'

    def test_local_override_preserves_source_and_outranks_sound_changes(self):
        result = self.api.set_manual_phonetic(0, 0, 'tik')
        cell, other = result['lines'][0][:2]
        self.assertEqual(cell['phonetic'], 'tuk')
        self.assertEqual(cell['dialect_phonetic'], 'tuʔ')
        self.assertEqual(cell['manual_phonetic'], 'tik')
        self.assertEqual(cell['effective_phonetic'], 'tik')
        self.assertEqual(other['manual_phonetic'], '')
        self.assertEqual(other['effective_phonetic'], 'tuʔ')
        self.assertEqual(self.saved[-1][0][0]['manual_phonetic'], 'tik')
        self.assertNotIn('manual_phonetic', self.api.mapping['甲'][0])
        details = self.api.get_cell_details(0, 0)
        self.assertEqual(details['effective_phonetic'], 'tik')
        self.assertEqual(details['phonetic'], 'tuk')

    def test_reset_undo_redo_and_noop(self):
        self.api.set_manual_phonetic(0, 0, 'tiŋ')
        depth = len(self.api.buf.undo_stack)
        self.api.set_manual_phonetic(0, 0, 'tiŋ')
        self.assertEqual(len(self.api.buf.undo_stack), depth)
        self.assertEqual(self.api.editor_action('undo')['lines'][0][0]['manual_phonetic'], '')
        self.assertEqual(self.api.editor_action('redo')['lines'][0][0]['manual_phonetic'], 'tiŋ')
        reset = self.api.set_manual_phonetic(0, 0, '')['lines'][0][0]
        self.assertEqual(reset['manual_phonetic'], '')
        self.assertEqual(reset['effective_phonetic'], 'tuʔ')
        self.assertEqual(self.api.editor_action('undo')['lines'][0][0]['manual_phonetic'], 'tiŋ')

    def test_text_suno_combined_copy_and_image_use_override(self):
        self.api.set_manual_phonetic(0, 0, 'tik')
        self.assertEqual(self.api.export_text('phon'), 'tik tuʔ lən')
        self.assertEqual(self.api.export_text('suno'), 'tik tuʔ lən')
        self.assertIn('tik tuʔ lən', self.api.export_text('raw+phon+suno'))
        self.api.buf.sel_anchor = (0, 0)
        self.api.buf.cur_line, self.api.buf.cur_col = 0, 1
        self.assertEqual(self.api.get_phonetic_text(True), 'tik')
        image = self.api.get_image_export_data()['lines'][0]['cells']
        self.assertEqual(image[0]['phonetic'], 'tik')
        self.assertEqual(image[0]['manual_phonetic'], 'tik')
        self.assertFalse(image[0]['dialect_changed'])
        self.assertTrue(image[1]['dialect_changed'])
        self.assertEqual(self.api.export_text('raw'), '甲甲乙')

    def test_copy_payload_moves_override_with_character(self):
        self.api.set_manual_phonetic(0, 0, 'tiŋ')
        self.api.buf.sel_anchor = (0, 0)
        self.api.buf.cur_line, self.api.buf.cur_col = 0, 1
        payload = self.api.get_copy_payload(True)
        target = EditorBuffer(self.api.mapping)
        target.insert_chars_raw('乙\n')
        target.insert_payload(payload)
        self.assertEqual(target.cell_info[1][0]['manual_phonetic'], 'tiŋ')
        self.assertEqual(target.cell_info[1][0]['phonetic'], 'tuk')
        self.api.buf = target
        self.assertEqual(self.api.get_editor()['lines'][1][0]['effective_phonetic'], 'tiŋ')

    def test_phonetic_replace_edits_override_not_hidden_source(self):
        self.api.set_manual_phonetic(0, 0, 'tiŋ')
        result = self.api.replace_text('i', 'u', True, 'phon')
        self.assertEqual(result['count'], 1)
        cell = result['editor']['lines'][0][0]
        self.assertEqual(cell['phonetic'], 'tuk')
        self.assertEqual(cell['manual_phonetic'], 'tuŋ')
        self.assertEqual(cell['effective_phonetic'], 'tuŋ')

    def test_choose_reading_clears_override_and_undo_restores_it(self):
        self.api.set_manual_phonetic(0, 0, 'tiŋ')
        result = self.api.apply_reading(0, 0, 'li')
        self.assertEqual(result['lines'][0][0]['manual_phonetic'], '')
        self.assertEqual(result['lines'][0][0]['effective_phonetic'], 'li')
        self.assertEqual(self.api.editor_action('undo')['lines'][0][0]['manual_phonetic'], 'tiŋ')

    def test_global_reading_protects_another_manual_override(self):
        self.api.set_manual_phonetic(0, 1, 'tiŋ')
        self.assertEqual(self.api.reading_conflicts(0, 0, 'li')[0]['phonetic'], 'tiŋ')
        self.api.apply_reading(0, 0, 'li', True)
        self.assertEqual(self.api.get_editor()['lines'][0][1]['manual_phonetic'], 'tiŋ')
        self.api.apply_reading(0, 0, 'li', True, True)
        self.assertEqual(self.api.get_editor()['lines'][0][1]['manual_phonetic'], '')

    def test_bracket_contents_are_never_overridden(self):
        self.api.buf = EditorBuffer(self.api.mapping)
        self.api.buf.insert_chars_raw('[甲]甲')
        with self.assertRaises(ValueError):
            self.api.set_manual_phonetic(0, 1, 'ti')
        # Even an old payload containing an override inside [] stays untouched.
        self.api.buf.cell_info[0][1]['manual_phonetic'] = 'ti'
        self.api.set_manual_phonetic(0, 3, 'ti')
        self.assertEqual(self.api.export_text('phon'), '[甲] ti')
        self.assertEqual(self.api.get_cell_details(0, 1)['manual_phonetic'], '')
        self.assertEqual(self.api.get_editor()['lines'][0][1]['manual_phonetic'], '')
        self.assertEqual(len(self.api.get_image_export_data()['lines'][0]['cells']), 1)

    def test_invalid_input_and_stale_target_do_not_change_state(self):
        for value in ('t i', 't\ni', 't\x00i', 'a' * 129, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.api.set_manual_phonetic(0, 0, value)
        for args in ((-1, 0, 'ti'), (0, 99, 'ti'),
                     (0, 0, 'ti', '乙'), (0, 0, 'ti', '甲', 'old'),
                     (0, 0, 'ti', '甲', 'tuk', 'another.json')):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.api.set_manual_phonetic(*args)
        self.assertEqual(self.api.buf.undo_stack, [])
        self.assertEqual(self.saved, [])

    def test_optional_ipa_segments_and_unrecorded_character(self):
        self.api.buf.insert_chars_raw('龘')
        result = self.api.set_manual_phonetic(0, 3, 'ti[ŋ]')
        self.assertFalse(result['lines'][0][3]['missing_phonetic'])
        self.assertEqual(result['lines'][0][3]['effective_phonetic'], 'ti[ŋ]')
        self.assertEqual(self.api.get_cell_details(0, 3)['options'], [])


class ManualPhoneticPersistenceTests(unittest.TestCase):
    def test_save_reload_history_and_completion_keep_override(self):
        with tempfile.TemporaryDirectory() as root:
            patches = {
                'DRAFTS_DIR': root,
                '_DRAFTS_ORDER_FILE': os.path.join(root, '_order.json'),
                '_DRAFTS_RECENT_FILE': os.path.join(root, '_recent.json'),
                '_DRAFT_HISTORY_DIR': os.path.join(root, '_history'),
            }
            with ExitStack() as stack:
                for key, value in patches.items():
                    stack.enter_context(patch.object(draft_io, key, value))
                infos = [[{'phonetic': 'tuk', 'is_poly': True,
                           'selected': 'none', 'manual_phonetic': 'tiŋ'}]]
                name = draft_io.save_draft(None, '手动', [['甲']], infos)
                _, loaded = draft_io.load_draft(name, {'甲': [{'phonetic': 'new'}]})
                self.assertEqual(loaded[0][0]['phonetic'], 'tuk')
                self.assertEqual(loaded[0][0]['manual_phonetic'], 'tiŋ')
                self.assertEqual(draft_io.list_drafts()[0]['unselected_polyphonic'], 0)
                infos[0][0].pop('manual_phonetic')
                draft_io.save_draft(name, '手动', [['甲']], infos, create_history=True)
                self.assertEqual(draft_io.list_drafts()[0]['unselected_polyphonic'], 1)
                history = draft_io.list_draft_history(name)
                draft_io.restore_draft_history(name, history[0]['id'])
                self.assertEqual(draft_io.load_draft(name, {})[1][0][0]['manual_phonetic'], 'tiŋ')

    def test_frontend_has_distinct_colors_and_reset_entry(self):
        root = Path(__file__).resolve().parent.parent
        script = (root / 'web/app.js').read_text(encoding='utf-8')
        styles = (root / 'web/styles.css').read_text(encoding='utf-8')
        self.assertIn('edit-manual-phonetic', script)
        self.assertIn('reset-manual-phonetic', script)
        self.assertIn('aria-label="修改音标"', script)
        self.assertIn('aria-label="恢复自动"', script)
        self.assertIn('class="inspector-reading-row">${readingControl}${manualActions}', script)
        self.assertIn('cell.manual_phonetic ? colors.manualPhonetic', script)
        self.assertIn('--manual-phonetic: #8050a8', styles)
        self.assertIn('--manual-phonetic: #c5a0ec', styles)
        self.assertIn('.image-line-mini-cell.manual-phonetic > small', styles)


if __name__ == '__main__':
    unittest.main()
