# Zillow HTTP feasibility probe: 2026-09-29

## Scope

The user requested an actual small scraping attempt, then narrowed the criteria to North Gwinnett High School, asking price USD 400,000-700,000 inclusive, at least three bedrooms, at least two bathrooms, and Zillow's Houses property type (SINGLE_FAMILY). Property types other than houses were disabled. Other sale-status options were left at the site's defaults.

This supplements FEASIBILITY.md: the earlier research had not performed live Zillow requests. A successful technical probe does not change Zillow's published automated-access restrictions or establish long-term operational reliability.

## Actual checks

The Browser runtime reported no available browser. A web retrieval tool returned a school-page representation crawled two days earlier; it was not counted as a current observation. The live tests below used ordinary PowerShell HTTP GET requests to public Zillow HTML pages, not that cached representation.

Five direct Zillow requests were made across the experiment: two unfiltered school-page requests (the second saved the page for inspection), one price-filtered request, one fully filtered request, and one property detail request. All returned HTTP 200. No CAPTCHA, login, proxy, retry loop, or access-control bypass was used.

| Check | Observed result |
| --- | --- |
| School page | HTTP 200; returned school ID 102507 and North Gwinnett High School |
| Price-only search | At 22:36:43 UTC, site reported 113 results and three pages; first-page extraction contained 41 entries, all in range |
| Price + 3 bedrooms + 2 bathrooms + Houses | At 22:39:55 UTC (18:39:55 America/New_York), site reported 71 results and two pages |
| Fully filtered first page | 41 records; 41 distinct Zillow property IDs; zero price/bed/bath/type violations |
| Returned search state | Price, minimum beds/baths, excluded property types, and school were validated; default values were included when interpreting omitted filters |
| Available list fields | Property ID, address, asking price, bedrooms, bathrooms, area, property type, display status, coordinates, and detail URL |
| Year built in list records | Absent from the extracted homeInfo fields in all 41 records |
| One detail page | HTTP 200; embedded property object matched zpid 58607266 and reported yearBuilt=2000 |

The site-reported 71 is not an independently verified count of eligible homes in the official school attendance polygon. The page title says homes near the school. No official polygon join was performed in this probe. No second result page was fetched after the user narrowed the experiment to a sample. Thus completeness, cross-page duplication, and full-universe statistics remain unverified.

The cached web representation and direct page response differed in counts and at least one displayed property attribute. This reinforces using our own observation timestamps and source-response provenance instead of treating search-engine representations as current snapshots.

## Reproduction

[probe_zillow.ps1](../scripts/probe_zillow.ps1) is a bounded, manually invoked first-page probe. It fetches the school page for query context and then one filtered HTML page. The optional SeedHtml parameter reuses a previously saved page, reducing this to one request. It stops on HTTP errors or recognized challenges and validates returned filters and records. It does not fetch property details or subsequent result pages.

```powershell
./housing-tracker/scripts/probe_zillow.ps1 -OutputDirectory <private-output-directory>
```

Use an output directory outside the code repository. The experiment's HTML responses, first-page CSV, and summaries were saved locally under the workspace's housing-tracker/probe-output directory. They were not committed or uploaded. Output filenames are overwritten on a subsequent run: this probe is not the future append-only historical collector.

## Implications

- Technical feasibility is demonstrated for a small request set from this local network at this time. Zillow must no longer be described as technically untested in this project.
- The complete filter reduced the site-reported result set from 113 to 71, and page count from three to two, relative to price alone.
- Basic list extraction needs a page request, not a paid data API call per home. Full detail enrichment may require additional requests; year built was tested on only one home.
- The exact same code may behave differently on GitHub Actions or another cloud host. No hosted-network test or multi-day reliability test was performed.
- A first-page sample is insufficient for a median across all reported results; no such statistic was calculated.
- Preserve and validate geographic scope, sale-status semantics, pagination, missingness, and filter entry/exit before using this route for market tracking.
- [Zillow terms](https://www.zillow.com/corporate/terms-of-use/) still restrict automated queries. This experiment is evidence about access behavior, not permission to operate a recurring collector.

No scheduled scraping, dashboard deployment, paid service, or account setup was performed.

## Follow-up: Built in text and year-built coverage

The user asked why only one construction year was reported. Only one detail page had been tested; that was a sample-size limitation, not evidence that other homes lack construction years.

Two additional detail GET requests at approximately 22:43:36-37 UTC succeeded with HTTP 200. Three saved pages now have matching visible Built in text and structured years:

| Zillow property ID | Visible text | Structured field |
| --- | --- | --- |
| 58607266 | Built in 2000 | property.yearBuilt |
| 14841020 | Built in 1998 | property.resoFacts.yearBuilt |
| 55042868 | Built in 2000 | property.resoFacts.yearBuilt |

An offline cross-check matched each embedded property object's ID to the requested home and verified equality with the visible year. Reading only property.yearBuilt would incorrectly classify the latter two as missing; the nested resoFacts field is required for those page variants. These checks were saved locally as year-built-validated.json. All three inspected homes had an extractable construction year; coverage for the remaining homes has not been measured.

Proposed collection behavior: enrich each newly encountered property from its detail page and preserve the construction year with its source and observation timestamp. Reuse that relatively stable attribute during daily price/inventory updates, periodically rechecking it for corrections and treating new construction separately. First-page search results alone do not establish year-built completeness. The total direct Zillow request count across the initial probe and this follow-up is seven; no challenge or retry was encountered.
