# -*- coding: utf-8 -*-
"""
バージョン互換用のヘルパー。

Blender 2.80 〜 最新系まで、API名やUIラベルの変更を吸収するための
薄いラッパーをまとめています。各ツールの処理内容（機能）は変更しません。
"""

import bpy


def bl_version():
    """現在の Blender バージョンを (major, minor, patch) のタプルで返す。"""
    return tuple(bpy.app.version)


def remove_doubles():
    """
    編集モードでの「重複頂点の結合（旧 Remove Doubles / 現 Merge by Distance）」。

    `bpy.ops.mesh.remove_doubles()` は新しい Blender でも Python API として
    残っているが（UI ラベルが変わっただけ）、将来的な削除に備えて
    `bpy.ops.mesh.merge(type='DISTANCE')` へフォールバックする。
    どちらも同じ「距離による頂点結合」を行うため、結果は実質的に同一。
    """
    try:
        bpy.ops.mesh.remove_doubles()
        return
    except (AttributeError, RuntimeError, TypeError):
        pass
    try:
        bpy.ops.mesh.merge(type='DISTANCE')
    except (AttributeError, RuntimeError, TypeError):
        pass
