import SwiftUI

/// Organise → Agents: the coding agents Vox runs in your project folders (vox/team.py). Who's working
/// on what, their latest update and full transcript; message, stop, or approve what they're asking.
/// Updates live (GET /api/changes "team").
struct AgentsView: View {
    @Environment(AppModel.self) private var model
    @State private var data: TeamData?
    @State private var selected: String?
    @State private var log: [TeamEvent] = []
    @State private var draft = ""
    @State private var starting = false
    @State private var error: String?

    var body: some View {
        RequiresEngine {
            HStack(spacing: 0) {
                list.frame(width: 300)
                Divider()
                detail.frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button("New Agent", systemImage: "plus") { starting = true }.help("Start an agent in a project folder")
                }
            }
            .sheet(isPresented: $starting) {
                NewAgentSheet(root: data?.projectsRoot ?? "~/Repos") { folder, task, name in Task { await start(folder, task, name) } }
            }
            .task { await load() }
            .reloadsOnChange("team", api: model.api) { await load() }
        }
    }

    private var current: TeamAgent? { data?.agents.first { $0.name == selected } ?? data?.agents.first }

    @ViewBuilder private var list: some View {
        VStack(spacing: 0) {
            if let p = data?.pending {
                VStack(alignment: .leading, spacing: 8) {
                    Label("\(p.agent) wants to \(p.what)", systemImage: "hand.raised.fill")
                        .font(.callout).foregroundStyle(.orange)
                    HStack {
                        Button("Allow") { Task { await approve(true) } }.buttonStyle(.borderedProminent)
                        Button("Don't Allow") { Task { await approve(false) } }
                    }
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.orange.opacity(0.1))
            }
            if let agents = data?.agents, !agents.isEmpty {
                List(selection: $selected) {
                    ForEach(agents) { a in AgentRow(agent: a).tag(a.name) }
                }
                .listStyle(.sidebar)
            } else {
                ContentUnavailableView {
                    Label("No agents yet", systemImage: "person.3.sequence")
                } description: {
                    Text("Say \u{201C}start an agent in the getprice folder to fix the login bug\u{201D}, or press +.")
                } actions: {
                    Button("New Agent") { starting = true }
                }
            }
        }
    }

    @ViewBuilder private var detail: some View {
        if let a = current {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(a.name).font(.title2.weight(.semibold))
                        Text(a.folderShort).font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
                    }
                    Spacer()
                    if !a.external && (a.status == "working" || a.status == "waiting") {
                        Button("Stop", systemImage: "stop.circle") { Task { await post("team/\(a.name)/stop") } }
                    }
                    if !a.external {
                        Button("Remove", systemImage: "trash") { Task { await remove(a) } }
                            .labelStyle(.iconOnly).buttonStyle(.borderless).help("Remove this agent")
                    }
                }
                if !a.task.isEmpty {
                    LabeledContent("Task") { Text(a.task).textSelection(.enabled) }.font(.callout)
                }
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 8) {
                            ForEach(Array(log.enumerated()), id: \.offset) { i, e in EventRow(event: e).id(i) }
                        }
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .background(.background.secondary, in: RoundedRectangle(cornerRadius: Metrics.radius))
                    .onChange(of: log.count) { _, n in if n > 0 { proxy.scrollTo(n - 1, anchor: .bottom) } }
                }
                if a.external {
                    Label("This is one of your own Claude Code sessions. It reports to Vox, but Vox can't message it yet.", systemImage: "terminal")
                        .font(.callout).foregroundStyle(.secondary)
                } else {
                HStack {
                    TextField("Message \(a.name)…", text: $draft).textFieldStyle(.roundedBorder)
                        .onSubmit { Task { await send(a) } }
                    Button("Send") { Task { await send(a) } }.disabled(draft.trimmingCharacters(in: .whitespaces).isEmpty)
                }
                }
                if let error { Text(error).foregroundStyle(.red).font(.callout) }
            }
            .padding(Metrics.page)
            .task(id: a.name) { await loadLog(a.name) }
        } else {
            ContentUnavailableView("Pick an agent", systemImage: "person.3.sequence")
        }
    }

    private func load() async {
        data = try? await model.api.get("team")
        if let a = current { await loadLog(a.name) }
    }

    private func loadLog(_ name: String) async {
        struct R: Decodable { var events: [TeamEvent] }
        if let r: R = try? await model.api.get("team/\(name)/log") {   // appending(path:) encodes it
            log = r.events
        }
    }

    private func path(_ name: String) -> String { name }   // APIClient's appending(path:) percent-encodes

    private func start(_ folder: String, _ task: String, _ name: String) async {
        struct R: Decodable { var message: String }
        do {
            let r: R = try await model.api.send("team", method: "POST",
                                                body: ["folder": folder, "task": task, "name": name])
            error = r.message.hasPrefix("Started") || r.message.contains("pick this up") ? nil : r.message
        } catch { self.error = ErrorWords.message("Couldn't start the agent.", error) }
        await load()
    }

    private func send(_ a: TeamAgent) async {
        let text = draft.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }
        draft = ""
        struct R: Decodable { var message: String }
        _ = try? await model.api.send("team/\(path(a.name))/message", method: "POST", body: ["text": text]) as R
        await load()
    }

    private func approve(_ allow: Bool) async {
        struct R: Decodable { var message: String }
        _ = try? await model.api.send("team/approval", method: "POST", body: ["allow": JSONValue.bool(allow)]) as R
        await load()
    }

    private func post(_ p: String) async {
        try? await model.api.post(p)
        await load()
    }

    private func remove(_ a: TeamAgent) async {
        try? await model.api.delete("team/\(path(a.name))")
        selected = nil
        await load()
    }
}

private struct AgentRow: View {
    var agent: TeamAgent
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(agent.name).font(.body.weight(.medium))
                Spacer()
                StatusPill(status: agent.status)
            }
            Text(agent.lastUpdate.isEmpty ? agent.task : agent.lastUpdate)
                .font(.caption).foregroundStyle(.secondary).lineLimit(2)
        }
        .padding(.vertical, 3)
    }
}

private struct StatusPill: View {
    var status: String
    var body: some View {
        let (label, color): (String, Color) = switch status {
        case "working": ("Working", .accentColor)
        case "waiting": ("Needs you", .orange)
        case "error": ("Error", .red)
        case "stopped": ("Stopped", .secondary)
        case "terminal": ("Terminal", .teal)
        default: ("Idle", .green)
        }
        HStack(spacing: 4) {
            if status == "working" { ProgressView().controlSize(.mini) }
            Text(label)
        }
        .font(.caption.weight(.medium))
        .padding(.horizontal, 7).padding(.vertical, 2)
        .background(color.opacity(0.15), in: Capsule())
        .foregroundStyle(color)
    }
}

private struct EventRow: View {
    var event: TeamEvent
    var body: some View {
        let (symbol, tint): (String, Color) = switch event.kind {
        case "user": ("person.fill", .accentColor)
        case "tool": ("wrench.and.screwdriver", .secondary)
        case "approved": ("checkmark.shield", .green)
        case "denied": ("xmark.shield", .red)
        default: ("sparkles", .purple)
        }
        Label {
            Text(event.text).font(event.kind == "tool" ? .caption.monospaced() : .callout)
                .foregroundStyle(event.kind == "tool" ? .secondary : .primary)
                .textSelection(.enabled).lineLimit(event.kind == "tool" ? 2 : nil)
        } icon: {
            Image(systemName: symbol).foregroundStyle(tint)
        }
    }
}

private struct NewAgentSheet: View {
    var root: String
    var onStart: (String, String, String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var folder = ""
    @State private var task = ""
    @State private var name = ""

    var body: some View {
        Form {
            Section {
                TextField("Project folder", text: $folder, prompt: Text("getprice"))
                TextField("Name", text: $name, prompt: Text("Optional, e.g. GetPrice agent"))
                TextField("Task", text: $task, prompt: Text("Fix the login bug and run the tests"), axis: .vertical)
                    .lineLimit(3...6)
            } footer: {
                Text("Looked up by name under \(root). The agent reads that project's CLAUDE.md, edits files there and runs tests; anything else asks you first.")
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .frame(width: 480)
        .fixedSize(horizontal: false, vertical: true)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button("Start") { onStart(folder, task, name); dismiss() }
                    .disabled(folder.trimmingCharacters(in: .whitespaces).isEmpty || task.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
    }
}

struct TeamData: Codable, Hashable {
    var agents: [TeamAgent]
    var projectsRoot: String
    var pending: TeamPending?
}

struct TeamPending: Codable, Hashable { var agent: String; var what: String }

struct TeamAgent: Codable, Identifiable, Hashable {
    var name: String
    var folder: String
    var status: String
    var task: String
    var lastUpdate: String
    var external = false
    var id: String { name }
    var folderShort: String { folder.replacingOccurrences(of: NSHomeDirectory(), with: "~") }

    enum CodingKeys: String, CodingKey { case name, folder, status, task, external, lastUpdate = "last_update" }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        folder = (try? c.decode(String.self, forKey: .folder)) ?? ""
        status = (try? c.decode(String.self, forKey: .status)) ?? "idle"
        task = (try? c.decode(String.self, forKey: .task)) ?? ""
        lastUpdate = (try? c.decode(String.self, forKey: .lastUpdate)) ?? ""
        external = (try? c.decode(Bool.self, forKey: .external)) ?? false
    }
}

struct TeamEvent: Codable, Hashable { var ts: Double; var kind: String; var text: String }
