import Charts
import SwiftUI

/// What Vox's brains cost and how fast they answer. Reply time comes first: it's what you feel.
struct ActivityView: View {
    @Environment(AppModel.self) private var model
    @State private var summary: UsageSummary?
    @State private var recent: [UsageEvent] = []
    @State private var budget: BudgetStatus?
    @State private var error: String?

    var body: some View {
        RequiresEngine {
            content
                .toolbar {
                    ToolbarItem(placement: .primaryAction) {
                        Button("Refresh", systemImage: "arrow.clockwise") { Task { await load() } }.help("Refresh")
                    }
                }
                .task {
                    // Keep the numbers current while the page is open.
                    while !Task.isCancelled {
                        await load()
                        try? await Task.sleep(for: .seconds(30))
                    }
                }
        }
    }

    @ViewBuilder
    private var content: some View {
        if let summary {
            if summary.totals.calls == 0 {
                ContentUnavailableView("No activity yet", systemImage: "chart.bar.xaxis",
                                       description: Text("Each time Vox asks a brain for help, the cost and reply time show up here."))
            } else {
                PageScroll {
                    if let error { ErrorLine(text: error) }
                    Tiles(summary: summary, recent: recent, budget: budget)
                    DailyCost(days: summary.byDay)
                    ByModel(models: summary.byModel, recent: recent)
                    RecentCalls(events: recent)
                }
            }
        } else if let error {
            ContentUnavailableView {
                Label("Couldn't load activity", systemImage: "exclamationmark.triangle")
            } description: { Text(error) } actions: { Button("Try Again") { Task { await load() } } }
        } else {
            ProgressView().controlSize(.small).frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func load() async {
        do {
            async let s: UsageSummary = model.api.get("usage/summary")
            async let r: [UsageEvent] = model.api.get("usage/recent?limit=200")
            (summary, recent) = try await (s, r)
            error = nil
        } catch { self.error = error.localizedDescription }
        // Budget answers {error} when unavailable; the page works without it.
        budget = try? await model.api.get("budget")
    }
}

// MARK: Tiles

private struct Tiles: View {
    var summary: UsageSummary
    var recent: [UsageEvent]
    var budget: BudgetStatus?

    var body: some View {
        let t = summary.totals
        let times = recent.map(\.latencyMs).filter { $0 > 0 }
        HStack(spacing: Metrics.gap) {
            StatTile(title: "Typical reply", value: Fmt.median(times).map(Fmt.latency) ?? "–",
                     detail: times.isEmpty ? "No recent calls" : "Middle of the last \(times.count) calls")
            StatTile(title: "Spent this month", value: Fmt.usd(budget?.spentUsd ?? monthCost),
                     detail: budgetDetail, detailTint: budgetTint)
            StatTile(title: "Calls", value: t.calls.formatted(), detail: "All time")
            StatTile(title: "Tokens", value: Fmt.compact(t.inputTokens + t.outputTokens),
                     detail: "\(Fmt.compact(t.inputTokens)) in · \(Fmt.compact(t.outputTokens)) out")
        }
        .fixedSize(horizontal: false, vertical: true)
    }

    private var monthCost: Double {
        let month = String(LocalISO.string(.now).prefix(7))
        return summary.byDay.filter { $0.date.hasPrefix(month) }.reduce(0) { $0 + $1.costUsd }
    }

    private var budgetDetail: String {
        guard let b = budget, b.state != "none", b.budgetUsd > 0 else { return "No monthly limit set" }
        return "\(Int(b.percent.rounded()))% of \(Fmt.usd(b.budgetUsd)) budget"
    }

    private var budgetTint: Color {
        switch budget?.state {
        case "warn": .orange
        case "over": .red
        default: .secondary
        }
    }
}

private struct StatTile: View {
    var title: String
    var value: String
    var detail: String
    var detailTint: Color = .secondary

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.callout).foregroundStyle(.secondary)
                Text(value).font(.title.weight(.semibold)).monospacedDigit().lineLimit(1).minimumScaleFactor(0.7)
                Text(detail).font(.caption).foregroundStyle(detailTint).lineLimit(2)
                Spacer(minLength: 0)
            }
            .frame(maxHeight: .infinity, alignment: .topLeading)
        }
    }
}

// MARK: Daily cost

private struct DailyCost: View {
    var days: [UsageByDay]
    private static let span = 30

    /// The last 30 days, with empty days filled in so the bars line up with the calendar.
    private var series: [(date: Date, cost: Double)] {
        let cal = Calendar.current
        let today = cal.startOfDay(for: .now)
        let byDate = Dictionary(days.map { ($0.date, $0.costUsd) }, uniquingKeysWith: +)
        return (0..<Self.span).reversed().compactMap { back in
            guard let d = cal.date(byAdding: .day, value: -back, to: today) else { return nil }
            return (d, byDate[String(LocalISO.string(d).prefix(10))] ?? 0)
        }
    }

    var body: some View {
        let s = series
        Card {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline) {
                    Text("Daily cost").font(.headline)
                    Spacer()
                    Text("\(Fmt.usd(s.reduce(0) { $0 + $1.cost })) in the last \(Self.span) days")
                        .font(.callout).foregroundStyle(.secondary)
                }
                Chart(s, id: \.date) { d in
                    BarMark(x: .value("Day", d.date, unit: .day), y: .value("Cost", d.cost))
                        .foregroundStyle(Color.accentColor.gradient)
                        .cornerRadius(3)
                }
                .chartXAxis {
                    AxisMarks(values: .stride(by: .day, count: 7)) { _ in
                        AxisGridLine()
                        AxisValueLabel(format: .dateTime.day().month(.abbreviated))
                    }
                }
                .chartYAxis {
                    AxisMarks(position: .leading, values: .automatic(desiredCount: 4)) { v in
                        AxisGridLine()
                        AxisValueLabel { if let x = v.as(Double.self) { Text(Fmt.usd(x, axis: true)) } }
                    }
                }
                .frame(height: 170)
            }
        }
    }
}

// MARK: By model

private struct ByModel: View {
    var models: [UsageByModel]
    var recent: [UsageEvent]

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline) {
                    Text("By brain").font(.headline)
                    Spacer()
                    Text("Typical reply is from the last \(recent.count) calls")
                        .font(.callout).foregroundStyle(.secondary)
                }
                Grid(alignment: .leading, horizontalSpacing: 20, verticalSpacing: 9) {
                    GridRow {
                        Text("Model")
                        Text("Typical reply").gridColumnAlignment(.trailing)
                        Text("Calls").gridColumnAlignment(.trailing)
                        Text("Tokens").gridColumnAlignment(.trailing)
                        Text("Cost").gridColumnAlignment(.trailing)
                    }
                    .font(.caption).foregroundStyle(.secondary)
                    ForEach(models) { m in
                        Divider()
                        GridRow {
                            VStack(alignment: .leading, spacing: 1) {
                                Text(BrainNames.model(m.model)).lineLimit(1)
                                Text(BrainNames.provider(m.provider, model: m.model)).font(.caption).foregroundStyle(.secondary)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            LatencyText(ms: typical(m))
                            Text(m.calls.formatted())
                            Text(Fmt.compact(m.inputTokens + m.outputTokens))
                            Text(Fmt.usd(m.costUsd))
                        }
                        .monospacedDigit()
                    }
                }
            }
        }
    }

    /// Median reply time for this model across the recent calls (nil if it hasn't been used lately).
    private func typical(_ m: UsageByModel) -> Double? {
        Fmt.median(recent.filter { $0.model == m.model && $0.provider == m.provider && $0.latencyMs > 0 }.map(\.latencyMs))
    }
}

// MARK: Recent calls

private struct RecentCalls: View {
    var events: [UsageEvent]
    @State private var order = [KeyPathComparator(\UsageEvent.ts, order: .reverse)]

    var body: some View {
        VStack(alignment: .leading, spacing: Metrics.tight) {
            HStack(alignment: .firstTextBaseline) {
                Text("Recent calls").font(.headline)
                Spacer()
                Text("Click a column to sort. Sort by reply time to find the slow ones.")
                    .font(.callout).foregroundStyle(.secondary)
            }
            .padding(.horizontal, Metrics.gap)
            Table(events.sorted(using: order), sortOrder: $order) {
                TableColumn("When", value: \.ts) { e in
                    Text(ISO8601.parse(e.ts)?.friendly ?? "").foregroundStyle(.secondary)
                }
                .width(min: 80, ideal: 100)
                TableColumn("Model", value: \.model) { e in Text(BrainNames.model(e.model)) }
                    .width(min: 120, ideal: 160)
                TableColumn("For", value: \.kind) { e in Text(Fmt.purpose(e)).foregroundStyle(.secondary) }
                    .width(min: 80, ideal: 110)
                TableColumn("Tokens", value: \.inputTokens) { e in
                    Text("\(e.inputTokens.formatted()) → \(e.outputTokens.formatted())").monospacedDigit()
                }
                .width(min: 90, ideal: 110)
                TableColumn("Reply time", value: \.latencyMs) { e in LatencyText(ms: e.latencyMs > 0 ? e.latencyMs : nil) }
                    .width(min: 80, ideal: 90)
                TableColumn("Cost", value: \.costUsd) { e in Text(Fmt.usd(e.costUsd)).monospacedDigit() }
                    .width(min: 60, ideal: 70)
            }
            .frame(height: 320)
            .clipShape(RoundedRectangle(cornerRadius: Metrics.radius, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: Metrics.radius, style: .continuous).strokeBorder(.separator.opacity(0.5)))
        }
    }
}

/// A reply time with a dot that says at a glance whether it felt quick.
private struct LatencyText: View {
    var ms: Double?

    var body: some View {
        if let ms {
            HStack(spacing: 5) {
                Circle().fill(color(ms)).frame(width: 6, height: 6)
                Text(Fmt.latency(ms)).monospacedDigit()
            }
            .help(ms < 1500 ? "Quick" : ms < 3000 ? "Noticeable wait" : "Slow")
        } else {
            Text("–").foregroundStyle(.tertiary)
        }
    }

    private func color(_ ms: Double) -> Color { ms < 1500 ? .green : ms < 3000 ? .orange : .red }
}

// MARK: Formatting

private enum Fmt {
    /// Dollars in the user's number style. Fractions of a cent get more digits so tiny calls aren't "$0.00".
    static func usd(_ v: Double, axis: Bool = false) -> String {
        if v == 0 && axis { return "$0" }
        let digits = abs(v) >= 0.01 ? 2 : axis ? 3 : 4
        return "$" + v.formatted(.number.precision(.fractionLength(digits)))
    }

    static func latency(_ ms: Double) -> String {
        ms < 1000 ? "\(Int(ms.rounded())) ms" : (ms / 1000).formatted(.number.precision(.fractionLength(1))) + " s"
    }

    static func compact(_ n: Int) -> String { n.formatted(.number.notation(.compactName)) }

    static func median(_ xs: [Double]) -> Double? {
        guard !xs.isEmpty else { return nil }
        let s = xs.sorted()
        return s.count % 2 == 1 ? s[s.count / 2] : (s[s.count / 2 - 1] + s[s.count / 2]) / 2
    }

    /// "Quick reply", "Hard question", "Command", "Screen".
    static func purpose(_ e: UsageEvent) -> String {
        switch e.kind {
        case "command": "Command"
        case "vision": "Looking at screen"
        case "rewrite": "Rewriting text"
        default: e.brain == "big" ? "Hard question" : "Quick reply"
        }
    }
}

private struct ErrorLine: View {
    var text: String
    var body: some View {
        Label(text, systemImage: "exclamationmark.triangle.fill").font(.callout).foregroundStyle(.red)
    }
}
