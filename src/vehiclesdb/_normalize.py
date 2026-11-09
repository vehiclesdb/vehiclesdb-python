"""The shared RESOLUTION.md §2 normalization, identical to the JS SDK."""
import re
import unicodedata


def fold(value):
    if value is None:
        return ''
    text = ''.join(c for c in unicodedata.normalize('NFKD', str(value))
                   if unicodedata.category(c) != 'Mn')
    return re.sub('[^a-z0-9]+', ' ', text.lower()).strip()


def slugify(value):
    return fold(value).replace(' ', '-')


def tokens(value):
    return value.split()
