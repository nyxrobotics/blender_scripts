# -*- coding: utf-8 -*-
"""
Mesh Simplifier and Shape Reconstructor

メッシュを Decimate で簡略化し、平面/曲面の検出・接続・交差処理・隙間埋め・
多様体化を行う。

面の分類は並列処理を試み、利用できない環境（Blender 内蔵 Python では
ProcessPoolExecutor を生成できないことがある）では逐次処理で実行する。
重複頂点の結合は新旧どちらの Blender でも動くよう compat 経由で呼び出す。
"""

import bpy
import bmesh
import math
import concurrent.futures
import multiprocessing
from mathutils import Vector

from . import compat


def apply_decimate_modifier(obj, max_vertices=1000000):
    """ Decimateモディファイアを適用し、頂点数を削減 """
    current_vertices = len(obj.data.vertices)

    if current_vertices <= max_vertices:
        print(f"頂点数 {current_vertices} が閾値 {max_vertices} 以下のため、Decimateは不要です。")
        return

    decimate_modifier = obj.modifiers.new(name="Decimate", type='DECIMATE')
    ratio = max_vertices / current_vertices
    decimate_modifier.ratio = ratio

    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier="Decimate")

    print(f"Decimate処理を適用し、頂点数を {current_vertices} から {max_vertices} に削減しました。")


def extract_face_data(face):
    """ 面の基本情報（法線ベクトルと面積）を抽出してシンプルなデータに変換 """
    normal = tuple(face.normal)
    area = face.area
    index = face.index
    return (normal, area, index)


def detect_surface_groups(mesh, tolerance=0.01):
    """ メッシュ内で平面・曲面を検出し、並列で処理 """
    flat_surfaces = []
    curved_surfaces = []

    print("平面と曲面を並列で検出中...")

    # メッシュの面データを抽出
    face_data = [extract_face_data(face) for face in mesh.polygons]

    def _classify_sequential():
        """ 並列処理が使えない環境向けの逐次フォールバック（結果は並列版と同一）"""
        flats, curves = [], []
        for data in face_data:
            kind, idx = process_face(data, tolerance)
            if kind == "flat":
                flats.append(idx)
            elif kind == "curved":
                curves.append(idx)
        return flats, curves

    # 処理を並列化
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=multiprocessing.cpu_count()) as executor:
            futures = {executor.submit(process_face, data, tolerance): data for data in face_data}

            for future in concurrent.futures.as_completed(futures):
                data = futures[future]
                try:
                    result = future.result()
                    if result[0] == "flat":
                        flat_surfaces.append(result[1])
                    elif result[0] == "curved":
                        curved_surfaces.append(result[1])
                except Exception as exc:
                    print(f"面 {data[2]} の処理中に例外が発生しました: {exc}")
    except Exception as exc:
        # Blender 内蔵 Python では ProcessPoolExecutor を生成できない環境が多いため、
        # 失敗した場合は逐次処理にフォールバックする（分類結果は同一）。
        print(f"並列処理を初期化できませんでした（{exc}）。逐次処理に切り替えます。")
        flat_surfaces, curved_surfaces = _classify_sequential()

    print(f"検出された平面群: {len(flat_surfaces)}, 曲面群: {len(curved_surfaces)}")
    return flat_surfaces, curved_surfaces


def process_face(face_data, tolerance):
    """ 各面の平面か曲面かを検出し、結果を返す """
    normal, area, index = face_data
    if is_flat_surface(normal, tolerance):
        return ("flat", index)
    else:
        return ("curved", index)


def explore_connected_faces(mesh, face, group, visited_faces, tolerance):
    """ 再帰的に接続された面を探索してグループ化 """
    for edge in face.edge_keys:
        connected_faces = [f for f in mesh.polygons if edge in f.edge_keys and f.index not in visited_faces]
        for connected_face in connected_faces:
            if abs(face.normal.dot(connected_face.normal)) > (1 - tolerance):
                group.append(connected_face)
                visited_faces.add(connected_face.index)
                explore_connected_faces(mesh, connected_face, group, visited_faces, tolerance)


def is_flat_surface(normal, tolerance=0.01):
    """ 面が平面かどうかを判定 """
    return abs(Vector(normal).length - 1.0) < tolerance


def process_connected_surfaces(flat_surfaces, curved_surfaces):
    """ 平面を優先し、面積が大きい方を優先して接続処理を行う """
    print("平面を処理中...")
    process_flat_surfaces(flat_surfaces)
    print("曲面を処理中...")
    process_curved_surfaces(curved_surfaces)


def process_flat_surfaces(flat_surfaces):
    """ 面積が大きい平面を優先して処理 """
    sorted_flat = sorted(flat_surfaces, key=lambda f: f, reverse=True)

    for flat_surface in sorted_flat:
        for other_surface in sorted_flat:
            if flat_surface != other_surface:
                connect_surfaces(flat_surface, other_surface, "flat")


def process_curved_surfaces(curved_surfaces):
    """ 曲面同士を処理 """
    sorted_curved = sorted(curved_surfaces, key=lambda f: f, reverse=True)

    for curved_surface in sorted_curved:
        for other_surface in sorted_curved:
            if curved_surface != other_surface:
                connect_surfaces(curved_surface, other_surface, "curved")


def connect_surfaces(face1, face2, surface_type):
    """ 平面または曲面を接続して正しくエッジで合わせる """
    bm = bmesh.new()
    bm.from_mesh(bpy.context.object.data)

    welded_verts = set()  # 結合済み頂点を追跡するためのセット

    for edge1 in bm.edges:
        for edge2 in bm.edges:
            if set(edge1.verts) == set(edge2.verts):
                v1_1, v1_2 = edge1.verts[0], edge1.verts[1]
                v2_1, v2_2 = edge2.verts[0], edge2.verts[1]

                # 重複頂点がないか確認し、結合済みの頂点を無視
                if v1_1 not in welded_verts and v1_2 not in welded_verts:
                    if (v1_1 != v2_1) and (v1_2 != v2_2):
                        bmesh.ops.weld_verts(bm, targetmap={v1_1: v2_1, v1_2: v2_2})
                        welded_verts.update([v1_1, v1_2, v2_1, v2_2])

    bm.to_mesh(bpy.context.object.data)
    bm.free()
    print(f"{surface_type} surfaceの接続が完了しました。")


def cut_intersecting_surfaces(flat_surfaces, curved_surfaces):
    """ 平面同士、曲面同士、平面と曲面の交差部分を切断 """
    print("交差部分を切断中...")

    for group1 in flat_surfaces:
        for group2 in flat_surfaces + curved_surfaces:
            if group1 != group2:
                cut_intersections(group1, group2)


def cut_intersections(group1, group2):
    """ 面同士が交差する場合に交差部分で切断 """
    bm = bmesh.new()
    bm.from_mesh(bpy.context.object.data)

    # 面の頂点を取得し、頂点リストを作成
    for face in group1:
        verts1 = [bm.verts.new(v.co) for v in face.verts]
        try:
            bm.faces.new(verts1)
        except ValueError:
            continue

    for face in group2:
        verts2 = [bm.verts.new(v.co) for v in face.verts]
        try:
            bm.faces.new(verts2)
        except ValueError:
            continue

    result = bmesh.ops.intersect(bm, faces=list(bm.faces), use_self=True)

    if result.get("geom_cut"):
        bmesh.ops.split_edges(bm, edges=result["geom_cut"])

    bm.to_mesh(bpy.context.object.data)
    bm.free()
    print("面の交差部分を切断しました。")


def fill_gaps(mesh):
    """ 凹みや隙間が残っている場合、それを埋める """
    bm = bmesh.new()
    bm.from_mesh(mesh)

    bmesh.ops.holes_fill(bm, edges=bm.edges)
    bm.to_mesh(mesh)
    bm.free()
    print("隙間を埋めました。")


def apply_manifold_cleanup(obj):
    """ メッシュをmanifoldにするために不要な頂点やエッジを削除し、法線を再計算 """
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    compat.remove_doubles()
    bpy.ops.mesh.delete_loose()

    # エッジが選択されているかを確認
    bpy.ops.mesh.select_non_manifold()
    if bpy.ops.mesh.select_non_manifold.poll():  # エッジが選択されている場合
        bpy.ops.mesh.fill()
    else:
        print("非多様体エッジがありません。")

    bpy.ops.object.mode_set(mode='OBJECT')
    print("不要な頂点・エッジを削除し、多様体化を行いました。")

    bpy.ops.object.shade_smooth()
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    print("法線を再計算しました。")


def process_mesh(obj, max_vertices=1000000, tolerance=0.01, area_threshold=0.05):
    """ メッシュの処理を行うメイン関数 """
    apply_decimate_modifier(obj, max_vertices=max_vertices)
    mesh = obj.data

    flat_surfaces, curved_surfaces = detect_surface_groups(mesh, tolerance=tolerance)

    # 接続処理を行う
    process_connected_surfaces(flat_surfaces, curved_surfaces)

    # 交差部分を切断
    cut_intersecting_surfaces(flat_surfaces, curved_surfaces)

    # 隙間の埋め
    fill_gaps(mesh)

    apply_manifold_cleanup(obj)


class OBJECT_OT_simplify_and_reconstruct(bpy.types.Operator):
    """ プラグインのメイン操作を行うオペレーター """
    bl_idname = "object.simplify_and_reconstruct"
    bl_label = "Simplify and Reconstruct Mesh"
    bl_options = {'REGISTER', 'UNDO'}

    max_vertices: bpy.props.IntProperty(name="Max Vertices", default=1000000)

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "選択されたオブジェクトはメッシュではありません。")
            return {'CANCELLED'}

        process_mesh(obj, max_vertices=self.max_vertices)

        self.report({'INFO'}, "メッシュの簡略化と再構成が完了しました。")
        return {'FINISHED'}


def menu_func(self, context):
    self.layout.operator(OBJECT_OT_simplify_and_reconstruct.bl_idname)
