from typing import NamedTuple

import cv2
import numpy as np
from numpy.core._multiarray_umath import ndarray

from opsi.util.cache import cached_property


# Also represents dimensions
class Point(NamedTuple):
    # implicit classmethod Point._make - create from existing iterable

    x: float
    y: float

    @classmethod
    def _make_rev(cls, iter):  # make reversed (y, x)
        return cls(iter[1], iter[0])

    @property
    def area(self):
        return self.x * self.y

    @property
    def hypot(self):
        return ((self.x ** 2) + (self.y ** 2)) ** 0.5

    @property
    def perimeter(self):
        return 2 * (self.x + self.y)

    # usage: normalized = Point(width, height).normalize(Point(x, y))
    def normalize(self, point: "Point") -> "Point":
        x = (2 * point.x / self.x) - 1
        y = (2 * point.y / self.y) - 1

        return Point(x, y)


class Shape:
    def __init__(self):
        raise TypeError("Must be made with from_* classmethods")

    @property
    def perimeter(self):
        return None

    @property
    def area(self):
        return None


class Rect(Shape):
    # create from top-left coordinate and dimensions
    @classmethod
    def from_params(cls, x, y, width, height):
        inst = cls.__new__(cls)

        inst.tl = Point(x, y)
        inst.dim = Point(width, height)

        return inst  # Big oof will occur if you forget this

    @classmethod
    def from_contour(cls, contour_raw):
        return cls.from_params(*cv2.boundingRect(contour_raw))

    @cached_property
    def tr(self):
        return Point(self.tl.x + self.dim.x, self.tl.y)

    @cached_property
    def bl(self):
        return Point(self.tl.x, self.tl.y + self.dim.y)

    @cached_property
    def br(self):
        return Point(self.tl.x + self.dim.x, self.tl.y + self.dim.y)

    @cached_property
    def center(self):
        return Point(self.tl.x + self.dim.x / 2, self.tl.y + self.dim.y / 2)

    @cached_property
    def perimeter(self):
        return self.dim.perimeter

    @cached_property
    def area(self):
        return self.dim.area


class RotatedRect(Shape):
    # create from top-left coordinate and dimensions
    @classmethod
    def from_params(cls, center, size, angle):
        inst = cls.__new__(cls)

        inst.center = Point(center[0], center[1])
        inst.dim = Point(size[0], size[1])
        inst.angle = angle

        return inst

    @classmethod
    def from_contour(cls, contour_raw):
        return cls.from_params(*cv2.minAreaRect(contour_raw))

    @cached_property
    def box_points(self):
        return cv2.boxPoints((self.center, self.dim, self.angle))

    @cached_property
    def perimeter(self):
        return self.dim.perimeter

    @cached_property
    def area(self):
        return self.dim.area

    # Returns the angle of the rectangle from -90 to 90, where 0 is the rectangle vertical on its shortest side.
    @cached_property
    def vertical_angle(self):
        rect_angle = self.angle
        if self.dim[0] > self.dim[1]:
            rect_angle += 90
        return rect_angle


# Stores corners used for SolvePNP
class Corners(NamedTuple):
    tl: Point
    tr: Point
    bl: Point
    br: Point

    def to_matrix(self):
        return np.array([self.tl, self.tr, self.bl, self.br])

    @cached_property
    def calculate_pose(self, object_points: "Corners", camera_matrix, distortion_coefficients):
        img_points_mat = self.to_matrix()
        object_points_mat = object_points.to_matrix()

        ret, rvec, tvec = cv2.solvePnP(object_points_mat, img_points_mat, camera_matrix, distortion_coefficients)

        print(ret, rvec, tvec)






# TODO Make proper wrapper classes for these shapes
class Circles(ndarray):
    pass


class Segments(ndarray):
    pass


class Lines(ndarray):
    pass
