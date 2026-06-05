# -*- coding: utf-8 -*-
"""
Generate Bounding Box (URDF/xacro 出力)

選択メッシュごとにバウンディングボックスを生成し、ROS(URDF/xacro) 向けの
<origin> / <geometry> タグを出力する。

出力は以下の 3 か所に同時に出される（内容は同一）:
  - システムコンソール（従来どおり print）
  - クリップボード（実行直後にそのまま貼り付け可能）
  - テキストデータブロック "bounding_box_urdf.xacro"（テキストエディタで閲覧/編集可）
さらに、実行後にプレビュー用のポップアップウィンドウを表示する。

元スクリプト: bbx.py / author: Jonatan Bijl
バウンディングボックスの計算・XML の内容は元のまま変更していません。
"""

import bpy
import mathutils
import math
from bpy.props import StringProperty

# 直近の出力（ポップアップ/再コピー用）
_LAST_OUTPUT = ""

# 出力を書き込むテキストデータブロック名
TEXT_BLOCK_NAME = "bounding_box_urdf.xacro"


def main(context, prefix):
    # make a list of the selected objects of type 'mesh'
    objs = [obj for obj in context.selected_objects if obj.type == 'MESH']
    generated_objs = []
    lines = []

    bpy.ops.object.select_all(action='DESELECT')

    for obj in objs:
        scale = obj.scale

        minx = obj.bound_box[0][0] * scale.x
        maxx = obj.bound_box[4][0] * scale.x
        miny = obj.bound_box[0][1] * scale.y
        maxy = obj.bound_box[2][1] * scale.y
        minz = obj.bound_box[0][2] * scale.z
        maxz = obj.bound_box[1][2] * scale.z
        dx = maxx - minx
        dy = maxy - miny
        dz = maxz - minz

        new_name = f'{prefix}{obj.name}'

        loc = mathutils.Vector(((minx + 0.5 * dx), (miny + 0.5 * dy), (minz + 0.5 * dz)))
        loc.rotate(obj.rotation_euler)
        loc = loc + obj.location

        # Convert Blender coordinates to ROS coordinates by rotating -90 degrees around Z-axis
        rotation_matrix = mathutils.Matrix.Rotation(-math.radians(90), 4, 'Z')
        ros_loc = rotation_matrix @ loc

        # Also rotate the orientation to match ROS coordinate system
        ros_rotation_euler = obj.rotation_euler.copy()
        ros_rotation_euler.rotate(rotation_matrix)

        # Adjust yaw by +90 degrees (+1.5708 radians)
        ros_rotation_euler.z += math.radians(90)

        # Swap the x and y dimensions to match the new orientation
        adjusted_dx = dy
        adjusted_dy = dx

        # Create the cube without rotation
        bpy.ops.mesh.primitive_cube_add(location=loc)
        new_obj = bpy.context.object

        new_obj.name = new_name
        new_obj.dimensions = mathutils.Vector((dx, dy, dz))

        # Apply the rotation after creation
        new_obj.rotation_euler = obj.rotation_euler

        generated_objs.append(new_obj)

        # Build the output in the specified format with ROS coordinates and adjusted orientation
        block = [
            f'  <origin xyz="{ros_loc.x:.4f} {ros_loc.y:.4f} {ros_loc.z:.4f}" rpy="{ros_rotation_euler.x:.4f} {ros_rotation_euler.y:.4f} {ros_rotation_euler.z:.4f}"/>',
            f'  <geometry>',
            f'    <box size="{adjusted_dx:.4f} {adjusted_dy:.4f} {dz:.4f}"/>',
            f'  </geometry>',
        ]
        for line in block:
            print(line)  # 従来どおりコンソールにも出力
        lines.extend(block)

    for obj in generated_objs:
        obj.select_set(True)

    return "\n".join(lines)


def _write_to_text_block(text):
    """出力をテキストデータブロックへ書き込む（テキストエディタで開ける）。"""
    txt = bpy.data.texts.get(TEXT_BLOCK_NAME)
    if txt is None:
        txt = bpy.data.texts.new(TEXT_BLOCK_NAME)
    txt.clear()
    txt.write(text)
    return txt


class BBX_OT_copy_output(bpy.types.Operator):
    """直近の出力をもう一度クリップボードへコピー"""
    bl_idname = "object.bbx_copy_output"
    bl_label = "Copy to Clipboard"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        context.window_manager.clipboard = _LAST_OUTPUT
        self.report({'INFO'}, "クリップボードにコピーしました。")
        return {'FINISHED'}


class BBX_OT_show_output(bpy.types.Operator):
    """直近の出力をポップアップウィンドウで表示"""
    bl_idname = "object.bbx_show_output"
    bl_label = "Bounding Box URDF / xacro"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=560)

    def draw(self, context):
        layout = self.layout
        layout.label(text="クリップボードにコピー済み / Text: '%s'" % TEXT_BLOCK_NAME, icon='TEXT')
        layout.operator(BBX_OT_copy_output.bl_idname, icon='COPYDOWN')
        box = layout.box()
        col = box.column(align=True)
        if _LAST_OUTPUT.strip():
            for line in _LAST_OUTPUT.split("\n"):
                # ラベルは先頭の空白を詰めるため、インデントは "." で可視化
                indent = len(line) - len(line.lstrip(" "))
                shown = ("." * indent) + line.lstrip(" ") if indent else line
                col.label(text=shown if shown else " ")
        else:
            col.label(text="(出力はありません)")


class GenerateBoundingBoxesOperator(bpy.types.Operator):
    """Create a bounding cube object for each selected object and output URDF/xacro"""
    bl_idname = "object.generate_bounding_boxes"
    bl_label = "Generate Bounding Box"
    bl_options = {'REGISTER', 'UNDO'}

    name_prefix: StringProperty(
        name='name_prefix',
        description='The name prefix for the new objects',
        default='UCX_',
    )

    @classmethod
    def poll(cls, context):
        return len(context.selected_objects) > 0

    def execute(self, context):
        global _LAST_OUTPUT
        text = main(context, self.name_prefix)
        _LAST_OUTPUT = text

        if text.strip():
            # クリップボード & テキストデータブロックへ出力
            context.window_manager.clipboard = text
            _write_to_text_block(text)
            self.report(
                {'INFO'},
                "URDF/xacro をクリップボードと Text '%s' に出力しました。" % TEXT_BLOCK_NAME,
            )
            # プレビューウィンドウを表示
            bpy.ops.object.bbx_show_output('INVOKE_DEFAULT')
        else:
            self.report({'WARNING'}, "メッシュオブジェクトが選択されていません。")

        return {'FINISHED'}


def menu_func(self, context):
    self.layout.operator(GenerateBoundingBoxesOperator.bl_idname, text="Generate Bounding Box")
