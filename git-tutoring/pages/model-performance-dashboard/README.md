# GitHub Pages Demo: Model Performance Dashboard

This folder contains a static interactive dashboard that can run on GitHub Pages without a Python server.

## What It Demonstrates

- Dropdown controls for model and customer segment
- A threshold slider that updates precision, recall, F1, and confusion matrix counts
- Plotly charts rendered in the browser
- A regional bubble chart using toy customer risk data
- A simple ranked table of high-risk customers

## Files

```text
index.html   Page structure
styles.css   Visual design
app.js       Toy data generation, metric calculation, and Plotly rendering
README.md    Explanation and GitHub Pages instructions
```

## Run Locally

Because this demo is static, you can open `index.html` directly in a browser.

For a slightly more realistic local server:

```bash
cd git-tutoring/pages/model-performance-dashboard
python -m http.server 8000
```

Then open:

```text
http://localhost:8000
```

## Publish with GitHub Pages

GitHub Pages serves static files from a branch and folder. For this branch demo, use:

```text
Branch: git_tutoring
Folder: /root
```

Then the demo should be available at a URL like:

```text
https://ladavid9989.github.io/data_science/git-tutoring/pages/model-performance-dashboard/
```

The exact URL depends on the repository owner, repository name, and Pages settings.

## Important Limitation

GitHub Pages does not run Python, Streamlit, Flask, or FastAPI by itself. It hosts static files. That is why this demo uses JavaScript and Plotly in the browser.

For Python dashboards, use Streamlit Community Cloud, Hugging Face Spaces, Render, Railway, or another server-capable hosting platform.

## Learning Exercise

1. Change the default threshold in `index.html` from `0.65` to another value.
2. Commit and push the change.
3. Refresh the GitHub Pages dashboard.
4. Change a chart title in `app.js`.
5. Commit and push again.
6. Compare the GitHub commit history.

## Extension Ideas

- Add another model option
- Add a calibration chart
- Replace generated toy data with a CSV file
- Add a cost-sensitive threshold calculator
- Add a downloadable model evaluation summary
