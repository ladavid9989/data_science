"""Small resumable batches: durable response -> validated state -> published snapshot."""
import copy
import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from tracker.collect import (AccessBlocked, Client, SOURCES, contains, filters, read_json,
                             validate_page, write_json, zone_for)
from tracker.extraction import extract_detail, extract_search, facts_hash
from tracker.probe import next_data
from tracker.storage import BAND_SCOPE, import_snapshot, normalize_status
from tracker.band import in_band, restrict_snapshot

PRICE_RANGE = [400000, 700000]
# Allow a 30-minute scheduler's small start-time jitter, while rejecting duplicate wakeups.
MIN_BATCH_INTERVAL = timedelta(minutes=25)
DAILY_REQUEST_LIMIT = 96
SEARCH_REFRESH_INTERVAL = timedelta(hours=1)


def utcnow():
    return datetime.now(timezone.utc)


def day(stamp):
    return datetime.fromisoformat(stamp).astimezone(ZoneInfo('America/New_York')).date().isoformat()


class BatchFull(Exception):
    pass


class Batch:
    def __init__(self, db, archive, request_limit=3, detail_limit=2, delay=30, client=None):
        self.db, self.root = db, Path(archive)
        self.path = self.root / 'state/batch-v2.json.gz'
        self.state = read_json(self.path) if self.path.exists() else dict(turn=0, jobs={}, details={}, requests={})
        self.client = client or Client(self.root / 'raw', delay=delay, budget=request_limit)
        self.limit, self.detail_limit, self.used = request_limit, detail_limit, 0
        self.detail_requests = self.years_added = 0
        if not self.path.exists():
            for old in (self.root / 'state').glob('*-details.json.gz'):
                for pid, saved in read_json(old).items():
                    if saved.get('year_built'):
                        self.state['details'][pid] = {**saved, 'year_status': 'verified',
                            'year_observed_at': saved.get('checked_at'),
                            'next_check': (utcnow() + timedelta(days=90)).isoformat()}

    def save(self):
        write_json(self.path, self.state)

    def get(self, url):
        today = day(utcnow().isoformat())
        count = self.state['requests'].get(today, 0)
        if self.used >= self.limit or count >= DAILY_REQUEST_LIMIT:
            raise BatchFull()
        self.used += 1
        self.state['requests'] = {today: count + 1}
        self.save()  # Charge attempts before sending, including interrupted requests.
        return self.client.get(url)

    def response(self, job, url):
        pending = job.get('response')
        if pending:
            if pending['url'] != url:
                raise ValueError('Checkpoint request mismatch')
            body = gzip.decompress((self.root / 'raw' / (pending['sha256'] + '.gz')).read_bytes())
            if hashlib.sha256(body).hexdigest() != pending['sha256']:
                raise ValueError('Raw response checksum mismatch')
            return body.decode('utf-8-sig'), pending['observed_at']
        text = self.get(url)
        body = text.encode('utf-8')
        digest = hashlib.sha256(body).hexdigest()
        raw = self.root / 'raw' / (digest + '.gz')
        raw.parent.mkdir(parents=True, exist_ok=True)
        if not raw.exists():
            temporary = raw.with_suffix('.tmp')
            with temporary.open('wb') as handle:
                import os
                handle.write(gzip.compress(body, mtime=0))
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(raw)
        job['response'] = dict(url=url, sha256=digest, observed_at=utcnow().isoformat())
        self.save()  # A parser failure reuses these exact bytes next time.
        return text, job['response']['observed_at']

    def publish(self, snapshot):
        snapshot = restrict_snapshot(snapshot)
        # Outbox is saved first; crash/replay uses the identical run ID and timestamp.
        self.state['outbox'] = snapshot
        self.save()
        self.flush_outbox()

    def flush_outbox(self):
        snapshot = self.state.get('outbox')
        if not snapshot:
            return
        run_id, _ = import_snapshot(self.db, snapshot)
        write_json(self.root / 'snapshots' / snapshot['observed_at'][:10] /
                   f"{snapshot['school']}-{run_id}.json.gz", snapshot)
        self.state.pop('outbox')
        self.save()

    def cached_year(self, row):
        saved = self.state['details'].get(row['property_id'], {})
        for key in ('year_built', 'year_source', 'year_observed_at', 'year_status'):
            if saved.get(key) is not None:
                row[key] = saved[key]
        row['facts_hash'] = facts_hash(row)

    def snapshot(self, school, job, quality, note=''):
        rows = copy.deepcopy(list({**job.get('followed', {}), **job.get('rows', {})}.values()))
        for row in rows:
            self.cached_year(row)
        stamp = utcnow().isoformat()
        return dict(schema_version=1, dataset='observed', school=school, observed_at=stamp,
                    search_observed_at=job.get('finished_at', stamp),
                    collection_started_at=job['started_at'], collection_finished_at=job.get('finished_at'),
                    quality=quality, scope=BAND_SCOPE + ':' + job.get('zone', {}).get('version', 'unverified'),
                    boundary_version=job.get('zone', {}).get('version', 'unverified'),
                    coverage=dict(all_pages=quality == 'source_complete', all_prices=False,
                                  price_range=PRICE_RANGE, query_validated=quality == 'source_complete',
                                  official_zone_verified=False, point_in_time_consistent=False),
                    source='Zillow school search / bounded resumable batches', listings=rows,
                    reported_count=job.get('total'), expected_unique_count=len(rows),
                    evidence_files=job.get('evidence', []),
                    note=f"$400k-$700k; collection window {job['started_at']} to {job.get('finished_at', 'in progress')}. "
                         f"Page-number pagination; not a source snapshot cursor. {note}")

    def search(self, school, job):
        if 'zone' not in job:
            job['zone'] = zone_for(school, self.root, self)
            self.save()
        school_id, slug, _, _ = SOURCES[school]
        base = f'https://www.zillow.com/schools/{school_id}/{slug}/'
        if 'query' not in job:
            html, stamp = self.response(job, base)
            seed = next_data(html)['props']['pageProps']['searchPageState']
            job['query'] = copy.deepcopy(seed['queryState'])
            job['query'].setdefault('filterState', {}).update(filters(*PRICE_RANGE))
            job['defaults'] = seed.get('defaultFilterState', {})
            job['evidence'].append(job.pop('response'))
            self.save()
        while not job.get('finished_at'):
            page = job['next_page']
            query = copy.deepcopy(job['query'])
            query['pagination'] = {'currentPage': page}
            url = base + (f'{page}_p/' if page > 1 else '') + '?searchQueryState=' + quote(json.dumps(query, sort_keys=True, separators=(',', ':')))
            html, stamp = self.response(job, url)
            data = next_data(html)['props']['pageProps']['searchPageState']
            validate_page(data, school_id, filters(*PRICE_RANGE), job['defaults'], page)
            result = data['cat1']
            total, pages = int(result['searchList']['totalResultCount']), max(1, int(result['searchList']['totalPages']))
            if pages > 10 or ('total' in job and (total != job['total'] or pages != job['pages'])):
                raise ValueError('Pagination drift: changed count/pages; restart required')
            incoming, ids = {}, []
            for item in result['searchResults']['listResults']:
                if item.get('relaxed') or item.get('isHomeRec'):
                    continue
                row = extract_search(item, stamp)
                if (row['property_type'] != 'SINGLE_FAMILY' or (row['bedrooms'] or 0) < 3 or
                        (row['bathrooms'] or 0) < 2 or not PRICE_RANGE[0] <= (row['price'] or 0) <= PRICE_RANGE[1]):
                    raise ValueError('Returned property violates requested criteria')
                pid = row['property_id']
                row['first_seen'] = job.get('previous', {}).get(pid, {}).get('first_seen', stamp)
                if pid in ids or pid in job['ids']:
                    raise ValueError('Pagination drift: duplicate property across pages')
                ids.append(pid)
                member = contains(job['zone']['geometry'], row['longitude'], row['latitude'])
                if member is not False:
                    row['in_inventory'] = member is True
                    incoming[pid] = row
            if page >= pages and len(job['ids']) + len(ids) != total:
                raise ValueError('Pagination reconciliation failed')
            # Commit records and the next-page bookmark in ONE atomic replacement.
            job['rows'].update(incoming)
            job['ids'].extend(ids)
            job.update(total=total, pages=pages, next_page=page + 1)
            job['evidence'].append(job.pop('response'))
            if page >= pages:
                job['finished_at'] = stamp
            self.save()
        if not job.get('published'):
            previous = job.get('previous', {})
            job['watch'] = {pid: row for pid, row in previous.items() if pid not in job['rows'] and row.get('status') != 'sold'}
            job.pop('previous', None)
            job['published'] = True
            self.publish(self.snapshot(school, job, 'source_complete', 'All pages and unique source count reconciled.'))
            self.save()

    def detail_candidates(self, job):
        now = utcnow()
        candidates = []
        available = {**job.get('watch', {}), **job.get('rows', {})}
        for pid, row in available.items():
            if not in_band(row.get('price')):
                continue
            saved = self.state['details'].get(pid, {})
            if saved.get('next_check') and now < datetime.fromisoformat(saved['next_check']):
                continue
            # Unattempted, missing years first; among them prioritize the largest price cuts.
            cut = max(0, row.get('price_cut') or 0)
            impact = cut / (row['price'] + cut)
            candidates.append((int(bool(saved.get('year_built') or row.get('year_built'))),
                               saved.get('attempted_at', ''), -impact, pid))
        if job.get('response') and job.get('detail_pid'):
            pid = job['detail_pid']
            candidates = [(-1, '', 0, pid)] + [x for x in candidates if x[-1] != pid]
        return sorted(candidates)

    def enrichment_progress(self):
        result = {}
        for school, job in self.state['jobs'].items():
            rows = [r for r in job.get('rows', {}).values() if in_band(r.get('price'))]
            known = sum(bool(self.state['details'].get(r['property_id'], {}).get('year_built') or
                             r.get('year_built')) for r in rows)
            result[school] = dict(total=len(rows), known=known, missing=len(rows) - known,
                                 eligible=len(self.detail_candidates(job)))
        return result

    def choose_school(self, stamp):
        schools = list(SOURCES)
        offset = self.state['turn'] % len(schools)
        schools = schools[offset:] + schools[:offset]
        # Bootstrap newly added schools without rewriting existing jobs/checkpoints.
        for school in schools:
            if school not in self.state['jobs']:
                return school
        # Re-query the entire inventory even after every construction year is known.
        for school in schools:
            job = self.state['jobs'].get(school)
            if not job or job.get('restart') or self.search_due(job, stamp):
                return school
        eligible = [(self.detail_candidates(self.state['jobs'][school]), school) for school in schools]
        eligible = [(queue, school) for queue, school in eligible if queue and self.detail_limit > 0]
        return min(eligible, key=lambda pair: pair[0][0])[1] if eligible else None

    @staticmethod
    def search_due(job, stamp):
        return (not job.get('finished_at') or day(job['finished_at']) < day(stamp) or
                datetime.fromisoformat(stamp) - datetime.fromisoformat(job['started_at']) >= SEARCH_REFRESH_INTERVAL)

    def details(self, school, job):
        now = utcnow()
        available = {**job.get('watch', {}), **job['rows']}
        for _, _, _, pid in self.detail_candidates(job)[:self.detail_limit]:
            row = available[pid]
            saved = self.state['details'].setdefault(pid, {})
            job['detail_pid'] = pid
            try:
                before = self.used
                html, stamp = self.response(job, row['url'])
                self.detail_requests += self.used - before
                prop = extract_detail(html, pid)
            except (AccessBlocked, BatchFull):
                raise
            except Exception as exc:
                saved.update(attempted_at=utcnow().isoformat(), year_status='parse_failed', error=str(exc)[:200],
                             next_check=(utcnow() + timedelta(days=3)).isoformat())
                self.save()
                raise  # Keep raw response for offline reprocessing after parser repair.
            year = prop.get('extracted_year')
            saved.update(attempted_at=stamp, year_status=prop['year_status'],
                         next_check=(now + timedelta(days=7 if pid in job.get('watch', {}) or row.get('status') in ('pending', 'under_contract') else 90 if year else 7)).isoformat(),
                         raw=job['response'])
            if year:
                self.years_added += int(not (saved.get('year_built') or row.get('year_built')))
                saved.update(year_built=year, year_source=prop['year_source'], year_observed_at=stamp)
            self.cached_year(row)
            if pid in job.get('watch', {}):
                status = normalize_status(prop.get('homeStatus'))
                row.update(in_inventory=False, status=status, raw_status=prop.get('homeStatus'),
                           price=prop.get('price'), price_observed_at=stamp,
                           price_cut=None, price_cut_date=None, cut_source=None)
                if status == 'sold':
                    for event in prop.get('priceHistory') or []:
                        if str(event.get('event', '')).lower() == 'sold' and event.get('date', '') >= row.get('first_seen', job['started_at'])[:10]:
                            row.update(sold_price=event.get('price'), sold_date=event['date'], evidence='Explicit source sold event observed at ' + stamp)
                            break
                if in_band(row.get('price')):
                    job.setdefault('followed', {})[pid] = copy.deepcopy(row)
                else:
                    job['watch'].pop(pid, None)
                    job.setdefault('followed', {}).pop(pid, None)
            # Search price/status remain tied to their own observation timestamp.
            job['evidence'].append(job.pop('response'))
            job.pop('detail_pid', None)
            job['enrichment_dirty'] = True
            self.save()

    def publish_enrichment(self, school, job):
        if job.get('enrichment_dirty') and job.get('finished_at'):
            snapshot = self.snapshot(school, job, 'source_complete', 'Year enrichment; prices retain search timestamps.')
            # Clearing the flag and saving the outbox use the same atomic state write.
            job.pop('enrichment_dirty', None)
            self.publish(snapshot)

    def run(self):
        self.flush_outbox()
        # Recover cached detail facts saved before a crash, even during a network cooldown.
        for school, job in self.state['jobs'].items():
            self.publish_enrichment(school, job)
        policy = self.root / 'state/access.json.gz'
        if policy.exists() and utcnow() < datetime.fromisoformat(read_json(policy)['retry_after']):
            return {'status': 'cooldown', 'requests': 0, 'enrichment': self.enrichment_progress(), **read_json(policy)}
        now = utcnow()
        last_batch = self.state.get('last_batch_started_at')
        if last_batch:
            due = datetime.fromisoformat(last_batch) + MIN_BATCH_INTERVAL
            if now < due:
                return dict(status='interval_wait', requests=0, next_batch_at=due.isoformat(), enrichment=self.enrichment_progress())
        if self.state['requests'].get(day(now.isoformat()), 0) >= DAILY_REQUEST_LIMIT:
            return dict(status='daily_budget_wait', requests=0, enrichment=self.enrichment_progress())
        school = self.choose_school(now.isoformat())
        if school is None:
            return dict(status='idle', requests=0, enrichment=self.enrichment_progress())
        self.state['turn'] += 1
        self.state['last_batch_started_at'] = now.isoformat()
        self.save()
        stamp = utcnow().isoformat()
        job = self.state['jobs'].get(school)
        if job and not job.get('finished_at') and utcnow() - datetime.fromisoformat(job['started_at']) > timedelta(hours=24):
            self.publish(self.snapshot(school, job, 'partial' if job['rows'] else 'failed', 'Expired 24-hour incomplete cycle.'))
            job = None
        if job is None or job.get('restart') or (job.get('finished_at') and self.search_due(job, stamp)):
            previous = {**job.get('watch', {}), **job.get('rows', {})} if job else {}
            seed = {k: copy.deepcopy(job[k]) for k in ('query', 'defaults') if k in job} if job else {}
            job = dict(started_at=stamp, next_page=1, rows={}, ids=[], evidence=[], previous=previous)
            job.update(seed)
            self.state['jobs'][school] = job
            self.save()
        try:
            self.search(school, job)
            self.details(school, job)
            result = 'complete'
        except BatchFull:
            result = 'checkpointed'
        except AccessBlocked as exc:
            old = read_json(policy) if policy.exists() else {}
            strikes = min(old.get('strikes', 0) + 1, 5)
            wait = max(exc.wait_seconds, min(86400, 3600 * 2 ** (strikes - 1)))
            write_json(policy, dict(reason=str(exc), strikes=strikes,
                                    retry_after=(utcnow() + timedelta(seconds=wait)).isoformat()))
            result = 'blocked'
        except Exception as exc:
            result = 'error'
            job['error'] = str(exc)[:250]
            if 'Pagination' in str(exc) or 'criteria' in str(exc) or 'filter mismatch' in str(exc):
                job['restart'] = True
            self.save()
        self.publish_enrichment(school, job)
        if not job.get('finished_at'):
            self.publish(self.snapshot(school, job, 'partial' if job['rows'] else 'failed',
                                       f"{result}; next page {job['next_page']}. {job.get('error', '')}"))
        return dict(status=result, school=school, requests=self.used, next_page=job['next_page'],
                    years=sum(bool(v.get('year_built')) for v in self.state['details'].values()),
                    detail_requests=self.detail_requests, years_added=self.years_added,
                    enrichment=self.enrichment_progress(),
                    error=job.get('error'))


def collect_batch(db, archive, request_limit=3, detail_limit=2):
    return Batch(db, archive, request_limit, detail_limit).run()


def replay_details(db, archive, manifest, raw_dir):
    """Reparse saved detail responses, without contacting Zillow or rewriting history."""
    import re
    batch = Batch(db, archive)
    imported = 0
    for evidence in read_json(manifest):
        match = re.search(r'/(\d+)_zpid/', evidence['url'])
        if not match:
            continue
        body = gzip.decompress((Path(raw_dir) / (evidence['sha256'] + '.gz')).read_bytes())
        if hashlib.sha256(body).hexdigest() != evidence['sha256']:
            raise ValueError('Detail replay checksum mismatch')
        pid = 'zillow:' + match[1]
        prop = extract_detail(body.decode('utf-8-sig'), pid)
        old = batch.state['details'].get(pid, {})
        if old.get('year_observed_at', '') and old['year_observed_at'] > evidence['observed_at']:
            continue
        target = batch.root / 'raw' / (evidence['sha256'] + '.gz')
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_suffix('.tmp')
            with temporary.open('wb') as handle:
                import os
                handle.write(gzip.compress(body, mtime=0))
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(target)
        saved = dict(old, raw=evidence, year_status=prop['year_status'], attempted_at=evidence['observed_at'])
        if prop['extracted_year']:
            saved.update(year_built=prop['extracted_year'], year_source=prop['year_source'],
                         year_observed_at=evidence['observed_at'], next_check=(utcnow() + timedelta(days=90)).isoformat())
        batch.state['details'][pid] = saved
        batch.save()
        imported += 1
    return imported
