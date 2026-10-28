"""Build a compact AI-workroom scene in Blender.

Run:
    blender --background --python blender_workroom/build_workroom.py

Outputs are written to ``blender_workroom/output``:
    ai_workroom.blend
    01_layout_random_color.png
    02_neutral_clay.png
    03_daylight_final.png
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
OUTPUT.mkdir(parents=True, exist_ok=True)
random.seed(11)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (
        bpy.data.meshes,
        bpy.data.curves,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
    ):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)


def material(
    name: str,
    color: tuple[float, float, float, float],
    roughness: float = 0.45,
    metallic: float = 0.0,
    emission: tuple[float, float, float, float] | None = None,
    emission_strength: float = 0.0,
) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if emission:
        emission_input = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
        if emission_input:
            emission_input.default_value = emission
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    return mat


def add_cube(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
    mat: bpy.types.Material,
    bevel: float = 0.0,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    if bevel:
        mod = obj.modifiers.new("Soft edges", "BEVEL")
        mod.width = bevel
        mod.segments = 3
    return obj


def add_cylinder(
    name: str,
    location: tuple[float, float, float],
    radius: float,
    depth: float,
    mat: bpy.types.Material,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    vertices: int = 32,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices, radius=radius, depth=depth, location=location, rotation=rotation
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    bevel = obj.modifiers.new("Edge rolloff", "BEVEL")
    bevel.width = min(radius * 0.12, 0.025)
    bevel.segments = 2
    return obj


def add_curve(
    name: str,
    points: list[tuple[float, float, float]],
    mat: bpy.types.Material,
    radius: float = 0.012,
) -> bpy.types.Object:
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 12
    curve.bevel_depth = radius
    curve.bevel_resolution = 3
    spline = curve.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for bp, point in zip(spline.bezier_points, points):
        bp.co = point
        bp.handle_left_type = "AUTO"
        bp.handle_right_type = "AUTO"
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    return obj


def point_camera(camera: bpy.types.Object, target: tuple[float, float, float]) -> None:
    direction = Vector(target) - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def build_architecture(mats: dict[str, bpy.types.Material]) -> None:
    add_cube("Floor", (0, 0, -0.08), (3.25, 2.75, 0.08), mats["floor"])
    add_cube("LeftWall", (-3.18, 0, 1.55), (0.08, 2.75, 1.55), mats["wall"])
    add_cube("BackWallLower", (0, 2.68, 0.55), (3.25, 0.08, 0.55), mats["wall"])
    add_cube("BackWallUpper", (0, 2.68, 2.75), (3.25, 0.08, 0.35), mats["wall"])
    add_cube("BackWallLeft", (-2.65, 2.68, 1.65), (0.60, 0.08, 1.10), mats["wall"])
    add_cube("BackWallRight", (2.65, 2.68, 1.65), (0.60, 0.08, 1.10), mats["wall"])
    add_cube("WindowFrameTop", (0, 2.59, 2.68), (2.05, 0.06, 0.06), mats["metal"])
    add_cube("WindowFrameBottom", (0, 2.59, 0.62), (2.05, 0.06, 0.06), mats["metal"])
    add_cube("WindowFrameLeft", (-2.0, 2.59, 1.65), (0.06, 0.06, 1.03), mats["metal"])
    add_cube("WindowFrameRight", (2.0, 2.59, 1.65), (0.06, 0.06, 1.03), mats["metal"])
    add_cube("WindowMullion", (0, 2.58, 1.65), (0.035, 0.06, 1.03), mats["metal"])
    for idx in range(20):
        z = 0.75 + idx * 0.095
        add_cube(
            f"Blind_{idx:02d}",
            (0, 2.46, z),
            (1.95, 0.045, 0.022),
            mats["blind"],
            bevel=0.008,
            rotation=(math.radians(16), 0, 0),
        )


def build_desks(mats: dict[str, bpy.types.Material]) -> None:
    add_cube("MainDeskTop", (0.35, 1.34, 0.79), (2.25, 0.62, 0.055), mats["desk"], 0.035)
    add_cube("SideDeskTop", (2.53, 0.14, 0.79), (0.62, 0.86, 0.055), mats["desk"], 0.035)
    for x in (-1.75, 1.75):
        for y in (0.88, 1.78):
            add_cube(f"DeskLeg_{x}_{y}", (x, y, 0.4), (0.04, 0.04, 0.4), mats["metal"])
    for x in (2.08, 2.97):
        for y in (-0.48, 0.74):
            add_cube(f"SideLeg_{x}_{y}", (x, y, 0.4), (0.04, 0.04, 0.4), mats["metal"])
    add_cube("DrawerUnit", (2.55, 1.2, 0.4), (0.43, 0.42, 0.4), mats["drawer"], 0.035)
    for z in (0.22, 0.58):
        add_cube(f"DrawerFace_{z}", (2.55, 0.765, z), (0.39, 0.025, 0.15), mats["drawer"], 0.015)
        add_cube(f"DrawerHandle_{z}", (2.55, 0.73, z), (0.11, 0.025, 0.015), mats["metal"], 0.01)


def build_monitor(
    name: str,
    x: float,
    y: float,
    screen_mat: bpy.types.Material,
    mats: dict[str, bpy.types.Material],
) -> None:
    add_cube(f"{name}_Body", (x, y, 1.55), (0.58, 0.06, 0.36), mats["black"], 0.045)
    add_cube(f"{name}_Screen", (x, y - 0.066, 1.55), (0.52, 0.012, 0.30), screen_mat, 0.015)
    add_cube(f"{name}_Stem", (x, y, 1.06), (0.035, 0.035, 0.16), mats["black"], 0.015)
    add_cube(f"{name}_Base", (x, y - 0.02, 0.89), (0.22, 0.18, 0.025), mats["black"], 0.02)


def build_equipment(mats: dict[str, bpy.types.Material]) -> None:
    build_monitor("MonitorLeft", -0.45, 1.92, mats["screen_off"], mats)
    build_monitor("MonitorRight", 0.82, 1.92, mats["screen_on"], mats)
    add_cube("Webcam", (0.82, 1.83, 1.98), (0.085, 0.04, 0.045), mats["black"], 0.025)
    add_cylinder("WebcamLens", (0.82, 1.785, 1.98), 0.022, 0.018, mats["glass"], (math.pi / 2, 0, 0))

    add_cube("KeyboardBase", (0.26, 0.91, 0.875), (0.55, 0.18, 0.025), mats["black"], 0.025)
    for row in range(5):
        for col in range(14):
            x = -0.23 + col * 0.075
            y = 0.80 + row * 0.062
            add_cube(f"Key_{row}_{col}", (x, y, 0.908), (0.029, 0.024, 0.012), mats["key"], 0.006)
    add_cube("MousePad", (1.25, 0.92, 0.86), (0.34, 0.28, 0.008), mats["black"], 0.035)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, location=(1.25, 0.88, 0.91))
    mouse = bpy.context.object
    mouse.name = "Mouse"
    mouse.scale = (0.075, 0.11, 0.045)
    mouse.data.materials.append(mats["black"])

    add_cube("PCTower", (2.1, 1.38, 1.35), (0.28, 0.48, 0.52), mats["pc"], 0.045)
    add_cube("PCTowerGlass", (1.807, 1.38, 1.35), (0.008, 0.42, 0.45), mats["glass"], 0.01)
    for z in (1.08, 1.36, 1.64):
        add_cylinder(f"PCFan_{z}", (1.78, 1.7, z), 0.10, 0.02, mats["screen_on"], (0, math.pi / 2, 0))

    add_cube("LaptopBase", (2.52, -0.05, 0.89), (0.36, 0.25, 0.025), mats["silver"], 0.025)
    add_cube(
        "LaptopScreen",
        (2.52, 0.14, 1.16),
        (0.36, 0.025, 0.24),
        mats["silver"],
        0.025,
        rotation=(math.radians(-16), 0, 0),
    )
    add_cube(
        "LaptopDisplay",
        (2.52, 0.10, 1.16),
        (0.32, 0.008, 0.20),
        mats["screen_off"],
        0.01,
        rotation=(math.radians(-16), 0, 0),
    )


def build_chair(mats: dict[str, bpy.types.Material]) -> None:
    add_cylinder("ChairPost", (-0.55, -0.05, 0.47), 0.065, 0.42, mats["metal"])
    add_cylinder("ChairHub", (-0.55, -0.05, 0.22), 0.11, 0.10, mats["black"])
    for idx in range(5):
        angle = idx * (math.tau / 5)
        end = (-0.55 + math.cos(angle) * 0.42, -0.05 + math.sin(angle) * 0.42, 0.13)
        add_curve("ChairStarArm", [(-0.55, -0.05, 0.20), end], mats["metal"], 0.03)
        add_cylinder("ChairCaster", end, 0.055, 0.045, mats["black"], (math.pi / 2, 0, 0), 20)
    add_cube("ChairSeat", (-0.55, -0.05, 0.73), (0.48, 0.47, 0.105), mats["leather"], 0.12)
    add_cube(
        "ChairBack",
        (-0.55, 0.37, 1.34),
        (0.48, 0.10, 0.58),
        mats["leather"],
        0.13,
        rotation=(math.radians(-7), 0, 0),
    )
    for side in (-1, 1):
        x = -0.55 + side * 0.55
        add_cube(f"ArmRestPost_{side}", (x, -0.02, 0.94), (0.035, 0.035, 0.22), mats["black"], 0.02)
        add_cube(f"ArmRest_{side}", (x, 0.0, 1.17), (0.18, 0.055, 0.045), mats["leather"], 0.035)


def build_shelves_and_clutter(mats: dict[str, bpy.types.Material]) -> None:
    for x in (-2.70, 2.78):
        for z in (0.08, 0.78, 1.48, 2.18):
            add_cube(f"ShelfBoard_{x}_{z}", (x, 1.25, z), (0.36, 0.85, 0.035), mats["wood"], 0.015)
        for y in (0.42, 2.08):
            add_cube(f"ShelfSide_{x}_{y}", (x, y, 1.13), (0.035, 0.035, 1.13), mats["metal"])
    colors = [mats["book_red"], mats["book_blue"], mats["book_green"], mats["paper"]]
    for shelf_x in (-2.70, 2.78):
        for level in range(3):
            z = 0.18 + level * 0.70
            cursor = 0.62
            for idx in range(9):
                width = random.uniform(0.025, 0.055)
                height = random.uniform(0.23, 0.46)
                add_cube(
                    f"Book_{shelf_x}_{level}_{idx}",
                    (shelf_x, cursor, z + height),
                    (width, 0.15, height),
                    random.choice(colors),
                    0.008,
                    rotation=(0, random.uniform(-0.04, 0.04), 0),
                )
                cursor += width * 2 + 0.018
    # Desk clutter
    for idx, (x, y) in enumerate(((-1.25, 1.0), (-1.55, 1.18), (1.58, 1.15), (1.48, 1.42))):
        add_cylinder(f"Cup_{idx}", (x, y, 0.98), 0.075, 0.19, mats["ceramic"])
    for idx in range(8):
        x = random.uniform(-1.8, -0.9)
        y = random.uniform(0.82, 1.7)
        add_cube(
            f"DeskBook_{idx}",
            (x, y, 0.89 + idx * 0.035),
            (random.uniform(0.14, 0.25), random.uniform(0.09, 0.16), 0.018),
            random.choice(colors),
            0.008,
            rotation=(0, 0, random.uniform(-0.25, 0.25)),
        )
    add_cube("CorkBoard", (-2.25, 2.48, 1.72), (0.42, 0.035, 0.42), mats["cork"], 0.025)
    for idx in range(4):
        add_cube(
            f"CorkNote_{idx}",
            (-2.25 + random.uniform(-0.26, 0.26), 2.435, 1.72 + random.uniform(-0.26, 0.26)),
            (0.10, 0.008, 0.13),
            mats["paper"],
            0.005,
            rotation=(0, random.uniform(-0.08, 0.08), random.uniform(-0.2, 0.2)),
        )
    # Loose cables on the desk and dropping to the floor.
    add_curve("CableKeyboard", [(0.6, 1.0, 0.91), (0.7, 1.3, 0.90), (0.75, 1.8, 0.91)], mats["cable"])
    add_curve("CableLaptop", [(2.30, 0.1, 0.90), (2.0, 0.35, 0.84), (1.95, 0.6, 0.35), (1.7, 0.8, 0.07)], mats["cable"])
    add_curve("CableMonitor", [(0.8, 1.9, 1.0), (1.15, 1.85, 0.78), (1.25, 1.9, 0.08)], mats["cable"])


def build_lighting_and_camera(mats: dict[str, bpy.types.Material]) -> None:
    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.055, 0.075, 0.11, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.23

    bpy.ops.object.light_add(type="AREA", location=(-0.8, 2.25, 2.2))
    window_light = bpy.context.object
    window_light.name = "WindowDaylight"
    window_light.data.energy = 900
    window_light.data.shape = "RECTANGLE"
    window_light.data.size = 3.8
    window_light.data.size_y = 1.8
    window_light.data.color = (0.68, 0.82, 1.0)
    point_camera(window_light, (0.0, 0.0, 0.8))

    bpy.ops.object.light_add(type="SUN", location=(0, 0, 3))
    sun = bpy.context.object
    sun.name = "MorningSun"
    sun.rotation_euler = (math.radians(34), math.radians(-18), math.radians(-24))
    sun.data.energy = 2.2
    sun.data.angle = math.radians(4)
    sun.data.color = (1.0, 0.76, 0.52)

    bpy.ops.object.light_add(type="AREA", location=(-1.45, 1.25, 2.15))
    desk_light = bpy.context.object
    desk_light.name = "DeskLampGlow"
    desk_light.data.energy = 120
    desk_light.data.shape = "DISK"
    desk_light.data.size = 0.35
    desk_light.data.color = (1.0, 0.55, 0.24)
    point_camera(desk_light, (-1.2, 0.9, 0.8))

    # Volume cube for gentle rays through the blinds.
    volume = add_cube("RoomVolume", (0, 0, 1.5), (3.05, 2.55, 1.45), mats["volume"])
    volume.display_type = "WIRE"

    bpy.ops.object.camera_add(location=(4.75, -5.8, 2.25))
    camera = bpy.context.object
    camera.name = "HeroCamera"
    camera.data.lens = 40
    camera.data.sensor_width = 36
    point_camera(camera, (0.25, 0.95, 1.12))
    bpy.context.scene.camera = camera


def make_materials() -> dict[str, bpy.types.Material]:
    mats = {
        "wall": material("Warm plaster", (0.34, 0.31, 0.28, 1), 0.82),
        "floor": material("Dark oak floor", (0.075, 0.045, 0.026, 1), 0.55),
        "desk": material("Grey laminate", (0.19, 0.20, 0.21, 1), 0.42),
        "wood": material("Bookcase oak", (0.27, 0.13, 0.055, 1), 0.58),
        "metal": material("Dark steel", (0.04, 0.05, 0.055, 1), 0.30, 0.72),
        "black": material("Soft black", (0.018, 0.022, 0.026, 1), 0.35),
        "key": material("Keyboard keycaps", (0.055, 0.06, 0.065, 1), 0.48),
        "leather": material("Worn black leather", (0.025, 0.031, 0.035, 1), 0.36),
        "drawer": material("Warm grey drawer", (0.22, 0.21, 0.20, 1), 0.52),
        "pc": material("PC dark chassis", (0.025, 0.028, 0.035, 1), 0.25, 0.35),
        "silver": material("Laptop aluminium", (0.28, 0.30, 0.32, 1), 0.25, 0.65),
        "screen_off": material("Unlit screen glass", (0.004, 0.006, 0.008, 1), 0.12, 0.15),
        "screen_on": material(
            "Cool screen glow",
            (0.02, 0.10, 0.16, 1),
            0.22,
            emission=(0.035, 0.32, 0.62, 1),
            emission_strength=4.0,
        ),
        "glass": material("Glass dark", (0.05, 0.08, 0.10, 1), 0.08, 0.0),
        "blind": material("Blind linen", (0.42, 0.44, 0.42, 1), 0.75),
        "book_red": material("Book red", (0.30, 0.045, 0.028, 1), 0.6),
        "book_blue": material("Book blue", (0.035, 0.11, 0.22, 1), 0.6),
        "book_green": material("Book green", (0.07, 0.20, 0.12, 1), 0.6),
        "paper": material("Aged paper", (0.64, 0.57, 0.44, 1), 0.85),
        "ceramic": material("Ivory ceramic", (0.55, 0.48, 0.38, 1), 0.28),
        "cork": material("Cork board", (0.30, 0.13, 0.045, 1), 0.85),
        "cable": material("Cable rubber", (0.008, 0.010, 0.012, 1), 0.62),
    }
    volume = bpy.data.materials.new("Atmosphere volume")
    volume.use_nodes = True
    nodes = volume.node_tree.nodes
    links = volume.node_tree.links
    for node in list(nodes):
        nodes.remove(node)
    output = nodes.new("ShaderNodeOutputMaterial")
    principled = nodes.new("ShaderNodeVolumePrincipled")
    principled.inputs["Density"].default_value = 0.018
    principled.inputs["Anisotropy"].default_value = 0.35
    links.new(principled.outputs["Volume"], output.inputs["Volume"])
    mats["volume"] = volume
    return mats


def configure_render() -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in {
        item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items
    } else "BLENDER_EEVEE"
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.look = "AgX - Medium High Contrast"


def render_final() -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in {
        item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items
    } else "BLENDER_EEVEE"
    scene.render.filepath = str(OUTPUT / "03_daylight_final.png")
    bpy.ops.render.render(write_still=True)


def render_clay(mats: dict[str, bpy.types.Material]) -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in {
        item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items
    } else "BLENDER_EEVEE"
    volume = bpy.data.objects.get("RoomVolume")
    if volume:
        volume.hide_render = True
    clay = material("Diagnostic clay", (0.50, 0.50, 0.48, 1), 0.70)
    material_backup: dict[str, list[bpy.types.Material]] = {}
    for obj in scene.objects:
        if obj.type not in {"MESH", "CURVE"} or obj == volume:
            continue
        material_backup[obj.name] = list(obj.data.materials)
        obj.data.materials.clear()
        obj.data.materials.append(clay)
    scene.render.filepath = str(OUTPUT / "02_neutral_clay.png")
    bpy.ops.render.render(write_still=True)
    for obj_name, original_materials in material_backup.items():
        obj = bpy.data.objects.get(obj_name)
        if not obj:
            continue
        obj.data.materials.clear()
        for original in original_materials:
            obj.data.materials.append(original)
    if volume:
        volume.hide_render = False


def render_random_color() -> None:
    scene = bpy.context.scene
    volume = bpy.data.objects.get("RoomVolume")
    if volume:
        volume.hide_render = True
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "RANDOM"
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "WORLD"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_specular_highlight = False
    scene.render.filepath = str(OUTPUT / "01_layout_random_color.png")
    bpy.ops.render.render(write_still=True)
    if volume:
        volume.hide_render = False


def main() -> None:
    clear_scene()
    configure_render()
    mats = make_materials()
    build_architecture(mats)
    build_desks(mats)
    build_equipment(mats)
    build_chair(mats)
    build_shelves_and_clutter(mats)
    build_lighting_and_camera(mats)
    render_random_color()
    render_clay(mats)
    render_final()
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT / "ai_workroom.blend"))
    print(f"AI workroom built successfully: {OUTPUT}")


if __name__ == "__main__":
    main()
