# -*- coding: utf-8 -*-
"""
Make Solid Manifold

任意のメッシュを、物理演算向けの「閉じた(watertight)・多様体(manifold)・
単一オブジェクト」に変換する。複数オブジェクトや分裂したパーツも結合して
ひとかたまりにする。

方式:
  - Voxel Remesh : 凹凸を保持したまま watertight な単体にする
                   （近接したパーツは結合される。Blender 2.82+ は OpenVDB ボクセル、
                    2.80/2.81 は従来の octree Remesh で自動的に近似する）
  - Convex Hull  : 凸包。確実に 1 つの凸ソリッドになる
                   （離れたパーツも 1 つに統合される）

進捗はステータスバーに常時表示し、ステップの区切りで ESC により中断できる。
中断時は作業用に作った複製を削除し、元の選択状態へ戻す。
"""

import bpy
import bmesh
import math
from bpy.props import (
    EnumProperty,
    FloatProperty,
    BoolProperty,
    StringProperty,
)


# ---------------------------------------------------------------------------
# 設定（シーンに保持）
# ---------------------------------------------------------------------------
class MakeSolidSettings(bpy.types.PropertyGroup):
    method: EnumProperty(
        name="方式",
        items=[
            ('VOXEL', "Voxel Remesh",
             "凹凸を保持したまま watertight な単体にする（2.82+はボクセル / それ未満は従来Remeshで近似）"),
            ('CONVEX', "Convex Hull",
             "凸包。確実に1つの凸ソリッドになる（離れたパーツも統合）"),
        ],
        default='VOXEL',
    )
    voxel_size: FloatProperty(
        name="Voxel Size",
        description="ボクセルの大きさ。小さいほど高精細で重い。離れたパーツを繋ぎたい場合は大きくする",
        default=0.01, min=0.0001, soft_min=0.001, soft_max=1.0,
        subtype='DISTANCE',
    )
    merge_distance: FloatProperty(
        name="Merge Distance",
        description="この距離以内の重複頂点を結合してから処理する",
        default=0.0001, min=0.0, soft_max=0.01,
        subtype='DISTANCE',
    )
    keep_original: BoolProperty(
        name="元を残す",
        description="元のオブジェクトを残し、結果を別オブジェクトとして作成する",
        default=True,
    )
    set_origin_volume: BoolProperty(
        name="原点を体積中心へ",
        description="物理演算向けに、結果オブジェクトの原点を体積の中心へ移動する",
        default=True,
    )
    result_name: StringProperty(
        name="結果の名前",
        default="SolidBody",
    )


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------
def _remesh_has_voxel(mod):
    """Remesh モディファイアが VOXEL モードに対応しているか（2.82+）。"""
    try:
        return 'VOXEL' in mod.bl_rna.properties['mode'].enum_items.keys()
    except Exception:
        return False


def _manifold_stats(obj):
    """(非多様体エッジ数, 頂点数, 面数) を返す。"""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.edges.ensure_lookup_table()
    nonmani = sum(1 for e in bm.edges if not e.is_manifold)
    nv = len(bm.verts)
    nf = len(bm.faces)
    bm.free()
    return nonmani, nv, nf


# ---------------------------------------------------------------------------
# オペレーター（モーダル：進捗表示＋中断対応）
# ---------------------------------------------------------------------------
class OBJECT_OT_make_solid_manifold(bpy.types.Operator):
    """選択メッシュを、物理演算向けの閉じた多様体の単一オブジェクトに変換する"""
    bl_idname = "object.make_solid_manifold"
    bl_label = "Make Solid Manifold"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(o.type == 'MESH' for o in context.selected_objects)

    # ---- 進捗表示 -------------------------------------------------------
    def _set_status(self, context, msg):
        try:
            context.workspace.status_text_set(msg)
        except Exception:
            pass

    # ---- 起動 -----------------------------------------------------------
    def invoke(self, context, event):
        self.settings = context.scene.make_solid_settings
        self._sources = [o for o in context.selected_objects if o.type == 'MESH']
        if not self._sources:
            self.report({'ERROR'}, "メッシュオブジェクトが選択されていません。")
            return {'CANCELLED'}

        # 編集モードなら抜ける
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        self._orig_selection = list(context.selected_objects)
        self._orig_active = context.view_layer.objects.active
        self.work_obj = None
        self._created = []      # 作成したオブジェクト（中断時に削除）
        self._stats = None
        self._note = ""
        self._timer = None
        self._index = 0
        self._phase = 'show'    # 'show' -> ラベル表示, 'run' -> 実行

        # ステップ構築
        self._steps = [
            ("選択を複製・結合", self._step_prepare),
            ("変換を適用", self._step_apply),
            ("重複頂点を結合", self._step_merge),
        ]
        if self.settings.method == 'VOXEL':
            self._steps.append(("リメッシュ（ソリッド化）", self._step_voxel))
        else:
            self._steps.append(("凸包を生成", self._step_convex))
        self._steps += [
            ("法線を再計算", self._step_recalc),
            ("仕上げ", self._step_finalize),
        ]

        wm = context.window_manager
        wm.progress_begin(0, len(self._steps))
        self._timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)
        self._set_status(context, "Make Solid: 開始...  (ESCで中断)")
        return {'RUNNING_MODAL'}

    # ---- モーダルループ -------------------------------------------------
    def modal(self, context, event):
        if event.type == 'ESC' and event.value == 'PRESS':
            return self._finish(context, cancelled=True, msg="中断しました。")

        if event.type == 'TIMER':
            n = len(self._steps)
            if self._index >= n:
                return self._finish(context, cancelled=False)

            label, func = self._steps[self._index]
            if self._phase == 'show':
                pct = int(100 * self._index / n)
                self._set_status(
                    context,
                    "Make Solid [%d%%] %d/%d: %s  (ESCで中断)"
                    % (pct, self._index + 1, n, label),
                )
                context.window_manager.progress_update(self._index)
                self._phase = 'run'
                return {'RUNNING_MODAL'}
            else:
                try:
                    func(context)
                except Exception as e:
                    return self._finish(
                        context, cancelled=True,
                        msg="失敗 (%s): %s" % (label, e), is_error=True,
                    )
                self._index += 1
                self._phase = 'show'
                return {'RUNNING_MODAL'}

        # 処理中は他の操作を抑止
        return {'RUNNING_MODAL'}

    # ---- 終了処理 -------------------------------------------------------
    def _finish(self, context, cancelled, msg=None, is_error=False):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.progress_end()
        self._set_status(context, None)

        if cancelled:
            for ob in self._created:
                if ob and ob.name in bpy.data.objects:
                    bpy.data.objects.remove(ob, do_unlink=True)
            self._restore_selection(context)
            self.report({'ERROR'} if is_error else {'WARNING'}, msg or "中断しました。")
            return {'CANCELLED'}

        nonmani, nv, nf = self._stats or (0, 0, 0)
        state = "manifold OK" if nonmani == 0 else ("非多様体エッジ %d 本" % nonmani)
        self.report(
            {'INFO'},
            "完成: '%s'  (頂点 %d / 面 %d / %s)%s"
            % (self.work_obj.name, nv, nf, state, self._note),
        )
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

    def _activate(self, context, ob):
        bpy.ops.object.select_all(action='DESELECT')
        ob.select_set(True)
        context.view_layer.objects.active = ob

    # ---- 各ステップ -----------------------------------------------------
    def _step_prepare(self, context):
        bpy.ops.object.select_all(action='DESELECT')
        copies = []
        for src in self._sources:
            if src.name not in bpy.data.objects:
                continue
            dup = src.copy()
            dup.data = src.data.copy()
            context.collection.objects.link(dup)
            copies.append(dup)
            self._created.append(dup)
        if not copies:
            raise RuntimeError("複製できるメッシュがありません。")

        for c in copies:
            c.select_set(True)
        context.view_layer.objects.active = copies[0]
        if len(copies) > 1:
            bpy.ops.object.join()   # 1 つに結合
        self.work_obj = context.view_layer.objects.active
        self.work_obj.name = self.settings.result_name

    def _step_apply(self, context):
        # 物理向けに回転・スケールを適用（scale=1 にする）
        self._activate(context, self.work_obj)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    def _step_merge(self, context):
        me = self.work_obj.data
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.remove_doubles(
            bm, verts=bm.verts, dist=max(self.settings.merge_distance, 1e-6)
        )
        bm.to_mesh(me)
        bm.free()
        me.update()

    def _step_voxel(self, context):
        ob = self.work_obj
        self._activate(context, ob)
        mod = ob.modifiers.new("Remesh", 'REMESH')
        if _remesh_has_voxel(mod):
            # Blender 2.82+ : OpenVDB ボクセルリメッシュ
            mod.mode = 'VOXEL'
            mod.voxel_size = self.settings.voxel_size
            if hasattr(mod, "adaptivity"):
                mod.adaptivity = 0.0
        else:
            # Blender 2.80 / 2.81 : ボクセル方式が無いので、従来の
            # octree ベース Remesh で voxel_size を近似する（watertight・manifold）。
            mod.mode = 'SHARP'
            if hasattr(mod, "use_remove_disconnected"):
                mod.use_remove_disconnected = False  # パーツを落とさない
            max_dim = max(ob.dimensions) if ob.dimensions else 0.0
            vsize = max(self.settings.voxel_size, 1e-6)
            depth = int(round(math.log2(max_dim / vsize))) if max_dim > 0.0 else 4
            mod.octree_depth = max(2, min(depth, 8))
            self._note = ("（Voxel非対応のため従来Remesh octree_depth=%d で近似）"
                          % mod.octree_depth)
        bpy.ops.object.modifier_apply(modifier=mod.name)

    def _step_convex(self, context):
        me = self.work_obj.data
        bm = bmesh.new()
        bm.from_mesh(me)
        if len(bm.verts) < 4:
            bm.free()
            raise RuntimeError("凸包を作るには頂点が足りません。")
        res = bmesh.ops.convex_hull(bm, input=bm.verts, use_existing_faces=False)
        to_del = res.get('geom_unused', []) + res.get('geom_interior', [])
        if to_del:
            bmesh.ops.delete(bm, geom=to_del, context='VERTS')
        bm.to_mesh(me)
        bm.free()
        me.update()

    def _step_recalc(self, context):
        me = self.work_obj.data
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me)
        bm.free()
        me.update()

    def _step_finalize(self, context):
        ob = self.work_obj
        self._activate(context, ob)
        if self.settings.set_origin_volume:
            try:
                bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_VOLUME', center='MEDIAN')
            except Exception:
                pass

        # 元を残さない設定なら、元オブジェクトを削除
        if not self.settings.keep_original:
            for src in self._sources:
                if src and src is not ob and src.name in bpy.data.objects:
                    bpy.data.objects.remove(src, do_unlink=True)

        self._stats = _manifold_stats(ob)
        self._activate(context, ob)


def menu_func(self, context):
    self.layout.operator(OBJECT_OT_make_solid_manifold.bl_idname, text="Make Solid Manifold")
