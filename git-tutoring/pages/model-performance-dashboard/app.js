const models = {
  xgboost: { label: "XGBoost", auc: 0.891, lift: 0.18, sharpness: 1.0 },
  randomForest: { label: "Random Forest", auc: 0.867, lift: 0.13, sharpness: 0.88 },
  logistic: { label: "Logistic Regression", auc: 0.821, lift: 0.06, sharpness: 0.72 }
};

const segments = ["enterprise", "midmarket", "smallBusiness"];
const regions = [
  { name: "West", lat: 37.4, lon: -122.1 },
  { name: "South", lat: 33.7, lon: -84.4 },
  { name: "Midwest", lat: 41.9, lon: -87.6 },
  { name: "Northeast", lat: 40.7, lon: -74.0 },
  { name: "Remote", lat: 39.5, lon: -98.3 }
];

function seededNoise(index) {
  const value = Math.sin(index * 12.9898) * 43758.5453;
  return value - Math.floor(value);
}

function buildCustomers() {
  const rows = [];
  for (let i = 0; i < 2400; i += 1) {
    const segment = segments[i % segments.length];
    const region = regions[i % regions.length].name;
    const tenure = seededNoise(i + 5);
    const usage = seededNoise(i + 17);
    const support = seededNoise(i + 29);
    const segmentRisk = segment === "enterprise" ? -0.08 : segment === "midmarket" ? 0.02 : 0.12;
    const regionRisk = region === "South" ? -0.03 : region === "Remote" ? 0.08 : 0.01;
    const baseRisk = 0.18 + segmentRisk + regionRisk + (1 - usage) * 0.34 + support * 0.22 + (1 - tenure) * 0.18;
    const actual = seededNoise(i + 41) < Math.max(0.04, Math.min(0.92, baseRisk));
    rows.push({
      id: `C-${String(i + 1000).padStart(5, "0")}`,
      segment,
      region,
      actual,
      scores: {
        xgboost: scoreForModel(baseRisk, actual, models.xgboost, i),
        randomForest: scoreForModel(baseRisk, actual, models.randomForest, i + 7),
        logistic: scoreForModel(baseRisk, actual, models.logistic, i + 13)
      }
    });
  }
  return rows;
}

function scoreForModel(baseRisk, actual, model, index) {
  const signal = actual ? model.lift : -model.lift;
  const noise = (seededNoise(index + 101) - 0.5) * (0.32 - model.sharpness * 0.12);
  return clamp(baseRisk + signal + noise, 0.01, 0.99);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function formatRate(value) {
  return Number.isFinite(value) ? value.toFixed(2) : "0.00";
}

function formatCount(value) {
  return value.toLocaleString("en-US");
}

function getFilteredRows() {
  const segment = document.getElementById("segmentSelect").value;
  if (segment === "all") {
    return customers;
  }
  return customers.filter(row => row.segment === segment);
}

function confusion(rows, modelKey, threshold) {
  let tp = 0;
  let tn = 0;
  let fp = 0;
  let fn = 0;
  for (const row of rows) {
    const predicted = row.scores[modelKey] >= threshold;
    if (row.actual && predicted) tp += 1;
    if (!row.actual && !predicted) tn += 1;
    if (!row.actual && predicted) fp += 1;
    if (row.actual && !predicted) fn += 1;
  }
  return { tp, tn, fp, fn };
}

function metricsFromConfusion(c) {
  const precision = c.tp / Math.max(1, c.tp + c.fp);
  const recall = c.tp / Math.max(1, c.tp + c.fn);
  const f1 = (2 * precision * recall) / Math.max(0.0001, precision + recall);
  return { precision, recall, f1 };
}

function thresholdSeries(rows, modelKey) {
  const thresholds = [];
  const precision = [];
  const recall = [];
  const fpr = [];
  const tpr = [];
  for (let t = 0.01; t <= 0.99; t += 0.02) {
    const c = confusion(rows, modelKey, t);
    const m = metricsFromConfusion(c);
    thresholds.push(Number(t.toFixed(2)));
    precision.push(m.precision);
    recall.push(m.recall);
    tpr.push(c.tp / Math.max(1, c.tp + c.fn));
    fpr.push(c.fp / Math.max(1, c.fp + c.tn));
  }
  return { thresholds, precision, recall, fpr, tpr };
}

function updateMetrics(c, modelKey) {
  const m = metricsFromConfusion(c);
  document.getElementById("aucMetric").textContent = models[modelKey].auc.toFixed(3);
  document.getElementById("precisionMetric").textContent = formatRate(m.precision);
  document.getElementById("recallMetric").textContent = formatRate(m.recall);
  document.getElementById("f1Metric").textContent = formatRate(m.f1);
  document.getElementById("tnCell").textContent = formatCount(c.tn);
  document.getElementById("fpCell").textContent = formatCount(c.fp);
  document.getElementById("fnCell").textContent = formatCount(c.fn);
  document.getElementById("tpCell").textContent = formatCount(c.tp);
}

function updateRoc(rows, modelKey) {
  const series = thresholdSeries(rows, modelKey);
  Plotly.react("rocChart", [
    {
      x: series.fpr,
      y: series.tpr,
      mode: "lines",
      line: { color: "#2563eb", width: 3 },
      name: models[modelKey].label
    },
    {
      x: [0, 1],
      y: [0, 1],
      mode: "lines",
      line: { color: "#94a3b8", width: 1, dash: "dash" },
      name: "Random baseline"
    }
  ], chartLayout("False positive rate", "True positive rate"), { displayModeBar: false, responsive: true });
}

function updateThresholdChart(rows, modelKey, threshold) {
  const series = thresholdSeries(rows, modelKey);
  Plotly.react("thresholdChart", [
    {
      x: series.thresholds,
      y: series.precision,
      mode: "lines",
      line: { color: "#0f9f6e", width: 3 },
      name: "Precision"
    },
    {
      x: series.thresholds,
      y: series.recall,
      mode: "lines",
      line: { color: "#dc2626", width: 3 },
      name: "Recall"
    }
  ], {
    ...chartLayout("Threshold", "Metric value"),
    shapes: [{
      type: "line",
      x0: threshold,
      x1: threshold,
      y0: 0,
      y1: 1,
      line: { color: "#7c3aed", width: 2, dash: "dot" }
    }]
  }, { displayModeBar: false, responsive: true });
}

function updateRegionChart(rows, modelKey) {
  const regionRows = regions.map(region => {
    const selected = rows.filter(row => row.region === region.name);
    const avgRisk = selected.reduce((sum, row) => sum + row.scores[modelKey], 0) / Math.max(1, selected.length);
    return { ...region, avgRisk, count: selected.length };
  });

  Plotly.react("regionChart", [{
    type: "scattergeo",
    mode: "markers+text",
    lat: regionRows.map(row => row.lat),
    lon: regionRows.map(row => row.lon),
    text: regionRows.map(row => row.name),
    textposition: "bottom center",
    marker: {
      size: regionRows.map(row => 18 + row.avgRisk * 54),
      color: regionRows.map(row => row.avgRisk),
      colorscale: [[0, "#0f9f6e"], [0.5, "#d97706"], [1, "#dc2626"]],
      cmin: 0,
      cmax: 1,
      line: { color: "#ffffff", width: 1 }
    },
    hovertemplate: "%{text}<br>Average risk: %{marker.color:.2f}<extra></extra>"
  }], {
    margin: { t: 10, r: 4, b: 4, l: 4 },
    geo: {
      scope: "usa",
      projection: { type: "albers usa" },
      showland: true,
      landcolor: "#eef2f7",
      subunitcolor: "#cbd5e1",
      countrycolor: "#cbd5e1"
    }
  }, { displayModeBar: false, responsive: true });
}

function updateTable(rows, modelKey) {
  const tbody = document.getElementById("riskTable");
  const topRows = [...rows]
    .sort((a, b) => b.scores[modelKey] - a.scores[modelKey])
    .slice(0, 10);
  tbody.innerHTML = topRows.map(row => `
    <tr>
      <td>${row.id}</td>
      <td>${labelSegment(row.segment)}</td>
      <td>${row.region}</td>
      <td>${row.scores[modelKey].toFixed(3)}</td>
      <td>${row.actual ? "Yes" : "No"}</td>
    </tr>
  `).join("");
}

function labelSegment(value) {
  if (value === "smallBusiness") return "Small business";
  if (value === "midmarket") return "Mid-market";
  return "Enterprise";
}

function chartLayout(xTitle, yTitle) {
  return {
    margin: { t: 10, r: 16, b: 44, l: 52 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    xaxis: { title: xTitle, range: [0, 1], gridcolor: "#e2e8f0", zeroline: false },
    yaxis: { title: yTitle, range: [0, 1], gridcolor: "#e2e8f0", zeroline: false },
    legend: { orientation: "h", x: 0, y: 1.14 }
  };
}

function render() {
  const modelKey = document.getElementById("modelSelect").value;
  const threshold = Number(document.getElementById("thresholdSlider").value);
  const rows = getFilteredRows();
  const c = confusion(rows, modelKey, threshold);
  document.getElementById("thresholdValue").textContent = threshold.toFixed(2);
  updateMetrics(c, modelKey);
  updateRoc(rows, modelKey);
  updateThresholdChart(rows, modelKey, threshold);
  updateRegionChart(rows, modelKey);
  updateTable(rows, modelKey);
}

const customers = buildCustomers();

document.getElementById("modelSelect").addEventListener("change", render);
document.getElementById("segmentSelect").addEventListener("change", render);
document.getElementById("thresholdSlider").addEventListener("input", render);

render();
