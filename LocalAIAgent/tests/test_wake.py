import unittest
from src.speech import wake


class WakeTests(unittest.TestCase):
    def check(self, text, expected):
        self.assertEqual(wake.match(text, 'Андрей'), expected, text)

    def test_start(self):
        self.check('Андрей, напиши текст привет', (True, 'напиши текст привет'))

    def test_only_name(self):
        self.check('Андрей.', (True, ''))

    def test_fillers(self):
        self.check('Эй, Андрей, открой калькулятор', (True, 'открой калькулятор'))

    def test_recognition_errors(self):
        self.check('Андрэй какая погода', (True, 'какая погода'))
        self.check('Andrey open notepad', (True, 'open notepad'))
        self.check('андрею позвони', (True, 'позвони'))

    def test_name_at_end(self):
        self.check('Открой калькулятор, Андрей', (True, 'Открой калькулятор'))

    def test_no_false_positive(self):
        for text in ('Андреевич привет', 'андерсен сказки', 'привет как дела', 'я вчера видел Андрея в магазине'):
            self.assertFalse(wake.match(text, 'Андрей')[0], text)

    def test_custom_name_and_aliases(self):
        self.assertEqual(wake.match('Джарвис, громче', 'Джарвис'), (True, 'громче'))
        self.assertEqual(wake.match('Andrew, stop', 'Андрей', 'Andrew'), (True, 'stop'))


if __name__ == '__main__':
    unittest.main()
