# -*- coding: utf-8 -*-
"""
Mesh & Robotics Tools

ロボティクス向けのメッシュ補助ツール集:
  1. Generate Bounding Box : 選択メッシュから URDF/xacro 用バウンディングボックスを生成
  2. Make Solid Manifold   : 任意のメッシュを物理演算向けの閉じた多様体の単一オブジェクトに変換
  3. Mesh to Spheres       : メッシュを球の集合に近似してコレクションに格納
  4. Spheres to xacro      : コレクション内の球から xacro の <collision>(sphere) を出力

Blender 2.80 〜 最新系まで、1 つの zip で導入できる。
（Make Solid Manifold の Voxel Remesh 方式は 2.82 以降では OpenVDB、それ未満は従来Remeshで近似）
"""

bl_info = {
    "name": "Mesh & Robotics Tools",
    "author": "Jonatan Bijl, et al.",
    "version": (1, 2, 0),
    "blender": (2, 80, 0),
    "location": "View3D > サイドバー(N) > Robotics タブ / Object メニュー / F3 検索",
    "description": "URDFバウンディングボックス、物理向けソリッド化、メッシュの球近似(collision)",
    "category": "Object",
}

# 再有効化（Reload Scripts）時にサブモジュールを確実に読み直す
if "bpy" in locals():
    import importlib
    if "bounding_box" in locals():
        importlib.reload(bounding_box)   # noqa: F821
    if "make_solid" in locals():
        importlib.reload(make_solid)     # noqa: F821
    if "spheres" in locals():
        importlib.reload(spheres)        # noqa: F821

import bpy

from . import bounding_box
from . import make_solid
from . import spheres


class VIEW3D_PT_robotics_tools(bpy.types.Panel):
    """3Dビューのサイドバー(Nパネル)に表示するツールパネル"""
    bl_label = "Mesh & Robotics Tools"
    bl_idname = "VIEW3D_PT_robotics_tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Robotics"

    def draw(self, context):
        layout = self.layout

        # --- URDF / Bounding Box ---
        col = layout.column(align=True)
        col.label(text="URDF / Bounding Box")
        col.operator(
            bounding_box.GenerateBoundingBoxesOperator.bl_idname,
            text="Generate Bounding Box",
        )

        layout.separator()

        # --- Make Solid Manifold ---
        col = layout.column(align=True)
        col.label(text="Make Solid Manifold")
        ms = context.scene.make_solid_settings
        col.prop(ms, "method")
        if ms.method == 'VOXEL':
            col.prop(ms, "voxel_size")
        col.prop(ms, "merge_distance")
        col.prop(ms, "keep_original")
        col.prop(ms, "set_origin_volume")
        col.prop(ms, "result_name")
        col.operator(
            make_solid.OBJECT_OT_make_solid_manifold.bl_idname,
            text="Make Solid",
        )

        layout.separator()

        # --- Mesh ⇄ Spheres ---
        col = layout.column(align=True)
        col.label(text="Mesh → Spheres")
        sp = context.scene.mesh_to_spheres_settings
        col.prop(sp, "method")
        col.prop(sp, "spacing")
        col.prop(sp, "radius_scale")
        col.prop(sp, "max_spheres")
        if sp.method == 'MEDIAL':
            col.prop(sp, "coverage")
            col.prop(sp, "min_radius")
        col.operator(
            spheres.OBJECT_OT_mesh_to_spheres.bl_idname,
            text="Mesh to Spheres",
        )

        col = layout.column(align=True)
        col.label(text="Spheres → xacro collision")
        col.prop(sp, "target_collection")
        col.operator(
            spheres.OBJECT_OT_spheres_to_xacro.bl_idname,
            text="Spheres to xacro",
        )


classes = (
    bounding_box.GenerateBoundingBoxesOperator,
    bounding_box.BBX_OT_show_output,
    bounding_box.BBX_OT_copy_output,
    make_solid.MakeSolidSettings,
    make_solid.OBJECT_OT_make_solid_manifold,
    spheres.MeshToSpheresSettings,
    spheres.OBJECT_OT_mesh_to_spheres,
    spheres.SPH_OT_show_output,
    spheres.SPH_OT_copy_output,
    spheres.OBJECT_OT_spheres_to_xacro,
    VIEW3D_PT_robotics_tools,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.make_solid_settings = bpy.props.PointerProperty(
        type=make_solid.MakeSolidSettings
    )
    bpy.types.Scene.mesh_to_spheres_settings = bpy.props.PointerProperty(
        type=spheres.MeshToSpheresSettings
    )
    # Object メニューにも追加してアクセスしやすくする
    bpy.types.VIEW3D_MT_object.append(bounding_box.menu_func)
    bpy.types.VIEW3D_MT_object.append(make_solid.menu_func)
    bpy.types.VIEW3D_MT_object.append(spheres.menu_func)


def unregister():
    bpy.types.VIEW3D_MT_object.remove(spheres.menu_func)
    bpy.types.VIEW3D_MT_object.remove(make_solid.menu_func)
    bpy.types.VIEW3D_MT_object.remove(bounding_box.menu_func)
    del bpy.types.Scene.mesh_to_spheres_settings
    del bpy.types.Scene.make_solid_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
