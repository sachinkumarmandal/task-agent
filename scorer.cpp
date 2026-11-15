// scorer.cpp - fast priority scorer for the personal task agent.
//
// Input  (stdin, one task per line, tab-separated):
//   id <TAB> priority(1-5) <TAB> hours_until_due (or "none") <TAB> est_minutes
// Output (stdout, best first):
//   id <TAB> score
//
// Higher score = do it sooner. Overdue and soon-due tasks get an urgency boost,
// short tasks get a small "quick win" bonus, long ones a small penalty.

#include <algorithm>
#include <cmath>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

struct Scored {
    std::string id;
    double score;
};

static double urgency(double hours) {
    if (hours < 0) return 50.0 + std::min(-hours, 72.0) * 0.25;  // overdue: big boost
    if (hours <= 24) return 40.0 - hours * 0.5;                   // due today
    if (hours <= 24 * 7) return 28.0 - (hours / 24.0) * 3.0;      // due this week
    return std::max(0.0, 7.0 - std::log2(hours / 24.0));          // far away
}

int main() {
    std::ios::sync_with_stdio(false);
    std::vector<Scored> out;
    std::string line;

    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        std::vector<std::string> f;
        std::stringstream ss(line);
        std::string cell;
        while (std::getline(ss, cell, '\t')) f.push_back(cell);
        if (f.size() < 4) continue;

        double priority = 3, hours = 1e9, minutes = 30;
        try {
            priority = std::stod(f[1]);
            if (f[2] != "none" && !f[2].empty()) hours = std::stod(f[2]);
            minutes = std::stod(f[3]);
        } catch (...) {
            continue;  // skip malformed lines
        }

        double score = priority * 12.0;
        if (hours < 1e8) score += urgency(hours);
        if (minutes <= 15) score += 6.0;                 // quick win
        else if (minutes > 120) score -= std::min((minutes - 120) / 60.0, 5.0);
        out.push_back({f[0], score});
    }

    std::sort(out.begin(), out.end(),
              [](const Scored& a, const Scored& b) { return a.score > b.score; });

    for (const auto& s : out) std::cout << s.id << '\t' << s.score << '\n';
    return 0;
}
