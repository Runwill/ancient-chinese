"""Regression tests for the HTML bridge's state-sensitive editor actions."""

import base64
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import web_api
import runtime_log
from web_api import WebApi


class WebApiEditorTests(unittest.TestCase):
    def setUp(self):
        self.saved = []
        self.save_patch = patch(
            'web_api.save_draft', side_effect=self._save_draft)
        self.name_patch = patch(
            'web_api.get_draft_name', return_value='测试文稿')
        self.ui_state_patch = patch('web_api._set_ui_state_value')
        self.save_patch.start()
        self.name_patch.start()
        self.ui_state_mock = self.ui_state_patch.start()
        self.addCleanup(self.save_patch.stop)
        self.addCleanup(self.name_patch.stop)
        self.addCleanup(self.ui_state_patch.stop)
        self.api = WebApi({
            'x': [
                {'phonetic': 'x1', 'note': 'first'},
                {'phonetic': 'x2', 'note': 'second'},
            ],
            'y': [{'phonetic': 'y1'}],
        })

    def test_update_download_runs_in_background_and_reports_progress(self):
        def fake_download(on_progress=None):
            on_progress({
                'phase': 'downloading', 'message': '正在下载安装包…',
                'progress': 50, 'downloaded': 5, 'total': 10,
            })
            time.sleep(0.02)
            return {
                'ok': True, 'path': 'update.apk', 'version': '9.8.7',
                'platform': 'android',
            }

        with patch('web_api.download_update', side_effect=fake_download):
            started = self.api.start_update_download('9.8.7')
            self.assertIn(started['phase'], ('checking', 'downloading'))
            for _ in range(50):
                status = self.api.get_update_download_status()
                if status['phase'] == 'ready':
                    break
                time.sleep(0.01)

        self.assertEqual(status['phase'], 'ready')
        self.assertEqual(status['result']['path'], 'update.apk')

    def test_update_check_runs_in_background(self):
        started = threading.Event()
        release = threading.Event()

        def fake_check():
            started.set()
            release.wait(1)
            return {
                'ok': True, 'current': '0.12.11', 'latest': '0.12.11',
                'available': False,
            }

        with patch('web_api.check_for_updates', side_effect=fake_check):
            status = self.api.start_update_check()
            self.assertTrue(started.wait(.5))
            self.assertEqual(status['phase'], 'checking')
            self.assertEqual(
                self.api.start_update_check()['phase'], 'checking')
            release.set()
            for _ in range(50):
                status = self.api.get_update_check_status()
                if status['phase'] == 'ready':
                    break
                time.sleep(.01)

        self.assertEqual(status['phase'], 'ready')
        self.assertFalse(status['result']['available'])

    def test_backend_output_can_be_viewed_and_cleared(self):
        runtime_log.clear_runtime_logs()
        self.addCleanup(runtime_log.clear_runtime_logs)
        runtime_log.write_runtime_log('后台测试输出')

        snapshot = self.api.get_backend_logs()
        self.assertIn('后台测试输出', snapshot['text'])
        self.assertGreater(snapshot['characters'], 0)

        cleared = self.api.clear_backend_logs()
        self.assertEqual(cleared['text'], '')
        self.assertEqual(cleared['characters'], 0)

    def test_desktop_window_controls_use_attached_window(self):
        window = Mock()
        with patch.object(web_api, '_APP_WINDOW', window):
            self.api.minimize_window()
            maximized = self.api.toggle_maximize_window()
            restored = self.api.toggle_maximize_window()

        window.minimize.assert_called_once_with()
        window.maximize.assert_called_once_with()
        window.restore.assert_called_once_with()
        self.assertTrue(maximized['maximized'])
        self.assertFalse(restored['maximized'])

    def _save_draft(self, filename, name, buffer, _cell_info,
                    _editor_state=None, create_history=False):
        filename = filename or 'test.json'
        self.saved.append({
            'filename': filename,
            'name': name,
            'text': '\n'.join(''.join(line) for line in buffer),
            'history': create_history,
        })
        return filename

    def test_edits_are_saved_immediately(self):
        editor = self.api.insert_text('xy\nx')

        self.assertEqual(editor['raw'], 'xy\nx')
        self.assertEqual(editor['current_draft'], 'test.json')
        self.assertFalse(editor['dirty'])
        self.assertEqual(self.saved[-1]['text'], 'xy\nx')

    def test_rich_copy_paste_preserves_selected_reading(self):
        self.api.insert_text('xy\nx')
        self.api.apply_reading(0, 0, 'x2', True, True)
        self.api.set_caret(0, 0)
        self.api.set_caret(0, 1, True)
        payload = self.api.get_copy_payload(True)
        self.api.set_caret(1, 1)

        editor = self.api.insert_text(payload['text'], payload)

        pasted = editor['lines'][1][1]
        self.assertEqual(pasted['phonetic'], 'x2')
        self.assertEqual(pasted['selected'], 'manual')
        self.assertEqual(self.saved[-1]['text'], 'xy\nxx')

    def test_multiline_rich_paste_preserves_selected_readings(self):
        self.api.insert_text('xy\nxx')
        self.api.apply_reading(0, 0, 'x2')
        self.api.apply_reading(1, 0, 'x2')
        self.api.set_caret(0, 0)
        self.api.set_caret(1, 2, True)
        payload = self.api.get_copy_payload(True)
        self.api.set_caret(1, 2)

        editor = self.api.insert_text(payload['text'], payload)

        self.assertEqual(editor['lines'][1][2]['phonetic'], 'x2')
        self.assertEqual(editor['lines'][1][2]['selected'], 'manual')
        self.assertEqual(editor['lines'][2][0]['phonetic'], 'x2')
        self.assertEqual(editor['lines'][2][0]['selected'], 'manual')

    def test_external_text_rebuilds_pronunciation_from_mapping(self):
        self.api.insert_text('x')
        self.api.apply_reading(0, 0, 'x2', False, False)
        self.api.set_caret(0, 1)

        editor = self.api.insert_text('x', None)

        self.assertEqual(editor['lines'][0][1]['phonetic'], 'x1')
        self.assertEqual(editor['lines'][0][1]['selected'], 'none')

    def test_undo_and_redo_are_persisted(self):
        self.api.insert_text('xy')
        self.api.editor_action('backspace')

        undone = self.api.editor_action('undo')
        redone = self.api.editor_action('redo')

        self.assertEqual(undone['raw'], 'xy')
        self.assertEqual(redone['raw'], 'x')
        self.assertEqual(self.saved[-1]['text'], 'x')

    def test_raw_replace_preserves_unmodified_polyphonic_state(self):
        self.api.insert_text('xyx')
        self.api.apply_reading(0, 0, 'x2', False, False)

        result = self.api.replace_text('y', 'yy', True, 'char', 0, 1)

        self.assertEqual(result['count'], 1)
        self.assertEqual(result['editor']['raw'], 'xyyx')
        self.assertEqual(result['editor']['lines'][0][0]['phonetic'], 'x2')
        self.assertEqual(result['editor']['lines'][0][0]['selected'], 'manual')

    def test_phonetic_replace_marks_reading_manual(self):
        self.api.insert_text('x')

        result = self.api.replace_text('x1', 'custom', False, 'phon', 0, 0)

        self.assertEqual(result['editor']['lines'][0][0]['phonetic'], 'custom')
        self.assertEqual(result['editor']['lines'][0][0]['selected'], 'manual')

    def test_polyphonic_summary_and_batch_apply(self):
        self.api.insert_text('xx')
        summary = self.api.get_polyphonic_summary()

        editor = self.api.batch_apply_reading('x', 'x2', True)

        self.assertEqual(summary[0]['count'], 2)
        self.assertTrue(all(cell['phonetic'] == 'x2'
                            for cell in editor['lines'][0]))

    def test_global_apply_preserves_same_manual_reading(self):
        self.api.insert_text('xx')
        self.api.apply_reading(0, 1, 'x2')

        editor = self.api.apply_reading(0, 0, 'x2', True, True)

        self.assertEqual(editor['lines'][0][0]['selected'], 'manual')
        self.assertEqual(editor['lines'][0][1]['selected'], 'manual')

    def test_global_apply_skips_selected_conflict_positions(self):
        self.api.insert_text('xxx')
        self.api.apply_reading(0, 1, 'x2')
        self.api.apply_reading(0, 2, 'x2')

        editor = self.api.apply_reading(
            0, 0, 'x1', True, True, [[0, 1]])

        self.assertEqual(editor['lines'][0][1]['phonetic'], 'x2')
        self.assertEqual(editor['lines'][0][1]['selected'], 'manual')
        self.assertEqual(editor['lines'][0][2]['phonetic'], 'x1')
        self.assertEqual(editor['lines'][0][2]['selected'], 'global_recent')

    def test_cell_details_counts_same_character_across_lines(self):
        self.api.insert_text('xy\nyx')

        details = self.api.get_cell_details(0, 0)

        self.assertEqual(details['char'], 'x')
        self.assertEqual(details['same_char_count'], 2)

    def test_unknown_han_has_missing_phonetic_warning(self):
        editor = self.api.insert_text('甲，A[乙]')

        self.assertTrue(editor['lines'][0][0]['missing_phonetic'])
        self.assertFalse(editor['lines'][0][1]['missing_phonetic'])
        self.assertFalse(editor['lines'][0][2]['missing_phonetic'])
        self.assertFalse(editor['lines'][0][4]['missing_phonetic'])

    def test_draft_library_marks_files_containing_changed_characters(self):
        drafts = [
            {'filename': 'stale.json', 'name': 'Stale'},
            {'filename': 'clean.json', 'name': 'Clean'},
        ]
        recent = [{'filename': 'stale.json', 'name': 'Stale'}]
        with (patch('web_api.list_drafts', return_value=drafts),
              patch('web_api.list_recent_drafts', return_value=recent),
              patch('web_api.get_reading_change_events',
                    return_value={'x': [{'id': 'event-x'}]}),
              patch('web_api.draft_has_pending_updates',
                    side_effect=lambda filename, _events:
                    filename == 'stale.json')):
            library, recent_library = web_api._draft_library_snapshot()

        self.assertTrue(library[0]['stale'])
        self.assertFalse(library[1]['stale'])
        self.assertTrue(recent_library[0]['stale'])

    def test_confirming_update_is_per_cell_and_undoable(self):
        self.api.insert_text('x')
        info = self.api.buf.cell_info[0][0]
        info['data_revision'] = '2026-08-01 00:00:00'
        self.api.reading_events = {'x': [{
            'id': 'event-x', 'batch_id': '10',
            'timestamp': '2026-08-20 10:00:00',
            'filename': 'base.json.gz', 'batch_count': 1,
            'kind': '修改', 'char': 'x',
            'summary': '移除 x1; 新增 x2',
            'removed': ['x1'], 'added': ['x2'],
        }]}

        details = self.api.get_cell_details(0, 0)
        self.assertTrue(details['stale'])
        self.assertEqual(details['pending_updates'][0]['id'], 'event-x')

        result = self.api.review_cell_update(
            0, 0, 'event-x', 'accept', 'x2')
        self.assertEqual(result['editor']['lines'][0][0]['phonetic'], 'x2')
        self.assertFalse(result['editor']['lines'][0][0]['stale'])
        confirmed = self.api.get_cell_details(0, 0)['confirmed_updates'][0]
        self.assertEqual(confirmed['review']['status'], 'accepted_new')

        undone = self.api.editor_action('undo')
        self.assertEqual(undone['lines'][0][0]['phonetic'], 'x1')
        self.assertTrue(undone['lines'][0][0]['stale'])

    def test_reopening_confirmation_restores_pending_state(self):
        self.api.insert_text('y')
        info = self.api.buf.cell_info[0][0]
        info.update({
            'phonetic': 'old-y',
            'data_revision': '2026-08-01 00:00:00',
        })
        self.api.reading_events = {'y': [{
            'id': 'event-y', 'batch_id': '20',
            'timestamp': '2026-08-21 10:00:00',
            'filename': 'base.json.gz', 'batch_count': 1,
            'kind': '修改', 'char': 'y',
            'summary': '移除 old-y; 新增 y1',
            'removed': ['old-y'], 'added': ['y1'],
        }]}
        self.api.review_cell_update(0, 0, 'event-y', 'keep')

        result = self.api.reopen_cell_update(0, 0, 'event-y')

        self.assertTrue(result['editor']['lines'][0][0]['stale'])
        self.assertEqual(
            self.api.buf.cell_info[0][0]['update_reviews']['event-y']['status'],
            'reopened')

    def test_confirming_one_occurrence_does_not_clear_another(self):
        self.api.insert_text('xx')
        event = {
            'id': 'event-x', 'batch_id': '10',
            'timestamp': '2026-08-20 10:00:00',
            'filename': 'base.json.gz', 'batch_count': 1,
            'kind': '修改', 'char': 'x',
            'summary': '移除 x1; 新增 x2',
            'removed': ['x1'], 'added': ['x2'],
        }
        self.api.reading_events = {'x': [event]}
        for info in self.api.buf.cell_info[0]:
            info['data_revision'] = '2026-08-01 00:00:00'

        self.api.review_cell_update(0, 0, 'event-x', 'accept', 'x2')

        self.assertFalse(self.api.get_cell_details(0, 0)['stale'])
        self.assertTrue(self.api.get_cell_details(0, 1)['stale'])

    def test_new_cell_at_current_revision_ignores_historical_update(self):
        event = {
            'id': 'event-y', 'batch_id': '20',
            'timestamp': '2026-08-20 10:00:00',
            'filename': 'base.json.gz', 'batch_count': 1,
            'kind': '修改', 'char': 'y',
            'summary': '移除 y1; 新增 y2',
            'removed': ['y1'], 'added': ['y2'],
        }
        self.api.reading_events = {'y': [event]}
        self.api.buf.data_revision = '2026-08-20 10:00:00'

        self.api.insert_text('y')

        self.assertFalse(self.api.get_cell_details(0, 0)['stale'])

    def test_restore_confirmation_recovers_original_reading(self):
        self.api.insert_text('y')
        info = self.api.buf.cell_info[0][0]
        info.update({
            'phonetic': 'old-y',
            'data_revision': '2026-08-01 00:00:00',
        })
        self.api.reading_events = {'y': [{
            'id': 'event-y', 'batch_id': '20',
            'timestamp': '2026-08-21 10:00:00',
            'filename': 'base.json.gz', 'batch_count': 1,
            'kind': '修改', 'char': 'y',
            'summary': '移除 old-y; 新增 y1',
            'removed': ['old-y'], 'added': ['y1'],
        }]}
        self.api.review_cell_update(0, 0, 'event-y', 'accept', 'y1')

        result = self.api.reopen_cell_update(
            0, 0, 'event-y', restore_reading=True)

        self.assertEqual(result['editor']['lines'][0][0]['phonetic'], 'old-y')
        self.assertTrue(result['editor']['lines'][0][0]['stale'])

    def test_import_scheme_renames_conflicting_id(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, 'scheme.json')
            with open(source, 'w', encoding='utf-8') as file:
                json.dump({
                    'id': 'current_suno',
                    'name': 'Imported',
                    'maps': {},
                }, file)
            existing = [
                {'id': 'current_suno'},
                {'id': 'current_suno_imported'},
            ]
            saved = {}

            def save_scheme(scheme, scheme_id):
                saved.update(scheme)
                return scheme_id

            with (patch('web_api.list_schemes', return_value=existing),
                  patch('web_api.save_scheme', side_effect=save_scheme),
                  patch('web_api.load_scheme', side_effect=lambda _id: saved),
                  patch('web_api.save_preferred_scheme_id')):
                result = self.api.import_scheme_json(source)

        self.assertEqual(result['selected_scheme'],
                         'current_suno_imported_2')
        self.assertEqual(saved['id'], 'current_suno_imported_2')

    def test_import_scheme_content_supports_android_file_picker(self):
        content = json.dumps({
            'id': 'phone_scheme',
            'name': 'Phone scheme',
            'maps': {},
        })
        saved = {}

        def save_scheme(scheme, scheme_id):
            saved.update(scheme)
            return scheme_id

        with (patch('web_api.list_schemes', return_value=[]),
              patch('web_api.save_scheme', side_effect=save_scheme),
              patch('web_api.load_scheme', side_effect=lambda _id: saved),
              patch('web_api.save_preferred_scheme_id')):
            result = self.api.import_scheme_content(
                content, 'phone_scheme.json')

        self.assertEqual(result['selected_scheme'], 'phone_scheme')
        self.assertEqual(saved['name'], 'Phone scheme')

    def test_clone_scheme_preserves_map_concat(self):
        lookup = {
            'type': 'map_concat', 'field': 'target',
            'parts': [['onset', 's']],
        }
        scheme = {
            'id': 'test', 'maps': {'onset': {'s': 'S'}},
            'rules': {'post_replace': [[lookup, 'X']]},
        }

        with patch('web_api.list_schemes', return_value=[]):
            copied = self.api.clone_scheme(scheme)

        self.assertEqual(copied['rules']['post_replace'][0][0], lookup)
        self.assertIsNot(copied['rules']['post_replace'][0][0], lookup)

    def test_scheme_description_can_be_updated_without_switching_scheme(self):
        scheme = {
            'id': 'notes', 'name': 'Notes', 'description': 'old',
            'maps': {},
        }
        self.api.export_scheme_id = 'current_suno'
        with (patch('web_api.load_scheme', return_value=scheme),
              patch('web_api.save_scheme', return_value='notes') as save_mock,
              patch('web_api.list_schemes', side_effect=lambda: [{
                  'id': 'notes', 'name': 'Notes',
                  'description': scheme['description'],
              }])):
            result = self.api.update_scheme_description(
                'notes', 'new note')

        self.assertEqual(result['scheme']['description'], 'new note')
        self.assertEqual(self.api.export_scheme_id, 'current_suno')
        save_mock.assert_called_once_with(scheme, 'notes')

    def test_reordering_schemes_does_not_change_selected_scheme(self):
        self.api.export_scheme_id = 'current_suno'
        ordered = [
            {'id': 'b', 'name': 'B', 'description': ''},
            {'id': 'a', 'name': 'A', 'description': ''},
        ]
        with (patch('web_api.save_scheme_order') as save_order,
              patch('web_api.list_schemes', return_value=ordered)):
            result = self.api.reorder_schemes(['b', 'a'])

        save_order.assert_called_once_with(['b', 'a'])
        self.assertEqual(result['schemes'], ordered)
        self.assertEqual(self.api.export_scheme_id, 'current_suno')

    def test_archiving_selected_scheme_selects_oldest_available_scheme(self):
        selected = {'id': 'selected', 'name': 'Selected', 'maps': {}}
        saved = []
        schemes = [
            {'id': 'older', 'name': 'Older', 'description': '',
             'created_at': '2026-01-01', 'archived': False},
            {'id': 'selected', 'name': 'Selected', 'description': '',
             'created_at': '2026-01-02', 'archived': True},
        ]
        self.api.export_scheme_id = 'selected'
        with (patch('web_api.load_scheme', return_value=selected),
              patch('web_api.save_scheme', side_effect=lambda value, _id: saved.append(value.copy())),
              patch('web_api.list_schemes', return_value=schemes),
              patch('web_api.save_preferred_scheme_id') as save_preferred):
            result = self.api.set_scheme_archived('selected', True)

        self.assertTrue(saved[0]['archived'])
        self.assertEqual(result['selected_scheme'], 'older')
        self.assertEqual(self.api.export_scheme_id, 'older')
        save_preferred.assert_called_once_with('older')

    def test_suno_export_requires_an_imported_scheme(self):
        self.api.insert_text('x')
        self.api.export_scheme_id = None

        with patch('web_api.load_scheme') as load_mock:
            with self.assertRaisesRegex(ValueError, '请先导入方案'):
                self.api.export_text('suno')

        load_mock.assert_not_called()

    def test_inspector_width_preference_is_clamped_and_persisted(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, '.ui_state.json')
            with patch.object(web_api, '_UI_STATE_PATH', path):
                result = self.api.set_ui_preference(
                    'inspector_width', 999)
                preferences = web_api._load_ui_preferences()

        self.assertEqual(result['value'], 520)
        self.assertEqual(preferences['inspector_width'], 520)

    def test_editor_zoom_preference_is_clamped_and_persisted(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, '.ui_state.json')
            with patch.object(web_api, '_UI_STATE_PATH', path):
                result = self.api.set_ui_preference('editor_zoom', 9)
                preferences = web_api._load_ui_preferences()

        self.assertEqual(result['value'], 2.0)
        self.assertEqual(preferences['editor_zoom'], 2.0)

    def test_debug_mode_preference_is_persisted(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, '.ui_state.json')
            with patch.object(web_api, '_UI_STATE_PATH', path):
                result = self.api.set_ui_preference('debug_mode', True)
                preferences = web_api._load_ui_preferences()

        self.assertIs(result['value'], True)
        self.assertIs(preferences['debug_mode'], True)

    def test_export_options_are_normalized_and_persisted(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, '.ui_state.json')
            with patch.object(web_api, '_UI_STATE_PATH', path):
                result = self.api.set_ui_preference('export_options', {
                    'punct_split': True,
                    'remove_pharyngeal': 1,
                    'unknown_option': True,
                })
                preferences = web_api._load_ui_preferences()

        options = result['value']
        self.assertIs(options['punct_split'], True)
        self.assertIs(options['remove_pharyngeal'], True)
        self.assertIs(options['clean_line_breaks'], False)
        self.assertIs(options['ignore_bracket_control_lines'], False)
        self.assertNotIn('unknown_option', options)
        self.assertEqual(preferences['export_options'], options)

    def test_export_contents_and_copy_mode_are_normalized_and_persisted(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, '.ui_state.json')
            with patch.object(web_api, '_UI_STATE_PATH', path):
                contents = self.api.set_ui_preference(
                    'export_contents', ['suno', 'invalid', 'raw', 'suno'])
                copy_mode = self.api.set_ui_preference(
                    'selection_copy_mode', 'phon')
                auto_update = self.api.set_ui_preference(
                    'auto_check_updates', False)
                preferences = web_api._load_ui_preferences()

        self.assertEqual(contents['value'], ['raw', 'suno'])
        self.assertEqual(copy_mode['value'], 'phon')
        self.assertIs(auto_update['value'], False)
        self.assertEqual(preferences['export_contents'], ['raw', 'suno'])
        self.assertEqual(preferences['selection_copy_mode'], 'phon')
        self.assertIs(preferences['auto_check_updates'], False)

    def test_empty_export_contents_falls_back_to_pboc(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, '.ui_state.json')
            with patch.object(web_api, '_UI_STATE_PATH', path):
                result = self.api.set_ui_preference('export_contents', [])

        self.assertEqual(result['value'], ['phon'])

    def test_loading_draft_remembers_it_for_next_startup(self):
        loaded = ([['x']], [[{
            'phonetic': 'x1', 'is_poly': True, 'selected': 'none',
            'manual_hl': False,
        }]], {'cursor': [0, 1], 'selection': None, 'scroll_top': 24})
        with patch('web_api.load_draft', return_value=loaded):
            self.api.load_draft('remembered.json')

        self.ui_state_mock.assert_called_with(
            'current_draft', 'remembered.json')
        self.assertEqual(self.api.current_draft, 'remembered.json')
        self.assertEqual(self.api.scroll_top, 24)

    def test_startup_restores_saved_current_draft(self):
        loaded = ([['x']], [[{
            'phonetic': 'x2', 'is_poly': True, 'selected': 'manual',
            'manual_hl': False,
        }]], {'cursor': [0, 1], 'selection': None, 'scroll_top': 42})
        with (patch('web_api._load_ui_preferences', return_value={
                  'current_draft': 'remembered.json'}),
              patch('web_api.list_recent_drafts', return_value=[]),
              patch('web_api.load_draft', return_value=loaded)):
            restored = self.api._restore_startup_draft()

        self.assertTrue(restored)
        self.assertEqual(self.api.current_draft, 'remembered.json')
        self.assertEqual(self.api.buf.cur_col, 1)
        self.assertEqual(self.api.scroll_top, 42)

    def test_missing_saved_draft_falls_back_to_recent(self):
        loaded = ([['y']], [[{
            'phonetic': 'y1', 'is_poly': False, 'selected': 'none',
            'manual_hl': False,
        }]], {'cursor': [0, 0], 'selection': None, 'scroll_top': 0})

        def load(filename, _mapping, include_state=False):
            if filename == 'missing.json':
                raise FileNotFoundError(filename)
            return loaded

        with (patch('web_api._load_ui_preferences', return_value={
                  'current_draft': 'missing.json'}),
              patch('web_api.list_recent_drafts', return_value=[{
                  'filename': 'recent.json'}]),
              patch('web_api.load_draft', side_effect=load)):
            restored = self.api._restore_startup_draft()

        self.assertTrue(restored)
        self.assertEqual(self.api.current_draft, 'recent.json')

    def test_deleting_current_draft_clears_startup_restore(self):
        self.api.current_draft = 'current.json'
        with patch('web_api.delete_draft'):
            self.api.delete_draft('current.json')

        self.ui_state_mock.assert_called_with('current_draft', None)
        self.assertIsNone(self.api.current_draft)

    def test_about_source_links_only_open_known_urls(self):
        source = 'https://space.bilibili.com/129368153'
        with patch('webbrowser.open') as open_mock:
            self.api.open_source_url(source)
            self.api.open_source_url('https://space.bilibili.com/87432837')
            with self.assertRaises(ValueError):
                self.api.open_source_url('https://example.com')

        self.assertEqual(open_mock.call_count, 2)
        open_mock.assert_any_call(source)

    def test_about_release_link_opens_release_page(self):
        with patch('webbrowser.open') as open_mock:
            result = self.api.open_releases_page()

        self.assertEqual(result, {'ok': True})
        open_mock.assert_called_once_with(
            'https://github.com/Runwill/ancient-chinese/releases')

    def test_loading_theme_preference_is_available_before_editor_startup(self):
        with patch('web_api.get_theme', return_value='dark'):
            self.assertEqual(
                self.api.get_theme_preference(), {'theme': 'dark'})

    def test_startup_initialization_runs_without_blocking_status_polling(self):
        api = WebApi(None)
        started = threading.Event()
        release = threading.Event()

        def delayed_initialize():
            started.set()
            release.wait(1)

        with patch.object(api, 'initialize', side_effect=delayed_initialize):
            status = api.start_initialize()
            self.assertTrue(started.wait(.5))
            self.assertEqual(status['phase'], 'loading')
            self.assertEqual(status['step'], 1)
            self.assertTrue(api._startup_thread.is_alive())
            self.assertEqual(api.get_startup_status()['step_count'], 6)
            release.set()
            api._startup_thread.join(1)

        self.assertFalse(api._startup_thread.is_alive())

    def test_startup_failure_includes_download_error_report(self):
        api = WebApi(None)
        report = {'errors': [{
            'filename': 'base.json.gz',
            'url': 'https://qwert-ly.github.io/xtext/base.json.gz',
            'type': 'URLError',
            'message': 'connection timed out',
        }]}
        with (tempfile.TemporaryDirectory() as root,
              patch('web_api.download_and_update', return_value=report),
              patch('web_api.load_map_from_json_gz', return_value=None),
              patch('web_api.get_data_dir', return_value=root)):
            result = api.initialize()

        details = result['startup']['details']
        self.assertFalse(result['ok'])
        self.assertIn(root, details)
        self.assertIn('base.json.gz', details)
        self.assertIn('qwert-ly.github.io', details)
        self.assertIn('URLError: connection timed out', details)

    def test_restart_preserves_source_launch_arguments(self):
        with (patch.object(web_api.sys, 'argv', ['main.py', '--debug-webview']),
              patch.object(web_api.sys, 'frozen', False, create=True),
              patch('web_api.os.execv') as exec_mock):
            self.api.restart_app()

        exec_mock.assert_called_once_with(
            web_api.sys.executable,
            [web_api.sys.executable, 'main.py', '--debug-webview'])

    def test_glottal_tone_options_only_change_suno_export(self):
        source = [
            'kap', 'ʔa', 'kat', 'ʔa', 'kak', 'ʔa',
            'kas', 'ʔa', 'kaps', 'ʔa', 'kats', 'ʔa',
            'kaks', 'ʔa', 'kaʔs', 'ʔa',
        ]
        self.api.insert_text('x' * len(source))
        for info, phonetic in zip(self.api.buf.cell_info[0], source):
            info['phonetic'] = phonetic
        original = ' '.join(source)
        transformed = ' '.join(['kaʔ', 'ʔa'] * 8)

        nocm = self.api.export_text(
            'phon', None, False, True, True)
        with (patch('web_api.load_scheme', return_value={}),
              patch('web_api.NocmTranscriber') as transcriber_cls):
            transcriber_cls.return_value.convert_text.side_effect = (
                lambda value: value)
            suno = self.api.export_text(
                'suno', None, False, True, True)

        self.assertEqual(nocm, original)
        self.assertEqual(suno, transformed)

    def test_glottal_tone_options_do_not_cross_punctuation_or_lines(self):
        self.api.insert_text('x，x\nxx')
        values = [['kap', '，', 'ʔa'], ['kat', 'ʔi']]
        for row, phonetics in zip(self.api.buf.cell_info, values):
            for info, phonetic in zip(row, phonetics):
                info['phonetic'] = phonetic

        with (patch('web_api.load_scheme', return_value={}),
              patch('web_api.NocmTranscriber') as transcriber_cls):
            transcriber_cls.return_value.convert_text.side_effect = (
                lambda value: value)
            result = self.api.export_text(
                'suno', None, False, True, False)

        self.assertEqual(result, 'kap ， ʔa\nkaʔ ʔi')

    def test_glottal_tone_options_work_independently(self):
        self.api.insert_text('xxxx')
        source = ['kap', 'ʔa', 'kas', 'ʔi']
        for info, phonetic in zip(self.api.buf.cell_info[0], source):
            info['phonetic'] = phonetic

        with (patch('web_api.load_scheme', return_value={}),
              patch('web_api.NocmTranscriber') as transcriber_cls):
            transcriber_cls.return_value.convert_text.side_effect = (
                lambda value: value)
            entry_only = self.api.export_text(
                'suno', None, False, True, False)
            departing_only = self.api.export_text(
                'suno', None, False, False, True)

        self.assertEqual(entry_only, 'kaʔ ʔa kas ʔi')
        self.assertEqual(departing_only, 'kap ʔa kaʔ ʔi')

    def test_remove_pharyngeal_only_changes_suno_export(self):
        self.api.insert_text('xx[x]')
        values = ['kˤan', 'lˤa', '[', 'ˤ', ']']
        for info, phonetic in zip(self.api.buf.cell_info[0], values):
            info['phonetic'] = phonetic

        nocm = self.api.export_text(
            'phon', None, False, False, False, True)
        with (patch('web_api.load_scheme', return_value={}),
              patch('web_api.NocmTranscriber') as transcriber_cls):
            transcriber_cls.return_value.convert_text.side_effect = (
                lambda value: value)
            suno = self.api.export_text(
                'suno', None, False, False, False, True)

        self.assertEqual(nocm, 'kˤan lˤa [x]')
        self.assertEqual(suno, 'kan la [x]')

    def test_remove_tones_only_changes_suno_export(self):
        source = [
            'kap', 'kat', 'kak', 'kaʔ', 'kas', 'kah',
            'kaps', 'kats', 'kaks', 'kaʔs', 'kan',
        ]
        self.api.insert_text('x' * len(source))
        for info, phonetic in zip(self.api.buf.cell_info[0], source):
            info['phonetic'] = phonetic
        scheme = {
            'maps': {'tone': {
                key: key for key in
                ('ps', 'ts', 'ks', 'ʔs', 'ʔ', 's', 'p', 't', 'k', 'h')
            }},
            'parse_order': {'tone': [
                'ps', 'ts', 'ks', 'ʔs', 'ʔ', 's', 'p', 't', 'k', 'h'
            ]},
        }

        nocm = self.api.export_text(
            'phon', None, False, False, False, False, True)
        with (patch('web_api.load_scheme', return_value=scheme),
              patch('web_api.NocmTranscriber') as transcriber_cls):
            transcriber_cls.return_value.convert_text.side_effect = (
                lambda value: value)
            suno = self.api.export_text(
                'suno', None, False, False, False, False, True)

        self.assertEqual(nocm, ' '.join(source))
        self.assertEqual(
            suno, 'ka ka ka ka ka ka ka ka ka ka kan')

    def test_remove_glottal_tone_keeps_onsets_and_other_tones(self):
        source = ['ʔaʔ', 'kaʔs', 'kap', 'kas', 'ʔa', 'kaʔ']
        self.api.insert_text('x' * len(source))
        for info, phonetic in zip(self.api.buf.cell_info[0], source):
            info['phonetic'] = phonetic
        scheme = {
            'maps': {'tone': {
                key: key for key in ('ʔs', 'ʔ', 's', 'p')
            }},
            'parse_order': {'tone': ['ʔs', 'ʔ', 's', 'p']},
        }

        nocm = self.api.export_text(
            'phon', None, False, False, False, False, False, False,
            True)
        with (patch('web_api.load_scheme', return_value=scheme),
              patch('web_api.NocmTranscriber') as transcriber_cls):
            transcriber_cls.return_value.convert_text.side_effect = (
                lambda value: value)
            suno = self.api.export_text(
                'suno', None, False, False, False, False, False,
                False, True)

        self.assertEqual(nocm, ' '.join(source))
        self.assertEqual(suno, 'ʔa kas kap kas ʔa ka')

    def test_scheme_extra_h_option_only_changes_suno(self):
        self.api.insert_text('x')
        self.api.buf.cell_info[0][0]['phonetic'] = 'm̥a'
        scheme = {
            'maps': {
                'onset': {'m̥': 'hm'},
                'nucleus': {'a': 'a'},
            },
            'parse_order': {
                'onset': ['m̥'], 'nucleus': ['a'],
            },
            'options': {'extra_h_voiceless_sonorant': True},
        }

        nocm = self.api.export_text('phon')
        with patch('web_api.load_scheme', return_value=scheme):
            suno = self.api.export_text('suno')

        self.assertEqual(nocm, 'm̥a')
        self.assertEqual(suno, 'hhma')

    def test_clean_line_breaks_keeps_only_one_blank_line(self):
        source = '\r\n  text  \n \n\n phon \n\n'

        self.assertEqual(
            self.api._clean_line_breaks(source), 'text\n\nphon')

    def test_punctuation_split_preserves_square_bracket_syntax(self):
        self.assertEqual(
            self.api._split_punctuation(
                '[Verse,clear male vocal]\nx[note,a]y,z'),
            '[Verse,clear male vocal]\nx[note,a]y\nz')

        self.api.insert_text('[Verse,clear male vocal]\nx,x')
        outputs = [
            self.api.export_text('raw', punct_split=True),
            self.api.export_text('phon', punct_split=True),
        ]
        with patch('web_api.load_scheme', return_value={}):
            outputs.append(self.api.export_text(
                'suno', 'test', punct_split=True))

        for output in outputs:
            self.assertEqual(
                output.splitlines()[0], '[Verse,clear male vocal]')
            self.assertEqual(len(output.splitlines()), 3)

    def test_clean_line_breaks_removes_blanks_after_control_lines(self):
        source = (
            '[Sample,lo-fi]\n\n\n[male]\n\n'
            '(正文)\n\n\n( phon )')

        self.assertEqual(
            self.api._clean_line_breaks(source),
            '[Sample,lo-fi]\n[male]\n(正文)\n\n( phon )')

    def test_clean_line_breaks_option_applies_to_export(self):
        self.api.insert_text('x\n\n\nx')

        untouched = self.api.export_text('phon')
        cleaned = self.api.export_text(
            'phon', None, False, False, False, False, False, True)

        self.assertEqual(untouched, 'x1\n\n\nx1')
        self.assertEqual(cleaned, 'x1\n\nx1')

    def test_ignore_bracket_control_lines_applies_to_all_text_modes(self):
        self.api.insert_text(
            '[Verse,clear male vocal]\n'
            'x[inline note]y\n'
            '  []  \n'
            '【中文方括号】')

        outputs = [
            self.api.export_text(
                mode, ignore_bracket_control_lines=True)
            for mode in ('raw', 'phon', 'both')
        ]
        with patch('web_api.load_scheme', return_value={}):
            outputs.append(self.api.export_text(
                'suno', ignore_bracket_control_lines=True))

        for output in outputs:
            lines = [line.strip() for line in output.splitlines()]
            self.assertNotIn('[Verse,clear male vocal]', lines)
            self.assertNotIn('[]', lines)
            self.assertTrue(any('[inline note]' in line for line in lines))
            self.assertTrue(any('【' in line and '】' in line for line in lines))

    def test_ignore_bracket_control_lines_keeps_unfinished_tag(self):
        source = '[tag]\ntext [inline]\n[unfinished\n【中文】'

        self.assertEqual(
            self.api._ignore_bracket_control_lines(source),
            'text [inline]\n[unfinished\n【中文】')

    def test_both_export_does_not_reserve_phonetic_lines_for_brackets(self):
        self.api.insert_text('[Sample,lo-fi]\n[male]\nxx')

        result = self.api.export_text('both')

        self.assertEqual(
            result, '[Sample,lo-fi]\n[male]\nxx\nx1 x1')

    def test_combined_suno_export_is_grouped_with_each_source_line(self):
        self.api.insert_text('[Verse]\nxx\nyy')
        scheme = {
            'maps': {},
            'rules': {'post_replace': [['x', 'X']]},
        }

        with patch('web_api.load_scheme', return_value=scheme):
            result = self.api.export_text('raw+phon+suno')

        self.assertEqual(
            result,
            '[Verse]\n'
            'xx\n'
            'x1 x1\n'
            'X1 X1\n'
            '\n'
            'yy\n'
            'y1 y1\n'
            'y1 y1')

    def test_suno_export_preserves_spaces_and_letters_inside_brackets(self):
        self.api.insert_text('[Verse,clear male vocal]x')
        self.api.buf.cell_info[0][-1]['phonetic'] = 'lal'
        scheme = {
            'maps': {},
            'rules': {'post_replace': [['l', 'X']]},
        }

        with patch('web_api.load_scheme', return_value=scheme):
            result = self.api.export_text('suno')

        self.assertEqual(result, '[Verse,clear male vocal] XaX')

    def test_image_export_data_turns_bracket_lines_into_blanks(self):
        self.api.insert_text(
            '[Verse,clear male vocal]\n'
            '\n'
            'x[remove this]y')
        self.api.buf.cell_info[2][0]['selected'] = 'global_recent'
        self.api.buf.cell_info[2][0]['manual_hl'] = True

        result = self.api.get_image_export_data()

        self.assertEqual(len(result['lines']), 3)
        self.assertEqual(
            result['lines'][0],
            {'source_line': 0, 'cells': [], 'blank': True})
        self.assertEqual(
            result['lines'][1],
            {'source_line': 1, 'cells': [], 'blank': True})
        self.assertEqual(result['lines'][2]['source_line'], 2)
        self.assertEqual(
            result['lines'][2]['cells'],
            [
                {
                    'char': 'x', 'phonetic': 'x1', 'is_poly': True,
                    'selected': 'global_recent', 'manual_hl': True,
                    'stale': False, 'missing_phonetic': False,
                },
                {
                    'char': 'y', 'phonetic': 'y1', 'is_poly': False,
                    'selected': 'none', 'manual_hl': False,
                    'stale': False, 'missing_phonetic': False,
                },
            ])
        self.assertFalse(result['lines'][2]['blank'])

    def test_export_image_writes_valid_png_bytes(self):
        png = b'\x89PNG\r\n\x1a\n' + b'test-payload'
        data_url = 'data:image/png;base64,' + base64.b64encode(png).decode()
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, '正文图片')

            result = self.api.export_image(data_url, '正文', path)

            saved_path = f'{path}.png'
            self.assertEqual(result['path'], os.path.abspath(saved_path))
            with open(saved_path, 'rb') as file:
                self.assertEqual(file.read(), png)


if __name__ == '__main__':
    unittest.main()
