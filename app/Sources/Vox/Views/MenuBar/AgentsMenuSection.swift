import SwiftUI

/// Your running named Claude sessions in the menu bar panel: who's open, where, and the latest
/// thing each one said (spoken lines, silent notices, approval requests). Tap one to see its recent
/// updates. Sessions that have ended drop off. Hidden when no session has registered a name.
struct AgentsMenuSection: View {
    @Environment(AppModel.self) private var model
    @State private var agents: [LiveAgent] = []
    @State private var expanded: String?
    @State private var failed: [String: String] = [:]

    var body: some View {
        // A VStack, not a Group: a Group hands its modifiers to its children, and while the list is
        // still empty it has none, so the .task that fetches the list would never start.
        VStack(spacing: 0) {
            if !agents.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Agents").font(.caption).foregroundStyle(.secondary)
                    ScrollView {
                        VStack(spacing: 4) {
                            ForEach(agents) { a in row(a) }
                        }
                    }
                    .frame(maxHeight: 220)
                    .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .task { await follow() }
    }

    private func row(_ a: LiveAgent) -> some View {
        let open = expanded == a.name
        let latest = a.updates.first
        return VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: Self.symbol(latest?.kind))
                    .foregroundStyle(latest?.kind == "approval" ? Color.orange : Color.secondary)
                    .frame(width: 14)
                Text(a.name).font(.callout.weight(.semibold))
                Text(a.folder).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                Spacer(minLength: 0)
                if let latest { Text(Self.ago(latest.at)).font(.caption2).foregroundStyle(.tertiary) }
                Button { expanded = open ? nil : a.name } label: {
                    Image(systemName: "chevron.right").font(.caption2.weight(.semibold))
                        .rotationEffect(.degrees(open ? 90 : 0))
                        .frame(width: 18, height: 18).contentShape(Rectangle())
                }
                .buttonStyle(.plain).foregroundStyle(.secondary)
                .help(open ? "Hide updates" : "Show recent updates")
                .accessibilityLabel(open ? "Hide \(a.name)'s updates" : "Show \(a.name)'s updates")
            }
            if let why = failed[a.name] {
                Text(why).font(.caption2).foregroundStyle(.orange)
            }
            if open {
                if a.updates.isEmpty {
                    Text("Nothing said yet.").font(.caption).foregroundStyle(.secondary)
                }
                ForEach(a.updates) { u in
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Image(systemName: Self.symbol(u.kind)).font(.caption2).foregroundStyle(.secondary).frame(width: 14)
                        Text(u.text).font(.caption).textSelection(.enabled)
                        Spacer(minLength: 0)
                        Text(Self.ago(u.at)).font(.caption2).foregroundStyle(.tertiary)
                    }
                }
            } else {
                Text(latest?.text ?? "Nothing said yet.").font(.caption)
                    .foregroundStyle(latest == nil ? .secondary : .primary).lineLimit(2)
            }
        }
        .padding(8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(open ? 0.8 : 0.5), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .contentShape(Rectangle())
        .onTapGesture { Task { await switchTo(a.name) } }
        .help("Switch to \(a.name)'s terminal tab")
        .accessibilityElement(children: .contain)
        .accessibilityAddTraits(.isButton)
        .accessibilityHint("Switches to its terminal tab")
    }

    /// Bring the agent's terminal tab to the front. A failure shows under the row for a few seconds.
    private func switchTo(_ name: String) async {
        struct R: Decodable { var ok: Bool; var error: String }
        let r: R? = try? await model.api.send("agents/\(name)/focus", method: "POST", body: [String: JSONValue]())
        guard let r, !r.ok else { failed[name] = nil; return }
        failed[name] = r.error.isEmpty ? "Couldn't switch to \(name)." : r.error
        try? await Task.sleep(for: .seconds(5))
        failed[name] = nil
    }

    /// Refresh every few seconds while the panel is open; the task ends when it closes.
    private func follow() async {
        while !Task.isCancelled {
            if let r: AgentsResponse = try? await model.api.get("agents") {
                agents = r.agents
                if let e = expanded, !r.agents.contains(where: { $0.name == e }) { expanded = nil }
            }
            try? await Task.sleep(for: .seconds(3))
        }
    }

    private static func symbol(_ kind: String?) -> String {
        switch kind {
        case "approval": "hand.raised.fill"
        case "notice": "bell"
        case "spoke": "speaker.wave.2"
        default: "person.crop.circle"
        }
    }

    private static func ago(_ at: Double) -> String {
        let s = max(0, Int(Date().timeIntervalSince1970 - at))
        if s < 60 { return "now" }
        if s < 3600 { return "\(s / 60)m" }
        if s < 86400 { return "\(s / 3600)h" }
        return "\(s / 86400)d"
    }
}

private struct AgentsResponse: Decodable { var agents: [LiveAgent] }

struct LiveAgent: Decodable, Identifiable {
    struct Update: Decodable, Identifiable {
        var at: Double
        var kind: String
        var text: String
        var id: String { "\(at)-\(kind)" }
    }
    var name: String
    var folder: String
    var updates: [Update]
    var id: String { name }
}
