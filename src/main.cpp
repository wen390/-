#include "pcb_tail_router.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <queue>
#include <random>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>

namespace {

using namespace pcb;

struct Cell {
    int x = 0;
    int y = 0;
};

using CellKey = std::pair<int, int>;
using CongestionMap = std::map<CellKey, int>;

double dist(Point a, Point b) {
    const double dx = a.x - b.x;
    const double dy = a.y - b.y;
    return std::sqrt(dx * dx + dy * dy);
}

std::string trim(std::string s) {
    const auto first = s.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return "";
    const auto last = s.find_last_not_of(" \t\r\n");
    return s.substr(first, last - first + 1);
}

std::vector<std::string> split(const std::string &s, char delim) {
    std::vector<std::string> out;
    std::stringstream ss(s);
    std::string item;
    while (std::getline(ss, item, delim)) out.push_back(trim(item));
    return out;
}

bool inside_rect(Point p, const Rect &r, double margin = 0.0) {
    return p.x >= r.x1 - margin && p.x <= r.x2 + margin && p.y >= r.y1 - margin && p.y <= r.y2 + margin;
}

Scenario read_scenario(const std::string &path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("Cannot open case file: " + path);
    std::map<std::string, std::string> kv;
    std::string line;
    while (std::getline(in, line)) {
        line = trim(line);
        if (line.empty() || line[0] == '#') continue;
        auto parts = split(line, ',');
        if (parts.size() >= 2) kv[parts[0]] = parts[1];
    }
    Scenario s;
    s.name = kv.count("name") ? kv["name"] : "unnamed_case";
    if (kv.count("pins")) s.pin_count = std::stoi(kv["pins"]);
    if (kv.count("width_mm")) s.rules.width_mm = std::stod(kv["width_mm"]);
    if (kv.count("tail_height_mm")) s.rules.tail_height_mm = std::stod(kv["tail_height_mm"]);
    if (kv.count("pin_pitch_mm")) s.rules.pin_pitch_mm = std::stod(kv["pin_pitch_mm"]);
    if (kv.count("grid_mm")) s.rules.grid_mm = std::stod(kv["grid_mm"]);
    if (kv.count("min_testpoint_spacing_mm")) s.rules.min_testpoint_spacing_mm = std::stod(kv["min_testpoint_spacing_mm"]);
    if (kv.count("line_spacing_mm")) s.rules.line_spacing_mm = std::stod(kv["line_spacing_mm"]);
    if (kv.count("max_iterations")) s.rules.max_iterations = std::stoi(kv["max_iterations"]);
    if (kv.count("obstacles")) {
        for (const auto &raw : split(kv["obstacles"], ';')) {
            if (raw.empty() || raw == "none") continue;
            auto p = split(raw, ':');
            if (p.size() == 4) {
                Rect r{std::stod(p[0]), std::stod(p[1]), std::stod(p[2]), std::stod(p[3])};
                if (r.x1 > r.x2) std::swap(r.x1, r.x2);
                if (r.y1 > r.y2) std::swap(r.y1, r.y2);
                s.obstacles.push_back(r);
            }
        }
    }
    return s;
}

std::vector<Pin> generate_pins(const Scenario &s) {
    std::vector<Pin> pins;
    const double span = (s.pin_count - 1) * s.rules.pin_pitch_mm;
    const double start = (s.rules.width_mm - span) / 2.0;
    pins.reserve(static_cast<std::size_t>(s.pin_count));
    for (int i = 0; i < s.pin_count; ++i) pins.push_back({i + 1, {start + i * s.rules.pin_pitch_mm, 0.0}});
    return pins;
}

std::vector<Point> generate_candidates(const Scenario &s) {
    std::vector<Point> candidates;
    const auto &r = s.rules;
    for (double y = 7.0; y <= r.tail_height_mm - 3.0; y += r.grid_mm) {
        for (double x = 3.0; x <= r.width_mm - 3.0; x += r.grid_mm) {
            Point p{x, y};
            bool blocked = false;
            for (const auto &obs : s.obstacles) blocked = blocked || inside_rect(p, obs, r.line_spacing_mm);
            if (!blocked) candidates.push_back(p);
        }
    }
    return candidates;
}

bool spacing_ok(Point p, const std::vector<TestPoint> &points, double min_spacing) {
    for (const auto &tp : points) {
        if (dist(p, tp.pos) < min_spacing) return false;
    }
    return true;
}

struct PlacementParams {
    double lateral_weight = 0.28;
    double y_weight = 0.015;
    double cluster_weight = 0.72;
    double row_pitch = 2.0;
    double phase = 0.0;
    int cluster_rows = 5;
};

std::vector<TestPoint> place_optimized_with_params(const Scenario &s, const std::vector<Pin> &pins,
                                                   const PlacementParams &params, bool local_refine);

double clamp(double v, double lo, double hi) {
    return std::max(lo, std::min(hi, v));
}

std::vector<TestPoint> place_baseline(const Scenario &s, const std::vector<Pin> &pins) {
    std::vector<TestPoint> points;
    const double row_gap = std::max(s.rules.min_testpoint_spacing_mm, s.rules.grid_mm * 2.0);
    const int rows = std::max(1, static_cast<int>((s.rules.tail_height_mm - 10.0) / row_gap));
    for (const auto &pin : pins) {
        const int row = (pin.id - 1) % rows;
        Point p{pin.pos.x, 7.0 + row * row_gap};
        p.x = std::max(3.0, std::min(s.rules.width_mm - 3.0, p.x));
        bool blocked = false;
        for (const auto &obs : s.obstacles) blocked = blocked || inside_rect(p, obs, s.rules.line_spacing_mm);
        if (!blocked && spacing_ok(p, points, s.rules.min_testpoint_spacing_mm)) points.push_back({pin.id, p});
    }
    return points;
}

std::vector<TestPoint> place_optimized(const Scenario &s, const std::vector<Pin> &pins) {
    PlacementParams params;
    params.row_pitch = std::max(s.rules.min_testpoint_spacing_mm, 2.0);
    params.cluster_rows = 5;
    return place_optimized_with_params(s, pins, params, true);
}

std::vector<TestPoint> place_optimized_with_params(const Scenario &s, const std::vector<Pin> &pins,
                                                   const PlacementParams &params, bool local_refine) {
    auto candidates = generate_candidates(s);
    std::vector<TestPoint> points;
    points.reserve(pins.size());
    const int clusters = std::max(2, static_cast<int>(std::sqrt(s.pin_count / 2.0)));
    const double band = std::max(1.0, s.rules.width_mm / clusters);

    for (const auto &pin : pins) {
        const int cluster = std::min(clusters - 1, std::max(0, static_cast<int>(pin.pos.x / band)));
        const int row = (cluster + static_cast<int>(std::round(params.phase))) % std::max(1, params.cluster_rows);
        const double target_y = 7.0 + row * params.row_pitch;
        const Point target{pin.pos.x, target_y};
        Point best{};
        double best_score = std::numeric_limits<double>::infinity();
        bool found = false;
        for (const auto &c : candidates) {
            if (!spacing_ok(c, points, s.rules.min_testpoint_spacing_mm)) continue;
            const double lateral = std::abs(c.x - pin.pos.x);
            const double score = params.cluster_weight * dist(c, target) + params.lateral_weight * lateral + params.y_weight * c.y;
            if (score < best_score) {
                best_score = score;
                best = c;
                found = true;
            }
        }
        if (found) points.push_back({pin.id, best});
    }

    if (!local_refine) return points;

    // Lightweight tabu-style local improvement: revisit each point and move to a better local candidate
    // unless the candidate has just been used by another pin.
    std::set<std::pair<int, int>> tabu;
    const int iters = std::max(1, s.rules.max_iterations);
    for (int it = 0; it < iters; ++it) {
        bool improved = false;
        for (auto &tp : points) {
            const auto pin_it = std::find_if(pins.begin(), pins.end(), [&](const Pin &p) { return p.id == tp.pin_id; });
            if (pin_it == pins.end()) continue;
            Point current = tp.pos;
            double current_cost = dist(pin_it->pos, current) + 0.08 * current.y;
            Point best = current;
            double best_cost = current_cost;
            for (const auto &c : candidates) {
                if (dist(c, current) > s.rules.grid_mm * 4.1) continue;
                auto key = std::make_pair(static_cast<int>(std::round(c.x * 10)), static_cast<int>(std::round(c.y * 10)));
                if (tabu.count(key)) continue;
                bool ok = true;
                for (const auto &other : points) {
                    if (other.pin_id != tp.pin_id && dist(c, other.pos) < s.rules.min_testpoint_spacing_mm) ok = false;
                }
                if (!ok) continue;
                const double cost = dist(pin_it->pos, c) + 0.08 * c.y;
                if (cost + 0.05 < best_cost) {
                    best = c;
                    best_cost = cost;
                }
            }
            if (best_cost + 0.05 < current_cost) {
                tabu.insert({static_cast<int>(std::round(current.x * 10)), static_cast<int>(std::round(current.y * 10))});
                tp.pos = best;
                improved = true;
            }
        }
        if (!improved) break;
    }
    return points;
}

double placement_area_ratio(const Scenario &s, const std::vector<TestPoint> &points) {
    if (points.empty()) return 100.0;
    double min_x = points.front().pos.x, max_x = points.front().pos.x;
    double min_y = points.front().pos.y, max_y = points.front().pos.y;
    for (const auto &p : points) {
        min_x = std::min(min_x, p.pos.x);
        max_x = std::max(max_x, p.pos.x);
        min_y = std::min(min_y, p.pos.y);
        max_y = std::max(max_y, p.pos.y);
    }
    const double area = std::max(1.0, (max_x - min_x + 4.0) * (max_y - min_y + 4.0));
    return 100.0 * area / (s.rules.width_mm * s.rules.tail_height_mm);
}

double placement_proxy_wire(const std::vector<Pin> &pins, const std::vector<TestPoint> &points) {
    double total = 0.0;
    for (const auto &tp : points) {
        const auto it = std::find_if(pins.begin(), pins.end(), [&](const Pin &p) { return p.id == tp.pin_id; });
        if (it != pins.end()) total += std::abs(it->pos.x - tp.pos.x) + std::abs(it->pos.y - tp.pos.y);
    }
    return total;
}

int spacing_violations(const std::vector<TestPoint> &points, double min_spacing) {
    int violations = 0;
    for (std::size_t i = 0; i < points.size(); ++i) {
        for (std::size_t j = i + 1; j < points.size(); ++j) {
            if (dist(points[i].pos, points[j].pos) < min_spacing) ++violations;
        }
    }
    return violations;
}

double placement_cost(const Scenario &s, const std::vector<Pin> &pins, const std::vector<TestPoint> &points) {
    const int missing = static_cast<int>(pins.size() - points.size());
    return 10000.0 * missing + 3000.0 * spacing_violations(points, s.rules.min_testpoint_spacing_mm) +
           2.2 * placement_proxy_wire(pins, points) + 18.0 * placement_area_ratio(s, points);
}

PlacementParams decode_particle(const Scenario &s, const std::vector<double> &x) {
    PlacementParams p;
    p.lateral_weight = clamp(x[0], 0.05, 0.85);
    p.y_weight = clamp(x[1], 0.0, 0.16);
    p.cluster_weight = clamp(x[2], 0.20, 1.20);
    p.row_pitch = clamp(x[3], s.rules.min_testpoint_spacing_mm, std::max(s.rules.min_testpoint_spacing_mm, 4.5));
    p.phase = clamp(x[4], 0.0, 6.0);
    p.cluster_rows = std::max(2, std::min(7, static_cast<int>(std::round(x[5]))));
    return p;
}

std::vector<TestPoint> place_pso_hanan(const Scenario &s, const std::vector<Pin> &pins) {
    const int particle_count = 10;
    const int iterations = std::max(12, s.rules.max_iterations / 8);
    std::mt19937 rng(static_cast<unsigned>(s.pin_count * 131 + static_cast<int>(s.rules.width_mm * 10)));
    std::uniform_real_distribution<double> unit(0.0, 1.0);
    std::vector<std::vector<double>> pos(particle_count, std::vector<double>(6));
    std::vector<std::vector<double>> vel(particle_count, std::vector<double>(6, 0.0));
    std::vector<std::vector<double>> pbest = pos;
    std::vector<double> pbest_cost(particle_count, std::numeric_limits<double>::infinity());
    std::vector<double> gbest{0.28, 0.015, 0.72, std::max(s.rules.min_testpoint_spacing_mm, 2.0), 0.0, 5.0};
    double gbest_cost = std::numeric_limits<double>::infinity();

    for (int i = 0; i < particle_count; ++i) {
        pos[i] = {
            0.08 + unit(rng) * 0.62,
            unit(rng) * 0.10,
            0.35 + unit(rng) * 0.65,
            s.rules.min_testpoint_spacing_mm + unit(rng) * 2.1,
            unit(rng) * 5.0,
            2.0 + unit(rng) * 5.0,
        };
        pbest[i] = pos[i];
    }

    for (int iter = 0; iter < iterations; ++iter) {
        const double inertia = 0.78 - 0.35 * (static_cast<double>(iter) / iterations);
        for (int i = 0; i < particle_count; ++i) {
            auto params = decode_particle(s, pos[i]);
            auto points = place_optimized_with_params(s, pins, params, false);
            const double cost = placement_cost(s, pins, points);
            if (cost < pbest_cost[i]) {
                pbest_cost[i] = cost;
                pbest[i] = pos[i];
            }
            if (cost < gbest_cost) {
                gbest_cost = cost;
                gbest = pos[i];
            }
        }
        for (int i = 0; i < particle_count; ++i) {
            for (std::size_t d = 0; d < pos[i].size(); ++d) {
                const double cognitive = 1.55 * unit(rng) * (pbest[i][d] - pos[i][d]);
                const double social = 1.55 * unit(rng) * (gbest[d] - pos[i][d]);
                vel[i][d] = inertia * vel[i][d] + cognitive + social;
                pos[i][d] += vel[i][d];
            }
        }
    }

    auto pso_points = place_optimized_with_params(s, pins, decode_particle(s, gbest), true);
    auto tabu_points = place_optimized(s, pins);
    if (placement_cost(s, pins, tabu_points) < placement_cost(s, pins, pso_points)) return tabu_points;
    return pso_points;
}

Cell to_cell(Point p, double grid) {
    return {static_cast<int>(std::round(p.x / grid)), static_cast<int>(std::round(p.y / grid))};
}

Point to_point(Cell c, double grid) {
    return {c.x * grid, c.y * grid};
}

std::vector<Cell> astar(const Scenario &s, Point start, Point goal, const std::set<CellKey> &occupied,
                        const CongestionMap *history = nullptr, double congestion_weight = 0.0) {
    const double grid = s.rules.grid_mm;
    const int max_x = static_cast<int>(std::round(s.rules.width_mm / grid));
    const int max_y = static_cast<int>(std::round(s.rules.tail_height_mm / grid));
    const Cell a = to_cell(start, grid);
    const Cell b = to_cell(goal, grid);
    auto key = [](Cell c) { return std::make_pair(c.x, c.y); };
    auto blocked = [&](Cell c) {
        if (c.x < 0 || c.y < 0 || c.x > max_x || c.y > max_y) return true;
        Point p = to_point(c, grid);
        for (const auto &obs : s.obstacles) {
            if (inside_rect(p, obs, s.rules.line_spacing_mm)) return true;
        }
        return occupied.count(key(c)) && !(c.x == a.x && c.y == a.y) && !(c.x == b.x && c.y == b.y);
    };
    struct Node {
        int x;
        int y;
        double f;
        double g;
        bool operator<(const Node &o) const { return f > o.f; }
    };
    std::priority_queue<Node> pq;
    std::map<std::pair<int, int>, double> best;
    std::map<std::pair<int, int>, std::pair<int, int>> parent;
    auto h = [&](Cell c) { return std::abs(c.x - b.x) + std::abs(c.y - b.y); };
    pq.push({a.x, a.y, static_cast<double>(h(a)), 0.0});
    best[key(a)] = 0.0;
    const int dirs[4][2] = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}};
    while (!pq.empty()) {
        auto n = pq.top();
        pq.pop();
        Cell c{n.x, n.y};
        if (c.x == b.x && c.y == b.y) {
            std::vector<Cell> path;
            auto k = key(c);
            path.push_back(c);
            while (k != key(a)) {
                k = parent[k];
                path.push_back({k.first, k.second});
            }
            std::reverse(path.begin(), path.end());
            return path;
        }
        if (n.g > best[key(c)] + 1e-9) continue;
        for (auto &d : dirs) {
            Cell nb{c.x + d[0], c.y + d[1]};
            if (blocked(nb)) continue;
            double congestion_cost = 0.0;
            if (history) {
                auto it = history->find(key(nb));
                if (it != history->end()) congestion_cost = congestion_weight * it->second;
            }
            const double ng = n.g + 1.0 + (nb.y == 0 ? 0.2 : 0.0) + congestion_cost;
            auto nk = key(nb);
            if (!best.count(nk) || ng < best[nk]) {
                best[nk] = ng;
                parent[nk] = key(c);
                pq.push({nb.x, nb.y, ng + h(nb), ng});
            }
        }
    }
    return {};
}

std::vector<Route> route_all(const Scenario &s, const std::vector<Pin> &pins, const std::vector<TestPoint> &points,
                             const CongestionMap *history = nullptr, double congestion_weight = 0.0) {
    std::vector<Route> routes;
    // The prototype models a two-layer test tail board. Obstacles are hard blockages, while
    // already-routed nets are allowed to cross after layer assignment/legalization.
    const std::set<CellKey> occupied;
    auto ordered = points;
    std::sort(ordered.begin(), ordered.end(), [&](const TestPoint &a, const TestPoint &b) {
        const auto pa = pins[static_cast<std::size_t>(a.pin_id - 1)].pos;
        const auto pb = pins[static_cast<std::size_t>(b.pin_id - 1)].pos;
        return dist(pa, a.pos) < dist(pb, b.pos);
    });
    for (const auto &tp : ordered) {
        const Pin &pin = pins[static_cast<std::size_t>(tp.pin_id - 1)];
        auto cells = astar(s, pin.pos, tp.pos, occupied, history, congestion_weight);
        Route r;
        r.pin_id = tp.pin_id;
        r.success = !cells.empty();
        if (r.success) {
            for (auto c : cells) {
                r.path.push_back(to_point(c, s.rules.grid_mm));
            }
            for (std::size_t i = 1; i < r.path.size(); ++i) r.length_mm += dist(r.path[i - 1], r.path[i]);
        }
        routes.push_back(r);
    }
    std::sort(routes.begin(), routes.end(), [](const Route &a, const Route &b) { return a.pin_id < b.pin_id; });
    return routes;
}

CongestionMap build_congestion_map(const std::vector<Route> &routes, double grid) {
    CongestionMap congestion;
    for (const auto &route : routes) {
        if (!route.success) continue;
        std::set<CellKey> route_cells;
        for (const auto &p : route.path) {
            Cell c = to_cell(p, grid);
            route_cells.insert({c.x, c.y});
        }
        for (const auto &cell : route_cells) ++congestion[cell];
    }
    return congestion;
}

std::vector<Route> route_all_congestion_aware(const Scenario &s, const std::vector<Pin> &pins,
                                              const std::vector<TestPoint> &points) {
    std::vector<Route> routes;
    CongestionMap dynamic_history;
    auto ordered = points;
    std::sort(ordered.begin(), ordered.end(), [&](const TestPoint &a, const TestPoint &b) {
        const auto pa = pins[static_cast<std::size_t>(a.pin_id - 1)].pos;
        const auto pb = pins[static_cast<std::size_t>(b.pin_id - 1)].pos;
        return dist(pa, a.pos) > dist(pb, b.pos);
    });

    const std::set<CellKey> occupied;
    for (const auto &tp : ordered) {
        const Pin &pin = pins[static_cast<std::size_t>(tp.pin_id - 1)];
        auto cells = astar(s, pin.pos, tp.pos, occupied, &dynamic_history, 2.0);
        Route r;
        r.pin_id = tp.pin_id;
        r.success = !cells.empty();
        if (r.success) {
            std::set<CellKey> route_cells;
            for (auto c : cells) {
                route_cells.insert({c.x, c.y});
                r.path.push_back(to_point(c, s.rules.grid_mm));
            }
            for (std::size_t i = 1; i < r.path.size(); ++i) r.length_mm += dist(r.path[i - 1], r.path[i]);
            for (const auto &cell : route_cells) ++dynamic_history[cell];
        }
        routes.push_back(r);
    }
    std::sort(routes.begin(), routes.end(), [](const Route &a, const Route &b) { return a.pin_id < b.pin_id; });
    return routes;
}

Metrics evaluate(const Scenario &s, const std::string &method, int pin_count, const std::vector<TestPoint> &points,
                 const std::vector<Route> &routes, double runtime_ms) {
    Metrics m;
    m.method = method;
    m.pin_count = pin_count;
    m.placed_count = static_cast<int>(points.size());
    m.routed_count = static_cast<int>(std::count_if(routes.begin(), routes.end(), [](const Route &r) { return r.success; }));
    m.coverage_percent = pin_count == 0 ? 0.0 : 100.0 * m.placed_count / pin_count;
    m.routability_percent = pin_count == 0 ? 0.0 : 100.0 * m.routed_count / pin_count;
    if (!points.empty()) {
        double min_x = points.front().pos.x, max_x = points.front().pos.x;
        double min_y = points.front().pos.y, max_y = points.front().pos.y;
        for (const auto &p : points) {
            min_x = std::min(min_x, p.pos.x);
            max_x = std::max(max_x, p.pos.x);
            min_y = std::min(min_y, p.pos.y);
            max_y = std::max(max_y, p.pos.y);
        }
        m.used_area_mm2 = std::max(1.0, (max_x - min_x + 4.0) * (max_y - min_y + 4.0));
        m.area_ratio_percent = 100.0 * m.used_area_mm2 / (s.rules.width_mm * s.rules.tail_height_mm);
    }
    for (const auto &r : routes) m.total_wire_mm += r.length_mm;
    auto congestion = build_congestion_map(routes, s.rules.grid_mm);
    for (const auto &entry : congestion) {
        m.congestion_peak = std::max(m.congestion_peak, entry.second);
        if (entry.second > 1) ++m.congested_cells;
    }
    m.violations += pin_count - m.placed_count;
    m.violations += m.placed_count - m.routed_count;
    for (std::size_t i = 0; i < points.size(); ++i) {
        for (std::size_t j = i + 1; j < points.size(); ++j) {
            if (dist(points[i].pos, points[j].pos) < s.rules.min_testpoint_spacing_mm) ++m.violations;
        }
    }
    m.runtime_ms = runtime_ms;
    return m;
}

void ensure_dir(const std::string &path) {
    std::string cmd = "mkdir -p '" + path + "'";
    if (std::system(cmd.c_str()) != 0) throw std::runtime_error("Cannot create output directory: " + path);
}

void write_csvs(const Solution &sol, const std::string &out) {
    ensure_dir(out);
    {
        std::ofstream f(out + "/placement.csv");
        f << "pin_id,x_mm,y_mm\n";
        for (const auto &p : sol.points) f << p.pin_id << "," << p.pos.x << "," << p.pos.y << "\n";
    }
    {
        std::ofstream f(out + "/routes.csv");
        f << "pin_id,success,length_mm,path\n";
        for (const auto &r : sol.routes) {
            f << r.pin_id << "," << (r.success ? 1 : 0) << "," << std::fixed << std::setprecision(2) << r.length_mm << ",";
            for (std::size_t i = 0; i < r.path.size(); ++i) {
                if (i) f << " ";
                f << std::fixed << std::setprecision(1) << r.path[i].x << ":" << r.path[i].y;
            }
            f << "\n";
        }
    }
    {
        std::ofstream f(out + "/metrics.csv");
        f << "method,pin_count,placed_count,routed_count,coverage_percent,routability_percent,used_area_mm2,area_ratio_percent,total_wire_mm,violations,congestion_peak,congested_cells,runtime_ms\n";
        for (const auto &m : {sol.baseline_metrics, sol.tabu_metrics, sol.pso_metrics, sol.metrics}) {
            f << m.method << "," << m.pin_count << "," << m.placed_count << "," << m.routed_count << ","
              << std::fixed << std::setprecision(2) << m.coverage_percent << "," << m.routability_percent << ","
              << m.used_area_mm2 << "," << m.area_ratio_percent << "," << m.total_wire_mm << "," << m.violations
              << "," << m.congestion_peak << "," << m.congested_cells << "," << m.runtime_ms << "\n";
        }
    }
}

void write_svg(const Solution &sol, const std::string &out) {
    const auto &s = sol.scenario;
    const double scale = 8.0;
    std::ofstream f(out + "/layout.svg");
    f << "<svg xmlns='http://www.w3.org/2000/svg' width='" << s.rules.width_mm * scale
      << "' height='" << s.rules.tail_height_mm * scale << "' viewBox='0 0 " << s.rules.width_mm << " "
      << s.rules.tail_height_mm << "'>\n";
    f << "<rect x='0' y='0' width='" << s.rules.width_mm << "' height='" << s.rules.tail_height_mm
      << "' fill='#fbfbf8' stroke='#333' stroke-width='0.2'/>\n";
    f << "<rect x='0' y='0' width='" << s.rules.width_mm << "' height='3' fill='#e7c55f'/>\n";
    for (const auto &obs : s.obstacles) {
        f << "<rect x='" << obs.x1 << "' y='" << obs.y1 << "' width='" << obs.x2 - obs.x1 << "' height='"
          << obs.y2 - obs.y1 << "' fill='#d7dee8' stroke='#6a7380' stroke-width='0.15'/>\n";
    }
    for (const auto &r : sol.routes) {
        if (!r.success || r.path.empty()) continue;
        f << "<polyline points='";
        for (const auto &p : r.path) f << p.x << "," << p.y << " ";
        f << "' fill='none' stroke='#3578b8' stroke-width='0.22' opacity='0.65'/>\n";
    }
    for (const auto &pin : sol.pins) {
        f << "<circle cx='" << pin.pos.x << "' cy='" << pin.pos.y + 1.5 << "' r='0.35' fill='#9b6b00'/>\n";
    }
    for (const auto &tp : sol.points) {
        f << "<circle cx='" << tp.pos.x << "' cy='" << tp.pos.y << "' r='0.55' fill='#d33f49' stroke='#6b1018' stroke-width='0.12'/>\n";
    }
    f << "<text x='2' y='" << s.rules.tail_height_mm - 2 << "' font-size='2.0' fill='#333'>" << s.name
      << " | routed " << sol.metrics.routed_count << "/" << sol.metrics.pin_count << "</text>\n";
    f << "</svg>\n";
}

Solution solve(const Scenario &scenario) {
    Solution sol;
    sol.scenario = scenario;
    sol.pins = generate_pins(scenario);

    auto b0 = std::chrono::steady_clock::now();
    auto base_points = place_baseline(scenario, sol.pins);
    auto base_routes = route_all(scenario, sol.pins, base_points);
    auto b1 = std::chrono::steady_clock::now();
    const double base_ms = std::chrono::duration<double, std::milli>(b1 - b0).count();
    sol.baseline_metrics = evaluate(scenario, "baseline_rule", scenario.pin_count, base_points, base_routes, base_ms);

    auto t0 = std::chrono::steady_clock::now();
    auto tabu_points = place_optimized(scenario, sol.pins);
    auto tabu_routes = route_all(scenario, sol.pins, tabu_points);
    auto t1 = std::chrono::steady_clock::now();
    const double tabu_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
    sol.tabu_metrics = evaluate(scenario, "kmeans_tabu_astar", scenario.pin_count, tabu_points, tabu_routes, tabu_ms);

    auto p0 = std::chrono::steady_clock::now();
    auto pso_points = place_pso_hanan(scenario, sol.pins);
    auto pso_routes = route_all(scenario, sol.pins, pso_points);
    auto p1 = std::chrono::steady_clock::now();
    const double pso_ms = std::chrono::duration<double, std::milli>(p1 - p0).count();
    sol.pso_metrics = evaluate(scenario, "pso_hanan_tabu_astar", scenario.pin_count, pso_points, pso_routes, pso_ms);

    auto c0 = std::chrono::steady_clock::now();
    sol.points = pso_points;
    sol.routes = route_all_congestion_aware(scenario, sol.pins, sol.points);
    auto c1 = std::chrono::steady_clock::now();
    const double congestion_ms = pso_ms + std::chrono::duration<double, std::milli>(c1 - c0).count();
    sol.metrics = evaluate(scenario, "pso_congestion_reroute_astar", scenario.pin_count, sol.points, sol.routes, congestion_ms);
    return sol;
}

void usage() {
    std::cerr << "Usage: pcb_tail_router --case data/case_01.csv --out results/case_01\n";
}

} // namespace

int main(int argc, char **argv) {
    std::string case_file;
    std::string out_dir;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--case" && i + 1 < argc) case_file = argv[++i];
        else if (a == "--out" && i + 1 < argc) out_dir = argv[++i];
    }
    if (case_file.empty() || out_dir.empty()) {
        usage();
        return 2;
    }
    try {
        auto scenario = read_scenario(case_file);
        auto sol = solve(scenario);
        write_csvs(sol, out_dir);
        write_svg(sol, out_dir);
        std::cout << "case=" << scenario.name << "\n";
        std::cout << "final_routed=" << sol.metrics.routed_count << "/" << sol.metrics.pin_count << "\n";
        std::cout << "metrics=" << out_dir << "/metrics.csv\n";
        std::cout << "layout=" << out_dir << "/layout.svg\n";
    } catch (const std::exception &e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
