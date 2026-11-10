"""Contract checks and the external, version-gated conformance suite."""
import json
import os
import unittest
from pathlib import Path
from helpers import FIXTURES_DIR
from vehiclesdb import VehiclesDB
from vehiclesdb._normalize import fold

ROOT = Path(FIXTURES_DIR).parent
DATA_PATH = Path(os.environ.get('VDB_DATA', str(Path(FIXTURES_DIR) / 'dist/vehicles.json'))).expanduser()
if DATA_PATH.is_dir():
    DATA_PATH = DATA_PATH / 'dist/vehicles.json'
DIST = json.loads(DATA_PATH.read_text())
CONFORMANCE = Path(os.environ.get('VDB_CONFORMANCE', str(ROOT.parent / 'vehiclesdb/conformance/resolve.json'))).expanduser()


def client(data=DIST):
    def transport(url, headers):
        assert url.endswith('/dist/vehicles.json'), url
        return 200, json.dumps(data).encode()
    return VehiclesDB(transport=transport)


class ResolutionContractTest(unittest.TestCase):
    def test_normalization(self):
        for text, expected in [('Škoda', 'skoda'), ('ﬁ ①', 'fi 1'), ('Straße', 'stra e'), ('丰田', ''), ('a\u034fb', 'ab')]:
            self.assertEqual(fold(text), expected)

    def test_pair_ladder(self):
        db = client(json.loads((Path(FIXTURES_DIR) / 'dist/vehicles.json').read_text()))
        a = db.model_match('VW', 'Golf')
        self.assertEqual(db.model_match('トヨタ', 'カローラ').via, ['alias:カローラ→corolla'])
        self.assertEqual((a.method, a.confidence, a.via), ('fold', .97, ['make_alias:vw→volkswagen']))
        b = db.model_match('Volkswagon', 'Golf')
        self.assertEqual((b.method, b.confidence, b.via), ('fuzzy', .8, ['make_typo:volkswagon→volkswagen']))
        c = db.model_match('VW', 'Nuevo Volkswagen Golf', kind='car')
        self.assertEqual((c.method, c.confidence), ('cleaned', .9))
        self.assertEqual(c.via, ['kind_hint:car', 'make_alias:vw→volkswagen', 'filler:nuevo', 'make_echo:volkswagen'])
        for make, model in [('Volkswagon', 'Gollf'), ('VW', 'Volkswagen'), ('VW', 'golf-extra')]:
            self.assertIsNone(db.model_match(make, model))
        self.assertIsNone(db.resolve('VW Golf 1.9 TDI'))
        self.assertIsNone(db.resolve('golf'))
        self.assertIsNone(db.resolve('VW+ Gollf'))
        typo = db.model_match('VW', 'Gollf')
        self.assertEqual(typo.method, 'fuzzy')
        self.assertEqual(typo.via, ['make_alias:vw→volkswagen', 'model_typo:gollf→golf'])

    def test_ambiguity_and_guards(self):
        db = client(dict(version='1', kinds=['van', 'car'], makes=[dict(name='Example', slug='example', aliases=['Ex'], models=[
            dict(name='Alpha', slug='alpha', kind='car', aliases=['Shared', 'One Two'], forms=['Registry', 'Echo']),
            dict(name='Alphi', slug='alphi', kind='car', aliases=['Shared', 'On E Two'], forms=['Registry', 'E c h o']),
            dict(name='A B', slug='a-b', kind='car'), dict(name='AB', slug='ab', kind='car'),
            dict(name='A BC', slug='a-bc', kind='car'), dict(name='AB C', slug='ab-c', kind='car'),
            dict(name='Twin Name', slug='twin-one', kind='car'), dict(name='Twin Name', slug='twin-two', kind='car'),
            dict(name='Alpha Z', slug='alpha-z', kind='car'), dict(name='Alpha Foo Bar', slug='alpha-foo-bar', kind='car'),
            dict(name='Alpha', slug='alpha', kind='van', global_decile=1),
            dict(name='2008', slug='2008', kind='car')])]))
        for query, method in [('A B C', 'fold'), ('TwinName', 'fold'), ('Shared', 'alias'), ('One T wo', 'alias'), ('Registry', 'form'), ('Ech o', 'form'), ('Alphu', 'fuzzy'), ('New Registry', 'form')]:
            r = db.model_match('Example', query)
            self.assertTrue(r.ambiguous, query)
            self.assertIsNone(r.match)
            self.assertGreaterEqual(len(r.alternates), 2)
            self.assertEqual((r.method, r.confidence), (method, 0))
        self.assertEqual(db.model_match('Example', 'a b').id, 'car/example/a-b')
        self.assertEqual(db.model_match('Example', 'Alpha').kind, 'van')
        self.assertEqual(db.model_match('Example', 'Alpha', kind='car').kind, 'car')
        for q in ['208', 'alpha_typo', 'alpha/typo', 'alpha+typo', 'alpha\\typo', 'alphu-slug', 'ALPHU-SLUG']:
            self.assertIsNone(db.model_match('Example', q), q)
        self.assertTrue(db.resolve('Shared').ambiguous)
        self.assertIsNone(db.model_match('Example', 'New alpha-z'))
        self.assertIsNone(db.resolve('exampel alpha-z'))
        self.assertIsNone(db.resolve('Example Alpah foo-bar'))
        self.assertEqual(db.resolve('Example Alpah Foo-Bar').method, 'fuzzy')
        self.assertEqual(db.resolve('Example alpha-z').id, 'car/example/alpha-z')

    @unittest.skipUnless(os.environ.get('VDB_DATA'), 'set VDB_DATA to the dist with forms')
    def test_real_forms(self):
        db = client()
        for make, model, expected, method in [
            ('Peugeot', '2008 Allure', 'car/peugeot/2008', 'form'),
            ('Opel', 'Insigna', 'car/opel/insignia', 'form'),
            ('VW', 'Toureg', 'car/volkswagen/touareg', 'form'),
            ('Citroen', 'Nuevo Citroën C3 Aircr', 'car/citroen/c3-aircross', 'form'),
            ('Kia', 'XCeed', 'car/kia/x-ceed', 'fold'),
            ('BMW', 'Serie 3', 'car/bmw/3-series', 'fold'),
            ('Mercedes', 'c class', 'car/mercedes-benz/c-class', 'fold')]:
            for r in [db.model_match(make, model, kind='car'), db.resolve(make + ' ' + model, kind='car')]:
                self.assertIsNotNone(r, (make, model))
                self.assertEqual((r.id, r.method), (expected, method))
        self.assertIsNone(db.model_match('Toyota', '2008 Allure'))
        self.assertIsNone(db.resolve('2008 Allure'))

    @unittest.skipUnless(CONFORMANCE.is_file(), 'absent: %s' % CONFORMANCE)
    def test_conformance(self):
        data = json.loads(CONFORMANCE.read_text())
        db = client()
        for c in data if isinstance(data, list) else data['cases']:
            with self.subTest(case=c):
                if c.get('min_dataset') and tuple(map(int, DIST['version'].split('.'))) < tuple(map(int, c['min_dataset'].split('.'))):
                    self.skipTest('needs dataset %s' % c['min_dataset'])
                r = db.model_match(c['make'], c['model'], kind=c.get('kind'), kinds=c.get('kinds')) if c['entry'] == 'pair' else db.resolve(c['input'], kind=c.get('kind'), kinds=c.get('kinds'))
                if c['expect'] == 'ambiguous':
                    self.assertTrue(r.ambiguous)
                    self.assertIsNone(r.match)
                    self.assertGreater(len(r.alternates), 1)
                elif c['expect'] is None:
                    self.assertIsNone(r)
                else:
                    self.assertIsNotNone(r)
                    self.assertEqual(r.id, c['expect'])
                    self.assertFalse(r.ambiguous)
                if c.get('method'):
                    self.assertEqual(r.method, c['method'])

    def test_echoes_protected_fillers_and_make_ties(self):
        db = client(dict(version='1', kinds=['car'], makes=[
            dict(name='A & B', slug='a-b', models=[
                dict(name='Alpha', slug='alpha', kind='car', aliases=['Space'], forms=['Registry/Alpha']),
                dict(name='Nova', slug='nova', kind='car'), dict(name='SS', slug='ss', kind='car')]),
            *[dict(name=n, slug=n.lower(), models=[dict(name='Alpha', slug='alpha', kind='car')]) for n in ['Acma', 'Acura']]]))
        echo = db.model_match('A & B', 'A And B Alpha')
        self.assertEqual((echo.method, echo.via), ('cleaned', ['make_echo:a and b']))
        self.assertIsNone(db.model_match('A & B', 'B Alpha'))
        self.assertIsNone(db.model_match('A & B', 'Nova SS'))
        self.assertEqual(db.model_match('A & B', 'Sp a ce').method, 'alias')
        self.assertEqual(db.model_match('A & B', 'Registry/Alpha').method, 'form')
        self.assertIsNone(db.model_match('Acra', 'Alpha'))
        self.assertIsNone(db.model_match('Acurra', 'Space'))
        self.assertEqual(db.model_match('Acurra', 'Alpha').method, 'fuzzy')

    def test_make_typo_distance_and_unique_make(self):
        makes = [dict(name=n, slug=n.lower().replace(' ', '-'),
                      models=[dict(name='Alpha', slug='alpha', kind='car')])
                 for n in ['De Lorean', 'Acma', 'Acura', 'Car AB8', 'Bus Ab']]
        db = client(dict(version='1', kinds=['car'], makes=makes))
        for make, slug in [('delorean', 'de-lorean'), ('car ab9', 'car-ab8'), ('bus ac', 'bus-ab')]:
            result = db.model_match(make, 'Alpha')
            self.assertEqual((result.id, result.method), ('car/%s/alpha' % slug, 'fuzzy'))
        self.assertIsNone(db.model_match('acra', 'Alpha'))
        self.assertIsNone(db.resolve('acra alpha'))
        self.assertIsNone(db.model_match('delorean extra', 'Alpha'))

    def test_text_matcher_splits_aliases_and_id_trails(self):
        db = client(dict(version='1', kinds=['car', 'van'], makes=[
            dict(name='Land', slug='land', models=[dict(name='Rover Defender', slug='rover-defender', kind='car'),
                 dict(name='Rovar Alpha', slug='rovar-alpha', kind='car')]),
            dict(name='Land Rover', slug='land-rover', models=[dict(name='Defender', slug='defender', kind='car')]),
            dict(name='Example', slug='example', models=[
                dict(name='Alpha', slug='alpha', kind='car', aliases=['Shared', 'Alpha'], former_ids=['car/example/old', 'car/example/collision']),
                dict(name='Alpha', slug='alpha', kind='van', aliases=['Shared']),
                dict(name='Beta', slug='beta', kind='car', aliases=['Collision'], former_ids=['car/example/collision'])]),
            dict(name='Other', slug='other', models=[dict(name='Collision', slug='collision', kind='car'),
                dict(name='Gamma', slug='gamma', kind='car', aliases=['Ambiguous'])]),
            dict(name='Third', slug='third', models=[dict(name='Delta', slug='delta', kind='car', aliases=['Ambiguous'])])]))
        self.assertEqual(db.resolve('land rover defender').id, 'car/land-rover/defender')
        self.assertEqual(db.resolve('land rovar alpha').id, 'car/land/rovar-alpha')
        self.assertEqual(db.resolve('alpha').id, 'car/example/alpha')
        self.assertIsNone(db.resolve('collision'))
        self.assertTrue(db.resolve('ambiguous').ambiguous)
        alias = db.resolve('shared', kind='van')
        self.assertEqual(alias.id, 'van/example/alpha')
        self.assertEqual(alias.via, ['kind_hint:van', 'alias:shared→example/alpha'])
        self.assertEqual(db.resolve('car/example/alpha').via, ['exact:car/example/alpha'])
        self.assertEqual(db.resolve('car/example/old').via, ['former_id:car/example/old'])
        self.assertTrue(db.resolve('car/example/collision', kind='van').ambiguous)
        self.assertIsNone(db.resolve('example+ alphi'))
