import unittest

import cv2
import numpy as np

from poi_core import PolygonPOIGenerator, normalize_mask


class PolygonPOITest(unittest.TestCase):
    def test_green_pseudo_mask_is_normalized(self):
        mask = np.zeros((40, 60, 3), dtype=np.uint8)
        mask[20:, 10:50] = (0, 255, 0)
        normalized = normalize_mask(mask)
        self.assertEqual(normalized.dtype, np.uint8)
        self.assertEqual(int(normalized[30, 20]), 1)
        self.assertEqual(int(normalized[5, 5]), 0)

    def test_generator_returns_numbered_points_inside_image(self):
        mask = np.zeros((240, 320), dtype=np.uint8)
        polygon = np.array([[35, 225], [285, 225], [235, 90], [90, 90]], dtype=np.int32)
        cv2.fillPoly(mask, [polygon], 1)
        result = PolygonPOIGenerator(240, 320).generate_pois(
            mask, min_edge_len=20, max_pois=7
        )
        self.assertGreaterEqual(len(result["pois"]), 1)
        self.assertEqual(
            list(range(1, len(result["pois"]) + 1)),
            [point["number"] for point in result["pois"]],
        )
        for point in result["pois"]:
            self.assertGreaterEqual(point["x"], 0)
            self.assertLess(point["x"], 320)
            self.assertGreaterEqual(point["y"], 0)
            self.assertLess(point["y"], 240)


if __name__ == "__main__":
    unittest.main()
