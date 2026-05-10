#pragma once

#include <string>
#include <vector>

namespace pcb {

struct Point {
    double x = 0.0;
    double y = 0.0;
};

struct Rect {
    double x1 = 0.0;
    double y1 = 0.0;
    double x2 = 0.0;
    double y2 = 0.0;
};

struct DesignRules {
    double width_mm = 90.0;
    double tail_height_mm = 42.0;
    double pin_pitch_mm = 0.8;
    double grid_mm = 1.0;
    double min_testpoint_spacing_mm = 2.0;
    double line_spacing_mm = 0.5;
    int max_iterations = 80;
};

struct Scenario {
    std::string name;
    int pin_count = 40;
    DesignRules rules;
    std::vector<Rect> obstacles;
};

struct Pin {
    int id = 0;
    Point pos;
};

struct TestPoint {
    int pin_id = 0;
    Point pos;
};

struct Route {
    int pin_id = 0;
    bool success = false;
    double length_mm = 0.0;
    std::vector<Point> path;
};

struct Metrics {
    std::string method;
    int pin_count = 0;
    int placed_count = 0;
    int routed_count = 0;
    double coverage_percent = 0.0;
    double routability_percent = 0.0;
    double used_area_mm2 = 0.0;
    double area_ratio_percent = 0.0;
    double total_wire_mm = 0.0;
    int violations = 0;
    int congestion_peak = 0;
    int congested_cells = 0;
    double runtime_ms = 0.0;
};

struct Solution {
    Scenario scenario;
    std::vector<Pin> pins;
    std::vector<TestPoint> points;
    std::vector<Route> routes;
    Metrics metrics;
    Metrics baseline_metrics;
    Metrics tabu_metrics;
    Metrics pso_metrics;
};

} // namespace pcb
