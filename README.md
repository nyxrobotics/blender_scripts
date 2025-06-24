
# bbx.py

## Overview

`bbx.py` is a Blender add-on that generates bounding box shapes for selected mesh objects and prints URDF-ready XML strings (for ROS) to the terminal. This allows easy integration of 3D bounding boxes into URDF files for robotics applications.

## Features

- Adds an operator to Blender that can be called via the search menu (F3).
- Generates bounding box shapes (`<geometry><box></box></geometry>`) for selected mesh objects.
- Converts Blender coordinates to ROS (URDF) coordinate system.
- Outputs `<origin>` and `<geometry>` tags for URDF.
- Applies a user-defined prefix to generated bounding box object names (default: `UCX_`).

## Requirements

- **Blender 2.80 or newer (tested on 2.82)**  
  👉 You can download Blender 2.82 here:  
  [https://download.blender.org/release/Blender2.82/](https://download.blender.org/release/Blender2.82/)

- ROS or any system where URDF files are used

## Installation

1. Save `bbx.py` to a known location on your system.
2. Open Blender.
3. Go to **Edit > Preferences > Add-ons**.
4. Click **Install...** and select `bbx.py`.
5. Enable the add-on by checking the box next to `Generate bounding box shapes`.
6. Save preferences if you want the add-on to load automatically next time.

## Usage

1. Select one or more mesh objects in the 3D Viewport.
2. Press `F3` (or `Space` depending on keymap) to open the search menu.
3. Type:
   ```
   Generate bounding box shapes for all selected objects
   ```
   and run the operator.
4. Open Blender’s **System Console** to view output:
   - On Windows: **Window > Toggle System Console**
   - On macOS/Linux: Run Blender from terminal to see output
5. Copy the printed URDF XML and paste it into your URDF file.

## Example URDF Output

```
  <origin xyz="0.1234 0.5678 0.9101" rpy="0.0000 0.0000 1.5708"/>
  <geometry>
    <box size="0.5000 0.3000 0.2000"/>
  </geometry>
```

## Notes

- The output uses ROS's coordinate system (X forward, Y left, Z up).
- The generated cube objects are added to your scene for visual confirmation.
- You can change the name prefix (`UCX_`) in the operator’s options (visible in the F3 search operator input).

## License

This script was authored by Jonatan Bijl. It is intended for use under the terms of the GPL or Blender’s default add-on licensing.
