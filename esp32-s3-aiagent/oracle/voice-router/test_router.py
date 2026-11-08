import unittest
from unittest.mock import Mock, patch

import router


class RouterTests(unittest.TestCase):
    def run_request(self, text):
        return router.answer([{'role': 'user', 'content': text}])

    def test_gold_failure_does_not_invent_prices(self):
        with patch.object(router, 'gold_answer', side_effect=TimeoutError), patch.object(router, 'ask_gemini') as fallback:
            self.assertIn('PNJ', self.run_request('Giá vàng hôm nay'))
            fallback.assert_not_called()

    def test_cloud_failure_is_not_retried(self):
        with patch.object(router, 'ask_gemini', side_effect=TimeoutError) as fallback:
            self.run_request('Giải thích vì sao trời xanh')
            self.assertEqual(fallback.call_count, 1)

    def test_local_timeout_uses_fallback_once(self):
        with patch.object(router, 'ask_local', side_effect=TimeoutError), patch.object(router, 'ask_gemini', return_value='Xin chào') as fallback:
            self.assertEqual(self.run_request('Xin chào'), 'Xin chào')
            self.assertEqual(fallback.call_count, 1)

    def test_music_query_and_stop(self):
        with patch.object(router, 'music_answer', return_value='queued') as music:
            self.assertEqual(self.run_request('Phát nhạc Sơn Tùng'), 'queued')
            music.assert_called_once_with('sơn tùng')
        pending = Mock()
        with patch.object(router, '_pending_music', pending), patch.object(router, 'ha_call'):
            self.assertEqual(self.run_request('Dừng nhạc'), 'Đã dừng nhạc.')
            pending.cancel.assert_called_once()

    def test_openclaw_timestamped_youtube_song_uses_music_route(self):
        request = "[Sun 2026-11-08 08:26 UTC] Phát bài nhạc 'Hẹn hò' trên YouTube"
        with patch.object(router, 'music_answer', return_value='queued') as music:
            self.assertEqual(self.run_request(request), 'queued')
            music.assert_called_once_with('hẹn hò')

    def test_music_answer_does_not_wait_for_youtube_search(self):
        with patch.object(router.threading, 'Thread') as thread:
            thread.return_value.start = Mock()
            self.assertEqual(router.music_answer('hẹn hò'), 'Đang tìm bài hẹn hò trên YouTube.')
            self.assertIs(thread.call_args.kwargs['target'], router.search_and_play_music)
            self.assertEqual(thread.call_args.kwargs['args'][0], 'hẹn hò')
            thread.return_value.start.assert_called_once()

    def test_appliance_command_is_not_a_music_search(self):
        with patch.object(router, 'music_answer') as music, patch.object(router, 'ha_call') as service:
            self.run_request('Bật máy lọc giúp tôi')
            music.assert_not_called()
            service.assert_called_once_with('switch', 'turn_on',
                {'entity_id': 'switch.zhimi_sg_874668291_rmb1_on_p_2_1'})

    def test_blocked_music_source_is_reported_without_claiming_success(self):
        with patch.object(router, 'music_answer', side_effect=RuntimeError('blocked')), patch.object(router, 'ask_gemini') as fallback:
            reply = self.run_request('Phát nhạc Sơn Tùng')
            self.assertIn('chưa thực hiện được', reply)
            fallback.assert_not_called()

    def test_room_temperature_uses_ha_directly(self):
        values = {'sensor.zhimi_sg_874668291_rmb1_temperature_p_3_7': '29',
                  'sensor.zhimi_sg_874668291_rmb1_relative_humidity_p_3_1': '80',
                  'sensor.zhimi_sg_874668291_rmb1_pm2_5_density_p_3_4': '4'}
        with patch.object(router, 'ha_state', side_effect=lambda entity: values[entity]), patch.object(router, 'ask_local') as local:
            reply = self.run_request('Nhiệt độ phòng bao nhiêu?')
            self.assertIn('29 độ', reply)
            local.assert_not_called()

    def test_ac_temperature_uses_ha_directly(self):
        with patch.object(router, 'ha_call') as service, patch.object(router, 'ask_local') as local:
            reply = self.run_request('Đặt điều hoà 26 độ')
            service.assert_called_once_with('input_number', 'set_value',
                {'entity_id': 'input_number.dieuhoa_temp', 'value': 26})
            self.assertIn('26 độ', reply)
            local.assert_not_called()

    def test_purifier_alarm_is_not_purifier_power(self):
        alarm = 'switch.zhimi_sg_874668291_rmb1_alarm_p_6_1'
        with patch.object(router, 'ha_call') as service:
            self.assertEqual(self.run_request('Bật báo động máy lọc'), 'Đã bật báo động máy lọc.')
            service.assert_called_once_with('switch', 'turn_on', {'entity_id': alarm})
            service.reset_mock()
            self.assertEqual(self.run_request('Tắt báo động máy lọc'), 'Đã tắt báo động máy lọc.')
            service.assert_called_once_with('switch', 'turn_off', {'entity_id': alarm})

    def test_purifier_power_command_still_targets_power_switch(self):
        power = 'switch.zhimi_sg_874668291_rmb1_on_p_2_1'
        with patch.object(router, 'ha_call') as service:
            self.assertEqual(self.run_request('Bật máy lọc không khí'), 'Đã bật máy lọc không khí.')
            service.assert_called_once_with('switch', 'turn_on', {'entity_id': power})

    def test_device_list_reports_live_offline_and_unknown_devices(self):
        snapshot = {
            'areas': [{'area_id': 'bedroom', 'name': 'Bedroom'}],
            'devices': [
                {'id': 'purifier', 'area_id': 'bedroom', 'name': 'Purifier'},
                {'id': 'ac', 'area_id': 'bedroom', 'name': 'Air Conditioner'},
                {'id': 'smart_ir', 'area_id': 'bedroom', 'name': 'Smart IR'},
                {'id': 'forecast', 'area_id': 'bedroom', 'name': 'Forecast'},
            ],
            'entities': [
                {'device_id': 'purifier', 'entity_id': 'switch.purifier', 'disabled_by': None},
                {'device_id': 'ac', 'entity_id': 'climate.ac', 'disabled_by': None},
                {'device_id': 'forecast', 'entity_id': 'weather.home', 'disabled_by': None},
            ],
            'states': [
                {'entity_id': 'switch.purifier', 'state': 'off'},
                {'entity_id': 'climate.ac', 'state': 'unavailable'},
                {'entity_id': 'weather.home', 'state': 'rainy'},
            ],
        }
        with patch.object(router, 'ha_registry_snapshot', return_value=snapshot), \
                patch.object(router, 'ask_local') as local, patch.object(router, 'ask_gemini') as gemini:
            reply = self.run_request('Liệt kê các thiết bị trong phòng, cả online và offline')
            self.assertIn('Purifier: online', reply)
            self.assertIn('Air Conditioner: offline', reply)
            self.assertIn('Smart IR: chưa xác định trạng thái', reply)
            self.assertIn('Thiết bị trong phòng ngủ:', reply)
            self.assertNotIn('Forecast', reply)
            local.assert_not_called()
            gemini.assert_not_called()


if __name__ == '__main__':
    unittest.main()