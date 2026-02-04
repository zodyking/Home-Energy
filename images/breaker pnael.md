#html

<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>Breaker Panel Card</title>
    <link rel="stylesheet" href="styles.css" />
  </head>
  <body>
    <div class="bp-card" id="mount" aria-label="Breaker panel card"></div>
    <script src="app.js"></script>
  </body>
</html>

#css
:root{
  --bg1:#f7fbff;
  --bg2:#e7f2fb;

  --steel0:#f2f6f9;
  --steel1:#e0e7ed;
  --steel2:#cfd8df;
  --steel3:#bcc7d0;
  --steel4:#aebbc6;

  --ink1:rgba(10,16,22,.45);
  --ink2:rgba(10,16,22,.28);
  --ink3:rgba(10,16,22,.18);
  --white1:rgba(255,255,255,.70);
  --white2:rgba(255,255,255,.40);
}

*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0;
  display:grid;
  place-items:center;
  font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;
  background:
    radial-gradient(1200px 800px at 55% 35%, rgba(255,255,255,.95), rgba(255,255,255,0) 60%),
    radial-gradient(900px 700px at 35% 30%, rgba(214,234,249,.55), rgba(214,234,249,0) 55%),
    linear-gradient(180deg,var(--bg1),var(--bg2));
}

.bp-card{
  width:min(860px,94vw);
  aspect-ratio:16/9;
  border-radius:22px;
  padding:26px;
  background:
    radial-gradient(130% 120% at 50% 38%, rgba(255,255,255,.92), rgba(255,255,255,0) 55%),
    radial-gradient(70% 70% at 30% 35%, rgba(205,226,246,.40), rgba(205,226,246,0) 58%),
    linear-gradient(180deg, rgba(255,255,255,.85), rgba(235,245,255,.85));
  box-shadow:
    0 26px 80px rgba(0,0,0,.18),
    0 6px 16px rgba(0,0,0,.14);
  display:grid;
  place-items:center;
  overflow:hidden;
}

.bp-card svg{
  width:min(560px,78%);
  height:auto;
  display:block;
  filter: drop-shadow(0 26px 40px rgba(0,0,0,.14));
}

#javascript
(function () {
  const mount = document.getElementById("mount");
  const NS = "http://www.w3.org/2000/svg";

  const svg = el("svg", {
    xmlns: NS,
    viewBox: "0 0 640 640",
    role: "img",
    "aria-label": "Breaker panel"
  });

  const defs = el("defs");
  defs.append(
    linearGrad("metalOuter", [
      [0, "#edf3f7"],
      [0.28, "#dbe3ea"],
      [0.55, "#cbd5dd"],
      [0.78, "#b9c4cd"],
      [1, "#d8e0e7"]
    ], { x1: "0", y1: "0", x2: "0", y2: "1" }),

    linearGrad("metalOuterEdge", [
      [0, "rgba(255,255,255,.70)"],
      [0.45, "rgba(255,255,255,0)"],
      [1, "rgba(0,0,0,.18)"]
    ], { x1: "0", y1: "0", x2: "0", y2: "1" }),

    radialGrad("outerGlow", [
      [0, "rgba(255,255,255,.70)"],
      [0.55, "rgba(255,255,255,.18)"],
      [1, "rgba(255,255,255,0)"]
    ], { cx: "38%", cy: "18%", r: "90%" }),

    linearGrad("metalInset", [
      [0, "#e3eaef"],
      [0.5, "#cdd6dd"],
      [1, "#b7c2cb"]
    ], { x1: "0", y1: "0", x2: "1", y2: "1" }),

    linearGrad("doorMetal", [
      [0, "#e2e9ee"],
      [0.55, "#cbd4dc"],
      [1, "#b7c2cb"]
    ], { x1: "0", y1: "0", x2: "1", y2: "1" }),

    radialGrad("doorSheen", [
      [0, "rgba(255,255,255,.55)"],
      [0.5, "rgba(255,255,255,.10)"],
      [1, "rgba(255,255,255,0)"]
    ], { cx: "42%", cy: "18%", r: "95%" }),

    linearGrad("stripMetal", [
      [0, "#eaf0f5"],
      [0.45, "#d5dee6"],
      [1, "#c1ccd5"]
    ], { x1: "0", y1: "0", x2: "0", y2: "1" }),

    linearGrad("breakerBody", [
      [0, "#1a1f26"],
      [0.5, "#0f1318"],
      [1, "#1b212a"]
    ], { x1: "0", y1: "0", x2: "1", y2: "1" }),

    radialGrad("blueToggle", [
      [0, "rgba(90,190,235,.45)"],
      [0.55, "rgba(90,190,235,.14)"],
      [1, "rgba(0,0,0,0)"]
    ], { cx: "35%", cy: "35%", r: "85%" }),

    linearGrad("screwGrad", [
      [0, "#f2f7fa"],
      [0.55, "#d2dbe2"],
      [1, "#aebbc6"]
    ], { x1: "0", y1: "0", x2: "1", y2: "1" }),

    filterDropInner("softBevel", 0.9)
  );
  svg.append(defs);

  const g = el("g");
  svg.append(g);

  const panel = roundedRect(60, 60, 520, 520, 10, {
    fill: "url(#metalOuter)"
  });
  g.append(panel);

  g.append(roundedRect(60, 60, 520, 520, 10, {
    fill: "none",
    stroke: "rgba(10,16,22,.55)",
    "stroke-width": 3.2
  }));

  g.append(roundedRect(72, 72, 496, 496, 9, {
    fill: "none",
    stroke: "rgba(255,255,255,.55)",
    "stroke-width": 2.2
  }));

  g.append(roundedRect(76, 76, 488, 488, 8, {
    fill: "none",
    stroke: "rgba(10,16,22,.22)",
    "stroke-width": 1.8
  }));

  g.append(roundedRect(60, 60, 520, 520, 10, {
    fill: "url(#outerGlow)",
    opacity: 0.9
  }));

  g.append(roundedRect(60, 60, 520, 520, 10, {
    fill: "none",
    stroke: "url(#metalOuterEdge)",
    "stroke-width": 3
  }));

  g.append(roundedRect(170, 140, 300, 360, 10, {
    fill: "url(#metalInset)",
    stroke: "rgba(10,16,22,.35)",
    "stroke-width": 2.2
  }));

  g.append(roundedRect(182, 152, 276, 336, 12, {
    fill: "none",
    stroke: "rgba(255,255,255,.35)",
    "stroke-width": 1.8
  }));

  const door = roundedRect(185, 155, 270, 330, 14, {
    fill: "url(#doorMetal)",
    stroke: "rgba(10,16,22,.42)",
    "stroke-width": 2.2
  });
  g.append(door);

  g.append(roundedRect(185, 155, 270, 330, 14, {
    fill: "url(#doorSheen)",
    opacity: 0.9
  }));

  g.append(roundedRect(195, 168, 250, 304, 22, {
    fill: "none",
    stroke: "rgba(10,16,22,.32)",
    "stroke-width": 2.0
  }));

  g.append(roundedRect(202, 176, 236, 288, 20, {
    fill: "none",
    stroke: "rgba(255,255,255,.28)",
    "stroke-width": 1.6
  }));

  g.append(roundedRect(170, 140, 300, 360, 10, {
    fill: "none",
    stroke: "rgba(0,0,0,.10)",
    "stroke-width": 1.2
  }));

  g.append(roundedRect(286, 168, 68, 12, 3, {
    fill: "rgba(245,250,255,.38)",
    stroke: "rgba(10,16,22,.30)",
    "stroke-width": 1.4
  }));

  g.append(roundedRect(286, 460, 68, 12, 3, {
    fill: "rgba(245,250,255,.38)",
    stroke: "rgba(10,16,22,.30)",
    "stroke-width": 1.4
  }));

  g.append(roundedRect(472, 310, 12, 36, 3, {
    fill: "rgba(55,70,85,.70)"
  }));

  g.append(el("path", {
    d: "M180 498 L460 498",
    stroke: "rgba(10,16,22,.14)",
    "stroke-width": 1.2,
    opacity: 0.8
  }));

  const stripOuter = roundedRect(244, 242, 152, 222, 7, {
    fill: "url(#stripMetal)",
    stroke: "rgba(10,16,22,.26)",
    "stroke-width": 1.6
  });
  g.append(stripOuter);

  g.append(roundedRect(248, 246, 144, 214, 6, {
    fill: "none",
    stroke: "rgba(255,255,255,.35)",
    "stroke-width": 1.6
  }));

  g.append(roundedRect(252, 250, 136, 206, 6, {
    fill: "none",
    stroke: "rgba(0,0,0,.10)",
    "stroke-width": 1.2
  }));

  const leftColX = 258;
  const rightColX = 323;
  const topY = 258;
  const rowH = 18;
  const gap = 6;

  for (let i = 0; i < 8; i++) {
    const y = topY + i * (rowH + gap);
    g.append(breaker(leftColX, y, 56, rowH));
    g.append(breaker(rightColX, y, 56, rowH));
  }

  g.append(numberScale(238, 258, 12, 210, true));
  g.append(numberScale(404, 258, 12, 210, false));

  g.append(screw(92, 92));
  g.append(screw(548, 92));
  g.append(screw(92, 548));
  g.append(screw(548, 548));

  g.append(vignette());

  mount.replaceChildren(svg);

  function el(name, attrs) {
    const n = document.createElementNS(NS, name);
    if (attrs) for (const k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  }

  function roundedRect(x, y, w, h, r, attrs) {
    return el("rect", { x, y, width: w, height: h, rx: r, ry: r, ...attrs });
  }

  function linearGrad(id, stops, attrs) {
    const lg = el("linearGradient", { id, ...attrs });
    stops.forEach(([o, c]) => lg.append(el("stop", { offset: pct(o), "stop-color": c })));
    return lg;
  }

  function radialGrad(id, stops, attrs) {
    const rg = el("radialGradient", { id, ...attrs });
    stops.forEach(([o, c]) => rg.append(el("stop", { offset: pct(o), "stop-color": c })));
    return rg;
  }

  function pct(v) {
    return (v * 100).toFixed(1) + "%";
  }

  function filterDropInner(id, strength) {
    const f = el("filter", { id, x: "-20%", y: "-20%", width: "140%", height: "140%" });
    f.append(el("feDropShadow", {
      dx: "0",
      dy: (1.2 * strength).toFixed(2),
      stdDeviation: (1.4 * strength).toFixed(2),
      "flood-color": "rgba(0,0,0,.22)"
    }));
    return f;
  }

  function screw(cx, cy) {
    const group = el("g");
    group.append(el("circle", {
      cx, cy, r: 14,
      fill: "url(#screwGrad)",
      stroke: "rgba(10,16,22,.45)",
      "stroke-width": 2.2
    }));
    group.append(el("circle", {
      cx, cy, r: 9,
      fill: "rgba(255,255,255,.18)",
      stroke: "rgba(10,16,22,.26)",
      "stroke-width": 1.6
    }));
    group.append(el("rect", {
      x: cx - 7,
      y: cy - 1,
      width: 14,
      height: 2,
      rx: 1,
      fill: "rgba(10,16,22,.55)",
      transform: `rotate(-18 ${cx} ${cy})`
    }));
    group.append(el("circle", {
      cx: cx - 3.5,
      cy: cy - 4,
      r: 4,
      fill: "rgba(255,255,255,.52)",
      opacity: 0.75
    }));
    return group;
  }

  function breaker(x, y, w, h) {
    const group = el("g");

    group.append(roundedRect(x, y, w, h, 3, {
      fill: "url(#breakerBody)",
      stroke: "rgba(255,255,255,.10)",
      "stroke-width": 1
    }));

    group.append(roundedRect(x + 1.2, y + 1.2, w - 2.4, h - 2.4, 3, {
      fill: "none",
      stroke: "rgba(0,0,0,.40)",
      "stroke-width": 1,
      opacity: 0.30
    }));

    group.append(roundedRect(x + 6, y + 4, 16, h - 8, 2.5, {
      fill: "rgba(18,24,30,.80)",
      stroke: "rgba(255,255,255,.10)",
      "stroke-width": 1
    }));

    group.append(roundedRect(x + 6, y + 4, 16, h - 8, 2.5, {
      fill: "url(#blueToggle)",
      opacity: 0.85
    }));

    group.append(roundedRect(x + w - 24, y + 4, 18, h - 8, 2, {
      fill: "rgba(255,255,255,.06)"
    }));

    for (let i = 0; i < 4; i++) {
      group.append(el("rect", {
        x: x + w - 22 + i * 4.2,
        y: y + 5,
        width: 1.5,
        height: h - 10,
        fill: "rgba(255,255,255,.16)",
        opacity: 0.50
      }));
    }

    group.append(el("path", {
      d: `M ${x+2} ${y+2} L ${x+w-2} ${y+2}`,
      stroke: "rgba(255,255,255,.10)",
      "stroke-width": 1
    }));

    return group;
  }

  function numberScale(x, y, w, h, left) {
    const group = el("g");
    const steps = 8;

    for (let i = 0; i <= steps; i++) {
      const yy = y + (h / steps) * i;
      group.append(el("line", {
        x1: x,
        y1: yy,
        x2: x + w,
        y2: yy,
        stroke: "rgba(0,0,0,.18)",
        "stroke-width": 1
      }));
    }

    const numsLeft = [1,2,3,4,5,6,7,8];
    const numsRight = [11,12,13,14,15,16,17,18];

    for (let i = 0; i < steps; i++) {
      const yy = y + (h / steps) * i + (h / steps) * 0.52;
      const t = el("text", {
        x: left ? (x + 1) : (x + w - 1),
        y: yy,
        "text-anchor": left ? "start" : "end",
        "dominant-baseline": "middle",
        "font-size": 10,
        fill: "rgba(0,0,0,.34)"
      });
      t.textContent = left ? numsLeft[i] : numsRight[i];
      group.append(t);
    }

    return group;
  }

  function vignette() {
    const v = el("path", {
      d: "M60,60 h520 v520 h-520 z",
      fill: "rgba(0,0,0,.00)"
    });
    v.setAttribute("filter", "url(#softBevel)");

    const overlay = el("rect", {
      x: 60, y: 60, width: 520, height: 520, rx: 10, ry: 10,
      fill: "rgba(0,0,0,.06)",
      opacity: 0.18
    });

    const mask = el("mask", { id: "fadeMask" });
    const mrect = el("rect", { x: 0, y: 0, width: 640, height: 640, fill: "white" });
    mask.append(mrect);
    defs.append(mask);

    overlay.setAttribute("mask", "url(#fadeMask)");
    overlay.setAttribute("opacity", "0.16");

    const g2 = el("g");
    g2.append(overlay);

    g2.append(roundedRect(60, 60, 520, 520, 10, {
      fill: "none",
      stroke: "rgba(0,0,0,.10)",
      "stroke-width": 1.2,
      opacity: 0.75
    }));

    return g2;
  }
})();
