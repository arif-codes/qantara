const state = {
  data: null,
  selectedNodeId: "source_arabic",
  liveApi: false
};

const arabicPattern = /[\u0600-\u06ff]/u;

function isArabicText(value = "") {
  return arabicPattern.test(value);
}

function scriptAttrs(value = "") {
  return isArabicText(value) ? ' lang="ar" dir="rtl"' : "";
}

function applyScriptAttrs(element, value = "") {
  if (isArabicText(value)) {
    element.lang = "ar";
    element.dir = "rtl";
    return;
  }

  element.removeAttribute("lang");
  element.removeAttribute("dir");
}

const kindLabels = {
  ancestor: "ancestor",
  bridge: "bridge",
  source: "Arabic source",
  target: "target language",
  focus: "query result"
};

function firstSelectableNode(data) {
  return data.nodes.find((node) => node.kind === "source") ?? data.nodes[0] ?? null;
}

async function fetchGraph(query) {
  if (window.location.protocol === "file:") {
    return null;
  }

  const url = new URL("/api/graph", window.location.origin);
  url.searchParams.set("q", query);
  url.searchParams.set("language", "English");

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Graph request failed with ${response.status}`);
  }
  return response.json();
}

async function loadData(query = "sugar") {
  const trimmed = query.trim() || "sugar";

  try {
    const apiData = await fetchGraph(trimmed);
    state.data = apiData ?? window.LANGUAGEGRAPH_SUGAR;
    state.liveApi = Boolean(apiData);
  } catch (error) {
    console.warn(error);
    state.data = window.LANGUAGEGRAPH_SUGAR;
    state.liveApi = false;
  }

  const selected = firstSelectableNode(state.data);
  state.selectedNodeId = selected ? selected.id : null;
  render();
}

function render() {
  renderSummary();
  renderEdges();
  renderNodes();
  renderTimeline();
  renderInspector();
  renderSignals();
  renderEdgeTable();
  renderSuggestions();
  document.body.classList.remove("is-loading");
  alignGraphScroll();
}

function isPhoneGraph() {
  return window.matchMedia("(max-width: 720px)").matches;
}

function graphLayout() {
  const { nodes, edges } = state.data;
  const basePositions = Object.fromEntries(
    nodes.map((node) => [node.id, { x: node.x, y: node.y }])
  );

  if (!isPhoneGraph()) {
    return basePositions;
  }

  const storyPath = storyPathIds(nodes, edges);
  if (storyPath.length < 2) {
    return basePositions;
  }

  const storySet = new Set(storyPath);
  const positions = { ...basePositions };
  const routeColumns = phoneRouteColumns(storyPath.length);

  storyPath.forEach((id, index) => {
    positions[id] = { x: routeColumns[index] ?? 28, y: 50 };
  });

  const extras = nodes
    .filter((node) => !storySet.has(node.id))
    .sort((left, right) => left.y - right.y || basePositions[left.id].x - basePositions[right.id].x);
  const extraColumns = routeColumns.slice(1, -1).length ? routeColumns.slice(1, -1) : [52];

  extras.forEach((node, index) => {
    const column = extraColumns[Math.min(index, extraColumns.length - 1)];
    positions[node.id] = {
      x: column,
      y: node.y < 50 ? 22 : 78
    };
  });

  return positions;
}

function storyPathIds(nodes, edges) {
  const storyEdges = edges.filter((edge) => edge.kind === "story");
  if (storyEdges.length === 0) {
    const source = nodes.find((node) => node.kind === "source");
    const focus = nodes.find((node) => node.kind === "focus") ?? nodes.find((node) => node.kind === "target");
    return [source?.id, focus?.id].filter(Boolean);
  }

  const incoming = new Set(storyEdges.map((edge) => edge.to));
  const outgoing = Object.fromEntries(storyEdges.map((edge) => [edge.from, edge.to]));
  let current = storyEdges.find((edge) => !incoming.has(edge.from))?.from ?? storyEdges[0].from;
  const ordered = [];

  while (current && !ordered.includes(current)) {
    ordered.push(current);
    current = outgoing[current];
  }

  return ordered;
}

function phoneRouteColumns(count) {
  if (count <= 2) {
    return [18, 72];
  }
  if (count === 3) {
    return [18, 46, 74];
  }
  if (count === 4) {
    return [12, 36, 60, 86];
  }

  const start = 12;
  const end = 88;
  const step = (end - start) / Math.max(count - 1, 1);
  return Array.from({ length: count }, (_, index) => start + step * index);
}

function alignGraphScroll() {
  const canvas = document.querySelector(".graph-canvas");
  if (!canvas) {
    return;
  }

  window.requestAnimationFrame(() => {
    if (canvas.scrollWidth > canvas.clientWidth) {
      canvas.scrollLeft = 0;
    }
  });
}

function renderSummary() {
  const { summary } = state.data;
  const source = state.data.source;
  const sourceNode = state.data.nodes.find((node) => node.kind === "source");
  const sourceText = sourceNode?.roman || source?.term;
  const sourceLabel = source && sourceText ? `${source.lang} source: ${sourceText}` : summary.ipa;
  const confidence = Math.round(summary.confidence * 100);
  const focusTerm = document.getElementById("focus-term");
  focusTerm.textContent = summary.display;
  applyScriptAttrs(focusTerm, summary.display);
  document.getElementById("focus-meta").textContent = sourceLabel;
  document.getElementById("confidence-score").textContent = `${confidence}%`;
  document.querySelector(".score-pill")?.style.setProperty("--score-width", `${confidence}%`);
  document.getElementById("score-label").textContent = summary.confidence.toFixed(2);
}

function renderEdges() {
  const edgeLayer = document.getElementById("edge-layer");
  const { nodes, edges } = state.data;
  const byId = Object.fromEntries(nodes.map((node) => [node.id, node]));
  const layout = graphLayout();

  edgeLayer.innerHTML = "";

  for (const edge of edges) {
    const source = byId[edge.from];
    const target = byId[edge.to];
    const sourcePosition = layout[edge.from];
    const targetPosition = layout[edge.to];
    if (!source || !target || !sourcePosition || !targetPosition) {
      continue;
    }

    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    const midX = (sourcePosition.x + targetPosition.x) / 2;
    const bend = sourcePosition.y === targetPosition.y ? 0 : sourcePosition.y < targetPosition.y ? -6 : 6;
    path.setAttribute(
      "d",
      `M ${sourcePosition.x} ${sourcePosition.y} C ${midX} ${sourcePosition.y + bend}, ${midX} ${targetPosition.y - bend}, ${targetPosition.x} ${targetPosition.y}`
    );
    const edgeClasses = ["edge-line"];
    if (edge.kind === "story") {
      edgeClasses.push("story-edge");
    } else if (source.kind === "source") {
      edgeClasses.push("source-edge");
    }
    path.setAttribute("class", edgeClasses.join(" "));
    edgeLayer.appendChild(path);
  }
}

function renderNodes() {
  const nodeLayer = document.getElementById("node-layer");
  const layout = graphLayout();
  nodeLayer.innerHTML = "";

  if (state.data.nodes.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No Arabic-source path found in the local graph.";
    nodeLayer.appendChild(empty);
    return;
  }

  for (const node of state.data.nodes) {
    const position = layout[node.id] ?? { x: node.x, y: node.y };
    const button = document.createElement("button");
    button.className = `graph-node ${node.id === state.selectedNodeId ? "is-selected" : ""}`;
    button.dataset.kind = node.kind;
    button.style.left = `${position.x}%`;
    button.style.top = `${position.y}%`;
    button.type = "button";
    button.innerHTML = `
      <span class="graph-node__term"${scriptAttrs(node.term)}>${node.term}</span>
      <span class="graph-node__language">${node.language}</span>
      <span class="graph-node__roman">${node.roman}</span>
    `;
    button.addEventListener("click", () => {
      state.selectedNodeId = node.id;
      renderNodes();
      renderInspector();
    });
    nodeLayer.appendChild(button);
  }
}

function renderTimeline() {
  const timeline = document.getElementById("timeline");
  timeline.innerHTML = "";

  if (state.data.nodes.length === 0) {
    const item = document.createElement("div");
    item.innerHTML = `
      <span>Result</span>
      <strong>No Arabic path</strong>
    `;
    timeline.appendChild(item);
    return;
  }

  const ordered = [...state.data.nodes].sort((left, right) => left.x - right.x);
  for (const node of ordered) {
    const item = document.createElement("div");
    if (node.kind === "source") {
      item.className = "timeline__source";
    }
    item.innerHTML = `
      <span>${node.language}</span>
      <strong${scriptAttrs(node.term)}>${node.term}</strong>
    `;
    timeline.appendChild(item);
  }
}

function renderInspector() {
  const selected = state.data.nodes.find((node) => node.id === state.selectedNodeId);
  if (!selected) {
    const selectedTerm = document.getElementById("selected-term");
    selectedTerm.textContent = "No match";
    applyScriptAttrs(selectedTerm, "No match");
    document.getElementById("selected-language").textContent = "n/a";
    document.getElementById("selected-roman").textContent = "n/a";
    document.getElementById("selected-role").textContent = state.liveApi ? "live SQLite" : "mock data";
    return;
  }

  const selectedTerm = document.getElementById("selected-term");
  selectedTerm.textContent = selected.term;
  applyScriptAttrs(selectedTerm, selected.term);
  document.getElementById("selected-language").textContent = selected.language;
  document.getElementById("selected-roman").textContent = selected.roman;
  document.getElementById("selected-role").textContent = kindLabels[selected.kind] ?? selected.kind;
}

function renderSignals() {
  const scoreBars = document.getElementById("score-bars");
  scoreBars.innerHTML = "";

  for (const signal of state.data.signals) {
    const row = document.createElement("div");
    row.className = "signal";
    row.title = signal.description ?? "";
    row.innerHTML = `
      <div class="signal__top">
        <span class="signal__label">${signal.label}</span>
        <span class="signal__value">${signal.value}</span>
      </div>
      <div class="signal__track">
        <div class="signal__bar" style="width: ${Math.round(signal.weight * 100)}%"></div>
      </div>
    `;
    scoreBars.appendChild(row);
  }
}

function renderEdgeTable() {
  const table = document.getElementById("edge-table");
  const byId = Object.fromEntries(state.data.nodes.map((node) => [node.id, node]));
  table.innerHTML = "";
  document.getElementById("edge-count").textContent = state.data.edges.length;

  for (const edge of state.data.edges) {
    const source = byId[edge.from];
    const target = byId[edge.to];
    if (!source || !target) {
      continue;
    }

    const row = document.createElement("div");
    row.className = "edge-row";
    row.title = `${edge.description ?? ""}\nEvidence: ${edge.evidence ?? "source graph row"}`.trim();
    const edgeKind = edge.kind === "story" ? "story path" : "direct fan-out";
    row.innerHTML = `
      <div class="edge-row__path">
        <strong><span${scriptAttrs(source.term)}>${source.term}</span> → <span${scriptAttrs(target.term)}>${target.term}</span></strong>
        <span>${edge.relation} · ${edgeKind} · ${source.language} to ${target.language}</span>
      </div>
      <span class="edge-row__score">${Math.round(edge.confidence * 100)}%</span>
    `;
    table.appendChild(row);
  }
}

function renderSuggestions() {
  const suggestions = document.getElementById("suggestions");
  suggestions.innerHTML = "";

  for (const suggestion of state.data.suggestions) {
    const term = typeof suggestion === "string" ? suggestion : suggestion.term;
    if (!term) {
      continue;
    }

    const button = document.createElement("button");
    button.type = "button";
    button.textContent = term;
    button.addEventListener("click", () => {
      document.getElementById("word-search").value = term;
      loadData(term);
    });
    suggestions.appendChild(button);
  }
}

document.getElementById("search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const input = form.elements.word;
  loadData(input.value);
});

loadData(document.getElementById("word-search").value);
