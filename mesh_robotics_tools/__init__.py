# -*- coding: utf-8 -*-
"""
Mesh & Robotics Tools

2 つのツールを 1 つのアドオンにまとめたもの:
  1. Generate Bounding Box : 選択メッシュから URDF/xacro 用バウンディングボックスを生成
  2. Make Solid Manifold   : 任意のメッシュを物理演算向けの閉じた多様体の単一オブジェクトに変換

Blender 2.80 〜 最新系まで、1 つの zip で導入できる。
（Make Solid Manifold の Voxel Remesh 方式は Blender 2.82 以降が必要）
"""

bl_info = {
    "name": "Mesh & Robotics Tools",
    "author": "Jonatan Bijl, et al.",
    "version": (1, 1, 0),
    "blender": (2, 80, 0),
    "location": "View3D > サイドバー(N) > Robotics タブ / Object メニュー / F3 検索",
    "description": "URDF用バウンディングボックス生成と、物理演算向けソリッド化(Make Solid Manifold)",
    "category": "Object",
}

# 再有効化（Reload Scripts）時にサブモジュールを確実に読み直す
if "bpy" in locals():
    import importlib
    if "bounding_box" in locals():
        importlib.reload(bounding_box)   # noqa: F821
    if "make_solid" in locals():
        importlib.reload(make_solid)     # noqa: F821

import bpy

from . import bounding_box
from . import make_solid


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
        s = context.scene.make_solid_settings
        col.prop(s, "method")
        if s.method == 'VOXEL':
            col.prop(s, "voxel_size")
        col.prop(s, "merge_distance")
        col.prop(s, "keep_original")
        col.prop(s, "set_origin_volume")
        col.prop(s, "result_name")
        col.operator(
            make_solid.OBJECT_OT_make_solid_manifold.bl_idname,
            text="Make Solid",
        )


classes = (
    bounding_box.GenerateBoundingBoxesOperator,
    bounding_box.BBX_OT_show_output,
    bounding_box.BBX_OT_copy_output,
    make_solid.MakeSolidSettings,
    make_solid.OBJECT_OT_make_solid_manifold,
    VIEW3D_PT_robotics_tools,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.make_solid_settings = bpy.props.PointerProperty(
        type=make_solid.MakeSolidSettings
    )
    # Object メニューにも追加してアクセスしやすくする
    bpy.types.VIEW3D_MT_object.append(bounding_box.menu_func)
    bpy.types.VIEW3D_MT_object.append(make_solid.menu_func)


def unregister():
    bpy.types.VIEW3D_MT_object.remove(make_solid.menu_func)
    bpy.types.VIEW3D_MT_object.remove(bounding_box.menu_func)
    del bpy.types.Scene.make_solid_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
