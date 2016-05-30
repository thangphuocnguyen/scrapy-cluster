'''
Offline tests
'''
from unittest import TestCase
from mock import MagicMock
from redis_monitor import RedisMonitor


class TestRedisMonitor(TestCase):

    def setUp(self):
        self.redis_monitor = RedisMonitor("settings.py", True)
        self.redis_monitor.settings = self.redis_monitor.wrapper.load("settings.py")
        self.redis_monitor.logger = MagicMock()

    def test_load_plugins(self):
        # test loading default plugins
        assert_keys = [100, 200, 300, 400, 500]
        self.redis_monitor._load_plugins()
        self.assertEqual(self.redis_monitor.plugins_dict.keys(), assert_keys)

        # test removing a plugin from settings
        assert_keys = [100, 300, 400, 500]
        self.redis_monitor.settings['PLUGINS'] \
            ['plugins.stop_monitor.StopMonitor'] = None
        self.redis_monitor._load_plugins()
        self.assertEqual(self.redis_monitor.plugins_dict.keys(), assert_keys)
        self.redis_monitor.settings['PLUGINS'] \
            ['plugins.stop_monitor.StopMonitor'] = 200

        # fail if the class is not found
        self.redis_monitor.settings['PLUGINS'] \
            ['plugins.crazy_class.CrazyHandler'] = 400,

        self.assertRaises(ImportError, self.redis_monitor._load_plugins)
        del self.redis_monitor.settings['PLUGINS'] \
            ['plugins.crazy_class.CrazyHandler']
        self.redis_monitor.settings['PLUGINS'] = {}

    def test_active_plugins(self):
        # test that exceptions are caught within each plugin
        # assuming now all plugins are loaded
        self.redis_monitor._load_plugins()
        self.redis_monitor.stats_dict = {}

        # BaseExceptions are never raised normally
        self.redis_monitor.plugins_dict.items()[0][1]['instance'].handle = MagicMock(side_effect=BaseException("info"))
        self.redis_monitor.plugins_dict.items()[1][1]['instance'].handle = MagicMock(side_effect=BaseException("stop"))
        self.redis_monitor.plugins_dict.items()[2][1]['instance'].handle = MagicMock(side_effect=BaseException("expire"))
        self.redis_monitor.redis_conn = MagicMock()
        self.redis_monitor.redis_conn.scan_iter = MagicMock()
        # lets just assume the regex worked
        self.redis_monitor.redis_conn.scan_iter.return_value = ['somekey1']

        # info
        try:
            plugin = self.redis_monitor.plugins_dict.items()[0][1]
            self.redis_monitor._process_plugin(plugin)
            self.fail("Info not called")
        except BaseException as e:
            self.assertEquals("info", e.message)

        # action
        try:
            plugin = self.redis_monitor.plugins_dict.items()[1][1]
            self.redis_monitor._process_plugin(plugin)
            self.fail("Stop not called")
        except BaseException as e:
            self.assertEquals("stop", e.message)

        # expire
        try:
            plugin = self.redis_monitor.plugins_dict.items()[2][1]
            self.redis_monitor._process_plugin(plugin)
            self.fail("Expire not called")
        except BaseException as e:
            self.assertEquals("expire", e.message)

        # test that an exception within a handle method is caught
        try:
            self.redis_monitor.plugins_dict.items()[0][1]['instance'].handle = MagicMock(side_effect=Exception("normal"))
            plugin = self.redis_monitor.plugins_dict.items()[0][1]
            self.redis_monitor._process_plugin(plugin)
        except Exception as e:
            self.fail("Normal Exception not handled")

    def test_load_stats_plugins(self):
        # lets assume we are loading the default plugins
        self.redis_monitor._load_plugins()
        self.redis_monitor.redis_conn = MagicMock()

        # test no rolling stats
        self.redis_monitor.stats_dict = {}
        self.redis_monitor.settings['STATS_TIMES'] = []
        self.redis_monitor._setup_stats_plugins()
        defaults = [
            'ExpireMonitor',
            'StopMonitor',
            'InfoMonitor',
            'StatsMonitor',
            'ZookeeperMonitor'
        ]

        self.assertEquals(
            sorted(self.redis_monitor.stats_dict['plugins'].keys()),
            sorted(defaults))

        for key in self.redis_monitor.plugins_dict:
            plugin_name = self.redis_monitor.plugins_dict[key]['instance'].__class__.__name__
            self.assertEquals(
                self.redis_monitor.stats_dict['plugins'][plugin_name].keys(),
                ['lifetime'])

        # test good/bad rolling stats
        self.redis_monitor.stats_dict = {}
        self.redis_monitor.settings['STATS_TIMES'] = [
            'SECONDS_15_MINUTE',
            'SECONDS_1_HOUR',
            'SECONDS_DUMB',
        ]
        good = [
            'lifetime', # for totals, not DUMB
            900,
            3600,
        ]

        self.redis_monitor._setup_stats_plugins()

        self.assertEquals(
            sorted(self.redis_monitor.stats_dict['plugins'].keys()),
            sorted(defaults))

        for key in self.redis_monitor.plugins_dict:
            plugin_name = self.redis_monitor.plugins_dict[key]['instance'].__class__.__name__
            self.assertEquals(
                sorted(self.redis_monitor.stats_dict['plugins'][plugin_name].keys()),
                sorted(good))

        for plugin_key in self.redis_monitor.stats_dict['plugins']:
            k1 = 'stats:redis-monitor:{p}'.format(p=plugin_key)
            for time_key in self.redis_monitor.stats_dict['plugins'][plugin_key]:
                if time_key == 0:
                    self.assertEquals(
                        self.redis_monitor.stats_dict['plugins'][plugin_key][0].key,
                        '{k}:lifetime'.format(k=k1)
                        )
                else:
                    self.assertEquals(
                        self.redis_monitor.stats_dict['plugins'][plugin_key][time_key].key,
                        '{k}:{t}'.format(k=k1, t=time_key)
                        )

    def test_main_loop(self):
        self.redis_monitor._load_plugins()
        self.redis_monitor._process_plugin = MagicMock(side_effect=Exception(
                                                       "normal"))

        try:
            self.redis_monitor._main_loop()
            self.fail("_process_plugin not called")
        except BaseException as e:
            self.assertEquals("normal", e.message)

    def test_precondition(self):
        self.redis_monitor.stats_dict = {}
        instance = MagicMock()
        instance.check_precondition = MagicMock(return_value=False)
        instance.handle = MagicMock(side_effect=Exception("handler"))
        key = 'stuff'
        value = 'blah'

        # this should not raise an exception
        self.redis_monitor._process_key_val(instance, key, value)

        # this should
        instance.check_precondition = MagicMock(return_value=True)
        try:
            self.redis_monitor._process_key_val(instance, key, value)
            self.fail('handler not called')
        except BaseException as e:
            self.assertEquals('handler', e.message)
