import asyncio
import copy
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
with patch.dict(os.environ, {key: '1' for key in (
    'ANNOUNCEMENT_CHANNEL_ID', 'SSU_CHANNEL_ID', 'RANK_LOG_CHANNEL_ID', 'ROBLOX_GROUP_ID'
)} | {'DATABASE_URL': '', 'BOT_TOKEN': ''}), patch('dotenv.load_dotenv'):
    spec = importlib.util.spec_from_file_location('rank_test_bot', ROOT / 'bot.py')
    bot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bot)


class RankSetupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original = {'ranks': dict(bot.ROBLOX_ROLE_VALUES), 'limits': dict(bot.DISCORD_RANK_LIMITS)}
        self.folder = tempfile.TemporaryDirectory()
        self.file_patch = patch.object(bot, 'RANK_CONFIG_FILE', str(Path(self.folder.name) / 'ranks.json'))
        self.file_patch.start()
        bot.rank_config_lock = asyncio.Lock()

    def tearDown(self):
        bot.apply_rank_config(self.original)
        self.file_patch.stop()
        self.folder.cleanup()

    def interaction(self, role_id):
        user = Mock(spec=bot.discord.Member)
        user.roles = [Mock(id=role_id)]
        return Mock(user=user, response=Mock(defer=AsyncMock()), followup=Mock(send=AsyncMock()))

    async def test_defaults_and_command_serialization(self):
        self.assertEqual(bot.ROBLOX_ROLE_VALUES, {
            'Class - D': 1, 'Class - E': 3, 'Level - 1': 4, 'Level - 2': 5,
            'Level - 3': 6, 'Level - 4': 7, 'O5 Council': 9, 'O5 Head': 10,
            'The Administrator': 11,
        })
        self.assertEqual(bot.get_role_value('Level 3'), 6)
        for command in bot.bot.tree.get_commands():
            self.assertEqual(command.to_dict()['name'], command.name)

    async def test_only_setup_roles_authorized(self):
        for command in bot.rank_setup_group.commands:
            for role in (1233139781840670746, 1233139781840670749):
                self.assertTrue(await command.checks[0](self.interaction(role)))
            self.assertFalse(await command.checks[0](self.interaction(1233139781823627473)))
            self.assertFalse(await command.checks[0](Mock(user=Mock(spec=bot.discord.User))))

    async def test_edit_persists_and_updates_autocomplete(self):
        interaction = self.interaction(1233139781840670746)
        await bot.update_rank_setup(interaction, 'ranks', 'New Rank', 12)
        self.assertEqual(bot.read_rank_config()['ranks']['New Rank'], 12)
        self.assertEqual((await bot.rank_autocomplete(interaction, 'new'))[0].value, 'New Rank')
        self.assertEqual(bot.get_role_value('New Rank'), 12)
        await bot.update_rank_setup(interaction, 'limits', '42', 12)
        self.assertTrue(await bot.can_rank(self.interaction(42)))
        saved = bot.read_rank_config()
        bot.apply_rank_config(self.original)
        bot.apply_rank_config(saved)
        self.assertEqual(bot.DISCORD_RANK_LIMITS['42'], 12)
        await bot.update_rank_setup(interaction, 'ranks', 'New Rank', None)
        self.assertNotIn('New Rank', bot.read_rank_config()['ranks'])

    async def test_invalid_or_failed_save_does_not_change_live_state(self):
        interaction = self.interaction(1233139781840670746)
        for name, value in [('Duplicate', 1), ('!!!', 12), ('Bad', 256), ('class d', 12)]:
            await bot.update_rank_setup(interaction, 'ranks', name, value)
            self.assertEqual(bot.ROBLOX_ROLE_VALUES, self.original['ranks'])
        with patch.object(bot, 'write_rank_config', side_effect=OSError('storage unavailable')):
            await bot.update_rank_setup(interaction, 'ranks', 'New Rank', 12)
        self.assertEqual(bot.ROBLOX_ROLE_VALUES, self.original['ranks'])
        self.assertIn('No changes were applied', interaction.followup.send.call_args.args[0])

    async def test_rank_uses_configured_autocomplete_value(self):
        interaction = self.interaction(1233139781840670749)
        interaction.user.id = 100
        interaction.user.mention = '<@100>'
        interaction.response.send_message = AsyncMock()
        bot._rank_last_used.clear()
        with patch.object(bot.bot, 'get_channel', return_value=None), \
             patch.object(bot, 'resolve_roblox_user', return_value=(123, 'Example')), \
             patch.object(bot, 'get_current_role_name', return_value='Class - D'), \
             patch.object(bot, 'get_role_id_by_name', return_value=456) as role_id, \
             patch.object(bot, 'roblox_request', return_value=Mock(status_code=200)) as request:
            await bot.rank.callback(interaction, 'Example', 'Level - 3', 'Test')
        role_id.assert_called_once_with('Level - 3')
        self.assertEqual(request.call_args.kwargs['json'], {'roleId': 456})
        self.assertIn('Ranked', interaction.response.send_message.call_args.args[0])

    async def test_database_storage_uses_timeout_and_round_trips(self):
        config = copy.deepcopy(self.original)
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = [config]
        with patch.object(bot, 'DATABASE_URL', 'test-dsn'), patch.object(bot.psycopg2, 'connect') as connect:
            connect.return_value.__enter__.return_value = connection
            bot.write_rank_config(config)
            self.assertEqual(bot.read_rank_config(), config)
            connect.assert_called_with('test-dsn', connect_timeout=10)


if __name__ == '__main__':
    unittest.main()
