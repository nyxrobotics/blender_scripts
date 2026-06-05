# -*- coding: utf-8 -*-
"""
Mesh & Robotics Tools

2 つのツールを 1 つのアドオンにまとめたもの:
  1. Generate Bounding Box        : 選択メッシュから URDF/xacro 用バウンディングボックスを生成
  2. Simplify and Reconstruct Mesh : メッシュ簡略化・形状再構成

Blender 2.80 〜 最新系まで、1 つの zip で導入できる。
"""

bl_info = {
    "name": "Mesh & Robotics Tools",
    "author": "Jonatan Bijl, et al.",
    "version": (1, 0, 0),
    "blender": (2, 80, 0),
    "location": "View3D > サイドバー(N) > Robotics タブ / Object メニュー / F3 検索",
    "description": "URDF用バウンディングボックス生成と、メッシュ簡略化・再構成",
    "category": "Object",
}

# 再有効化（Reload Scripts）時にサブモジュールを確実に読み直す
if "bpy" in locals():
    import importlib
    if "compat" in locals():
        importlib.reload(compat)             # noqa: F821
    if "bounding_box" in locals():
        importlib.reload(bounding_box)       # noqa: F821
    if "mesh_reconstructor" in locals():
        importlib.reload(mesh_reconstructor)  # noqa: F821

import bpy

from . import compat            # noqa: F401  (互換ヘルパー: サブモジュールから利用)
from . import bounding_box
from . import mesh_reconstructor


class VIEW3D_PT_robotics_tools(bpy.types.Panel):
    """3Dビューのサイドバー(Nパネル)に表示するツールパネル"""
    bl_label = "Mesh & Robotics Tools"
    bl_idname = "VIEW3D_PT_robotics_tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Robotics"

    def draw(self, context):
        layout = self.layout

        col = layout.column(align=True)
        col.label(text="URDF / Bounding Box")
        col.operator(
            bounding_box.GenerateBoundingBoxesOperator.bl_idname,
            text="Generate Bounding Box",
        )

        layout.separator()

        col = layout.column(align=True)
        col.label(text="Mesh Reconstruct")
        col.operator(
            mesh_reconstructor.OBJECT_OT_simplify_and_reconstruct.bl_idname,
            text="Simplify & Reconstruct",
        )


classes = (
    bounding_box.GenerateBoundingBoxesOperator,
    bounding_box.BBX_OT_show_output,
    bounding_box.BBX_OT_copy_output,
    mesh_reconstructor.OBJECT_OT_simplify_and_reconstruct,
    VIEW3D_PT_robotics_tools,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    # Object メニューにも追加してアクセスしやすくする
    bpy.types.VIEW3D_MT_object.append(bounding_box.menu_func)
    bpy.types.VIEW3D_MT_object.append(mesh_reconstructor.menu_func)


def unregister():
    bpy.types.VIEW3D_MT_object.remove(mesh_reconstructor.menu_func)
    bpy.types.VIEW3D_MT_object.remove(bounding_box.menu_func)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
