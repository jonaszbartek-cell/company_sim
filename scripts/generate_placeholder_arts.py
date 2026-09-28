#!/usr/bin/env python3
"""Generate modern minimal placeholder arts for company_sim.

Outputs under web/assets/:
  goods/{id}.svg                        — flat 2D UI icons
  buildings/ui/{id}.svg                 — flat 2D UI icons
  buildings/map/{id}/{w}x{h}.svg        — fake-3D map sprites (1..9 × 1..9)
  terrain/grass.svg                     — plot ground
  roads/mask_{0..15}.svg                — N=1 E=2 S=4 W=8 road junctions
"""

from __future__ import annotations

from pathlib import Path

from company_sim.content import GameContent

ROOT = Path(__file__).resolve().parents[1] / "web" / "assets"

CAT_COLORS = {
    "raw": ("#2a9d8f", "#e9f5f3"),
    "processed": ("#457b9d", "#eef4f8"),
    "finished": ("#e76f51", "#fff1ec"),
    "utility": ("#7b2cbf", "#f3e9ff"),
    "general": ("#6c757d", "#f1f3f5"),
}

BLD_COLORS = {
    "city_hall": ("#4a5568", "#cbd5e1"),
    "mine": ("#bc6c25", "#f4a261"),
    "rig": ("#264653", "#2a9d8f"),
    "foundry": ("#9b2226", "#ee9b00"),
    "refinery": ("#023e8a", "#48cae4"),
    "chemical_plant": ("#2d6a4f", "#95d5b2"),
    "manufacturing_facility": ("#3a86ff", "#a2d2ff"),
    "electronics_facility": ("#5a189a", "#c77dff"),
    "assembly_facility": ("#0077b6", "#90e0ef"),
    "car_manufacturing_facility": ("#1b4332", "#52b788"),
    "plane_factory": ("#03045e", "#00b4d8"),
    "rocket_factory": ("#3c096c", "#e0aaff"),
    "satellite_factory": ("#212529", "#74c0fc"),
    "power_plant": ("#b08968", "#ffe8a3"),
}


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def flat_icon(label: str, bg: str, accent: str, kind: str, size: int = 64) -> str:
    short = label.replace("_", " ")
    if len(short) > 12:
        parts = short.split()
        short = "".join(p[0].upper() for p in parts[:4]) if len(parts) > 1 else short[:10]
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{accent}"/>
      <stop offset="100%" stop-color="{bg}"/>
    </linearGradient>
  </defs>
  <rect width="{size}" height="{size}" rx="{size * 0.22:.1f}" fill="#0f1418"/>
  <rect x="{size * 0.08:.1f}" y="{size * 0.08:.1f}" width="{size * 0.84:.1f}" height="{size * 0.84:.1f}"
        rx="{size * 0.18:.1f}" fill="url(#g)"/>
  <circle cx="{size * 0.78:.1f}" cy="{size * 0.22:.1f}" r="{size * 0.06:.1f}" fill="#ffffff" opacity="0.35"/>
  <text x="50%" y="46%" text-anchor="middle" fill="#0b1014" font-family="Inter,Segoe UI,sans-serif"
        font-size="{max(8, size // 7)}" font-weight="700" letter-spacing="0.04em">{_esc(kind)}</text>
  <text x="50%" y="68%" text-anchor="middle" fill="#0b1014" font-family="Inter,Segoe UI,sans-serif"
        font-size="{max(7, size // 9)}" font-weight="600" opacity="0.85">{_esc(short)}</text>
</svg>
'''


def fake3d_building(building_id: str, w: int, h: int, face: str, side: str) -> str:
    """Isometric-ish building block sized for w×h plots (viewBox in plot units)."""
    # Each plot unit = 40 viewBox units; depth skew for fake 3D
    unit = 40
    width_px = w * unit
    depth_px = h * unit
    height_px = 18 + min(w, h) * 6  # taller for larger footprints
    # Projected canvas
    skew = 10
    canvas_w = width_px + skew + 8
    canvas_h = depth_px + height_px + skew + 8
    # Front face bottom-left
    ox, oy = 4, canvas_h - depth_px - 4
    # Points for box
    # top face
    t0 = (ox, oy - height_px)
    t1 = (ox + width_px, oy - height_px)
    t2 = (ox + width_px + skew, oy - height_px - skew)
    t3 = (ox + skew, oy - height_px - skew)
    # front
    f0 = (ox, oy)
    f1 = (ox + width_px, oy)
    f2 = (ox + width_px, oy - height_px)
    f3 = (ox, oy - height_px)
    # right
    r0 = (ox + width_px, oy)
    r1 = (ox + width_px + skew, oy - skew)
    r2 = (ox + width_px + skew, oy - height_px - skew)
    r3 = (ox + width_px, oy - height_px)

    def poly(pts: list[tuple[float, float]], fill: str, opacity: float = 1.0) -> str:
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        return f'<polygon points="{points}" fill="{fill}" opacity="{opacity}"/>'

    label = f"{w}×{h}"
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w:.0f}" height="{canvas_h:.0f}"
     viewBox="0 0 {canvas_w:.1f} {canvas_h:.1f}">
  <!-- soft ground shadow -->
  <ellipse cx="{(ox + width_px / 2 + skew / 2):.1f}" cy="{(oy - skew / 2):.1f}"
           rx="{(width_px * 0.48):.1f}" ry="{(max(6, depth_px * 0.18)):.1f}"
           fill="#000000" opacity="0.22"/>
  {poly([f0, f1, f2, f3], face)}
  {poly([r0, r1, r2, r3], side)}
  {poly([t0, t1, t2, t3], "#ffffff", 0.22)}
  <!-- window strip -->
  <rect x="{ox + 4:.1f}" y="{oy - height_px + 5:.1f}" width="{max(4, width_px - 8):.1f}"
        height="3" fill="#ffffff" opacity="0.35" rx="1"/>
  <text x="{(ox + width_px / 2):.1f}" y="{(oy - height_px / 2 + 2):.1f}" text-anchor="middle"
        fill="#0b1014" font-family="Inter,Segoe UI,sans-serif" font-size="9" font-weight="700"
        opacity="0.8">{_esc(label)}</text>
</svg>
'''


def grass_tile() -> str:
    return '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="soil" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#3f7d4e"/>
      <stop offset="100%" stop-color="#2f5e3b"/>
    </linearGradient>
    <pattern id="blades" width="8" height="8" patternUnits="userSpaceOnUse">
      <path d="M2 8 Q3 3 4 8" stroke="#6fbf7a" stroke-width="1" fill="none" opacity="0.55"/>
      <path d="M6 8 Q7 2 8 8" stroke="#58a864" stroke-width="1" fill="none" opacity="0.4"/>
    </pattern>
  </defs>
  <rect width="64" height="64" rx="6" fill="url(#soil)"/>
  <rect width="64" height="64" rx="6" fill="url(#blades)"/>
  <rect x="1" y="1" width="62" height="62" rx="5" fill="none" stroke="#9ad4a3" stroke-opacity="0.25"/>
</svg>
'''


def road_mask_svg(mask: int) -> str:
    """Draw asphalt edges with side lines for N/E/S/W bits."""
    n = bool(mask & 1)
    e = bool(mask & 2)
    s = bool(mask & 4)
    w = bool(mask & 8)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">',
        '<rect width="64" height="64" fill="none"/>',
    ]
    # Asphalt strip geometry
    thick = 14
    line = 1.5

    def h_strip(y: float) -> None:
        parts.append(
            f'<rect x="0" y="{y}" width="64" height="{thick}" fill="#3a3f46"/>'
        )
        parts.append(
            f'<rect x="0" y="{y + 2}" width="64" height="{line}" fill="#f4f1de" opacity="0.9"/>'
        )
        parts.append(
            f'<rect x="0" y="{y + thick - 2 - line}" width="64" height="{line}" fill="#f4f1de" opacity="0.9"/>'
        )

    def v_strip(x: float) -> None:
        parts.append(
            f'<rect x="{x}" y="0" width="{thick}" height="64" fill="#3a3f46"/>'
        )
        parts.append(
            f'<rect x="{x + 2}" y="0" width="{line}" height="64" fill="#f4f1de" opacity="0.9"/>'
        )
        parts.append(
            f'<rect x="{x + thick - 2 - line}" y="0" width="{line}" height="64" fill="#f4f1de" opacity="0.9"/>'
        )

    # Draw center junction pad when 2+ directions meet
    dirs = sum([n, e, s, w])
    if dirs >= 2:
        parts.append('<rect x="18" y="18" width="28" height="28" fill="#3a3f46"/>')

    if n:
        parts.append(f'<rect x="{(64 - thick) / 2}" y="0" width="{thick}" height="32" fill="#3a3f46"/>')
        parts.append(
            f'<rect x="{(64 - thick) / 2 + 2}" y="0" width="{line}" height="32" fill="#f4f1de" opacity="0.9"/>'
        )
        parts.append(
            f'<rect x="{(64 - thick) / 2 + thick - 2 - line}" y="0" width="{line}" height="32" fill="#f4f1de" opacity="0.9"/>'
        )
    if s:
        parts.append(f'<rect x="{(64 - thick) / 2}" y="32" width="{thick}" height="32" fill="#3a3f46"/>')
        parts.append(
            f'<rect x="{(64 - thick) / 2 + 2}" y="32" width="{line}" height="32" fill="#f4f1de" opacity="0.9"/>'
        )
        parts.append(
            f'<rect x="{(64 - thick) / 2 + thick - 2 - line}" y="32" width="{line}" height="32" fill="#f4f1de" opacity="0.9"/>'
        )
    if w:
        parts.append(f'<rect x="0" y="{(64 - thick) / 2}" width="32" height="{thick}" fill="#3a3f46"/>')
        parts.append(
            f'<rect x="0" y="{(64 - thick) / 2 + 2}" width="32" height="{line}" fill="#f4f1de" opacity="0.9"/>'
        )
        parts.append(
            f'<rect x="0" y="{(64 - thick) / 2 + thick - 2 - line}" width="32" height="{line}" fill="#f4f1de" opacity="0.9"/>'
        )
    if e:
        parts.append(f'<rect x="32" y="{(64 - thick) / 2}" width="32" height="{thick}" fill="#3a3f46"/>')
        parts.append(
            f'<rect x="32" y="{(64 - thick) / 2 + 2}" width="32" height="{line}" fill="#f4f1de" opacity="0.9"/>'
        )
        parts.append(
            f'<rect x="32" y="{(64 - thick) / 2 + thick - 2 - line}" width="32" height="{line}" fill="#f4f1de" opacity="0.9"/>'
        )

    # Corner fillets / center lines for crosses
    if dirs >= 2:
        parts.append(
            '<circle cx="32" cy="32" r="2" fill="#f4f1de" opacity="0.55"/>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> None:
    c = GameContent.load()
    goods = ROOT / "goods"
    ui = ROOT / "buildings" / "ui"
    maps = ROOT / "buildings" / "map"
    terrain = ROOT / "terrain"
    roads = ROOT / "roads"
    for d in (goods, ui, maps, terrain, roads):
        d.mkdir(parents=True, exist_ok=True)

    # Clear legacy flat map sprites (old {id}.svg / {id}_{w}x{h}.svg layout)
    for old in maps.glob("*.svg"):
        old.unlink(missing_ok=True)

    for item in c.items.all():
        bg, accent = CAT_COLORS.get(item.category, CAT_COLORS["general"])
        write(goods / f"{item.id}.svg", flat_icon(item.id, bg, accent, item.category[:3].upper(), 56))

    map_count = 0
    for b in c.buildings.all():
        face, side = BLD_COLORS.get(b.id, ("#6c757d", "#adb5bd"))
        write(ui / f"{b.id}.svg", flat_icon(b.name if len(b.name) <= 14 else b.id, face, side, "BLD", 72))
        bdir = maps / b.id
        bdir.mkdir(parents=True, exist_ok=True)
        for w in range(1, 10):
            for h in range(1, 10):
                write(bdir / f"{w}x{h}.svg", fake3d_building(b.id, w, h, face, side))
                map_count += 1

    write(terrain / "grass.svg", grass_tile())
    write(
        terrain / "grass_specialized.svg",
        grass_tile()
        .replace("#3f7d4e", "#5a7d3f")
        .replace("#2f5e3b", "#3f5e2a")
        .replace("#6fbf7a", "#c4bf6f")
        .replace("#58a864", "#a8a058")
        .replace("#9ad4a3", "#d4d49a"),
    )

    for mask in range(16):
        write(roads / f"mask_{mask}.svg", road_mask_svg(mask))

    print(f"goods={len(list(goods.glob('*.svg')))}")
    print(f"ui={len(list(ui.glob('*.svg')))}")
    print(f"map={map_count} across {len(list(maps.iterdir()))} building folders")
    print(f"roads={len(list(roads.glob('*.svg')))}")
    print("terrain ok")


if __name__ == "__main__":
    main()
