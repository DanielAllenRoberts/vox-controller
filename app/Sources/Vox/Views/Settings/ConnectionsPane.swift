import SwiftUI

/// Settings → Connections: the MCP servers Vox can use (Composio, Notion, Linear, a local server…)
/// and the Spotify link. Add one by URL or by the command that starts it; Test connects and lists its
/// tools. Vox's brain then reaches them for requests like "check my email" (APPS: in the router).
struct ConnectionsPane: View {
    @Environment(AppModel.self) private var model
    @State private var servers: [MCPServer] = []
    @State private var tests: [String: MCPTest] = [:]
    @State private var testing: Set<String> = []
    @State private var adding = false
    @State private var removing: MCPServer?
    @State private var error: String?

    var body: some View {
        Form {
            if model.engine.isRunning {
                Section {
                    if servers.isEmpty {
                        Text("No connections yet.").foregroundStyle(.secondary)
                    }
                    ForEach(servers) { s in row(s) }
                    Button("Add Connection…", systemImage: "plus") { adding = true }
                    if let error { Text(error).foregroundStyle(.red).font(.callout) }
                } header: {
                    Text("MCP servers")
                } footer: {
                    Text("Anything with an MCP server: Composio (Gmail, Calendar, Slack, Notion and hundreds more through one link), or a service's own server. Then just ask: \u{201C}any new email from Sam?\u{201D} Vox asks before it sends or changes anything.")
                        .foregroundStyle(.secondary)
                }
                SpotifySection()
            } else {
                EngineOffView()
            }
        }
        .formStyle(.grouped)
        .task { await load() }
        .sheet(isPresented: $adding) {
            AddConnectionSheet { body in Task { await add(body) } }
        }
        .confirmationDialog("Remove \u{201C}\(removing?.name ?? "")\u{201D}?", isPresented: .init(get: { removing != nil }, set: { if !$0 { removing = nil } })) {
            Button("Remove", role: .destructive) { if let s = removing { Task { await remove(s) } } }
        } message: {
            Text("Vox won't be able to use it any more. You can add it again later.")
        }
    }

    private func row(_ s: MCPServer) -> some View {
        LabeledContent {
            HStack(spacing: 10) {
                if testing.contains(s.name) {
                    ProgressView().controlSize(.small)
                } else if let t = tests[s.name] {
                    Label(t.ok ? "\(t.tools.count) tools" : "Failed", systemImage: t.ok ? "checkmark.circle.fill" : "xmark.octagon.fill")
                        .foregroundStyle(t.ok ? .green : .red)
                        .help(t.ok ? t.tools.prefix(20).joined(separator: ", ") : t.error)
                }
                Button("Test") { Task { await test(s) } }.disabled(testing.contains(s.name) || !s.enabled)
                Toggle("Enabled", isOn: Binding(get: { s.enabled }, set: { v in Task { await setEnabled(s, v) } }))
                    .labelsHidden().toggleStyle(.vox)
                Button("Remove", systemImage: "trash") { removing = s }.labelStyle(.iconOnly).buttonStyle(.borderless)
            }
        } label: {
            VStack(alignment: .leading, spacing: 2) {
                Text(s.name)
                Text(s.kind == "stdio" ? "\(s.command) \(s.args.joined(separator: " "))" : s.url)
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                if let t = tests[s.name], !t.ok, !t.error.isEmpty {
                    Text(t.error).font(.caption).foregroundStyle(.red).lineLimit(2)
                }
            }
        }
    }

    private func load() async {
        struct R: Decodable { var servers: [MCPServer] }
        if let r: R = try? await model.api.get("mcp") { servers = r.servers }
    }

    private func add(_ body: AddMCPBody) async {
        do {
            let s: MCPServer = try await model.api.send("mcp", method: "POST", body: body)
            error = nil
            await load()
            await test(s)
        } catch { self.error = ErrorWords.message("Couldn't add that connection.", error) }
    }

    private func test(_ s: MCPServer) async {
        testing.insert(s.name)
        defer { testing.remove(s.name) }
        do {
            tests[s.name] = try await model.api.send("mcp/\(s.name)/test", method: "POST", body: [String: JSONValue]())
        } catch {
            tests[s.name] = MCPTest(ok: false, status: "error", tools: [], error: ErrorWords.reason(error))
        }
    }

    private func setEnabled(_ s: MCPServer, _ on: Bool) async {
        try? await model.api.patch("mcp/\(s.name)", ["enabled": .bool(on)])
        await load()
    }

    private func remove(_ s: MCPServer) async {
        try? await model.api.delete("mcp/\(s.name)")
        tests[s.name] = nil
        await load()
    }
}

private struct AddConnectionSheet: View {
    var onAdd: (AddMCPBody) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var kind = "http"
    @State private var url = ""
    @State private var headerName = ""
    @State private var headerValue = ""
    @State private var command = ""
    @State private var args = ""
    @State private var envName = ""
    @State private var envValue = ""

    var body: some View {
        Form {
            Section {
                TextField("Name", text: $name, prompt: Text("composio"))
                Picker("Type", selection: $kind) {
                    Text("URL").tag("http")
                    Text("URL (SSE)").tag("sse")
                    Text("Command").tag("stdio")
                }
                .pickerStyle(.segmented)
            }
            if kind == "stdio" {
                Section {
                    TextField("Command", text: $command, prompt: Text("npx"))
                    TextField("Arguments", text: $args, prompt: Text("-y @modelcontextprotocol/server-filesystem ~/Documents"))
                    TextField("Environment variable", text: $envName, prompt: Text("Optional, e.g. API_KEY"))
                    if !envName.isEmpty { SecureField("Value", text: $envValue) }
                }
            } else {
                Section {
                    TextField("URL", text: $url, prompt: Text("https://…/mcp"))
                    TextField("Header", text: $headerName, prompt: Text("Optional, e.g. x-api-key or Authorization"))
                    if !headerName.isEmpty { SecureField("Header value", text: $headerValue) }
                } footer: {
                    Text("For Composio: dashboard.composio.dev → MCP → create a server with the apps you want, then copy its URL (and API key header if it shows one).")
                        .foregroundStyle(.secondary)
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 500)
        .fixedSize(horizontal: false, vertical: true)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button("Add") { onAdd(makeBody()); dismiss() }
                    .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty
                              || (kind == "stdio" ? command.trimmingCharacters(in: .whitespaces).isEmpty
                                                  : url.trimmingCharacters(in: .whitespaces).isEmpty))
            }
        }
    }

    private func makeBody() -> AddMCPBody {
        AddMCPBody(name: name.trimmingCharacters(in: .whitespaces), kind: kind,
                   url: url.trimmingCharacters(in: .whitespaces),
                   headers: headerName.isEmpty ? nil : [headerName.trimmingCharacters(in: .whitespaces): headerValue],
                   command: command.trimmingCharacters(in: .whitespaces), args: args,
                   env: envName.isEmpty ? nil : [envName.trimmingCharacters(in: .whitespaces): envValue])
    }
}

struct MCPServer: Codable, Identifiable, Hashable {
    var name: String
    var kind: String
    var url: String
    var command: String
    var args: [String]
    var headerNames: [String]
    var envNames: [String]
    var enabled: Bool
    var id: String { name }
}

struct MCPTest: Codable, Hashable {
    var ok: Bool
    var status: String
    var tools: [String]
    var error: String
}

struct AddMCPBody: Encodable {
    var name: String
    var kind: String
    var url: String
    var headers: [String: String]?
    var command: String
    var args: String
    var env: [String: String]?
}
