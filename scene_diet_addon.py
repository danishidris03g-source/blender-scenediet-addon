bl_info = {
    "name": "SceneDiet",
    "author": "SceneDiet",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > SceneDiet",
    "description": "Scan scene for orphan data, duplicates, and mesh bloat",
    "category": "Mesh",
}

import bpy  # type: ignore[import-unresolved]
import re
import datetime
import json
from bpy_extras.io_utils import ExportHelper  # type: ignore[import-unresolved]


class SCENEDIET_UL_items(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            label = item.name
            if item.details:
                label = f"{label}  ({item.details})"
            row.label(text=label, icon=icon)
        elif self.layout_type == "GRID":
            row.alignment = "CENTER"
            label = item.name
            if item.details:
                label = f"{label} ({item.details})"
            row.label(text=label, icon=icon)
        op = row.operator("scenediet.delete_item", text="", icon="TRASH")
        op.item_name = item.name
        op.collection_type = ""


class SceneDietItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()
    details: bpy.props.StringProperty(default="")


def on_preset_change(self, context):
    if self.optimization_preset == "ARCHVIZ":
        self.heavy_mesh_threshold = 500000
    elif self.optimization_preset == "GAMEDEV":
        self.heavy_mesh_threshold = 20000


class SceneDietResults(bpy.types.PropertyGroup):
    scan_done: bpy.props.BoolProperty(default=False)

    orphan_materials: bpy.props.CollectionProperty(type=SceneDietItem)
    orphan_textures: bpy.props.CollectionProperty(type=SceneDietItem)
    orphan_node_groups: bpy.props.CollectionProperty(type=SceneDietItem)
    duplicate_blocks: bpy.props.CollectionProperty(type=SceneDietItem)
    duplicate_suffixes: bpy.props.CollectionProperty(type=SceneDietItem)
    meshes_zero_poly: bpy.props.CollectionProperty(type=SceneDietItem)
    meshes_extreme_poly: bpy.props.CollectionProperty(type=SceneDietItem)
    oversized_textures: bpy.props.CollectionProperty(type=SceneDietItem)

    active_oversized_tex_index: bpy.props.IntProperty(default=0)

    expand_orphans: bpy.props.BoolProperty(name="Orphans", default=False)
    expand_duplicates: bpy.props.BoolProperty(name="Duplicates", default=False)
    expand_suffixes: bpy.props.BoolProperty(name="Suffix Duplicates", default=False)
    expand_heavy: bpy.props.BoolProperty(name="Heavy Meshes", default=False)
    expand_zero: bpy.props.BoolProperty(name="Zero Poly Meshes", default=False)
    expand_oversized: bpy.props.BoolProperty(name="Oversized Textures", default=False)
    heavy_mesh_threshold: bpy.props.IntProperty(
        name="Heavy Mesh Threshold",
        default=100000,
        min=1000,
        max=5000000,
        description="Polygon count threshold to flag heavy meshes",
    )
    optimization_preset: bpy.props.EnumProperty(
        name="Optimization Preset",
        items=[
            ("CUSTOM", "Custom", "User-defined settings"),
            ("ARCHVIZ", "ArchViz", "High-poly architectural visualization (500k limit)"),
            ("GAMEDEV", "Game Dev", "Optimized real-time game asset limit (20k limit)"),
        ],
        default="CUSTOM",
        update=on_preset_change,
    )
    backup_before_purge: bpy.props.BoolProperty(
        name="Backup Before Purge",
        default=True,
        description="Automatically create a backup copy of the blend file before running bulk purge operations",
    )
    protect_prefixes: bpy.props.StringProperty(
        name="Protect Prefixes",
        description="Comma-separated name prefixes to protect from purging (e.g. DOT, PROTECT)",
        default="DOT",
    )


# pyright: reportInvalidTypeForm=false
def get_image_memory_mb(image):
    width, height = image.size
    channels = image.channels
    bytes_per_channel = 4.0 if image.is_float else 1.0
    bytes_total = width * height * channels * bytes_per_channel
    return bytes_total / (1024.0 * 1024.0)


def scan_scene_bloat(context):
    results = {
        "orphan_materials": [],
        "orphan_textures": [],
        "orphan_node_groups": [],
        "duplicate_data_blocks": [],
        "meshes_zero_poly": [],
        "meshes_extreme_poly": [],
        "oversized_textures": [],
    }

    for mat in bpy.data.materials:
        if mat.users == 0:
            results["orphan_materials"].append(mat.name)

    orphan_imgs = []
    for img in bpy.data.images:
        if img.users == 0:
            mb = get_image_memory_mb(img)
            orphan_imgs.append((img.name, mb))
    orphan_imgs.sort(key=lambda x: x[1], reverse=True)
    for name, mb in orphan_imgs:
        results["orphan_textures"].append(f"{name} ({mb:.1f} MB)")

    for ng in bpy.data.node_groups:
        if ng.users == 0:
            results["orphan_node_groups"].append(ng.name)

    duplicate_textures = []
    for block_type, data_list in [
        ("material", bpy.data.materials),
        ("texture", bpy.data.images),
        ("node_group", bpy.data.node_groups),
        ("mesh", bpy.data.meshes),
        ("object", bpy.data.objects),
        ("scene", bpy.data.scenes),
        ("world", bpy.data.worlds),
    ]:
        for item in data_list:
            if ".00" in item.name:
                if block_type == "texture":
                    mb = get_image_memory_mb(item)
                    duplicate_textures.append((item.name, mb))
                else:
                    results["duplicate_data_blocks"].append((block_type, item.name))
    duplicate_textures.sort(key=lambda x: x[1], reverse=True)
    for name, mb in duplicate_textures:
        results["duplicate_data_blocks"].append(("texture", name))

    for img in bpy.data.images:
        if img.size[0] > 2048 or img.size[1] > 2048:
            results["oversized_textures"].append((img.name, f"{img.size[0]} x {img.size[1]}"))

    for mesh in bpy.data.meshes:
        poly_count = len(mesh.polygons)
        if poly_count == 0:
            results["meshes_zero_poly"].append(mesh.name)
        elif poly_count > context.scene.scenediet.heavy_mesh_threshold:
            results["meshes_extreme_poly"].append((mesh.name, poly_count))

    return results


def _store_results(context, results):
    s = context.scene.scenediet
    s.scan_done = True

    mappings = [
        ("orphan_materials", "orphan_materials", None),
        ("orphan_textures", "orphan_textures", None),
        ("orphan_node_groups", "orphan_node_groups", None),
        ("duplicate_blocks", "duplicate_data_blocks", 1),
        ("meshes_zero_poly", "meshes_zero_poly", None),
        ("meshes_extreme_poly", "meshes_extreme_poly", 0),
        ("oversized_textures", "oversized_textures", 0),
    ]

    for prop_name, result_key, name_idx in mappings:
        col = getattr(s, prop_name)
        col.clear()
        for entry in results[result_key]:
            if isinstance(entry, tuple):
                if name_idx is not None:
                    name = entry[name_idx]
                else:
                    name = entry[1]
            else:
                name = entry
            if not isinstance(name, str):
                continue
            item = col.add()
            item.name = name
            if prop_name == "oversized_textures" and isinstance(entry, tuple) and len(entry) > 1:
                item.details = entry[1]
            elif prop_name == "duplicate_blocks" and isinstance(entry, tuple):
                item.details = entry[0]

    suffix_results = find_duplicate_suffixes()
    s.duplicate_suffixes.clear()
    for key in ["materials", "images", "node_groups", "meshes"]:
        for name in suffix_results[key]:
            item = s.duplicate_suffixes.add()
            item.name = name
            item.details = key


def get_audit_report(context):
    s = context.scene.scenediet
    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "blend_file": bpy.path.basename(bpy.data.filepath),
        "polygon_threshold": s.heavy_mesh_threshold,
        "optimization_preset": s.optimization_preset,
        "orphan_materials": [item.name for item in s.orphan_materials],
        "orphan_textures": [item.name for item in s.orphan_textures],
        "orphan_node_groups": [item.name for item in s.orphan_node_groups],
        "duplicate_blocks": [item.name for item in s.duplicate_blocks],
        "duplicate_suffixes": [item.name for item in s.duplicate_suffixes],
        "meshes_zero_poly": [item.name for item in s.meshes_zero_poly],
        "meshes_extreme_poly": [item.name for item in s.meshes_extreme_poly],
        "oversized_textures": [item.name for item in s.oversized_textures],
    }


DUPLICATE_SUFFIX_RE = re.compile(r"^(.*?)\.\d{3,}$")


def find_duplicate_suffixes():
    results = {
        "materials": [],
        "images": [],
        "node_groups": [],
        "meshes": [],
    }
    for data_list, key in [
        (bpy.data.materials, "materials"),
        (bpy.data.images, "images"),
        (bpy.data.node_groups, "node_groups"),
        (bpy.data.meshes, "meshes"),
    ]:
        names = {item.name for item in data_list}
        for item in data_list:
            match = DUPLICATE_SUFFIX_RE.match(item.name)
            if match and match.group(1) in names:
                results[key].append(item.name)
    return results


def is_protected(name, prefixes_str):
    if not prefixes_str:
        return False
    prefixes = [p.strip().upper() for p in prefixes_str.split(",") if p.strip()]
    return any(name.upper().startswith(p) for p in prefixes)


class SCENEDIET_OT_export_report(bpy.types.Operator, ExportHelper):
    bl_idname = "scenediet.export_report"
    bl_label = "Export Audit Report"
    bl_description = "Export scan results as a JSON audit report"
    bl_options = {"REGISTER"}

    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        report = get_audit_report(context)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        self.report({"INFO"}, f"Exported report to {self.filepath}")
        return {"FINISHED"}


class SCENEDIET_OT_purge_duplicates(bpy.types.Operator):
    bl_idname = "scenediet.purge_duplicates"
    bl_label = "Purge Duplicates"
    bl_description = "Remove duplicate data-blocks with suffixes (.001, .002, etc.) that have a base copy"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        s = context.scene.scenediet
        if s.backup_before_purge:
            bpy.ops.wm.save_as_mainfile(copy=True)
        count = 0
        skipped = 0
        for data_list in [
            bpy.data.materials,
            bpy.data.images,
            bpy.data.node_groups,
            bpy.data.meshes,
        ]:
            for item in list(data_list):
                if is_protected(item.name, s.protect_prefixes):
                    skipped += 1
                    continue
                match = DUPLICATE_SUFFIX_RE.match(item.name)
                if match and item.users == 0:
                    data_list.remove(item)
                    count += 1
        msg = f"SceneDiet purged {count} duplicate data-block(s)"
        if skipped:
            msg += f", {skipped} protected"
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class SCENEDIET_OT_scan(bpy.types.Operator):
    bl_idname = "scenediet.scan_scene"
    bl_label = "Scan Scene"
    bl_description = "Scan for orphan data, duplicates, and mesh bloat"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        results = scan_scene_bloat(context)
        _store_results(context, results)
        total = sum(len(v) for v in results.values())
        self.report(
            {"INFO"},
            f"SceneDiet scan complete: {total} bloat items found",
        )
        return {"FINISHED"}


class SCENEDIET_OT_highlight_bloat(bpy.types.Operator):
    bl_idname = "scenediet.highlight_bloat_objects"
    bl_label = "Highlight Bloat"
    bl_description = "Select objects using heavy meshes or duplicate data-blocks"
    bl_options = {"REGISTER"}

    def execute(self, context):
        bpy.ops.object.select_all(action="DESELECT")

        bloat_objs = []
        for obj in bpy.data.objects:
            is_bloat = False

            if obj.type == "MESH" and len(obj.data.polygons) > context.scene.scenediet.heavy_mesh_threshold:
                is_bloat = True

            if DUPLICATE_SUFFIX_RE.match(obj.name):
                is_bloat = True

            if obj.type == "MESH" and DUPLICATE_SUFFIX_RE.match(obj.data.name):
                is_bloat = True

            for mat_slot in obj.material_slots:
                if mat_slot.material and DUPLICATE_SUFFIX_RE.match(mat_slot.material.name):
                    is_bloat = True
                    break

            if is_bloat:
                bloat_objs.append(obj)

        for obj in bloat_objs:
            obj.select_set(True)

        if bloat_objs:
            context.view_layer.objects.active = bloat_objs[-1]
            self.report({"INFO"}, f"Highlighted {len(bloat_objs)} bloat object(s)")
        else:
            self.report({"INFO"}, "No bloat objects found")

        return {"FINISHED"}


class SCENEDIET_OT_delete_item(bpy.types.Operator):
    bl_idname = "scenediet.delete_item"
    bl_label = "Delete Item"
    bl_description = "Delete a specific item from a bloat list"
    bl_options = {"REGISTER", "UNDO"}

    item_name: bpy.props.StringProperty()
    collection_type: bpy.props.StringProperty()

    def execute(self, context):
        s = context.scene.scenediet
        name = self.item_name
        col_type = self.collection_type

        bpy_data_map = {
            "orphan_materials": [bpy.data.materials],
            "orphan_textures": [bpy.data.images],
            "orphan_node_groups": [bpy.data.node_groups],
            "duplicate_blocks": [bpy.data.materials, bpy.data.images, bpy.data.node_groups, bpy.data.meshes],
            "duplicate_suffixes": [bpy.data.materials, bpy.data.images, bpy.data.node_groups, bpy.data.meshes],
            "meshes_zero_poly": [bpy.data.meshes],
            "meshes_extreme_poly": [bpy.data.meshes],
        }

        data_lists = bpy_data_map.get(col_type, [])
        if not data_lists:
            data_lists = [bpy.data.materials, bpy.data.images, bpy.data.node_groups, bpy.data.meshes]

        removed_from_bpy = False

        for data_list in data_lists:
            item = None
            for d in data_list:
                if d.name == name:
                    item = d
                    break
            if item is not None:
                if item.users == 0:
                    data_list.remove(item)
                    removed_from_bpy = True
                else:
                    self.report(
                        {"WARNING"},
                        f"'{name}' has {item.users} user(s) — not deleted",
                    )
                    return {"CANCELLED"}
                break

        if col_type:
            col = getattr(s, col_type, None)
        else:
            col = None
            for prop_name in [
                "orphan_materials", "orphan_textures", "orphan_node_groups",
                "duplicate_blocks", "duplicate_suffixes",
                "meshes_zero_poly", "meshes_extreme_poly",
                "oversized_textures",
            ]:
                candidate = getattr(s, prop_name, None)
                if candidate is not None:
                    for item in candidate:
                        if item.name == name:
                            col = candidate
                            break
                    if col is not None:
                        break

        if col is not None:
            idx = col.find(name)
            if idx >= 0:
                col.remove(idx)

        if removed_from_bpy:
            self.report({"INFO"}, f"Deleted '{name}'")
        else:
            self.report({"WARNING"}, f"'{name}' not found in bpy.data")

        return {"FINISHED"}


class SCENEDIET_OT_select_heavy_mesh(bpy.types.Operator):
    bl_idname = "scenediet.select_heavy_mesh"
    bl_label = "Select"
    bl_description = "Select this heavy mesh in the viewport"
    bl_options = {"REGISTER"}

    mesh_name: bpy.props.StringProperty()

    def execute(self, context):
        mesh = bpy.data.meshes.get(self.mesh_name)
        if not mesh:
            self.report({"WARNING"}, f"Mesh '{self.mesh_name}' not found")
            return {"CANCELLED"}

        bpy.ops.object.select_all(action="DESELECT")
        selected = 0
        for obj in bpy.data.objects:
            if obj.type == "MESH" and obj.data == mesh:
                obj.select_set(True)
                selected += 1
        if selected:
            self.report(
                {"INFO"},
                f"Selected {selected} object(s) using '{self.mesh_name}'",
            )
        else:
            self.report(
                {"WARNING"},
                f"No objects using '{self.mesh_name}' found in scene",
            )
        return {"FINISHED"}


class SCENEDIET_OT_select_item(bpy.types.Operator):
    bl_idname = "scenediet.select_item"
    bl_label = "Select"
    bl_description = "Select objects using this data-block in the viewport"
    bl_options = {"REGISTER"}

    item_name: bpy.props.StringProperty()
    item_type: bpy.props.StringProperty()

    def execute(self, context):
        type_singular = {
            "mesh": "mesh",
            "materials": "material",
            "material": "material",
            "image": "image",
            "images": "image",
            "node_group": "node_group",
            "node_groups": "node_group",
        }
        item_type = type_singular.get(self.item_type, self.item_type)

        type_map = {
            "mesh": bpy.data.meshes,
            "material": bpy.data.materials,
            "image": bpy.data.images,
            "node_group": bpy.data.node_groups,
        }
        data_list = type_map.get(item_type)
        if data_list is None:
            self.report({"WARNING"}, f"Unknown type: {self.item_type}")
            return {"CANCELLED"}

        item = data_list.get(self.item_name)
        if item is None:
            self.report({"WARNING"}, f"'{self.item_name}' not found")
            return {"CANCELLED"}

        bpy.ops.object.select_all(action="DESELECT")
        selected = 0

        if item_type == "mesh":
            for obj in bpy.data.objects:
                if obj.type == "MESH" and obj.data == item:
                    obj.select_set(True)
                    selected += 1
        elif item_type == "material":
            for obj in bpy.data.objects:
                for slot in obj.material_slots:
                    if slot.material == item:
                        obj.select_set(True)
                        selected += 1
                        break
        elif item_type == "image":
            for obj in bpy.data.objects:
                for slot in obj.material_slots:
                    mat = slot.material
                    if mat and mat.node_tree:
                        for node in mat.node_tree.nodes:
                            if node.type == "TEX_IMAGE" and node.image == item:
                                obj.select_set(True)
                                selected += 1
                                break
                if obj.select_get():
                    continue
        elif item_type == "node_group":
            for obj in bpy.data.objects:
                for slot in obj.material_slots:
                    mat = slot.material
                    if mat and mat.node_tree and mat.node_tree.name == self.item_name:
                        obj.select_set(True)
                        selected += 1
                        break
                if obj.select_get():
                    continue

        if selected:
            self.report(
                {"INFO"},
                f"Selected {selected} object(s) using '{self.item_name}'",
            )
        else:
            self.report(
                {"WARNING"},
                f"No objects using '{self.item_name}' found",
            )
        return {"FINISHED"}


class SCENEDIET_OT_purge_orphans(bpy.types.Operator):
    bl_idname = "scenediet.purge_orphans"
    bl_label = "Purge Orphans"
    bl_description = "Remove orphan materials, textures, and node groups"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        s = context.scene.scenediet
        if s.backup_before_purge:
            bpy.ops.wm.save_as_mainfile(copy=True)
        count = 0
        skipped = 0
        for data_list in [bpy.data.materials, bpy.data.images, bpy.data.node_groups]:
            for item in list(data_list):
                if is_protected(item.name, s.protect_prefixes):
                    skipped += 1
                    continue
                if item.users == 0:
                    data_list.remove(item)
                    count += 1
        msg = f"SceneDiet purged {count} orphan data-block(s)"
        if skipped:
            msg += f", {skipped} protected"
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class SCENEDIET_PT_main_panel(bpy.types.Panel):
    bl_label = "SceneDiet"
    bl_idname = "SCENEDIET_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "SceneDiet"

    def draw(self, context):
        layout = self.layout
        s = context.scene.scenediet

        layout.prop(s, "optimization_preset", text="Preset")
        layout.prop(s, "heavy_mesh_threshold")
        layout.prop(s, "backup_before_purge")
        layout.operator("scenediet.scan_scene", icon="VIEW3D")
        layout.operator("scenediet.purge_orphans", icon="TRASH")
        layout.operator("scenediet.purge_duplicates", icon="GREASEPENCIL")
        layout.operator("scenediet.highlight_bloat_objects", icon="VIEWZOOM")
        if s.scan_done:
            layout.operator("scenediet.export_report", icon="EXPORT")

        layout.separator()
        layout.prop(s, "protect_prefixes", text="Protect Prefixes")

        if not s.scan_done:
            return

        has_orphans = bool(s.orphan_materials or s.orphan_textures or s.orphan_node_groups)
        if has_orphans:
            layout.prop(s, "expand_orphans", toggle=True, icon="FILE_REFRESH")
            if s.expand_orphans:
                if s.orphan_materials:
                    layout.label(text=f"Materials ({len(s.orphan_materials)}):")
                    for item in s.orphan_materials:
                        row = layout.row(align=True)
                        row.label(text=f"  {item.name}", icon="MATERIAL")
                        op = row.operator(
                            "scenediet.select_item",
                            text="Select",
                            icon="VIEWZOOM",
                        )
                        op.item_name = item.name
                        op.item_type = "material"
                if s.orphan_textures:
                    layout.label(text=f"Textures ({len(s.orphan_textures)}):")
                    for item in s.orphan_textures:
                        row = layout.row(align=True)
                        row.label(text=f"  {item.name}", icon="IMAGE_DATA")
                        op = row.operator(
                            "scenediet.select_item",
                            text="Select",
                            icon="VIEWZOOM",
                        )
                        op.item_name = item.name
                        op.item_type = "image"
                if s.orphan_node_groups:
                    layout.label(text=f"Node Groups ({len(s.orphan_node_groups)}):")
                    for item in s.orphan_node_groups:
                        row = layout.row(align=True)
                        row.label(text=f"  {item.name}", icon="NODETREE")
                        op = row.operator(
                            "scenediet.select_item",
                            text="Select",
                            icon="VIEWZOOM",
                        )
                        op.item_name = item.name
                        op.item_type = "node_group"

        if s.duplicate_blocks:
            layout.prop(s, "expand_duplicates", toggle=True, icon="FILE_REFRESH")
            if s.expand_duplicates:
                layout.label(text=f"Duplicates ({len(s.duplicate_blocks)}):")
                for item in s.duplicate_blocks:
                    row = layout.row(align=True)
                    row.label(text=f"  {item.name}", icon="GREASEPENCIL")
                    op = row.operator(
                        "scenediet.select_item",
                        text="Select",
                        icon="VIEWZOOM",
                    )
                    op.item_name = item.name
                    op.item_type = item.details

        if s.duplicate_suffixes:
            layout.prop(s, "expand_suffixes", toggle=True, icon="FILE_REFRESH")
            if s.expand_suffixes:
                layout.label(text=f"Suffix Duplicates ({len(s.duplicate_suffixes)}):")
                for item in s.duplicate_suffixes:
                    row = layout.row(align=True)
                    row.label(text=f"  {item.name}", icon="GREASEPENCIL")
                    op = row.operator(
                        "scenediet.select_item",
                        text="Select",
                        icon="VIEWZOOM",
                    )
                    op.item_name = item.name
                    op.item_type = item.details

        if s.meshes_zero_poly:
            layout.prop(s, "expand_zero", toggle=True, icon="FILE_REFRESH")
            if s.expand_zero:
                layout.label(text=f"Zero Poly Meshes ({len(s.meshes_zero_poly)}):")
                for item in s.meshes_zero_poly:
                    row = layout.row(align=True)
                    row.label(text=f"  {item.name}", icon="MESH_DATA")
                    op = row.operator(
                        "scenediet.select_item",
                        text="Select",
                        icon="VIEWZOOM",
                    )
                    op.item_name = item.name
                    op.item_type = "mesh"

        if s.meshes_extreme_poly:
            layout.prop(s, "expand_heavy", toggle=True, icon="FILE_REFRESH")
            if s.expand_heavy:
                layout.label(text=f"Heavy Meshes ({len(s.meshes_extreme_poly)}):")
                for item in s.meshes_extreme_poly:
                    row = layout.row(align=True)
                    row.label(text=f"  {item.name}", icon="MESH_DATA")
                    op = row.operator(
                        "scenediet.select_heavy_mesh",
                        text="Select",
                        icon="VIEWZOOM",
                    )
                    op.mesh_name = item.name

        if s.oversized_textures:
            layout.prop(s, "expand_oversized", toggle=True, icon="IMAGE_DATA")
            if s.expand_oversized:
                layout.label(text=f"Oversized Textures ({len(s.oversized_textures)}):")
                layout.template_list(
                    "SCENEDIET_UL_items", "oversized_textures", s, "oversized_textures",
                    active_dataptr=s, active_propname="active_oversized_tex_index",
                    maxrows=6, rows=4, type="DEFAULT", icon="IMAGE_DATA",
                )


classes = (
    SceneDietItem,
    SceneDietResults,
    SCENEDIET_UL_items,
    SCENEDIET_OT_export_report,
    SCENEDIET_OT_select_item,
    SCENEDIET_OT_scan,
    SCENEDIET_OT_purge_orphans,
    SCENEDIET_OT_purge_duplicates,
    SCENEDIET_OT_highlight_bloat,
    SCENEDIET_OT_delete_item,
    SCENEDIET_OT_select_heavy_mesh,
    SCENEDIET_PT_main_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.scenediet = bpy.props.PointerProperty(type=SceneDietResults)


def unregister():
    del bpy.types.Scene.scenediet
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
