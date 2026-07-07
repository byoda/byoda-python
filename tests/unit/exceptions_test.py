#!/usr/bin/env python3

import unittest

from byoda.exceptions import ByodaRuntimeError
from byoda.exceptions import ByodaValueError


class TestByodaExceptions(unittest.TestCase):
    def test_runtime_error_constructor(self) -> None:
        exc = ByodaRuntimeError('boom', extra={'key': 'value'})

        self.assertIsInstance(exc, ByodaRuntimeError)
        self.assertIsInstance(exc, RuntimeError)
        self.assertEqual(str(exc), 'boom')

    def test_value_error_constructor(self) -> None:
        exc = ByodaValueError('bad value', extra={'key': 'value'})

        self.assertIsInstance(exc, ByodaValueError)
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(str(exc), 'bad value')


if __name__ == '__main__':
    unittest.main()
