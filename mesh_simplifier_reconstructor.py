bl_info = {
    "name": "Mesh Simplifier and Shape Reconstructor",
    "blender": (2, 82, 0),
    "category": "Object",
}

import bpy
import bmesh
import mathutils
import math

def apply_decimate_modifier(obj, max_vertices=10000):
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

def detect_surface_groups(mesh, tolerance=0.01):
    """ メッシュ内で平面・曲面を検出し、グルーピング """
    flat_surfaces = []
    curved_surfaces = []
    visited_faces = set()

    print("平面と曲面を検出中...")

    for face in mesh.polygons:
        if face.index not in visited_faces:
            if is_flat_surface(face, tolerance):
                group = [face]
                visited_faces.add(face.index)
                explore_connected_faces(mesh, face, group, visited_faces, tolerance)
                flat_surfaces.append(group)
            else:
                group = [face]
                visited_faces.add(face.index)
                explore_connected_faces(mesh, face, group, visited_faces, tolerance)
                curved_surfaces.append(group)

    print(f"検出された平面群: {len(flat_surfaces)}, 曲面群: {len(curved_surfaces)}")
    return flat_surfaces, curved_surfaces

def explore_connected_faces(mesh, face, group, visited_faces, tolerance):
    """ 再帰的に接続された面を探索してグループ化 """
    for edge in face.edge_keys:
        connected_faces = [f for f in mesh.polygons if edge in f.edge_keys and f.index not in visited_faces]
        for connected_face in connected_faces:
            if abs(face.normal.dot(connected_face.normal)) > (1 - tolerance):
                group.append(connected_face)
                visited_faces.add(connected_face.index)
                explore_connected_faces(mesh, connected_face, group, visited_faces, tolerance)

def is_flat_surface(face, tolerance=0.01):
    """ 面が平面かどうかを判定 """
    return abs(face.normal.length - 1.0) < tolerance

def process_connected_surfaces(flat_surfaces, curved_surfaces):
    """ 平面を優先し、面積が大きい方を優先して接続処理を行う """
    print("平面を処理中...")
    process_flat_surfaces(flat_surfaces)
    print("曲面を処理中...")
    process_curved_surfaces(curved_surfaces)
    
def process_flat_surfaces(flat_surfaces):
    """ 面積が大きい平面を優先して処理 """
    sorted_flat = sorted(flat_surfaces, key=lambda g: sum(f.area for f in g), reverse=True)
    
    for flat_surface in sorted_flat:
        # 平面同士の接続処理
        for other_surface in sorted_flat:
            if flat_surface != other_surface:
                connect_surfaces(flat_surface, other_surface, "flat")
                bpy.context.window_manager.progress_update(len(flat_surface))

def process_curved_surfaces(curved_surfaces):
    """ 曲面同士を処理 """
    sorted_curved = sorted(curved_surfaces, key=lambda g: sum(f.area for f in g), reverse=True)
    
    for curved_surface in sorted_curved:
        # 曲面同士の接続処理
        for other_surface in sorted_curved:
            if curved_surface != other_surface:
                connect_surfaces(curved_surface, other_surface, "curved")
                bpy.context.window_manager.progress_update(len(curved_surface))

def connect_surfaces(group1, group2, surface_type):
    """ 平面または曲面を接続して正しくエッジで合わせる """
    bm = bmesh.new()
    bm.from_mesh(bpy.context.object.data)
    
    for face1 in group1:
        for face2 in group2:
            for edge1 in face1.edge_keys:
                for edge2 in face2.edge_keys:
                    if set(edge1) == set(edge2):  # 同じエッジを共有している場合
                        v1_1, v1_2 = bm.verts[edge1[0]], bm.verts[edge1[1]]
                        v2_1, v2_2 = bm.verts[edge2[0]], bm.verts[edge2[1]]
                        
                        if (v1_1.co - v2_1.co).length > 0.001:
                            v1_1.co = v2_1.co
                        if (v1_2.co - v2_2.co).length > 0.001:
                            v1_2.co = v2_2.co
                        
                        bmesh.ops.weld_verts(bm, targetmap={v1_1: v2_1, v1_2: v2_2})

    bm.to_mesh(bpy.context.object.data)
    bm.free()
    print(f"{surface_type} surfaceの接続が完了しました。")

def cut_intersecting_surfaces(flat_surfaces, curved_surfaces):
    """ 平面同士、曲面同士、平面と曲面の交差部分を切断 """
    for group1 in flat_surfaces + curved_surfaces:
        for group2 in flat_surfaces + curved_surfaces:
            if group1 != group2:
                cut_intersections(group1, group2)

def cut_intersections(group1, group2):
    """ 面同士が交差する場合に交差部分で切断 """
    bm = bmesh.new()
    bm.from_mesh(bpy.context.object.data)
    
    for face in group1 + group2:
        verts = [bm.verts.new(v.co) for v in face.verts]
        try:
            bm.faces.new(verts)
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
    bpy.ops.mesh.remove_doubles()
    bpy.ops.mesh.delete_loose()

    bpy.ops.mesh.select_non_manifold()
    bpy.ops.mesh.fill()

    bpy.ops.object.mode_set(mode='OBJECT')
    print("不要な頂点・エッジを削除し、多様体化を行いました。")

    bpy.ops.object.shade_smooth()
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    print("法線を再計算しました。")

def process_mesh(obj, max_vertices=10000, tolerance=0.01, area_threshold=0.05):
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
    
    max_vertices: bpy.props.IntProperty(name="Max Vertices", default=10000)
    
    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "選択されたオブジェクトはメッシュではありません。")
            return {'CANCELLED'}
        
        # 処理の進行状況をトラッキング
        bpy.context.window_manager.progress_begin(0, 100)
        
        try:
            process_mesh(obj, max_vertices=self.max_vertices)
        finally:
            bpy.context.window_manager.progress_end()
        
        self.report({'INFO'}, "メッシュの簡略化と再構成が完了しました。")
        return {'FINISHED'}

def menu_func(self, context):
    self.layout.operator(OBJECT_OT_simplify_and_reconstruct.bl_idname)

def register():
    bpy.utils.register_class(OBJECT_OT_simplify_and_reconstruct)
    bpy.types.VIEW3D_MT_object.append(menu_func)

def unregister():
    bpy.utils.unregister_class(OBJECT_OT_simplify_and_reconstruct)
    bpy.types.VIEW3D_MT_object.remove(menu_func)

if __name__ == "__main__":
    register()
