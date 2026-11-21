#!/usr/bin/env python3
"""Prevent teacher predictions from giving precise ball instances a second class."""
import unittest

from collect_ball_dataset import exclude_ball_pseudo_labels


class TrainingLabelTests(unittest.TestCase):
    def test_green_ball_does_not_also_become_bush(self):
        green=[6,.5,.5,.2,.2]
        false_bush=[1,.51,.5,.21,.2]
        real_bush=[1,.2,.5,.25,.15]
        self.assertEqual(exclude_ball_pseudo_labels([false_bush,real_bush],[green]),[real_bush])

    def test_visible_bush_behind_small_ball_is_retained(self):
        bush=[1,.5,.5,.4,.2]
        green=[6,.5,.5,.1,.1]
        self.assertEqual(exclude_ball_pseudo_labels([bush],[green]),[bush])

    def test_without_balls_scenery_is_unchanged(self):
        scenery=[[0,.5,.3,.2,.4],[1,.2,.5,.25,.15],[2,.8,.7,.1,.1],[3,.4,.6,.04,.2]]
        self.assertEqual(exclude_ball_pseudo_labels(scenery,[]),scenery)

    def test_other_ball_colours_are_not_duplicated_as_scenery(self):
        for cls in [4,5,6]:
            ball=[cls,.4,.6,.1,.1]
            self.assertEqual(exclude_ball_pseudo_labels([[2,.4,.6,.1,.1]],[ball]),[])


if __name__=='__main__':
    unittest.main()
