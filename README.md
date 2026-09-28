# CMP Performance Benchmark

A reproducible Lighthouse benchmark for measuring the performance impact of Consent Management Platforms (CMPs).

This repository contains the test page, measurement tools and Docker environment used for [Lawwwing's CMP performance benchmark](https://docs.lawwwing.com). It is published to make our methodology transparent and allow others to reproduce the tests.


## How it works

The benchmark compares a baseline page without a CMP against versions of the same page with different CMP integrations.

Every variant uses the same static HTML, CSS, image and measurement script. The only difference is the CMP integration snippet. Tests measure a first visit, before any consent preferences have been stored.

We use Lighthouse to collect:

- Performance score
- Largest Contentful Paint (LCP)
- First Contentful Paint (FCP)
- Total Blocking Time (TBT)
- Cumulative Layout Shift (CLS)
- Speed Index

Results are reported as the median of multiple runs. Differences are calculated against the baseline page measured in the same environment.

## Requirements

- Docker and Docker Compose
- Your own CMP integration snippets for the providers you want to test

The Docker environment includes Python, Node.js, Chromium and Lighthouse. You do not need to install these tools on your host machine.

## Getting started

### 1. Clone the repository

```bash
git clone https://github.com/lawwwing/cmp-performance-benchmark.git
cd cmp-performance-benchmark
```

### 2. Add your CMP snippets

Third-party CMP integration snippets are not included in this repository due to licensing and configuration restrictions. To reproduce the benchmark, you must provide your own snippets for the platforms you want to test.

1. Add each provider's integration snippet to the `snippets/` directory. You can use `snippets/competitor.html.example` as a starting point.
2. Open `benchmark.config.json` and add an entry for each provider under `variants`. Keep the existing `baseline` entry unchanged.

For example:

```json
{
  "host": "127.0.0.1",
  "port": 4173,
  "lighthouseHost": null,
  "variants": [
    {
      "id": "baseline",
      "label": "Baseline (no CMP)",
      "snippet": null
    },
    {
      "id": "provider-a",
      "label": "Provider A",
      "snippet": "snippets/provider-a.html",
      "host": "samplesite.com"
    },
    {
      "id": "provider-b",
      "label": "Provider B",
      "snippet": "snippets/provider-b.html"
    }
  ]
}
```

Each snippet is inserted into the same test page without modification. Use the provider's documented integration and include any required consent configuration.

Make sure the snippet filenames match the paths in `benchmark.config.json`. If a CMP only works on registered domains, see [Domain-restricted CMPs](#domain-restricted-cmps).


Keep the baseline variant without a snippet.

### 3. Start the benchmark server

```bash
docker compose up --build -d
```

The test pages are served at `http://127.0.0.1:4173`.

You can open `/baseline/` to view the page without a CMP or `/<variant-id>/` to inspect a configured variant.

### 4. Run Lighthouse

To run the benchmark using the Docker environment:

```bash
docker compose --profile lighthouse run --rm lighthouse
```

The default Compose command runs 10 mobile measurements per variant.

To run desktop measurements:

```bash
docker compose --profile lighthouse run --rm lighthouse \
  python3 scripts/lighthouse.py --runs 10 --desktop --no-sandbox
```

You can change the number of measurements using `--runs`.

## Results

Each benchmark execution creates a timestamped directory under `reports/` containing:

- `summary.csv` — individual measurement results.
- `summary.json` — configuration details, individual results and median values.
- Lighthouse JSON and HTML reports for each measurement.

The `reports/` directory is excluded from version control.

## Test methodology

The benchmark is designed to keep the test page and execution environment consistent across variants.

- Every variant shares the same page, with only its CMP snippet changed.
- Snippets are inserted without modification.
- The page server disables caching.
- Before measuring, the runner verifies that every variant matches the shared page template and its configured snippet.
- Lighthouse runs the performance category using the same Chromium build.
- Mobile tests use Lighthouse's default configuration; desktop tests use its desktop preset.
- Failed measurements are retained in the output but excluded from median calculations.

The benchmark measures the impact of each integration on this particular test page. Results may differ on other websites or when using different hardware, browser versions or CMP configurations.

## Domain-restricted CMPs

Some CMPs only load on domains registered in their dashboards.

If a provider does not support `127.0.0.1`, you can configure `lighthouseHost` or a variant-specific `host` in `benchmark.config.json`.

The Lighthouse runner maps that hostname to the local benchmark server inside Chromium. The CMP's external resources continue to use normal DNS resolution.


## Limitations

This is a controlled laboratory benchmark, not a measurement of real-user performance. It measures each CMP's configured integration on a shared test page during a first visit.

To reproduce the comparison, you must supply your own integration snippets and configure the corresponding CMP accounts. Results may vary depending on those configurations and the conditions under which the tests are run.


## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

The license applies to the original benchmark code and documentation
included in this repository. Third-party CMP integration snippets are
not included and remain subject to their respective providers' terms.
