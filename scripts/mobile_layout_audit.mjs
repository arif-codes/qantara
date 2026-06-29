#!/usr/bin/env node

const PLAYWRIGHT_IMPORT =
  process.env.PLAYWRIGHT_IMPORT ??
  "file:///private/tmp/route-refresh-probe/node_modules/playwright/index.mjs";

const { chromium } = await import(PLAYWRIGHT_IMPORT);

const baseUrl = process.env.LANGUAGEGRAPH_URL ?? "http://127.0.0.1:8000/";
const screenshotDir = new URL("../reports/mobile/", import.meta.url);

const viewports = [
  { name: "iphone-se", width: 320, height: 568 },
  { name: "iphone-8", width: 375, height: 667 },
  { name: "iphone-13", width: 390, height: 844 },
  { name: "pixel-7", width: 412, height: 915 },
  { name: "iphone-pro-max", width: 430, height: 932 },
  { name: "ipad-mini", width: 768, height: 1024 },
];

const words = ["sugar", "arsenal", "almanac", "zero", "cipher", "tariff"];

async function ensureDir() {
  const { mkdir } = await import("node:fs/promises");
  await mkdir(screenshotDir, { recursive: true });
}

function overlapArea(a, b) {
  const x = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
  const y = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
  return x * y;
}

async function pageMetrics(page) {
  return page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    const docWidth = document.documentElement.scrollWidth;
    const graph = document.querySelector(".graph-canvas")?.getBoundingClientRect();
    const graphElement = document.querySelector(".graph-canvas");
    const track = document.querySelector(".graph-scroll-track")?.getBoundingClientRect();
    const nodes = [...document.querySelectorAll(".graph-node")].map((node) => {
      const rect = node.getBoundingClientRect();
      return {
        label: node.innerText.replace(/\s+/g, " ").trim(),
        selected: node.classList.contains("is-selected"),
        left: rect.left,
        right: rect.right,
        top: rect.top,
        bottom: rect.bottom,
        width: rect.width,
        height: rect.height,
      };
    });
    const inspector = document.querySelector(".inspector")?.getBoundingClientRect();
    const search = document.querySelector(".search")?.getBoundingClientRect();

    return {
      viewportWidth,
      docWidth,
      horizontalOverflow: docWidth - viewportWidth,
      graphScrollOverflow: graphElement
        ? graphElement.scrollWidth - graphElement.clientWidth
        : 0,
      graphScrollLeft: graphElement?.scrollLeft ?? 0,
      graph,
      track,
      nodes,
      inspector,
      search,
    };
  });
}

function analyse(metrics) {
  const issues = [];
  if (metrics.horizontalOverflow > 1) {
    issues.push(`document horizontal overflow ${metrics.horizontalOverflow}px`);
  }

  const bounds = metrics.track ?? metrics.graph;
  if (bounds) {
    for (const node of metrics.nodes) {
      if (node.left < bounds.left - 1 || node.right > bounds.right + 1) {
        issues.push(`graph node out of scroll track: ${node.label}`);
      }
    }
  }

  if (metrics.graph && metrics.graphScrollOverflow > 1) {
    const selected = metrics.nodes.find((node) => node.selected);
    if (selected && (selected.left < metrics.graph.left - 1 || selected.right > metrics.graph.right + 1)) {
      issues.push(`selected source not visible at initial scroll: ${selected.label}`);
    }
  }

  for (let i = 0; i < metrics.nodes.length; i += 1) {
    for (let j = i + 1; j < metrics.nodes.length; j += 1) {
      const area = overlapArea(metrics.nodes[i], metrics.nodes[j]);
      if (area > 24) {
        issues.push(
          `graph node overlap: ${metrics.nodes[i].label} / ${metrics.nodes[j].label} (${Math.round(area)}px²)`
        );
      }
    }
  }

  return issues;
}

await ensureDir();

const browser = await chromium.launch({ headless: true, channel: "chrome" });
const results = [];

try {
  for (const viewport of viewports) {
    const context = await browser.newContext({
      viewport: { width: viewport.width, height: viewport.height },
      isMobile: viewport.width < 768,
      hasTouch: viewport.width < 768,
      deviceScaleFactor: 2,
    });
    const page = await context.newPage();
    await page.goto(baseUrl, { waitUntil: "networkidle" });

    for (const word of words) {
      await page.locator("#word-search").fill(word);
      await page.locator("#search-form").evaluate((form) => form.requestSubmit());
      await page.waitForFunction(
        (expected) => document.querySelector("#focus-term")?.textContent?.trim() === expected,
        word
      );
      await page.waitForTimeout(150);

      const metrics = await pageMetrics(page);
      const issues = analyse(metrics);
      const screenshotPath = new URL(`${viewport.name}-${word}.png`, screenshotDir);
      await page.screenshot({ path: screenshotPath.pathname, fullPage: true });

      results.push({
        viewport: viewport.name,
        size: `${viewport.width}x${viewport.height}`,
        word,
        issues,
        screenshot: screenshotPath.pathname,
      });
    }

    await context.close();
  }
} finally {
  await browser.close();
}

const failing = results.filter((result) => result.issues.length > 0);
for (const result of results) {
  const status = result.issues.length ? "FAIL" : "PASS";
  console.log(`${status} ${result.viewport} ${result.size} ${result.word}`);
  for (const issue of result.issues) {
    console.log(`  - ${issue}`);
  }
}

if (failing.length) {
  process.exitCode = 1;
}
