# School attendance zone housing tracker: feasibility research

Research date: 2026-09-29. Status: discovery, not an implementation or an approved deployment plan.

## Objective and constraints

Build a personal Streamlit dashboard comparing homes assigned to North Gwinnett High School (Gwinnett County Public Schools) and Johns Creek High School (Fulton County Schools), Georgia. Track listing inventory and asking prices over time with property filters. Collection should continue without a dashboard visit.

The user prefers zero recurring cost and currently has no MLS membership or broker partner. No paid subscription, provider account, deployed service, live listing collection, or scheduled job was created during this research. Current research does not establish actual inventory counts or API coverage in either attendance zone.

The existing public repository is ladavid9989/data_science. Keep implementation and research there on feature/school-housing-tracker. Store operational data in a separate persistent store; the code branch is not the running database or a sufficient backup system.

## Existing jobAgent implementation: verified findings

Reviewed remote jobAgent commit [8c394d071d5c1ecfe960fe04a9f82387179ce1ab](https://github.com/ladavid9989/data_science/tree/8c394d071d5c1ecfe960fe04a9f82387179ce1ab/job-agent), including README, architecture/handoff information, collectors, pipeline, persistence, and Streamlit. The current local workspace also contains a job-agent copy, but it is not a usable Git checkout in this environment; remote code is the reference.

| Area | Evidence | Implication |
| --- | --- | --- |
| Storage | [memory.py](https://github.com/ladavid9989/data_science/blob/8c394d071d5c1ecfe960fe04a9f82387179ce1ab/job-agent/src/memory.py#L103) updates existing jobs and retains first/last observation timestamps | Reuse persistence separation, not the overwrite-only entity model |
| Collection | [collectors.py](https://github.com/ladavid9989/data_science/blob/8c394d071d5c1ecfe960fe04a9f82387179ce1ab/job-agent/src/collectors.py#L129) logs failed requests and returns an empty dictionary; collect_all can skip failed sources | Housing counts need explicit failed/partial/complete runs; failure must not look like no inventory |
| Orchestration | [pipeline.py](https://github.com/ladavid9989/data_science/blob/8c394d071d5c1ecfe960fe04a9f82387179ce1ab/job-agent/src/pipeline.py) separates collect, score, and report | Useful structure for collect, validate, publish, and aggregate |
| Dashboard | [streamlit_app.py](https://github.com/ladavid9989/data_science/blob/8c394d071d5c1ecfe960fe04a9f82387179ce1ab/job-agent/streamlit_app.py#L33) starts pipeline on Refresh; cached reads are keyed by DB path | Move collection to scheduler; invalidate views by published run/version or TTL |
| Hosting | [README](https://github.com/ladavid9989/data_science/blob/8c394d071d5c1ecfe960fe04a9f82387179ce1ab/job-agent/README.md#L245) describes local-first operation; recursive branch tree contains no Actions workflow or deployment manifest | No established cloud server or scheduled collector was found in the reviewed branch |
| Version control | README excludes live SQLite files and generated private artifacts | Continue separating code and operational data |

The absence of deployment configuration in this branch does not prove no external deployment exists. No external hosting account was inspected. Ollama, resume processing, and job scoring are unrelated to the housing tracker and need not be carried over.

## Attendance boundaries: live read-only checks succeeded

School attendance zones, not the school district as a whole, city name, ZIP code, or radius around a school, define the target. In particular, Johns Creek High School belongs to Fulton County Schools; do not constrain its inventory to city=Suwanee.

### North Gwinnett High School

- Official [GCPS cluster page](https://www.gcpsk12.org/schools/clusters/north-gwinnett) links a cluster map.
- County public GIS [School Zones layer 26](https://gis3.gwinnettcounty.com/mapvis/rest/services/GISDataBrowser/GC_Main/MapServer/26) exposes polygon geometry and HIGH, MIDDLE, and ELEMENTARY fields.
- Live query on 2026-09-29: HIGH='North Gwinnett HS', output coordinates EPSG:4326, output format GeoJSON.
- Response: a FeatureCollection with four features and nonempty geometry: Riverside ES (Polygon), Level Creek ES (MultiPolygon), Roberts ES (Polygon), and Suwanee ES (Polygon). All list North Gwinnett MS and North Gwinnett HS.
- Proposed zone construction: union all matching features, preserving multipart geometry and holes.
- The layer response did not establish the applicable school year. Confirm it against current GCPS assignment information before treating it as the authoritative production boundary.

### Johns Creek High School

- Official [Fulton mapping page](https://www.fultonschools.org/all-departments/operations/operational-planning/mapping) links the school locator and attendance map.
- The [2026-27 locator page](https://www.fultonschools.org/all-departments/operations/operational-planning/mapping/find-your-school-25-26) embeds ArcGIS application c628e2b57b324c92a6891b3e51fb7a9d.
- Live public application configuration points to webmap 7169e82e2c004054a7f87d61cc199470, titled FIND MY SCHOOL MAP FY2627.
- Its attendance [FeatureServer layer 22](https://www4.fultonschools.org/arcgisserver/rest/services/AttendanceZones/CombinedAttendanceZones/FeatureServer/22) is named Attendance Zones FY2627.
- Live query: name_1633352979610 LIKE '%Johns Creek%' AND zonetype='High School Attendance Zone'; output EPSG:4326 GeoJSON.
- Response: one Polygon for Johns Creek High School, facilityid 741, with nonempty coordinates.
- Some application text still says 2025-26, despite the page and active layer saying 2026-27. Record layer metadata, effective school year, retrieval time, and a content hash; do not infer validity solely from page URLs.

These checks establish public technical access to geometry, not address-level assignment correctness, topology validation, historical boundary availability, or unrestricted redistribution rights. Public map metadata did not supply a clear redistribution license. Preserve attribution and review source terms before publishing boundary datasets. Official locator disclaimers also distinguish geographic zones from enrollment exceptions.

For production, compare interior and near-boundary addresses with official school locators. Store unresolved assignments explicitly. Store the zone version used for each result so a boundary update does not silently rewrite the historical cohort.

## Listing and transaction sources

| Source | Useful capability | Limits for this project |
| --- | --- | --- |
| Zillow website | Consumer view and manual spot checks | [Terms](https://www.zillow.com/corporate/terms-of-use/) restrict automated scraping; not a dependable authorized collection foundation |
| Zillow Research | Free regional historical aggregates | Weekly/monthly series and predefined geographies; not arbitrary school-zone daily listing snapshots. [Downloads](https://www.zillow.com/research/market-data/) |
| Realtor.com Research | Downloadable monthly ZIP inventory history | Useful contextual history, not school-zone data or arbitrary bedroom/year-built filters. Attribute the source. [Data library](https://www.realtor.com/research/data/) |
| RentCast listing API | Candidate for observed asking-price/inventory tracking | Regional completeness still untested; no fine-grained pending/sold/withdrawn listing status |
| FMLS via Bridge | Licensed regional MLS feed | Requires approval and applicable rights; not a free individual-access route currently established |
| ATTOM | Sale records and school boundary products | Pricing/access and archival rights require product-specific confirmation; not established as a zero-cost option |

### RentCast: documented capability, no live listing test yet

[Listing documentation](https://developers.rentcast.io/reference/property-listings) supplies coordinates, home attributes, year built, asking price, listing dates, source identifiers, and listing episodes. The provider states daily record updates and typical new-listing ingestion within 12-24 hours; this is not a guarantee that all local listings are complete or current. Its coverage target is a vendor statement, not a measured result for these schools.

The [sale search endpoint](https://developers.rentcast.io/reference/sale-listings) supports ZIP/city or circular searches, pagination of up to 500 records per response, and X-Total-Count when requested. School polygon search is not documented. Query a geographic superset, retrieve every page, then filter by the verified boundary. Pagination is ordered by lastSeenDate and is not documented as a transactionally frozen snapshot; check duplicates/count drift and retry inconsistencies.

The [status schema](https://developers.rentcast.io/reference/property-listings-schema) only exposes Active/Inactive. Inactive is not equivalent to sold. The history structure describes listing episodes and does not establish a complete daily price-change log. Persist our observations prospectively.

[Property records](https://developers.rentcast.io/reference/property-records) provide sale history and sale-date filtering separately. [Coverage documentation](https://developers.rentcast.io/reference/property-data) explains that recorded sales can lag by weeks to months. This can supplement longer-term transaction analysis, but cannot substitute for immediate listing status.

The [API license](https://www.rentcast.io/terms-api), sections 1 and 7, permits internal storage/analytics and qualified continued use of previously obtained data after termination, subject to surviving restrictions and third-party terms. Store operational responses privately; publishing bulk responses to the public code repository is not part of the proposed workflow.

### MLS and alternative licensing

[FMLS documentation](https://www.fmls.com/marketplace-info) identifies Bridge as its API platform and lists vendor approval, a $250 vendor application fee, and recurring data fees. With no current broker partner, this is a later option. Access to an IDX display feed should not be assumed to grant unrestricted historical retention or analytics rights. Georgia MLS eligibility and coverage were not resolved in this investigation.

[ATTOM documentation](https://api.developer.attomdata.com/docs) describes sales and school services. Its [bulk page](https://api.developer.attomdata.com/bulk) references a 24-hour API caching limit when discussing bulk alternatives. Do not select it for indefinite archival storage without confirming the relevant current contract.

## Can this run at zero recurring cost?

Infrastructure has plausible free options; complete daily listing acquisition is the unresolved constraint.

| Component | Candidate | Free-tier condition |
| --- | --- | --- |
| Scheduled collection | GitHub Actions standard Linux runner | Public repository execution is free; scheduling is best-effort |
| Dashboard | Streamlit Community Cloud | Free hosting; idle apps sleep, which must not stop collection |
| Database | Supabase Free PostgreSQL | 500 MB DB, finite bandwidth; track growth |
| Raw response archive | Private Supabase Storage bucket | 1 GB included; compress, deduplicate, monitor retention capacity |
| Independent backup | Local export/download | Additional copy must actually be made and restore-tested |
| Listings | RentCast Developer | 50 free successful API requests per billing period; complete regional scans may need multiple requests |

Sources: [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [Streamlit hosting](https://docs.streamlit.io/deploy/streamlit-community-cloud), [Supabase pricing](https://supabase.com/pricing).

Supabase Free does not include automatic backups and may pause after one week of inactivity. Raw files and DB in the same project are not an independent disaster-recovery copy. Free-tier storage is finite; avoid predicting unlimited historical retention without measured record sizes and growth.

[GitHub schedule rules](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule): the workflow must exist on the default branch. It can explicitly check out the feature branch's code, but a workflow present only on the feature branch will not run on a schedule. Runs may be delayed or dropped; public repository schedules can be disabled after 60 days of inactivity. No default-branch change was made.

[Streamlit sleep behavior](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app): apps without traffic for 12 hours sleep. Treat the UI as a reader of external persistent data.

### Free API request budget

[RentCast billing](https://developers.rentcast.io/reference/billing-and-pricing) includes 50 free calls, charges overages, and offers no provider-side hard usage cap. A zero-cost implementation must count/reserve requests before dispatch, include retries and ambiguous timeouts, reconcile the account billing period and other key usage, and stop conservatively before the allowance is exhausted. No key or subscription was activated here.

Planning arithmetic, not measured local inventory:

| Complete scan cost | Daily over 31 days | Interpretation |
| --- | --- | --- |
| 1 request across both zones | 31 calls | Potentially free, with a small validation reserve |
| 1 request per zone | 62 calls | Exceeds free allowance before retries or transaction lookups |
| 2 requests per zone | 124 calls | Not free at daily frequency |

One circular search covering both zones could reduce calls only if the entire relevant search result fits the request budget. Unrelated homes inside that circle also consume pages. Truncating at 500 is not a valid solution.

If daily coverage exceeds the budget, two complete scans per week might fit (nine scans x four pages = 36 calls, before additional checks). The product must then say twice-weekly observations, not daily market tracking. Re-reading yesterday's database or carrying values forward does not create a new observation. Decide the cadence after measuring page counts.

Fully free public aggregate series can show surrounding ZIP trends immediately, but must be labeled as context and kept distinct from the two school's observed inventories.

An alternative single VM with SQLite and an OS scheduler is technically suitable but has hosting or always-on local-machine costs. Render is a possible paid future option; its [cron jobs](https://render.com/docs/cronjobs) have a minimum monthly charge and cannot access persistent disks. It cannot simply share a SQLite disk with a separate web service.

## What truthful historical tracking requires

The following are proposed design requirements, not implemented features:

1. Collect the broad agreed residential universe around both zones; apply user bedroom, price, age, and size filters at query time. Narrow API collection permanently limits future retrospective filters. If budget forces a narrower universe, version and display that limit.
2. Separate properties from listing episodes and provider identifiers. Re-listing and dual MLS listings must not double-count one home. Preserve reconciliation evidence.
3. Retain immutable observations and source responses or content-addressed versions with per-run observation links. Record observation time separately from provider effective/update time.
4. Publish only validated complete runs. Store failed/partial attempts without replacing the last complete snapshot. A completed provider scan still does not prove full market coverage.
5. Record membership in a selected filter on each observation date. Separate homes entering a price filter from genuinely new listings, and leaving a filter from delisting.
6. Missing in one query means unobserved, not sold. Use explicit provider status or follow-up verification; mark uncertainty.
7. Maintain boundary versions, query definitions, normalization versions, and run manifests. A replay should reproduce the published metrics.
8. Keep raw archive, analytical database, and independent backups logically separate. Use transactional database export/backup and a restore check.
9. Flag small samples, missing yearBuilt/coordinates, stale provider timestamps, and collection gaps in the UI. Do not silently fill gaps with zero or report zero median for an empty cohort.
10. Use deterministic code for numbers and geographic assignment; an LLM is not required.

Potential core entities: properties, listing_episodes, observations, collection_runs, raw_objects, school_zone_versions, property_zone_assignments, and versioned aggregate outputs. PostgreSQL is a deployment convenience, not a requirement imposed by having only two schools. SQLite remains suitable for a single persistent host ([official guidance](https://www.sqlite.org/whentouse.html)).

Separate three metrics:
- Asking-price distribution of the observed active inventory: affected by composition.
- Price changes for the same matched listing episodes: closer to seller repricing behavior, still not a home-value index.
- Recorded sale prices: transaction data, with reporting lag and small local samples; typically evaluate monthly or rolling multiweek windows.

Year-built changes mostly describe the composition of available homes. Missing values need a separate category. Do not label an asking-price median or an AVM estimate as completed-sale price.

Historical exports imported later must be labeled provider-reconstructed; they are not equivalent to contemporaneous observations. Backup recovers what was saved, not a market state never observed.

## Evidence status and next validation gates

Verified:
- Remote jobAgent architecture and lack of checked-in hosting/scheduler.
- Both public school boundary endpoints returned geometry without API credentials.
- Fulton active layer identifies FY2627.
- Documented RentCast features, status limits, pagination, licensing, and free quota.
- Free hosting/storage candidates and their principal limits.

Still unverified:
- Current school-year applicability of Gwinnett geometry, precise boundary/address accuracy, and boundary publication rights.
- Live RentCast inventory, page counts, coordinate/yearBuilt completeness, and update lag in both zones.
- Whether one combined geographic query can support complete daily collection inside 50 calls.
- Coverage against a dated manual reference set; Zillow counts alone are not ground truth.
- Sale-history coverage, transaction lag, and price quality for the two counties.
- Account activation requirements, actual deployment compatibility, backup capacity, and measured storage growth.

Recommended next experiment, before implementation commitment:
1. Validate the two boundaries with sampled official address lookups.
2. With a user-provisioned free API key stored as a secret, make a small explicitly budgeted coverage probe, using total-count headers.
3. Compare 10-20 dated sample homes per zone across a reference source; include new listings, boundary addresses, and disappeared homes. Measure discrepancies rather than promise completeness.
4. Determine requests per complete scan and select daily versus twice-weekly cadence within a conservative 50-call ceiling.
5. Run a short observation pilot; then finalize schema, dashboard filters, and deployment.
6. Demonstrate failure handling and restoration before calling it reliable tracking.

No paid service, live listing collector, main-branch schedule, or production dashboard is active as a result of this research.
