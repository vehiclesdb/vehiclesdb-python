"""Published resolution ladder; port of the Ruby ModelMatcher (RESOLUTION.md)."""
import re
from ._normalize import fold
from .models import Resolution, MATCH_CONFIDENCE

FILLERS = set('nuevo nueva new neu neue nouveau nouvelle nuovo nuova novo nova'.split())


def raw_key(s):
    return str(s or '').strip().lower()


def eligible(raw):
    s = str(raw or '').strip()
    return all(not (re.search(r'[/_+\\]', token) or token.startswith('-') or token.endswith('-') or '--' in token or
                    re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)+', token) or
                    re.fullmatch(r'[A-Z0-9]+(?:-[A-Z0-9]+)+', token)) for token in s.split())


def distance(a, b, limit):
    """Optimal string alignment, with adjacent transposition as one edit."""
    prev2, prev = None, list(range(len(b) + 1))
    for i, ch in enumerate(a, 1):
        cur = [i]
        for j, other in enumerate(b, 1):
            n = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ch != other))
            if prev2 is not None and j > 1 and ch == b[j - 2] and a[i - 2] == other:
                n = min(n, prev2[j - 2] + 1)
            cur.append(n)
        if min(cur) > limit and min(prev) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return min(prev[-1], limit + 1)


def word_distance(query, key):
    if len(query) < 4:
        return None
    limit = 2 if len(query) >= 6 else 1
    if abs(len(query) - len(key)) > limit:
        return None
    words, others = query.split(), key.split()
    if len(words) != len(others):
        return None
    total = 0
    for a, b in zip(words, others):
        if a == b:
            continue
        if a[0] != b[0] or re.search('[0-9]', a + b) or min(len(a), len(b)) < 4:
            return None
        budget = 2 if len(a) >= 9 else 1
        d = distance(a, b, budget)
        total += d
        if d > budget or total > limit:
            return None
    return total or None


class Resolver:
    def __init__(self, db):
        self.db = db
        self.scopes = {}
        self.make_keys = []
        for make in db._makes:
            for s in [make.name, make.slug] + (make.aliases or []):
                if fold(s):
                    self.make_keys.append((fold(s), make))
            self.scopes[make.slug] = [
                dict(model=m, name=fold(m.name), slug=fold(m.slug),
                     aliases=[fold(a) for a in m.aliases or [] if fold(a)],
                     forms=[fold(a) for a in m.forms or [] if fold(a)])
                for m in db._models_by_make.get(make.slug, [])]

    def pick(self, models):
        from .client import pick_collision
        return pick_collision(models)

    def result(self, hits, method, via, ambiguous=False, confidence=None, selected=None):
        hits = list({m.id: m for m in hits}.values())
        model = None if ambiguous else (selected or self.pick(hits)) if hits else None
        if model is None and not ambiguous:
            return None
        score = 0.0 if ambiguous else MATCH_CONFIDENCE[method] if confidence is None else confidence
        return Resolution(id=model.id if model else None, kind=model.kind if model else None,
                          make=model.make_name if model else None, model=model.name if model else None,
                          method=method, confidence=score, via=list(via), candidates=hits,
                          ambiguous=ambiguous, record=model)

    def make(self, raw, fuzzy=True):
        q, key = fold(raw), raw_key(raw)
        for m in self.db._makes:
            if q and q in (fold(m.name), fold(m.slug)):
                return dict(make=m, via=[], typo=False)
        for m in self.db._makes:
            if q and any(fold(f) == q for f in m.former_slugs):
                return dict(make=m, via=['former_make_slug:%s→%s' % (q, m.slug)], typo=False)
        for m in self.db._makes:
            if any(fold(a) == q if q else key and raw_key(a) == key for a in m.aliases or []):
                return dict(make=m, via=['make_alias:%s→%s' % (q, m.slug)] if q else [], typo=False)
        if not fuzzy or not eligible(raw) or len(q) < 4:
            return None
        limit = 2 if len(q) >= 6 else 1
        words = q.split()
        best, hits = float('inf'), {}
        for k, m in self.make_keys:
            other = k.split()
            if abs(len(q) - len(k)) > limit or len(other) < len(words):
                continue
            if len(other) == len(words):
                if any(a[0] != b[0] for a, b in zip(words, other)):
                    continue
            elif words[0][0] != other[0][0]:
                continue
            d = distance(q, k, limit)
            if d > limit or d > best:
                continue
            if d < best:
                best, hits = d, {}
            hits[m.slug] = m
        if len(hits) != 1:
            return None
        m = next(iter(hits.values()))
        return dict(make=m, via=['make_typo:%s→%s' % (q, m.slug)], typo=True)

    def scope(self, make, kind, country, kinds=None):
        return [e for e in self.scopes[make.slug] if
                (not kind or e['model'].kind == kind) and (kinds is None or e['model'].kind in kinds) and
                (not country or raw_key(country) in e['model'].availability)]

    def rungs(self, entries, query, via, cap):
        sq = query.replace(' ', '')
        hits = [e for e in entries if query in (e['name'], e['slug'])]
        transformed, ambiguous = False, False
        if not hits:
            hits = [e for e in entries if e['name'].replace(' ', '') == sq]
            transformed = True
            ambiguous = len({e['model'].slug for e in hits}) > 1
        if not hits and re.fullmatch(r'serie \w+', query):
            series = re.sub(r'^serie (\w+)$', r'\1 series', query)
            hits = [e for e in entries if series in (e['name'], e['slug'])]
            if not hits:
                hits = [e for e in entries if e['name'].replace(' ', '') == series.replace(' ', '')]
                ambiguous = len({e['model'].slug for e in hits}) > 1
            transformed = True
        if hits:
            models = [e['model'] for e in hits]
            steps = ['fold:%s' % query] if ambiguous else ['fold:%s→%s' % (query, self.pick(models).slug)] if transformed else []
            return self.result(models, 'fold' if ambiguous else cap or 'fold', via + steps, ambiguous)
        for field, method in [('aliases', 'alias'), ('forms', 'form')]:
            hits = [e for e in entries if query in e[field]]
            if not hits:
                hits = [e for e in entries if any(s.replace(' ', '') == sq for s in e[field])]
            if not hits:
                continue
            models = [e['model'] for e in hits]
            ambiguous = len({m.slug for m in models}) > 1
            step = '%s:%s%s' % (method, query, '' if ambiguous else '→' + self.pick(models).slug)
            return self.result(models, method if ambiguous else cap or method, via + [step], ambiguous)
        return None

    def ladder(self, resolved, raw, kind=None, country=None, heuristics=True, make_query='', kinds=None):
        make, typo = resolved['make'], resolved['typo']
        via = (['kind_hint:%s' % kind] if kind else []) + resolved['via']
        entries = self.scope(make, kind, country, kinds)
        query = fold(raw)
        if not query:
            hits = [e['model'] for e in entries if raw_key(raw) and any(raw_key(a) == raw_key(raw) for a in e['model'].aliases or [])]
            if not hits:
                return None
            ambiguous = len({m.slug for m in hits}) > 1
            return self.result(hits, 'fuzzy' if typo and not ambiguous else 'alias',
                               via + ['alias:%s%s' % (str(raw).strip(), '' if ambiguous else '→' + self.pick(hits).slug)], ambiguous)
        exact = self.rungs(entries, query, via, 'fuzzy' if typo else None)
        if exact is not None or not heuristics or not eligible(raw):
            return exact
        all_entries = self.scopes[make.slug]

        def model_word(key):
            return any(key in (e['name'], e['slug']) or key in e['aliases'] for e in all_entries)

        names = [make.name, make.slug] + (make.aliases or []) + ([make_query] if not typo else [])
        names += [n.replace('&', ' and ') for n in names if '&' in n]
        echoes = sorted(dict.fromkeys(fold(n) for n in names if fold(n)), key=lambda n: -len(n.split()))
        steps = []
        while query:
            head = query.split()[0]
            if head in FILLERS and not model_word(head):
                peel, step = head, 'filler:%s' % head
            else:
                peel = next((e for e in echoes if (query == e or query.startswith(e + ' ')) and not model_word(e)), None)
                step = 'make_echo:%s' % peel
            if not peel:
                break
            query = query[len(peel):].strip()
            steps.append(step)
            if not query:
                return None
            retried = self.rungs(entries, query, via + steps, 'fuzzy' if typo else 'cleaned')
            if retried is not None:
                return retried
        if typo:
            return None
        best = {}
        for e in entries:
            for key in [e['name']] + e['aliases'] + e['forms']:
                d = word_distance(query, key)
                if d is None:
                    continue
                old = best.get(e['model'].slug)
                if old is None or d < old[0]:
                    best[e['model'].slug] = [d, key, [e['model']]]
                elif d == old[0]:
                    old[2].append(e['model'])
        ranked = sorted(best.values(), key=lambda r: r[0])
        if not ranked:
            return None
        top = [r for r in ranked if r[0] == ranked[0][0]]
        ambiguous = len(top) > 1
        return self.result([m for r in top for m in r[2]], 'fuzzy',
                           via + steps + ['model_typo:%s%s' % (query, '' if ambiguous else '→' + top[0][1])], ambiguous)

    def pair(self, make, model, kind=None, country=None, kinds=None):
        resolved = self.make(make)
        if resolved is None:
            return None
        return self.ladder(resolved, model, kind, country, make_query=make, kinds=kinds)

    def text(self, raw, kind=None, country=None, kinds=None):
        raw = str(raw or '').strip()
        if not raw:
            return None

        def allowed(m):
            return ((not kind or m.kind == kind) and (kinds is None or m.kind in kinds) and
                    (not country or raw_key(country) in m.availability))

        hint = ['kind_hint:%s' % kind] if kind else []
        def by_id(hits, method):
            hits = [m for m in hits if (kinds is None or m.kind in kinds) and
                    (not country or raw_key(country) in m.availability)]
            if not hits:
                return None
            via = hint + ['%s:%s' % (method, raw)]
            if len({(m.make_id, m.slug) for m in hits}) > 1:
                return self.result(hits, method, via, True)
            preferred = [m for m in hits if kind and m.kind == kind]
            return self.result(hits, method, via, selected=self.pick(preferred or hits))

        exact = self.db._models_by_id.get(raw)
        former = [m for m in self.db._former_ids.get(raw.lower(), []) if raw in (m.former_ids or [])]
        id_result = by_id([exact] if exact is not None else [], 'exact') or by_id(former, 'former_id')
        if id_result is not None:
            return id_result
        q = fold(raw)
        if not q:
            return None
        tokens = q.split()
        split = None
        for fuzzy in ((False, True) if eligible(raw) else (False,)):
            for i in range(len(tokens) - (1 if fuzzy else 0), 0, -1):
                make_query, model = ' '.join(tokens[:i]), ' '.join(tokens[i:])
                resolved = self.make(make_query, fuzzy)
                if resolved is not None:
                    split = (resolved, model, make_query)
                    break
            if split:
                break
        if split and split[1]:
            found = self.rungs(self.scope(split[0]['make'], kind, country, kinds), split[1],
                               hint + split[0]['via'], 'fuzzy' if split[0]['typo'] else None)
            if found is not None:
                return found
        hits = [m for m in self.db._alias_index.get(q, []) if allowed(m)]
        if hits:
            records = {(m.make_id, m.slug) for m in hits}
            named = {(m.make_id, m.slug) for m in self.db._name_index.get(q, []) if fold(m.name) == q}
            if not (named - records):
                if len(records) > 1:
                    return self.result(hits, 'alias', hint + ['alias:%s' % q], True)
                model = self.pick(hits)
                return self.result(hits, 'alias', hint + ['alias:%s→%s/%s' % (q, model.make_id, model.slug)], confidence=.90)
        if not split or not split[1] or not eligible(raw):
            return None
        return self.ladder(split[0], split[1], kind, country, True, split[2], kinds)
