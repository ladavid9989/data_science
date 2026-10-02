"""Identity-bound facts, including visible text when structured year data is absent."""
import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

from tracker.collect import detail_property, search_row


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []
        self.canonical = ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical = attrs.get('href', '')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, text):
        if not self.hidden:
            self.parts.append(text)


def extract_detail(html, pid):
    page = PageText()
    page.feed(html)
    identity = pid.split(':')[-1]
    try:
        prop = detail_property(html, pid)
    except (KeyError, ValueError, TypeError):
        if not re.search(r'/' + re.escape(identity) + r'_zpid/?$', page.canonical):
            raise ValueError('Cannot verify detail identity')
        prop = {'zpid': identity}
    candidates = [(prop.get('yearBuilt'), 'property.yearBuilt'),
                  ((prop.get('resoFacts') or {}).get('yearBuilt'), 'property.resoFacts.yearBuilt')]
    structured = {(int(str(y)), source) for y, source in candidates
                  if re.fullmatch(r'\d{4}', str(y)) and 1600 <= int(y) <= datetime.now().year + 5}
    years = {y for y, _ in structured}
    if len(years) > 1:
        prop.update(year_status='conflict', extracted_year=None)
        return prop
    if structured:
        year, source = sorted(structured)[0]
    else:
        visible = ' '.join(page.parts)
        visible = re.split(r'Similar homes|Nearby homes|You may also like', visible, flags=re.I)[0]
        matches = {int(y) for y in re.findall(r'\bBuilt\s+in\s+(\d{4})\b', visible, flags=re.I)
                   if 1600 <= int(y) <= datetime.now().year + 5}
        year = next(iter(matches)) if len(matches) == 1 else None
        source = 'detail visible Built in text' if year else ''
    prop.update(extracted_year=year, year_source=source,
                year_status='verified' if year else 'not_in_response')
    return prop


def facts_hash(row):
    keys = ('property_id', 'episode_id', 'price', 'status', 'year_built', 'bedrooms', 'bathrooms',
            'square_feet', 'sold_price', 'sold_date')
    return hashlib.sha256(json.dumps({k: row.get(k) for k in keys}, sort_keys=True).encode()).hexdigest()


def extract_search(item, stamp):
    row = search_row(item)
    info = item.get('hdpData', {}).get('homeInfo', {})
    change = info.get('priceChange')
    cut = -change if isinstance(change, (int, float)) and change < 0 else None
    if cut is None and item.get('contentType') == 'priceCut':
        match = re.search(r'Price cut:\s*\$([\d,.]+)\s*([KM]?)', item.get('flexFieldText', ''), re.I)
        if match:
            cut = float(match[1].replace(',', '')) * {'': 1, 'K': 1000, 'M': 1000000}[match[2].upper()]
    changed = info.get('datePriceChanged')
    cut_date = datetime.fromtimestamp(changed / 1000, timezone.utc).date().isoformat() if cut and isinstance(changed, (int, float)) else None
    row.update(price_observed_at=stamp, year_status='verified' if row['year_built'] else 'not_requested',
               price_cut=cut, price_cut_date=cut_date, cut_source='Zillow reported price cut' if cut else None)
    row['facts_hash'] = facts_hash(row)
    return row
