import SwiftUI

/// Insights → Testing: every feature that's been built, how to try it, how far it has been checked,
/// and the user's own verdict and notes. Replaces the hand-edited to-test.md checklist.
struct TestingView: View {
    @Environment(AppModel.self) private var model
    @State private var features: [Feature] = []
    @State private var issues: [LoggedIssue] = []
    @State private var filter: Filter = .toTest
    @State private var error: String?
    @State private var loaded = false

    enum Filter: String, CaseIterable, Identifiable {
        case toTest = "To Test", problems = "Problems", all = "All"
        var id: String { rawValue }
    }

    private var shown: [Feature] {
        switch filter {
        case .toTest: features.filter { $0.status == "untested" }
        case .problems: features.filter { $0.status == "broken" || $0.status == "partly" }
        case .all: features
        }
    }

    private var areas: [String] {
        var seen: [String] = []
        for f in shown where !seen.contains(f.area) { seen.append(f.area) }
        return seen
    }

    var body: some View {
        RequiresEngine {
            PageScroll {
                summary
                if !issues.filter({ $0.status == "open" }).isEmpty {
                    SectionLabel("Logged issues")
                    Card(padding: 0) {
                        VStack(spacing: 0) {
                            let open = issues.filter { $0.status == "open" }
                            ForEach(Array(open.enumerated()), id: \.element.id) { i, issue in
                                IssueRow(issue: issue) { Task { await resolve(issue) } }
                                if i < open.count - 1 { Divider().padding(.leading, Metrics.gap) }
                            }
                        }
                    }
                }
                if let error {
                    Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red).font(.callout)
                }
                if !loaded {
                    ProgressView().frame(maxWidth: .infinity).padding(.top, 40)
                } else if shown.isEmpty {
                    ContentUnavailableView(filter == .problems ? "No problems reported" : "All tested",
                                           systemImage: "checkmark.seal",
                                           description: Text(filter == .problems ? "Nothing is marked broken." : "Everything here has a verdict."))
                        .padding(.top, 30)
                } else {
                    ForEach(areas, id: \.self) { area in
                        SectionLabel(area)
                        Card(padding: 0) {
                            VStack(spacing: 0) {
                                let rows = shown.filter { $0.area == area }
                                ForEach(Array(rows.enumerated()), id: \.element.id) { i, f in
                                    FeatureRow(feature: f) { status, comment in
                                        Task { await save(f, status: status, comment: comment) }
                                    }
                                    if i < rows.count - 1 { Divider().padding(.leading, Metrics.gap) }
                                }
                            }
                        }
                    }
                }
            }
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Picker("Show", selection: $filter) {
                        ForEach(Filter.allCases) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 260)
                }
                ToolbarItem {
                    Button { Task { await load() } } label: { Label("Refresh", systemImage: "arrow.clockwise") }
                        .keyboardShortcut("r", modifiers: .command)
                }
            }
            .task { await load() }
        }
    }

    private var summary: some View {
        let tested = features.filter { $0.status != "untested" }.count
        let broken = features.filter { $0.status == "broken" }.count
        return Card {
            HStack(spacing: Metrics.gap) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("\(tested) of \(features.count) tried").font(.title2.weight(.semibold))
                    Text("Mark each feature once you've tried it. To report a problem by voice, say \u{201C}log an issue\u{201D} and what happened.")
                        .font(.callout).foregroundStyle(.secondary)
                }
                Spacer()
                if broken > 0 {
                    Label("\(broken) broken", systemImage: "xmark.octagon.fill").foregroundStyle(.red)
                }
                ProgressView(value: Double(tested), total: Double(max(features.count, 1)))
                    .frame(width: 140)
            }
        }
    }

    private func load() async {
        do {
            features = try await model.api.get("features")
            issues = (try? await model.api.get("issues")) ?? []
            error = nil
        } catch { self.error = "Couldn't load the feature list. Is Vox running?" }
        loaded = true
    }

    private func resolve(_ issue: LoggedIssue) async {
        issues.removeAll { $0.id == issue.id }
        do { try await model.api.patch("issues/\(issue.id)", ["status": .string("fixed")]) }
        catch { self.error = "Couldn't update that issue."; await load() }
    }

    private func save(_ f: Feature, status: String?, comment: String?) async {
        var body: [String: JSONValue] = [:]
        if let status { body["status"] = .string(status) }
        if let comment { body["comment"] = .string(comment) }
        if let i = features.firstIndex(where: { $0.id == f.id }) {
            if let status { features[i].status = status }
            if let comment { features[i].comment = comment }
        }
        do { try await model.api.patch("features/\(f.id)", body) }
        catch { self.error = "Couldn't save that. Is Vox running?"; await load() }
    }
}

private struct FeatureRow: View {
    var feature: Feature
    var onChange: (_ status: String?, _ comment: String?) -> Void
    @State private var comment = ""
    @State private var savedFlash = false
    @FocusState private var editing: Bool

    private var dirty: Bool { comment.trimmingCharacters(in: .whitespacesAndNewlines) != feature.comment }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 8) {
                        Text(feature.title).font(.body.weight(.medium))
                        checkedBadge
                    }
                    Text(feature.how).font(.callout).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 12)
                Menu {
                    ForEach(Feature.statuses, id: \.self) { s in
                        Button { onChange(s, nil) } label: { Label(Feature.title(s), systemImage: Feature.symbol(s)) }
                    }
                } label: {
                    Label(Feature.title(feature.status), systemImage: Feature.symbol(feature.status))
                        .foregroundStyle(Feature.color(feature.status))
                }
                .menuStyle(.borderlessButton)
                .fixedSize()
                .help("Your verdict")
            }
            HStack(alignment: .top, spacing: 8) {
                TextField("Notes: what happened, what felt off…", text: $comment, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(1...4)
                    .focused($editing)
                    .onSubmit { commit() }
                    .onChange(of: editing) { _, e in if !e { commit() } }
                // An explicit Save, so it's obvious notes are kept (Return and clicking away save too).
                if dirty {
                    Button("Save") { commit() }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.regular)
                        .keyboardShortcut(.return, modifiers: .command)
                        .help("Save note (Return or ⌘Return)")
                } else if savedFlash {
                    Label("Saved", systemImage: "checkmark.circle.fill")
                        .font(.callout).foregroundStyle(.green)
                        .transition(.opacity)
                }
            }
            .animation(.easeOut(duration: 0.2), value: dirty)
            .animation(.easeOut(duration: 0.2), value: savedFlash)
        }
        .padding(.horizontal, Metrics.gap).padding(.vertical, 12)
        .onAppear { comment = feature.comment }
        .onChange(of: feature.comment) { _, c in if !editing { comment = c } }
    }

    private var checkedBadge: some View {
        let ran = feature.checked == "claude"
        return Text(ran ? "Claude ran it" : "Code-checked only")
            .font(.caption2.weight(.medium))
            .foregroundStyle(ran ? Color.green : Color.secondary)
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background((ran ? Color.green : Color.secondary).opacity(0.12), in: Capsule())
            .help(ran ? "Claude used this for real in the app or engine." : "Only tests, API checks or screenshots so far. Nobody has used it for real.")
    }

    private func commit() {
        guard dirty else { return }
        onChange(nil, comment.trimmingCharacters(in: .whitespacesAndNewlines))
        savedFlash = true
        Task { try? await Task.sleep(for: .seconds(2)); savedFlash = false }
    }
}

private struct IssueRow: View {
    var issue: LoggedIssue
    var resolve: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "exclamationmark.bubble.fill").foregroundStyle(.orange).padding(.top, 2)
            VStack(alignment: .leading, spacing: 3) {
                Text(issue.text)
                Text([ISO8601.parse(issue.ts)?.friendly, issue.context?.app.map { "in \($0)" }]
                    .compactMap { $0 }.joined(separator: " · "))
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button("Mark Fixed", action: resolve).buttonStyle(.borderless)
        }
        .padding(.horizontal, Metrics.gap).padding(.vertical, 10)
    }
}

struct LoggedIssue: Codable, Identifiable, Hashable {
    struct Context: Codable, Hashable { var app: String? }
    var id: String
    var ts: String
    var text: String
    var status: String
    var context: Context?
}

struct Feature: Codable, Identifiable, Hashable {
    var id: String
    var area: String
    var title: String
    var how: String
    var checked: String
    var status: String
    var comment: String
    var updated: String?

    static let statuses = ["untested", "works", "partly", "broken"]

    static func title(_ s: String) -> String {
        switch s {
        case "works": "Works"
        case "partly": "Partly works"
        case "broken": "Broken"
        default: "Not tried"
        }
    }

    static func symbol(_ s: String) -> String {
        switch s {
        case "works": "checkmark.circle.fill"
        case "partly": "exclamationmark.circle.fill"
        case "broken": "xmark.octagon.fill"
        default: "circle.dashed"
        }
    }

    static func color(_ s: String) -> Color {
        switch s {
        case "works": .green
        case "partly": .orange
        case "broken": .red
        default: .secondary
        }
    }
}
