param(
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [string]$SeedHtml
)

# Bounded, first-page feasibility probe. No login, retries, challenge handling,
# proxy rotation, detail-page crawling, or scheduled execution.
$ErrorActionPreference = 'Stop'
$baseUrl = 'https://www.zillow.com/schools/102507/north-gwinnett-high-school/'
$utf8 = [Text.UTF8Encoding]::new($false)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path

function Read-SearchState([string]$Html) {
    if ($Html -match '(?i)px-captcha|Access to this page has been denied|verify you are human') {
        throw 'Challenge detected; probe stopped without attempting a bypass.'
    }
    $match = [regex]::Match($Html, '(?is)<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>')
    if (-not $match.Success) { throw 'Search data was not present in the returned HTML.' }
    $state = ($match.Groups[1].Value | ConvertFrom-Json).props.pageProps.searchPageState
    if (-not $state) { throw 'Search state schema was not recognized.' }
    return $state
}

if ($SeedHtml) {
    $seedBody = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $SeedHtml).Path)
} else {
    $seedReply = Invoke-WebRequest -UseBasicParsing -Uri $baseUrl -TimeoutSec 30
    $seedBody = $seedReply.Content
    [IO.File]::WriteAllText((Join-Path $OutputDirectory 'seed.html'), $seedBody, $utf8)
}
$seedState = Read-SearchState $seedBody
$query = $seedState.queryState
if ($query.schoolId -ne 102507) { throw 'Unexpected seed school.' }
$requested = @{
    price = @{ min = 400000; max = 700000 }
    beds = @{ min = 3 }
    baths = @{ min = 2 }
    isSingleFamily = @{ value = $true }
    isCondo = @{ value = $false }
    isApartmentOrCondo = @{ value = $false }
    isMultiFamily = @{ value = $false }
    isApartment = @{ value = $false }
    isManufactured = @{ value = $false }
    isLotLand = @{ value = $false }
    isTownhouse = @{ value = $false }
}
foreach ($key in $requested.Keys) {
    $query.filterState | Add-Member -NotePropertyName $key -NotePropertyValue $requested[$key] -Force
}
$url = $baseUrl + '?searchQueryState=' + [uri]::EscapeDataString(($query | ConvertTo-Json -Depth 12 -Compress))
$observedAt = [DateTimeOffset]::UtcNow.ToString('o')
$reply = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 30
[IO.File]::WriteAllText((Join-Path $OutputDirectory 'houses-first-page.html'), $reply.Content, $utf8)
$state = Read-SearchState $reply.Content
$filters = $state.queryState.filterState
$effective = $state.defaultFilterState
if (-not $effective) { $effective = $seedState.defaultFilterState }
foreach ($property in $filters.PSObject.Properties) {
    $effective | Add-Member -NotePropertyName $property.Name -NotePropertyValue $property.Value -Force
}
$filterErrors = @()
foreach ($key in $requested.Keys) {
    foreach ($part in $requested[$key].Keys) {
        if ($effective.$key.$part -ne $requested[$key][$part]) { $filterErrors += "$key.$part" }
    }
}
if ($state.queryState.schoolId -ne 102507) { $filterErrors += 'schoolId' }
$rows = @($state.cat1.searchResults.listResults | ForEach-Object {
    [pscustomobject]@{
        observed_at_utc = $observedAt
        zpid = $_.zpid
        address = $_.address
        price = $_.unformattedPrice
        bedrooms = $_.beds
        bathrooms = $_.baths
        square_feet = $_.area
        property_type = $_.hdpData.homeInfo.homeType
        year_built = $_.hdpData.homeInfo.yearBuilt
        status = $_.statusText
        latitude = $_.latLong.latitude
        longitude = $_.latLong.longitude
        url = $_.detailUrl
    }
})
$violations = @($rows | Where-Object {
    $_.price -lt 400000 -or $_.price -gt 700000 -or $_.bedrooms -lt 3 -or
    $_.bathrooms -lt 2 -or $_.property_type -ne 'SINGLE_FAMILY'
})
$summary = [pscustomobject]@{
    observed_at_utc = $observedAt
    requested_url = $url
    http_status = [int]$reply.StatusCode
    school = $state.schoolState.selectedSchool
    returned_query = $state.queryState
    total_results_reported = $state.cat1.searchList.totalResultCount
    total_pages_reported = $state.cat1.searchList.totalPages
    extracted_first_page = $rows.Count
    unique_zpids = @($rows.zpid | Sort-Object -Unique).Count
    filter_mismatches = $filterErrors
    row_violations = $violations.Count
    rows_with_year_built = @($rows | Where-Object { $null -ne $_.year_built }).Count
    complete_inventory_collected = $false
    official_attendance_zone_verified = $false
    sample = @($rows | Select-Object -First 3)
}
$rows | Export-Csv -LiteralPath (Join-Path $OutputDirectory 'houses-first-page.csv') -NoTypeInformation -Encoding UTF8
$summaryJson = $summary | ConvertTo-Json -Depth 12
[IO.File]::WriteAllText((Join-Path $OutputDirectory 'houses-summary.json'), $summaryJson, $utf8)
$summaryJson
if ($filterErrors.Count -gt 0 -or $violations.Count -gt 0) {
    throw 'Returned filters or rows failed validation; do not treat this as a successful filtered probe.'
}
