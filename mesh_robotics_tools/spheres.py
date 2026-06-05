# -*- coding: utf-8 -*-
"""
Mesh ⇄ Spheres

(1) Mesh → Spheres
    選択メッシュを球の集合に近似し、"<メッシュ名>_spheres" コレクションに
    球オブジェクトとして格納する。手法は 2 種類:
      - VOXEL  : 内部をボクセル格子で埋め、各内点に均一半径の球を置く
                 （NVlabs/curobo の fit_spheres_to_mesh の voxel 系に相当する考え方）
      - MEDIAL : 各内点で表面までの最短距離（＝内接最大球）を求め、大きい順に
                 貪欲被覆する（CoMMALab/foam の medial 系に相当する考え方）
    ※ 外部ライブラリへのバインディングではなく、同じ考え方を Blender 内で
       依存なしに再現した近似実装。

(2) Spheres → xacro collision
    コレクションを指定し、その中の球から URDF/xacro の <collision>（sphere）を
    生成して、コピペ用にウィンドウ・クリップボード・テキストへ出力する。

座標は Blender のワールド座標で出力する（座標系変換はインポート時に行う想定）。
進捗はステータスバーに表示し、ステップの区切りで ESC により中断できる。
"""

import bpy
import bmesh
import math
from mathutils import Vector
from bpy.props import (
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
)

# グリッドの安全上限（これを超える spacing は自動的に粗くする）
MAX_CELLS = 3_000_000

# Spheres → xacro 出力用
_LAST_OUTPUT = ""
TEXT_BLOCK_NAME = "spheres_collision.xacro"


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
class MeshToSpheresSettings(bpy.types.PropertyGroup):
    method: EnumProperty(
        name="手法",
        items=[
            ('VOXEL', "Voxel Fill",
             "内部をボクセル格子で埋め、均一半径の球を置く（curobo の voxel 系の考え方）"),
            ('MEDIAL', "Medial (greedy)",
             "内接最大球を大きい順に貪欲被覆。少数の大球で覆う（foam の medial 系の考え方）"),
        ],
        default='VOXEL',
    )
    spacing: FloatProperty(
        name="Spacing",
        description="格子間隔。小さいほど球が増え高精細・重くなる",
        default=0.02, min=0.0001, soft_min=0.002, soft_max=0.5,
        subtype='DISTANCE',
    )
    radius_scale: FloatProperty(
        name="Radius Scale",
        description="算出した半径に掛ける倍率。隙間を埋めたい場合は大きくする",
        default=1.0, min=0.1, soft_max=2.0,
    )
    max_spheres: IntProperty(
        name="Max Spheres",
        description="生成する球の最大数。超える場合は間引き/粗くする",
        default=2000, min=1, soft_max=20000,
    )
    coverage: FloatProperty(
        name="Coverage (Medial)",
        description="Medial の貪欲被覆の重なり係数。小さいほど球が増え密になる",
        default=0.7, min=0.05, max=0.99,
    )
    min_radius: FloatProperty(
        name="Min Radius",
        description="これ未満の半径の球は生成しない",
        default=0.005, min=0.0, soft_max=0.1,
        subtype='DISTANCE',
    )
    target_collection: PointerProperty(
        name="対象コレクション",
        description="Spheres → xacro の対象。未指定ならアクティブコレクション",
        type=bpy.types.Collection,
    )


# ---------------------------------------------------------------------------
# (1) Mesh → Spheres （モーダル：進捗＋中断）
# ---------------------------------------------------------------------------
class OBJECT_OT_mesh_to_spheres(bpy.types.Operator):
    """選択メッシュを球の集合に近似し、専用コレクションに格納する"""
    bl_idname = "object.mesh_to_spheres"
    bl_label = "Mesh to Spheres"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(o.type == 'MESH' for o in context.selected_objects)

    def _set_status(self, context, msg):
        try:
            context.workspace.status_text_set(msg)
        except Exception:
            pass

    def invoke(self, context, event):
        self.settings = context.scene.mesh_to_spheres_settings
        self._sources = [o for o in context.selected_objects if o.type == 'MESH']
        if not self._sources:
            self.report({'ERROR'}, "メッシュオブジェクトが選択されていません。")
            return {'CANCELLED'}

        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        self._orig_selection = list(context.selected_objects)
        self._orig_active = context.view_layer.objects.active
        self._created_objs = []
        self._created_colls = []
        self._created_data = []
        self._note = ""
        self._summary = ""
        self._timer = None
        self._gen = self._run(context)

        wm = context.window_manager
        wm.progress_begin(0, 100)
        self._timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)
        self._set_status(context, "Mesh→Spheres: 開始...  (ESCで中断)")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'ESC' and event.value == 'PRESS':
            return self._finish(context, cancelled=True, msg="中断しました。")

        if event.type == 'TIMER':
            try:
                label, frac = next(self._gen)
            except StopIteration:
                return self._finish(context, cancelled=False)
            except Exception as e:
                return self._finish(context, cancelled=True,
                                    msg="失敗: %s" % e, is_error=True)
            if frac is not None:
                pct = max(0, min(100, int(frac * 100)))
                context.window_manager.progress_update(pct)
                self._set_status(context, "Mesh→Spheres [%d%%] %s  (ESCで中断)" % (pct, label))
            else:
                self._set_status(context, "Mesh→Spheres %s  (ESCで中断)" % label)
            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}

    def _finish(self, context, cancelled, msg=None, is_error=False):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.progress_end()
        self._set_status(context, None)

        if cancelled:
            for o in self._created_objs:
                if o and o.name in bpy.data.objects:
                    bpy.data.objects.remove(o, do_unlink=True)
            for c in self._created_colls:
                if c and c.name in bpy.data.collections:
                    bpy.data.collections.remove(c)
            for d in self._created_data:
                if d and d.name in bpy.data.meshes and d.users == 0:
                    bpy.data.meshes.remove(d)
            self._restore_selection(context)
            self.report({'ERROR'} if is_error else {'WARNING'}, msg or "中断しました。")
            return {'CANCELLED'}

        self.report({'INFO'}, "完了: %s%s" % (self._summary, self._note))
        return {'FINISHED'}

    def _restore_selection(self, context):
        try:
            bpy.ops.object.select_all(action='DESELECT')
            for o in self._orig_selection:
                if o and o.name in bpy.data.objects:
                    o.select_set(True)
            if self._orig_active and self._orig_active.name in bpy.data.objects:
                context.view_layer.objects.active = self._orig_active
        except Exception:
            pass

    # ---- ジオメトリ処理 -------------------------------------------------
    def _make_unit_sphere_mesh(self):
        bm = bmesh.new()
        try:
            bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0)
        except TypeError:
            bm.clear()
            bmesh.ops.create_icosphere(bm, subdivisions=1, diameter=1.0)
        maxd = max((v.co.length for v in bm.verts), default=1.0) or 1.0
        for v in bm.verts:
            v.co /= maxd
        me = bpy.data.meshes.new("collision_sphere_unit")
        bm.to_mesh(me)
        bm.free()
        self._created_data.append(me)
        return me

    def _build_bvh(self, context, obj):
        from mathutils.bvhtree import BVHTree
        deps = context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(deps)
        me = obj_eval.to_mesh()
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.triangulate(bm, faces=bm.faces)
        bm.verts.ensure_lookup_table()
        mat = obj.matrix_world
        verts = [mat @ v.co for v in bm.verts]
        polys = [[v.index for v in f.verts] for f in bm.faces]
        bm.free()
        obj_eval.to_mesh_clear()
        if not verts or not polys:
            raise RuntimeError("メッシュにポリゴンがありません。")
        tree = BVHTree.FromPolygons(verts, polys, all_triangles=True)
        mn = Vector((min(v.x for v in verts), min(v.y for v in verts), min(v.z for v in verts)))
        mx = Vector((max(v.x for v in verts), max(v.y for v in verts), max(v.z for v in verts)))
        return tree, mn, mx

    def _auto_spacing(self, mn, mx, s):
        spacing = max(s.spacing, 1e-5)
        size = mx - mn

        def cells(sp):
            return (max(1, int(size.x / sp) + 1)
                    * max(1, int(size.y / sp) + 1)
                    * max(1, int(size.z / sp) + 1))

        c = cells(spacing)
        if c > MAX_CELLS:
            spacing *= (c / MAX_CELLS) ** (1.0 / 3.0)
            self._note = "（格子が大きすぎるため spacing を %.4f に自動調整）" % spacing
        return spacing

    def _make_collection(self, context, name):
        coll = bpy.data.collections.new(name)
        context.scene.collection.children.link(coll)
        self._created_colls.append(coll)
        return coll

    def _make_sphere(self, coll, base_mesh, base_name, idx, center, radius):
        o = bpy.data.objects.new("%s_sphere_%04d" % (base_name, idx), base_mesh)
        o.location = center
        o.scale = (radius, radius, radius)
        o["is_collision_sphere"] = True
        o["sphere_radius"] = radius
        coll.objects.link(o)
        self._created_objs.append(o)

    def _greedy(self, candidates, s, prefix):
        candidates.sort(key=lambda t: t[1], reverse=True)
        accepted = []
        cov = max(min(s.coverage, 0.99), 0.05)
        n = len(candidates)
        for i, (p, r) in enumerate(candidates):
            covered = False
            for (C, R) in accepted:
                if (p - C).length < R * cov:
                    covered = True
                    break
            if not covered:
                accepted.append((p, r))
                if len(accepted) >= s.max_spheres:
                    break
            if (i % 500) == 0:
                yield ("%s 被覆 %d/%d (採用 %d)" % (prefix, i, n, len(accepted)), None)
        return accepted

    def _run(self, context):
        s = self.settings
        base_mesh = self._make_unit_sphere_mesh()
        total = len(self._sources)
        grand_total = 0

        for oi, obj in enumerate(self._sources):
            base_frac = oi / total
            yield ("[%d/%d] %s: 準備" % (oi + 1, total, obj.name), base_frac)

            tree, mn, mx = self._build_bvh(context, obj)
            spacing = self._auto_spacing(mn, mx, s)
            voxel_r = spacing * 0.8660254 * s.radius_scale  # 半対角で被覆
            size = mx - mn
            nx = max(1, int(size.x / spacing) + 1)
            ny = max(1, int(size.y / spacing) + 1)
            nz = max(1, int(size.z / spacing) + 1)

            centers = []  # (Vector, radius)
            for kz in range(nz):
                z = mn.z + (kz + 0.5) * spacing
                for jy in range(ny):
                    y = mn.y + (jy + 0.5) * spacing
                    for ix in range(nx):
                        x = mn.x + (ix + 0.5) * spacing
                        p = Vector((x, y, z))
                        res = tree.find_nearest(p)
                        if not res:
                            continue
                        loc, nrm, _idx, dist = res
                        if (p - loc).dot(nrm) >= 0.0:
                            continue  # 外側
                        if s.method == 'VOXEL':
                            centers.append((p, voxel_r))
                        else:
                            r = dist * s.radius_scale
                            if r >= s.min_radius:
                                centers.append((p, r))
                frac = base_frac + (kz + 1) / nz * 0.8 / total
                yield ("[%d/%d] %s: 走査 %d/%d (候補 %d)"
                       % (oi + 1, total, obj.name, kz + 1, nz, len(centers)), frac)

            if s.method == 'MEDIAL':
                prefix = "[%d/%d] %s:" % (oi + 1, total, obj.name)
                centers = yield from self._greedy(centers, s, prefix)
            else:
                if len(centers) > s.max_spheres and centers:
                    step = max(1, math.ceil(len(centers) / s.max_spheres))
                    centers = centers[::step]

            coll = self._make_collection(context, "%s_spheres" % obj.name)
            for i, (p, r) in enumerate(centers):
                self._make_sphere(coll, base_mesh, obj.name, i, p, r)
            grand_total += len(centers)
            yield ("[%d/%d] %s: 完了 (%d 球)" % (oi + 1, total, obj.name, len(centers)),
                   (oi + 1) / total)

        if grand_total == 0 and base_mesh.users == 0:
            bpy.data.meshes.remove(base_mesh)
        self._summary = "%d オブジェクト / 合計 %d 球を生成" % (total, grand_total)


# ---------------------------------------------------------------------------
# (2) Spheres → xacro collision
# ---------------------------------------------------------------------------
def _sphere_of(obj):
    """オブジェクトから (中心(world), 半径) を推定。球でなければ None。"""
    c = obj.matrix_world.translation.copy()
    scale = obj.matrix_world.to_scale()
    smax = max(abs(scale.x), abs(scale.y), abs(scale.z))
    if obj.type == 'EMPTY' and obj.empty_display_type == 'SPHERE':
        return c, obj.empty_display_size * smax
    if obj.type == 'MESH':
        # 生成した球（is_collision_sphere）含め、ワールド寸法から半径を取る
        return c, max(obj.dimensions) / 2.0
    return None


def _write_text_block(text):
    txt = bpy.data.texts.get(TEXT_BLOCK_NAME)
    if txt is None:
        txt = bpy.data.texts.new(TEXT_BLOCK_NAME)
    txt.clear()
    txt.write(text)
    return txt


class SPH_OT_copy_output(bpy.types.Operator):
    """直近の出力をもう一度クリップボードへコピー"""
    bl_idname = "object.sph_copy_output"
    bl_label = "Copy to Clipboard"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        context.window_manager.clipboard = _LAST_OUTPUT
        self.report({'INFO'}, "クリップボードにコピーしました。")
        return {'FINISHED'}


class SPH_OT_show_output(bpy.types.Operator):
    """直近の出力をポップアップウィンドウで表示"""
    bl_idname = "object.sph_show_output"
    bl_label = "Spheres collision (xacro)"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=560)

    def draw(self, context):
        layout = self.layout
        layout.label(text="クリップボードにコピー済み / Text: '%s'" % TEXT_BLOCK_NAME, icon='TEXT')
        layout.operator(SPH_OT_copy_output.bl_idname, icon='COPYDOWN')
        box = layout.box()
        col = box.column(align=True)
        if _LAST_OUTPUT.strip():
            for line in _LAST_OUTPUT.split("\n"):
                indent = len(line) - len(line.lstrip(" "))
                shown = ("." * indent) + line.lstrip(" ") if indent else line
                col.label(text=shown if shown else " ")
        else:
            col.label(text="(出力はありません)")


class OBJECT_OT_spheres_to_xacro(bpy.types.Operator):
    """コレクション内の球から xacro の <collision>(sphere) を生成して出力する"""
    bl_idname = "object.spheres_to_xacro"
    bl_label = "Spheres to xacro Collision"
    bl_options = {'REGISTER'}

    def execute(self, context):
        global _LAST_OUTPUT
        s = context.scene.mesh_to_spheres_settings
        coll = s.target_collection
        if coll is None:
            alc = context.view_layer.active_layer_collection
            coll = alc.collection if alc else None
        if coll is None:
            self.report({'ERROR'}, "対象コレクションがありません。")
            return {'CANCELLED'}

        spheres = []
        for obj in coll.all_objects:
            sp = _sphere_of(obj)
            if sp and sp[1] > 0.0:
                spheres.append(sp)

        if not spheres:
            self.report({'WARNING'}, "コレクション '%s' に球が見つかりません。" % coll.name)
            return {'CANCELLED'}

        lines = []
        for (c, r) in spheres:
            lines += [
                '  <collision>',
                '    <origin xyz="%.4f %.4f %.4f" rpy="0 0 0"/>' % (c.x, c.y, c.z),
                '    <geometry>',
                '      <sphere radius="%.4f"/>' % r,
                '    </geometry>',
                '  </collision>',
            ]
        text = "\n".join(lines)
        for line in text.split("\n"):
            print(line)

        _LAST_OUTPUT = text
        context.window_manager.clipboard = text
        _write_text_block(text)
        self.report(
            {'INFO'},
            "%d 球の collision を Text '%s' とクリップボードに出力しました。"
            % (len(spheres), TEXT_BLOCK_NAME),
        )
        bpy.ops.object.sph_show_output('INVOKE_DEFAULT')
        return {'FINISHED'}


def menu_func(self, context):
    self.layout.operator(OBJECT_OT_mesh_to_spheres.bl_idname, text="Mesh to Spheres")
    self.layout.operator(OBJECT_OT_spheres_to_xacro.bl_idname, text="Spheres to xacro Collision")
