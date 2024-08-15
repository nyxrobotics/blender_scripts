bl_info = {
    "name": "Generate bounding box shapes",
    "author": "Jonatan Bijl",
    "version": (0, 1),
    "blender": (2, 80, 0),
    "location": "context menu",
    "description": "Creates a bounding cube object for each selected object",
    "category": "Object",
}

import bpy
import mathutils
from bpy.props import StringProperty
import math

def main(context, prefix):
    # make a list of the selected objects of type 'mesh'
    objs = [obj for obj in context.selected_objects if obj.type == 'MESH']
    generated_objs = []

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

        # Print the output in the specified format with ROS coordinates and adjusted orientation
        print(f'  <origin xyz="{ros_loc.x:.4f} {ros_loc.y:.4f} {ros_loc.z:.4f}" rpy="{ros_rotation_euler.x:.4f} {ros_rotation_euler.y:.4f} {ros_rotation_euler.z:.4f}"/>')
        print(f'  <geometry>')
        print(f'    <box size="{adjusted_dx:.4f} {adjusted_dy:.4f} {dz:.4f}"/>')
        print(f'  </geometry>')

    for obj in generated_objs:
        obj.select_set(True)

class GenerateBoundingBoxesOperator(bpy.types.Operator):
    """Create a joined copy of selected meshes, with modifiers applied if needed"""
    bl_idname = "object.generate_bounding_boxes"
    bl_label = "Generate bounding box shapes for all selected objects"
    bl_options = {'REGISTER', 'UNDO'}

    name_prefix: StringProperty(name='name_prefix', description='The name prefix for the new objects', default='UCX_')

    @classmethod
    def poll(cls, context):
        return len(context.selected_objects) > 0

    def execute(self, context):
        main(context, self.name_prefix)
        return {'FINISHED'}

def register():
    bpy.utils.register_class(GenerateBoundingBoxesOperator)

def unregister():
    bpy.utils.unregister_class(GenerateBoundingBoxesOperator)

if __name__ == "__main__":
    register()

    # test call
    bpy.ops.object.generate_bounding_boxes()
