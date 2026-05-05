from robodk import robolink, robomath, robodialogs
import os
import urllib.request

robolink.import_install('svgpathtools')
import svgpathtools as spt

#-------------------------------------------
# Settings
IMAGE_FILE = r"C:\Users\Lenovo\Desktop\IMPL\robot1.svg"  # Leave this empty ("") to prompt a file explorer

BOARD_WIDTH, BOARD_HEIGHT = 250,250  # Size of the image. The image will be scaled keeping its aspect ratio
BOARD_BACKGROUND_COLOR = [0, 0, 0, 1]  # Background of the drawing board (R, G, B, A)

DEFAULT_PATH_COLOR = '#FFFFFF'  # Default drawing colors for path with no styling (should contrast with the background!)
USE_STYLE_COLOR = True
PREFER_STROKE_OVER_FILL_COLOR = True  # Prefer using a path stroke color over a path fill color

TCP_KEEP_TANGENCY = False  # Set to True to keep the tangency along the path
LIFT_DISTANCE = 50.0  # mm, pen lift distance between SVG strokes (5 cm)

MM_X_PIXEL = 5.0  # mm, the path will be cut depending on the pixel size. If this value is changed it is recommended to scale the pixel object.
SEGMENT_BREAK_TOL = 5.0  # mm, tolerance used to detect disconnected SVG segments

#-------------------------------------------
# Load the SVG file
if IMAGE_FILE.startswith('http') and IMAGE_FILE.endswith('.svg'):
    r = urllib.request.urlretrieve(IMAGE_FILE, "drawing.svg")
    IMAGE_FILE = "drawing.svg"

elif not IMAGE_FILE or not os.path.exists(os.path.abspath(IMAGE_FILE)):
    IMAGE_FILE = robodialogs.getOpenFileName(strtitle='Open SVG File', defaultextension='.svg', filetypes=[('SVG files', '.svg')])

if not IMAGE_FILE or not os.path.exists(os.path.abspath(IMAGE_FILE)):
    quit()

paths, path_attribs, svg_attribs = spt.svg2paths2(IMAGE_FILE)

# Scale the SVG to fit in the desired drawing area
# 1. Find the bounding area
xmin, xmax, ymin, ymax = 9e9, 0, 9e9, 0
for path in paths:
    _xmin, _xmax, _ymin, _ymax = path.bbox()
    xmin = min(_xmin, xmin)
    xmax = max(_xmax, xmax)
    ymin = min(_ymin, ymin)
    ymax = max(_ymax, ymax)
bbox_height, bbox_width = ymax - ymin, xmax - xmin

# 2. Scale the SVG file and recenter it to the drawing board
SCALE = min(BOARD_HEIGHT / bbox_height, BOARD_WIDTH / bbox_width)
svg_height, svg_width = bbox_height * SCALE, bbox_width * SCALE
svg_height_min, svg_width_min = ymin * SCALE, xmin * SCALE
TRANSLATE = complex((BOARD_WIDTH - svg_width) / 2 - svg_width_min, (BOARD_HEIGHT - svg_height) / 2 - svg_height_min)

#-------------------------------------------
# Get RoboDK Items
RDK = robolink.Robolink()
RDK.setSelection([])

robot = RDK.Item('UR5e')
tool = RDK.Item('SpringMarkerToolAssy')
h_frame = RDK.Item('UR5e Base')
home = RDK.Item('home')
entry = RDK.Item('Entry')
if not robot.Valid() or not tool.Valid():
    quit()

frames = RDK.ItemList(robolink.ITEM_TYPE_FRAME)
frames.remove(robot.Parent())
frame = RDK.Item('Draw Frame')  # Reference frame for the drawing
if not frame.Valid():
    quit()

pixel_ref = RDK.Item('pixel')  # Reference object to paint
if not frame.Valid():
    quit()

RDK.Render(False)

board_draw = RDK.Item('Drawing Board')  # Drawing board
if board_draw.Valid() and board_draw.Type() == robolink.ITEM_TYPE_OBJECT:
    board_draw.Delete()
board_250mm = RDK.Item('Whiteboard 250mm')
board_250mm.setVisible(False)
board_250mm.Copy()
board_draw = frame.Paste()
board_draw.setVisible(True, False)
board_draw.setName('Drawing Board')
board_draw.Scale([BOARD_HEIGHT / 250, BOARD_WIDTH / 250, 1])  # adjust the board size to the image size (scale)
board_draw.setColor(BOARD_BACKGROUND_COLOR)
RDK.setSelection([])

RDK.Render(True)

#-------------------------------------------
# Initialize the robot
home_joints = robot.JointsHome().tolist()
if abs(home_joints[4]) < 5:
    home_joints[4] = 90.0

robot.setPoseFrame(h_frame)
robot.setPoseTool(tool)
robot.MoveJ(entry)


robot.setPoseFrame(frame)
# Get the target orientation depending on the tool orientation at home position
#orient_frame2tool = robomath.invH(frame.Pose()) * robot.SolveFK(home_joints) * tool.Pose()
#orient_frame2tool[0:3, 3] = robomath.Mat([0, 0, 0])

orient_frame2tool = robomath.rotx(robomath.pi)
orient_frame2tool[0:3, 3] = robomath.Mat([0, 0, 0])


def point_to_poses(point, angle):
    py, px = point.real, point.imag
    point_pose = robomath.transl(px, py, 0) * robomath.rotz(angle)
    if TCP_KEEP_TANGENCY:
        robot_pose = point_pose * orient_frame2tool
    else:
        robot_pose = robomath.transl(px, py, 0) * orient_frame2tool
    return point_pose, robot_pose


def pen_up_pose(robot_pose):
    return robot_pose * robomath.transl(0, 0, -LIFT_DISTANCE)


def pen_down(robot_item, robot_pose):
    robot_item.MoveL(robot_pose)


def pen_up(robot_item, robot_pose):
    robot_item.MoveL(pen_up_pose(robot_pose))


def move_to_stroke_start(robot_item, robot_pose):
    robot_item.MoveJ(pen_up_pose(robot_pose))
    pen_down(robot_item, robot_pose)


#-------------------------------------------
RDK.ShowMessage(f"Drawing {IMAGE_FILE}..", False)

for path_count, (path, attrib) in enumerate(zip(paths, path_attribs)):
    styles = {}

    if 'style' not in attrib:
        if 'fill' in attrib:
            styles['fill'] = attrib['fill']
        if 'stroke' in attrib:
            styles['stroke'] = attrib['stroke']
    else:
        for style in attrib['style'].split(';'):
            style_pair = style.split(':')
            if len(style_pair) != 2:
                continue
            styles[style_pair[0].strip()] = style_pair[1].strip()

    if 'fill' in styles and not styles['fill'].startswith('#'):
        styles.pop('fill')
    if 'stroke' in styles and not styles['stroke'].startswith('#'):
        styles.pop('stroke')

    hex_color = DEFAULT_PATH_COLOR
    if USE_STYLE_COLOR:
        if PREFER_STROKE_OVER_FILL_COLOR:
            if 'stroke' in styles:
                hex_color = styles['stroke']
            elif 'fill' in styles:
                hex_color = styles['fill']
        else:
            if 'fill' in styles:
                hex_color = styles['fill']
            elif 'stroke' in styles:
                hex_color = styles['stroke']

    draw_color = spt.misctools.hex2rgb(hex_color)
    draw_color = [round(x / 255, 4) for x in draw_color]

    if 'id' in attrib:
        RDK.ShowMessage(f"Drawing {attrib['id']} with color {hex_color}", False)
    else:
        RDK.ShowMessage(f"Drawing path {path_count} with color {hex_color}", False)

    pen_is_down = False
    prev_point = None
    last_robot_pose = None
    for segment in path.scaled(SCALE).translated(TRANSLATE):
        segment_len = segment.length()
        steps = int(segment_len / MM_X_PIXEL)
        if steps < 1:
            continue

        for i in range(steps + 1):
            t = 1.0
            segment.point(t)
            if i < steps:
                # We need this check to prevent numerical accuracy going over 1, as t must be bound to [0,1]
                i_len = segment_len * i / steps
                t = segment.ilength(i_len)

            point = segment.point(t)
            if i == 0 and prev_point is not None and abs(segment.start - prev_point) > SEGMENT_BREAK_TOL:
                pen_up(robot, last_robot_pose)
                pen_is_down = False
                prev_point = None

            pa = 0
            if prev_point:
                v = point - prev_point
                norm_v = robomath.sqrt(v.real * v.real + v.imag * v.imag)
                v = v / norm_v if norm_v > 1e-6 else complex(1, 0)
                pa = robomath.atan2(v.real, v.imag)

            point_pose, robot_pose = point_to_poses(point, pa)

            if not pen_is_down:
                move_to_stroke_start(robot, robot_pose)
                pen_is_down = True
            else:
                robot.MoveL(robot_pose)

            pixel_ref.Recolor(draw_color)
            board_draw.AddGeometry(pixel_ref, point_pose)

            prev_point = point
            last_robot_pose = robot_pose

    # Safe retract from the last target
    if pen_is_down and last_robot_pose is not None:
        pen_up(robot, last_robot_pose)


robot.setPoseFrame(h_frame)
robot.MoveJ(entry)
robot.MoveJ(home)
RDK.ShowMessage(f"Done drawing {IMAGE_FILE}!", False)
