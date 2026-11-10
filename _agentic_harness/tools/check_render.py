"""Validate the generated workflow graph in isolated, offline headless Chrome."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from html import escape

import yaml

HARNESS = Path(__file__).resolve().parents[1]
ROOT = HARNESS.parent
WIDTHS = (1440, 390)
RESULT_MARKER = "__SDW_GRAPH_PROBE__"
RUN_SUBPROCESS = subprocess.run


class GraphValidationError(RuntimeError):
    """The required browser or rendered graph does not satisfy its contract."""


def browser_candidates() -> list[Path]:
    home = Path.home()
    return [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        home / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        home / "Applications/Chromium.app/Contents/MacOS/Chromium",
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
        Path("/snap/bin/chromium"),
    ]


def find_browser(override: str | None = None) -> str:
    if override:
        resolved = shutil.which(override) if not Path(override).is_absolute() else override
        if resolved and Path(resolved).is_file() and os.access(resolved, os.X_OK):
            return str(Path(resolved).resolve())
        raise GraphValidationError(f"browser override is not an executable file: {override}")
    for candidate in browser_candidates():
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    raise GraphValidationError(
        "required headless browser not found; install Chrome/Chromium or pass --browser /path/to/browser"
    )


def _probe_script(nodes: list[dict[str, str]], edges: list[dict[str, object]]) -> str:
    expected_nodes = json.dumps(nodes, ensure_ascii=True).replace("<", "\\u003c")
    expected_edges = json.dumps(edges, ensure_ascii=True).replace("<", "\\u003c")
    # Keep the probe self-contained. No page resource or network request is added.
    return r"""<script>
(() => {
  try {
  const expectedNodes = __EXPECTED_NODES__;
  const expectedEdges = __EXPECTED_EDGES__;
  const errors = [];
  const fail = (message) => { if (!errors.includes(message)) errors.push(message); };
  const checkStaticSvgInventory = (svg) => {
    // The generated diagram supports one deliberately small SVG vocabulary.
    // Keep frame paint behind graph content and reject unknown paint containers.
    const children = Array.from(svg.children);
    const name = (el) => el.tagName.toLowerCase();
    const attrsAllowed = (el, allowed) => {
      for (const attr of Array.from(el.attributes)) {
        if (!allowed.includes(attr.name)) fail('unsupported SVG attribute: ' + name(el) + '.' + attr.name);
      }
    };
    const plainText = (el) => {
      if (el.children.length) fail('supported SVG text contains nested elements');
    };
    let cursor = 0;
    const take = (tag, id) => {
      const el = children[cursor++];
      if (!el || name(el) !== tag || (id && el.getAttribute('id') !== id)) {
        fail('SVG frame metadata/order differs from the supported format');
        return null;
      }
      return el;
    };
    const title = take('title', 'flow-title');
    const desc = take('desc', 'flow-desc');
    if (title) plainText(title);
    if (desc) plainText(desc);
    const defs = take('defs');
    if (defs) {
      const markers = Array.from(defs.children);
      const markerIds = markers.map((el) => el.getAttribute('id'));
      if (JSON.stringify(markerIds) !== JSON.stringify(['arrow', 'arrow-loop', 'arrow-stop']) ||
          markers.some((el) => name(el) !== 'marker' || el.children.length !== 1 || name(el.children[0]) !== 'path')) {
        fail('SVG definitions differ from the supported marker inventory');
      }
    }
    let laneCount = 0;
    while (children[cursor] && name(children[cursor]) === 'rect') {
      const lane = children[cursor++];
      laneCount++;
      if (!['lane', 'lane alt'].includes(lane.getAttribute('class'))) fail('unsupported SVG frame rectangle');
      attrsAllowed(lane, ['class', 'x', 'y', 'width', 'height', 'rx']);
    }
    if (laneCount !== 4) fail('SVG frame must have four lane backgrounds before content');
    const frameTextCounts = {'lane-title': 0, 'lane-detail': 0, 'phase-title': 0, 'phase-copy': 0};
    while (children[cursor] && name(children[cursor]) === 'text') {
      const label = children[cursor++];
      const klass = label.getAttribute('class');
      if (!(klass in frameTextCounts)) fail('unsupported SVG frame text');
      else frameTextCounts[klass]++;
      plainText(label);
      attrsAllowed(label, ['class', 'x', 'y', 'text-anchor']);
    }
    if (frameTextCounts['lane-title'] !== 4 || frameTextCounts['lane-detail'] !== 5 ||
        frameTextCounts['phase-title'] !== 4 || frameTextCounts['phase-copy'] !== 10) {
      fail('SVG frame text inventory differs from the supported format');
    }
    for (const node of expectedNodes) {
      const group = children[cursor++];
      if (!group || name(group) !== 'g' || group.getAttribute('data-node') !== node.id ||
          group.getAttribute('data-role') !== node.role) {
        fail('SVG node groups or paint order differ from the handbook graph');
        continue;
      }
      attrsAllowed(group, ['data-node', 'data-role']);
      const parts = Array.from(group.children);
      if (parts.length < 2 || name(parts[0]) !== 'rect' || parts.slice(1).some((el) => name(el) !== 'text')) {
        fail('SVG node group must contain one rectangle followed by text');
      }
      for (const part of parts) {
        if (name(part) === 'rect') attrsAllowed(part, ['class', 'x', 'y', 'width', 'height', 'rx']);
        else if (name(part) === 'text') {
          plainText(part);
          if (!['node-title', 'node-detail'].includes(part.getAttribute('class'))) fail('unsupported SVG node text');
          attrsAllowed(part, ['class', 'x', 'y', 'text-anchor']);
        }
      }
    }
    for (const edge of expectedEdges) {
      const path = children[cursor++];
      const edgeClass = edge.kind === 'fix' ? 'edge loop-edge' : edge.kind === 'blocked' ? 'edge stop-edge' : 'edge';
      if (!path || name(path) !== 'path' || path.getAttribute('data-edge') !== edge.id ||
          path.getAttribute('data-from') !== edge.from || path.getAttribute('data-to') !== edge.to ||
          path.getAttribute('data-condition') !== edge.condition || path.getAttribute('class') !== edgeClass) {
        fail('SVG edge paths or paint order differ from the handbook graph');
        continue;
      }
      attrsAllowed(path, ['class', 'data-edge', 'data-from', 'data-to', 'data-condition', 'd']);
      const titles = Array.from(path.children);
      if (titles.length !== 1 || name(titles[0]) !== 'title' || titles[0].textContent !== edge.condition || titles[0].children.length) {
        fail('SVG edge path must have its supported title');
      }
      for (const caption of edge.caption || []) {
        const label = children[cursor++];
        if (!label || name(label) !== 'text' || label.textContent !== caption ||
            !['label', 'label loop-label'].includes(label.getAttribute('class'))) {
          fail('SVG edge captions or paint order differ from the handbook graph');
          continue;
        }
        plainText(label);
        attrsAllowed(label, ['class', 'x', 'y', 'text-anchor']);
      }
    }
    if (cursor !== children.length) fail('SVG has unrecognized elements or painted content after the graph');
  };
  const parseColor = (paint) => {
    if (!paint || paint === 'none' || paint === 'transparent' || /url\(|gradient|currentcolor/i.test(paint)) return null;
    const match = /^rgba?\((.*)\)$/i.exec(paint.trim());
    if (!match) return null;
    let parts;
    if (match[1].includes(',')) parts = match[1].split(',').map((part) => part.trim());
    else parts = match[1].replace('/', ' ').trim().split(/\s+/);
    if (parts.length !== 3 && parts.length !== 4) return null;
    const channel = (part) => {
      const percent = part.endsWith('%');
      const value = Number.parseFloat(part);
      return Number.isFinite(value) ? Math.min(255, Math.max(0, percent ? value * 2.55 : value)) : NaN;
    };
    const rgb = parts.slice(0, 3).map(channel);
    let alpha = parts.length === 4 ? Number.parseFloat(parts[3]) : 1;
    if (parts.length === 4 && parts[3].endsWith('%')) alpha /= 100;
    if (rgb.some((value) => !Number.isFinite(value)) || !Number.isFinite(alpha)) return null;
    return {rgb, alpha: Math.min(1, Math.max(0, alpha))};
  };
  const luminance = (rgb) => {
    const linear = rgb.map((value) => {
      const c = value / 255;
      return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
  };
  const contrast = (a, b) => {
    const la = luminance(a), lb = luminance(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  };
  const composite = (fg, bg, alpha) => fg.map((value, index) => value * alpha + bg[index] * (1 - alpha));
  const opacityThrough = (el) => {
    let value = 1;
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) value *= Number(getComputedStyle(node).opacity);
    return value;
  };
  const paintAlpha = (el, style, channel) => opacityThrough(el) * Number(style[channel + 'Opacity'] || 1);
  const visiblePaint = (paint) => {
    const parsed = parseColor(paint);
    return Boolean(parsed && parsed.alpha > 0);
  };
  const checkEffects = (el, label) => {
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const s = getComputedStyle(node);
      const unsupported = [];
      if (s.clipPath !== 'none' || s.clip !== 'auto') unsupported.push('clipping');
      if ((s.maskImage && s.maskImage !== 'none') || (s.webkitMaskImage && s.webkitMaskImage !== 'none')) unsupported.push('masking');
      if (s.filter !== 'none' || (s.backdropFilter && s.backdropFilter !== 'none') || (s.webkitBackdropFilter && s.webkitBackdropFilter !== 'none')) unsupported.push('filtering');
      if (s.mixBlendMode !== 'normal' || s.backgroundBlendMode !== 'normal') unsupported.push('blend modes');
      if (s.transform !== 'none' || s.translate !== 'none' || s.rotate !== 'none' || s.scale !== 'none' || (s.zoom && s.zoom !== '1' && s.zoom !== 'normal')) unsupported.push('transforms');
      if (s.visibility === 'collapse' || s.contentVisibility === 'hidden') unsupported.push('hidden content');
      if (s.contain && (s.contain.split(/\s+/).includes('paint') || ['strict', 'content'].includes(s.contain))) unsupported.push('paint containment');
      if (node.hasAttribute('transform')) unsupported.push('SVG transforms');
      if (unsupported.length) fail(label + ' uses unsupported ' + [...new Set(unsupported)].join(', '));
      if (s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) <= 0) fail(label + ' or an ancestor is hidden');
    }
  };
  const checkPseudoElements = (el) => {
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      for (const pseudo of ['::before', '::after']) {
        const s = getComputedStyle(node, pseudo);
        if (s.content !== 'none' && s.content !== 'normal' && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) > 0) {
          fail('graph container or ancestor has a generated ' + pseudo + ' overlay');
        }
      }
    }
  };
  const checkContrast = (paint, alpha, backgrounds, label) => {
    const parsed = parseColor(paint);
    if (!parsed || !(alpha > 0)) {
      fail(label + ' has unsupported or invisible paint');
      return;
    }
    for (const background of backgrounds) {
      const foreground = composite(parsed.rgb, background.rgb, parsed.alpha * alpha);
      if (contrast(foreground, background.rgb) < 3) {
        fail(label + ' has less than 3:1 contrast against a graph background');
        return;
      }
    }
  };
  const visibleStyle = (el) => {
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) <= 0) return false;
    }
    return true;
  };
  const box = (el) => {
    const b = el.getBBox();
    return {x: b.x, y: b.y, width: b.width, height: b.height, right: b.x + b.width, bottom: b.y + b.height};
  };
  const inside = (b, v) => b.x >= v.x - 1 && b.y >= v.y - 1 && b.right <= v.x + v.width + 1 && b.bottom <= v.y + v.height + 1;
  const svg = document.querySelector('.diagram-wrap svg.diagram');
  const wrap = document.querySelector('.diagram-wrap');
  if (!svg || !wrap) fail('graph SVG or scroll container is missing');
  if (svg) {
    checkStaticSvgInventory(svg);
    checkEffects(svg, 'graph SVG');
    checkPseudoElements(svg);
    for (const el of svg.querySelectorAll('*')) checkEffects(el, 'graph graphic');
  }
  if (wrap) {
    checkEffects(wrap, 'graph scroll container');
    checkPseudoElements(wrap);
    if (wrap.getBoundingClientRect().width <= 0 || wrap.getBoundingClientRect().height <= 0) fail('graph scroll container has zero geometry');
    const wrapStyle = getComputedStyle(wrap);
    const wrapperColor = parseColor(wrapStyle.backgroundColor);
    if (!wrapperColor || wrapperColor.alpha !== 1 || wrapStyle.backgroundImage !== 'none' || wrapStyle.backgroundBlendMode !== 'normal' || opacityThrough(wrap) !== 1) {
      fail('graph wrapper needs a solid opaque background without effects');
    }
    for (let ancestor = wrap.parentElement; ancestor; ancestor = ancestor.parentElement) {
      const style = getComputedStyle(ancestor);
      if (['hidden', 'clip'].includes(style.overflowX) || ['hidden', 'clip'].includes(style.overflowY)) fail('graph has an ancestor that clips overflow');
    }
  }
  if (svg && (svg.getBoundingClientRect().width <= 0 || svg.getBoundingClientRect().height <= 0)) fail('graph SVG has zero rendered geometry');
  if (document.documentElement.scrollWidth > window.innerWidth + 1 || document.body.scrollWidth > window.innerWidth + 1) fail('page overflows horizontally');
  if (svg && wrap) {
    const svgRect = svg.getBoundingClientRect();
    const wrapRect = wrap.getBoundingClientRect();
    const wrapStyle = getComputedStyle(wrap);
    const contentLeft = svgRect.left - wrapRect.left - wrap.clientLeft + wrap.scrollLeft;
    const contentTop = svgRect.top - wrapRect.top - wrap.clientTop + wrap.scrollTop;
    if (contentLeft < -1 || contentTop < -1 || contentLeft + svgRect.width > wrap.scrollWidth + 1 || contentTop + svgRect.height > wrap.scrollHeight + 1) {
      fail('graph SVG is not reachable within its wrapper');
    }
    if (wrap.clientHeight + 1 < svgRect.height) fail('graph wrapper vertically clips the SVG');
    if (wrapRect.left < -1 || wrapRect.top < -1 || wrapRect.right > document.documentElement.clientWidth + 1 || wrapRect.bottom > document.documentElement.scrollHeight + 1) {
      fail('graph wrapper is outside reachable document bounds');
    }
    if (svgRect.width > wrap.clientWidth + 1 && (!['auto', 'scroll'].includes(wrapStyle.overflowX) || wrap.scrollWidth <= wrap.clientWidth)) {
      fail('overflowing diagram does not permit user scrolling');
    }
  }
  const view = svg && svg.viewBox && svg.viewBox.baseVal;
  if (!view || !(view.width > 0 && view.height > 0)) fail('graph has no positive viewBox');
  if (svg && view) {
    const rect = svg.getBoundingClientRect();
    if (rect.width / view.width < 0.5 || rect.height / view.height < 0.5) fail('graph SVG is scaled too small to remain readable');
  }
  const graphBackgrounds = [];
  if (wrap) {
    const color = parseColor(getComputedStyle(wrap).backgroundColor);
    if (color && color.alpha === 1 && opacityThrough(wrap) === 1) graphBackgrounds.push({rgb: color.rgb, label: 'wrapper'});
  }
  if (svg) {
    const backgroundShapes = [...svg.querySelectorAll('rect.lane'), ...Array.from(svg.querySelectorAll('[data-node]')).flatMap((node) => Array.from(node.querySelectorAll('rect')))];
    if (!backgroundShapes.length) fail('graph has no supported lane or node backgrounds');
    for (const shape of backgroundShapes) {
      const style = getComputedStyle(shape);
      const color = parseColor(style.fill);
      if (!color || color.alpha !== 1 || Number(style.fillOpacity || 1) !== 1 || opacityThrough(shape) !== 1) {
        fail('graph lane or node background is not a solid opaque fill');
      } else graphBackgrounds.push({rgb: color.rgb, label: 'lane or node'});
    }
  }
  const nodeEls = svg ? Array.from(svg.querySelectorAll('[data-node]')) : [];
  const actualNodes = nodeEls.map((el) => el.getAttribute('data-node')).sort();
  const nodeBoxes = Object.fromEntries(nodeEls.map((el) => [el.getAttribute('data-node'), box(el)]));
  if (JSON.stringify(actualNodes) !== JSON.stringify(expectedNodes.map((node) => node.id).sort())) fail('node inventory differs from the handbook graph');
  if (view) for (const el of nodeEls) {
    const id = el.getAttribute('data-node');
    checkEffects(el, 'node ' + id);
    const b = box(el);
    if (!(b.width > 0 && b.height > 0)) fail('node has zero geometry: ' + id);
    if (!inside(b, view)) fail('node is outside the graph viewBox: ' + id);
    for (const child of el.querySelectorAll('rect, text')) {
      checkEffects(child, 'node content ' + id);
      const childStyle = getComputedStyle(child);
      const fill = visiblePaint(childStyle.fill) && paintAlpha(child, childStyle, 'fill') > 0;
      const stroke = visiblePaint(childStyle.stroke) && paintAlpha(child, childStyle, 'stroke') > 0 && parseFloat(childStyle.strokeWidth) > 0;
      if (child.tagName.toLowerCase() === 'text' && !fill) fail('node text has no visible fill: ' + id);
      if (child.tagName.toLowerCase() === 'rect' && !fill && !stroke) fail('node box has no visible fill or stroke: ' + id);
      if (child.tagName.toLowerCase() === 'text') {
        const nodeBox = el.querySelector('rect');
        const bg = nodeBox && parseColor(getComputedStyle(nodeBox).fill);
        if (!bg || Number(getComputedStyle(nodeBox).fillOpacity || 1) !== 1 || opacityThrough(nodeBox) !== 1) fail('node text background is unsupported: ' + id);
        else checkContrast(childStyle.fill, paintAlpha(child, childStyle, 'fill'), [{rgb: bg.rgb}], 'node text ' + id);
      }
      const childBox = box(child);
      if (!(childBox.width > 0 && childBox.height > 0)) fail('node content has zero geometry: ' + id);
      if (child.tagName.toLowerCase() === 'text' && !inside(childBox, box(el.querySelector('rect')))) {
        fail('node label extends outside its box: ' + id);
      }
    }
  }
  const edgeEls = svg ? Array.from(svg.querySelectorAll('path[data-edge]')) : [];
  const actualEdges = edgeEls.map((el) => el.getAttribute('data-edge')).sort();
  const wantedEdges = expectedEdges.map((edge) => edge.id).sort();
  if (JSON.stringify(actualEdges) !== JSON.stringify(wantedEdges)) fail('edge inventory differs from the handbook graph');
  for (const el of edgeEls) {
    const id = el.getAttribute('data-edge');
    const style = getComputedStyle(el);
    const stroke = style.stroke;
    const opacity = paintAlpha(el, style, 'stroke');
    checkEffects(el, 'edge ' + id);
    if (!visiblePaint(stroke) || opacity <= 0 || parseFloat(style.strokeWidth) <= 0) fail('edge has no visible stroke: ' + id);
    else checkContrast(stroke, opacity, graphBackgrounds, 'edge ' + id);
    let length = 0;
    try { length = el.getTotalLength(); } catch (_) {}
    if (!(length > 0)) fail('edge path has zero length: ' + id);
    const pathBox = box(el);
    if (!(pathBox.width > 0 || pathBox.height > 0)) fail('edge path has zero geometry: ' + id);
    if (view && !inside(pathBox, view)) fail('edge path is outside the graph viewBox: ' + id);
    const definition = expectedEdges.find((edge) => edge.id === id);
    if (definition && length > 0) {
      const start = el.getPointAtLength(0);
      const end = el.getPointAtLength(length);
      const gap = (point, target) => {
        const dx = Math.max(target.x - point.x, 0, point.x - target.right);
        const dy = Math.max(target.y - point.y, 0, point.y - target.bottom);
        return Math.hypot(dx, dy);
      };
      if (!nodeBoxes[definition.from] || gap(start, nodeBoxes[definition.from]) > 3) fail('edge start does not meet its source node: ' + id);
      if (!nodeBoxes[definition.to] || gap(end, nodeBoxes[definition.to]) > 3) fail('edge arrow endpoint does not meet its target node: ' + id);
    }
    const wanted = el.classList.contains('loop-edge') ? 'arrow-loop' : (el.classList.contains('stop-edge') ? 'arrow-stop' : 'arrow');
    const markerEnd = style.markerEnd || style.getPropertyValue('marker-end');
    const markerMatch = /#([^)'"\s]+)/.exec(markerEnd || '');
    if (!markerMatch || markerMatch[1] !== wanted) fail('edge has no expected arrow marker: ' + id);
    const marker = markerMatch && document.getElementById(markerMatch[1]);
    if (!marker) fail('edge arrow marker target is missing: ' + id);
    else {
      // This static format supports the template's forward triangle only.
      // Positive child bounds alone do not prove paint survives a marker viewport.
      const vb = marker.viewBox.baseVal;
      if (vb.x !== 0 || vb.y !== 0 || vb.width !== 10 || vb.height !== 10 ||
          marker.refX.baseVal.value !== 9 || marker.refY.baseVal.value !== 5 ||
          marker.markerWidth.baseVal.value !== 7 || marker.markerHeight.baseVal.value !== 7 ||
          marker.getAttribute('orient') !== 'auto' ||
          (marker.getAttribute('markerUnits') || 'strokeWidth') !== 'strokeWidth' ||
          ![null, 'xMidYMid meet'].includes(marker.getAttribute('preserveAspectRatio'))) {
        fail('edge arrow marker has unsupported viewport/reference geometry: ' + id);
      }
      const markerShapes = Array.from(marker.querySelectorAll('path, polygon, polyline, circle, rect'));
      if (markerShapes.length !== 1 || markerShapes[0].tagName.toLowerCase() !== 'path' ||
          markerShapes[0].getAttribute('d') !== 'M0 0L10 5L0 10z') {
        fail('edge arrow marker is not the supported triangle: ' + id);
      }
      if (!markerShapes.length || !markerShapes.some((shape) => {
        const b = box(shape);
        const s = getComputedStyle(shape);
        const opacity = paintAlpha(shape, s, 'fill');
        checkEffects(shape, 'edge marker');
        if (b.width <= 0 || b.height <= 0 || opacity <= 0 || !visiblePaint(s.fill)) return false;
        checkContrast(s.fill, opacity, graphBackgrounds, 'edge marker');
        return true;
      })) fail('edge arrow marker target is empty: ' + id);
      if (!(Number(marker.getAttribute('markerWidth')) > 0 && Number(marker.getAttribute('markerHeight')) > 0)) fail('edge arrow marker has zero dimensions: ' + id);
    }
  }
  const output = {width: window.innerWidth, colorScheme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light', nodeCount: actualNodes.length, edgeCount: actualEdges.length, errors};
  const result = document.createElement('pre');
  result.id = 'sdw-render-probe-result';
  result.style.display = 'none';
  result.textContent = '__RESULT_MARKER__' + JSON.stringify(output);
  document.body.appendChild(result);
  } catch (error) {
    const output = {width: window.innerWidth, nodeCount: 0, edgeCount: 0, errors: ['probe exception: ' + String(error)]};
    const result = document.createElement('pre');
    result.id = 'sdw-render-probe-result';
    result.style.display = 'none';
    result.textContent = '__RESULT_MARKER__' + JSON.stringify(output);
    document.body.appendChild(result);
  }
})();
</script>""".replace("__EXPECTED_NODES__", expected_nodes).replace("__EXPECTED_EDGES__", expected_edges).replace("__RESULT_MARKER__", RESULT_MARKER)


def _extract_result(document: str, width: int) -> dict:
    match = re.search(r"__SDW_GRAPH_PROBE__(\{[^<]*\})", document)
    if not match:
        raise GraphValidationError(f"browser did not return the injected graph probe result at {width}px: {document[-500:]}")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise GraphValidationError("browser returned malformed graph probe data") from exc


def validate_html(html_path: Path, handbook_path: Path, browser: str | None = None,
                  widths: tuple[int, ...] = WIDTHS, *, dark: bool = False) -> list[dict]:
    """Render one generated handbook at each width and enforce graph visibility and geometry."""
    executable = find_browser(browser)
    handbook = yaml.safe_load(handbook_path.read_text())
    nodes = [{"id": node["id"], "role": node["role"]} for node in handbook["graph"]["nodes"]]
    edges = [{"id": edge["id"], "kind": edge["kind"], "from": edge["from"], "to": edge["to"], "condition": edge["condition"], "caption": edge.get("caption", [])} for edge in handbook["graph"]["edges"]]
    source = html_path.read_text()
    injection = _probe_script(nodes, edges)
    if "</body>" not in source:
        raise GraphValidationError(f"generated handbook has no body insertion point: {html_path}")
    injected = source.replace("</body>", injection + "</body>", 1)
    results = []
    for width in widths:
        with tempfile.TemporaryDirectory(prefix="sdw-handbook-render-") as temporary:
            temp_root = Path(temporary)
            page = temp_root / "handbook.html"
            page.write_text(injected)
            profile = temp_root / "chrome-profile"
            if width < 500:
                # Chrome's headless outer window has a 500px minimum. Render the
                # document in a real narrow browsing context inside an iframe.
                inner_document = injected
                outer = (
                    '<!doctype html><html><head><meta charset="utf-8"><script>'
                    "window.addEventListener('load',()=>{try{const f=document.querySelector('iframe');"
                    "const d=f.contentDocument;const child=d.querySelector('#sdw-render-probe-result');"
                    "const p=document.createElement('pre');p.id='sdw-render-probe-result';"
                    f"p.textContent=child?child.textContent:'{RESULT_MARKER}'+JSON.stringify({{width:d.defaultView.innerWidth,nodeCount:0,edgeCount:0,errors:['iframe probe result missing']}});"
                    "document.body.appendChild(p);}catch(e){const p=document.createElement('pre');"
                    f"p.textContent='{RESULT_MARKER}'+JSON.stringify({{width:0,nodeCount:0,edgeCount:0,errors:['iframe access failed: '+String(e)]}});"
                    "document.body.appendChild(p);}});"
                    f"</script></head><body style=\"margin:0;width:{width}px\"><iframe title=\"rendered handbook\" "
                    f"style=\"display:block;border:0;width:{width}px;height:1000px\" srcdoc=\"{escape(inner_document, quote=True)}\"></iframe>"
                    "</body></html>"
                )
                page.write_text(outer)
            command = [
                executable,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-networking",
                "--disable-sync",
                "--disable-extensions",
                "--disable-component-update",
                "--host-resolver-rules=MAP * ~NOTFOUND",
                f"--user-data-dir={profile}",
                f"--window-size={max(width, 500)},1000",
                "--virtual-time-budget=5000",
                "--dump-dom",
                page.as_uri(),
            ]
            if dark:
                command.insert(1, "--force-dark-mode")
            try:
                process = RUN_SUBPROCESS(command, capture_output=True, text=True, timeout=30, check=False)
            except subprocess.TimeoutExpired as exc:
                raise GraphValidationError(f"headless browser timed out at {width}px") from exc
            if process.returncode or not process.stdout.strip():
                details = (process.stderr or process.stdout).strip()[-1000:]
                raise GraphValidationError(f"headless browser failed at {width}px (exit {process.returncode}): {details}")
            result = _extract_result(process.stdout, width)
            if result.get("width") != width:
                raise GraphValidationError(f"browser viewport mismatch: requested {width}px, rendered {result.get('width')}px")
            if dark and result.get("colorScheme") != "dark":
                raise GraphValidationError("browser did not apply the requested dark color scheme")
            if result.get("errors"):
                errors = "; ".join(result["errors"])
                raise GraphValidationError(f"rendered graph failed at {width}px: {errors}")
            if result.get("nodeCount") != len(nodes) or result.get("edgeCount") != len(edges):
                raise GraphValidationError(f"rendered graph inventory mismatch at {width}px")
            results.append(result)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", help="Chrome/Chromium executable path or command name")
    parser.add_argument("--html", type=Path, default=HARNESS / "index.html", help="generated handbook HTML")
    parser.add_argument("--handbook", type=Path, default=HARNESS / "handbook.yaml", help="handbook graph YAML")
    parser.add_argument("--dark", action="store_true", help="also require the browser's dark color scheme")
    args = parser.parse_args(argv)
    try:
        results = validate_html(args.html, args.handbook, args.browser, dark=args.dark)
        print("headless graph render verified: " + ", ".join(f"{item['width']}px {item.get('colorScheme', 'unknown')} ({item['nodeCount']} nodes, {item['edgeCount']} edges)" for item in results))
        return 0
    except (GraphValidationError, OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(f"headless graph render: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
