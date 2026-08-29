"""Tests for versioned persistence, backup restore, and scheme tooling."""

import json
import hashlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup_manager
import data_loader
import draft_io
import folder_manager
import library_import
import update_manager
from app_version import (CHANGELOG, DRAFT_SCHEMA_VERSION,
                         SCHEME_SCHEMA_VERSION, __version__)
from nocm_transcriber import (NocmTranscriber, diff_schemes,
                              list_schemes, load_preferred_scheme_id,
                              load_scheme, migrate_scheme_data, save_scheme,
                              save_scheme_order,
                              validate_scheme)


class DataDownloadTests(unittest.TestCase):
    def test_existing_local_data_is_used_when_remote_check_fails(self):
        with (tempfile.TemporaryDirectory() as root,
              patch.object(data_loader, '_get_remote_last_modified',
                           return_value=None)):
            local = os.path.join(root, 'base.json.gz')
            Path(local).write_bytes(b'existing')

            self.assertFalse(data_loader._needs_update(
                'https://example.invalid/base.json.gz', local))

    def test_download_report_preserves_network_errors(self):
        with (tempfile.TemporaryDirectory() as root,
              patch.object(data_loader, 'get_data_dir', return_value=root),
              patch.object(data_loader, '_needs_update', return_value=True),
              patch.object(data_loader.urllib.request, 'urlopen',
                           side_effect=OSError('GitHub connection timed out'))):
            report = data_loader.download_and_update()

        self.assertFalse(report['ok'])
        self.assertEqual(len(report['errors']), 2)
        self.assertEqual(report['errors'][0]['type'], 'OSError')
        self.assertIn('GitHub connection timed out',
                      report['errors'][0]['message'])
        self.assertIn('qwert-ly.github.io', report['errors'][0]['url'])


class ApplicationUpdateTests(unittest.TestCase):
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    def test_release_manifest_exposes_verified_android_asset(self):
        release = {
            'tag_name': 'v9.8.7',
            'html_url': 'https://github.com/Runwill/ancient-chinese/releases/tag/v9.8.7',
            'assets': [{
                'name': 'update.json',
                'browser_download_url': 'https://github.com/update.json',
            }],
        }
        manifest = {
            'schema': 1, 'version': '9.8.7', 'notes': '安全更新',
            'assets': {'android': {
                'filename': 'HanToPBOC-9.8.7-release.apk',
                'url': 'https://github.com/update.apk',
                'sha256': 'a' * 64, 'size': 12,
            }},
        }
        responses = [
            self.Response(json.dumps(release).encode()),
            self.Response(json.dumps(manifest).encode()),
        ]
        with (patch.dict(os.environ, {'HAN_NOCM_RUNTIME': 'android'}),
              patch.object(update_manager.urllib.request, 'urlopen',
                           side_effect=responses)):
            result = update_manager.check_for_updates()

        self.assertTrue(result['available'])
        self.assertTrue(result['can_install'])
        self.assertEqual(result['asset']['sha256'], 'a' * 64)
        self.assertEqual(result['notes'], '安全更新')

    def test_download_is_hashed_and_revalidated(self):
        content = b'verified apk bytes'
        digest = hashlib.sha256(content).hexdigest()
        update = {
            'ok': True, 'available': True, 'latest': '9.8.7',
            'platform': 'android',
            'asset': {
                'filename': 'HanToPBOC-9.8.7-release.apk',
                'url': 'https://github.com/update.apk',
                'sha256': digest, 'size': len(content),
            },
        }
        with (tempfile.TemporaryDirectory() as root,
              patch.dict(os.environ, {
                  'HAN_NOCM_RUNTIME': 'android',
                  'HAN_NOCM_DATA_DIR': root,
              }),
              patch.object(update_manager, 'check_for_updates',
                           return_value=update),
              patch.object(update_manager.urllib.request, 'urlopen',
                           return_value=self.Response(content))):
            progress = []
            downloaded = update_manager.download_update(progress.append)
            verified = update_manager.validate_downloaded_update(
                downloaded['path'])
            with open(downloaded['path'], 'ab') as file:
                file.write(b'changed')
            with self.assertRaisesRegex(ValueError, '发生了变化'):
                update_manager.validate_downloaded_update(downloaded['path'])

        self.assertEqual(verified['sha256'], digest)
        self.assertIn('downloading', [item['phase'] for item in progress])
        self.assertEqual(progress[-1]['phase'], 'ready')
        self.assertEqual(progress[-1]['downloaded'], len(content))


class DataChangeViewerTests(unittest.TestCase):
    def test_large_log_is_indexed_by_batch_and_entries_are_paged(self):
        content = '''
============================================================
[2026-08-20 10:00:00] base.json.gz 更新 — 共 2 处差异
============================================================
  [修改] 關: 移除 kˤron; 新增 kˤro[n]
  [新增] 雎: tsa

============================================================
[2026-08-21 11:30:00] extra.json.gz 更新 — 共 2 处差异
============================================================
  [修改] #18:
    旧: {"z": "關", "y": "old"}
    新: {"z": "關", "y": "new"}
  [删除] #19: {"z": "雎"}
'''
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, 'data_update.log'), 'w',
                      encoding='utf-8') as file:
                file.write(content)
            with patch.object(data_loader, 'get_data_dir', return_value=root):
                batches = data_loader.get_data_change_batches(0, 1)
                latest = batches['items'][0]
                first_page = data_loader.get_data_change_entries(
                    latest['id'], 0, 1)
                searched = data_loader.get_data_change_entries(
                    latest['id'], 0, 10, 'new')
                reading_events = data_loader.get_reading_change_events()

        self.assertEqual(batches['total'], 2)
        self.assertTrue(batches['has_more'])
        self.assertEqual(latest['filename'], 'extra.json.gz')
        self.assertEqual(first_page['total'], 2)
        self.assertTrue(first_page['has_more'])
        self.assertEqual(first_page['items'][0]['label'], '#18')
        self.assertEqual(first_page['items'][0]['display_label'], '關 · #18')
        self.assertEqual(first_page['items'][0]['changes'], [{
            'field': '音标', 'field_key': 'y', 'status': '修改',
            'old': 'old', 'new': 'new',
        }])
        self.assertEqual(first_page['items'][0]['unchanged_count'], 1)
        self.assertEqual(searched['total'], 1)
        self.assertIn('event_id', first_page['items'][0])
        self.assertEqual(reading_events['關'][0]['removed'], ['kˤron'])
        self.assertEqual(reading_events['關'][0]['added'], ['kˤro[n]'])
        self.assertEqual(len(reading_events['關'][0]['id']), 24)

    def test_missing_change_log_returns_an_empty_view(self):
        with (tempfile.TemporaryDirectory() as root,
              patch.object(data_loader, 'get_data_dir', return_value=root)):
            result = data_loader.get_data_change_batches()

        self.assertFalse(result['exists'])
        self.assertEqual(result['items'], [])


class VersionMetadataTests(unittest.TestCase):
    def test_current_version_is_first_changelog_entry(self):
        self.assertEqual(CHANGELOG[0]['version'], __version__)
        self.assertTrue(CHANGELOG[0]['date'])
        self.assertTrue(CHANGELOG[0]['items'])

    def test_html_preview_history_is_split_into_point_releases(self):
        versions = [entry['version'] for entry in CHANGELOG]
        for patch_version in range(1, 7):
            self.assertIn(f'0.9.{patch_version}', versions)
        version_010 = next(
            entry for entry in CHANGELOG if entry['version'] == '0.10.0')
        self.assertEqual(version_010['title'], '正文图片导出')

    def test_configured_data_directory_is_used(self):
        import app_version

        with (tempfile.TemporaryDirectory() as root,
              patch.dict(os.environ, {'HAN_NOCM_DATA_DIR': root})):
            self.assertEqual(app_version.get_app_dir(), os.path.abspath(root))

    def test_android_runtime_mode_is_reported_as_apk(self):
        with (tempfile.TemporaryDirectory() as root,
              patch.dict(os.environ, {
                  'HAN_NOCM_DATA_DIR': root,
                  'HAN_NOCM_RUNTIME': 'android',
              }),
              patch.object(update_manager, 'list_drafts', return_value=[]),
              patch.object(update_manager, 'list_schemes', return_value=[]),
              patch.object(update_manager, 'get_scheme_dir',
                           return_value=os.path.join(root, 'schemes'))):
            info = update_manager.diagnostic_info()

        self.assertEqual(info['runtime_mode'], 'Android APK')
        self.assertFalse(info['frozen'])


class WebAssetContractTests(unittest.TestCase):
    def test_image_preview_stage_selector_exists_in_markup(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'web', 'index.html'),
                  encoding='utf-8') as file:
            markup = file.read()
        with open(os.path.join(root, 'web', 'app.js'),
                  encoding='utf-8') as file:
            script = file.read()

        self.assertIn('id="image-canvas-stage"', markup)
        self.assertIn("$('#image-canvas-stage')", script)
        self.assertIn('id="copy-image-export"', markup)
        self.assertIn("$('#copy-image-export')", script)
        self.assertIn("new ClipboardItem({ 'image/png': blob })", script)

    def test_packaged_app_does_not_bundle_a_default_scheme(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'build_exe.py'),
                  encoding='utf-8') as file:
            build_script = file.read()

        self.assertNotIn('schemes/current_suno.json;schemes', build_script)
        self.assertIn("executable_name = f'汉转PBOC-{__version__}'", build_script)

    def test_scheme_picker_uses_one_header_row_without_dropdown_glyph(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'web', 'index.html'),
                  encoding='utf-8') as file:
            markup = file.read()

        picker = markup.split('id="scheme-picker-dialog"', 1)[1].split(
            'id="image-export-dialog"', 1)[0]
        trigger = markup.split('id="open-scheme-picker"', 1)[1].split(
            '</button>', 1)[0]
        self.assertNotIn('⌄', trigger)
        self.assertNotIn('scheme-picker-list-heading', picker)
        self.assertLess(
            picker.index('id="scheme-picker-filter"'),
            picker.index('id="import-scheme-picker"'))
        self.assertIn(f'styles.css?v={__version__}', markup)
        self.assertIn(f'app.js?v={__version__}', markup)

    def test_close_buttons_use_centered_svg_icons(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'web', 'index.html'),
                  encoding='utf-8') as file:
            markup = file.read()

        close_buttons = [
            part.split('</button>', 1)[0]
            for part in markup.split('<button')[1:]
            if 'aria-label="关闭' in part.split('>', 1)[0]
        ]
        self.assertEqual(len(close_buttons), 16)
        for button in close_buttons:
            self.assertIn('<svg ', button)
            self.assertNotIn('×', button)

    def test_frontend_supports_android_json_bridge(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'web', 'app.js'),
                  encoding='utf-8') as file:
            script = file.read()

        self.assertIn('function createAndroidApi(bridge)', script)
        self.assertIn('bridge.invokeAsync(', script)
        self.assertIn('window.__resolveAndroidApi', script)
        self.assertNotIn(
            'bridge.invoke(String(method), JSON.stringify(args))', script)
        self.assertIn('window.handleAndroidBack', script)

    def test_android_build_does_not_bundle_schemes(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'android', 'app', 'build.gradle.kts'),
                  encoding='utf-8') as file:
            build_script = file.read()

        self.assertNotIn('schemes/', build_script)
        self.assertNotIn('schemes\\', build_script)
        self.assertIn('base.json.gz', build_script)
        self.assertIn('extra.json.gz', build_script)
        self.assertIn('"runtime_log.py"', build_script)

    def test_android_activity_forces_landscape_and_hides_status_bar(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(
                root, 'android', 'app', 'src', 'main', 'AndroidManifest.xml'),
                encoding='utf-8') as file:
            manifest = file.read()
        with open(os.path.join(
                root, 'android', 'app', 'src', 'main', 'java', 'com',
                'runwill', 'hantonom', 'MainActivity.kt'),
                encoding='utf-8') as file:
            activity = file.read()

        self.assertIn('android:screenOrientation="sensorLandscape"', manifest)
        self.assertIn('WindowManager.LayoutParams.FLAG_FULLSCREEN', activity)
        self.assertIn('View.SYSTEM_UI_FLAG_FULLSCREEN', activity)
        self.assertIn('runCatching', activity)
        self.assertNotIn('WindowInsetsController', activity)

    def test_application_icon_is_wired_to_web_and_android(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'web', 'index.html'),
                  encoding='utf-8') as file:
            markup = file.read()
        with open(os.path.join(root, 'android', 'app', 'src', 'main',
                               'AndroidManifest.xml'),
                  encoding='utf-8') as file:
            manifest = file.read()

        self.assertIn('rel="icon"', markup)
        self.assertIn('app-icon.png', markup)
        self.assertIn('app-icon-dark.png', markup)
        self.assertTrue(os.path.isfile(
            os.path.join(root, 'web', 'app-icon-dark.png')))
        self.assertIn('android:icon="@drawable/app_icon"', manifest)

        with open(os.path.join(root, 'main.py'), encoding='utf-8') as file:
            desktop_entry = file.read()
        with open(os.path.join(root, 'build_exe.py'), encoding='utf-8') as file:
            build_script = file.read()
        self.assertIn('icon=icon_path', desktop_entry)
        self.assertIn('assets/app-icon.ico;assets', build_script)

    def test_windows_titlebar_is_integrated_into_the_web_ui(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'main.py'), encoding='utf-8') as file:
            desktop_entry = file.read()
        with open(os.path.join(root, 'web', 'index.html'),
                  encoding='utf-8') as file:
            markup = file.read()
        with open(os.path.join(root, 'web', 'app.js'),
                  encoding='utf-8') as file:
            script = file.read()
        with open(os.path.join(root, 'web', 'styles.css'),
                  encoding='utf-8') as file:
            styles = file.read()

        self.assertIn('frameless=True', desktop_entry)
        self.assertIn('easy_drag=False', desktop_entry)
        self.assertIn("DRAG_REGION_DIRECT_TARGET_ONLY", desktop_entry)
        self.assertIn('id="app-titlebar"', markup)
        self.assertIn('titlebar-icon-light', markup)
        self.assertIn('titlebar-icon-dark', markup)
        self.assertIn(':root[data-theme="dark"] .titlebar-icon-dark', styles)
        self.assertIn('data-window-action="minimize"', markup)
        self.assertIn('data-window-action="maximize"', markup)
        self.assertIn('data-window-action="close"', markup)
        self.assertIn('data-resize-edge="bottom-right"', markup)
        self.assertIn("invoke('toggle_maximize_window')", script)
        self.assertIn("invoke('start_window_resize'", script)

    def test_editor_supports_persistent_ctrl_wheel_zoom(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'web', 'index.html'),
                  encoding='utf-8') as file:
            markup = file.read()
        with open(os.path.join(root, 'web', 'styles.css'),
                  encoding='utf-8') as file:
            styles = file.read()
        with open(os.path.join(root, 'web', 'app.js'),
                  encoding='utf-8') as file:
            script = file.read()

        self.assertIn('id="editor-zoom-status"', markup)
        self.assertIn('zoom: var(--editor-zoom, 1)', styles)
        self.assertIn('font-size: calc(14px * var(--editor-zoom, 1))',
                      styles)
        self.assertIn("addEventListener('wheel', adjustEditorZoom", script)
        self.assertIn("$('#export-output').addEventListener(", script)
        self.assertIn('<span>正文字号</span><kbd>Ctrl 滚轮</kbd>', script)
        self.assertIn("'set_ui_preference', 'editor_zoom'", script)
        self.assertIn('event.preventDefault()', script)

    def test_dialog_headers_are_compact_and_not_duplicated(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'web', 'index.html'),
                  encoding='utf-8') as file:
            markup = file.read()
        with open(os.path.join(root, 'web', 'styles.css'),
                  encoding='utf-8') as file:
            styles = file.read()

        self.assertNotIn('<span class="eyebrow">输出</span>', markup)
        self.assertNotIn('<span class="eyebrow">正文成图</span>', markup)
        self.assertNotIn('<span class="eyebrow">转写配置</span>', markup)
        self.assertNotIn('<span class="eyebrow">文稿保护</span>', markup)
        self.assertNotIn('<span class="eyebrow">正文工具</span>', markup)
        self.assertNotIn('<span class="eyebrow">运行诊断</span>', markup)
        self.assertNotIn('class="export-experimental"', markup)
        self.assertNotIn('<summary>实验选项</summary>', markup)
        self.assertIn(
            'class="export-option-group" data-debug-only data-suno-only',
            markup)
        self.assertIn('<input id="remove-tones"', markup)
        self.assertIn('.compact-dialog > form > header', styles)
        self.assertIn('.export-dialog > form > header', styles)
        self.assertIn('border-bottom: 0', styles)

    def test_export_content_buttons_are_multi_select_without_all_button(self):
        markup = Path('web/index.html').read_text(encoding='utf-8')
        script = Path('web/app.js').read_text(encoding='utf-8')
        export_buttons = markup.split('id="export-mode"', 1)[1].split(
            '</div>', 1)[0]

        self.assertEqual(export_buttons.count('<button'), 3)
        self.assertIn('data-value="raw"', export_buttons)
        self.assertIn('data-value="phon"', export_buttons)
        self.assertIn('data-value="suno"', export_buttons)
        self.assertNotIn('data-value="both"', export_buttons)
        self.assertIn("const EXPORT_CONTENT_KEYS = ['raw', 'phon', 'suno'];", script)
        self.assertIn("const exportContents = new Set(['phon']);", script)
        self.assertIn("exportContents.add(value)", script)
        self.assertIn("'export_contents', EXPORT_CONTENT_KEYS.filter", script)
        self.assertIn('applyPersistentUiPreferences(result.ui_preferences)', script)
        self.assertIn("renderMode('both')", script)
        self.assertIn('id="export-settings-toggle"', markup)
        self.assertIn('id="export-settings-panel"', markup)
        self.assertIn("renderMode(modes.join('+'))", script)
        self.assertIn(
            'body.debug-mode .export-controls:not(.suno-mode) '
            '.export-option-group[data-suno-only] { display: none; }',
            Path('web/styles.css').read_text(encoding='utf-8'))
        self.assertIn(
            "$('#remove-tones').disabled = !includesSuno || !debugEnabled",
            script)

    def test_selection_inspector_controls_use_complete_rows(self):
        styles = Path('web/styles.css').read_text(encoding='utf-8')

        self.assertIn(
            'grid-template-columns: repeat(3, minmax(0, 1fr));', styles)
        self.assertIn('#copy-mode { width: 100%; }', styles)
        self.assertIn('#copy-mode button { min-width: 0; flex: 1 1 50%; }', styles)

    def test_interactive_text_and_conditional_toolbars_stay_stable(self):
        styles = Path('web/styles.css').read_text(encoding='utf-8')
        script = Path('web/app.js').read_text(encoding='utf-8')
        markup = Path('web/index.html').read_text(encoding='utf-8')

        self.assertIn('-webkit-user-select: none', styles)
        self.assertIn('body,\nbody * {', styles)
        self.assertIn('[contenteditable="true"],\npre,\noutput,', styles)
        self.assertIn('.data-change-values > div > span,', styles)
        self.assertIn('.diff-value > :not(span),', styles)
        self.assertIn('.utilitybar,\n.searchbar {', styles)
        self.assertIn('min-height: 46px', styles)
        self.assertIn('#export-mode { height: 34px; gap: 0; }', styles)
        self.assertIn('#export-mode button { min-width: 62px; height: 32px;', styles)
        self.assertIn('.export-scheme-controls { min-width: 0; margin-left: auto;', styles)
        self.assertIn('background: transparent; border: 0; border-bottom: 1px solid var(--divider); border-radius: 0;', styles)
        self.assertIn('class="export-scheme-controls"', markup)
        self.assertNotIn('class="export-scheme-controls" data-suno-only', markup)
        self.assertLess(markup.index('id="export-settings-toggle"'),
                        markup.index('class="export-scheme-controls"'))
        self.assertIn('class="scheme-picker-label">方案</span>', markup)
        self.assertIn("clearTimeout(node._removeTimer)", script)

    def test_rules_use_one_header_and_one_mode_control_per_row(self):
        styles = Path('web/styles.css').read_text(encoding='utf-8')
        script = Path('web/app.js').read_text(encoding='utf-8')

        self.assertIn('class="table-row rule header rule-list-header"', script)
        self.assertIn('class="rule-mode-toggle ${mapped', script)
        self.assertIn('data-rule-mode="${mapped', script)
        self.assertNotIn('data-rule-field="mode"', script)
        self.assertIn('.rule-mode-toggle:hover, .rule-mode-toggle.mapped', styles)

    def test_scheme_tools_only_exposes_visual_comparison(self):
        markup = Path('web/index.html').read_text(encoding='utf-8')
        script = Path('web/app.js').read_text(encoding='utf-8')
        styles = Path('web/styles.css').read_text(encoding='utf-8')

        self.assertIn('data-tab="tools" role="tab" aria-selected="false">方案比较', markup)
        self.assertIn('class="diff-column-head"', script)
        self.assertIn('class="diff-row-arrow"', script)
        self.assertIn("improve_pharyngeal: '改善咽化组合'", script)
        self.assertIn('class="diff-summary"', script)
        self.assertIn('class="diff-scheme-menu"', script)
        self.assertNotIn('<select id="diff-scheme"', script)
        self.assertNotIn('scheme-preview-input', script)
        self.assertNotIn('validation-summary', script)
        self.assertNotIn('.dialog header {', styles)
        self.assertIn('.dialog > .scheme-layout > header', styles)
        self.assertIn('.diff-entry { min-height: 34px;', styles)

    def test_android_loads_startup_page_before_backend_thread(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(
                root, 'android', 'app', 'src', 'main', 'java', 'com',
                'runwill', 'hantonom', 'MainActivity.kt'),
                encoding='utf-8') as file:
            activity = file.read()
        with open(os.path.join(root, 'web', 'app.js'),
                  encoding='utf-8') as file:
            script = file.read()
        with open(os.path.join(root, 'web', 'index.html'),
                  encoding='utf-8') as file:
            markup = file.read()
        with open(os.path.join(root, 'web', 'styles.css'),
                  encoding='utf-8') as file:
            styles = file.read()

        load_page = 'webView.loadUrl("file:///android_asset/web/index.html?theme='
        self.assertLess(activity.index(load_page), activity.index('Thread {'))
        self.assertIn('prefersDarkTheme()', activity)
        self.assertTrue(os.path.isfile(os.path.join(
            root, 'android', 'app', 'src', 'main', 'res', 'values-night',
            'styles.xml')))
        self.assertIn('updateAvailableIndicator(result)', script)
        self.assertIn('get_backend_readiness', activity)
        self.assertIn('fun invokeAsync(', activity)
        self.assertIn("invoke('start_initialize')", script)
        self.assertIn('id="startup-stage"', markup)
        self.assertIn('id="startup-stage" class="startup-stage" aria-hidden="true"', markup)
        self.assertIn('class="startup-progress-block"', markup)
        self.assertIn('.startup p { margin: 0 0 18px;', styles)
        self.assertIn('.startup-progress-block { position: relative; width: 320px; height: 28px;', styles)
        self.assertIn('const showStage = elapsed >= 8', script)
        self.assertIn("classList.toggle('startup-stage-visible', showStage)", script)
        self.assertIn('requestAnimationFrame(\n        () => requestAnimationFrame(resolve))', script)


class DraftMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = self.temp.name
        patches = [
            patch.object(draft_io, 'DRAFTS_DIR', root),
            patch.object(draft_io, '_DRAFTS_ORDER_FILE', os.path.join(root, '_order.json')),
            patch.object(draft_io, '_DRAFTS_RECENT_FILE', os.path.join(root, '_recent.json')),
            patch.object(draft_io, '_DRAFT_HISTORY_DIR', os.path.join(root, '_history')),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_legacy_draft_is_migrated_without_losing_reading(self):
        path = os.path.join(self.temp.name, 'legacy.json')
        data = {
            'name': 'legacy', 'buffer': [['x']],
            'cell_info': [[{'phonetic': 'x2', 'is_poly': True,
                            'selected': 'manual'}]],
        }
        with open(path, 'w', encoding='utf-8') as file:
            json.dump(data, file)

        buffer, info, view = draft_io.load_draft(
            'legacy.json', {'x': [{'phonetic': 'x1'}, {'phonetic': 'x2'}]},
            include_state=True)

        self.assertEqual(buffer, [['x']])
        self.assertEqual(info[0][0]['phonetic'], 'x2')
        self.assertEqual(view['cursor'], [0, 0])
        self.assertEqual(draft_io.load_json(path)['schema_version'],
                         DRAFT_SCHEMA_VERSION)

    def test_draft_list_counts_only_unselected_polyphonic_cells(self):
        draft_io.save_draft(
            None, 'unfinished', [['甲', '乙', '丙']], [[
                {'phonetic': 'a', 'is_poly': True, 'selected': 'none'},
                {'phonetic': 'b', 'is_poly': True, 'selected': 'manual'},
                {'phonetic': 'c', 'is_poly': False, 'selected': 'none'},
            ]])

        drafts = draft_io.list_drafts()

        self.assertEqual(drafts[0]['unselected_polyphonic'], 1)

    def test_manual_completion_marker_survives_later_saves(self):
        filename = draft_io.save_draft(
            None, 'complete', [['甲']], [[{
                'phonetic': 'a', 'is_poly': True, 'selected': 'none',
            }]])
        draft_io.set_draft_completed(filename, True)
        draft_io.save_draft(
            filename, None, [['甲']], [[{
                'phonetic': 'a', 'is_poly': True, 'selected': 'none',
            }]])

        draft = next(item for item in draft_io.list_drafts()
                     if item['filename'] == filename)

        self.assertTrue(draft['manually_completed'])
        self.assertEqual(draft['unselected_polyphonic'], 1)

    def test_manual_save_creates_restorable_history(self):
        mapping = {'x': [{'phonetic': 'x1'}]}
        filename = draft_io.save_draft(
            None, 'draft', [['x']], [[{'phonetic': 'x1', 'is_poly': False}]])
        draft_io.save_draft(
            filename, None, [['x', 'x']],
            [[{'phonetic': 'x1', 'is_poly': False},
              {'phonetic': 'x1', 'is_poly': False}]],
            create_history=True)
        history = draft_io.list_draft_history(filename)

        draft_io.restore_draft_history(filename, history[0]['id'])
        buffer, _info = draft_io.load_draft(filename, mapping)
        self.assertEqual(buffer, [['x']])

    def test_update_reviews_survive_draft_round_trip(self):
        review = {
            'event-x': {
                'status': 'accepted_new', 'before': 'x1', 'after': 'x2',
                'event': {'id': 'event-x', 'timestamp': '2026-08-20'},
            },
        }
        filename = draft_io.save_draft(
            None, 'reviewed', [['x']], [[{
                'phonetic': 'x2', 'is_poly': True, 'selected': 'manual',
                'data_revision': '2026-08-20', 'update_reviews': review,
            }]])

        _buffer, info = draft_io.load_draft(
            filename, {'x': [{'phonetic': 'x1'}, {'phonetic': 'x2'}]})

        self.assertEqual(info[0][0]['data_revision'], '2026-08-20')
        self.assertEqual(
            info[0][0]['update_reviews']['event-x']['status'],
            'accepted_new')

class SchemeToolTests(unittest.TestCase):
    def test_missing_scheme_directory_has_no_preferred_default(self):
        with (tempfile.TemporaryDirectory() as root,
              patch('nocm_transcriber.get_scheme_dir', return_value=root),
              patch('nocm_transcriber._scheme_pref_path',
                    return_value=os.path.join(root, '.scheme_pref'))):
            selected = load_preferred_scheme_id()

        self.assertIsNone(selected)

    def test_scheme_migration_and_validation(self):
        scheme, changed = migrate_scheme_data({
            'id': 'test', 'maps': {'onset': {'k': 'K'}},
            'rules': {'post_replace': []},
        })

        self.assertTrue(changed)
        self.assertEqual(scheme['schema_version'], SCHEME_SCHEMA_VERSION)
        self.assertIs(scheme['options']['extra_h_voiceless_sonorant'], False)
        self.assertEqual(
            scheme['option_definitions']['extra_h_voiceless_sonorant']['label'],
            '清响音前额外加 h')
        self.assertFalse([i for i in validate_scheme(scheme)
                          if i['severity'] == 'error'])

    def test_missing_concat_reference_is_reported(self):
        scheme = {
            'id': 'test', 'maps': {'onset': {}}, 'options': {},
            'labels': {}, 'parse_order': {},
            'rules': {'post_replace': [[{
                'type': 'map_concat', 'field': 'target',
                'parts': [['onset', 'missing']]
            }, 'x']]},
        }
        errors = [item for item in validate_scheme(scheme)
                  if item['severity'] == 'error']
        self.assertTrue(errors)

    def test_map_concat_survives_save_and_load(self):
        lookup = {
            'type': 'map_concat', 'field': 'target',
            'parts': [['onset', 's'], ['glide', 'r']],
        }
        scheme = {
            'id': 'roundtrip',
            'maps': {'onset': {'s': 'S'}, 'glide': {'r': 'R'}},
            'options': {}, 'labels': {}, 'parse_order': {},
            'rules': {'post_replace': [[lookup, 'X']]},
        }

        with (tempfile.TemporaryDirectory() as root,
              patch('nocm_transcriber.get_scheme_dir', return_value=root)):
            save_scheme(scheme)
            loaded = load_scheme('roundtrip')

        self.assertEqual(loaded['rules']['post_replace'][0][0], lookup)

    def test_rule_description_survives_save_and_does_not_affect_output(self):
        scheme = {
            'id': 'described-rule',
            'maps': {},
            'rules': {'post_replace': [['x', 'y', '把 x 改写为 y']]},
        }

        with (tempfile.TemporaryDirectory() as root,
              patch('nocm_transcriber.get_scheme_dir', return_value=root)):
            save_scheme(scheme)
            loaded = load_scheme('described-rule')

        self.assertEqual(
            loaded['rules']['post_replace'][0][2], '把 x 改写为 y')
        self.assertEqual(NocmTranscriber(loaded).convert_text('x'), 'y')

    def test_schemes_are_sorted_by_creation_time(self):
        with (tempfile.TemporaryDirectory() as root,
              patch('nocm_transcriber.get_scheme_dir', return_value=root)):
            for scheme_id, name, created_at in (
                    ('alpha', 'Alpha', '2026-01-02T00:00:00+00:00'),
                    ('beta', 'Beta', '2026-01-03T00:00:00+00:00'),
                    ('gamma', 'Gamma', '2026-01-01T00:00:00+00:00')):
                save_scheme({
                    'id': scheme_id, 'name': name,
                    'description': f'{name} note', 'created_at': created_at,
                    'maps': {},
                })
            schemes = list_schemes()

        self.assertEqual(
            [item['id'] for item in schemes],
            ['gamma', 'alpha', 'beta'])
        self.assertEqual(schemes[0]['description'], 'Gamma note')
        self.assertFalse(schemes[0]['archived'])

    def test_new_scheme_gets_creation_time_once(self):
        with (tempfile.TemporaryDirectory() as root,
              patch('nocm_transcriber.get_scheme_dir', return_value=root)):
            save_scheme({'id': 'dated', 'maps': {}})
            created_at = load_scheme('dated')['created_at']
            save_scheme({'id': 'dated', 'maps': {}, 'description': 'edited'})
            saved_again = load_scheme('dated')['created_at']

        self.assertTrue(created_at)
        self.assertEqual(saved_again, created_at)

    def test_scheme_diff_reports_changed_mapping(self):
        left = {'maps': {'onset': {'k': 'K'}}, 'rules': {}, 'options': {}}
        right = {'maps': {'onset': {'k': 'Q'}}, 'rules': {}, 'options': {}}
        differences = diff_schemes(left, right)
        self.assertEqual(differences[0]['category'], '基础映射')
        self.assertEqual(differences[0]['key'], 'onset.k')

    def test_old_voiced_stop_boolean_migrates_to_nasal_preset(self):
        scheme, changed = migrate_scheme_data({
            'schema_version': 2,
            'maps': {'onset': {'b': 'old-b', 'd': 'old-d', 'g': 'old-g'}},
            'options': {'english_voiced_stops': False},
            'option_definitions': {'english_voiced_stops': {}},
        })

        self.assertTrue(changed)
        self.assertEqual(scheme['options']['voiced_stop_style'], 'nasal')
        self.assertNotIn('english_voiced_stops', scheme['options'])
        self.assertEqual(scheme['maps']['onset'], {
            'b': 'mб', 'd': 'nд', 'g': 'ŋг'})

    def test_old_voiced_stop_boolean_migrates_to_english_preset(self):
        scheme, changed = migrate_scheme_data({
            'schema_version': 2,
            'maps': {'onset': {}},
            'options': {'english_voiced_stops': True},
            'option_definitions': {'english_voiced_stops': {}},
        })

        self.assertTrue(changed)
        self.assertEqual(scheme['options']['voiced_stop_style'], 'english')
        self.assertEqual(scheme['maps']['onset'], {
            'b': 'б', 'd': 'ντ', 'g': 'γκ'})

    def test_custom_voiced_stop_maps_are_not_overridden(self):
        scheme = {
            'maps': {
                'onset': {'b': 'B!', 'd': 'D!', 'g': 'G!'},
                'nucleus': {'a': 'A'},
            },
            'options': {'voiced_stop_style': 'custom'},
            'option_definitions': {
                'voiced_stop_style': {
                    'type': 'choice',
                    'presets': {'english': {
                        'b': 'б', 'd': 'ντ', 'g': 'γκ'}},
                },
            },
            'rules': {},
        }

        self.assertEqual(NocmTranscriber(scheme).convert_text('ba da ga'),
                         'B!A D!A G!A')

    def test_missing_voiced_stop_option_defaults_to_custom_without_guessing(self):
        onsets = {'b': 'mб', 'd': 'nд', 'g': 'ŋг', 'dz': 'nц'}
        scheme, changed = migrate_scheme_data({
            'schema_version': SCHEME_SCHEMA_VERSION,
            'maps': {'onset': dict(onsets)},
            'options': {'improve_pharyngeal': True},
            'option_definitions': {},
        })

        self.assertTrue(changed)
        self.assertEqual(scheme['options']['voiced_stop_style'], 'custom')
        self.assertEqual(scheme['maps']['onset'], onsets)
        definition = scheme['option_definitions']['voiced_stop_style']
        self.assertEqual(definition['type'], 'choice')
        self.assertEqual(
            [item['value'] for item in definition['choices']],
            ['nasal', 'english', 'custom'])

    def test_mapping_table_order_controls_overlapping_onsets(self):
        scheme = {
            'maps': {
                'onset': {'k': 'K', 'kh': 'X'},
                'nucleus': {'a': 'a'},
            },
            'parse_order': {
                'onset': ['k', 'kh'],
                'nucleus': ['a'],
            },
        }
        self.assertEqual(NocmTranscriber(scheme).convert_text('kha'), 'Kha')

        scheme['parse_order']['onset'] = ['kh', 'k']
        self.assertEqual(NocmTranscriber(scheme).convert_text('kha'), 'Xa')

    def test_residual_mapping_uses_visible_table_order_without_auto_sort(self):
        scheme = {
            'maps': {
                'residual': {'k': 'K', 'kh': 'X'},
                'nucleus': {'a': 'a'},
            },
            'parse_order': {
                'residual': ['k', 'kh'],
                'nucleus': ['a'],
            },
        }
        self.assertEqual(NocmTranscriber(scheme).convert_text('kha'), 'Kha')

        scheme['parse_order']['residual'] = ['kh', 'k']
        self.assertEqual(NocmTranscriber(scheme).convert_text('kha'), 'Xa')

    def test_scheme_editor_exposes_manual_mapping_and_rule_order(self):
        script = Path('web/app.js').read_text(encoding='utf-8')
        self.assertIn('data-drag-map', script)
        self.assertIn('data-drag-rule', script)
        self.assertIn('setPointerCapture', script)
        self.assertNotIn('data-move-map', script)
        self.assertNotIn('data-move-rule', script)
        self.assertNotIn('data-sort-map', script)
        self.assertNotIn('data-sort-rule', script)

    def test_scheme_editor_supports_voiced_stop_choice_and_custom_state(self):
        script = Path('web/app.js').read_text(encoding='utf-8')
        markup = Path('web/index.html').read_text(encoding='utf-8')
        styles = Path('web/styles.css').read_text(encoding='utf-8')
        self.assertIn('data-option-choice', script)
        self.assertIn('Object.assign(schemeDraft.maps.onset, preset)', script)
        self.assertIn("schemeDraft.options.voiced_stop_style = 'custom'", script)
        self.assertIn("rows.length ? `<div class=\"data-table\">", script)
        self.assertIn("rules.length ? `<div class=\"rule-list\">", script)
        self.assertIn("['rules', '附加替换开关'", script)
        self.assertIn("['output', '输出拼写'", script)
        self.assertIn('data-tab="maps" role="tab" aria-selected="false">基础映射', markup)
        self.assertIn('data-tab="rules" role="tab" aria-selected="false">附加替换', markup)
        self.assertIn('data-rule-field="description"', script)
        self.assertNotIn('id="extra-h-voiceless-sonorant"', markup)
        self.assertIn("if (key === 's')", script)
        self.assertIn("$('#save-scheme-button').click()", script)
        self.assertIn('role="tablist"', markup)
        self.assertIn('role="tabpanel"', markup)
        self.assertIn('.scheme-save-status:empty { display: none; }', styles)
        self.assertIn('.scheme-section.empty { margin-bottom: 8px; }', styles)

    def test_library_search_shortcut_and_search_result_drag_guard_exist(self):
        script = Path('web/app.js').read_text(encoding='utf-8')
        self.assertIn('function focusLibrarySearch()', script)
        self.assertIn("if ($$('dialog[open]').length) return;", script)
        self.assertIn("$('#search-button').click();", script)
        self.assertIn('if (!ungrouped) return;', script)
        self.assertIn('按当前焦点查找', script)
        self.assertNotIn('Ctrl Shift F', script)

    def test_renaming_mapping_item_preserves_its_table_position(self):
        script = Path('web/app.js').read_text(encoding='utf-8')
        rename_block = script.split("if (field === 'source') {", 1)[1].split(
            'markSchemeDirty();', 1)[0]
        self.assertLess(rename_block.index('const order = mapOrder(section);'),
                        rename_block.index('delete schemeDraft.maps'))
        self.assertIn(
            'schemeDraft.parse_order[section] = order.map(', rename_block)

    def test_clear_sonorant_english_variant_matches_r_change_voiced_stops(self):
        clear_sonorant = load_scheme('hsth_change')
        r_change = load_scheme('r_change')

        active_onsets = NocmTranscriber(clear_sonorant).maps['onset']
        self.assertEqual(
            {key: active_onsets[key] for key in ('b', 'd', 'g')},
            {key: r_change['maps']['onset'][key] for key in ('b', 'd', 'g')})

    def test_transcriber_preserves_spaced_bracket_tags(self):
        transcriber = NocmTranscriber({
            'maps': {},
            'rules': {'post_replace': [['l', 'X']]},
        })

        result = transcriber.convert_text(
            'lal [Verse,clear male vocal] lal\n'
            'lal[Bridge soft vocal]lal')

        self.assertEqual(
            result,
            'XaX [Verse,clear male vocal] XaX\n'
            'XaX[Bridge soft vocal]XaX')

    def test_transcriber_preserves_unfinished_bracket_tag(self):
        transcriber = NocmTranscriber({
            'maps': {},
            'rules': {'post_replace': [['l', 'X']]},
        })

        self.assertEqual(
            transcriber.convert_text('lal [Verse clear male'),
            'XaX [Verse clear male')

    def test_extra_h_uses_source_voiceless_sonorant_after_mapping(self):
        transcriber = NocmTranscriber({
            'maps': {
                'onset': {
                    'm̥': 'hm', 'n̥': 'hn', 'r̥': 'ร',
                    'l̥': 'hl', 'ŋ̊': 'hง', 'm': 'm',
                },
                'nucleus': {'a': 'a'},
            },
            'parse_order': {
                'onset': ['m̥', 'n̥', 'r̥', 'l̥', 'ŋ̊', 'm'],
                'nucleus': ['a'],
            },
        })

        result = transcriber.convert_text(
            'm̥a n̥a r̥a l̥a ŋ̊a ma [m̥a]', True)

        self.assertEqual(
            result, 'hhma hhna hรa hhla hhงa ma [m̥a]')


class BackupTests(unittest.TestCase):
    def test_backup_round_trip(self):
        with tempfile.TemporaryDirectory() as root:
            drafts = os.path.join(root, 'drafts')
            schemes = os.path.join(root, 'schemes')
            os.makedirs(drafts)
            os.makedirs(schemes)
            with open(os.path.join(drafts, 'one.json'), 'w', encoding='utf-8') as file:
                json.dump({'name': 'original'}, file)
            with open(os.path.join(schemes, 'one.json'), 'w', encoding='utf-8') as file:
                json.dump({'id': 'one', 'maps': {}}, file)
            backup_path = os.path.join(root, 'backup.zip')
            with (patch.object(backup_manager, 'DRAFTS_DIR', drafts),
                  patch.object(backup_manager, 'ensure_drafts_dir',
                               lambda: os.makedirs(drafts, exist_ok=True)),
                  patch.object(backup_manager, 'get_scheme_dir',
                               return_value=schemes),
                  patch.object(backup_manager, 'get_app_dir',
                               return_value=root)):
                backup_manager.create_backup(backup_path)
                with open(os.path.join(drafts, 'one.json'), 'w', encoding='utf-8') as file:
                    json.dump({'name': 'changed'}, file)
                backup_manager.restore_backup(backup_path)
            with open(os.path.join(drafts, 'one.json'), encoding='utf-8') as file:
                restored = json.load(file)
            self.assertEqual(restored['name'], 'original')


class LegacyLibraryImportTests(unittest.TestCase):
    def test_conflicting_draft_is_renamed_and_folder_reference_is_remapped(self):
        with tempfile.TemporaryDirectory() as root:
            current = os.path.join(root, 'current')
            old = os.path.join(root, 'old', 'drafts')
            os.makedirs(current)
            os.makedirs(old)
            current_data = {
                'name': 'current', 'buffer': [['a']],
                'cell_info': [[{'phonetic': 'a', 'is_poly': False}]],
            }
            old_data = {
                'name': 'old', 'buffer': [['b']],
                'cell_info': [[{'phonetic': 'b', 'is_poly': False}]],
            }
            for directory, data in ((current, current_data), (old, old_data)):
                with open(os.path.join(directory, 'same.json'), 'w', encoding='utf-8') as file:
                    json.dump(data, file)
            with open(os.path.join(old, '_groups.json'), 'w', encoding='utf-8') as file:
                json.dump([{'id': 'g1', 'name': '旧文件夹', 'expanded': True,
                            'files': ['same.json'], 'children': []}], file)

            history = os.path.join(current, '_history')
            patches = [
                patch.object(draft_io, 'DRAFTS_DIR', current),
                patch.object(draft_io, '_DRAFTS_ORDER_FILE', os.path.join(current, '_order.json')),
                patch.object(draft_io, '_DRAFTS_RECENT_FILE', os.path.join(current, '_recent.json')),
                patch.object(draft_io, '_DRAFT_HISTORY_DIR', history),
                patch.object(folder_manager, '_GROUPS_FILE', os.path.join(current, '_groups.json')),
                patch.object(library_import, 'DRAFTS_DIR', current),
                patch.object(library_import, '_DRAFTS_ORDER_FILE', os.path.join(current, '_order.json')),
                patch.object(library_import, '_DRAFTS_RECENT_FILE', os.path.join(current, '_recent.json')),
                patch.object(library_import, '_DRAFT_HISTORY_DIR', history),
                patch.object(library_import, 'create_backup',
                             return_value={'path': 'safety.zip'}),
            ]
            for item in patches:
                item.start()
                self.addCleanup(item.stop)
            report = library_import.import_legacy_library(old)

            self.assertEqual(report['imported'], 1)
            self.assertEqual(report['renamed'], 1)
            self.assertTrue(os.path.isfile(
                os.path.join(current, 'same_imported.json')))
            groups = folder_manager.get_groups()
            self.assertEqual(groups[0]['files'], ['same_imported.json'])


if __name__ == '__main__':
    unittest.main()
