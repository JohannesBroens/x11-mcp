"""Unit tests for the accuracy runner — pure math, no X11 required.

Tests point generators, statistics computation, and report formatting.
These verify the test infrastructure itself is correct.
"""

from tests.accuracy.runner import (
    PointResult,
    ScenarioResult,
    _compute_stats,
    _grid_points,
    _edge_points,
    _screen_edge_points,
    _diagonal_points,
    _dense_points,
    _micro_move_points,
    _large_jump_points,
    _same_axis_points,
    _random_points,
    _fractional_stress_points,
    format_report,
    SCENARIOS,
)


class TestPointGenerators:
    """Verify point generators produce valid coordinates within API bounds."""

    API_W, API_H = 1280, 800

    def _check_bounds(self, points):
        for name, x, y in points:
            assert 0 <= x < self.API_W, f"{name}: x={x} out of bounds"
            assert 0 <= y < self.API_H, f"{name}: y={y} out of bounds"

    def _check_unique_names(self, points):
        names = [name for name, _, _ in points]
        assert len(names) == len(set(names)), f"Duplicate names: {names}"

    def test_grid_3x3(self):
        points = _grid_points(self.API_W, self.API_H)
        assert len(points) == 9
        self._check_bounds(points)
        self._check_unique_names(points)

    def test_grid_symmetry(self):
        """Grid points should be symmetric around the center."""
        points = _grid_points(self.API_W, self.API_H)
        xs = sorted(set(x for _, x, _ in points))
        ys = sorted(set(y for _, _, y in points))
        assert len(xs) == 3
        assert len(ys) == 3
        # Center column should be at midpoint
        assert xs[1] == self.API_W // 2

    def test_edge_points_near_borders(self):
        points = _edge_points(self.API_W, self.API_H)
        assert len(points) == 8
        self._check_bounds(points)
        self._check_unique_names(points)
        # All points should be within 20px of an edge
        for name, x, y in points:
            near_left = x <= 20
            near_right = x >= self.API_W - 20
            near_top = y <= 20
            near_bottom = y >= self.API_H - 20
            assert near_left or near_right or near_top or near_bottom, (
                f"{name}: ({x},{y}) not near any edge"
            )

    def test_screen_edges_at_absolute_limits(self):
        points = _screen_edge_points(self.API_W, self.API_H)
        assert len(points) == 8
        self._check_unique_names(points)
        # Should include (0,0) corner
        coords = [(x, y) for _, x, y in points]
        assert (0, 0) in coords
        # Should include bottom-right corner
        assert (self.API_W - 1, self.API_H - 1) in coords

    def test_diagonal_ascending(self):
        points = _diagonal_points(self.API_W, self.API_H)
        assert len(points) == 5
        self._check_bounds(points)
        # Points should increase in both x and y
        for i in range(len(points) - 1):
            assert points[i][1] < points[i + 1][1]  # x increases
            assert points[i][2] < points[i + 1][2]  # y increases

    def test_dense_4x5_grid(self):
        points = _dense_points(self.API_W, self.API_H)
        assert len(points) == 20
        self._check_bounds(points)
        self._check_unique_names(points)

    def test_micro_moves_from_center(self):
        points = _micro_move_points(self.API_W, self.API_H)
        assert len(points) == 10  # center + 9 deltas
        self._check_bounds(points)
        # First point should be at center
        _, cx, cy = points[0]
        assert cx == self.API_W // 2
        assert cy == self.API_H // 2
        # All other points should be within 5px of center x
        for _, x, y in points[1:]:
            assert abs(x - cx) <= 5

    def test_large_jumps_opposite_corners(self):
        points = _large_jump_points(self.API_W, self.API_H)
        assert len(points) == 5
        self._check_bounds(points)
        # Should include near-corners and center
        xs = [x for _, x, _ in points]
        ys = [y for _, _, y in points]
        assert min(xs) <= 10
        assert max(xs) >= self.API_W - 10
        assert min(ys) <= 10
        assert max(ys) >= self.API_H - 10

    def test_same_axis_horizontal_and_vertical(self):
        points = _same_axis_points(self.API_W, self.API_H)
        assert len(points) == 6
        self._check_bounds(points)
        # First 3 should share same y (horizontal axis)
        h_ys = [y for _, _, y in points[:3]]
        assert len(set(h_ys)) == 1
        # Last 3 should share same x (vertical axis)
        v_xs = [x for _, x, _ in points[3:]]
        assert len(set(v_xs)) == 1

    def test_random_deterministic(self):
        """Random points with fixed seed should be reproducible."""
        points1 = _random_points(self.API_W, self.API_H)
        points2 = _random_points(self.API_W, self.API_H)
        assert points1 == points2
        assert len(points1) == 20
        self._check_bounds(points1)

    def test_fractional_stress(self):
        points = _fractional_stress_points(self.API_W, self.API_H)
        assert len(points) == 13
        self._check_bounds(points)
        self._check_unique_names(points)

    def test_all_scenarios_registered(self):
        """Every generator function should be in the SCENARIOS dict."""
        assert len(SCENARIOS) == 10
        for name, gen in SCENARIOS.items():
            points = gen(self.API_W, self.API_H)
            assert len(points) > 0, f"Scenario {name} produced no points"

    def test_generators_work_at_small_sizes(self):
        """Generators shouldn't crash on small API dimensions."""
        for name, gen in SCENARIOS.items():
            points = gen(100, 100)
            assert len(points) > 0, f"Scenario {name} failed at 100x100"


class TestStatistics:
    """Verify _compute_stats produces correct statistical summaries."""

    def _make_points(self, errors_and_biases):
        """Create PointResults from (error, dx, dy) tuples."""
        points = []
        for i, (err, dx, dy) in enumerate(errors_and_biases):
            points.append(PointResult(
                name=f"pt-{i}",
                api_x=100, api_y=100,
                expected_screen_x=200, expected_screen_y=200,
                actual_screen_x=200 + dx, actual_screen_y=200 + dy,
                error_px=err,
            ))
        return points

    def test_perfect_accuracy(self):
        points = self._make_points([(0.0, 0, 0)] * 10)
        result = _compute_stats(ScenarioResult(scenario="test", backend="uinput", points=points))
        assert result.mean_error == 0.0
        assert result.max_error == 0.0
        assert result.p50_error == 0.0
        assert result.p95_error == 0.0
        assert result.bias_x == 0.0
        assert result.bias_y == 0.0

    def test_uniform_1px_bias(self):
        """Consistent -1px,-1px drift (typical of uinput)."""
        points = self._make_points([(1.4, -1, -1)] * 20)
        result = _compute_stats(ScenarioResult(scenario="test", backend="uinput", points=points))
        assert result.mean_error == 1.4
        assert result.max_error == 1.4
        assert result.bias_x == -1.0
        assert result.bias_y == -1.0

    def test_mixed_errors(self):
        points = self._make_points([
            (0.0, 0, 0),
            (1.0, 1, 0),
            (1.4, -1, -1),
            (2.0, -1, 1),
            (5.0, 3, -4),
        ])
        result = _compute_stats(ScenarioResult(scenario="test", backend="uinput", points=points))
        assert result.max_error == 5.0
        assert result.mean_error == 1.9  # (0+1+1.4+2+5)/5 = 1.88 -> 1.9
        assert result.p50_error == 1.4  # median

    def test_empty_points(self):
        result = _compute_stats(ScenarioResult(scenario="test", backend="uinput", points=[]))
        assert result.mean_error == 0.0
        assert result.max_error == 0.0

    def test_single_point(self):
        points = self._make_points([(2.5, 2, 1)])
        result = _compute_stats(ScenarioResult(scenario="test", backend="uinput", points=points))
        assert result.mean_error == 2.5
        assert result.max_error == 2.5
        assert result.p50_error == 2.5
        assert result.p95_error == 2.5


class TestReportFormatting:
    """Verify report output structure."""

    def _make_result(self, scenario, backend, errors):
        points = []
        for i, err in enumerate(errors):
            points.append(PointResult(
                name=f"pt-{i}",
                api_x=100, api_y=100,
                expected_screen_x=200, expected_screen_y=200,
                actual_screen_x=200, actual_screen_y=200,
                error_px=err,
            ))
        result = ScenarioResult(scenario=scenario, backend=backend, points=points)
        return _compute_stats(result)

    def test_report_contains_verdict(self):
        results = [self._make_result("grid", "uinput", [0.0] * 9)]
        report = format_report(results)
        assert "VERDICT:" in report

    def test_pass_scenario(self):
        results = [self._make_result("grid", "uinput", [0.0, 1.0, 1.4])]
        report = format_report(results)
        assert "[PASS]" in report

    def test_fail_scenario(self):
        # More than 20% over 2px = FAIL
        results = [self._make_result("grid", "uinput", [5.0, 5.0, 5.0, 0.0])]
        report = format_report(results)
        assert "[FAIL]" in report

    def test_worst_cases_section(self):
        results = [self._make_result("grid", "xdotool", [0.0, 3.5, 1.0])]
        report = format_report(results)
        assert "WORST CASES:" in report

    def test_systematic_bias_section(self):
        results = [self._make_result("grid", "uinput", [1.4] * 9)]
        report = format_report(results)
        assert "SYSTEMATIC BIAS:" in report

    def test_excellent_verdict_on_perfect(self):
        results = [self._make_result("grid", "uinput", [0.0] * 20)]
        report = format_report(results)
        assert "EXCELLENT" in report

    def test_multiple_scenarios_reported(self):
        results = [
            self._make_result("grid", "uinput", [0.0] * 9),
            self._make_result("edges", "xdotool", [1.0] * 8),
        ]
        report = format_report(results)
        assert "grid" in report
        assert "edges" in report
        assert "TOTAL:" in report
