import glob
import logging
import re
import subprocess
from dataclasses import dataclass
from sys import platform

import cv2

LOGGER = logging.getLogger(__name__)

__package__ = "opsi.input"

ENABLE_RES = False
ENABLE_FPS = False
IS_LINUX = platform.startswith("linux")


def get_settings():
    @dataclass
    class Linux:
        mode: get_modes()
        brightness: int = 50
        contrast: int = 50
        saturation: int = 50
        exposure: int = 50
        width: controls() = None
        height: controls() = None
        fps: controls(True) = None

    @dataclass
    class NonLinux:
        mode: int = 0
        brightness: int = 50
        contrast: int = 50
        saturation: int = 50
        exposure: int = 50
        width: int = 320
        height: int = 240
        fps: int = 60

    return Linux if IS_LINUX else NonLinux


def get_w(mode):
    cammode = parse_cammode(mode)
    if len(cammode) >= 3:
        camtuple = parse_cammode(mode)
        return camtuple[1] + camtuple[2]
    return 0


def get_codec(v4l2_out):
    # for each codec, add the codec name and the description from v4l2-ctl (regex allowed), and FOURCC name
    # order by priority
    codecs = [
        ("H264", "H.264, compressed", "X264"),
        ("MJPG", "Motion-JPEG, compressed", "MJPG"),
        ("YUYV", r"YUYV \d:\d:\d", "YUYV"),
        ("YU12", r"Planar YUV \d:\d:\d", "YU12"),
    ]
    for i in codecs:
        # [digit] '<CODEC NAME>' (<CODEC DESCRIPTION>)
        # ex. [1]: 'MJPG' (Motion-JPEG, compressed)
        pattern1 = fr"\[\d+\]: '{i[0]}' \({i[1]}\) (.+)(\[\d+\].+)"
        lines1 = re.search(pattern1, v4l2_out)
        if lines1 is not None:
            return (cv2.VideoWriter_fourcc(*i[2]), lines1.group(1))
        pattern2 = fr"\[\d+\]: '{i[0]}' \({i[1]}\) (.+)($)"
        lines2 = re.search(pattern2, v4l2_out)
        if lines2 is not None:
            return (cv2.VideoWriter_fourcc(*i[2]), lines2.group(1))
    return None


def get_cam_info(cam):
    try:
        sp_out = subprocess.run(
            f"v4l2-ctl -d {str(cam)} --list-formats-ext".split(),
            capture_output=True,
            check=True,
        )
        return str(sp_out.stdout).replace("\\n", " ").replace("\\t", "")
    except subprocess.CalledProcessError:
        pass
    return None


def get_modes():
    # TODO: don't use globals, move all of this to a class and make a instance for module
    global ENABLE_FPS
    global ENABLE_RES

    all_modes = set()
    cam_list = (cam.replace("/dev/video", "") for cam in glob.glob("/dev/video*"))

    for cam in sorted(cam_list, key=int):

        caminfo = get_cam_info(cam)

        # remove cameras of these types
        # PiCam has extraneous cameras with type "Video Capture Multiplanar"

        skip = False
        cam_blacklist = ("Video Capture Multiplanar",)
        for i in cam_blacklist:
            if re.search(i, caminfo):
                skip = True
        if skip:
            continue

        codec = get_codec(caminfo)
        if codec is None:
            continue

        # group 1: resolution
        # group 2: everything up until next instance of Size
        any_set = False
        for match in re.finditer(r"Size: Discrete (\d+x\d+) ", codec[1]):
            resolution = match.group(1)
            # get everything from the curent resolution to the next resolution
            line = re.search(
                fr"{match.group(0)}(.+?)Size|{match.group(0)}(.+)", codec[1]
            )
            line = line.group(1) or line.group(2)
            fpses = set()
            for interval in re.finditer(r"nterval: \w+ \d+\.\d+s \((.+?) fps\)", line):
                fpses.add(float(interval.group(1)))
            # convert to float to use %g formatting, removing extraneous decimals
            if resolution:
                if fpses:
                    all_modes.add(
                        "Cam {0}: {1} @ {2:g} fps".format(
                            cam, resolution, float(max(fpses))
                        )
                    )
                    any_set = True
                else:
                    all_modes.add("Cam {0}: {1}".format(cam, resolution))
                    any_set = True
                    ENABLE_FPS = True
        if not any_set:
            all_modes.add("Cam {0}".format(cam))
            ENABLE_RES = True

    return tuple(sorted(all_modes, key=get_w, reverse=True))


def parse_cammode(mode):
    if type(mode) is int:
        return (mode,)
    cammode = []
    # group 3: any digit+ OR any digit+, decimal, any digit+
    m = re.search(r"(?:Cam (\d+))?(?::( \d+)x(\d+))?(?: @ (\d+|\d+.\d+) fps)?", mode)
    cam = m.group(1)
    w = m.group(2)
    h = m.group(3)
    fps = m.group(4)
    if cam:
        cammode.append(int(cam))
    if w and h:
        cammode.append(int(w))
        cammode.append(int(h))
    if fps:
        cammode.append(float(fps))
    return tuple(cammode)


def controls(fps=False):
    if ENABLE_RES:
        return int
    if fps and ENABLE_FPS:
        return int
    return None


def set_property(cap, prop, value):
    try:
        cap.set(prop, value)
    except AttributeError:
        LOGGER.debug("Camera does not support property %s", property)


def create_capture(settings):
    mode = parse_cammode(settings.mode)
    if len(mode) < 1:
        return None
    if IS_LINUX:
        cap = cv2.VideoCapture(mode[0], cv2.CAP_V4L)
        codec = get_codec(get_cam_info(mode[0]))
        if codec:
            set_property(cap, cv2.CAP_PROP_FOURCC, codec[0])
    else:
        cap = cv2.VideoCapture(mode[0])
    if len(mode) >= 3:
        w = mode[1]
        h = mode[2]
    else:
        w = settings.width
        h = settings.height
    set_property(cap, cv2.CAP_PROP_FRAME_WIDTH, w)
    set_property(cap, cv2.CAP_PROP_FRAME_HEIGHT, h)
    if len(mode) >= 4:
        fps = mode[3]
    else:
        fps = settings.fps
    set_property(cap, cv2.CAP_PROP_FPS, fps)
    set_property(cap, cv2.CAP_PROP_BRIGHTNESS, settings.brightness)
    set_property(cap, cv2.CAP_PROP_CONTRAST, settings.contrast)
    set_property(cap, cv2.CAP_PROP_SATURATION, settings.saturation)
    set_property(cap, cv2.CAP_PROP_EXPOSURE, settings.exposure)
    return cap
