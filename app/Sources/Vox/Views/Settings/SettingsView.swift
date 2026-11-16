import ServiceManagement
import SwiftUI

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @AppStorage("settingsTab") private var tab: SettingsTab = .general

    var body: some View {
        TabView(selection: $tab) {
            ForEach(SettingsTab.allCases) { t in
                content(for: t)
                    .tabItem { Label(t.title, systemImage: t.symbol) }
                    .tag(t)
            }
        }
        .toggleStyle(.vox)
        .frame(width: 620, height: 600)
        .task { await model.reloadSettings() }
    }

    @ViewBuilder
    private func content(for t: SettingsTab) -> some View {
        switch t {
        case .permissions: PermissionsPane()
        case .advanced: AdvancedPane()
        case .general: CatalogPane(tab: t) { AppBehaviourSection() }
        case .connections: ConnectionsPane()
        case .listening: CatalogPane(tab: t) { HoldToTalkSection() }
        case .brains: CatalogPane(tab: t) { APIKeysSection() }
        default: CatalogPane(tab: t) { EmptyView() }
        }
    }
}

/// A tab rendered from the catalog, with optional app-side sections above it.
private struct CatalogPane<Header: View>: View {
    @Environment(AppModel.self) private var model
    var tab: SettingsTab
    @ViewBuilder var header: Header

    var body: some View {
        Form {
            if model.restartNeeded {
                Section {
                    HStack {
                        Label("Some changes take effect after Vox restarts.", systemImage: "arrow.clockwise.circle")
                        Spacer()
                        Button("Restart Now") { model.restartEngine() }
                    }
                }
            }
            header
            if model.engine.isRunning {
                ForEach(SettingsCatalog.tabs[tab] ?? [], id: \.title) { section in
                    let rows = section.items.filter { model.setting($0.key) != nil }
                    if !rows.isEmpty {
                        Section {
                            ForEach(rows, id: \.key) { spec in SettingRow(spec: spec) }
                        } header: {
                            Text(section.title)
                        } footer: {
                            if let f = section.footer { Text(f).foregroundStyle(.secondary) }
                        }
                    }
                }
            } else {
                Section { EngineNotice() }
            }
            if let err = model.settingsError {
                Section { Label(err, systemImage: "exclamationmark.triangle").foregroundStyle(.red) }
            }
        }
        .formStyle(.grouped)
    }
}

private struct EngineNotice: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow
    var body: some View {
        HStack {
            if model.engine.isStarting {
                Label("Vox is starting…", systemImage: "hourglass").foregroundStyle(.secondary)
                Spacer()
                ProgressView().controlSize(.small)
            } else if model.engine.state == .notInstalled {
                Label("Vox isn't set up yet.", systemImage: "wrench.and.screwdriver").foregroundStyle(.secondary)
                Spacer()
                Button("Open Setup…") { openWindow(id: "onboarding"); NSApp.activate() }
            } else {
                Label("Start Vox to change these settings.", systemImage: "power").foregroundStyle(.secondary)
                Spacer()
                Button("Start Vox") { model.boot() }
            }
        }
    }
}

/// One engine setting, drawn by type: switch, menu, or field.
struct SettingRow: View {
    @Environment(AppModel.self) private var model
    var spec: SettingSpec

    var body: some View {
        if let s = model.setting(spec.key) {
            control(s).help(s.help)
                .onChange(of: model.value(spec.key)) { old, new in
                    if old != .null && old != new && SettingsCatalog.needsRestart(s) { model.noteRestartNeeded() }
                }
        }
    }

    @ViewBuilder
    private func control(_ s: Setting) -> some View {
        switch s.type {
        case "toggle":
            Toggle(isOn: model.binding(bool: s.key)) { label }
        case "select":
            Picker(selection: selectBinding(s)) {
                ForEach(options(for: s), id: \.value) { o in Text(o.label).tag(o.value) }
            } label: { label }
        default:
            LabeledContent { NumberOrTextField(key: s.key) } label: { label }
        }
    }

    private var label: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(spec.label)
            if let c = spec.caption { Text(c).font(.caption).foregroundStyle(.secondary) }
            if let s = model.setting(spec.key), SettingsCatalog.needsRestart(s) {
                Text("Takes effect after Vox restarts.").font(.caption).foregroundStyle(.tertiary)
            }
        }
    }

    /// Choosing a provider also switches the model if the current one can't run there (Anthropic
    /// can't run DeepSeek), instead of leaving a mismatched pair that only fails at the next reply.
    private func selectBinding(_ s: Setting) -> Binding<String> {
        guard s.key.hasSuffix("_brain_provider") else { return model.binding(string: s.key) }
        let brain = String(s.key.dropLast("_provider".count))
        return Binding(get: { model.value(s.key).string }, set: { provider in
            model.set(s.key, .string(provider))
            let modelKey = "\(brain)_model"
            let current = model.value(modelKey).string
            let choices = provider == "chatgpt" ? model.chatgptModels : (model.setting(modelKey)?.options ?? []).map(\.value)
            if !Self.runs(current, on: provider), let pick = choices.first(where: { Self.runs($0, on: provider) }) {
                model.set(modelKey, .string(pick))
            }
        })
    }

    static func runs(_ modelID: String, on provider: String) -> Bool {
        switch provider {
        case "claude_sdk", "anthropic", "claude_cli": modelID.hasPrefix("claude")
        case "chatgpt": modelID.hasPrefix("gpt-") || modelID.range(of: #"^o\d"#, options: .regularExpression) != nil
        case "openai": !modelID.hasPrefix("claude") && !modelID.contains("/")
        case "local_ai": modelID.contains("/")
        default: true
        }
    }

    /// Model menus only offer models the chosen provider can run (plus the current value, so a
    /// custom model set in config still shows).
    private func options(for s: Setting) -> [SettingOption] {
        var opts = s.options ?? []
        let brain = s.key.hasPrefix("small_brain") ? "small_brain" : s.key.hasPrefix("big_brain") ? "big_brain" : nil
        if let brain, s.key.hasSuffix("_model") {
            let provider = model.value("\(brain)_provider").string
            if provider == "chatgpt" { opts = model.chatgptModels.map { SettingOption(value: $0, label: $0) } }
            opts = opts.filter { Self.runs($0.value, on: provider) }
            opts = opts.map { SettingOption(value: $0.value, label: BrainNames.model($0.value)) }
        }
        if s.key.hasSuffix("_provider") {
            opts = opts.map { SettingOption(value: $0.value, label: BrainNames.providerOption($0.value)) }
        }
        let current = s.value.string
        if !current.isEmpty && !opts.contains(where: { $0.value == current }) {
            opts.insert(SettingOption(value: current, label: BrainNames.model(current)), at: 0)
        }
        return opts
    }
}

/// Text/number settings commit on Return or when focus leaves, not on every keystroke.
private struct NumberOrTextField: View {
    @Environment(AppModel.self) private var model
    var key: String
    @State private var draft = ""
    @FocusState private var focused: Bool

    var body: some View {
        TextField("", text: $draft)
            .multilineTextAlignment(.trailing)
            .frame(width: 120)
            .focused($focused)
            .onSubmit(commit)
            .onChange(of: focused) { _, f in if !f { commit() } }
            .onAppear { draft = model.value(key).string }
            // Follow the real value (changed by voice, or restored after a refused edit) unless the
            // user is typing in this field. A field seeded once could later write a stale value back.
            .onChange(of: model.value(key)) { _, v in if !focused { draft = v.string } }
    }

    private func commit() {
        guard draft != model.value(key).string else { return }
        if let s = model.setting(key), s.type == "number", let n = Double(draft) {
            model.set(key, .number(n))
        } else {
            model.set(key, .string(draft))
        }
    }
}

// MARK: General: app behaviour (Vox.app's own settings, not the engine's)

private struct AppBehaviourSection: View {
    @AppStorage("quitEngineWithApp") private var quitEngine = true
    @State private var launchAtLogin = SMAppService.mainApp.status == .enabled
    @State private var loginError: String?

    var body: some View {
        Section("Vox app") {
            Toggle(isOn: $launchAtLogin) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Open Vox at login")
                    if let loginError { Text(loginError).font(.caption).foregroundStyle(.red) }
                }
            }
            .onChange(of: launchAtLogin) { _, on in
                do {
                    if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
                    loginError = nil
                } catch {
                    loginError = error.localizedDescription
                    launchAtLogin = SMAppService.mainApp.status == .enabled
                }
            }
            Toggle(isOn: $quitEngine) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Stop listening when Vox quits")
                    Text("Closing the window keeps Vox in the menu bar either way.").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }
}

private struct HoldToTalkSection: View {
    @State private var on = HoldToTalk.enabled

    var body: some View {
        Section {
            Toggle(isOn: $on) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Hold Right Option to talk")
                    Text("Hold the key, speak, let go. Works in any mode without a wake word, and letting go ends the turn instantly.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            .onChange(of: on) { _, v in HoldToTalk.enabled = v }
        } header: {
            Text("Hold to talk")
        }
    }
}

// MARK: Permissions

private struct PermissionsPane: View {
    @State private var perms = Permissions()
    @Environment(\.scenePhase) private var phase

    var body: some View {
        Form {
            Section {
                ForEach(Permissions.Kind.allCases) { k in PermissionRow(kind: k, perms: perms) }
            } footer: {
                Text("Vox asks macOS for these on its own behalf, and the speech engine it runs inherits them. After changing one in System Settings, restart Vox.")
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .task {   // System Settings sends no change notification; re-check while this tab is open
            while !Task.isCancelled {
                perms.refresh()
                try? await Task.sleep(for: .seconds(2))
            }
        }
        .onChange(of: phase) { _, _ in perms.refresh() }
    }
}

struct PermissionRow: View {
    var kind: Permissions.Kind
    var perms: Permissions

    var body: some View {
        let st = perms.status(kind)
        HStack(spacing: 12) {
            Image(systemName: kind.symbol)
                .font(.title3).frame(width: 28)
                .foregroundStyle(st == .granted ? Color.green : Color.secondary)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(kind.title)
                    if !kind.required { Text("Optional").font(.caption2).foregroundStyle(.secondary)
                        .padding(.horizontal, 5).padding(.vertical, 1).background(.quaternary, in: Capsule()) }
                }
                Text(kind.why).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if st == .granted {
                Label("Allowed", systemImage: "checkmark.circle.fill").labelStyle(.titleAndIcon)
                    .foregroundStyle(.green).font(.callout)
            } else {
                Button(st == .denied ? "Open Settings…" : "Allow…") { perms.request(kind) }
            }
        }
        .padding(.vertical, 2)
    }
}

// MARK: Advanced

private struct AdvancedPane: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow
    @Environment(\.dismissWindow) private var dismissWindow

    var body: some View {
        Form {
            Section("Engine") {
                LabeledContent("Status") {
                    Text(VoxPresence.from(engine: model.engine.state, status: model.engine.status).title)
                }
                LabeledContent("Runs from") {
                    Text(model.engine.location.kind == .checkout ? "Source checkout" : "Installed engine")
                        .help(model.engine.location.engineDir.path)
                }
                if let v = model.engine.status?.version { LabeledContent("Version", value: v) }
                HStack {
                    Button("Restart Engine") { model.restartEngine() }
                    if model.engine.isRunning {
                        Button("Stop Engine") { Task { await model.engine.stop() } }
                    } else if model.engine.isStarting {
                        ProgressView().controlSize(.small)
                        Text("Starting…").foregroundStyle(.secondary)
                    } else {
                        Button("Start Engine") { model.boot() }
                    }
                    Spacer()
                }
            }
            Section("Files") {
                HStack {
                    Button("Show Data Folder") { NSWorkspace.shared.open(model.engine.location.resolvedDataDir) }
                    Button("Open Log") { NSWorkspace.shared.open(model.engine.location.logFile) }
                    Button("Open Console Output") { NSWorkspace.shared.open(EngineSupervisor.consoleLogURL) }
                    Spacer()
                }
            }
            if model.engine.isRunning {
                ForEach(SettingsCatalog.tabs[.advanced] ?? [], id: \.title) { section in
                    Section(section.title) {
                        ForEach(section.items.filter { model.setting($0.key) != nil }, id: \.key) { SettingRow(spec: $0) }
                    }
                }
                let other = model.settings.filter { !SettingsCatalog.knownKeys.contains($0.key) }
                if !other.isEmpty {
                    Section {
                        ForEach(other) { s in SettingRow(spec: SettingSpec(key: s.key, label: s.label, caption: nil)) }
                    } header: { Text("Other") } footer: { Text("Settings this version of the app doesn't have a place for yet.") }
                }
            }
            Section("Setup") {
                HStack {
                    Button("Run Setup Again…") { openWindow(id: "onboarding"); dismissWindow(id: "main"); NSApp.activate() }
                    Spacer()
                }
            }
        }
        .formStyle(.grouped)
    }
}

/// API keys for the brains that need one. Saved in Vox's key store (data/secrets.db, owner-only) and used at once;
/// the values never come back from the engine, only whether each is set.
/// Spotify: link the user's account so Vox can find their playlists, search, and add songs.
/// Playback itself goes through the Spotify app and needs no link.
struct SpotifySection: View {
    @Environment(AppModel.self) private var model
    struct Status: Decodable { var clientId: Bool; var connected: Bool; var user: String; var redirectUri: String }
    @State private var status: Status?
    @State private var draft = ""
    @State private var error: String?
    @State private var waiting = false

    var body: some View {
        if model.engine.isRunning {
            Section {
                if let s = status, s.connected {
                    LabeledContent("Account") {
                        HStack(spacing: 8) {
                            Label(s.user.isEmpty ? "Linked" : s.user, systemImage: "checkmark.circle.fill")
                                .foregroundStyle(.green)
                            Button("Unlink") { Task { await disconnect() } }
                        }
                    }
                } else {
                    LabeledContent("Client ID") {
                        HStack(spacing: 8) {
                            TextField("", text: $draft, prompt: Text("Paste Client ID")).frame(width: 220)
                                .onSubmit { Task { await saveID() } }
                            Button("Save") { Task { await saveID() } }
                                .disabled(draft.trimmingCharacters(in: .whitespaces).isEmpty)
                        }
                    }
                    LabeledContent("Account") {
                        Button(waiting ? "Waiting for Spotify…" : "Connect Spotify…") { Task { await connect() } }
                            .disabled(!(status?.clientId ?? false) || waiting)
                    }
                    if let uri = status?.redirectUri {
                        LabeledContent("Redirect URI") {
                            HStack(spacing: 6) {
                                Text(uri).font(.callout.monospaced()).textSelection(.enabled)
                                Button("Copy", systemImage: "doc.on.doc") {
                                    NSPasteboard.general.clearContents()
                                    NSPasteboard.general.setString(uri, forType: .string)
                                }.labelStyle(.iconOnly).buttonStyle(.borderless)
                            }
                        }
                    }
                }
                if let error { Text(error).foregroundStyle(.red).font(.callout) }
            } header: {
                Text("Spotify")
            } footer: {
                Text(status?.connected == true
                     ? "Try \u{201C}play my film score playlist\u{201D} or \u{201C}add this song to my film score playlist\u{201D}."
                     : "\u{201C}What's playing?\u{201D} works already. To play playlists by name and add songs to them: at developer.spotify.com/dashboard create an app (any name), add the Redirect URI above, tick Web API, then paste its Client ID here and press Connect.")
                    .foregroundStyle(.secondary)
            }
            .task { await load() }
        }
    }

    private func load() async {
        status = try? await model.api.get("spotify")
        if draft.isEmpty, case .string(let v)? = model.setting("spotify_client_id")?.value { draft = v }
    }

    private func saveID() async {
        do { try await model.api.setSetting("spotify_client_id", .string(draft.trimmingCharacters(in: .whitespaces))); error = nil }
        catch { self.error = ErrorWords.message("Couldn't save the Client ID.", error) }
        await load()
    }

    private func connect() async {
        struct R: Decodable { var url: String }
        do {
            let r: R = try await model.api.send("spotify/connect", method: "POST", body: [String: JSONValue]())
            if let url = URL(string: r.url) { NSWorkspace.shared.open(url) }
            waiting = true
            error = nil
            for _ in 0..<90 {   // the login finishes in the browser; look for it for 3 minutes
                try? await Task.sleep(for: .seconds(2))
                await load()
                if status?.connected == true { break }
            }
            waiting = false
        } catch { self.error = ErrorWords.message("Couldn't start the Spotify login.", error) }
    }

    private func disconnect() async {
        try? await model.api.post("spotify/disconnect")
        await load()
    }
}

private struct APIKeysSection: View {
    @Environment(AppModel.self) private var model
    @State private var keys: [String: Bool] = [:]
    @State private var drafts: [String: String] = [:]
    @State private var error: String?
    @State private var removing: String?

    private static let names: [(env: String, label: String, help: String)] = [
        ("OPENAI_API_KEY", "OpenAI (ChatGPT)", "platform.openai.com → API keys"),
        ("ANTHROPIC_API_KEY", "Anthropic (Claude API)", "console.anthropic.com → API keys"),
        ("DEEPSEEK_API_KEY", "DeepSeek", "platform.deepseek.com → API keys"),
        ("COMPOSIO_API_KEY", "Composio (your apps: Google Calendar…)", "dashboard.composio.dev → Settings → API keys"),
    ]

    var body: some View {
        Section {
            ForEach(Self.names.filter { keys[$0.env] != nil }, id: \.env) { k in
                LabeledContent {
                    if keys[k.env] == true {
                        HStack(spacing: 8) {
                            Label("Saved", systemImage: "checkmark.circle.fill").foregroundStyle(.green).labelStyle(.titleAndIcon)
                            Button("Remove…") { removing = k.env }
                        }
                    } else {
                        HStack(spacing: 8) {
                            SecureField("", text: Binding(get: { drafts[k.env] ?? "" }, set: { drafts[k.env] = $0 }),
                                        prompt: Text("Paste key"))
                                .frame(width: 200)
                                .onSubmit { Task { await save(k.env, drafts[k.env] ?? "") } }
                            Button("Save") { Task { await save(k.env, drafts[k.env] ?? "") } }
                                .disabled((drafts[k.env] ?? "").trimmingCharacters(in: .whitespaces).isEmpty)
                        }
                    }
                } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(k.label)
                        Text(k.help).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        } header: {
            Text("API keys")
        } footer: {
            if let error { Text(error).foregroundStyle(.red) }
            else { Text("Only needed for the brains you pick below. Keys stay on this Mac.").foregroundStyle(.secondary) }
        }
        .task { await load() }
        .confirmationDialog("Remove this API key?", isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }),
                            titleVisibility: .visible) {
            Button("Remove Key", role: .destructive) { if let r = removing { Task { await save(r, "") } } }
        } message: {
            Text("Brains that use it stop working until you add a key again.")
        }
    }

    private func load() async {
        if let k: [String: Bool] = try? await model.api.get("secrets") { keys = k }
        await model.loadChatGPTModels()
    }

    private func save(_ name: String, _ value: String) async {
        do {
            try await model.api.post("secrets", ["name": .string(name), "value": .string(value.trimmingCharacters(in: .whitespacesAndNewlines))])
            drafts[name] = ""
            error = nil
            await load()
        } catch { self.error = ErrorWords.message("Couldn't save that key.", error) }
    }
}
