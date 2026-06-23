import math

from geometry import Circle, Rectangle


def test_circle_area_uses_pi_r_squared():
    assert Circle(3).area() == math.pi * 9


def test_rectangle_area_multiplies_width_and_height():
    assert Rectangle(4, 5).area() == 20
