# -*- coding: utf-8 -*-
"""结构审计修复回归入口。"""
import repair_boundary_tests
import repair_pipeline_tests
import repair_lens_tests
import coop_launch_tests


def run(check, root, client):
    repair_boundary_tests.run(check, root, client)
    repair_pipeline_tests.run(check, root)
    repair_lens_tests.run(check, root)
    coop_launch_tests.run(check, root, client)
