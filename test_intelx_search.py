import os
import unittest
from unittest.mock import Mock, patch

from universal_search_system import UniversalSearchSystem, app


class IntelXSearchTests(unittest.TestCase):
    def test_intelx_search_requires_api_key(self) -> None:
        with patch.dict(os.environ, {'INTELX_API_KEY': ''}, clear=False):
            system = UniversalSearchSystem()

        payload = system.intelx_search('+15551234567')

        self.assertFalse(payload['success'])
        self.assertFalse(payload['configured'])
        self.assertEqual(payload['error'], 'INTELX_API_KEY is not configured')

    def test_intelx_search_returns_records(self) -> None:
        with patch.dict(
            os.environ,
            {'INTELX_API_KEY': 'test-key', 'INTELX_API_URL': 'https://free.intelx.io'},
            clear=False,
        ):
            system = UniversalSearchSystem()

        responses = [
            Mock(status_code=200, json=Mock(return_value={'id': 'search-123'}), raise_for_status=Mock()),
            Mock(
                status_code=200,
                json=Mock(
                    return_value={
                        'status': 1,
                        'records': [
                            {
                                'systemid': 'sys-1',
                                'storageid': 'store-1',
                                'name': 'Leaked record',
                                'description': 'Matched selector',
                                'bucket': 'leaks.public',
                                'bucketh': 'Leaks » Public',
                                'media': 24,
                                'mediah': 'Text file',
                                'date': '2025-01-02T03:04:05Z',
                                'added': '2025-01-03T03:04:05Z',
                                'xscore': 88,
                                'tagsh': [{'classh': 'Email', 'valueh': 'user@example.com'}],
                            }
                        ],
                    }
                ),
                raise_for_status=Mock(),
            ),
            Mock(status_code=204, json=Mock(return_value={}), raise_for_status=Mock()),
        ]

        with patch.object(system, '_intelx_request', side_effect=responses) as mocked_request:
            payload = system.intelx_search('+15551234567', maxresults=5, timeout_seconds=2)

        self.assertTrue(payload['success'])
        self.assertTrue(payload['configured'])
        self.assertTrue(payload['found'])
        self.assertEqual(payload['records_returned'], 1)
        self.assertEqual(payload['records'][0]['systemid'], 'sys-1')
        self.assertEqual(mocked_request.call_args_list[0].kwargs['params']['term'], '+15551234567')
        self.assertEqual(mocked_request.call_args_list[1].kwargs['params']['id'], 'search-123')

    def test_intelx_endpoint_returns_503_when_not_configured(self) -> None:
        with app.test_client() as client, patch(
            'universal_search_system.universal_search.intelx_search',
            return_value={
                'service': 'IntelX',
                'success': False,
                'configured': False,
                'error': 'INTELX_API_KEY is not configured',
            },
        ):
            response = client.get('/api/intelx_search?term=%2B15551234567')

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()['service'], 'IntelX')


if __name__ == '__main__':
    unittest.main()
